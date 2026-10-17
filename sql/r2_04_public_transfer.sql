-- ============================================================================
-- Release 2, Step 1, piece 4: PUBLIC TRANSFER (listing, reservation, payment, payout, return)
-- Written 17 Oct 2026. Tested on the scratch database before use.
-- REQUIRES r2_01, r2_02 and r2_03 first. Supersedes these piece-3 functions (same names, extended):
--   _close_open_transfers, private_sell, lookup_tickets, admin_transfer_confirm_call,
--   admin_transfer_approve, admin_transfer_reject.
-- Apply together with the new pages. Transfers stay OFF until settings.transfers_open is set.
-- ============================================================================

-- 1. Tables: more statuses and the money / edit / reservation fields
alter table public.transfers drop constraint if exists transfers_status_check;
alter table public.transfers add constraint transfers_status_check check (status in
  ('code_active', 'listing_pending', 'listed', 'reserved', 'pending_admin', 'done', 'rejected', 'withdrawn', 'replaced'));
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
alter table public.transfers add column if not exists payment_verified_at timestamptz;
alter table public.transfers add column if not exists payment_verified_by uuid references auth.users(id);
alter table public.transfers add column if not exists amount_received integer check (amount_received is null or amount_received >= 0);
alter table public.transfers add column if not exists seller_paid_at timestamptz;
alter table public.transfers add column if not exists seller_paid_by uuid references auth.users(id);
alter table public.transfers add column if not exists payout_reference text check (payout_reference is null or char_length(payout_reference) between 3 and 80);
alter table public.transfers add column if not exists return_due boolean not null default false;
alter table public.transfers add column if not exists returned_at timestamptz;
alter table public.transfers add column if not exists returned_by uuid references auth.users(id);
alter table public.transfers add column if not exists return_reference text check (return_reference is null or char_length(return_reference) between 3 and 80);
alter table public.transfers drop constraint if exists transfers_public_fields;
alter table public.transfers add constraint transfers_public_fields check (kind <> 'public' or (price is not null and seller_upi is not null and reason is not null));
drop index if exists public.transfers_one_open_per_ticket;
create unique index transfers_one_open_per_ticket on public.transfers (ticket_id)
  where status in ('code_active', 'listing_pending', 'listed', 'reserved', 'pending_admin');

-- buyer rows can now be a reservation (name + phone only) before the form is filled
alter table public.transfer_buyers alter column submission_id drop not null;
alter table public.transfer_buyers alter column booking_id drop not null;
alter table public.transfer_buyers alter column email drop not null;
alter table public.transfer_buyers alter column location drop not null;
alter table public.transfer_buyers alter column attendance drop not null;
alter table public.transfer_buyers alter column food drop not null;
alter table public.transfer_buyers alter column consent_at drop not null;
alter table public.transfer_buyers add column if not exists token uuid not null default gen_random_uuid();
create unique index if not exists transfer_buyers_token_uq on public.transfer_buyers (token);
alter table public.transfer_buyers add column if not exists reserved_until timestamptz;
alter table public.transfer_buyers add column if not exists screenshot_path text;
alter table public.transfer_buyers drop constraint if exists transfer_buyers_status_check;
alter table public.transfer_buyers add constraint transfer_buyers_status_check check (status in ('reserved', 'active', 'done', 'rejected', 'released'));
alter table public.transfer_buyers drop constraint if exists transfer_buyers_full_when_submitted;
alter table public.transfer_buyers add constraint transfer_buyers_full_when_submitted check (status not in ('active', 'done') or
  (booking_id is not null and submission_id is not null and email is not null and location is not null
   and attendance is not null and food is not null and consent_at is not null));
drop index if exists public.transfer_buyers_one_per_transfer;
create unique index transfer_buyers_one_per_transfer on public.transfer_buyers (transfer_id) where status in ('reserved', 'active', 'done');
create unique index if not exists transfer_buyers_one_reservation_per_phone on public.transfer_buyers (phone) where status = 'reserved';

-- 2. Helpers
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

-- a reservation whose time ran out and that nobody has taken over frees the listing (caller holds the transfer row lock)
create or replace function public._normalize_reservation(p_transfer uuid) returns void
 language plpgsql security definer set search_path to 'public' as $function$
