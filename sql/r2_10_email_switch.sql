-- ============================================================================
-- Release 2, piece 10: switch for the Email box on the forms (Admin > Settings)
-- Written 26 Oct 2026. Tested on the scratch database before use. REQUIRES r2_01 to r2_09. Safe to run twice.
-- ask_email = true  (the default, how it works today): email is required on the registration form and the transfer form.
-- ask_email = false: the forms do not show the box; no email is asked for or stored.
-- Emails already collected stay where they are (admin-only). Only admins can change the switch.
-- ============================================================================
alter table public.settings add column if not exists ask_email boolean not null default true;
alter table public.transfer_buyers alter column email drop not null;   -- a buyer may now have no email (check rules still apply when one is given)

-- visitors: which optional parts of the site are on (replaces the piece-9 version; adds ask_email)
create or replace function public.get_site_flags() returns jsonb
 language sql stable security definer set search_path to 'public' as $function$
  select jsonb_build_object('show_about', s.show_about, 'ask_email', s.ask_email) from settings s where s.id = 1
$function$;
revoke all on function public.get_site_flags() from public, anon, authenticated, service_role;
grant execute on function public.get_site_flags() to anon, authenticated;

create or replace function public.admin_set_ask_email(p_ask boolean) returns void
 language plpgsql security definer set search_path to 'public' as $function$
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  if p_ask is null then raise exception 'INVALID_VALUE'; end if;
  update settings set ask_email = p_ask where id = 1;
end $function$;
revoke all on function public.admin_set_ask_email(boolean) from public, anon, authenticated, service_role;
grant execute on function public.admin_set_ask_email(boolean) to authenticated;

-- registration: email required only while the switch is on
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
    if s.ask_email and (length(trim(coalesce(r.value->>'email',''))) not between 5 and 120
       or lower(trim(r.value->>'email')) !~ '^[^@\s]+@[^@\s]+\.[^@\s]+$') then raise exception 'INVALID_EMAIL'; end if;
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
    if s.ask_email then insert into ticket_emails (ticket_id, email) values (tid, lower(trim(r.value->>'email'))); end if;
  end loop;

  return _booking_json(b.id);
end $function$;

-- transfer form: email required only while the switch is on
CREATE OR REPLACE FUNCTION public.transfer_submit(p_code text, p_submission_id uuid, p_buyer jsonb)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
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
  v_email := case when s.ask_email then lower(trim(coalesce(p_buyer->>'email', ''))) else null end;
  if length(v_name) not between 1 and 80 then return jsonb_build_object('ok', false, 'error', 'INVALID_NAME'); end if;
  if coalesce(p_buyer->>'phone', '') !~ '^[0-9]{10}$' then return jsonb_build_object('ok', false, 'error', 'INVALID_PHONE'); end if;
  if s.ask_email and (length(v_email) not between 5 and 120 or v_email !~ '^[^@\s]+@[^@\s]+\.[^@\s]+$') then return jsonb_build_object('ok', false, 'error', 'INVALID_EMAIL'); end if;
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

-- approval: copy the buyer's email only if there is one
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
  if bu.email is not null then insert into ticket_emails (ticket_id, email) values (nt.id, bu.email); end if;   -- email stays in the admin-only table
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
