-- ============================================================================
-- Release 2, Step 1, piece 4 (REWRITTEN 17 Oct 2026): PUBLIC TRANSFER, admin-matched
-- Sellers send a listing request; buyers send an interest form (1 to 5 people);
-- ONLY the admin sees both sides and matches them by hand. No public board, no timers.
-- Tested on the scratch database before use.
-- REQUIRES r2_01, r2_02 and r2_03 first. Supersedes these piece-3 functions (same names, extended):
--   _close_open_transfers, private_sell, lookup_tickets, admin_transfer_confirm_call.
-- Transfers stay OFF until settings.transfers_open is set.
-- ============================================================================

-- 1. Listing side: more statuses and the listing fields (price, payout ID, reason, pending change)
alter table public.transfers drop constraint if exists transfers_status_check;
alter table public.transfers add constraint transfers_status_check check (status in
  ('code_active', 'listing_pending', 'listed', 'matched', 'pending_admin', 'done', 'rejected', 'withdrawn', 'replaced'));
alter table public.transfers add column if not exists price integer check (price is null or price >= 0);
alter table public.transfers add column if not exists seller_upi text
  check (seller_upi is null or seller_upi ~ '^([0-9]{10}|[A-Za-z0-9._-]{2,64}@[A-Za-z][A-Za-z0-9]{1,31})$');
alter table public.transfers add column if not exists reason text check (reason is null or char_length(reason) <= 300);
alter table public.transfers add column if not exists listed_at timestamptz;
alter table public.transfers add column if not exists listed_by uuid references auth.users(id);
alter table public.transfers add column if not exists edit_price integer check (edit_price is null or edit_price >= 0);
alter table public.transfers add column if not exists edit_upi text
  check (edit_upi is null or edit_upi ~ '^([0-9]{10}|[A-Za-z0-9._-]{2,64}@[A-Za-z][A-Za-z0-9]{1,31})$');
alter table public.transfers add column if not exists edit_reason text check (edit_reason is null or char_length(edit_reason) <= 300);
alter table public.transfers add column if not exists edit_requested_at timestamptz;
alter table public.transfers add column if not exists seller_paid_at timestamptz;
alter table public.transfers add column if not exists seller_paid_by uuid references auth.users(id);
alter table public.transfers add column if not exists payout_reference text check (payout_reference is null or char_length(payout_reference) between 3 and 80);
alter table public.transfers drop constraint if exists transfers_public_fields;
alter table public.transfers add constraint transfers_public_fields check (kind <> 'public' or (price is not null and seller_upi is not null and reason is not null));
drop index if exists public.transfers_one_open_per_ticket;
create unique index transfers_one_open_per_ticket on public.transfers (ticket_id)
  where status in ('code_active', 'listing_pending', 'listed', 'matched', 'pending_admin');