begin
  update transfer_buyers set status = 'released' where transfer_id = p_transfer and status = 'reserved' and reserved_until < now();
  if exists (select 1 from transfers where id = p_transfer and status = 'reserved')
     and not exists (select 1 from transfer_buyers where transfer_id = p_transfer and status = 'reserved') then
    update transfers set status = 'listed', updated_at = now() where id = p_transfer;
  end if;
end $function$;

create or replace function public._clean_reason(p text) returns text language sql immutable as $$
  select btrim(regexp_replace(coalesce(p, ''), '\s+', ' ', 'g')) $$;

-- closes every open transfer of a seller booking (used when an admin rejects or reopens that booking)
create or replace function public._close_open_transfers(p_booking uuid, p_reason text) returns void
 language plpgsql security definer set search_path to 'public' as $function$
declare x record; due boolean;
begin
  for x in select id, status, kind from transfers where booking_id = p_booking
           and status in ('code_active', 'listing_pending', 'listed', 'reserved', 'pending_admin') for update loop
    due := exists (select 1 from transfer_buyers where transfer_id = x.id and status = 'active' and screenshot_path is not null);
    update transfers set status = 'withdrawn', decision_note = left(p_reason, 300), decided_at = now(),
           decided_by = auth.uid(), updated_at = now(), return_due = (return_due or due) where id = x.id;
    update bookings set status = 'rejected', reviewed_by = auth.uid(), reviewed_at = now(), reviewed_via = 'admin'
     where id in (select booking_id from transfer_buyers where transfer_id = x.id and status = 'active' and booking_id is not null);
    update transfer_buyers set status = 'released' where transfer_id = x.id and status in ('reserved', 'active');
    perform _tlog(x.kind || ' transfer closed automatically', x.status, left(x.id::text, 8) || ': ' || p_reason || case when due then ' (RETURN DUE)' else '' end);
  end loop;
end $function$;

-- 3. Private sell, now aware of public listings
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
     and status in ('code_active', 'listing_pending', 'listed', 'reserved', 'pending_admin') for update;
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

-- 4. Seller side of a public transfer (visitors)
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
     and status in ('code_active', 'listing_pending', 'listed', 'reserved', 'pending_admin') for update;
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
declare s settings%rowtype; tid uuid; x transfers%rowtype; rs text; upi text; lbl text; t tickets%rowtype;
begin
  select * into s from settings where id = 1;
  if not s.transfers_open then return jsonb_build_object('ok', false, 'error', 'TRANSFERS_CLOSED'); end if;
  tid := _find_seller_ticket(p_booking_code, p_ticket, p_phone);
  if tid is null then return jsonb_build_object('ok', false, 'error', 'MISMATCH'); end if;
  select * into t from tickets where id = tid for update;
  select * into x from transfers where ticket_id = tid and kind = 'public'
     and status in ('listing_pending', 'listed', 'reserved', 'pending_admin') for update;
  if not found then return jsonb_build_object('ok', false, 'error', 'NOTHING_TO_EDIT'); end if;
  perform _normalize_reservation(x.id);
  select * into x from transfers where id = x.id;
  if x.status <> 'listed' then return jsonb_build_object('ok', false, 'error', 'EDIT_BLOCKED', 'status', x.status); end if;
  rs := _clean_reason(p_reason);
  if length(rs) not between 3 and 300 then return jsonb_build_object('ok', false, 'error', 'INVALID_REASON'); end if;
  if p_price is null or p_price < s.resale_min_price or p_price > s.max_resale_price then
    return jsonb_build_object('ok', false, 'error', 'PRICE_OUT_OF_RANGE', 'min', s.resale_min_price, 'max', s.max_resale_price); end if;
  upi := btrim(coalesce(p_upi, ''));
  if upi !~ '^([0-9]{10}|[A-Za-z0-9._-]{2,64}@[A-Za-z][A-Za-z0-9]{1,31})$' then return jsonb_build_object('ok', false, 'error', 'INVALID_UPI'); end if;
  lbl := _ticket_label(t.kind, t.ticket_no, t.coord_no);
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
        'status', case when x.status = 'reserved' and not exists (select 1 from transfer_buyers bu where bu.transfer_id = x.id and bu.status = 'reserved' and bu.reserved_until >= now())
                       then 'listed' else x.status end,
        'price', x.price, 'seller_upi', x.seller_upi, 'edit_pending', (x.edit_requested_at is not null),
        'edit_price', x.edit_price,
        'buyer_name', case when x.status in ('pending_admin', 'done')
                           then (select bu.name from transfer_buyers bu where bu.transfer_id = x.id and bu.status in ('active', 'done') limit 1) end,
        'payout', case when x.status = 'done' then case when x.seller_paid_at is not null then 'paid' else 'to_be_paid' end end,
        'created_at', x.created_at) as j
      from transfers x join tickets tk on tk.id = x.ticket_id
     where x.booking_id = b.id and x.seller_phone = ph and x.kind = 'public'
     order by x.created_at desc limit 10) r;
  return jsonb_build_object('found', true, 'transfers', res);
