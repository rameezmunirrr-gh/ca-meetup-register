-- ROLLOUT STEP 4 (part 2): r2_02b + r2_03 + r2_04 + r2_05 + r2_06, in this order. Run AFTER part 1 and after the new pages are live.

-- >>>>>>>> r2_02b_cutover.sql
-- ============================================================================
-- Release 2, Step 1, piece 2b: CUT-OVER. Apply ONLY together with the new Tickets page.
-- Removes the old lookup that showed tickets (and QR secrets) for a Booking ID alone.
-- After this, the old Tickets page stops working until the new page is live.
-- ============================================================================
drop function if exists public.lookup_booking(text);

-- >>>>>>>> r2_03_private_transfer.sql
-- ============================================================================
-- Release 2, Step 1, piece 3: PRIVATE TRANSFER (database rules)
-- Written 17 Oct 2026. Tested on the scratch database before use.
-- REQUIRES r2_01_prep.sql and r2_02_lookup.sql first.
-- Apply together with the new pages. Transfers stay OFF until settings.transfers_open is set.
-- ============================================================================

-- 1. Transfer bookings: no screenshot, amount 0 allowed (registrations keep the old rules)
alter table public.bookings alter column screenshot_path drop not null;
alter table public.bookings drop constraint if exists bookings_amount_expected_check;
alter table public.bookings add constraint bookings_amount_expected_check
  check ((kind = 'registration' and amount_expected > 0) or (kind = 'transfer' and amount_expected >= 0));
alter table public.bookings drop constraint if exists bookings_screenshot_check;
alter table public.bookings add constraint bookings_screenshot_check
  check (kind = 'transfer' or screenshot_path is not null);

-- 2. The settings log may also hold transfer steps
alter table public.settings_log drop constraint if exists settings_log_area_check;
alter table public.settings_log add constraint settings_log_area_check
  check (area = any (array['settings'::text, 'staff'::text, 'transfer'::text]));

-- 3. Tables (one sale per seat; one row per buyer application)
create table if not exists public.transfers (
  id uuid primary key default gen_random_uuid(),
  kind text not null check (kind in ('private', 'public')),
  ticket_id uuid not null references public.tickets(id) on delete cascade,
  booking_id uuid not null references public.bookings(id) on delete cascade,
  seller_name text not null,
  seller_phone text not null check (seller_phone ~ '^[0-9]{10}$'),
  status text not null check (status in ('code_active', 'pending_admin', 'done', 'rejected', 'withdrawn', 'replaced')),
  code text,
  code_expires_at timestamptz,
  seller_call_confirmed_at timestamptz,
  seller_call_confirmed_by uuid references auth.users(id),
  decided_at timestamptz,
  decided_by uuid references auth.users(id),
  decision_note text check (decision_note is null or char_length(decision_note) <= 300),
  result_ticket_id uuid references public.tickets(id) on delete set null,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint transfers_private_has_code check (kind <> 'private' or (code is not null and code_expires_at is not null))
);
create unique index if not exists transfers_code_active_uq on public.transfers (code) where status = 'code_active';
create unique index if not exists transfers_one_open_per_ticket on public.transfers (ticket_id) where status in ('code_active', 'pending_admin');
create index if not exists transfers_booking_idx on public.transfers (booking_id);