-- 2. Buyer side: an interest form (1 to 5 people), matches, and one payment per confirmed group of matches
create table if not exists public.transfer_interests (
  id uuid primary key default gen_random_uuid(),
  booking_id uuid not null unique references public.bookings(id) on delete cascade,
  submission_id uuid not null unique,
  all_together boolean not null default false,
  consent_at timestamptz not null,
  status text not null default 'waiting' check (status in ('waiting', 'done', 'revoked')),
  note text check (note is null or char_length(note) <= 300),
  revoked_at timestamptz,
  revoked_by uuid references auth.users(id),
  created_at timestamptz not null default now()
);
create table if not exists public.transfer_interest_people (
  id uuid primary key default gen_random_uuid(),
  interest_id uuid not null references public.transfer_interests(id) on delete cascade,
  position integer not null check (position between 1 and 5),
  name text not null check (char_length(name) between 1 and 80),
  phone text not null check (phone ~ '^[0-9]{10}$'),
  email text not null check (char_length(email) between 5 and 120 and email ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$'),
  location text not null check (location in ('In Bengaluru', 'Outside Bengaluru')),
  attendance text not null check (attendance in ('Surely', 'Most probably')),
  food text check (food is null or food in ('Veg', 'Non-veg')),
  max_price integer check (max_price is null or max_price >= 0),
  status text not null default 'waiting' check (status in ('waiting', 'matched', 'done', 'revoked')),
  unique (interest_id, position)
);
create table if not exists public.transfer_payments (
  id uuid primary key default gen_random_uuid(),
  interest_id uuid not null references public.transfer_interests(id) on delete cascade,
  amount integer not null check (amount >= 0),
  status text not null default 'awaiting' check (status in ('awaiting', 'submitted', 'verified', 'void')),
  submission_id uuid unique,
  screenshot_path text,
  submitted_at timestamptz,
  verified_at timestamptz,
  verified_by uuid references auth.users(id),
  amount_received integer check (amount_received is null or amount_received >= 0),
  created_at timestamptz not null default now(),
  created_by uuid references auth.users(id)
);
create table if not exists public.transfer_matches (
  id uuid primary key default gen_random_uuid(),
  interest_id uuid not null references public.transfer_interests(id) on delete cascade,
  person_id uuid not null references public.transfer_interest_people(id) on delete cascade,
  listing_id uuid not null references public.transfers(id) on delete cascade,
  price integer not null check (price >= 0),
  status text not null default 'held' check (status in ('held', 'confirmed', 'done', 'released')),
  matched_at timestamptz not null default now(),
  matched_by uuid references auth.users(id),
  confirmed_at timestamptz,
  confirmed_by uuid references auth.users(id),
  payment_id uuid references public.transfer_payments(id),
  released_at timestamptz,
  released_by uuid references auth.users(id),
  release_note text check (release_note is null or char_length(release_note) <= 300),
  return_due boolean not null default false,
  returned_at timestamptz,
  returned_by uuid references auth.users(id),
  return_reference text check (return_reference is null or char_length(return_reference) between 3 and 80),
  result_ticket_id uuid references public.tickets(id) on delete set null
);
create unique index if not exists transfer_matches_one_live_per_person on public.transfer_matches (person_id) where status in ('held', 'confirmed');
create unique index if not exists transfer_matches_one_live_per_listing on public.transfer_matches (listing_id) where status in ('held', 'confirmed');
create index if not exists transfer_matches_interest_idx on public.transfer_matches (interest_id);
create index if not exists transfer_interest_people_phone_idx on public.transfer_interest_people (phone);

alter table public.transfer_interests enable row level security;
alter table public.transfer_interest_people enable row level security;
alter table public.transfer_payments enable row level security;
alter table public.transfer_matches enable row level security;
drop policy if exists admin_read_transfer_interests on public.transfer_interests;
create policy admin_read_transfer_interests on public.transfer_interests for select to authenticated using (is_admin());
drop policy if exists admin_read_transfer_interest_people on public.transfer_interest_people;
create policy admin_read_transfer_interest_people on public.transfer_interest_people for select to authenticated using (is_admin());
drop policy if exists admin_read_transfer_payments on public.transfer_payments;
create policy admin_read_transfer_payments on public.transfer_payments for select to authenticated using (is_admin());
drop policy if exists admin_read_transfer_matches on public.transfer_matches;
create policy admin_read_transfer_matches on public.transfer_matches for select to authenticated using (is_admin());
revoke all on table public.transfer_interests, public.transfer_interest_people, public.transfer_payments, public.transfer_matches
  from public, anon, authenticated, service_role;
grant select on table public.transfer_interests, public.transfer_interest_people, public.transfer_payments, public.transfer_matches to authenticated;

-- 3. Internal helpers (nobody outside the database can call these)
create or replace function public._seller_block(p_ticket uuid) returns text
 language plpgsql stable security definer set search_path to 'public' as $function$
declare t tickets%rowtype; b bookings%rowtype;
begin
  select * into t from tickets where id = p_ticket;
  select * into b from bookings where id = t.booking_id;
  if t.transferred_out_at is not null then return 'ALREADY_TRANSFERRED'; end if;
  if b.status <> 'paid' or t.ticket_no is null then return 'NOT_CONFIRMED'; end if;
  if t.kind <> 'guest' then return 'COORDINATOR'; end if;
  if t.checked_in_at is not null then return 'ALREADY_CHECKED_IN'; end if;
  return null;
end $function$;

create or replace function public._clean_reason(p text) returns text language sql immutable as $$
  select btrim(regexp_replace(coalesce(p, ''), '\s+', ' ', 'g')) $$;

-- one match goes back: the listing becomes available again, the person waits again, money is marked due if it was paid
create or replace function public._release_match(p_match uuid, p_reason text) returns void
 language plpgsql security definer set search_path to 'public' as $function$
declare m transfer_matches%rowtype; pay transfer_payments%rowtype; due boolean := false; remaining integer;
begin
  select * into m from transfer_matches where id = p_match for update;
  if not found or m.status not in ('held', 'confirmed') then return; end if;
  if m.payment_id is not null then
    select * into pay from transfer_payments where id = m.payment_id for update;
    due := pay.status in ('submitted', 'verified');
  end if;
  update transfer_matches set status = 'released', released_at = now(), released_by = auth.uid(),
         release_note = left(p_reason, 300), return_due = due where id = m.id;
  update transfer_interest_people set status = 'waiting' where id = m.person_id and status = 'matched';
  update transfers set status = 'listed', updated_at = now() where id = m.listing_id and status = 'matched';
  if m.payment_id is not null and pay.status = 'awaiting' then
    select count(*) into remaining from transfer_matches where payment_id = pay.id and status = 'confirmed';
    if remaining = 0 then update transfer_payments set status = 'void' where id = pay.id;
    else update transfer_payments set amount = (select coalesce(sum(price), 0) from transfer_matches where payment_id = pay.id and status = 'confirmed') where id = pay.id;
    end if;
  end if;
  perform _tlog('match released', m.status, left(m.id::text, 8) || ': ' || left(p_reason, 120) || case when due then ' (RETURN DUE)' else '' end);
end $function$;

-- a buyer who ticked "all together" loses ALL their matches when one goes back
create or replace function public._release_cascade(p_match uuid, p_reason text) returns void
 language plpgsql security definer set search_path to 'public' as $function$
declare m transfer_matches%rowtype; it transfer_interests%rowtype; r record;
begin
  select * into m from transfer_matches where id = p_match;
  if not found then return; end if;
  select * into it from transfer_interests where id = m.interest_id for update;
  if it.all_together then
    for r in select id from transfer_matches where interest_id = it.id and status in ('held', 'confirmed') order by id loop
      perform _release_match(r.id, p_reason);
    end loop;
  else
    perform _release_match(m.id, p_reason);
  end if;
end $function$;

create or replace function public._revoke_interest(p_interest uuid, p_reason text) returns boolean
 language plpgsql security definer set search_path to 'public' as $function$
declare it transfer_interests%rowtype; r record;
begin
  select * into it from transfer_interests where id = p_interest for update;
  if not found or it.status <> 'waiting' then return false; end if;
  for r in select id from transfer_matches where interest_id = it.id and status in ('held', 'confirmed') order by id loop
    perform _release_match(r.id, p_reason);
  end loop;
  update transfer_interest_people set status = 'revoked' where interest_id = it.id and status in ('waiting', 'matched');
  update transfer_interests set status = 'revoked', revoked_at = now(), revoked_by = auth.uid(), note = left(p_reason, 300) where id = it.id;
  update bookings set status = 'rejected', reviewed_by = auth.uid(), reviewed_at = now(), reviewed_via = 'admin'
   where id = it.booking_id and not exists (select 1 from tickets where booking_id = it.booking_id);
  perform _tlog('interest revoked', null, left(it.id::text, 8) || ': ' || left(p_reason, 120));
  return true;
end $function$;

-- the swap for one person: a NEW ticket in the buyer's booking, the seller's ticket cancelled for good
create or replace function public._do_swap(p_seller_ticket uuid, p_booking uuid, p_person transfer_interest_people) returns uuid
 language plpgsql security definer set search_path to 'public' as $function$
declare t tickets%rowtype; sb bookings%rowtype; s settings%rowtype; nt tickets%rowtype; v_food text;
begin
  select * into s from settings where id = 1;
  select * into t from tickets where id = p_seller_ticket for update;
  select * into sb from bookings where id = t.booking_id for update;
  if t.transferred_out_at is not null then raise exception 'SELLER_ALREADY_TRANSFERRED'; end if;
  if t.checked_in_at is not null then raise exception 'SELLER_CHECKED_IN'; end if;
  if sb.status <> 'paid' or t.kind <> 'guest' or t.ticket_no is null then raise exception 'SELLER_TICKET_INVALID'; end if;
  v_food := case when s.transfer_food_locked then t.food else coalesce(p_person.food, t.food) end;
  insert into tickets (secret, booking_id, name, phone, email, location, attendance, food, kind, transferred_from)
  values (substr(replace(gen_random_uuid()::text, '-', ''), 1, 12), p_booking, p_person.name, p_person.phone, p_person.email,
          p_person.location, p_person.attendance, v_food, 'guest', t.id)
  returning * into nt;
  update tickets set transferred_out_at = now() where id = t.id;
  update bookings set status = 'paid', reviewed_by = auth.uid(), reviewed_at = now(), reviewed_via = 'admin' where id = p_booking;
  perform _assign_numbers(p_booking);
  return nt.id;
end $function$;

-- closes every open transfer of a seller booking (used when an admin rejects or reopens that booking)
create or replace function public._close_open_transfers(p_booking uuid, p_reason text) returns void
 language plpgsql security definer set search_path to 'public' as $function$
declare x record; mm record;
begin
  for x in select id, status, kind from transfers where booking_id = p_booking
           and status in ('code_active', 'listing_pending', 'listed', 'matched', 'pending_admin') for update loop
    if x.kind = 'public' and x.status = 'matched' then
      for mm in select id from transfer_matches where listing_id = x.id and status in ('held', 'confirmed') loop
        perform _release_cascade(mm.id, 'seller booking closed: ' || p_reason);
      end loop;
    end if;
    update transfers set status = 'withdrawn', decision_note = left(p_reason, 300), decided_at = now(),
           decided_by = auth.uid(), updated_at = now(),
           edit_price = null, edit_upi = null, edit_reason = null, edit_requested_at = null where id = x.id;
    if x.kind = 'private' then
      update bookings set status = 'rejected', reviewed_by = auth.uid(), reviewed_at = now(), reviewed_via = 'admin'
       where id in (select booking_id from transfer_buyers where transfer_id = x.id and status = 'active');
      update transfer_buyers set status = 'released' where transfer_id = x.id and status = 'active';
    end if;
    perform _tlog(x.kind || ' transfer closed automatically', x.status, left(x.id::text, 8) || ': ' || p_reason);
  end loop;
end $function$;

-- 4. Private sell, now aware of public listings
create or replace function public.private_sell(p_booking_code text, p_ticket text, p_phone text) returns jsonb
 language plpgsql security definer set search_path to 'public' as $function$
declare s settings%rowtype; tid uuid; t tickets%rowtype; b bookings%rowtype; x transfers%rowtype; code text; lbl text; blocked text;
begin
  select * into s from settings where id = 1;
  if not s.transfers_open then return jsonb_build_object('ok', false, 'error', 'TRANSFERS_CLOSED'); end if;
  if s.transfer_cutoff_at is not null and now() > s.transfer_cutoff_at then
    return jsonb_build_object('ok', false, 'error', 'CUTOFF_PASSED'); end if;
  tid := _find_seller_ticket(p_booking_code, p_ticket, p_phone);
  if tid is null then return jsonb_build_object('ok', false, 'error', 'MISMATCH'); end if;
  select * into t from tickets where id = tid for update;
  select * into b from bookings where id = t.booking_id;
  blocked := _seller_block(t.id);
  if blocked is not null then return jsonb_build_object('ok', false, 'error', blocked); end if;
  lbl := _ticket_label(t.kind, t.ticket_no, t.coord_no);
  select * into x from transfers where ticket_id = t.id
     and status in ('code_active', 'listing_pending', 'listed', 'matched', 'pending_admin') for update;
  if found then
    if x.kind = 'private' and x.status = 'pending_admin' then return jsonb_build_object('ok', false, 'error', 'ALREADY_PENDING'); end if;
    if x.kind <> 'private' then return jsonb_build_object('ok', false, 'error', 'ALREADY_OPEN', 'kind', x.kind); end if;
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

-- 5. SELLER side (visitors): a listing request, a change request, status
create or replace function public.public_sell(p_booking_code text, p_ticket text, p_phone text,
                                              p_reason text, p_price integer, p_upi text) returns jsonb
 language plpgsql security definer set search_path to 'public' as $function$
declare s settings%rowtype; tid uuid; t tickets%rowtype; b bookings%rowtype; x transfers%rowtype; blocked text; rs text; upi text; lbl text;
begin
  select * into s from settings where id = 1;
  if not s.transfers_open then return jsonb_build_object('ok', false, 'error', 'TRANSFERS_CLOSED'); end if;
  if s.transfer_cutoff_at is not null and now() > s.transfer_cutoff_at then
    return jsonb_build_object('ok', false, 'error', 'CUTOFF_PASSED'); end if;
  tid := _find_seller_ticket(p_booking_code, p_ticket, p_phone);
  if tid is null then return jsonb_build_object('ok', false, 'error', 'MISMATCH'); end if;
  select * into t from tickets where id = tid for update;
  select * into b from bookings where id = t.booking_id;
  blocked := _seller_block(t.id);
  if blocked is not null then return jsonb_build_object('ok', false, 'error', blocked); end if;
  rs := _clean_reason(p_reason);
  if length(rs) not between 3 and 300 then return jsonb_build_object('ok', false, 'error', 'INVALID_REASON'); end if;
  if p_price is null or p_price < s.resale_min_price or p_price > s.max_resale_price then
    return jsonb_build_object('ok', false, 'error', 'PRICE_OUT_OF_RANGE', 'min', s.resale_min_price, 'max', s.max_resale_price); end if;
  upi := btrim(coalesce(p_upi, ''));
  if upi !~ '^([0-9]{10}|[A-Za-z0-9._-]{2,64}@[A-Za-z][A-Za-z0-9]{1,31})$' then return jsonb_build_object('ok', false, 'error', 'INVALID_UPI'); end if;
  lbl := _ticket_label(t.kind, t.ticket_no, t.coord_no);
  select * into x from transfers where ticket_id = t.id
     and status in ('code_active', 'listing_pending', 'listed', 'matched', 'pending_admin') for update;
  if found then return jsonb_build_object('ok', false, 'error', 'ALREADY_OPEN', 'kind', x.kind); end if;
  begin
    insert into transfers (kind, ticket_id, booking_id, seller_name, seller_phone, status, price, seller_upi, reason)
    values ('public', t.id, b.id, t.name, t.phone, 'listing_pending', p_price, upi, rs) returning * into x;
  exception when unique_violation then
    return jsonb_build_object('ok', false, 'error', 'TRY_AGAIN');
  end;
  perform _tlog('public listing: requested', null, lbl || ' at ' || p_price || ' (' || left(x.id::text, 8) || ')');
  return jsonb_build_object('ok', true, 'status', 'listing_pending', 'ticket_label', lbl, 'price', p_price);
end $function$;

create or replace function public.public_edit(p_booking_code text, p_ticket text, p_phone text,
                                              p_reason text, p_price integer, p_upi text) returns jsonb
 language plpgsql security definer set search_path to 'public' as $function$
declare s settings%rowtype; tid uuid; x transfers%rowtype; rs text; upi text; t tickets%rowtype;
begin
  select * into s from settings where id = 1;
  if not s.transfers_open then return jsonb_build_object('ok', false, 'error', 'TRANSFERS_CLOSED'); end if;
  tid := _find_seller_ticket(p_booking_code, p_ticket, p_phone);
  if tid is null then return jsonb_build_object('ok', false, 'error', 'MISMATCH'); end if;
  select * into t from tickets where id = tid for update;
  select * into x from transfers where ticket_id = tid and kind = 'public'
     and status in ('listing_pending', 'listed', 'matched') for update;
  if not found then return jsonb_build_object('ok', false, 'error', 'NOTHING_TO_EDIT'); end if;
  if x.status <> 'listed' then return jsonb_build_object('ok', false, 'error', 'EDIT_BLOCKED', 'status', x.status); end if;
  rs := _clean_reason(p_reason);
  if length(rs) not between 3 and 300 then return jsonb_build_object('ok', false, 'error', 'INVALID_REASON'); end if;
  if p_price is null or p_price < s.resale_min_price or p_price > s.max_resale_price then
    return jsonb_build_object('ok', false, 'error', 'PRICE_OUT_OF_RANGE', 'min', s.resale_min_price, 'max', s.max_resale_price); end if;
  upi := btrim(coalesce(p_upi, ''));
  if upi !~ '^([0-9]{10}|[A-Za-z0-9._-]{2,64}@[A-Za-z][A-Za-z0-9]{1,31})$' then return jsonb_build_object('ok', false, 'error', 'INVALID_UPI'); end if;
  update transfers set edit_price = p_price, edit_upi = upi, edit_reason = rs, edit_requested_at = now(), updated_at = now() where id = x.id;
  perform _tlog('public listing: change requested', x.price::text, p_price::text || ' (' || left(x.id::text, 8) || ')');
  return jsonb_build_object('ok', true, 'status', 'edit_pending');
end $function$;

create or replace function public.public_status(p_booking_code text, p_phone text) returns jsonb
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
        'status', x.status, 'price', x.price, 'seller_upi', x.seller_upi,
        'edit_pending', (x.edit_requested_at is not null), 'edit_price', x.edit_price,
        'payout', case when x.status = 'done' then case when x.seller_paid_at is not null then 'paid' else 'to_be_paid' end end,
        'created_at', x.created_at) as j
      from transfers x join tickets tk on tk.id = x.ticket_id
     where x.booking_id = b.id and x.seller_phone = ph and x.kind = 'public'
     order by x.created_at desc limit 10) r;
  return jsonb_build_object('found', true, 'transfers', res);