end $function$;

-- 5. Buyer side of a public transfer (visitors)
create or replace function public.public_board() returns jsonb
 language plpgsql stable security definer set search_path to 'public' as $function$
declare s settings%rowtype; res jsonb;
begin
  select * into s from settings where id = 1;
  if not s.transfers_open then return jsonb_build_object('open', false, 'cutoff_passed', false, 'listings', '[]'::jsonb); end if;
  if s.transfer_cutoff_at is not null and now() > s.transfer_cutoff_at then
    return jsonb_build_object('open', true, 'cutoff_passed', true, 'listings', '[]'::jsonb); end if;
  select coalesce(jsonb_agg(jsonb_build_object('id', x.id, 'seller_name', tk.name, 'price', x.price,
           'available', (x.status = 'listed' or not exists (select 1 from transfer_buyers bu where bu.transfer_id = x.id and bu.status = 'reserved' and bu.reserved_until >= now())))
           order by x.listed_at), '[]'::jsonb) into res
    from transfers x join tickets tk on tk.id = x.ticket_id
   where x.kind = 'public' and x.status in ('listed', 'reserved')
     and tk.checked_in_at is null and tk.transferred_out_at is null;
  return jsonb_build_object('open', true, 'cutoff_passed', false, 'listings', res, 'reservation_minutes', s.reservation_minutes);
end $function$;

create or replace function public.public_reserve(p_listing uuid, p_name text, p_phone text) returns jsonb
 language plpgsql security definer set search_path to 'public' as $function$
declare s settings%rowtype; x transfers%rowtype; t tickets%rowtype; cur transfer_buyers%rowtype; tb transfer_buyers%rowtype; nm text; ph text;
begin
  select * into s from settings where id = 1;
  if not s.transfers_open then return jsonb_build_object('ok', false, 'error', 'TRANSFERS_CLOSED'); end if;
  if s.transfer_cutoff_at is not null and now() > s.transfer_cutoff_at then
    return jsonb_build_object('ok', false, 'error', 'CUTOFF_PASSED'); end if;
  nm := btrim(coalesce(p_name, '')); ph := replace(replace(coalesce(p_phone, ''), ' ', ''), '-', '');
  if length(nm) not between 1 and 80 then return jsonb_build_object('ok', false, 'error', 'INVALID_NAME'); end if;
  if ph !~ '^[0-9]{10}$' then return jsonb_build_object('ok', false, 'error', 'INVALID_PHONE'); end if;
  select * into x from transfers where id = p_listing and kind = 'public' and status in ('listed', 'reserved') for update;
  if not found then return jsonb_build_object('ok', false, 'error', 'LISTING_UNAVAILABLE'); end if;
  select * into t from tickets where id = x.ticket_id for update;
  if _seller_block(t.id) is not null then return jsonb_build_object('ok', false, 'error', 'LISTING_UNAVAILABLE'); end if;

  select * into cur from transfer_buyers where transfer_id = x.id and status = 'reserved' for update;
  if found then
    if cur.reserved_until >= now() then return jsonb_build_object('ok', false, 'error', 'LISTING_RESERVED'); end if;
    update transfer_buyers set status = 'released' where id = cur.id;      -- their time ran out and someone else wants it
  end if;
  -- one active reservation per phone
  update transfer_buyers set status = 'released' where phone = ph and status = 'reserved' and reserved_until < now();
  if exists (select 1 from transfer_buyers where phone = ph and status = 'reserved' and reserved_until >= now()) then
    return jsonb_build_object('ok', false, 'error', 'ALREADY_RESERVED_ELSEWHERE'); end if;
  begin
    insert into transfer_buyers (transfer_id, name, phone, status, reserved_until)
    values (x.id, nm, ph, 'reserved', now() + make_interval(mins => s.reservation_minutes)) returning * into tb;
  exception when unique_violation then
    return jsonb_build_object('ok', false, 'error', 'TRY_AGAIN');
  end;
  update transfers set status = 'reserved', updated_at = now() where id = x.id;
  perform _tlog('public listing: reserved by a buyer', null, left(x.id::text, 8));
  return jsonb_build_object('ok', true, 'token', tb.token, 'reserved_until', tb.reserved_until, 'minutes', s.reservation_minutes,
                            'seller_name', t.name, 'price', x.price, 'food_locked', s.transfer_food_locked,
                            'food', case when s.transfer_food_locked then t.food end);