create table if not exists public.transfer_buyers (
  id uuid primary key default gen_random_uuid(),
  transfer_id uuid not null references public.transfers(id) on delete cascade,
  submission_id uuid not null unique,
  booking_id uuid not null references public.bookings(id) on delete cascade,
  name text not null check (char_length(name) between 1 and 80),
  phone text not null check (phone ~ '^[0-9]{10}$'),
  email text not null check (char_length(email) between 5 and 120 and email ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
  location text not null check (location in ('In Bengaluru', 'Outside Bengaluru')),
  attendance text not null check (attendance in ('Surely', 'Most probably')),
  food text not null check (food in ('Veg', 'Non-veg')),
  consent_at timestamptz not null,
  status text not null default 'active' check (status in ('active', 'done', 'rejected', 'released')),
  created_at timestamptz not null default now()
);
create unique index if not exists transfer_buyers_one_per_transfer on public.transfer_buyers (transfer_id) where status in ('active', 'done');
create index if not exists transfer_buyers_booking_idx on public.transfer_buyers (booking_id);

-- admin-read-only, same pattern as the other tables
alter table public.transfers enable row level security;
alter table public.transfer_buyers enable row level security;
drop policy if exists admin_read_transfers on public.transfers;
create policy admin_read_transfers on public.transfers for select to authenticated using (is_admin());
drop policy if exists admin_read_transfer_buyers on public.transfer_buyers;
create policy admin_read_transfer_buyers on public.transfer_buyers for select to authenticated using (is_admin());
revoke all on table public.transfers, public.transfer_buyers from public, anon, authenticated, service_role;
grant select on table public.transfers, public.transfer_buyers to authenticated;

-- 4. Internal helpers (nobody outside the database can call these)
create or replace function public._actor() returns text language sql stable security definer set search_path to 'public' as $$
  select coalesce((select name from staff where user_id = auth.uid()),
                  case when auth.uid() is null then 'visitor' else 'unknown login' end) $$;

create or replace function public._tlog(p_field text, p_old text, p_new text) returns void
 language sql security definer set search_path to 'public' as $$
  insert into settings_log (changed_by, who, area, field, old_value, new_value)
  values (auth.uid(), _actor(), 'transfer', p_field, p_old, p_new) $$;

create or replace function public._new_transfer_code() returns text
 language plpgsql volatile set search_path to 'public' as $function$
declare alpha constant text := 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'; bytes bytea; c text; i int;
begin
  loop
    bytes := decode(replace(gen_random_uuid()::text, '-', ''), 'hex');
    c := '';
    for i in 0..5 loop c := c || substr(alpha, (get_byte(bytes, i) % 32) + 1, 1); end loop;
    exit when not exists (select 1 from transfers where code = c and status = 'code_active');
  end loop;
  return c;
end $function$;

-- finds the seller's ticket only if Booking ID + ticket number + the phone of THAT ticket all match
create or replace function public._find_seller_ticket(p_code text, p_ticket text, p_phone text) returns uuid
 language plpgsql stable security definer set search_path to 'public' as $function$
declare c text; ph text; k text; n int; v uuid;
begin
  c  := replace(replace(replace(upper(coalesce(p_code, '')), 'O', '0'), ' ', ''), '-', '');
  ph := replace(replace(coalesce(p_phone, ''), ' ', ''), '-', '');
  if length(c) <> 8 or ph !~ '^[0-9]{10}$' then return null; end if;
  select pt.kind, pt.no into k, n from _parse_ticket(p_ticket) pt;
  if k is null then return null; end if;
  select t.id into v from tickets t join bookings b on b.id = t.booking_id
   where b.booking_code = c and t.phone = ph   -- a ticket received by transfer can be sold on too
     and ((k = 'guest' and t.kind = 'guest' and t.ticket_no = n)
       or (k = 'coordinator' and t.kind = 'coordinator' and t.coord_no = n));
  return v;
end $function$;

-- closes every open transfer of a seller booking (used when an admin rejects or reopens that booking)
create or replace function public._close_open_transfers(p_booking uuid, p_reason text) returns void
 language plpgsql security definer set search_path to 'public' as $function$
declare x record;
begin
  for x in select id, status from transfers where booking_id = p_booking and status in ('code_active', 'pending_admin') for update loop
    update transfers set status = 'withdrawn', decision_note = left(p_reason, 300), decided_at = now(),
           decided_by = auth.uid(), updated_at = now() where id = x.id;
    update bookings set status = 'rejected', reviewed_by = auth.uid(), reviewed_at = now(), reviewed_via = 'admin'
     where id in (select booking_id from transfer_buyers where transfer_id = x.id and status = 'active');
    update transfer_buyers set status = 'released' where transfer_id = x.id and status = 'active';
    perform _tlog('private transfer closed automatically', x.status, left(x.id::text, 8) || ': ' || p_reason);
  end loop;
end $function$;

-- 5. Seller side (visitors)
create or replace function public.private_sell(p_booking_code text, p_ticket text, p_phone text) returns jsonb
 language plpgsql security definer set search_path to 'public' as $function$
declare s settings%rowtype; tid uuid; t tickets%rowtype; b bookings%rowtype; x transfers%rowtype; code text; lbl text;
begin
  select * into s from settings where id = 1;
  if not s.transfers_open then return jsonb_build_object('ok', false, 'error', 'TRANSFERS_CLOSED'); end if;
  if s.transfer_cutoff_at is not null and now() > s.transfer_cutoff_at then
    return jsonb_build_object('ok', false, 'error', 'CUTOFF_PASSED'); end if;
  tid := _find_seller_ticket(p_booking_code, p_ticket, p_phone);
  if tid is null then return jsonb_build_object('ok', false, 'error', 'MISMATCH'); end if;
  select * into t from tickets where id = tid for update;
  select * into b from bookings where id = t.booking_id;
  if t.transferred_out_at is not null then return jsonb_build_object('ok', false, 'error', 'ALREADY_TRANSFERRED'); end if;
  if b.status <> 'paid' or t.ticket_no is null then return jsonb_build_object('ok', false, 'error', 'NOT_CONFIRMED'); end if;
  if t.kind <> 'guest' then return jsonb_build_object('ok', false, 'error', 'COORDINATOR'); end if;
  if t.checked_in_at is not null then return jsonb_build_object('ok', false, 'error', 'ALREADY_CHECKED_IN'); end if;
  lbl := _ticket_label(t.kind, t.ticket_no, t.coord_no);

  select * into x from transfers where ticket_id = t.id and status in ('code_active', 'pending_admin') for update;
  if found then
    if x.status = 'pending_admin' then return jsonb_build_object('ok', false, 'error', 'ALREADY_PENDING'); end if;
    update transfers set status = 'replaced', updated_at = now() where id = x.id;
    perform _tlog('private transfer: code replaced', lbl, left(x.id::text, 8));
  end if;
  begin
    code := _new_transfer_code();
    insert into transfers (kind, ticket_id, booking_id, seller_name, seller_phone, status, code, code_expires_at)
    values ('private', t.id, b.id, t.name, t.phone, 'code_active', code, now() + make_interval(hours => s.private_code_hours))
    returning * into x;
  exception when unique_violation then
    return jsonb_build_object('ok', false, 'error', 'TRY_AGAIN');
  end;
  perform _tlog('private transfer: code created', null, lbl || ' (' || left(x.id::text, 8) || ')');
  return jsonb_build_object('ok', true, 'code', x.code, 'expires_at', x.code_expires_at,
                            'hours', s.private_code_hours, 'ticket_label', lbl);
end $function$;

create or replace function public.transfer_status(p_booking_code text, p_phone text) returns jsonb
 language plpgsql stable security definer set search_path to 'public' as $function$
declare c text; ph text; b bookings%rowtype; res jsonb;
begin
  c  := replace(replace(replace(upper(coalesce(p_booking_code, '')), 'O', '0'), ' ', ''), '-', '');
  ph := replace(replace(coalesce(p_phone, ''), ' ', ''), '-', '');
  if length(c) <> 8 or ph !~ '^[0-9]{10}$' then return jsonb_build_object('found', false); end if;
  select * into b from bookings where booking_code = c;
  if not found or not exists (select 1 from tickets where booking_id = b.id and phone = ph) then
    return jsonb_build_object('found', false); end if;
  select coalesce(jsonb_agg(r.j order by r.created_at desc), '[]'::jsonb) into res from (
    select x.created_at, jsonb_build_object(
        'ticket_label', _ticket_label(tk.kind, tk.ticket_no, tk.coord_no), 'mode', x.kind,
        'status', case when x.status = 'code_active' and x.code_expires_at <= now() then 'expired' else x.status end,
        'code', case when x.status = 'code_active' and x.code_expires_at > now() then x.code end,
        'expires_at', case when x.status = 'code_active' then x.code_expires_at end,
        'buyer_name', case when x.status in ('pending_admin', 'done')
                           then (select bu.name from transfer_buyers bu where bu.transfer_id = x.id and bu.status in ('active', 'done') limit 1) end,
        'created_at', x.created_at) as j
      from transfers x join tickets tk on tk.id = x.ticket_id
     where x.booking_id = b.id and x.seller_phone = ph
     order by x.created_at desc limit 10) r;
  return jsonb_build_object('found', true, 'transfers', res);
end $function$;

create or replace function public.transfer_cancel(p_booking_code text, p_ticket text, p_phone text) returns jsonb
 language plpgsql security definer set search_path to 'public' as $function$
declare tid uuid; x transfers%rowtype;
begin
  tid := _find_seller_ticket(p_booking_code, p_ticket, p_phone);
  if tid is null then return jsonb_build_object('ok', false, 'error', 'MISMATCH'); end if;
  select * into x from transfers where ticket_id = tid and status in ('code_active', 'pending_admin') for update;
  if not found then return jsonb_build_object('ok', false, 'error', 'NOTHING_TO_CANCEL'); end if;
  if x.status = 'pending_admin' then return jsonb_build_object('ok', false, 'error', 'CONTACT_ADMIN'); end if;
  update transfers set status = 'withdrawn', updated_at = now() where id = x.id;
  perform _tlog('private transfer: cancelled by seller', 'code_active', left(x.id::text, 8));
  return jsonb_build_object('ok', true);
end $function$;

-- 6. Buyer side (visitors)
create or replace function public.transfer_open(p_code text) returns jsonb
 language plpgsql stable security definer set search_path to 'public' as $function$
declare s settings%rowtype; c text; x transfers%rowtype; t tickets%rowtype; b bookings%rowtype;
begin
  select * into s from settings where id = 1;
  if not s.transfers_open then return jsonb_build_object('ok', false, 'error', 'TRANSFERS_CLOSED'); end if;
  if s.transfer_cutoff_at is not null and now() > s.transfer_cutoff_at then
    return jsonb_build_object('ok', false, 'error', 'CUTOFF_PASSED'); end if;
  c := upper(regexp_replace(coalesce(p_code, ''), '[\s-]', '', 'g'));
  if c !~ '^[A-Z2-9]{6}$' then return jsonb_build_object('ok', false, 'error', 'INVALID_CODE'); end if;
  select * into x from transfers where code = c and status = 'code_active' and code_expires_at > now();
  if not found then return jsonb_build_object('ok', false, 'error', 'INVALID_CODE'); end if;
  select * into t from tickets where id = x.ticket_id;
  select * into b from bookings where id = t.booking_id;
  if t.transferred_out_at is not null or t.checked_in_at is not null or b.status <> 'paid' then
    return jsonb_build_object('ok', false, 'error', 'NOT_AVAILABLE'); end if;
  return jsonb_build_object('ok', true, 'mode', x.kind, 'seller_name', t.name, 'expires_at', x.code_expires_at,
                            'food_locked', s.transfer_food_locked,
                            'food', case when s.transfer_food_locked then t.food end);
end $function$;

create or replace function public.transfer_submit(p_code text, p_submission_id uuid, p_buyer jsonb) returns jsonb
 language plpgsql security definer set search_path to 'public' as $function$
declare s settings%rowtype; c text; x transfers%rowtype; t tickets%rowtype; sb bookings%rowtype; bu transfer_buyers%rowtype;
        bk bookings%rowtype; bcode text; v_food text; v_email text; v_name text;
begin
  if p_submission_id is null then return jsonb_build_object('ok', false, 'error', 'INVALID_DATA'); end if;
  -- the same submission again: give back the same answer (a retry after a bad connection)
  select * into bu from transfer_buyers where submission_id = p_submission_id;
  if found then
    select * into bk from bookings where id = bu.booking_id;
    return jsonb_build_object('ok', true, 'booking_code', bk.booking_code, 'status', bk.status, 'replay', true);
  end if;

  select * into s from settings where id = 1;
  if not s.transfers_open then return jsonb_build_object('ok', false, 'error', 'TRANSFERS_CLOSED'); end if;
  if s.transfer_cutoff_at is not null and now() > s.transfer_cutoff_at then
    return jsonb_build_object('ok', false, 'error', 'CUTOFF_PASSED'); end if;
  c := upper(regexp_replace(coalesce(p_code, ''), '[\s-]', '', 'g'));
  if c !~ '^[A-Z2-9]{6}$' then return jsonb_build_object('ok', false, 'error', 'INVALID_CODE'); end if;

  if p_buyer is null or jsonb_typeof(p_buyer) <> 'object' then return jsonb_build_object('ok', false, 'error', 'INVALID_DATA'); end if;
  v_name := trim(coalesce(p_buyer->>'name', ''));
  v_email := lower(trim(coalesce(p_buyer->>'email', '')));
  if length(v_name) not between 1 and 80 then return jsonb_build_object('ok', false, 'error', 'INVALID_NAME'); end if;
  if coalesce(p_buyer->>'phone', '') !~ '^[0-9]{10}$' then return jsonb_build_object('ok', false, 'error', 'INVALID_PHONE'); end if;
  if length(v_email) not between 5 and 120 or v_email !~ '^[^@\s]+@[^@\s]+\.[^@\s]+$' then return jsonb_build_object('ok', false, 'error', 'INVALID_EMAIL'); end if;
  if coalesce(p_buyer->>'loc', '') not in ('In Bengaluru', 'Outside Bengaluru') then return jsonb_build_object('ok', false, 'error', 'INVALID_LOCATION'); end if;
  if coalesce(p_buyer->>'att', '') not in ('Surely', 'Most probably') then return jsonb_build_object('ok', false, 'error', 'INVALID_ATTENDANCE'); end if;
  if not s.transfer_food_locked and coalesce(p_buyer->>'food', '') not in ('Veg', 'Non-veg') then return jsonb_build_object('ok', false, 'error', 'INVALID_FOOD'); end if;
  if coalesce(p_buyer->>'consent', '') <> 'true' then return jsonb_build_object('ok', false, 'error', 'INVALID_CONSENT'); end if;

  -- first valid submission wins
  select * into x from transfers where code = c and status = 'code_active' and code_expires_at > now() for update;
  if not found then return jsonb_build_object('ok', false, 'error', 'INVALID_CODE'); end if;
  select * into t from tickets where id = x.ticket_id for update;
  select * into sb from bookings where id = t.booking_id;
  if t.transferred_out_at is not null or t.checked_in_at is not null or sb.status <> 'paid' then
    return jsonb_build_object('ok', false, 'error', 'NOT_AVAILABLE'); end if;
  v_food := case when s.transfer_food_locked then t.food else p_buyer->>'food' end;

  begin
    loop
      bcode := upper(substr(replace(gen_random_uuid()::text, '-', ''), 1, 8));
      exit when not exists (select 1 from bookings where booking_code = bcode);
    end loop;
    insert into bookings (booking_code, submission_id, people_count, amount_expected, screenshot_path, kind)
    values (bcode, p_submission_id, 1, 0, null, 'transfer') returning * into bk;
    insert into transfer_buyers (transfer_id, submission_id, booking_id, name, phone, email, location, attendance, food, consent_at)
    values (x.id, p_submission_id, bk.id, v_name, p_buyer->>'phone', v_email, p_buyer->>'loc', p_buyer->>'att', v_food, now());
  exception when unique_violation then
    return jsonb_build_object('ok', false, 'error', 'TRY_AGAIN');
  end;
  update transfers set status = 'pending_admin', updated_at = now() where id = x.id;
  perform _tlog('private transfer: buyer submitted', 'code_active', _ticket_label(t.kind, t.ticket_no, t.coord_no) || ' (' || left(x.id::text, 8) || ')');
  return jsonb_build_object('ok', true, 'mode', x.kind, 'booking_code', bk.booking_code, 'status', 'pending',
                            'seller_name', t.name, 'food', v_food);
end $function$;

-- 7. Ticket lookup: now also serves the buyer's transfer booking (Booking ID + the BUYER's phone)
create or replace function public.lookup_tickets(p_code text, p_phone text)
 returns jsonb
 language plpgsql
 stable security definer
 set search_path to 'public'