end $function$;

-- 6. BUYER side (visitors): the interest form, the payment, revoking
create or replace function public.interest_submit(p_submission_id uuid, p_people jsonb, p_all_together boolean, p_consent boolean) returns jsonb
 language plpgsql security definer set search_path to 'public' as $function$
declare s settings%rowtype; n integer; i integer; p jsonb; bk bookings%rowtype; it transfer_interests%rowtype; bcode text;
        v_name text; v_phone text; v_email text; v_food text; v_max integer; v_loc text; v_att text; open_count integer;
begin
  if p_submission_id is null then return jsonb_build_object('ok', false, 'error', 'INVALID_DATA'); end if;
  select * into it from transfer_interests where submission_id = p_submission_id;
  if found then
    select * into bk from bookings where id = it.booking_id;
    return jsonb_build_object('ok', true, 'booking_code', bk.booking_code, 'replay', true);
  end if;
  select * into s from settings where id = 1;
  if not s.transfers_open then return jsonb_build_object('ok', false, 'error', 'TRANSFERS_CLOSED'); end if;
  if s.transfer_cutoff_at is not null and now() > s.transfer_cutoff_at then
    return jsonb_build_object('ok', false, 'error', 'CUTOFF_PASSED'); end if;
  if p_consent is not true then return jsonb_build_object('ok', false, 'error', 'INVALID_CONSENT'); end if;
  if p_people is null or jsonb_typeof(p_people) <> 'array' then return jsonb_build_object('ok', false, 'error', 'INVALID_PEOPLE'); end if;
  n := jsonb_array_length(p_people);
  if n not between 1 and 5 then return jsonb_build_object('ok', false, 'error', 'INVALID_PEOPLE'); end if;
  for i in 0..n - 1 loop
    p := p_people -> i;
    if jsonb_typeof(p) <> 'object' then return jsonb_build_object('ok', false, 'error', 'INVALID_PEOPLE'); end if;
    v_name := btrim(coalesce(p->>'name', '')); v_email := lower(btrim(coalesce(p->>'email', '')));
    if length(v_name) not between 1 and 80 then return jsonb_build_object('ok', false, 'error', 'INVALID_NAME', 'person', i + 1); end if;
    if coalesce(p->>'phone', '') !~ '^[0-9]{10}$' then return jsonb_build_object('ok', false, 'error', 'INVALID_PHONE', 'person', i + 1); end if;
    if length(v_email) not between 5 and 120 or v_email !~ '^[^@\s]+@[^@\s]+\.[^@\s]+$' then return jsonb_build_object('ok', false, 'error', 'INVALID_EMAIL', 'person', i + 1); end if;
    if coalesce(p->>'loc', '') not in ('In Bengaluru', 'Outside Bengaluru') then return jsonb_build_object('ok', false, 'error', 'INVALID_LOCATION', 'person', i + 1); end if;
    if coalesce(p->>'att', '') not in ('Surely', 'Most probably') then return jsonb_build_object('ok', false, 'error', 'INVALID_ATTENDANCE', 'person', i + 1); end if;
    if not s.transfer_food_locked and coalesce(p->>'food', '') not in ('Veg', 'Non-veg') then return jsonb_build_object('ok', false, 'error', 'INVALID_FOOD', 'person', i + 1); end if;
    if s.interest_max_price_enabled and nullif(btrim(coalesce(p->>'max_price', '')), '') is not null then
      if btrim(p->>'max_price') !~ '^[0-9]{1,6}$' or btrim(p->>'max_price')::integer > s.max_resale_price then
        return jsonb_build_object('ok', false, 'error', 'INVALID_MAX_PRICE', 'person', i + 1, 'max', s.max_resale_price); end if;
    end if;
  end loop;
  select count(*) into open_count from transfer_interests ti join transfer_interest_people tp on tp.interest_id = ti.id and tp.position = 1
   where ti.status = 'waiting' and tp.phone = p_people->0->>'phone';
  if open_count >= 3 then return jsonb_build_object('ok', false, 'error', 'TOO_MANY_OPEN'); end if;
  begin
    loop
      bcode := upper(substr(replace(gen_random_uuid()::text, '-', ''), 1, 8));
      exit when not exists (select 1 from bookings where booking_code = bcode);
    end loop;
    insert into bookings (booking_code, submission_id, people_count, amount_expected, screenshot_path, kind)
    values (bcode, p_submission_id, n, 0, null, 'transfer') returning * into bk;
    insert into transfer_interests (booking_id, submission_id, all_together, consent_at)
    values (bk.id, p_submission_id, coalesce(p_all_together, false), now()) returning * into it;
    for i in 0..n - 1 loop
      p := p_people -> i;
      v_food := case when s.transfer_food_locked then null else p->>'food' end;
      v_max := case when s.interest_max_price_enabled and nullif(btrim(coalesce(p->>'max_price', '')), '') is not null
                    then btrim(p->>'max_price')::integer else null end;
      insert into transfer_interest_people (interest_id, position, name, phone, email, location, attendance, food, max_price)
      values (it.id, i + 1, btrim(p->>'name'), p->>'phone', lower(btrim(p->>'email')), p->>'loc', p->>'att', v_food, v_max);
    end loop;
  exception when unique_violation then
    return jsonb_build_object('ok', false, 'error', 'TRY_AGAIN');
  end;
  perform _tlog('interest: form submitted', null, n || ' person(s)' || case when it.all_together then ', all together' else '' end || ' (' || left(it.id::text, 8) || ')');
  return jsonb_build_object('ok', true, 'booking_code', bk.booking_code, 'people', n, 'all_together', it.all_together);