end $function$;

create or replace function public.public_reservation(p_token uuid) returns jsonb
 language plpgsql stable security definer set search_path to 'public' as $function$
declare tb transfer_buyers%rowtype; x transfers%rowtype; t tickets%rowtype; s settings%rowtype; bk bookings%rowtype;
begin
  select * into tb from transfer_buyers where token = p_token;
  if not found then return jsonb_build_object('ok', false, 'error', 'INVALID_RESERVATION'); end if;
  select * into x from transfers where id = tb.transfer_id and kind = 'public';
  if not found then return jsonb_build_object('ok', false, 'error', 'INVALID_RESERVATION'); end if;
  select * into s from settings where id = 1;
  select * into t from tickets where id = x.ticket_id;
  if tb.status in ('active', 'done') then
    select * into bk from bookings where id = tb.booking_id;
    return jsonb_build_object('ok', true, 'state', 'submitted', 'booking_code', bk.booking_code, 'price', x.price);
  end if;
  if tb.status <> 'reserved' or x.status <> 'reserved' then return jsonb_build_object('ok', true, 'state', 'ended'); end if;
  return jsonb_build_object('ok', true, 'state', 'reserved', 'seconds_left', greatest(0, floor(extract(epoch from (tb.reserved_until - now())))::int),
                            'expired', tb.reserved_until < now(), 'name', tb.name, 'phone', tb.phone, 'seller_name', t.name, 'price', x.price,
                            'food_locked', s.transfer_food_locked, 'food', case when s.transfer_food_locked then t.food end);
end $function$;

create or replace function public.public_cancel_reservation(p_token uuid) returns jsonb
 language plpgsql security definer set search_path to 'public' as $function$
declare tb transfer_buyers%rowtype; x transfers%rowtype;
begin
  select * into tb from transfer_buyers where token = p_token;
  if not found then return jsonb_build_object('ok', false, 'error', 'INVALID_RESERVATION'); end if;
  select * into x from transfers where id = tb.transfer_id for update;
  select * into tb from transfer_buyers where id = tb.id for update;
  if tb.status <> 'reserved' then return jsonb_build_object('ok', false, 'error', 'NOT_RESERVED'); end if;
  update transfer_buyers set status = 'released' where id = tb.id;
  if x.status = 'reserved' then update transfers set status = 'listed', updated_at = now() where id = x.id; end if;
  perform _tlog('public listing: reservation cancelled by buyer', null, left(x.id::text, 8));
  return jsonb_build_object('ok', true);
end $function$;

create or replace function public.public_submit(p_token uuid, p_submission_id uuid, p_buyer jsonb, p_screenshot_path text) returns jsonb
 language plpgsql security definer set search_path to 'public' as $function$
declare s settings%rowtype; tb transfer_buyers%rowtype; x transfers%rowtype; t tickets%rowtype; bk bookings%rowtype;
        bcode text; v_name text; v_email text; v_food text;
