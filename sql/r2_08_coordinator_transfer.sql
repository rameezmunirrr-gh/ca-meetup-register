-- ============================================================================
-- Release 2, piece 8: coordinators can transfer their ticket like anyone else
-- Written 26 Oct 2026. Tested on the scratch database before use.
-- REQUIRES r2_01 to r2_06. Safe to run twice. Changes no data.
-- Also: an admin can no longer change the coordinator status of a ticket that was already transferred away.
-- What changes: the seller checks no longer refuse a coordinator ticket, and the admin's
-- final check accepts a coordinator ticket. The buyer always becomes a normal GUEST (the
-- coordinator role is only ever given by an admin). The coordinator's own numbers (guest and
-- coordinator) are retired for good, as for any transferred ticket.
-- ============================================================================

-- private_sell
CREATE OR REPLACE FUNCTION public.private_sell(p_booking_code text, p_ticket text, p_phone text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
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
  if b.status <> 'paid' or (t.ticket_no is null and t.coord_no is null) then return jsonb_build_object('ok', false, 'error', 'NOT_CONFIRMED'); end if;
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

-- public_sell
CREATE OR REPLACE FUNCTION public.public_sell(p_booking_code text, p_ticket text, p_phone text, p_upi text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
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
  if b.status <> 'paid' or (t.ticket_no is null and t.coord_no is null) then return jsonb_build_object('ok', false, 'error', 'NOT_CONFIRMED'); end if;
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

-- admin_transfer_approve
CREATE OR REPLACE FUNCTION public.admin_transfer_approve(p_transfer uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
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
  if sb.status <> 'paid' or (t.ticket_no is null and t.coord_no is null) then raise exception 'SELLER_TICKET_INVALID'; end if;
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

-- set_coordinator
CREATE OR REPLACE FUNCTION public.set_coordinator(p_ticket_id uuid, p_make boolean)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare s settings%rowtype; t tickets%rowtype; bs text;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  select * into s from settings where id = 1 for update;
  select * into t from tickets where id = p_ticket_id for update;
  if not found then raise exception 'INVALID_TICKET'; end if;
  if t.transferred_out_at is not null then raise exception 'ALREADY_TRANSFERRED'; end if;   -- a retired ticket can never become (or stop being) a coordinator

  if p_make and t.kind = 'guest' then
    if t.prev_coord_no is not null then
      -- this person was a coordinator before: they get their own old number and QR back
      update tickets set kind = 'coordinator', coord_no = t.prev_coord_no,
        orig_secret = t.secret,
        secret = coalesce(t.prev_coord_secret, substr(replace(gen_random_uuid()::text, '-', ''), 1, 12)),
        prev_coord_no = null, prev_coord_secret = null,
        marked_by = auth.uid(), marked_at = now() where id = t.id;
    else
      -- first time: next new coordinator number. Any guest number stays on record, cancelled while coordinator.
      update tickets set kind = 'coordinator', coord_no = s.next_coord, orig_secret = t.secret,
        secret = substr(replace(gen_random_uuid()::text, '-', ''), 1, 12),
        marked_by = auth.uid(), marked_at = now() where id = t.id;
      update settings set next_coord = next_coord + 1 where id = 1;
    end if;
  elsif not p_make and t.kind = 'coordinator' then
    -- the coordinator number is kept on this person (cancelled), never given to anyone else.
    -- the guest number and original QR come back, or a new guest number is given once paid.
    update tickets set kind = 'guest', prev_coord_no = t.coord_no, prev_coord_secret = t.secret,
      coord_no = null, secret = coalesce(orig_secret, secret),
      orig_secret = null, marked_by = null, marked_at = null where id = t.id;
    select status into bs from bookings where id = t.booking_id;
    if bs = 'paid' then perform _assign_numbers(t.booking_id); end if;
  end if;

  select * into t from tickets where id = t.id;
  return jsonb_build_object('id', t.id, 'kind', t.kind, 'ticket_no', t.ticket_no,
                            'label', _ticket_label(t.kind, t.ticket_no, t.coord_no));
end $function$;