end $function$;

create or replace function public.interest_pay(p_booking_code text, p_phone text, p_payment_id uuid, p_submission_id uuid, p_screenshot_path text) returns jsonb
 language plpgsql security definer set search_path to 'public' as $function$
declare c text; ph text; b bookings%rowtype; it transfer_interests%rowtype; pay transfer_payments%rowtype; s settings%rowtype;
begin
  c  := replace(replace(replace(upper(coalesce(p_booking_code, '')), 'O', '0'), ' ', ''), '-', '');
  ph := replace(replace(coalesce(p_phone, ''), ' ', ''), '-', '');
  if length(c) <> 8 or ph !~ '^[0-9]{10}$' or p_payment_id is null or p_submission_id is null then return jsonb_build_object('ok', false, 'error', 'MISMATCH'); end if;
  select * into b from bookings where booking_code = c and kind = 'transfer';
  if not found then return jsonb_build_object('ok', false, 'error', 'MISMATCH'); end if;
  select * into it from transfer_interests where booking_id = b.id;
  if not found or not exists (select 1 from transfer_interest_people where interest_id = it.id and phone = ph) then
    return jsonb_build_object('ok', false, 'error', 'MISMATCH'); end if;
  select * into pay from transfer_payments where id = p_payment_id and interest_id = it.id for update;
  if not found then return jsonb_build_object('ok', false, 'error', 'MISMATCH'); end if;
  if pay.submission_id = p_submission_id then return jsonb_build_object('ok', true, 'replay', true, 'amount', pay.amount); end if;
  select * into s from settings where id = 1;
  if not s.transfers_open then return jsonb_build_object('ok', false, 'error', 'TRANSFERS_CLOSED'); end if;
  if pay.status <> 'awaiting' then return jsonb_build_object('ok', false, 'error', case when pay.status = 'void' then 'PAYMENT_CANCELLED' else 'ALREADY_SUBMITTED' end); end if;
  if p_screenshot_path is null or p_screenshot_path not like p_submission_id::text || '%'
     or not exists (select 1 from storage.objects where bucket_id = 'payment-proofs' and name = p_screenshot_path) then
    return jsonb_build_object('ok', false, 'error', 'SCREENSHOT_MISSING'); end if;
  update transfer_payments set status = 'submitted', submission_id = p_submission_id, screenshot_path = p_screenshot_path, submitted_at = now() where id = pay.id;
  perform _tlog('interest: payment submitted', null, pay.amount::text || ' (' || left(pay.id::text, 8) || ')');
  return jsonb_build_object('ok', true, 'amount', pay.amount);