begin
  if p_submission_id is null or p_token is null then return jsonb_build_object('ok', false, 'error', 'INVALID_DATA'); end if;
  select * into tb from transfer_buyers where submission_id = p_submission_id;
  if found then                                                     -- same form sent again: same answer
    if tb.token <> p_token then return jsonb_build_object('ok', false, 'error', 'INVALID_RESERVATION'); end if;
    select * into bk from bookings where id = tb.booking_id;
    return jsonb_build_object('ok', true, 'booking_code', bk.booking_code, 'status', bk.status, 'replay', true);
  end if;
  select * into s from settings where id = 1;
  if not s.transfers_open then return jsonb_build_object('ok', false, 'error', 'TRANSFERS_CLOSED'); end if;
  -- the cut-off does not apply here: a reservation can only exist if it was made before the cut-off

  select * into tb from transfer_buyers where token = p_token;
  if not found then return jsonb_build_object('ok', false, 'error', 'INVALID_RESERVATION'); end if;
  select * into x from transfers where id = tb.transfer_id and kind = 'public' for update;
  if not found then return jsonb_build_object('ok', false, 'error', 'INVALID_RESERVATION'); end if;
  select * into tb from transfer_buyers where id = tb.id for update;
  if tb.status in ('active', 'done') then return jsonb_build_object('ok', false, 'error', 'ALREADY_SUBMITTED'); end if;
  if tb.status <> 'reserved' or x.status <> 'reserved' then return jsonb_build_object('ok', false, 'error', 'RESERVATION_ENDED'); end if;
  select * into t from tickets where id = x.ticket_id for update;
  if _seller_block(t.id) is not null then return jsonb_build_object('ok', false, 'error', 'NOT_AVAILABLE'); end if;

  if p_buyer is null or jsonb_typeof(p_buyer) <> 'object' then return jsonb_build_object('ok', false, 'error', 'INVALID_DATA'); end if;
  v_name := btrim(coalesce(p_buyer->>'name', '')); v_email := lower(btrim(coalesce(p_buyer->>'email', '')));
  if length(v_name) not between 1 and 80 then return jsonb_build_object('ok', false, 'error', 'INVALID_NAME'); end if;
  if coalesce(p_buyer->>'phone', '') <> tb.phone then return jsonb_build_object('ok', false, 'error', 'PHONE_CHANGED'); end if;
  if length(v_email) not between 5 and 120 or v_email !~ '^[^@\s]+@[^@\s]+\.[^@\s]+$' then return jsonb_build_object('ok', false, 'error', 'INVALID_EMAIL'); end if;
  if coalesce(p_buyer->>'loc', '') not in ('In Bengaluru', 'Outside Bengaluru') then return jsonb_build_object('ok', false, 'error', 'INVALID_LOCATION'); end if;
  if coalesce(p_buyer->>'att', '') not in ('Surely', 'Most probably') then return jsonb_build_object('ok', false, 'error', 'INVALID_ATTENDANCE'); end if;
  if not s.transfer_food_locked and coalesce(p_buyer->>'food', '') not in ('Veg', 'Non-veg') then return jsonb_build_object('ok', false, 'error', 'INVALID_FOOD'); end if;
  if coalesce(p_buyer->>'consent', '') <> 'true' then return jsonb_build_object('ok', false, 'error', 'INVALID_CONSENT'); end if;
  if p_screenshot_path is null or p_screenshot_path not like p_submission_id::text || '%'
     or not exists (select 1 from storage.objects where bucket_id = 'payment-proofs' and name = p_screenshot_path) then
    return jsonb_build_object('ok', false, 'error', 'SCREENSHOT_MISSING'); end if;
  v_food := case when s.transfer_food_locked then t.food else p_buyer->>'food' end;

  begin
    loop
      bcode := upper(substr(replace(gen_random_uuid()::text, '-', ''), 1, 8));
      exit when not exists (select 1 from bookings where booking_code = bcode);
    end loop;
    insert into bookings (booking_code, submission_id, people_count, amount_expected, screenshot_path, kind)
    values (bcode, p_submission_id, 1, 0, null, 'transfer') returning * into bk;      -- the price never enters the registration money
    update transfer_buyers set status = 'active', booking_id = bk.id, submission_id = p_submission_id, name = v_name, email = v_email,
           location = p_buyer->>'loc', attendance = p_buyer->>'att', food = v_food, consent_at = now(), screenshot_path = p_screenshot_path
     where id = tb.id;
  exception when unique_violation then
    return jsonb_build_object('ok', false, 'error', 'TRY_AGAIN');
  end;
  update transfers set status = 'pending_admin', updated_at = now() where id = x.id;
  perform _tlog('public transfer: buyer submitted payment', null, _ticket_label(t.kind, t.ticket_no, t.coord_no) || ' at ' || x.price || ' (' || left(x.id::text, 8) || ')');
  return jsonb_build_object('ok', true, 'booking_code', bk.booking_code, 'status', 'pending', 'price', x.price,
                            'seller_name', t.name, 'food', v_food);
end $function$;

