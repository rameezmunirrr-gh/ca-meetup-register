-- ============================================================================
-- Release 2, Step 1, piece 1: preparation (email, transfer markers, settings)
-- Written 17 Oct 2026. Tested on the scratch database before use.
-- Safe to run once. Changes no existing data. Transfers stay OFF.
-- ============================================================================

-- 1. Email per person (required for new bookings, optional on old rows)
alter table public.tickets add column if not exists email text;
alter table public.tickets drop constraint if exists tickets_email_check;
alter table public.tickets add constraint tickets_email_check
  check (email is null or (char_length(email) between 5 and 120 and email ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$'));

-- 2. Markers used by transfers (nothing writes them yet)
--    transferred_out_at: the seller's ticket after a transfer (cancelled, not counted anywhere)
--    transferred_from:   on the buyer's new ticket, points at the seller's old ticket
alter table public.tickets add column if not exists transferred_out_at timestamptz;
alter table public.tickets add column if not exists transferred_from uuid references public.tickets(id);
create unique index if not exists tickets_transferred_from_uq on public.tickets (transferred_from) where transferred_from is not null;

-- 3. A booking is a normal registration or a transfer (transfer bookings never count as seats or income)
alter table public.bookings add column if not exists kind text not null default 'registration';
alter table public.bookings drop constraint if exists bookings_kind_check;
alter table public.bookings add constraint bookings_kind_check check (kind in ('registration', 'transfer'));

-- 4. New settings (all logged automatically by settings_log_trg)
alter table public.settings add column if not exists transfer_cutoff_at timestamptz;
alter table public.settings add column if not exists transfer_food_locked boolean not null default false;
alter table public.settings add column if not exists private_code_hours integer not null default 2;
alter table public.settings drop constraint if exists settings_code_hours_check;
alter table public.settings add constraint settings_code_hours_check check (private_code_hours between 1 and 168);

-- 5. Counting: a ticket that was transferred away no longer counts toward the cap
CREATE OR REPLACE FUNCTION public._public_state(s settings, p_session uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE
 SET search_path TO 'public'
AS $function$
declare used int; remaining int; reason text; pi jsonb; gu timestamptz; reopen timestamptz;
begin
  select count(*) into used from tickets t join bookings b on b.id = t.booking_id where b.status <> 'rejected' and t.transferred_out_at is null;
  remaining := greatest(s.cap - used, 0);
  pi := _pause_info(s);
  reason := case when not s.is_open then 'not_open'
                 when now() > s.deadline then 'deadline'
                 when remaining = 0 then 'full'
                 when (pi->>'in_pause')::boolean then 'paused'
                 else null end;
  reopen := case when reason = 'paused' and (pi->>'next_open')::timestamptz <= s.deadline
                 then (pi->>'next_open')::timestamptz else null end;
  if reason = 'paused' and reopen is null then reason := 'deadline'; end if;
  gu := case when reason in ('not_open', 'paused', 'deadline') then _grace_until(s, p_session) else null end;
  return jsonb_build_object('accepting', reason is null, 'closed_reason', reason,
    'spots_left', remaining, 'price_per_head', s.price_per_head,
    'max_group', greatest(least(s.max_group, remaining), 1), 'deadline', s.deadline,
    'server_now', now(), 'grace_until', gu, 'reopen_at', reopen,
    'pause_enabled', s.pause_enabled,
    'next_close_at', case when reason is null and s.pause_enabled and (pi->>'next_close')::timestamptz < s.deadline
                          then (pi->>'next_close')::timestamptz else null end);
end $function$;

-- 6. Registration now requires an email for every person
CREATE OR REPLACE FUNCTION public.submit_booking(p_submission_id uuid, p_people jsonb, p_screenshot_path text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare s settings%rowtype; b bookings%rowtype; n int; used int; r record; code text; pi jsonb;
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

  insert into tickets (secret, booking_id, name, phone, email, location, attendance, food)
  select substr(replace(gen_random_uuid()::text, '-', ''), 1, 12), b.id,
         trim(value->>'name'), value->>'phone', lower(trim(value->>'email')), value->>'loc', value->>'att', value->>'food'
  from jsonb_array_elements(p_people) with ordinality as e(value, ord) order by ord;

  return _booking_json(b.id);
end $function$;

-- 7. Exports: add email and the transfer marker at the end of the report view
create or replace view public.report as
 select t.ticket_no as sl_no, t.name, t.phone, t.location, t.attendance, t.food,
        b.booking_code, b.status as payment_status, b.amount_expected, b.people_count, b.screenshot_path,
        (t.checked_in_at is not null) as present, t.checked_in_at, t.created_at, t.kind, t.coord_no,
        _ticket_label(t.kind, t.ticket_no, t.coord_no) as ticket_label,
        t.email, t.transferred_out_at, b.kind as booking_kind
   from tickets t join bookings b on b.id = t.booking_id
  order by t.kind, t.coord_no, t.ticket_no, t.reg_seq;