end $function$;

create or replace function public.interest_revoke(p_booking_code text, p_phone text) returns jsonb
 language plpgsql security definer set search_path to 'public' as $function$
declare c text; ph text; b bookings%rowtype; it transfer_interests%rowtype;
begin
  c  := replace(replace(replace(upper(coalesce(p_booking_code, '')), 'O', '0'), ' ', ''), '-', '');
  ph := replace(replace(coalesce(p_phone, ''), ' ', ''), '-', '');
  if length(c) <> 8 or ph !~ '^[0-9]{10}$' then return jsonb_build_object('ok', false, 'error', 'MISMATCH'); end if;
  select * into b from bookings where booking_code = c and kind = 'transfer';
  if not found then return jsonb_build_object('ok', false, 'error', 'MISMATCH'); end if;
  select * into it from transfer_interests where booking_id = b.id for update;
  if not found or not exists (select 1 from transfer_interest_people where interest_id = it.id and phone = ph) then
    return jsonb_build_object('ok', false, 'error', 'MISMATCH'); end if;
  if it.status <> 'waiting' then return jsonb_build_object('ok', false, 'error', 'NOT_OPEN'); end if;
  -- once money has been sent, only the organizers can end it (so the return is recorded)
  if exists (select 1 from transfer_matches m join transfer_payments pay on pay.id = m.payment_id
              where m.interest_id = it.id and m.status = 'confirmed' and pay.status in ('submitted', 'verified')) then
    return jsonb_build_object('ok', false, 'error', 'CONTACT_ADMIN'); end if;
  perform _revoke_interest(it.id, 'revoked by the buyer');
  return jsonb_build_object('ok', true);
end $function$;

-- 7. Ticket lookup: Booking ID + phone also serves a buyer's interest form (status, matches, payment due)
create or replace function public.lookup_tickets(p_code text, p_phone text)
 returns jsonb
 language plpgsql
 stable security definer
 set search_path to 'public'
as $function$
declare b bookings%rowtype; c text; ph text; tk jsonb; bu transfer_buyers%rowtype; x transfers%rowtype; ti transfer_interests%rowtype;
        st text; nm text; ppl jsonb; pay jsonb; is_interest boolean := false;
begin
  c  := replace(replace(replace(upper(coalesce(p_code, '')), 'O', '0'), ' ', ''), '-', '');
  ph := replace(replace(coalesce(p_phone, ''), ' ', ''), '-', '');
  if length(c) <> 8 or ph !~ '^[0-9]{10}$' then return jsonb_build_object('found', false); end if;
  select * into b from bookings where booking_code = c;
  if not found then return jsonb_build_object('found', false); end if;
  if b.kind = 'transfer' then
    select * into ti from transfer_interests where booking_id = b.id;
    if found then
      is_interest := true;
      select tp.name into nm from transfer_interest_people tp where tp.interest_id = ti.id and tp.phone = ph order by tp.position limit 1;
      if nm is null then return jsonb_build_object('found', false); end if;
    else
      select * into bu from transfer_buyers where booking_id = b.id and phone = ph;
      if not found then return jsonb_build_object('found', false); end if;
      select * into x from transfers where id = bu.transfer_id;
      nm := bu.name;
    end if;
  end if;
  select jsonb_agg(jsonb_build_object(
           'ticket_no', t.ticket_no, 'kind', t.kind, 'coord_no', t.coord_no,
           'label', _ticket_label(t.kind, t.ticket_no, t.coord_no),
           'secret', case when b.status = 'paid' and t.transferred_out_at is null then t.secret else null end,
           'transferred', (t.transferred_out_at is not null),
           'name', t.name, 'location', t.location, 'attendance', t.attendance, 'food', t.food)
         order by t.reg_seq)
    into tk from tickets t where t.booking_id = b.id and t.phone = ph;

  if is_interest then
    select coalesce(jsonb_agg(jsonb_build_object('name', tp.name, 'status', tp.status,
             'price', (select m.price from transfer_matches m where m.person_id = tp.id and m.status in ('held', 'confirmed', 'done') limit 1))
             order by tp.position), '[]'::jsonb) into ppl from transfer_interest_people tp where tp.interest_id = ti.id;
    select jsonb_build_object('id', py.id, 'amount', py.amount, 'status', py.status) into pay from transfer_payments py
     where py.interest_id = ti.id and py.status in ('awaiting', 'submitted', 'verified')
       and exists (select 1 from transfer_matches m where m.payment_id = py.id and m.status = 'confirmed')
     order by (py.status = 'awaiting') desc, py.created_at desc limit 1;
    st := case when ti.status = 'revoked' then 'revoked'
               when ti.status = 'done' then 'done'
               when pay is not null and pay->>'status' = 'awaiting' then 'payment_due'
               when pay is not null and pay->>'status' = 'submitted' then 'payment_submitted'
               when pay is not null and pay->>'status' = 'verified' then 'payment_verified'
               when exists (select 1 from transfer_matches m where m.interest_id = ti.id and m.status = 'held') then 'matched'
               else 'waiting' end;
    return jsonb_build_object('found', true, 'kind', 'transfer', 'booking_code', b.booking_code, 'status', b.status,
             'people_count', b.people_count, 'amount_expected', 0, 'name', nm, 'tickets', coalesce(tk, '[]'::jsonb),
             'transfer', jsonb_build_object('type', 'interest', 'all_together', ti.all_together, 'state', st, 'people', ppl, 'payment', pay));
  end if;

  if tk is null then
    if b.kind = 'transfer' then
      st := case when b.status = 'rejected' then 'rejected' else 'pending' end;
      return jsonb_build_object('found', true, 'kind', 'transfer', 'booking_code', b.booking_code, 'status', b.status,
                                'people_count', 1, 'amount_expected', 0, 'name', nm, 'tickets', '[]'::jsonb,
                                'transfer', jsonb_build_object('type', x.kind, 'state', st));
    end if;
    return jsonb_build_object('found', false);
  end if;
  return jsonb_build_object('found', true, 'kind', b.kind, 'booking_code', b.booking_code, 'status', b.status,
                            'people_count', b.people_count, 'amount_expected', b.amount_expected, 'tickets', tk);