-- 6. Ticket lookup, now also telling the buyer the state of a public transfer (and a payment return)
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
      st := case when x.returned_at is not null then 'returned'
                 when x.return_due then 'return_due'
                 when b.status = 'rejected' then 'rejected' else 'pending' end;
      return jsonb_build_object('found', true, 'kind', 'transfer', 'booking_code', b.booking_code, 'status', b.status,
                                'people_count', 1, 'amount_expected', 0, 'name', bu.name, 'tickets', '[]'::jsonb,
                                'transfer', jsonb_build_object('type', x.kind, 'price', case when x.kind = 'public' then x.price end, 'state', st));
    end if;
    return jsonb_build_object('found', false);
  end if;
  return jsonb_build_object('found', true, 'kind', b.kind, 'booking_code', b.booking_code, 'status', b.status,
                            'people_count', b.people_count, 'amount_expected', b.amount_expected, 'tickets', tk);
end $function$;

-- 7. Admin side
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
  perform _normalize_reservation(x.id);
  select * into x from transfers where id = x.id;
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

create or replace function public.admin_listing_withdraw(p_transfer uuid, p_note text default null) returns void
 language plpgsql security definer set search_path to 'public' as $function$
declare x transfers%rowtype; note text;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  select * into x from transfers where id = p_transfer and kind = 'public' for update;
  if not found then raise exception 'INVALID_TRANSFER'; end if;
  perform _normalize_reservation(x.id);
  select * into x from transfers where id = x.id;
  if x.status = 'reserved' then raise exception 'BUYER_RESERVED'; end if;
  if x.status = 'pending_admin' then raise exception 'USE_REJECT'; end if;
  if x.status not in ('listed', 'listing_pending') then raise exception 'NOT_OPEN'; end if;
  note := nullif(btrim(coalesce(p_note, '')), '');
  if note is not null and char_length(note) > 300 then raise exception 'INVALID_NOTE'; end if;
  update transfers set status = 'withdrawn', decision_note = note, decided_at = now(), decided_by = auth.uid(),
         edit_price = null, edit_upi = null, edit_reason = null, edit_requested_at = null, updated_at = now() where id = x.id;
  perform _tlog('public listing: WITHDRAWN', x.status, left(x.id::text, 8) || coalesce(': ' || note, ''));
end $function$;

create or replace function public.admin_release_reservation(p_transfer uuid, p_note text default null) returns void
 language plpgsql security definer set search_path to 'public' as $function$
declare x transfers%rowtype;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  select * into x from transfers where id = p_transfer and kind = 'public' for update;
  if not found then raise exception 'INVALID_TRANSFER'; end if;
  if x.status <> 'reserved' then raise exception 'NOT_RESERVED'; end if;
  update transfer_buyers set status = 'released' where transfer_id = x.id and status = 'reserved';
  update transfers set status = 'listed', updated_at = now() where id = x.id;
  perform _tlog('public listing: reservation released by admin', null, left(x.id::text, 8) || coalesce(': ' || left(p_note, 100), ''));
end $function$;

create or replace function public.admin_transfer_verify_payment(p_transfer uuid, p_amount integer) returns void
 language plpgsql security definer set search_path to 'public' as $function$
declare x transfers%rowtype;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  select * into x from transfers where id = p_transfer and kind = 'public' for update;
  if not found then raise exception 'INVALID_TRANSFER'; end if;
  if x.status <> 'pending_admin' then raise exception 'NOT_PENDING'; end if;
  if p_amount is null or p_amount <> x.price then raise exception 'AMOUNT_MISMATCH'; end if;
  update transfers set payment_verified_at = now(), payment_verified_by = auth.uid(), amount_received = p_amount, updated_at = now() where id = x.id;
  perform _tlog('public transfer: payment VERIFIED', null, p_amount::text || ' (' || left(x.id::text, 8) || ')');
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

  insert into tickets (secret, booking_id, name, phone, email, location, attendance, food, kind, transferred_from)
  values (substr(replace(gen_random_uuid()::text, '-', ''), 1, 12), bk.id, bu.name, bu.phone, bu.email,
          bu.location, bu.attendance, bu.food, 'guest', t.id)
  returning * into nt;
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
  if x.status not in ('code_active', 'listing_pending', 'listed', 'reserved', 'pending_admin') then raise exception 'NOT_PENDING'; end if;
  note := nullif(btrim(coalesce(p_note, '')), '');
  if note is not null and char_length(note) > 300 then raise exception 'INVALID_NOTE'; end if;
  due := x.kind = 'public' and exists (select 1 from transfer_buyers where transfer_id = x.id and status = 'active' and screenshot_path is not null);
  update transfers set status = 'rejected', decision_note = note, decided_at = now(), decided_by = auth.uid(), updated_at = now(),
         return_due = (return_due or due),
         edit_price = null, edit_upi = null, edit_reason = null, edit_requested_at = null where id = x.id;
  update bookings set status = 'rejected', reviewed_by = auth.uid(), reviewed_at = now(), reviewed_via = 'admin'
   where id in (select booking_id from transfer_buyers where transfer_id = x.id and status = 'active' and booking_id is not null);
  update transfer_buyers set status = 'rejected' where transfer_id = x.id and status in ('reserved', 'active');
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
  perform _tlog('public transfer: money RETURNED to buyer', null, left(x.id::text, 8));