as $function$
declare b bookings%rowtype; c text; ph text; tk jsonb; bu transfer_buyers%rowtype;
begin
  c  := replace(replace(replace(upper(coalesce(p_code, '')), 'O', '0'), ' ', ''), '-', '');
  ph := replace(replace(coalesce(p_phone, ''), ' ', ''), '-', '');
  if length(c) <> 8 or ph !~ '^[0-9]{10}$' then return jsonb_build_object('found', false); end if;

  select * into b from bookings where booking_code = c;
  if not found then return jsonb_build_object('found', false); end if;
  if b.kind = 'transfer' then
    select * into bu from transfer_buyers where booking_id = b.id and phone = ph;
    if not found then return jsonb_build_object('found', false); end if;
  end if;

  select jsonb_agg(jsonb_build_object(
           'ticket_no', t.ticket_no, 'kind', t.kind, 'coord_no', t.coord_no,
           'label', _ticket_label(t.kind, t.ticket_no, t.coord_no),
           'secret', case when b.status = 'paid' and t.transferred_out_at is null then t.secret else null end,
           'transferred', (t.transferred_out_at is not null),
           'name', t.name, 'location', t.location, 'attendance', t.attendance, 'food', t.food)
         order by t.reg_seq)
    into tk
    from tickets t
   where t.booking_id = b.id and t.phone = ph;

  if tk is null then
    -- a transfer booking that is waiting for the admin (or was rejected) has no ticket yet
    if b.kind = 'transfer' then
      return jsonb_build_object('found', true, 'kind', 'transfer', 'booking_code', b.booking_code, 'status', b.status,
                                'people_count', 1, 'amount_expected', 0, 'name', bu.name, 'tickets', '[]'::jsonb);
    end if;
    return jsonb_build_object('found', false);
  end if;

  return jsonb_build_object('found', true, 'kind', b.kind, 'booking_code', b.booking_code, 'status', b.status,
                            'people_count', b.people_count, 'amount_expected', b.amount_expected,
                            'tickets', tk);
end $function$;

-- 8. Admin side
create or replace function public.admin_transfer_confirm_call(p_transfer uuid, p_confirmed boolean default true) returns void
 language plpgsql security definer set search_path to 'public' as $function$
declare x transfers%rowtype;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  select * into x from transfers where id = p_transfer for update;
  if not found then raise exception 'INVALID_TRANSFER'; end if;
  if x.status <> 'pending_admin' then raise exception 'NOT_PENDING'; end if;
  if p_confirmed then
    update transfers set seller_call_confirmed_at = now(), seller_call_confirmed_by = auth.uid(), updated_at = now() where id = x.id;
  else
    update transfers set seller_call_confirmed_at = null, seller_call_confirmed_by = null, updated_at = now() where id = x.id;
  end if;
  perform _tlog('private transfer: seller phone call ' || case when p_confirmed then 'confirmed' else 'tick removed' end, null, left(x.id::text, 8));
end $function$;

create or replace function public.admin_transfer_approve(p_transfer uuid) returns jsonb
 language plpgsql security definer set search_path to 'public' as $function$
declare x transfers%rowtype; t tickets%rowtype; sb bookings%rowtype; bu transfer_buyers%rowtype; bk bookings%rowtype; nt tickets%rowtype; old_lbl text;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  perform 1 from settings where id = 1 for update;                       -- same lock order as set_booking_status
  select * into x from transfers where id = p_transfer for update;
  if not found then raise exception 'INVALID_TRANSFER'; end if;
  if x.status <> 'pending_admin' then raise exception 'NOT_PENDING'; end if;
  if x.kind = 'private' and x.seller_call_confirmed_at is null then raise exception 'CALL_NOT_CONFIRMED'; end if;
  select * into t from tickets where id = x.ticket_id for update;
  select * into sb from bookings where id = t.booking_id for update;
  if t.transferred_out_at is not null then raise exception 'SELLER_ALREADY_TRANSFERRED'; end if;
  if t.checked_in_at is not null then raise exception 'SELLER_CHECKED_IN'; end if;
  if sb.status <> 'paid' or t.kind <> 'guest' or t.ticket_no is null then raise exception 'SELLER_TICKET_INVALID'; end if;
  select * into bu from transfer_buyers where transfer_id = x.id and status = 'active' for update;
  if not found then raise exception 'NO_BUYER'; end if;
  select * into bk from bookings where id = bu.booking_id for update;
  if bk.kind <> 'transfer' or bk.status <> 'pending' then raise exception 'BUYER_BOOKING_INVALID'; end if;
  old_lbl := _ticket_label(t.kind, t.ticket_no, t.coord_no);

  -- the swap: the buyer gets a NEW ticket, the seller's ticket is cancelled (its number is retired for good)
  insert into tickets (secret, booking_id, name, phone, location, attendance, food, kind, transferred_from)
  values (substr(replace(gen_random_uuid()::text, '-', ''), 1, 12), bk.id, bu.name, bu.phone,
          bu.location, bu.attendance, bu.food, 'guest', t.id)
  returning * into nt;
  insert into ticket_emails (ticket_id, email) values (nt.id, bu.email);   -- email stays in the admin-only table
  update tickets set transferred_out_at = now() where id = t.id;
  update bookings set status = 'paid', reviewed_by = auth.uid(), reviewed_at = now(), reviewed_via = 'admin' where id = bk.id;
  perform _assign_numbers(bk.id);                                         -- the normal numbering rule gives the next guest number
  select * into nt from tickets where id = nt.id;
  update transfers set status = 'done', decided_at = now(), decided_by = auth.uid(), result_ticket_id = nt.id, updated_at = now() where id = x.id;
  update transfer_buyers set status = 'done' where id = bu.id;
  perform _tlog('private transfer: APPROVED', old_lbl, _ticket_label(nt.kind, nt.ticket_no, nt.coord_no) || ' (' || left(x.id::text, 8) || ')');
  return jsonb_build_object('new_label', _ticket_label(nt.kind, nt.ticket_no, nt.coord_no),
                            'old_label', old_lbl, 'booking_code', bk.booking_code);
end $function$;

create or replace function public.admin_transfer_reject(p_transfer uuid, p_note text default null) returns void
 language plpgsql security definer set search_path to 'public' as $function$
declare x transfers%rowtype; note text;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  select * into x from transfers where id = p_transfer for update;
  if not found then raise exception 'INVALID_TRANSFER'; end if;
  if x.status not in ('code_active', 'pending_admin') then raise exception 'NOT_PENDING'; end if;
  note := nullif(btrim(coalesce(p_note, '')), '');
  if note is not null and char_length(note) > 300 then raise exception 'INVALID_NOTE'; end if;
  update transfers set status = 'rejected', decision_note = note, decided_at = now(), decided_by = auth.uid(), updated_at = now() where id = x.id;
  update bookings set status = 'rejected', reviewed_by = auth.uid(), reviewed_at = now(), reviewed_via = 'admin'
   where id in (select booking_id from transfer_buyers where transfer_id = x.id and status = 'active');
  update transfer_buyers set status = 'rejected' where transfer_id = x.id and status = 'active';
  perform _tlog('private transfer: REJECTED', x.status, left(x.id::text, 8) || coalesce(': ' || note, ''));
end $function$;

-- 9. Existing functions, changed only where needed (generated from the real snapshot)
CREATE OR REPLACE FUNCTION public.set_booking_status(p_booking uuid, p_status text)
 RETURNS void
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  if p_status not in ('pending','paid','rejected') then raise exception 'INVALID_STATUS'; end if;
  perform 1 from settings where id = 1 for update;
  -- transfer bookings are moved only by the transfer tools (they hold no ticket until approved)
  if exists (select 1 from bookings where id = p_booking and kind = 'transfer') then raise exception 'USE_TRANSFER_TOOLS'; end if;
  update bookings set status = p_status, reviewed_by = auth.uid(), reviewed_at = now(), reviewed_via = 'admin'
  where id = p_booking;
  if p_status = 'paid' then perform _assign_numbers(p_booking);
  else perform _close_open_transfers(p_booking, 'seller booking was set to ' || p_status); end if;