end $function$;

-- 8. ADMIN side
create or replace function public.admin_transfer_confirm_call(p_transfer uuid, p_confirmed boolean default true) returns void
 language plpgsql security definer set search_path to 'public' as $function$
declare x transfers%rowtype;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  select * into x from transfers where id = p_transfer for update;
  if not found then raise exception 'INVALID_TRANSFER'; end if;
  if x.status not in ('pending_admin', 'listing_pending') then raise exception 'NOT_PENDING'; end if;
  if p_confirmed then
    update transfers set seller_call_confirmed_at = now(), seller_call_confirmed_by = auth.uid(), updated_at = now() where id = x.id;
  else
    update transfers set seller_call_confirmed_at = null, seller_call_confirmed_by = null, updated_at = now() where id = x.id;
  end if;
  perform _tlog(x.kind || ' transfer: seller phone call ' || case when p_confirmed then 'confirmed' else 'tick removed' end, null, left(x.id::text, 8));
end $function$;

create or replace function public.admin_listing_approve(p_transfer uuid) returns void
 language plpgsql security definer set search_path to 'public' as $function$
declare x transfers%rowtype; s settings%rowtype; blocked text;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  select * into s from settings where id = 1;
  select * into x from transfers where id = p_transfer and kind = 'public' for update;
  if not found then raise exception 'INVALID_TRANSFER'; end if;
  if x.status <> 'listing_pending' then raise exception 'NOT_PENDING'; end if;
  if x.seller_call_confirmed_at is null then raise exception 'CALL_NOT_CONFIRMED'; end if;
  perform 1 from tickets where id = x.ticket_id for update;
  blocked := _seller_block(x.ticket_id);
  if blocked is not null then raise exception 'SELLER_%', blocked; end if;
  if x.price < s.resale_min_price or x.price > s.max_resale_price then raise exception 'PRICE_OUT_OF_RANGE'; end if;
  update transfers set status = 'listed', listed_at = now(), listed_by = auth.uid(), updated_at = now() where id = x.id;
  perform _tlog('public listing: APPROVED', null, 'at ' || x.price || ' (' || left(x.id::text, 8) || ')');
end $function$;

create or replace function public.admin_listing_edit_decide(p_transfer uuid, p_approve boolean) returns void
 language plpgsql security definer set search_path to 'public' as $function$
declare x transfers%rowtype; s settings%rowtype;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  select * into s from settings where id = 1;
  select * into x from transfers where id = p_transfer and kind = 'public' for update;
  if not found then raise exception 'INVALID_TRANSFER'; end if;
  if x.edit_requested_at is null then raise exception 'NO_EDIT_PENDING'; end if;
  if x.status <> 'listed' then raise exception 'EDIT_BLOCKED'; end if;
  if p_approve then
    if x.edit_price < s.resale_min_price or x.edit_price > s.max_resale_price then raise exception 'PRICE_OUT_OF_RANGE'; end if;
    update transfers set price = edit_price, seller_upi = edit_upi, reason = edit_reason,
           edit_price = null, edit_upi = null, edit_reason = null, edit_requested_at = null, updated_at = now() where id = x.id;
    perform _tlog('public listing: change APPROVED', x.price::text, x.edit_price::text || ' (' || left(x.id::text, 8) || ')');
  else
    update transfers set edit_price = null, edit_upi = null, edit_reason = null, edit_requested_at = null, updated_at = now() where id = x.id;
    perform _tlog('public listing: change REJECTED', null, left(x.id::text, 8));
  end if;
end $function$;

-- the admin can end a listing at any time; a buyer matched to it goes back to waiting (all of them, if "all together")
create or replace function public.admin_listing_revoke(p_listing uuid, p_note text default null) returns void
 language plpgsql security definer set search_path to 'public' as $function$
declare x transfers%rowtype; note text; mm record;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  select * into x from transfers where id = p_listing and kind = 'public' for update;
  if not found then raise exception 'INVALID_TRANSFER'; end if;
  if x.status not in ('listing_pending', 'listed', 'matched') then raise exception 'NOT_OPEN'; end if;
  note := nullif(btrim(coalesce(p_note, '')), '');
  if note is not null and char_length(note) > 300 then raise exception 'INVALID_NOTE'; end if;
  if x.status = 'matched' then
    for mm in select id from transfer_matches where listing_id = x.id and status in ('held', 'confirmed') loop
      perform _release_cascade(mm.id, 'listing revoked' || coalesce(': ' || note, ''));
    end loop;
  end if;
  update transfers set status = 'withdrawn', decision_note = note, decided_at = now(), decided_by = auth.uid(), updated_at = now(),
         edit_price = null, edit_upi = null, edit_reason = null, edit_requested_at = null where id = x.id;
  perform _tlog('public listing: REVOKED', x.status, left(x.id::text, 8) || coalesce(': ' || left(note, 100), ''));
end $function$;

create or replace function public.admin_interest_revoke(p_interest uuid, p_note text default null) returns void
 language plpgsql security definer set search_path to 'public' as $function$
declare note text;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  if not exists (select 1 from transfer_interests where id = p_interest) then raise exception 'INVALID_INTEREST'; end if;
  note := nullif(btrim(coalesce(p_note, '')), '');
  if note is not null and char_length(note) > 300 then raise exception 'INVALID_NOTE'; end if;
  if not _revoke_interest(p_interest, coalesce(note, 'revoked by the organizers')) then raise exception 'NOT_OPEN'; end if;
end $function$;

-- joins waiting buyers to listed tickets; pairs = [{"person": uuid, "listing": uuid}, ...]
create or replace function public.admin_transfer_match(p_pairs jsonb, p_override boolean default false) returns jsonb
 language plpgsql security definer set search_path to 'public' as $function$
