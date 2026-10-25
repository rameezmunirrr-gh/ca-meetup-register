-- ROLLOUT PART A (run once). Contains r2_01_prep.sql then r2_02_lookup.sql.
-- Safe to run twice. Registration must stay CLOSED until the new pages are published.

-- ============================================================================
-- Release 2, Step 1, piece 1: preparation (email, transfer markers, settings)
-- Written 17 Oct 2026. Tested on the scratch database before use.
-- Safe to run once. Changes no existing data. Transfers stay OFF.
-- ============================================================================

-- 1. Email per person (required for new bookings). Kept in its OWN table that only admins can read,
--    so gate volunteers (who can read the tickets table) never see email addresses.
create table if not exists public.ticket_emails (
  ticket_id uuid primary key references public.tickets(id) on delete cascade,
  email text not null check (char_length(email) between 5 and 120 and email ~ '^[^@\s]+@[^@\s]+\.[^@\s]+$')
);
alter table public.ticket_emails enable row level security;
drop policy if exists admin_read_ticket_emails on public.ticket_emails;
create policy admin_read_ticket_emails on public.ticket_emails for select to authenticated using (is_admin());
revoke all on table public.ticket_emails from public, anon, authenticated, service_role;
grant select on table public.ticket_emails to authenticated;

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

-- 7. Exports: add email (admins only, via ticket_emails) and the transfer marker at the end of the report view
create or replace view public.report with (security_invoker = true) as   -- keep it staff-only: it must follow the caller's row-level security
 select t.ticket_no as sl_no, t.name, t.phone, t.location, t.attendance, t.food,
        b.booking_code, b.status as payment_status, b.amount_expected, b.people_count, b.screenshot_path,
        (t.checked_in_at is not null) as present, t.checked_in_at, t.created_at, t.kind, t.coord_no,
        _ticket_label(t.kind, t.ticket_no, t.coord_no) as ticket_label,
        e.email, t.transferred_out_at, b.kind as booking_kind
   from tickets t join bookings b on b.id = t.booking_id
        left join ticket_emails e on e.ticket_id = t.id
  order by t.kind, t.coord_no, t.ticket_no, t.reg_seq;


-- ============================================================================
-- Release 2, Step 1, piece 2: ticket lookup by Booking ID + phone
-- Written 17 Oct 2026. Tested on the scratch database before use.
-- Adds a NEW function; changes nothing that exists.
-- REQUIRES r2_01_prep.sql first (it uses bookings.kind and tickets.transferred_out_at),
-- so apply it together with r2_01 when the new pages are ready.
-- (The old lookup_booking is removed by r2_02b_cutover.sql, applied together
--  with the new Tickets page.)
-- ============================================================================

create or replace function public.lookup_tickets(p_code text, p_phone text)
 returns jsonb
 language plpgsql
 stable security definer
 set search_path to 'public'
as $function$
declare b bookings%rowtype; c text; ph text; tk jsonb;
begin
  -- same Booking ID cleaning as before (case, spaces, dashes, letter O for zero)
  c  := replace(replace(replace(upper(coalesce(p_code, '')), 'O', '0'), ' ', ''), '-', '');
  ph := replace(replace(coalesce(p_phone, ''), ' ', ''), '-', '');
  -- every kind of failure returns the SAME answer, so nobody can tell which part was wrong
  if length(c) <> 8 or ph !~ '^[0-9]{10}$' then return jsonb_build_object('found', false); end if;

  select * into b from bookings where booking_code = c;
  -- Transfer bookings (kind = 'transfer') are not handled here yet; a later piece adds them.
  if not found or b.kind <> 'registration' then return jsonb_build_object('found', false); end if;

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

  -- right Booking ID but this phone is not on any ticket in it: same answer as "not found"
  if tk is null then return jsonb_build_object('found', false); end if;

  return jsonb_build_object('found', true, 'booking_code', b.booking_code, 'status', b.status,
                            'people_count', b.people_count, 'amount_expected', b.amount_expected,
                            'tickets', tk);
end $function$;

revoke all on function public.lookup_tickets(text, text) from public;
grant execute on function public.lookup_tickets(text, text) to anon, authenticated;