end $function$;

CREATE OR REPLACE FUNCTION public.admit_ticket(p_ticket_no integer DEFAULT NULL::integer, p_secret text DEFAULT NULL::text, p_approve boolean DEFAULT false, p_coord boolean DEFAULT false, p_id uuid DEFAULT NULL::uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare t tickets%rowtype; b bookings%rowtype; info jsonb; who text; nt tickets%rowtype; nx tickets%rowtype; hops int;
begin
  if not is_staff() then raise exception 'NOT_ALLOWED'; end if;
  if p_approve then perform 1 from settings where id = 1 for update; end if;

  if p_id is not null then
    select * into t from tickets where id = p_id for update;
  elsif p_coord then
    select * into t from tickets where coord_no = p_ticket_no and kind = 'coordinator' for update;
    if not found then
      -- maybe a coordinator number that was cancelled (person is a guest again)
      select * into t from tickets where prev_coord_no = p_ticket_no for update;
      if found then
        return jsonb_build_object('result', 'cancelled', 'name', t.name,
          'label', coalesce(_ticket_label(t.kind, t.ticket_no, t.coord_no), 'not numbered yet'),
          'old_label', _ticket_label('coordinator', null, t.prev_coord_no));
      end if;
    end if;
  else
    select * into t from tickets where ticket_no = p_ticket_no for update;
  end if;
  if not found then return jsonb_build_object('result', 'invalid'); end if;

  if t.transferred_out_at is not null then
    -- this ticket was transferred away: its QR is cancelled; show who holds the seat now (follow the chain)
    nt := t; hops := 0;
    while nt.transferred_out_at is not null and hops < 20 loop
      select * into nx from tickets where transferred_from = nt.id;
      exit when not found;
      nt := nx; hops := hops + 1;
    end loop;
    return jsonb_build_object('result', 'cancelled', 'name', nt.name,
      'label', coalesce(_ticket_label(nt.kind, nt.ticket_no, nt.coord_no), 'not numbered yet'),
      'old_label', _ticket_label(t.kind, t.ticket_no, t.coord_no));
  end if;

  if p_id is null and t.kind = 'coordinator' and not p_coord then
    return jsonb_build_object('result', 'cancelled', 'name', t.name,
      'label', _ticket_label(t.kind, t.ticket_no, t.coord_no),
      'old_label', _ticket_label('guest', t.ticket_no, null));
  end if;
  if p_secret is not null and t.secret <> p_secret then
    return jsonb_build_object('result', 'invalid'); end if;

  select * into b from bookings where id = t.booking_id for update;

  if b.status = 'pending' and p_approve then
    update bookings set status = 'paid', reviewed_by = auth.uid(), reviewed_at = now(), reviewed_via = 'gate' where id = b.id;
    perform _assign_numbers(b.id);
    select * into t from tickets where id = t.id;
    b.status := 'paid';
  end if;

  info := jsonb_build_object('id', t.id, 'ticket_no', t.ticket_no, 'kind', t.kind,
    'label', _ticket_label(t.kind, t.ticket_no, t.coord_no),
    'name', t.name, 'food', t.food,
    'booking_code', b.booking_code, 'people_count', b.people_count,
    'amount_expected', b.amount_expected, 'screenshot_path', b.screenshot_path);

  if b.status = 'rejected' then return info || jsonb_build_object('result', 'rejected'); end if;
  if b.status = 'pending' then return info || jsonb_build_object('result', 'pending'); end if;
  if t.checked_in_at is not null then
    select name into who from staff where user_id = t.checked_in_by;
    return info || jsonb_build_object('result', 'already_scanned', 'checked_in_at', t.checked_in_at, 'checked_in_by', who);
  end if;
  update tickets set checked_in_at = now(), checked_in_by = auth.uid() where id = t.id;
  return info || jsonb_build_object('result', 'ok');
end $function$;

-- 10. Who may call what
revoke all on function public._actor(), public._tlog(text, text, text), public._new_transfer_code(),
  public._find_seller_ticket(text, text, text), public._close_open_transfers(uuid, text) from public, anon, authenticated, service_role;
revoke all on function public.private_sell(text, text, text), public.transfer_status(text, text), public.transfer_cancel(text, text, text),
  public.transfer_open(text), public.transfer_submit(text, uuid, jsonb) from public;
grant execute on function public.private_sell(text, text, text), public.transfer_status(text, text), public.transfer_cancel(text, text, text),
  public.transfer_open(text), public.transfer_submit(text, uuid, jsonb) to anon, authenticated;
revoke all on function public.admin_transfer_confirm_call(uuid, boolean), public.admin_transfer_approve(uuid),
  public.admin_transfer_reject(uuid, text) from public, anon;
grant execute on function public.admin_transfer_confirm_call(uuid, boolean), public.admin_transfer_approve(uuid),
  public.admin_transfer_reject(uuid, text) to authenticated;

-- >>>>>>>> r2_04_public_via_code.sql
-- ============================================================================
-- Release 2, Step 1, piece 4 (FINAL DESIGN, 17 Oct 2026): PUBLIC TRANSFER via the same code
-- The seller makes a code exactly like a private transfer, but the money goes THROUGH THE ORGANISERS:
-- seller's payout UPI ID -> admin shares the code with a buyer they found -> buyer fills the form ->
-- admin phones the seller -> admin asks the buyer to pay -> buyer uploads a screenshot -> admin enters
-- the amount actually received and presses Transfer -> admin pays the seller exactly that amount.
-- A private transfer stays as it is: no money passes through the organisers.
-- REQUIRES r2_01, r2_02 and r2_03. Supersedes these piece-3 functions (same names, extended):
--   transfer_status, lookup_tickets, admin_transfer_approve, admin_transfer_reject, _close_open_transfers.
-- Transfers stay OFF until settings.transfers_open is set.
-- ============================================================================

-- 1. Money fields on the transfer (a transfer has exactly one buyer, so one payment)
alter table public.transfers add column if not exists seller_upi text
  check (seller_upi is null or seller_upi ~ '^([0-9]{10}|[A-Za-z0-9._-]{2,64}@[A-Za-z][A-Za-z0-9]{1,31})$');
alter table public.transfers add column if not exists amount_due integer check (amount_due is null or amount_due >= 0);
alter table public.transfers add column if not exists payment_requested_at timestamptz;
alter table public.transfers add column if not exists payment_requested_by uuid references auth.users(id);
alter table public.transfers add column if not exists payment_submission_id uuid unique;
alter table public.transfers add column if not exists payment_screenshot_path text;
alter table public.transfers add column if not exists payment_submitted_at timestamptz;
alter table public.transfers add column if not exists payment_verified_at timestamptz;
alter table public.transfers add column if not exists payment_verified_by uuid references auth.users(id);
alter table public.transfers add column if not exists amount_received integer check (amount_received is null or amount_received > 0);
alter table public.transfers add column if not exists seller_paid_at timestamptz;
alter table public.transfers add column if not exists seller_paid_by uuid references auth.users(id);
alter table public.transfers add column if not exists payout_reference text check (payout_reference is null or char_length(payout_reference) between 3 and 80);
alter table public.transfers add column if not exists return_due boolean not null default false;
alter table public.transfers add column if not exists returned_at timestamptz;
alter table public.transfers add column if not exists returned_by uuid references auth.users(id);
alter table public.transfers add column if not exists return_reference text check (return_reference is null or char_length(return_reference) between 3 and 80);
alter table public.transfers drop constraint if exists transfers_public_has_upi;
alter table public.transfers add constraint transfers_public_has_upi check (kind <> 'public' or seller_upi is not null);

-- 2. A transfer that failed after the buyer sent money must go back to the buyer
create or replace function public._close_open_transfers(p_booking uuid, p_reason text) returns void
 language plpgsql security definer set search_path to 'public' as $function$
declare x record; due boolean;
begin
  for x in select id, status, kind, payment_submitted_at from transfers where booking_id = p_booking
           and status in ('code_active', 'pending_admin') for update loop
    due := x.kind = 'public' and x.payment_submitted_at is not null;
    update transfers set status = 'withdrawn', decision_note = left(p_reason, 300), decided_at = now(),
           decided_by = auth.uid(), updated_at = now(), return_due = (return_due or due) where id = x.id;
    update bookings set status = 'rejected', reviewed_by = auth.uid(), reviewed_at = now(), reviewed_via = 'admin'
     where id in (select booking_id from transfer_buyers where transfer_id = x.id and status = 'active');
    update transfer_buyers set status = 'released' where transfer_id = x.id and status = 'active';
    perform _tlog(x.kind || ' transfer closed automatically', x.status, left(x.id::text, 8) || ': ' || p_reason || case when due then ' (RETURN DUE)' else '' end);
  end loop;
end $function$;

-- 3. Seller side of a public transfer: like private_sell, plus the payout UPI ID
create or replace function public.public_sell(p_booking_code text, p_ticket text, p_phone text, p_upi text) returns jsonb
 language plpgsql security definer set search_path to 'public' as $function$
declare s settings%rowtype; tid uuid; t tickets%rowtype; b bookings%rowtype; x transfers%rowtype; code text; lbl text; blocked text; upi text;
begin
  select * into s from settings where id = 1;
  if not s.transfers_open then return jsonb_build_object('ok', false, 'error', 'TRANSFERS_CLOSED'); end if;
  if s.transfer_cutoff_at is not null and now() > s.transfer_cutoff_at then
    return jsonb_build_object('ok', false, 'error', 'CUTOFF_PASSED'); end if;
  tid := _find_seller_ticket(p_booking_code, p_ticket, p_phone);
  if tid is null then return jsonb_build_object('ok', false, 'error', 'MISMATCH'); end if;
  select * into t from tickets where id = tid for update;
  select * into b from bookings where id = t.booking_id;
  if t.transferred_out_at is not null then return jsonb_build_object('ok', false, 'error', 'ALREADY_TRANSFERRED'); end if;
  if b.status <> 'paid' or t.ticket_no is null then return jsonb_build_object('ok', false, 'error', 'NOT_CONFIRMED'); end if;
  if t.kind <> 'guest' then return jsonb_build_object('ok', false, 'error', 'COORDINATOR'); end if;
  if t.checked_in_at is not null then return jsonb_build_object('ok', false, 'error', 'ALREADY_CHECKED_IN'); end if;
  upi := btrim(coalesce(p_upi, ''));
  if upi !~ '^([0-9]{10}|[A-Za-z0-9._-]{2,64}@[A-Za-z][A-Za-z0-9]{1,31})$' then return jsonb_build_object('ok', false, 'error', 'INVALID_UPI'); end if;
  lbl := _ticket_label(t.kind, t.ticket_no, t.coord_no);
  select * into x from transfers where ticket_id = t.id and status in ('code_active', 'pending_admin') for update;
  if found then
    if x.status = 'pending_admin' then return jsonb_build_object('ok', false, 'error', 'ALREADY_PENDING'); end if;
    update transfers set status = 'replaced', updated_at = now() where id = x.id;
    perform _tlog('public transfer: code replaced', lbl, left(x.id::text, 8));
  end if;
  begin
    code := _new_transfer_code();
    insert into transfers (kind, ticket_id, booking_id, seller_name, seller_phone, status, code, code_expires_at, seller_upi)
    values ('public', t.id, b.id, t.name, t.phone, 'code_active', code, now() + make_interval(hours => s.private_code_hours), upi)
    returning * into x;
  exception when unique_violation then
    return jsonb_build_object('ok', false, 'error', 'TRY_AGAIN');
  end;
  perform _tlog('public transfer: code created', null, lbl || ' (' || left(x.id::text, 8) || ')');
  return jsonb_build_object('ok', true, 'mode', 'public', 'code', x.code, 'expires_at', x.code_expires_at,
                            'hours', s.private_code_hours, 'ticket_label', lbl);
end $function$;

-- 4. Seller status (both modes); for a public transfer also whether the seller has been paid
create or replace function public.transfer_status(p_booking_code text, p_phone text) returns jsonb
 language plpgsql stable security definer set search_path to 'public' as $function$
declare c text; ph text; b bookings%rowtype; res jsonb;
begin
  c  := replace(replace(replace(upper(coalesce(p_booking_code, '')), 'O', '0'), ' ', ''), '-', '');
  ph := replace(replace(coalesce(p_phone, ''), ' ', ''), '-', '');
  if length(c) <> 8 or ph !~ '^[0-9]{10}$' then return jsonb_build_object('found', false); end if;
  select * into b from bookings where booking_code = c;
  if not found or not exists (select 1 from tickets where booking_id = b.id and phone = ph) then
    return jsonb_build_object('found', false); end if;
  select coalesce(jsonb_agg(r.j order by r.created_at desc), '[]'::jsonb) into res from (
    select x.created_at, jsonb_build_object(
        'ticket_label', _ticket_label(tk.kind, tk.ticket_no, tk.coord_no), 'mode', x.kind,
        'status', case when x.status = 'code_active' and x.code_expires_at <= now() then 'expired' else x.status end,
        'code', case when x.status = 'code_active' and x.code_expires_at > now() then x.code end,
        'expires_at', case when x.status = 'code_active' then x.code_expires_at end,
        'buyer_name', case when x.status in ('pending_admin', 'done')
                           then (select bu.name from transfer_buyers bu where bu.transfer_id = x.id and bu.status in ('active', 'done') limit 1) end,
        'payout', case when x.kind = 'public' and x.status = 'done' then case when x.seller_paid_at is not null then 'paid' else 'to_be_paid' end end,
        'amount_to_receive', case when x.kind = 'public' and x.status = 'done' then x.amount_received end,
        'created_at', x.created_at) as j
      from transfers x join tickets tk on tk.id = x.ticket_id
     where x.booking_id = b.id and x.seller_phone = ph
     order by x.created_at desc limit 10) r;
  return jsonb_build_object('found', true, 'transfers', res);
end $function$;

-- 5. Buyer side: Booking ID + phone shows where a public transfer stands, and what to pay
create or replace function public.lookup_tickets(p_code text, p_phone text)
 returns jsonb
 language plpgsql
 stable security definer
 set search_path to 'public'
as $function$
declare b bookings%rowtype; c text; ph text; tk jsonb; bu transfer_buyers%rowtype; x transfers%rowtype; st text;
begin
  c  := replace(replace(replace(upper(coalesce(p_code, '')), 'O', '0'), ' ', ''), '-', '');
  ph := replace(replace(coalesce(p_phone, ''), ' ', ''), '-', '');
  if length(c) <> 8 or ph !~ '^[0-9]{10}$' then return jsonb_build_object('found', false); end if;
  select * into b from bookings where booking_code = c;
  if not found then return jsonb_build_object('found', false); end if;
  if b.kind = 'transfer' then
    select * into bu from transfer_buyers where booking_id = b.id and phone = ph;
    if not found then return jsonb_build_object('found', false); end if;
    select * into x from transfers where id = bu.transfer_id;
  end if;
  select jsonb_agg(jsonb_build_object(
           'ticket_no', t.ticket_no, 'kind', t.kind, 'coord_no', t.coord_no,
           'label', _ticket_label(t.kind, t.ticket_no, t.coord_no),
           'secret', case when b.status = 'paid' and t.transferred_out_at is null then t.secret else null end,
           'transferred', (t.transferred_out_at is not null),
           'name', t.name, 'location', t.location, 'attendance', t.attendance, 'food', t.food)
         order by t.reg_seq)
    into tk from tickets t where t.booking_id = b.id and t.phone = ph;
  if tk is null then
    if b.kind = 'transfer' then
      st := case when x.kind = 'public' and x.returned_at is not null then 'returned'
                 when x.kind = 'public' and x.return_due then 'return_due'
                 when b.status = 'rejected' then 'rejected'
                 when x.kind = 'public' and x.payment_verified_at is not null then 'payment_verified'
                 when x.kind = 'public' and x.payment_submitted_at is not null then 'payment_submitted'
                 when x.kind = 'public' and x.payment_requested_at is not null then 'payment_due'
                 else 'pending' end;
      return jsonb_build_object('found', true, 'kind', 'transfer', 'booking_code', b.booking_code, 'status', b.status,
                                'people_count', 1, 'amount_expected', 0, 'name', bu.name, 'tickets', '[]'::jsonb,
                                'transfer', jsonb_build_object('type', x.kind, 'state', st,
                                   'amount_due', case when st = 'payment_due' then x.amount_due end));
    end if;
    return jsonb_build_object('found', false);
  end if;
  return jsonb_build_object('found', true, 'kind', b.kind, 'booking_code', b.booking_code, 'status', b.status,
                            'people_count', b.people_count, 'amount_expected', b.amount_expected, 'tickets', tk);
end $function$;

-- the buyer uploads the payment screenshot once the organisers asked for payment
create or replace function public.transfer_pay(p_booking_code text, p_phone text, p_submission_id uuid, p_screenshot_path text) returns jsonb
 language plpgsql security definer set search_path to 'public' as $function$
declare c text; ph text; b bookings%rowtype; bu transfer_buyers%rowtype; x transfers%rowtype; s settings%rowtype;
begin
  c  := replace(replace(replace(upper(coalesce(p_booking_code, '')), 'O', '0'), ' ', ''), '-', '');
  ph := replace(replace(coalesce(p_phone, ''), ' ', ''), '-', '');
  if length(c) <> 8 or ph !~ '^[0-9]{10}$' or p_submission_id is null then return jsonb_build_object('ok', false, 'error', 'MISMATCH'); end if;
  select * into b from bookings where booking_code = c and kind = 'transfer';
  if not found then return jsonb_build_object('ok', false, 'error', 'MISMATCH'); end if;
  select * into bu from transfer_buyers where booking_id = b.id and phone = ph;
  if not found then return jsonb_build_object('ok', false, 'error', 'MISMATCH'); end if;
  select * into x from transfers where id = bu.transfer_id and kind = 'public' for update;
  if not found then return jsonb_build_object('ok', false, 'error', 'MISMATCH'); end if;
  if x.payment_submission_id = p_submission_id then return jsonb_build_object('ok', true, 'replay', true, 'amount_due', x.amount_due); end if;
  select * into s from settings where id = 1;
  if not s.transfers_open then return jsonb_build_object('ok', false, 'error', 'TRANSFERS_CLOSED'); end if;
  if x.status <> 'pending_admin' then return jsonb_build_object('ok', false, 'error', 'NOT_ACTIVE'); end if;
  if x.payment_requested_at is null then return jsonb_build_object('ok', false, 'error', 'PAYMENT_NOT_REQUESTED'); end if;
  if x.payment_submitted_at is not null then return jsonb_build_object('ok', false, 'error', 'ALREADY_SUBMITTED'); end if;
  if p_screenshot_path is null or p_screenshot_path not like p_submission_id::text || '%'
     or not exists (select 1 from storage.objects where bucket_id = 'payment-proofs' and name = p_screenshot_path) then
    return jsonb_build_object('ok', false, 'error', 'SCREENSHOT_MISSING'); end if;
  update transfers set payment_submission_id = p_submission_id, payment_screenshot_path = p_screenshot_path,
         payment_submitted_at = now(), updated_at = now() where id = x.id;
  perform _tlog('public transfer: buyer payment submitted', null, x.amount_due::text || ' due (' || left(x.id::text, 8) || ')');
  return jsonb_build_object('ok', true, 'amount_due', x.amount_due);
end $function$;

-- 6. Admin side
-- a code can last longer than the default when finding a buyer takes time (also revives an expired code)
create or replace function public.admin_transfer_extend_code(p_transfer uuid, p_hours integer) returns void
 language plpgsql security definer set search_path to 'public' as $function$
declare x transfers%rowtype;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  if p_hours is null or p_hours not between 1 and 168 then raise exception 'INVALID_HOURS'; end if;
  select * into x from transfers where id = p_transfer for update;
  if not found then raise exception 'INVALID_TRANSFER'; end if;
  if x.status <> 'code_active' then raise exception 'NOT_ACTIVE'; end if;
  update transfers set code_expires_at = now() + make_interval(hours => p_hours), updated_at = now() where id = x.id;
  perform _tlog(x.kind || ' transfer: code extended', null, p_hours || ' h (' || left(x.id::text, 8) || ')');
end $function$;

-- after the phone call with the seller: ask the buyer to pay the standard ticket price
create or replace function public.admin_transfer_request_payment(p_transfer uuid) returns jsonb
 language plpgsql security definer set search_path to 'public' as $function$
declare x transfers%rowtype; s settings%rowtype;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  select * into s from settings where id = 1;
  select * into x from transfers where id = p_transfer for update;
  if not found then raise exception 'INVALID_TRANSFER'; end if;
  if x.kind <> 'public' then raise exception 'NOT_PUBLIC'; end if;
  if x.status <> 'pending_admin' then raise exception 'NOT_PENDING'; end if;
  if x.seller_call_confirmed_at is null then raise exception 'CALL_NOT_CONFIRMED'; end if;
  if x.payment_requested_at is not null then raise exception 'ALREADY_REQUESTED'; end if;
  update transfers set payment_requested_at = now(), payment_requested_by = auth.uid(), amount_due = s.price_per_head, updated_at = now() where id = x.id;
  perform _tlog('public transfer: payment requested', null, s.price_per_head || ' (' || left(x.id::text, 8) || ')');
  return jsonb_build_object('amount_due', s.price_per_head);
end $function$;

-- the admin enters what actually arrived (any positive amount: it is passed on to the seller in full)
create or replace function public.admin_transfer_verify_payment(p_transfer uuid, p_amount integer) returns void
 language plpgsql security definer set search_path to 'public' as $function$
declare x transfers%rowtype;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  select * into x from transfers where id = p_transfer and kind = 'public' for update;
  if not found then raise exception 'INVALID_TRANSFER'; end if;
  if x.status <> 'pending_admin' then raise exception 'NOT_PENDING'; end if;
  if x.payment_submitted_at is null then raise exception 'NOT_SUBMITTED'; end if;
  if x.payment_verified_at is not null then raise exception 'ALREADY_VERIFIED'; end if;
  if p_amount is null or p_amount not between 1 and 1000000 then raise exception 'INVALID_AMOUNT'; end if;
  update transfers set payment_verified_at = now(), payment_verified_by = auth.uid(), amount_received = p_amount, updated_at = now() where id = x.id;
  perform _tlog('public transfer: payment VERIFIED', x.amount_due::text || ' asked', p_amount::text || ' received (' || left(x.id::text, 8) || ')');
end $function$;

-- THE TRANSFER BUTTON for both modes (private needs the call tick; public needs the call tick AND the verified payment)
create or replace function public.admin_transfer_approve(p_transfer uuid) returns jsonb
 language plpgsql security definer set search_path to 'public' as $function$
declare x transfers%rowtype; t tickets%rowtype; sb bookings%rowtype; bu transfer_buyers%rowtype; bk bookings%rowtype; nt tickets%rowtype; old_lbl text;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  perform 1 from settings where id = 1 for update;                       -- same lock order as set_booking_status
  select * into x from transfers where id = p_transfer for update;
  if not found then raise exception 'INVALID_TRANSFER'; end if;
  if x.status <> 'pending_admin' then raise exception 'NOT_PENDING'; end if;
  if x.seller_call_confirmed_at is null then raise exception 'CALL_NOT_CONFIRMED'; end if;
  if x.kind = 'public' and x.payment_verified_at is null then raise exception 'PAYMENT_NOT_VERIFIED'; end if;
  select * into t from tickets where id = x.ticket_id for update;
  select * into sb from bookings where id = t.booking_id for update;
  if t.transferred_out_at is not null then raise exception 'SELLER_ALREADY_TRANSFERRED'; end if;
  if t.checked_in_at is not null then raise exception 'SELLER_CHECKED_IN'; end if;
  if sb.status <> 'paid' or t.kind <> 'guest' or t.ticket_no is null then raise exception 'SELLER_TICKET_INVALID'; end if;
  select * into bu from transfer_buyers where transfer_id = x.id and status = 'active' for update;
  if not found then raise exception 'NO_BUYER'; end if;
  select * into bk from bookings where id = bu.booking_id for update;
  if bk.kind <> 'transfer' or bk.status <> 'pending' then raise exception 'BUYER_BOOKING_INVALID'; end if;
  old_lbl := _ticket_label(t.kind, t.ticket_no, t.coord_no);
  insert into tickets (secret, booking_id, name, phone, location, attendance, food, kind, transferred_from)
  values (substr(replace(gen_random_uuid()::text, '-', ''), 1, 12), bk.id, bu.name, bu.phone,
          bu.location, bu.attendance, bu.food, 'guest', t.id)
  returning * into nt;
  insert into ticket_emails (ticket_id, email) values (nt.id, bu.email);   -- email stays in the admin-only table
  update tickets set transferred_out_at = now() where id = t.id;
  update bookings set status = 'paid', reviewed_by = auth.uid(), reviewed_at = now(), reviewed_via = 'admin' where id = bk.id;
  perform _assign_numbers(bk.id);
  select * into nt from tickets where id = nt.id;
  update transfers set status = 'done', decided_at = now(), decided_by = auth.uid(), result_ticket_id = nt.id, updated_at = now() where id = x.id;
  update transfer_buyers set status = 'done' where id = bu.id;
  perform _tlog(x.kind || ' transfer: APPROVED', old_lbl, _ticket_label(nt.kind, nt.ticket_no, nt.coord_no) || ' (' || left(x.id::text, 8) || ')');
  return jsonb_build_object('new_label', _ticket_label(nt.kind, nt.ticket_no, nt.coord_no),
                            'old_label', old_lbl, 'booking_code', bk.booking_code);
end $function$;

create or replace function public.admin_transfer_reject(p_transfer uuid, p_note text default null) returns void
 language plpgsql security definer set search_path to 'public' as $function$
declare x transfers%rowtype; note text; due boolean;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  select * into x from transfers where id = p_transfer for update;
  if not found then raise exception 'INVALID_TRANSFER'; end if;
  if x.status not in ('code_active', 'pending_admin') then raise exception 'NOT_PENDING'; end if;
  note := nullif(btrim(coalesce(p_note, '')), '');
  if note is not null and char_length(note) > 300 then raise exception 'INVALID_NOTE'; end if;
  due := x.kind = 'public' and x.payment_submitted_at is not null;
  update transfers set status = 'rejected', decision_note = note, decided_at = now(), decided_by = auth.uid(), updated_at = now(),
         return_due = (return_due or due) where id = x.id;
  update bookings set status = 'rejected', reviewed_by = auth.uid(), reviewed_at = now(), reviewed_via = 'admin'
   where id in (select booking_id from transfer_buyers where transfer_id = x.id and status = 'active');
  update transfer_buyers set status = 'rejected' where transfer_id = x.id and status = 'active';
  perform _tlog(x.kind || ' transfer: REJECTED', x.status, left(x.id::text, 8) || coalesce(': ' || note, '') || case when due then ' (RETURN DUE)' else '' end);
end $function$;

create or replace function public.admin_transfer_mark_paid(p_transfer uuid, p_reference text) returns void
 language plpgsql security definer set search_path to 'public' as $function$
declare x transfers%rowtype; ref text;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  select * into x from transfers where id = p_transfer and kind = 'public' for update;
  if not found then raise exception 'INVALID_TRANSFER'; end if;
  if x.status <> 'done' then raise exception 'NOT_DONE'; end if;
  if x.seller_paid_at is not null then raise exception 'ALREADY_PAID'; end if;
  ref := btrim(coalesce(p_reference, ''));
  if char_length(ref) not between 3 and 80 then raise exception 'INVALID_REFERENCE'; end if;
  update transfers set seller_paid_at = now(), seller_paid_by = auth.uid(), payout_reference = ref, updated_at = now() where id = x.id;
  perform _tlog('public transfer: seller PAID', x.amount_received::text, left(x.id::text, 8));
end $function$;

create or replace function public.admin_transfer_mark_returned(p_transfer uuid, p_reference text) returns void
 language plpgsql security definer set search_path to 'public' as $function$
declare x transfers%rowtype; ref text;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  select * into x from transfers where id = p_transfer and kind = 'public' for update;
  if not found then raise exception 'INVALID_TRANSFER'; end if;
  if not x.return_due then raise exception 'NO_RETURN_DUE'; end if;
  if x.returned_at is not null then raise exception 'ALREADY_RETURNED'; end if;
  ref := btrim(coalesce(p_reference, ''));
  if char_length(ref) not between 3 and 80 then raise exception 'INVALID_REFERENCE'; end if;
  update transfers set returned_at = now(), returned_by = auth.uid(), return_reference = ref, updated_at = now() where id = x.id;
  perform _tlog('public transfer: money RETURNED to buyer', coalesce(x.amount_received, x.amount_due)::text, left(x.id::text, 8));
end $function$;

create or replace function public.admin_transfer_money() returns jsonb
 language plpgsql stable security definer set search_path to 'public' as $function$
declare r jsonb;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  select jsonb_build_object(
    'awaiting_payment', jsonb_build_object('count', count(*) filter (where status = 'pending_admin' and payment_requested_at is not null and payment_submitted_at is null),
        'amount', coalesce(sum(amount_due) filter (where status = 'pending_admin' and payment_requested_at is not null and payment_submitted_at is null), 0)),
    'awaiting_verification', jsonb_build_object('count', count(*) filter (where status = 'pending_admin' and payment_submitted_at is not null and payment_verified_at is null),
        'amount', coalesce(sum(amount_due) filter (where status = 'pending_admin' and payment_submitted_at is not null and payment_verified_at is null), 0)),
    'verified_waiting_transfer', jsonb_build_object('count', count(*) filter (where status = 'pending_admin' and payment_verified_at is not null),
        'amount', coalesce(sum(amount_received) filter (where status = 'pending_admin' and payment_verified_at is not null), 0)),
    'to_pay_out', jsonb_build_object('count', count(*) filter (where status = 'done' and seller_paid_at is null),
        'amount', coalesce(sum(amount_received) filter (where status = 'done' and seller_paid_at is null), 0)),
    'paid_out', jsonb_build_object('count', count(*) filter (where seller_paid_at is not null),
        'amount', coalesce(sum(amount_received) filter (where seller_paid_at is not null), 0)),
    'return_due', jsonb_build_object('count', count(*) filter (where return_due and returned_at is null),
        'amount', coalesce(sum(coalesce(amount_received, amount_due)) filter (where return_due and returned_at is null), 0)),
    'returned', jsonb_build_object('count', count(*) filter (where returned_at is not null),
        'amount', coalesce(sum(coalesce(amount_received, amount_due)) filter (where returned_at is not null), 0)),
    'held_now', coalesce(sum(amount_received) filter (where (status = 'pending_admin' and payment_verified_at is not null)
                                                         or (status = 'done' and seller_paid_at is null)
                                                         or (return_due and returned_at is null and payment_verified_at is not null)), 0))
    into r from transfers where kind = 'public';
  return r;
end $function$;

-- 7. Who may call what
revoke all on function public._close_open_transfers(uuid, text) from public, anon, authenticated, service_role;
revoke all on function public.public_sell(text, text, text, text), public.transfer_pay(text, text, uuid, text) from public;
grant execute on function public.public_sell(text, text, text, text), public.transfer_pay(text, text, uuid, text) to anon, authenticated;
revoke all on function public.admin_transfer_extend_code(uuid, integer), public.admin_transfer_request_payment(uuid),
  public.admin_transfer_verify_payment(uuid, integer), public.admin_transfer_mark_paid(uuid, text),
  public.admin_transfer_mark_returned(uuid, text), public.admin_transfer_money() from public, anon;
grant execute on function public.admin_transfer_extend_code(uuid, integer), public.admin_transfer_request_payment(uuid),
  public.admin_transfer_verify_payment(uuid, integer), public.admin_transfer_mark_paid(uuid, text),
  public.admin_transfer_mark_returned(uuid, text), public.admin_transfer_money() to authenticated;

-- >>>>>>>> r2_05_cleanup_and_ip.sql
-- ============================================================================
-- Release 2, Step 1, piece 5: CLEAN-UP of the old transfer backend + the IP FLAG
-- Written 17 Oct 2026. Tested on the scratch database before use.
-- REQUIRES r2_01 to r2_04. Run when the new pages are live (nothing calls the old backend; checked).
-- 1. Drops the OLD transfer functions and tables (ticket_listings, ticket_interests, ticket_transfers).
-- 2. Records the visitor's IP on every registration, ADMIN-ONLY, FLAG ONLY (never blocks anyone).
-- ============================================================================

-- 1. The old transfer backend (replaced by the code flow in r2_03 / r2_04)
do $$
declare r record;
begin
  for r in
    select p.oid::regprocedure as sig
      from pg_proc p join pg_namespace n on n.oid = p.pronamespace
     where n.nspname = 'public'
       and p.proname = any (array[
             'apply_receive',
             'check_request',
             'close_listing',
             'edit_listing',
             'express_interest',
             'get_transfer_status',
             'list_board',
             'lookup_transfer',
             'manage_ticket',
             'post_listing',
             'start_transfer',
             'submit_transfer_payment',
             'withdraw_transfer',
             'approve_transfer',
             'decline_transfer',
             'admin_confirm_amount',
             'admin_mark_payment_received',
             'admin_mark_seller_paid',
             'admin_mark_refunded',
             'admin_remove_listing',
             'admin_clear_comment',
             'admin_set_transfer_settings',
             '_seller_ticket',
             '_transfer_block_reason',
             '_clean_comment',
             '_clean_payout',
             '_seller_kind',
             '_norm_code'])
  loop
    execute 'drop function ' || r.sig;
  end loop;
end $$;
drop table if exists public.ticket_transfers, public.ticket_interests, public.ticket_listings;   -- one statement: they reference each other

-- 2. IP flag. Kept in its own admin-only table so a gate login can never read it from the bookings table.
alter table public.settings add column if not exists ip_flag_threshold integer not null default 5;
alter table public.settings drop constraint if exists settings_ip_flag_check;
alter table public.settings add constraint settings_ip_flag_check check (ip_flag_threshold between 2 and 1000);

create table if not exists public.booking_ips (
  booking_id uuid primary key references public.bookings(id) on delete cascade,
  ip text,
  raw text,
  created_at timestamptz not null default now()
);
create index if not exists booking_ips_ip_idx on public.booking_ips (ip);
alter table public.booking_ips enable row level security;
drop policy if exists admin_read_booking_ips on public.booking_ips;
create policy admin_read_booking_ips on public.booking_ips for select to authenticated using (is_admin());
revoke all on table public.booking_ips from public, anon, authenticated, service_role;
grant select on table public.booking_ips to authenticated;

-- the request headers (empty when called from the SQL editor)
create or replace function public._request_headers() returns jsonb
 language plpgsql stable as $function$
declare h text;
begin
  h := current_setting('request.headers', true);
  if h is null or h = '' then return '{}'::jsonb; end if;
  begin return h::jsonb; exception when others then return '{}'::jsonb; end;
end $function$;

create or replace function public._clean_ip(p text) returns text language sql immutable as $$
  select case when btrim(coalesce(p, '')) ~ '^[0-9a-fA-F:.]{2,45}$' then btrim(p) end $$;

create or replace function public._header(p_name text) returns text language sql stable as $$
  select value from jsonb_each_text(_request_headers()) where lower(key) = lower(p_name) limit 1 $$;

-- Cloudflare's header when present (a visitor cannot fake it); otherwise the LAST address in x-forwarded-for
-- (the one added by the nearest proxy). Which header is trustworthy on the real project must be checked
-- from the stored raw values (see the notes); this only ever FLAGS.
create or replace function public._client_ip() returns text
 language plpgsql stable as $function$
declare ip text; xff text; parts text[];
begin
  ip := _clean_ip(_header('cf-connecting-ip'));
  if ip is not null then return ip; end if;
  xff := _header('x-forwarded-for');
  if xff is not null then
    parts := string_to_array(replace(xff, ' ', ''), ',');
    ip := _clean_ip(parts[array_length(parts, 1)]);
  end if;
  return ip;
end $function$;

create or replace function public._client_ip_raw() returns text language sql stable as $$
  select nullif(left(regexp_replace('cf=' || coalesce(_header('cf-connecting-ip'), '') || ' xff=' || coalesce(_header('x-forwarded-for'), ''), '[^\x20-\x7E]', '', 'g'), 300), 'cf= xff=') $$;

-- registration now records the IP (flag only)
CREATE OR REPLACE FUNCTION public.submit_booking(p_submission_id uuid, p_people jsonb, p_screenshot_path text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare s settings%rowtype; b bookings%rowtype; n int; used int; r record; code text; pi jsonb; tid uuid;
begin
  select * into b from bookings where submission_id = p_submission_id;
  if found then return _booking_json(b.id); end if;

  select * into s from settings where id = 1 for update;
  select * into b from bookings where submission_id = p_submission_id;
  if found then return _booking_json(b.id); end if;

  pi := _pause_info(s);
  if (not s.is_open or (pi->>'in_pause')::boolean or now() > s.deadline) then
    -- closed right now: only people who were already filling the form get the grace minutes (+30 s for upload time)
    if _grace_until(s, p_submission_id, interval '30 seconds') is null then
      raise exception 'REGISTRATION_CLOSED';
    end if;
  end if;
  if p_people is null or jsonb_typeof(p_people) <> 'array' then raise exception 'INVALID_DATA'; end if;
  n := jsonb_array_length(p_people);
  if n < 1 or n > s.max_group then raise exception 'INVALID_GROUP_SIZE'; end if;

  select count(*) into used from tickets t join bookings bk on bk.id = t.booking_id where bk.status <> 'rejected' and t.transferred_out_at is null;
  if used + n > s.cap then raise exception 'NOT_ENOUGH_SPOTS'; end if;

  for r in select value from jsonb_array_elements(p_people) loop
    if length(trim(coalesce(r.value->>'name',''))) not between 1 and 80 then raise exception 'INVALID_NAME'; end if;
    if coalesce(r.value->>'phone','') !~ '^[0-9]{10}$' then raise exception 'INVALID_PHONE'; end if;
    if length(trim(coalesce(r.value->>'email',''))) not between 5 and 120
       or lower(trim(r.value->>'email')) !~ '^[^@\s]+@[^@\s]+\.[^@\s]+$' then raise exception 'INVALID_EMAIL'; end if;
    if coalesce(r.value->>'loc','') not in ('In Bengaluru','Outside Bengaluru') then raise exception 'INVALID_LOCATION'; end if;
    if coalesce(r.value->>'att','') not in ('Surely','Most probably') then raise exception 'INVALID_ATTENDANCE'; end if;
    if coalesce(r.value->>'food','') not in ('Veg','Non-veg') then raise exception 'INVALID_FOOD'; end if;
  end loop;

  if p_screenshot_path is null or p_screenshot_path not like p_submission_id::text || '%'
     or not exists (select 1 from storage.objects where bucket_id = 'payment-proofs' and name = p_screenshot_path)
  then raise exception 'SCREENSHOT_MISSING'; end if;

  loop
    code := upper(substr(replace(gen_random_uuid()::text, '-', ''), 1, 8));
    exit when not exists (select 1 from bookings where booking_code = code);
  end loop;

  insert into bookings (booking_code, submission_id, people_count, amount_expected, screenshot_path)
  values (code, p_submission_id, n, n * s.price_per_head, p_screenshot_path) returning * into b;
  insert into booking_ips (booking_id, ip, raw) values (b.id, _client_ip(), _client_ip_raw());   -- flag only, never blocks

  -- one ticket per person, in the order listed; the email goes to the admin-only table ticket_emails
  for r in select value, ord from jsonb_array_elements(p_people) with ordinality as e(value, ord) order by ord loop
    insert into tickets (secret, booking_id, name, phone, location, attendance, food)
    values (substr(replace(gen_random_uuid()::text, '-', ''), 1, 12), b.id,
            trim(r.value->>'name'), r.value->>'phone', r.value->>'loc', r.value->>'att', r.value->>'food')
    returning id into tid;
    insert into ticket_emails (ticket_id, email) values (tid, lower(trim(r.value->>'email')));
  end loop;

  return _booking_json(b.id);
end $function$;

-- admin: addresses with many registrations (the threshold is a setting, default 5)
create or replace function public.admin_ip_flags() returns jsonb
 language plpgsql stable security definer set search_path to 'public' as $function$
declare th integer; res jsonb; bb jsonb;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  select ip_flag_threshold into th from settings where id = 1;
  select coalesce(jsonb_agg(q.j order by (q.j->>'bookings')::int desc, q.j->>'ip'), '[]'::jsonb) into res from (
    select jsonb_build_object('ip', i.ip, 'bookings', count(*), 'people', sum(b.people_count),
             'pending', count(*) filter (where b.status = 'pending'), 'paid', count(*) filter (where b.status = 'paid'),
             'rejected', count(*) filter (where b.status = 'rejected'),
             'first_at', min(b.created_at), 'last_at', max(b.created_at)) as j
      from booking_ips i join bookings b on b.id = i.booking_id
     where i.ip is not null and b.kind = 'registration'
     group by i.ip having count(*) >= th) q;
  select coalesce(jsonb_object_agg(b.booking_code, jsonb_build_object('ip', i.ip, 'count', c.n)), '{}'::jsonb) into bb
    from booking_ips i join bookings b on b.id = i.booking_id
    join (select ip, count(*) n from booking_ips bi join bookings bb2 on bb2.id = bi.booking_id where bi.ip is not null and bb2.kind = 'registration' group by ip having count(*) >= th) c on c.ip = i.ip
   where b.kind = 'registration';
  return jsonb_build_object('threshold', th, 'ips', res, 'by_booking', bb);
end $function$;

-- admin: delete every stored IP (to be done after the event)
create or replace function public.admin_clear_client_ips() returns integer
 language plpgsql security definer set search_path to 'public' as $function$
declare n integer;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  delete from booking_ips; get diagnostics n = row_count;
  insert into settings_log (changed_by, who, area, field, old_value, new_value)
  values (auth.uid(), _actor(), 'settings', 'stored visitor IPs deleted', n::text || ' rows', null);
  return n;
end $function$;

revoke all on function public._request_headers(), public._clean_ip(text), public._header(text), public._client_ip(), public._client_ip_raw()
  from public, anon, authenticated, service_role;
revoke all on function public.admin_ip_flags(), public.admin_clear_client_ips() from public, anon;
grant execute on function public.admin_ip_flags(), public.admin_clear_client_ips() to authenticated;

-- >>>>>>>> r2_06_transfer_settings.sql
-- ============================================================================
-- Release 2, Step 1, piece 6: transfer settings (admin) and transfer info (visitors)
-- Written 24 Oct 2026. Tested on the scratch database before use.
-- REQUIRES r2_01 to r2_05 (run it AFTER r2_05: that file drops every function named
-- admin_set_transfer_settings, including this one if it already existed).
-- Changes no data. Transfers stay OFF until an admin switches them on here.
-- ============================================================================

-- 1. Admin: change the transfer settings (the only way to do it from the app)
--    p_open          true/false      turn transfers on or off
--    p_cutoff        timestamp       no NEW codes, buyer forms or payment uploads after this moment
--    p_clear_cutoff  true            remove the cut-off again (cannot be combined with p_cutoff)
--    p_food_locked   true/false      the buyer gets the seller's food (use after the food order is placed)
--    p_code_hours    1 to 168        how long a new code stays valid
--    p_ip_threshold  2 to 1000       how many registrations from one address raise a flag
--    A null parameter means "keep as it is". Every change is written to the settings log automatically.
create or replace function public.admin_set_transfer_settings(
  p_open boolean default null,
  p_cutoff timestamptz default null,
  p_clear_cutoff boolean default false,
  p_food_locked boolean default null,
  p_code_hours integer default null,
  p_ip_threshold integer default null) returns void
 language plpgsql security definer set search_path to 'public' as $function$
declare s settings%rowtype;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  if p_code_hours is not null and p_code_hours not between 1 and 168 then raise exception 'INVALID_HOURS'; end if;
  if p_ip_threshold is not null and p_ip_threshold not between 2 and 1000 then raise exception 'INVALID_THRESHOLD'; end if;
  if p_cutoff is not null and coalesce(p_clear_cutoff, false) then raise exception 'INVALID_CUTOFF'; end if;
  select * into s from settings where id = 1 for update;
  -- do not open a feature that would show buyers an empty Pay screen or a dead Contact button
  if p_open is true and (s.upi_id is null or s.payee_name is null or s.whatsapp_number is null) then
    raise exception 'PAYMENT_INFO_MISSING';
  end if;
  update settings set
    transfers_open       = coalesce(p_open, transfers_open),
    transfer_cutoff_at   = case when coalesce(p_clear_cutoff, false) then null else coalesce(p_cutoff, transfer_cutoff_at) end,
    transfer_food_locked = coalesce(p_food_locked, transfer_food_locked),
    private_code_hours   = coalesce(p_code_hours, private_code_hours),
    ip_flag_threshold    = coalesce(p_ip_threshold, ip_flag_threshold)
  where id = 1;
end $function$;

-- 2. Visitors: is the transfer feature available right now, and with which rules?
--    Nothing secret: no phone numbers, no UPI ID, no counts.
--    The page shows the Transfer menu only when open is true and cutoff_passed is false.
create or replace function public.get_transfer_info() returns jsonb
 language sql stable security definer set search_path to 'public' as $function$
  select jsonb_build_object(
    'open',          s.transfers_open,
    'cutoff_at',     s.transfer_cutoff_at,
    'cutoff_passed', (s.transfer_cutoff_at is not null and now() > s.transfer_cutoff_at),
    'food_locked',   s.transfer_food_locked,
    'code_hours',    s.private_code_hours,
    'ask_price',     s.price_per_head,
    'server_now',    now())
  from settings s where s.id = 1
$function$;

-- 3. Who may call them
revoke all on function public.admin_set_transfer_settings(boolean, timestamptz, boolean, boolean, integer, integer)
  from public, anon, authenticated, service_role;
grant execute on function public.admin_set_transfer_settings(boolean, timestamptz, boolean, boolean, integer, integer) to authenticated;
revoke all on function public.get_transfer_info() from public, anon, authenticated, service_role;
grant execute on function public.get_transfer_info() to anon, authenticated;