declare s settings%rowtype; elem jsonb; pid uuid; lid uuid; pr transfer_interest_people%rowtype; it transfer_interests%rowtype;
        l transfers%rowtype; r record; n integer; oldest timestamptz; older integer;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  select * into s from settings where id = 1;
  if p_pairs is null or jsonb_typeof(p_pairs) <> 'array' or jsonb_array_length(p_pairs) = 0 then raise exception 'INVALID_PAIRS'; end if;
  n := jsonb_array_length(p_pairs);
  if (select count(distinct e->>'person') from jsonb_array_elements(p_pairs) e) <> n
     or (select count(distinct e->>'listing') from jsonb_array_elements(p_pairs) e) <> n then raise exception 'DUPLICATE_IN_PAIRS'; end if;
  for r in select (e->>'listing')::uuid as lid from jsonb_array_elements(p_pairs) e order by 1 loop
    perform 1 from transfers where id = r.lid for update; end loop;
  for r in select distinct tp.interest_id as iid from transfer_interest_people tp
            where tp.id in (select (e->>'person')::uuid from jsonb_array_elements(p_pairs) e) order by 1 loop
    perform 1 from transfer_interests where id = r.iid for update; end loop;
  for elem in select * from jsonb_array_elements(p_pairs) loop
    pid := (elem->>'person')::uuid; lid := (elem->>'listing')::uuid;
    select * into pr from transfer_interest_people where id = pid;
    if not found then raise exception 'PERSON_NOT_FOUND'; end if;
    select * into it from transfer_interests where id = pr.interest_id;
    if pr.status <> 'waiting' or it.status <> 'waiting' then raise exception 'PERSON_NOT_WAITING'; end if;
    select * into l from transfers where id = lid and kind = 'public';
    if not found or l.status <> 'listed' or _seller_block(l.ticket_id) is not null then raise exception 'LISTING_NOT_AVAILABLE'; end if;
    if not p_override and s.interest_max_price_enabled and pr.max_price is not null and l.price > pr.max_price then raise exception 'PRICE_ABOVE_MAX'; end if;
    if not p_override and exists (select 1 from transfer_matches where person_id = pid and listing_id = lid and status = 'released') then raise exception 'PAIR_RELEASED_BEFORE'; end if;
  end loop;
  for r in select tp.interest_id as iid, count(*) as c from transfer_interest_people tp
            where tp.id in (select (e->>'person')::uuid from jsonb_array_elements(p_pairs) e) group by tp.interest_id loop
    select * into it from transfer_interests where id = r.iid;
    if it.all_together and (select count(*) from transfer_interest_people where interest_id = r.iid and status = 'waiting') <> r.c then
      raise exception 'ALL_TOGETHER_REQUIRED'; end if;
  end loop;
  for elem in select * from jsonb_array_elements(p_pairs) loop
    pid := (elem->>'person')::uuid; lid := (elem->>'listing')::uuid;
    select * into pr from transfer_interest_people where id = pid;
    select * into l from transfers where id = lid;
    insert into transfer_matches (interest_id, person_id, listing_id, price, matched_by) values (pr.interest_id, pid, lid, l.price, auth.uid());
    update transfer_interest_people set status = 'matched' where id = pid;
    update transfers set status = 'matched', updated_at = now() where id = lid;
    perform _tlog('match created', null, left(lid::text, 8) || ' at ' || l.price);
  end loop;
  select min(ti.created_at) into oldest from transfer_interests ti where ti.id in
    (select tp.interest_id from transfer_interest_people tp where tp.id in (select (e->>'person')::uuid from jsonb_array_elements(p_pairs) e));
  select count(*) into older from transfer_interests i2 where i2.status = 'waiting' and i2.created_at < oldest
     and exists (select 1 from transfer_interest_people where interest_id = i2.id and status = 'waiting');
  return jsonb_build_object('matches', n, 'older_waiting', older);
end $function$;

-- after the phone call "a ticket is available, shall I proceed?": confirms ALL held matches of that buyer and asks for ONE payment
create or replace function public.admin_match_confirm(p_interest uuid) returns jsonb
 language plpgsql security definer set search_path to 'public' as $function$
declare it transfer_interests%rowtype; total integer; pay transfer_payments%rowtype; cnt integer;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  select * into it from transfer_interests where id = p_interest for update;
  if not found then raise exception 'INVALID_INTEREST'; end if;
  if it.status <> 'waiting' then raise exception 'NOT_OPEN'; end if;
  select count(*), coalesce(sum(price), 0) into cnt, total from transfer_matches where interest_id = it.id and status = 'held';
  if cnt = 0 then raise exception 'NO_HELD_MATCH'; end if;
  insert into transfer_payments (interest_id, amount, status, created_by, verified_at, verified_by, amount_received)
  values (it.id, total, case when total = 0 then 'verified' else 'awaiting' end, auth.uid(),
          case when total = 0 then now() end, case when total = 0 then auth.uid() end, case when total = 0 then 0 end)
  returning * into pay;
  update transfer_matches set status = 'confirmed', confirmed_at = now(), confirmed_by = auth.uid(), payment_id = pay.id
   where interest_id = it.id and status = 'held';
  perform _tlog('match confirmed by buyer (phone call)', null, cnt || ' ticket(s), ' || total || ' (' || left(it.id::text, 8) || ')');
  return jsonb_build_object('payment_id', pay.id, 'amount', total, 'tickets', cnt);
end $function$;

create or replace function public.admin_match_release(p_match uuid, p_note text default null) returns void
 language plpgsql security definer set search_path to 'public' as $function$
declare m transfer_matches%rowtype; note text;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  select * into m from transfer_matches where id = p_match;
  if not found then raise exception 'INVALID_MATCH'; end if;
  if m.status not in ('held', 'confirmed') then raise exception 'NOT_OPEN'; end if;
  note := nullif(btrim(coalesce(p_note, '')), '');
  if note is not null and char_length(note) > 300 then raise exception 'INVALID_NOTE'; end if;
  perform _release_cascade(p_match, coalesce(note, 'released by the organizers'));
end $function$;

create or replace function public.admin_payment_verify(p_payment uuid, p_amount integer) returns void
 language plpgsql security definer set search_path to 'public' as $function$
declare pay transfer_payments%rowtype;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  select * into pay from transfer_payments where id = p_payment for update;
  if not found then raise exception 'INVALID_PAYMENT'; end if;
  if pay.status <> 'submitted' then raise exception 'NOT_SUBMITTED'; end if;
  if p_amount is null or p_amount <> pay.amount then raise exception 'AMOUNT_MISMATCH'; end if;
  update transfer_payments set status = 'verified', verified_at = now(), verified_by = auth.uid(), amount_received = p_amount where id = pay.id;
  perform _tlog('payment VERIFIED', null, p_amount::text || ' (' || left(pay.id::text, 8) || ')');
end $function$;

-- THE TRANSFER BUTTON: one person's swap (or all of a "together" buyer's, in one step)
create or replace function public.admin_match_transfer(p_match uuid) returns jsonb
 language plpgsql security definer set search_path to 'public' as $function$