end $function$;

create or replace function public.admin_transfer_money() returns jsonb
 language plpgsql stable security definer set search_path to 'public' as $function$
declare r jsonb;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  select jsonb_build_object(
    'awaiting_verification', jsonb_build_object('count', count(*) filter (where status = 'pending_admin' and payment_verified_at is null),
        'amount', coalesce(sum(price) filter (where status = 'pending_admin' and payment_verified_at is null), 0)),
    'verified_waiting_transfer', jsonb_build_object('count', count(*) filter (where status = 'pending_admin' and payment_verified_at is not null),
        'amount', coalesce(sum(amount_received) filter (where status = 'pending_admin' and payment_verified_at is not null), 0)),
    'to_pay_out', jsonb_build_object('count', count(*) filter (where status = 'done' and seller_paid_at is null),
        'amount', coalesce(sum(amount_received) filter (where status = 'done' and seller_paid_at is null), 0)),
    'paid_out', jsonb_build_object('count', count(*) filter (where seller_paid_at is not null),
        'amount', coalesce(sum(amount_received) filter (where seller_paid_at is not null), 0)),
    'return_due', jsonb_build_object('count', count(*) filter (where return_due and returned_at is null),
        'amount', coalesce(sum(coalesce(amount_received, price)) filter (where return_due and returned_at is null), 0)),
    'returned', jsonb_build_object('count', count(*) filter (where returned_at is not null),
        'amount', coalesce(sum(coalesce(amount_received, price)) filter (where returned_at is not null), 0)),
    'held_now', coalesce(sum(amount_received) filter (where (status = 'pending_admin' and payment_verified_at is not null)
                                                        or (status = 'done' and seller_paid_at is null)
                                                        or (return_due and returned_at is null and payment_verified_at is not null)), 0))
    into r from transfers where kind = 'public';
  return r;
end $function$;

-- 8. Who may call what
revoke all on function public._seller_block(uuid), public._normalize_reservation(uuid), public._clean_reason(text) from public, anon, authenticated, service_role;
revoke all on function public._close_open_transfers(uuid, text) from public, anon, authenticated, service_role;
revoke all on function public.public_sell(text, text, text, text, integer, text), public.public_edit(text, text, text, text, integer, text),
  public.public_status(text, text), public.public_board(), public.public_reserve(uuid, text, text), public.public_reservation(uuid),
  public.public_cancel_reservation(uuid), public.public_submit(uuid, uuid, jsonb, text) from public;
grant execute on function public.public_sell(text, text, text, text, integer, text), public.public_edit(text, text, text, text, integer, text),
  public.public_status(text, text), public.public_board(), public.public_reserve(uuid, text, text), public.public_reservation(uuid),
  public.public_cancel_reservation(uuid), public.public_submit(uuid, uuid, jsonb, text) to anon, authenticated;
revoke all on function public.admin_listing_approve(uuid), public.admin_listing_edit_decide(uuid, boolean), public.admin_listing_withdraw(uuid, text),
  public.admin_release_reservation(uuid, text), public.admin_transfer_verify_payment(uuid, integer), public.admin_transfer_mark_paid(uuid, text),
  public.admin_transfer_mark_returned(uuid, text), public.admin_transfer_money() from public, anon;
grant execute on function public.admin_listing_approve(uuid), public.admin_listing_edit_decide(uuid, boolean), public.admin_listing_withdraw(uuid, text),
  public.admin_release_reservation(uuid, text), public.admin_transfer_verify_payment(uuid, integer), public.admin_transfer_mark_paid(uuid, text),
  public.admin_transfer_mark_returned(uuid, text), public.admin_transfer_money() to authenticated;
