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

create or replace function public.private_status(p_booking_code text, p_phone text) returns jsonb
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
        'ticket_label', _ticket_label(tk.kind, tk.ticket_no, tk.coord_no),
        'status', case when x.status = 'code_active' and x.code_expires_at <= now() then 'expired' else x.status end,
        'code', case when x.status = 'code_active' and x.code_expires_at > now() then x.code end,
        'expires_at', case when x.status = 'code_active' then x.code_expires_at end,
        'buyer_name', case when x.status in ('pending_admin', 'done')
                           then (select bu.name from transfer_buyers bu where bu.transfer_id = x.id and bu.status in ('active', 'done') limit 1) end,
        'created_at', x.created_at) as j
      from transfers x join tickets tk on tk.id = x.ticket_id
     where x.booking_id = b.id and x.seller_phone = ph and x.kind = 'private'
     order by x.created_at desc limit 10) r;
  return jsonb_build_object('found', true, 'transfers', res);
end $function$;

create or replace function public.private_cancel(p_booking_code text, p_ticket text, p_phone text) returns jsonb
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
create or replace function public.private_open(p_code text) returns jsonb
 language plpgsql stable security definer set search_path to 'public' as $function$
declare s settings%rowtype; c text; x transfers%rowtype; t tickets%rowtype; b bookings%rowtype;
begin
  select * into s from settings where id = 1;
  if not s.transfers_open then return jsonb_build_object('ok', false, 'error', 'TRANSFERS_CLOSED'); end if;
  if s.transfer_cutoff_at is not null and now() > s.transfer_cutoff_at then
    return jsonb_build_object('ok', false, 'error', 'CUTOFF_PASSED'); end if;
  c := upper(regexp_replace(coalesce(p_code, ''), '[\s-]', '', 'g'));
  if c !~ '^[A-Z2-9]{6}$' then return jsonb_build_object('ok', false, 'error', 'INVALID_CODE'); end if;
  select * into x from transfers where code = c and kind = 'private' and status = 'code_active' and code_expires_at > now();
  if not found then return jsonb_build_object('ok', false, 'error', 'INVALID_CODE'); end if;
  select * into t from tickets where id = x.ticket_id;
  select * into b from bookings where id = t.booking_id;
  if t.transferred_out_at is not null or t.checked_in_at is not null or b.status <> 'paid' then
    return jsonb_build_object('ok', false, 'error', 'NOT_AVAILABLE'); end if;
  return jsonb_build_object('ok', true, 'seller_name', t.name, 'expires_at', x.code_expires_at,
                            'food_locked', s.transfer_food_locked,
                            'food', case when s.transfer_food_locked then t.food end);
end $function$;

create or replace function public.private_submit(p_code text, p_submission_id uuid, p_buyer jsonb) returns jsonb
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
  select * into x from transfers where code = c and kind = 'private' and status = 'code_active' and code_expires_at > now() for update;
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
  return jsonb_build_object('ok', true, 'booking_code', bk.booking_code, 'status', 'pending',
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
  insert into tickets (secret, booking_id, name, phone, email, location, attendance, food, kind, transferred_from)
  values (substr(replace(gen_random_uuid()::text, '-', ''), 1, 12), bk.id, bu.name, bu.phone, bu.email,
          bu.location, bu.attendance, bu.food, 'guest', t.id)
  returning * into nt;
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
      -- or a coordinator number retired by an approved transfer: show who holds the seat now
      select tk.* into t from ticket_transfers x join tickets tk on tk.id = x.ticket_id
       where x.from_coord_no = p_ticket_no and x.status = 'done';
      if found then
        return jsonb_build_object('result', 'cancelled', 'name', t.name,
          'label', coalesce(_ticket_label(t.kind, t.ticket_no, t.coord_no), 'not numbered yet'),
          'old_label', _ticket_label('coordinator', null, p_ticket_no));
      end if;
    end if;
  else
    select * into t from tickets where ticket_no = p_ticket_no for update;
    if not found and p_ticket_no is not null then
      -- a number retired by an approved transfer: the QR is cancelled, show who holds the seat now
      select tk.* into t from ticket_transfers x join tickets tk on tk.id = x.ticket_id
       where x.from_ticket_no = p_ticket_no and x.status = 'done';
      if found then
        return jsonb_build_object('result', 'cancelled', 'name', t.name,
          'label', coalesce(_ticket_label(t.kind, t.ticket_no, t.coord_no), 'not numbered yet'),
          'old_label', _ticket_label('guest', p_ticket_no, null));
      end if;
    end if;
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
revoke all on function public.private_sell(text, text, text), public.private_status(text, text), public.private_cancel(text, text, text),
  public.private_open(text), public.private_submit(text, uuid, jsonb) from public;
grant execute on function public.private_sell(text, text, text), public.private_status(text, text), public.private_cancel(text, text, text),
  public.private_open(text), public.private_submit(text, uuid, jsonb) to anon, authenticated;
revoke all on function public.admin_transfer_confirm_call(uuid, boolean), public.admin_transfer_approve(uuid),
  public.admin_transfer_reject(uuid, text) from public, anon;
grant execute on function public.admin_transfer_confirm_call(uuid, boolean), public.admin_transfer_approve(uuid),
  public.admin_transfer_reject(uuid, text) to authenticated;