declare m transfer_matches%rowtype; it transfer_interests%rowtype; pay transfer_payments%rowtype; r record; pr transfer_interest_people%rowtype;
        l transfers%rowtype; nt uuid; lbls jsonb := '[]'::jsonb; ntk tickets%rowtype; old_lbl text; st tickets%rowtype;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  perform 1 from settings where id = 1 for update;                       -- same lock order as set_booking_status
  select * into m from transfer_matches where id = p_match;
  if not found then raise exception 'INVALID_MATCH'; end if;
  select * into it from transfer_interests where id = m.interest_id for update;
  if it.status <> 'waiting' then raise exception 'NOT_OPEN'; end if;
  for r in select id from transfer_matches where interest_id = it.id and status = 'confirmed'
           and (it.all_together or id = p_match) order by listing_id loop
    select * into m from transfer_matches where id = r.id for update;
    if m.status <> 'confirmed' then raise exception 'NOT_CONFIRMED'; end if;
    select * into pay from transfer_payments where id = m.payment_id;
    if pay.status <> 'verified' then raise exception 'PAYMENT_NOT_VERIFIED'; end if;
  end loop;
  if not exists (select 1 from transfer_matches where id = p_match and status = 'confirmed') then raise exception 'NOT_CONFIRMED'; end if;
  for r in select id from transfer_matches where interest_id = it.id and status = 'confirmed'
           and (it.all_together or id = p_match) order by listing_id loop
    select * into m from transfer_matches where id = r.id;
    select * into l from transfers where id = m.listing_id for update;
    select * into pr from transfer_interest_people where id = m.person_id;
    select * into st from tickets where id = l.ticket_id;
    old_lbl := _ticket_label(st.kind, st.ticket_no, st.coord_no);
    nt := _do_swap(l.ticket_id, it.booking_id, pr);
    select * into ntk from tickets where id = nt;
    update transfers set status = 'done', decided_at = now(), decided_by = auth.uid(), result_ticket_id = nt, updated_at = now() where id = l.id;
    update transfer_matches set status = 'done', result_ticket_id = nt where id = m.id;
    update transfer_interest_people set status = 'done' where id = m.person_id;
    lbls := lbls || jsonb_build_array(jsonb_build_object('old_label', old_lbl, 'new_label', _ticket_label(ntk.kind, ntk.ticket_no, ntk.coord_no)));
    perform _tlog('public transfer: APPROVED', old_lbl, _ticket_label(ntk.kind, ntk.ticket_no, ntk.coord_no) || ' (' || left(l.id::text, 8) || ')');
  end loop;
  if not exists (select 1 from transfer_interest_people where interest_id = it.id and status in ('waiting', 'matched')) then
    update transfer_interests set status = 'done' where id = it.id; end if;
  return jsonb_build_object('transferred', lbls);
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
  perform _tlog('public transfer: seller PAID', x.price::text, left(x.id::text, 8));
end $function$;

create or replace function public.admin_transfer_mark_returned(p_match uuid, p_reference text) returns void
 language plpgsql security definer set search_path to 'public' as $function$
declare m transfer_matches%rowtype; ref text;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  select * into m from transfer_matches where id = p_match for update;
  if not found then raise exception 'INVALID_MATCH'; end if;
  if not m.return_due then raise exception 'NO_RETURN_DUE'; end if;
  if m.returned_at is not null then raise exception 'ALREADY_RETURNED'; end if;
  ref := btrim(coalesce(p_reference, ''));
  if char_length(ref) not between 3 and 80 then raise exception 'INVALID_REFERENCE'; end if;
  update transfer_matches set returned_at = now(), returned_by = auth.uid(), return_reference = ref where id = m.id;
  perform _tlog('public transfer: money RETURNED to buyer', m.price::text, left(m.id::text, 8));
end $function$;

create or replace function public.admin_transfer_money() returns jsonb
 language plpgsql stable security definer set search_path to 'public' as $function$
declare r jsonb;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  select jsonb_build_object(
    'awaiting_payment', (select jsonb_build_object('count', count(*), 'amount', coalesce(sum(amount), 0)) from transfer_payments where status = 'awaiting'),
    'awaiting_verification', (select jsonb_build_object('count', count(*), 'amount', coalesce(sum(amount), 0)) from transfer_payments where status = 'submitted'),
    'verified_waiting_transfer', (select jsonb_build_object('count', count(*), 'amount', coalesce(sum(m.price), 0)) from transfer_matches m
        join transfer_payments p on p.id = m.payment_id where m.status = 'confirmed' and p.status = 'verified'),
    'to_pay_out', (select jsonb_build_object('count', count(*), 'amount', coalesce(sum(price), 0)) from transfers where kind = 'public' and status = 'done' and seller_paid_at is null),
    'paid_out', (select jsonb_build_object('count', count(*), 'amount', coalesce(sum(price), 0)) from transfers where kind = 'public' and seller_paid_at is not null),
    'return_due', (select jsonb_build_object('count', count(*), 'amount', coalesce(sum(price), 0)) from transfer_matches where return_due and returned_at is null),
    'returned', (select jsonb_build_object('count', count(*), 'amount', coalesce(sum(price), 0)) from transfer_matches where returned_at is not null),
    'held_now',
      (select coalesce(sum(m.price), 0) from transfer_matches m join transfer_payments p on p.id = m.payment_id where m.status = 'confirmed' and p.status = 'verified')
    + (select coalesce(sum(price), 0) from transfers where kind = 'public' and status = 'done' and seller_paid_at is null)
    + (select coalesce(sum(m.price), 0) from transfer_matches m join transfer_payments p on p.id = m.payment_id
        where m.return_due and m.returned_at is null and p.status = 'verified')) into r;
  return r;
end $function$;

-- 9. Who may call what
revoke all on function public._seller_block(uuid), public._clean_reason(text), public._release_match(uuid, text), public._release_cascade(uuid, text),
  public._revoke_interest(uuid, text), public._do_swap(uuid, uuid, public.transfer_interest_people), public._close_open_transfers(uuid, text)
  from public, anon, authenticated, service_role;
revoke all on function public.public_sell(text, text, text, text, integer, text), public.public_edit(text, text, text, text, integer, text),
  public.public_status(text, text), public.interest_submit(uuid, jsonb, boolean, boolean), public.interest_pay(text, text, uuid, uuid, text),
  public.interest_revoke(text, text) from public;
grant execute on function public.public_sell(text, text, text, text, integer, text), public.public_edit(text, text, text, text, integer, text),
  public.public_status(text, text), public.interest_submit(uuid, jsonb, boolean, boolean), public.interest_pay(text, text, uuid, uuid, text),
  public.interest_revoke(text, text) to anon, authenticated;
revoke all on function public.admin_listing_approve(uuid), public.admin_listing_edit_decide(uuid, boolean), public.admin_listing_revoke(uuid, text),
  public.admin_interest_revoke(uuid, text), public.admin_transfer_match(jsonb, boolean), public.admin_match_confirm(uuid),
  public.admin_match_release(uuid, text), public.admin_payment_verify(uuid, integer), public.admin_match_transfer(uuid),
  public.admin_transfer_mark_paid(uuid, text), public.admin_transfer_mark_returned(uuid, text), public.admin_transfer_money() from public, anon;
grant execute on function public.admin_listing_approve(uuid), public.admin_listing_edit_decide(uuid, boolean), public.admin_listing_revoke(uuid, text),
  public.admin_interest_revoke(uuid, text), public.admin_transfer_match(jsonb, boolean), public.admin_match_confirm(uuid),
  public.admin_match_release(uuid, text), public.admin_payment_verify(uuid, integer), public.admin_match_transfer(uuid),
  public.admin_transfer_mark_paid(uuid, text), public.admin_transfer_mark_returned(uuid, text), public.admin_transfer_money() to authenticated;
