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
