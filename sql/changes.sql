-- 13 Oct 2026: make the report view follow the caller's permissions
alter view public.report set (security_invoker = true);

-- 13 Oct 2026: internal helpers must not be callable from outside
revoke execute on function public._assign_numbers(uuid), public._booking_json(uuid)
  from public, anon, authenticated;

-- 13 Oct 2026: undo_checkin now works for coordinators too (by ticket id or number)
drop function if exists public.undo_checkin(integer);

create or replace function public.undo_checkin(
  p_ticket_no integer default null,
  p_coord boolean default false,
  p_id uuid default null
) returns void
language plpgsql
security definer
set search_path to 'public'
as $function$
declare n int;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;

  if p_id is not null then
    update tickets set checked_in_at = null, checked_in_by = null where id = p_id;
  elsif p_coord then
    update tickets set checked_in_at = null, checked_in_by = null
    where coord_no = p_ticket_no and kind = 'coordinator';
  else
    update tickets set checked_in_at = null, checked_in_by = null where ticket_no = p_ticket_no;
  end if;

  get diagnostics n = row_count;
  if n = 0 then raise exception 'INVALID_TICKET'; end if;
end $function$;

revoke execute on function public.undo_checkin(integer, boolean, uuid) from public, anon;
grant execute on function public.undo_checkin(integer, boolean, uuid) to authenticated;

-- 14 Oct 2026: daily "reconciliation pause" + 10-minute grace for people mid-registration.
-- Run this whole file once in the Supabase SQL editor. Safe to run twice.

-- 1) New settings
alter table public.settings
  add column if not exists pause_enabled boolean not null default false,
  add column if not exists pause_close_time time not null default '23:00',
  add column if not exists pause_open_time  time not null default '00:00',
  add column if not exists grace_minutes integer not null default 10,
  add column if not exists closed_at timestamptz;

alter table public.settings drop constraint if exists settings_grace_check;
alter table public.settings add constraint settings_grace_check check (grace_minutes between 1 and 60);
alter table public.settings drop constraint if exists settings_pause_times_check;
alter table public.settings add constraint settings_pause_times_check check (pause_close_time <> pause_open_time);

-- 2) People currently filling the form (one row per registration attempt). No personal data.
create table if not exists public.reg_sessions (
  id uuid primary key,
  started_at timestamptz not null default now(),
  last_seen  timestamptz not null default now()
);
revoke all on public.reg_sessions from public, anon, authenticated;


-- 3) Where are we in the daily pause? (all times in India time)
create or replace function public._pause_info(s settings)
 returns jsonb
 language plpgsql
 stable
 set search_path to 'public'
as $function$
declare ist_now timestamp; lc timestamp; op timestamp;
begin
  if not s.pause_enabled then
    return jsonb_build_object('in_pause', false, 'last_close', null, 'next_open', null, 'next_close', null);
  end if;
  ist_now := now() at time zone 'Asia/Kolkata';
  lc := ist_now::date + s.pause_close_time;
  if lc > ist_now then lc := lc - interval '1 day'; end if;      -- most recent close moment
  op := lc::date + s.pause_open_time;
  if op <= lc then op := op + interval '1 day'; end if;           -- the reopen that follows it
  return jsonb_build_object(
    'in_pause',   ist_now < op,
    'last_close', lc at time zone 'Asia/Kolkata',
    'next_open',  op at time zone 'Asia/Kolkata',
    'next_close', (lc + interval '1 day') at time zone 'Asia/Kolkata');
end $function$;


-- 3b) The moment registration closed (earliest of: switched off by hand, daily pause started, deadline passed)
create or replace function public._close_moment(s settings)
 returns timestamptz
 language plpgsql
 stable
 set search_path to 'public'
as $function$
declare pi jsonb := _pause_info(s);
begin
  return least(case when not s.is_open then s.closed_at end,
               case when (pi->>'in_pause')::boolean then (pi->>'last_close')::timestamptz end,
               case when now() > s.deadline then s.deadline end);
end $function$;


-- 4) Grace: is this person (session) allowed to finish although registration just closed?
drop function if exists public._grace_until(settings, uuid);
create or replace function public._grace_until(s settings, p_session uuid, p_slack interval default '0 seconds')
 returns timestamptz
 language plpgsql
 stable
 set search_path to 'public'
as $function$
declare cm timestamptz; r reg_sessions%rowtype;
begin
  if p_session is null then return null; end if;
  cm := _close_moment(s);
  if cm is null or now() > cm + make_interval(mins => s.grace_minutes) + p_slack then return null; end if;
  select * into r from reg_sessions where id = p_session;
  if not found or r.started_at >= cm or r.last_seen < cm - interval '10 minutes' then return null; end if;
  if exists (select 1 from bookings where submission_id = p_session) then return null; end if;
  return cm + make_interval(mins => s.grace_minutes);
end $function$;


-- 5) What the public page sees
drop function if exists public.get_public_status();
create or replace function public._public_state(s settings, p_session uuid)
 returns jsonb
 language plpgsql
 stable
 set search_path to 'public'
as $function$
declare used int; remaining int; reason text; pi jsonb; gu timestamptz; reopen timestamptz;
begin
  select count(*) into used from tickets t join bookings b on b.id = t.booking_id where b.status <> 'rejected';
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

create or replace function public.get_public_status(p_session uuid default null)
 returns jsonb
 language plpgsql
 stable
 security definer
 set search_path to 'public'
as $function$
declare s settings%rowtype;
begin
  select * into s from settings where id = 1;
  return _public_state(s, p_session);
end $function$;

-- The form page calls this every 30 seconds while the person is filling the form.
create or replace function public.registration_heartbeat(p_session uuid)
 returns jsonb
 language plpgsql
 volatile
 security definer
 set search_path to 'public'
as $function$
declare s settings%rowtype; st jsonb;
begin
  if p_session is null then raise exception 'INVALID_DATA'; end if;
  select * into s from settings where id = 1;
  st := _public_state(s, p_session);
  if (st->>'accepting')::boolean then
    insert into reg_sessions (id) values (p_session)
    on conflict (id) do update set last_seen = now();
    delete from reg_sessions where last_seen < now() - interval '1 day';
  else
    -- while closed, only a person who is still inside their grace minutes gets refreshed; nobody new can start
    if (st->>'grace_until') is not null then
      update reg_sessions set last_seen = now() where id = p_session;
    end if;
  end if;
  return st;
end $function$;


-- 6) Booking: the closed check now allows the grace period
create or replace function public.submit_booking(p_submission_id uuid, p_people jsonb, p_screenshot_path text)
 returns jsonb
 language plpgsql
 security definer
 set search_path to 'public'
as $function$
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

  select count(*) into used from tickets t join bookings bk on bk.id = t.booking_id where bk.status <> 'rejected';
  if used + n > s.cap then raise exception 'NOT_ENOUGH_SPOTS'; end if;

  for r in select value from jsonb_array_elements(p_people) loop
    if length(trim(coalesce(r.value->>'name',''))) not between 1 and 80 then raise exception 'INVALID_NAME'; end if;
    if coalesce(r.value->>'phone','') !~ '^[0-9]{10}$' then raise exception 'INVALID_PHONE'; end if;
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

  insert into tickets (secret, booking_id, name, phone, location, attendance, food)
  select substr(replace(gen_random_uuid()::text, '-', ''), 1, 12), b.id,
         trim(value->>'name'), value->>'phone', value->>'loc', value->>'att', value->>'food'
  from jsonb_array_elements(p_people) with ordinality as e(value, ord) order by ord;

  return _booking_json(b.id);
end $function$;


-- 7) Admin: save settings (now with the pause options). Remembers the moment registration was switched off.
drop function if exists public.admin_update_settings(integer, integer, timestamp with time zone, boolean);
create or replace function public.admin_update_settings(
  p_cap integer default null, p_price integer default null,
  p_deadline timestamp with time zone default null, p_is_open boolean default null,
  p_pause_enabled boolean default null, p_pause_close time default null, p_pause_open time default null)
 returns void
 language plpgsql
 security definer
 set search_path to 'public'
as $function$
declare s settings%rowtype;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  select * into s from settings where id = 1 for update;
  if coalesce(p_pause_close, s.pause_close_time) = coalesce(p_pause_open, s.pause_open_time) then
    raise exception 'INVALID_PAUSE_TIMES';
  end if;
  update settings set cap = coalesce(p_cap, cap), price_per_head = coalesce(p_price, price_per_head),
    deadline = coalesce(p_deadline, deadline), is_open = coalesce(p_is_open, is_open),
    pause_enabled = coalesce(p_pause_enabled, pause_enabled),
    pause_close_time = coalesce(p_pause_close, pause_close_time),
    pause_open_time = coalesce(p_pause_open, pause_open_time),
    closed_at = case when p_is_open is true then null
                     when p_is_open is false and s.is_open then now()
                     else closed_at end
  where id = 1;
end $function$;


-- 8) Admin: live status for the dashboard banner
create or replace function public.admin_registration_status()
 returns jsonb
 language plpgsql
 stable
 security definer
 set search_path to 'public'
as $function$
declare s settings%rowtype; st jsonb; cm timestamptz; gc int := 0; gu timestamptz;
begin
  if not is_staff() then raise exception 'NOT_ALLOWED'; end if;
  select * into s from settings where id = 1;
  st := _public_state(s, null);
  cm := _close_moment(s);
  if cm is not null and now() <= cm + make_interval(mins => s.grace_minutes) then
    gu := cm + make_interval(mins => s.grace_minutes);
    select count(*) into gc from reg_sessions r
    where r.started_at < cm and r.last_seen >= cm - interval '10 minutes'
      and not exists (select 1 from bookings b where b.submission_id = r.id);
  end if;
  return jsonb_build_object('closed_reason', st->'closed_reason', 'accepting', st->'accepting',
    'reopen_at', st->'reopen_at', 'next_close_at', st->'next_close_at',
    'grace_count', gc, 'grace_until', case when gc > 0 then gu else null end, 'server_now', now());
end $function$;


-- 9) Who may call what
revoke execute on function public._pause_info(settings), public._close_moment(settings), public._grace_until(settings, uuid, interval),
  public._public_state(settings, uuid) from public, anon, authenticated;
revoke execute on function public.get_public_status(uuid), public.registration_heartbeat(uuid),
  public.submit_booking(uuid, jsonb, text) from public;
grant execute on function public.get_public_status(uuid), public.registration_heartbeat(uuid),
  public.submit_booking(uuid, jsonb, text) to anon, authenticated;
revoke execute on function public.admin_update_settings(integer, integer, timestamp with time zone, boolean, boolean, time, time),
  public.admin_registration_status() from public, anon;
grant execute on function public.admin_update_settings(integer, integer, timestamp with time zone, boolean, boolean, time, time),
  public.admin_registration_status() to authenticated;

-- 14 Oct 2026: a number touched by a person is never given to anyone else.
-- A person keeps their guest number AND their coordinator number for good.
-- Run this whole file once in the Supabase SQL editor.

-- 1) Remember a removed coordinator's number and QR secret on the same person
alter table public.tickets
  add column if not exists prev_coord_no integer,
  add column if not exists prev_coord_secret text;

-- a retired coordinator number can belong to only one person
create unique index if not exists tickets_prev_coord_no_uq
  on public.tickets (prev_coord_no) where prev_coord_no is not null;


-- 2) Make / remove coordinator
create or replace function public.set_coordinator(p_ticket_id uuid, p_make boolean)
 returns jsonb
 language plpgsql
 security definer
 set search_path to 'public'
as $function$
declare s settings%rowtype; t tickets%rowtype; bs text;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  select * into s from settings where id = 1 for update;
  select * into t from tickets where id = p_ticket_id for update;
  if not found then raise exception 'INVALID_TICKET'; end if;

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


-- 3) Gate check: a cancelled coordinator ticket now shows CANCELLED (not INVALID)
create or replace function public.admit_ticket(p_ticket_no integer default null::integer, p_secret text default null::text, p_approve boolean default false, p_coord boolean default false, p_id uuid default null::uuid)
 returns jsonb
 language plpgsql
 security definer
 set search_path to 'public'
as $function$
declare t tickets%rowtype; b bookings%rowtype; info jsonb; who text;
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

-- =====================================================================
-- TICKET TRANSFER  (notice board + handshake; organisers approve)
-- Safe to run more than once. Run it in the Supabase SQL editor.
--
-- How it works
--   1. A ticket holder can post an ad ("ticket for sale at Rs X") on the board.
--      Posting needs Booking ID + ticket number, so only real tickets can be listed.
--   2. A buyer taps Interested (leaves name + phone). Choosing "talk" shows the seller's number.
--   3. The seller (Booking ID + ticket number) picks a buyer and starts the transfer.
--      This creates a one-time TRANSFER CODE and hides the ad. A seller who already has a
--      buyer can skip steps 1-2 and start the transfer directly.
--   4. The buyer enters ticket number + transfer code + their five details.
--   5. The organisers see the matched pair, call both, and approve or decline.
--   6. On approval the seat gets the buyer's details, the NEXT FREE ticket number and a new QR.
--      The old number is retired for ever (never given to anyone else); scanning the old QR
--      says TICKET CANCELLED. Counts do not change (same seat, same booking).
--
-- Error messages the pages should translate (text after the colon is what the database raises):
--   TRANSFERS_CLOSED, INVALID_TICKET, ALREADY_TRANSFERRED, NOT_PAID, NOT_GUEST,
--   ALREADY_CHECKED_IN, FORMER_COORDINATOR, INVALID_PRICE, INVALID_PHONE, INVALID_NAME,
--   INVALID_LOCATION, INVALID_ATTENDANCE, INVALID_FOOD, INVALID_CHOICE, ALREADY_LISTED,
--   ALREADY_IN_TRANSFER, NO_ACTIVE_LISTING, NO_ACTIVE_TRANSFER, LISTING_NOT_AVAILABLE,
--   TOO_MANY_INTERESTED, INVALID_TRANSFER, NOT_PENDING, NOT_ALLOWED, INVALID_SETTINGS
-- =====================================================================

-- 1. SETTINGS (off by default; maximum asking price defaults to the ticket price) ------------
alter table settings add column if not exists transfers_open boolean not null default false;
alter table settings add column if not exists max_resale_price integer not null default 250 check (max_resale_price >= 0);

-- 2. TABLES -----------------------------------------------------------------------------------
-- The ads on the board
create table if not exists ticket_listings (
  id uuid primary key default gen_random_uuid(),
  ticket_id uuid not null references tickets(id) on delete cascade,
  price integer not null check (price >= 0),
  contact_phone text not null check (contact_phone ~ '^[0-9]{10}$'),
  status text not null default 'active' check (status in ('active','withdrawn','sold','closed','removed')),
  created_at timestamptz not null default now(),
  closed_at timestamptz);
create unique index if not exists ticket_listings_one_active on ticket_listings (ticket_id) where status = 'active';

-- People who tapped Interested on an ad
create table if not exists ticket_interests (
  id uuid primary key default gen_random_uuid(),
  listing_id uuid not null references ticket_listings(id) on delete cascade,
  name text not null check (char_length(btrim(name)) between 1 and 80),
  phone text not null check (phone ~ '^[0-9]{10}$'),
  choice text not null check (choice in ('talk','agree')),
  created_at timestamptz not null default now(),
  unique (listing_id, phone));

-- The transfer applications and their history
create table if not exists ticket_transfers (
  id uuid primary key default gen_random_uuid(),
  ticket_id uuid not null references tickets(id) on delete cascade,
  code text not null unique,
  status text not null default 'awaiting_buyer'
    check (status in ('awaiting_buyer','pending_admin','done','declined','withdrawn')),
  price integer check (price is null or price >= 0),
  listing_id uuid references ticket_listings(id) on delete set null,
  -- the person receiving the ticket (filled when the buyer applies)
  new_name text, new_phone text, new_location text, new_attendance text, new_food text,
  buyer_applied_at timestamptz,
  -- the person who held the ticket before (filled when the organisers approve)
  from_name text, from_phone text, from_location text, from_attendance text, from_food text,
  from_ticket_no integer, to_ticket_no integer,
  payment_confirmed boolean not null default false,
  decided_by uuid references auth.users(id), decided_at timestamptz, decline_reason text,
  created_at timestamptz not null default now(),
  constraint ticket_transfers_new_values check (
    (new_phone is null or new_phone ~ '^[0-9]{10}$')
    and (new_location is null or new_location in ('In Bengaluru','Outside Bengaluru'))
    and (new_attendance is null or new_attendance in ('Surely','Most probably'))
    and (new_food is null or new_food in ('Veg','Non-veg'))),
  constraint ticket_transfers_buyer_present check (
    status not in ('pending_admin','done')
    or (new_name is not null and new_phone is not null and new_location is not null
        and new_attendance is not null and new_food is not null)));
-- only one live application per ticket; a retired number appears in history only once
create unique index if not exists ticket_transfers_one_open on ticket_transfers (ticket_id)
  where status in ('awaiting_buyer','pending_admin');
create unique index if not exists ticket_transfers_from_no_uq on ticket_transfers (from_ticket_no)
  where from_ticket_no is not null;

-- Same protection as your other tables: only admins can read, nobody can write directly
alter table ticket_listings enable row level security;
alter table ticket_interests enable row level security;
alter table ticket_transfers enable row level security;
revoke all on table ticket_listings, ticket_interests, ticket_transfers from anon, authenticated;
grant select on table ticket_listings, ticket_interests, ticket_transfers to authenticated;
drop policy if exists admin_read_listings on ticket_listings;
create policy admin_read_listings on ticket_listings for select to authenticated using (is_admin());
drop policy if exists admin_read_interests on ticket_interests;
create policy admin_read_interests on ticket_interests for select to authenticated using (is_admin());
drop policy if exists admin_read_transfers on ticket_transfers;
create policy admin_read_transfers on ticket_transfers for select to authenticated using (is_admin());

-- 3. INTERNAL HELPERS (not callable from the website) ----------------------------------------
create or replace function _norm_code(p text) returns text
language sql immutable as $$
  select replace(replace(replace(upper(coalesce(p, '')), 'O', '0'), ' ', ''), '-', '') $$;

-- Why a ticket cannot be sold/transferred right now (null = it can)
create or replace function _transfer_block_reason(t tickets, b bookings) returns text
language sql as $$
  select case
    when b.status <> 'paid' then 'NOT_PAID'
    when t.kind <> 'guest' then 'NOT_GUEST'
    when t.ticket_no is null then 'NOT_PAID'
    when t.checked_in_at is not null then 'ALREADY_CHECKED_IN'
    when t.prev_coord_no is not null then 'FORMER_COORDINATOR'
  end $$;

-- Booking ID + ticket number -> the ticket's id (the seller's proof of ownership)
create or replace function _seller_ticket(p_booking_code text, p_ticket_no integer) returns uuid
language plpgsql security definer set search_path to 'public' as $$
declare c text; b bookings%rowtype; v uuid;
begin
  c := _norm_code(p_booking_code);
  if length(c) <> 8 or p_ticket_no is null then raise exception 'INVALID_TICKET'; end if;
  select * into b from bookings where booking_code = c;
  if not found then raise exception 'INVALID_TICKET'; end if;
  select id into v from tickets where booking_id = b.id and ticket_no = p_ticket_no;
  if found then return v; end if;
  if exists (select 1 from ticket_transfers x join tickets tk on tk.id = x.ticket_id
             where tk.booking_id = b.id and x.from_ticket_no = p_ticket_no and x.status = 'done')
  then raise exception 'ALREADY_TRANSFERRED'; end if;
  raise exception 'INVALID_TICKET';
end $$;

-- 4. PUBLIC FUNCTIONS (the website calls these) ------------------------------------------------
create or replace function get_transfer_status() returns jsonb
language sql stable security definer set search_path to 'public' as $$
  select jsonb_build_object('open', transfers_open, 'max_price', max_resale_price, 'price_per_head', price_per_head)
  from settings where id = 1 $$;

-- The board: only price and age. No names, phones or ticket numbers.
create or replace function list_board() returns jsonb
language sql stable security definer set search_path to 'public' as $$
  select coalesce(jsonb_agg(jsonb_build_object('id', l.id, 'price', l.price, 'posted_at', l.created_at)
                            order by l.created_at desc), '[]'::jsonb)
  from ticket_listings l
  join tickets t on t.id = l.ticket_id
  join bookings b on b.id = t.booking_id
  where (select transfers_open from settings where id = 1)
    and l.status = 'active' and t.kind = 'guest' and t.checked_in_at is null and b.status = 'paid' $$;

create or replace function post_listing(p_code text, p_ticket_no integer, p_price integer, p_contact text) returns jsonb
language plpgsql security definer set search_path to 'public' as $$
declare s settings%rowtype; v uuid; t tickets%rowtype; b bookings%rowtype; l ticket_listings%rowtype; r text;
begin
  select * into s from settings where id = 1;
  if not s.transfers_open then raise exception 'TRANSFERS_CLOSED'; end if;
  v := _seller_ticket(p_code, p_ticket_no);
  select * into t from tickets where id = v for update;
  select * into b from bookings where id = t.booking_id;
  r := _transfer_block_reason(t, b);
  if r is not null then raise exception '%', r; end if;
  if p_price is null or p_price < 0 or p_price > s.max_resale_price then raise exception 'INVALID_PRICE'; end if;
  if coalesce(p_contact, '') !~ '^[0-9]{10}$' then raise exception 'INVALID_PHONE'; end if;
  if exists (select 1 from ticket_transfers where ticket_id = t.id and status in ('awaiting_buyer','pending_admin'))
  then raise exception 'ALREADY_IN_TRANSFER'; end if;
  if exists (select 1 from ticket_listings where ticket_id = t.id and status = 'active')
  then raise exception 'ALREADY_LISTED'; end if;
  insert into ticket_listings (ticket_id, price, contact_phone) values (t.id, p_price, p_contact) returning * into l;
  return jsonb_build_object('id', l.id, 'price', l.price);
end $$;

-- Seller's "Manage my listing" page: their ad, who is interested, and any live transfer
create or replace function manage_ticket(p_code text, p_ticket_no integer) returns jsonb
language plpgsql security definer set search_path to 'public' as $$
declare v uuid; t tickets%rowtype; b bookings%rowtype; s settings%rowtype; l ticket_listings%rowtype;
        x ticket_transfers%rowtype; li jsonb; xi jsonb;
begin
  v := _seller_ticket(p_code, p_ticket_no);
  select * into t from tickets where id = v;
  select * into b from bookings where id = t.booking_id;
  select * into s from settings where id = 1;
  select * into l from ticket_listings where ticket_id = t.id and status = 'active';
  if found then
    li := jsonb_build_object('id', l.id, 'price', l.price, 'contact_phone', l.contact_phone, 'created_at', l.created_at,
      'interests', coalesce((select jsonb_agg(jsonb_build_object('id', i.id, 'name', i.name, 'phone', i.phone,
                  'choice', i.choice, 'created_at', i.created_at) order by i.created_at)
                  from ticket_interests i where i.listing_id = l.id), '[]'::jsonb));
  end if;
  select * into x from ticket_transfers where ticket_id = t.id and status in ('awaiting_buyer','pending_admin');
  if found then
    xi := jsonb_build_object('status', x.status, 'code', x.code, 'price', x.price, 'created_at', x.created_at,
                             'buyer_name', x.new_name, 'buyer_phone', x.new_phone);
  end if;
  return jsonb_build_object('label', _ticket_label(t.kind, t.ticket_no, t.coord_no),
    'open', s.transfers_open, 'max_price', s.max_resale_price,
    'blocked', _transfer_block_reason(t, b), 'listing', li, 'transfer', xi);
end $$;

-- Seller deletes the ad (p_sold = false) or marks it sold/complete (p_sold = true). Works even when transfers are closed.
create or replace function close_listing(p_code text, p_ticket_no integer, p_sold boolean default false) returns void
language plpgsql security definer set search_path to 'public' as $$
declare v uuid; n int;
begin
  v := _seller_ticket(p_code, p_ticket_no);
  update ticket_listings set status = case when coalesce(p_sold, false) then 'sold' else 'withdrawn' end, closed_at = now()
  where ticket_id = v and status = 'active';
  get diagnostics n = row_count;
  if n = 0 then raise exception 'NO_ACTIVE_LISTING'; end if;
end $$;

-- Buyer taps Interested. 'talk' shows the seller's number; 'agree' only records the interest.
create or replace function express_interest(p_listing uuid, p_name text, p_phone text, p_choice text) returns jsonb
language plpgsql security definer set search_path to 'public' as $$
declare s settings%rowtype; l ticket_listings%rowtype; t tickets%rowtype; b bookings%rowtype; n int;
begin
  select * into s from settings where id = 1;
  if not s.transfers_open then raise exception 'TRANSFERS_CLOSED'; end if;
  select * into l from ticket_listings where id = p_listing and status = 'active';
  if not found then raise exception 'LISTING_NOT_AVAILABLE'; end if;
  select * into t from tickets where id = l.ticket_id;
  select * into b from bookings where id = t.booking_id;
  if _transfer_block_reason(t, b) is not null then raise exception 'LISTING_NOT_AVAILABLE'; end if;
  if length(trim(coalesce(p_name, ''))) not between 1 and 80 then raise exception 'INVALID_NAME'; end if;
  if coalesce(p_phone, '') !~ '^[0-9]{10}$' then raise exception 'INVALID_PHONE'; end if;
  if coalesce(p_choice, '') not in ('talk', 'agree') then raise exception 'INVALID_CHOICE'; end if;
  select count(*) into n from ticket_interests where listing_id = l.id;
  if n >= 50 and not exists (select 1 from ticket_interests where listing_id = l.id and phone = p_phone)
  then raise exception 'TOO_MANY_INTERESTED'; end if;
  insert into ticket_interests (listing_id, name, phone, choice) values (l.id, trim(p_name), p_phone, p_choice)
  on conflict (listing_id, phone) do update set name = excluded.name, choice = excluded.choice;
  return jsonb_build_object('choice', p_choice, 'price', l.price,
                            'contact_phone', case when p_choice = 'talk' then l.contact_phone end);
end $$;

-- Seller submits the transfer application. Returns the one-time transfer code to give the buyer.
-- Works with or without an ad (p_price is only used when there is no ad; it is optional).
create or replace function start_transfer(p_code text, p_ticket_no integer, p_price integer default null) returns jsonb
language plpgsql security definer set search_path to 'public' as $$
declare s settings%rowtype; v uuid; t tickets%rowtype; b bookings%rowtype; l ticket_listings%rowtype;
        x ticket_transfers%rowtype; r text; c text; price int;
begin
  select * into s from settings where id = 1;
  if not s.transfers_open then raise exception 'TRANSFERS_CLOSED'; end if;
  v := _seller_ticket(p_code, p_ticket_no);
  select * into t from tickets where id = v for update;
  select * into b from bookings where id = t.booking_id;
  r := _transfer_block_reason(t, b);
  if r is not null then raise exception '%', r; end if;
  if exists (select 1 from ticket_transfers where ticket_id = t.id and status in ('awaiting_buyer','pending_admin'))
  then raise exception 'ALREADY_IN_TRANSFER'; end if;
  select * into l from ticket_listings where ticket_id = t.id and status = 'active' for update;
  if found then
    price := l.price;
    update ticket_listings set status = 'closed', closed_at = now() where id = l.id;
  else
    price := p_price;
    if price is not null and (price < 0 or price > s.max_resale_price) then raise exception 'INVALID_PRICE'; end if;
  end if;
  loop
    c := upper(substr(replace(gen_random_uuid()::text, '-', ''), 1, 10));
    exit when not exists (select 1 from ticket_transfers where code = c);
  end loop;
  insert into ticket_transfers (ticket_id, code, price, listing_id)
  values (t.id, c, price, l.id) returning * into x;
  return jsonb_build_object('code', x.code, 'price', x.price, 'label', _ticket_label(t.kind, t.ticket_no, t.coord_no));
end $$;

-- Seller cancels their live transfer application. Works even when transfers are closed.
create or replace function withdraw_transfer(p_code text, p_ticket_no integer) returns void
language plpgsql security definer set search_path to 'public' as $$
declare v uuid; n int;
begin
  v := _seller_ticket(p_code, p_ticket_no);
  perform 1 from tickets where id = v for update;
  update ticket_transfers set status = 'withdrawn' where ticket_id = v and status in ('awaiting_buyer','pending_admin');
  get diagnostics n = row_count;
  if n = 0 then raise exception 'NO_ACTIVE_TRANSFER'; end if;
end $$;

-- Buyer's side: ticket number + transfer code + the five details. Can be re-sent until the organisers decide.
create or replace function apply_receive(p_ticket_no integer, p_code text, p_name text, p_phone text,
                                         p_location text, p_attendance text, p_food text) returns jsonb
language plpgsql security definer set search_path to 'public' as $$
declare s settings%rowtype; c text; v uuid; t tickets%rowtype; b bookings%rowtype; x ticket_transfers%rowtype; r text;
begin
  select * into s from settings where id = 1;
  if not s.transfers_open then raise exception 'TRANSFERS_CLOSED'; end if;
  c := _norm_code(p_code);
  if length(c) <> 10 or p_ticket_no is null then raise exception 'INVALID_TRANSFER'; end if;
  select ticket_id into v from ticket_transfers where code = c;
  if not found then raise exception 'INVALID_TRANSFER'; end if;
  select * into t from tickets where id = v for update;           -- lock order: ticket first, then the application
  select * into x from ticket_transfers where code = c for update;
  if t.ticket_no is distinct from p_ticket_no or x.status not in ('awaiting_buyer','pending_admin')
  then raise exception 'INVALID_TRANSFER'; end if;
  select * into b from bookings where id = t.booking_id;
  r := _transfer_block_reason(t, b);
  if r is not null then raise exception '%', r; end if;
  if length(trim(coalesce(p_name, ''))) not between 1 and 80 then raise exception 'INVALID_NAME'; end if;
  if coalesce(p_phone, '') !~ '^[0-9]{10}$' then raise exception 'INVALID_PHONE'; end if;
  if coalesce(p_location, '') not in ('In Bengaluru', 'Outside Bengaluru') then raise exception 'INVALID_LOCATION'; end if;
  if coalesce(p_attendance, '') not in ('Surely', 'Most probably') then raise exception 'INVALID_ATTENDANCE'; end if;
  if coalesce(p_food, '') not in ('Veg', 'Non-veg') then raise exception 'INVALID_FOOD'; end if;
  update ticket_transfers set new_name = trim(p_name), new_phone = p_phone, new_location = p_location,
    new_attendance = p_attendance, new_food = p_food, buyer_applied_at = now(), status = 'pending_admin'
  where id = x.id;
  return lookup_transfer(c);
end $$;

-- Status page, by transfer code only. After approval it returns the buyer's own new ticket.
create or replace function lookup_transfer(p_code text) returns jsonb
language plpgsql security definer set search_path to 'public' as $$
declare c text; x ticket_transfers%rowtype; t tickets%rowtype; b bookings%rowtype; res jsonb;
begin
  c := _norm_code(p_code);
  if length(c) <> 10 then return null; end if;
  select * into x from ticket_transfers where code = c;
  if not found then return null; end if;
  select * into t from tickets where id = x.ticket_id;
  select * into b from bookings where id = t.booking_id;
  res := jsonb_build_object('status', x.status, 'price', x.price, 'buyer_applied', x.new_name is not null,
                            'decline_reason', x.decline_reason);
  if x.status in ('awaiting_buyer', 'pending_admin') then
    res := res || jsonb_build_object('old_label', _ticket_label('guest', t.ticket_no, null));
  elsif x.status = 'done' then
    res := res || jsonb_build_object('old_label', _ticket_label('guest', x.from_ticket_no, null));
    -- show the ticket only while it is still the one issued by this transfer (never a later holder's)
    if t.ticket_no is not distinct from x.to_ticket_no and t.kind = 'guest' and b.status = 'paid' then
      res := res || jsonb_build_object('ticket', jsonb_build_object('label', _ticket_label(t.kind, t.ticket_no, t.coord_no),
        'secret', t.secret, 'name', t.name, 'location', t.location, 'attendance', t.attendance, 'food', t.food));
    end if;
  end if;
  return res;
end $$;

-- 5. ADMIN FUNCTIONS --------------------------------------------------------------------------
create or replace function admin_set_transfer_settings(p_open boolean, p_max_price integer) returns void
language plpgsql security definer set search_path to 'public' as $$
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  if p_open is null or p_max_price is null or p_max_price < 0 or p_max_price > 100000 then raise exception 'INVALID_SETTINGS'; end if;
  update settings set transfers_open = p_open, max_resale_price = p_max_price where id = 1;
end $$;

-- Approve a matched pair: new person, NEXT FREE number, new QR. The old number is retired for good.
create or replace function approve_transfer(p_id uuid, p_payment_confirmed boolean default false) returns jsonb
language plpgsql security definer set search_path to 'public' as $$
declare s settings%rowtype; v uuid; t tickets%rowtype; b bookings%rowtype; x ticket_transfers%rowtype; r text; new_no int;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  select * into s from settings where id = 1 for update;          -- same lock order as the gate: settings, ticket, ...
  select ticket_id into v from ticket_transfers where id = p_id;
  if not found then raise exception 'INVALID_TRANSFER'; end if;
  select * into t from tickets where id = v for update;
  select * into x from ticket_transfers where id = p_id for update;
  if x.status <> 'pending_admin' then raise exception 'NOT_PENDING'; end if;
  select * into b from bookings where id = t.booking_id;
  r := _transfer_block_reason(t, b);                                -- checked again now: it may have changed while waiting
  if r is not null then raise exception '%', r; end if;
  new_no := s.next_ticket;
  update ticket_transfers set status = 'done',
    from_name = t.name, from_phone = t.phone, from_location = t.location, from_attendance = t.attendance,
    from_food = t.food, from_ticket_no = t.ticket_no, to_ticket_no = new_no,
    payment_confirmed = coalesce(p_payment_confirmed, false), decided_by = auth.uid(), decided_at = now()
  where id = x.id;
  update tickets set ticket_no = new_no, secret = substr(replace(gen_random_uuid()::text, '-', ''), 1, 12),
    name = x.new_name, phone = x.new_phone, location = x.new_location,
    attendance = x.new_attendance, food = x.new_food
  where id = t.id;
  update settings set next_ticket = next_ticket + 1 where id = 1;
  update ticket_listings set status = 'closed', closed_at = now() where ticket_id = t.id and status = 'active';
  return jsonb_build_object('id', t.id, 'old_label', _ticket_label('guest', t.ticket_no, null),
                            'label', _ticket_label('guest', new_no, null), 'name', x.new_name);
end $$;

create or replace function decline_transfer(p_id uuid, p_reason text default null) returns void
language plpgsql security definer set search_path to 'public' as $$
declare x ticket_transfers%rowtype;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  select * into x from ticket_transfers where id = p_id for update;
  if not found then raise exception 'INVALID_TRANSFER'; end if;
  if x.status not in ('awaiting_buyer', 'pending_admin') then raise exception 'NOT_PENDING'; end if;
  update ticket_transfers set status = 'declined', decided_by = auth.uid(), decided_at = now(),
    decline_reason = nullif(left(btrim(coalesce(p_reason, '')), 200), '') where id = x.id;
end $$;

create or replace function admin_remove_listing(p_id uuid) returns void
language plpgsql security definer set search_path to 'public' as $$
declare n int;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  update ticket_listings set status = 'removed', closed_at = now() where id = p_id and status = 'active';
  get diagnostics n = row_count;
  if n = 0 then raise exception 'NO_ACTIVE_LISTING'; end if;
end $$;


-- 6. GATE: a number retired by a transfer now says TICKET CANCELLED (everything else in admit_ticket is unchanged) --
CREATE OR REPLACE FUNCTION public.admit_ticket(p_ticket_no integer DEFAULT NULL::integer, p_secret text DEFAULT NULL::text, p_approve boolean DEFAULT false, p_coord boolean DEFAULT false, p_id uuid DEFAULT NULL::uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare t tickets%rowtype; b bookings%rowtype; info jsonb; who text;
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

-- 7. WHO MAY CALL WHAT ---------------------------------------------------------------------------
revoke all on function _norm_code(text) from public;
revoke all on function _transfer_block_reason(tickets, bookings) from public;
revoke all on function _seller_ticket(text, integer) from public;
revoke all on function get_transfer_status() from public;
revoke all on function list_board() from public;
revoke all on function post_listing(text, integer, integer, text) from public;
revoke all on function manage_ticket(text, integer) from public;
revoke all on function close_listing(text, integer, boolean) from public;
revoke all on function express_interest(uuid, text, text, text) from public;
revoke all on function start_transfer(text, integer, integer) from public;
revoke all on function withdraw_transfer(text, integer) from public;
revoke all on function apply_receive(integer, text, text, text, text, text, text) from public;
revoke all on function lookup_transfer(text) from public;
revoke all on function admin_set_transfer_settings(boolean, integer) from public;
revoke all on function approve_transfer(uuid, boolean) from public;
revoke all on function decline_transfer(uuid, text) from public;
revoke all on function admin_remove_listing(uuid) from public;
revoke all on function admit_ticket(integer, text, boolean, boolean, uuid) from public;
-- website visitors (no login)
grant execute on function get_transfer_status() to anon, authenticated;
grant execute on function list_board() to anon, authenticated;
grant execute on function post_listing(text, integer, integer, text) to anon, authenticated;
grant execute on function manage_ticket(text, integer) to anon, authenticated;
grant execute on function close_listing(text, integer, boolean) to anon, authenticated;
grant execute on function express_interest(uuid, text, text, text) to anon, authenticated;
grant execute on function start_transfer(text, integer, integer) to anon, authenticated;
grant execute on function withdraw_transfer(text, integer) to anon, authenticated;
grant execute on function apply_receive(integer, text, text, text, text, text, text) to anon, authenticated;
grant execute on function lookup_transfer(text) to anon, authenticated;
-- signed-in staff only (admins are checked again inside each function)
grant execute on function admin_set_transfer_settings(boolean, integer) to authenticated;
grant execute on function approve_transfer(uuid, boolean) to authenticated;
grant execute on function decline_transfer(uuid, text) to authenticated;
grant execute on function admin_remove_listing(uuid) to authenticated;
grant execute on function admit_ticket(integer, text, boolean, boolean, uuid) to authenticated;

-- =====================================================================
-- TICKET TRANSFER, PART 2  (Public/Private transfer, locked price, comments, coordinator transfers)
-- Run this AFTER "transfer-feature.sql" (part 1). Safe to run more than once.
-- Run it in the Supabase SQL editor.
--
-- What changes compared with part 1
--   * Every ad / transfer is PRIVATE (buyer pays seller directly, organisers only approve)
--     or PUBLIC (buyer pays the organisers, organisers pay the seller after approval).
--   * The seller picks the price on the ad and may add a short comment (no phone numbers).
--     Editing the price closes the old ad ("edited") and opens a new one, so a buyer who
--     tapped Buy at Rs 200 can never be charged Rs 250. Starting the transfer locks the price.
--   * A buyer's tap on Buy remembers the price the buyer saw. A buyer can check the request
--     with ad + phone and is shown the transfer code once the seller has chosen them.
--   * Public transfers track the money: amount confirmed with the seller, buyer's payment proof,
--     payment received, seller paid, refund.
--   * Coordinators and former coordinators can now transfer too. On approval the buyer gets a
--     brand-new GUEST number and QR; the coordinator number (and any old guest number) is retired
--     for good. The seller's ticket is typed exactly as printed: 7, E26-007 or E26-001C.
--   * The retired-number check at the gate also covers retired coordinator numbers.
--
-- New error messages the pages should translate (the old ones from part 1 still apply, except
-- NOT_GUEST and FORMER_COORDINATOR which no longer happen):
--   INVALID_MODE, INVALID_PAYOUT, INVALID_COMMENT, INVALID_BUYER, COORDINATOR_ACK_REQUIRED,
--   WRONG_BUYER, PAYMENT_IN_PROGRESS, AMOUNT_NOT_CONFIRMED, PAYMENT_NOT_RECEIVED,
--   SCREENSHOT_MISSING, NOT_PUBLIC, INVALID_AMOUNT
-- =====================================================================

-- 1. TABLE CHANGES -----------------------------------------------------------------------------
alter table ticket_listings add column if not exists mode text not null default 'private';
alter table ticket_listings add column if not exists comment text;
alter table ticket_listings drop constraint if exists ticket_listings_mode_check;
alter table ticket_listings add constraint ticket_listings_mode_check check (mode in ('private','public'));
alter table ticket_listings drop constraint if exists ticket_listings_comment_check;
alter table ticket_listings add constraint ticket_listings_comment_check
  check (comment is null or char_length(comment) between 1 and 140);
-- an ad whose price was changed is kept as history with status 'edited'
alter table ticket_listings drop constraint if exists ticket_listings_status_check;
alter table ticket_listings add constraint ticket_listings_status_check
  check (status in ('active','withdrawn','sold','closed','removed','edited'));

alter table ticket_interests add column if not exists price_seen integer;

alter table ticket_transfers add column if not exists mode text not null default 'private';
alter table ticket_transfers add column if not exists payout text;                 -- seller's UPI ID or phone (Public only)
alter table ticket_transfers add column if not exists agreed_amount integer;       -- what the buyer pays the organisers (Public only)
alter table ticket_transfers add column if not exists amount_confirmed_at timestamptz;
alter table ticket_transfers add column if not exists amount_confirmed_by uuid references auth.users(id);
alter table ticket_transfers add column if not exists intended_phone text;         -- the buyer the seller chose (optional)
alter table ticket_transfers add column if not exists buyer_interest_id uuid references ticket_interests(id) on delete set null;
alter table ticket_transfers add column if not exists buyer_paid_at timestamptz;
alter table ticket_transfers add column if not exists buyer_screenshot_path text;
alter table ticket_transfers add column if not exists payment_received_at timestamptz;
alter table ticket_transfers add column if not exists payment_received_by uuid references auth.users(id);
alter table ticket_transfers add column if not exists seller_paid_at timestamptz;
alter table ticket_transfers add column if not exists seller_paid_ref text;
alter table ticket_transfers add column if not exists refunded_at timestamptz;
alter table ticket_transfers add column if not exists refund_ref text;
alter table ticket_transfers add column if not exists from_kind text;              -- guest / coordinator / former_coordinator
alter table ticket_transfers add column if not exists from_coord_no integer;       -- retired coordinator number

alter table ticket_transfers drop constraint if exists ticket_transfers_mode_check;
alter table ticket_transfers add constraint ticket_transfers_mode_check check (mode in ('private','public'));
alter table ticket_transfers drop constraint if exists ticket_transfers_from_kind_check;
alter table ticket_transfers add constraint ticket_transfers_from_kind_check
  check (from_kind is null or from_kind in ('guest','coordinator','former_coordinator'));
alter table ticket_transfers drop constraint if exists ticket_transfers_payout_check;
alter table ticket_transfers add constraint ticket_transfers_payout_check
  check (payout is null or payout ~ '^([0-9]{10}|[A-Za-z0-9._-]{2,64}@[A-Za-z][A-Za-z0-9]{1,31})$');
alter table ticket_transfers drop constraint if exists ticket_transfers_amount_check;
alter table ticket_transfers add constraint ticket_transfers_amount_check
  check (agreed_amount is null or agreed_amount >= 0);
-- a retired coordinator number appears in history only once
create unique index if not exists ticket_transfers_from_coord_uq on ticket_transfers (from_coord_no)
  where from_coord_no is not null;

-- 2. REMOVE THE OLD VERSIONS WHOSE ARGUMENTS CHANGED -------------------------------------------
drop function if exists post_listing(text, integer, integer, text);
drop function if exists manage_ticket(text, integer);
drop function if exists close_listing(text, integer, boolean);
drop function if exists start_transfer(text, integer, integer);
drop function if exists withdraw_transfer(text, integer);
drop function if exists apply_receive(integer, text, text, text, text, text, text);
drop function if exists _seller_ticket(text, integer);

-- 3. INTERNAL HELPERS ----------------------------------------------------------------------------
-- "E26-007", "7", "e26 007" -> guest 7;  "E26-001C", "1c" -> coordinator 1;  anything else -> nulls
create or replace function _parse_ticket(p text, out kind text, out no integer)
language plpgsql immutable as $$
declare s text;
begin
  s := upper(regexp_replace(coalesce(p, ''), '[\s-]', '', 'g'));
  s := regexp_replace(s, '^E26', '');
  s := replace(s, 'O', '0');
  if s ~ '^[0-9]{1,6}C$' then kind := 'coordinator'; no := substr(s, 1, length(s) - 1)::integer;
  elsif s ~ '^[0-9]{1,6}$' then kind := 'guest'; no := s::integer;
  end if;
end $$;

-- What kind of seat this is: guest, coordinator, or a guest who used to be a coordinator
create or replace function _seller_kind(t tickets) returns text
language sql immutable as $$
  select case when t.kind = 'coordinator' then 'coordinator'
              when t.prev_coord_no is not null then 'former_coordinator'
              else 'guest' end $$;

-- Why a ticket cannot be sold/transferred right now (null = it can).
-- Coordinators and former coordinators are allowed now; only unpaid or already-scanned tickets are blocked.
create or replace function _transfer_block_reason(t tickets, b bookings) returns text
language sql as $$
  select case
    when b.status <> 'paid' then 'NOT_PAID'
    when t.kind = 'guest' and t.ticket_no is null then 'NOT_PAID'
    when t.checked_in_at is not null then 'ALREADY_CHECKED_IN'
  end $$;

-- Booking ID + ticket as printed -> the ticket's id (the seller's proof of ownership)
create or replace function _seller_ticket(p_booking_code text, p_ticket text) returns uuid
language plpgsql security definer set search_path to 'public' as $$
declare c text; b bookings%rowtype; v uuid; k text; n integer;
begin
  c := _norm_code(p_booking_code);
  if length(c) <> 8 then raise exception 'INVALID_TICKET'; end if;
  select kind, no into k, n from _parse_ticket(p_ticket);
  if k is null then raise exception 'INVALID_TICKET'; end if;
  select * into b from bookings where booking_code = c;
  if not found then raise exception 'INVALID_TICKET'; end if;
  if k = 'guest' then
    select id into v from tickets where booking_id = b.id and kind = 'guest' and ticket_no = n;
  else
    select id into v from tickets where booking_id = b.id and kind = 'coordinator' and coord_no = n;
  end if;
  if found then return v; end if;
  if exists (select 1 from ticket_transfers x join tickets tk on tk.id = x.ticket_id
             where tk.booking_id = b.id and x.status = 'done'
               and ((k = 'guest' and x.from_ticket_no = n) or (k = 'coordinator' and x.from_coord_no = n)))
  then raise exception 'ALREADY_TRANSFERRED'; end if;
  raise exception 'INVALID_TICKET';
end $$;

-- A seller's comment: short, plain text, no phone numbers / UPI IDs / links (those would skip the organisers)
create or replace function _clean_comment(p text) returns text
language plpgsql immutable as $$
declare v text;
begin
  if p is null then return null; end if;
  v := btrim(regexp_replace(p, '\s+', ' ', 'g'));
  if v = '' then return null; end if;
  if char_length(v) > 140
     or length(regexp_replace(v, '[^0-9]', '', 'g')) >= 8
     or position('@' in v) > 0
     or v ~* '(https?:|www\.)'
  then raise exception 'INVALID_COMMENT'; end if;
  return v;
end $$;

-- The seller's payout: a 10-digit phone number or a UPI ID like name@bank
create or replace function _clean_payout(p text) returns text
language plpgsql immutable as $$
declare v text;
begin
  v := btrim(coalesce(p, ''));
  if v ~ '^[0-9]{10}$' or v ~ '^[A-Za-z0-9._-]{2,64}@[A-Za-z][A-Za-z0-9]{1,31}$' then return v; end if;
  raise exception 'INVALID_PAYOUT';
end $$;

-- 4. PUBLIC FUNCTIONS ----------------------------------------------------------------------------
create or replace function list_board() returns jsonb
language sql stable security definer set search_path to 'public' as $$
  select coalesce(jsonb_agg(jsonb_build_object('id', l.id, 'price', l.price, 'mode', l.mode, 'comment', l.comment,
                                               'posted_at', l.created_at) order by l.created_at desc), '[]'::jsonb)
  from ticket_listings l
  join tickets t on t.id = l.ticket_id
  join bookings b on b.id = t.booking_id
  where (select transfers_open from settings where id = 1)
    and l.status = 'active' and t.checked_in_at is null and b.status = 'paid' $$;

create or replace function post_listing(p_code text, p_ticket text, p_price integer, p_contact text,
                                        p_mode text default 'private', p_comment text default null,
                                        p_ack boolean default false) returns jsonb
language plpgsql security definer set search_path to 'public' as $$
declare s settings%rowtype; v uuid; t tickets%rowtype; b bookings%rowtype; l ticket_listings%rowtype; r text; cm text;
begin
  select * into s from settings where id = 1;
  if not s.transfers_open then raise exception 'TRANSFERS_CLOSED'; end if;
  v := _seller_ticket(p_code, p_ticket);
  select * into t from tickets where id = v for update;
  select * into b from bookings where id = t.booking_id;
  r := _transfer_block_reason(t, b);
  if r is not null then raise exception '%', r; end if;
  if coalesce(p_mode, '') not in ('private', 'public') then raise exception 'INVALID_MODE'; end if;
  if _seller_kind(t) <> 'guest' and not coalesce(p_ack, false) then raise exception 'COORDINATOR_ACK_REQUIRED'; end if;
  if p_price is null or p_price < 0 or p_price > s.max_resale_price then raise exception 'INVALID_PRICE'; end if;
  if coalesce(p_contact, '') !~ '^[0-9]{10}$' then raise exception 'INVALID_PHONE'; end if;
  cm := _clean_comment(p_comment);
  if exists (select 1 from ticket_transfers where ticket_id = t.id and status in ('awaiting_buyer','pending_admin'))
  then raise exception 'ALREADY_IN_TRANSFER'; end if;
  if exists (select 1 from ticket_listings where ticket_id = t.id and status = 'active')
  then raise exception 'ALREADY_LISTED'; end if;
  insert into ticket_listings (ticket_id, price, contact_phone, mode, comment)
  values (t.id, p_price, p_contact, p_mode, cm) returning * into l;
  return jsonb_build_object('id', l.id, 'price', l.price, 'mode', l.mode);
end $$;

-- Change the price (closes the old ad as 'edited' and opens a new one) and/or the comment (changed in place).
-- p_comment: null keeps the current comment, '' clears it.
create or replace function edit_listing(p_code text, p_ticket text, p_price integer, p_comment text default null) returns jsonb
language plpgsql security definer set search_path to 'public' as $$
declare s settings%rowtype; v uuid; t tickets%rowtype; b bookings%rowtype; l ticket_listings%rowtype;
        n ticket_listings%rowtype; r text; cm text;
begin
  select * into s from settings where id = 1;
  if not s.transfers_open then raise exception 'TRANSFERS_CLOSED'; end if;
  v := _seller_ticket(p_code, p_ticket);
  select * into t from tickets where id = v for update;
  select * into b from bookings where id = t.booking_id;
  r := _transfer_block_reason(t, b);
  if r is not null then raise exception '%', r; end if;
  if exists (select 1 from ticket_transfers where ticket_id = t.id and status in ('awaiting_buyer','pending_admin'))
  then raise exception 'ALREADY_IN_TRANSFER'; end if;
  select * into l from ticket_listings where ticket_id = t.id and status = 'active' for update;
  if not found then raise exception 'NO_ACTIVE_LISTING'; end if;
  if p_price is null or p_price < 0 or p_price > s.max_resale_price then raise exception 'INVALID_PRICE'; end if;
  cm := case when p_comment is null then l.comment else _clean_comment(p_comment) end;
  if p_price = l.price then
    update ticket_listings set comment = cm where id = l.id;
    return jsonb_build_object('id', l.id, 'price', l.price, 'changed', false);
  end if;
  update ticket_listings set status = 'edited', closed_at = now() where id = l.id;
  insert into ticket_listings (ticket_id, price, contact_phone, mode, comment)
  values (t.id, p_price, l.contact_phone, l.mode, cm) returning * into n;
  return jsonb_build_object('id', n.id, 'price', n.price, 'changed', true);
end $$;

-- Seller's "Manage my listing" page
create or replace function manage_ticket(p_code text, p_ticket text) returns jsonb
language plpgsql security definer set search_path to 'public' as $$
declare v uuid; t tickets%rowtype; b bookings%rowtype; s settings%rowtype; l ticket_listings%rowtype;
        x ticket_transfers%rowtype; li jsonb; xi jsonb; hist jsonb;
begin
  v := _seller_ticket(p_code, p_ticket);
  select * into t from tickets where id = v;
  select * into b from bookings where id = t.booking_id;
  select * into s from settings where id = 1;
  select * into l from ticket_listings where ticket_id = t.id and status = 'active';
  if found then
    li := jsonb_build_object('id', l.id, 'price', l.price, 'mode', l.mode, 'comment', l.comment,
      'contact_phone', l.contact_phone, 'created_at', l.created_at,
      'interests', coalesce((select jsonb_agg(jsonb_build_object('id', i.id, 'name', i.name, 'phone', i.phone,
                  'choice', i.choice, 'price_seen', i.price_seen, 'created_at', i.created_at) order by i.created_at)
                  from ticket_interests i where i.listing_id = l.id), '[]'::jsonb));
  end if;
  select coalesce(jsonb_agg(h.j order by h.created_at desc), '[]'::jsonb) into hist
  from (select jsonb_build_object('id', o.id, 'price', o.price, 'status', o.status, 'comment', o.comment,
                                  'created_at', o.created_at, 'closed_at', o.closed_at) as j, o.created_at
        from ticket_listings o where o.ticket_id = t.id and o.status <> 'active'
        order by o.created_at desc limit 10) h;
  select * into x from ticket_transfers where ticket_id = t.id and status in ('awaiting_buyer','pending_admin');
  if found then
    xi := jsonb_build_object('status', x.status, 'code', x.code, 'mode', x.mode, 'price', x.price,
                             'agreed_amount', x.agreed_amount, 'amount_confirmed', x.amount_confirmed_at is not null,
                             'created_at', x.created_at, 'buyer_name', x.new_name, 'buyer_phone', x.new_phone,
                             'buyer_paid', x.buyer_paid_at is not null,
                             'payment_received', x.payment_received_at is not null, 'payout', x.payout);
  end if;
  return jsonb_build_object('label', _ticket_label(t.kind, t.ticket_no, t.coord_no),
    'kind', _seller_kind(t), 'open', s.transfers_open, 'max_price', s.max_resale_price,
    'blocked', _transfer_block_reason(t, b), 'listing', li, 'history', hist, 'transfer', xi);
end $$;

-- Seller deletes the ad (p_sold = false) or marks it sold/complete (p_sold = true). Works even when transfers are closed.
create or replace function close_listing(p_code text, p_ticket text, p_sold boolean default false) returns void
language plpgsql security definer set search_path to 'public' as $$
declare v uuid; n int;
begin
  v := _seller_ticket(p_code, p_ticket);
  update ticket_listings set status = case when coalesce(p_sold, false) then 'sold' else 'withdrawn' end, closed_at = now()
  where ticket_id = v and status = 'active';
  get diagnostics n = row_count;
  if n = 0 then raise exception 'NO_ACTIVE_LISTING'; end if;
end $$;

-- Buyer taps Buy/Interested. Remembers the price the buyer saw. In a Public ad the seller's number is never shown.
create or replace function express_interest(p_listing uuid, p_name text, p_phone text, p_choice text) returns jsonb
language plpgsql security definer set search_path to 'public' as $$
declare s settings%rowtype; l ticket_listings%rowtype; t tickets%rowtype; b bookings%rowtype; n int;
begin
  select * into s from settings where id = 1;
  if not s.transfers_open then raise exception 'TRANSFERS_CLOSED'; end if;
  select * into l from ticket_listings where id = p_listing and status = 'active';
  if not found then raise exception 'LISTING_NOT_AVAILABLE'; end if;
  select * into t from tickets where id = l.ticket_id;
  select * into b from bookings where id = t.booking_id;
  if _transfer_block_reason(t, b) is not null then raise exception 'LISTING_NOT_AVAILABLE'; end if;
  if length(trim(coalesce(p_name, ''))) not between 1 and 80 then raise exception 'INVALID_NAME'; end if;
  if coalesce(p_phone, '') !~ '^[0-9]{10}$' then raise exception 'INVALID_PHONE'; end if;
  if coalesce(p_choice, '') not in ('talk', 'agree') then raise exception 'INVALID_CHOICE'; end if;
  select count(*) into n from ticket_interests where listing_id = l.id;
  if n >= 50 and not exists (select 1 from ticket_interests where listing_id = l.id and phone = p_phone)
  then raise exception 'TOO_MANY_INTERESTED'; end if;
  insert into ticket_interests (listing_id, name, phone, choice, price_seen)
  values (l.id, trim(p_name), p_phone, p_choice, l.price)
  on conflict (listing_id, phone) do update set name = excluded.name, choice = excluded.choice, price_seen = excluded.price_seen;
  return jsonb_build_object('choice', p_choice, 'price', l.price, 'mode', l.mode,
                            'contact_phone', case when p_choice = 'talk' and l.mode = 'private' then l.contact_phone end);
end $$;

-- The buyer's "Check my request" page: ad + the phone used when tapping Buy.
-- States: waiting, price_changed, accepted (shows the transfer code), done, ended, taken, sold, gone
create or replace function check_request(p_listing uuid, p_phone text) returns jsonb
language plpgsql security definer set search_path to 'public' as $$
declare i ticket_interests%rowtype; l ticket_listings%rowtype; n ticket_listings%rowtype;
        x ticket_transfers%rowtype; t tickets%rowtype;
begin
  if coalesce(p_phone, '') !~ '^[0-9]{10}$' then raise exception 'INVALID_PHONE'; end if;
  select * into i from ticket_interests where listing_id = p_listing and phone = p_phone;
  if not found then return null; end if;
  select * into l from ticket_listings where id = p_listing;
  if l.status = 'active' then
    return jsonb_build_object('state', 'waiting', 'price', l.price, 'mode', l.mode);
  elsif l.status = 'edited' then
    select * into n from ticket_listings where ticket_id = l.ticket_id and status = 'active';
    if found then
      return jsonb_build_object('state', 'price_changed', 'old_price', i.price_seen, 'new_price', n.price,
                                'new_listing', n.id, 'mode', n.mode);
    end if;
    return jsonb_build_object('state', 'gone');
  elsif l.status = 'closed' then
    select * into x from ticket_transfers where listing_id = l.id order by created_at desc limit 1;
    if not found or x.intended_phone is distinct from p_phone then
      return jsonb_build_object('state', 'taken');
    end if;
    if x.status in ('awaiting_buyer', 'pending_admin') then
      select * into t from tickets where id = x.ticket_id;
      return jsonb_build_object('state', 'accepted', 'code', x.code, 'mode', x.mode, 'price', x.price,
                                'ticket', _ticket_label(t.kind, t.ticket_no, t.coord_no));
    elsif x.status = 'done' then
      return jsonb_build_object('state', 'done', 'code', x.code);
    end if;
    return jsonb_build_object('state', 'ended');
  elsif l.status = 'sold' then
    return jsonb_build_object('state', 'sold');
  end if;
  return jsonb_build_object('state', 'gone');
end $$;

-- Seller starts the transfer. Locks the price and returns the one-time transfer code.
--   with an ad: mode and price come from the ad; p_buyer (optional) is one of the people who tapped Buy
--   without an ad: p_mode is required; a Public transfer also needs p_price (the amount to collect)
--   Public transfers need the seller's payout (UPI ID or phone)
create or replace function start_transfer(p_code text, p_ticket text, p_price integer default null,
                                          p_mode text default null, p_payout text default null,
                                          p_buyer uuid default null, p_ack boolean default false) returns jsonb
language plpgsql security definer set search_path to 'public' as $$
declare s settings%rowtype; v uuid; t tickets%rowtype; b bookings%rowtype; l ticket_listings%rowtype;
        i ticket_interests%rowtype; x ticket_transfers%rowtype; r text; c text; price int; md text; po text;
begin
  select * into s from settings where id = 1;
  if not s.transfers_open then raise exception 'TRANSFERS_CLOSED'; end if;
  v := _seller_ticket(p_code, p_ticket);
  select * into t from tickets where id = v for update;
  select * into b from bookings where id = t.booking_id;
  r := _transfer_block_reason(t, b);
  if r is not null then raise exception '%', r; end if;
  if _seller_kind(t) <> 'guest' and not coalesce(p_ack, false) then raise exception 'COORDINATOR_ACK_REQUIRED'; end if;
  if exists (select 1 from ticket_transfers where ticket_id = t.id and status in ('awaiting_buyer','pending_admin'))
  then raise exception 'ALREADY_IN_TRANSFER'; end if;
  select * into l from ticket_listings where ticket_id = t.id and status = 'active' for update;
  if found then
    md := l.mode;
    price := l.price;
    if price > s.max_resale_price then raise exception 'INVALID_PRICE'; end if;
    if p_buyer is not null then
      select * into i from ticket_interests where id = p_buyer and listing_id = l.id;
      if not found then raise exception 'INVALID_BUYER'; end if;
    end if;
    update ticket_listings set status = 'closed', closed_at = now() where id = l.id;
  else
    md := coalesce(p_mode, '');
    if md not in ('private', 'public') then raise exception 'INVALID_MODE'; end if;
    if p_buyer is not null then raise exception 'INVALID_BUYER'; end if;
    price := p_price;
    if price is not null and (price < 0 or price > s.max_resale_price) then raise exception 'INVALID_PRICE'; end if;
    if md = 'public' and price is null then raise exception 'INVALID_PRICE'; end if;
  end if;
  if md = 'public' then po := _clean_payout(p_payout); end if;
  loop
    c := upper(substr(replace(gen_random_uuid()::text, '-', ''), 1, 10));
    exit when not exists (select 1 from ticket_transfers where code = c);
  end loop;
  insert into ticket_transfers (ticket_id, code, price, listing_id, mode, payout, agreed_amount,
                                intended_phone, buyer_interest_id)
  values (t.id, c, price, l.id, md, po, case when md = 'public' then price end, i.phone, i.id)
  returning * into x;
  return jsonb_build_object('code', x.code, 'price', x.price, 'mode', x.mode,
                            'label', _ticket_label(t.kind, t.ticket_no, t.coord_no), 'kind', _seller_kind(t));
end $$;

-- Seller cancels their live transfer. Not possible once the buyer has paid the organisers.
create or replace function withdraw_transfer(p_code text, p_ticket text) returns void
language plpgsql security definer set search_path to 'public' as $$
declare v uuid; x ticket_transfers%rowtype;
begin
  v := _seller_ticket(p_code, p_ticket);
  perform 1 from tickets where id = v for update;
  select * into x from ticket_transfers where ticket_id = v and status in ('awaiting_buyer','pending_admin') for update;
  if not found then raise exception 'NO_ACTIVE_TRANSFER'; end if;
  if x.buyer_paid_at is not null then raise exception 'PAYMENT_IN_PROGRESS'; end if;
  update ticket_transfers set status = 'withdrawn' where id = x.id;
end $$;

-- Buyer's side: seller's ticket + transfer code + the five details.
-- If the seller chose a particular buyer, only that phone number is accepted.
create or replace function apply_receive(p_ticket text, p_code text, p_name text, p_phone text,
                                         p_location text, p_attendance text, p_food text) returns jsonb
language plpgsql security definer set search_path to 'public' as $$
declare s settings%rowtype; c text; v uuid; t tickets%rowtype; b bookings%rowtype; x ticket_transfers%rowtype;
        r text; k text; n integer;
begin
  select * into s from settings where id = 1;
  if not s.transfers_open then raise exception 'TRANSFERS_CLOSED'; end if;
  c := _norm_code(p_code);
  select kind, no into k, n from _parse_ticket(p_ticket);
  if length(c) <> 10 or k is null then raise exception 'INVALID_TRANSFER'; end if;
  select ticket_id into v from ticket_transfers where code = c;
  if not found then raise exception 'INVALID_TRANSFER'; end if;
  select * into t from tickets where id = v for update;           -- lock order: ticket first, then the application
  select * into x from ticket_transfers where code = c for update;
  if x.status not in ('awaiting_buyer','pending_admin')
     or not ((k = 'guest' and t.kind = 'guest' and t.ticket_no = n) or (k = 'coordinator' and t.kind = 'coordinator' and t.coord_no = n))
  then raise exception 'INVALID_TRANSFER'; end if;
  select * into b from bookings where id = t.booking_id;
  r := _transfer_block_reason(t, b);
  if r is not null then raise exception '%', r; end if;
  if x.buyer_paid_at is not null then raise exception 'PAYMENT_IN_PROGRESS'; end if;
  if length(trim(coalesce(p_name, ''))) not between 1 and 80 then raise exception 'INVALID_NAME'; end if;
  if coalesce(p_phone, '') !~ '^[0-9]{10}$' then raise exception 'INVALID_PHONE'; end if;
  if x.intended_phone is not null and x.intended_phone <> p_phone then raise exception 'WRONG_BUYER'; end if;
  if coalesce(p_location, '') not in ('In Bengaluru', 'Outside Bengaluru') then raise exception 'INVALID_LOCATION'; end if;
  if coalesce(p_attendance, '') not in ('Surely', 'Most probably') then raise exception 'INVALID_ATTENDANCE'; end if;
  if coalesce(p_food, '') not in ('Veg', 'Non-veg') then raise exception 'INVALID_FOOD'; end if;
  update ticket_transfers set new_name = trim(p_name), new_phone = p_phone, new_location = p_location,
    new_attendance = p_attendance, new_food = p_food, buyer_applied_at = now(), status = 'pending_admin'
  where id = x.id;
  return lookup_transfer(c);
end $$;

-- Public transfers only: after the organisers confirmed the amount with the seller, the buyer pays the
-- organisers and uploads the proof (file name must start with "transfer-" + the transfer code).
-- Works even if transfers were switched off meanwhile (so transfers already in progress can finish).
create or replace function submit_transfer_payment(p_ticket text, p_code text, p_screenshot_path text) returns jsonb
language plpgsql security definer set search_path to 'public' as $$
declare c text; v uuid; t tickets%rowtype; x ticket_transfers%rowtype; k text; n integer;
begin
  c := _norm_code(p_code);
  select kind, no into k, n from _parse_ticket(p_ticket);
  if length(c) <> 10 or k is null then raise exception 'INVALID_TRANSFER'; end if;
  select ticket_id into v from ticket_transfers where code = c;
  if not found then raise exception 'INVALID_TRANSFER'; end if;
  select * into t from tickets where id = v for update;
  select * into x from ticket_transfers where code = c for update;
  if x.status <> 'pending_admin'
     or not ((k = 'guest' and t.kind = 'guest' and t.ticket_no = n) or (k = 'coordinator' and t.kind = 'coordinator' and t.coord_no = n))
  then raise exception 'INVALID_TRANSFER'; end if;
  if x.mode <> 'public' then raise exception 'NOT_PUBLIC'; end if;
  if x.amount_confirmed_at is null then raise exception 'AMOUNT_NOT_CONFIRMED'; end if;
  if x.payment_received_at is not null then raise exception 'PAYMENT_IN_PROGRESS'; end if;
  if p_screenshot_path is null or p_screenshot_path not like 'transfer-' || x.code || '%'
     or not exists (select 1 from storage.objects where bucket_id = 'payment-proofs' and name = p_screenshot_path)
  then raise exception 'SCREENSHOT_MISSING'; end if;
  update ticket_transfers set buyer_screenshot_path = p_screenshot_path, buyer_paid_at = now() where id = x.id;
  return lookup_transfer(c);
end $$;

-- Status page, by transfer code only. After approval it returns the buyer's own new ticket (never the Booking ID).
create or replace function lookup_transfer(p_code text) returns jsonb
language plpgsql security definer set search_path to 'public' as $$
declare c text; x ticket_transfers%rowtype; t tickets%rowtype; b bookings%rowtype; res jsonb;
begin
  c := _norm_code(p_code);
  if length(c) <> 10 then return null; end if;
  select * into x from ticket_transfers where code = c;
  if not found then return null; end if;
  select * into t from tickets where id = x.ticket_id;
  select * into b from bookings where id = t.booking_id;
  res := jsonb_build_object('status', x.status, 'mode', x.mode, 'price', x.price,
    'agreed_amount', x.agreed_amount, 'amount_confirmed', x.amount_confirmed_at is not null,
    'buyer_applied', x.new_name is not null,
    'paid', x.buyer_paid_at is not null, 'payment_received', x.payment_received_at is not null,
    'refund_due', (x.mode = 'public' and x.payment_received_at is not null and x.refunded_at is null
                   and x.status in ('declined', 'withdrawn')),
    'refunded', x.refunded_at is not null, 'decline_reason', x.decline_reason);
  if x.status in ('awaiting_buyer', 'pending_admin') then
    res := res || jsonb_build_object('old_label', _ticket_label(t.kind, t.ticket_no, t.coord_no));
  elsif x.status = 'done' then
    res := res || jsonb_build_object('old_label',
      case when x.from_kind = 'coordinator' then _ticket_label('coordinator', null, x.from_coord_no)
           else _ticket_label('guest', x.from_ticket_no, null) end);
    -- show the ticket only while it is still the one issued by this transfer (never a later holder's)
    if t.ticket_no is not distinct from x.to_ticket_no and t.kind = 'guest' and b.status = 'paid' then
      res := res || jsonb_build_object('ticket', jsonb_build_object('label', _ticket_label(t.kind, t.ticket_no, t.coord_no),
        'secret', t.secret, 'name', t.name, 'location', t.location, 'attendance', t.attendance, 'food', t.food));
    end if;
  end if;
  return res;
end $$;

-- 5. ADMIN FUNCTIONS -----------------------------------------------------------------------------
-- Public transfers: the organisers called the seller and agreed the amount the buyer must pay.
create or replace function admin_confirm_amount(p_id uuid, p_amount integer) returns void
language plpgsql security definer set search_path to 'public' as $$
declare s settings%rowtype; x ticket_transfers%rowtype;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  select * into s from settings where id = 1;
  select * into x from ticket_transfers where id = p_id for update;
  if not found then raise exception 'INVALID_TRANSFER'; end if;
  if x.status not in ('awaiting_buyer', 'pending_admin') then raise exception 'NOT_PENDING'; end if;
  if x.mode <> 'public' then raise exception 'NOT_PUBLIC'; end if;
  if x.buyer_paid_at is not null then raise exception 'PAYMENT_IN_PROGRESS'; end if;
  if p_amount is null or p_amount < 0 or p_amount > s.max_resale_price then raise exception 'INVALID_AMOUNT'; end if;
  update ticket_transfers set agreed_amount = p_amount, amount_confirmed_at = now(), amount_confirmed_by = auth.uid()
  where id = x.id;
end $$;

-- Tick (or untick) "payment received" after checking the bank app.
create or replace function admin_mark_payment_received(p_id uuid, p_received boolean default true) returns void
language plpgsql security definer set search_path to 'public' as $$
declare x ticket_transfers%rowtype;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  select * into x from ticket_transfers where id = p_id for update;
  if not found then raise exception 'INVALID_TRANSFER'; end if;
  if x.status <> 'pending_admin' then raise exception 'NOT_PENDING'; end if;
  if x.mode <> 'public' then raise exception 'NOT_PUBLIC'; end if;
  if x.amount_confirmed_at is null then raise exception 'AMOUNT_NOT_CONFIRMED'; end if;
  if coalesce(p_received, true) then
    update ticket_transfers set payment_received_at = coalesce(payment_received_at, now()),
      buyer_paid_at = coalesce(buyer_paid_at, now()), payment_received_by = auth.uid() where id = x.id;
  else
    -- also forget the "paid" mark if it only came from the admin's tick (the buyer never uploaded proof)
    update ticket_transfers set payment_received_at = null, payment_received_by = null,
      buyer_paid_at = case when buyer_screenshot_path is null then null else buyer_paid_at end
    where id = x.id;
  end if;
end $$;

-- After approval the organisers pay the seller by UPI and record it here.
create or replace function admin_mark_seller_paid(p_id uuid, p_ref text default null) returns void
language plpgsql security definer set search_path to 'public' as $$
declare x ticket_transfers%rowtype;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  select * into x from ticket_transfers where id = p_id for update;
  if not found then raise exception 'INVALID_TRANSFER'; end if;
  if x.status <> 'done' or x.mode <> 'public' then raise exception 'NOT_PUBLIC'; end if;
  update ticket_transfers set seller_paid_at = coalesce(seller_paid_at, now()),
    seller_paid_ref = nullif(left(btrim(coalesce(p_ref, '')), 100), '') where id = x.id;
end $$;

-- After a declined/withdrawn Public transfer where the organisers had received the money: record the refund.
create or replace function admin_mark_refunded(p_id uuid, p_ref text default null) returns void
language plpgsql security definer set search_path to 'public' as $$
declare x ticket_transfers%rowtype;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  select * into x from ticket_transfers where id = p_id for update;
  if not found then raise exception 'INVALID_TRANSFER'; end if;
  if x.mode <> 'public' or x.status not in ('declined', 'withdrawn') or x.payment_received_at is null
  then raise exception 'NOT_PENDING'; end if;
  update ticket_transfers set refunded_at = coalesce(refunded_at, now()),
    refund_ref = nullif(left(btrim(coalesce(p_ref, '')), 100), '') where id = x.id;
end $$;

-- Remove just the comment of an ad (for example if it is rude), keeping the ad.
create or replace function admin_clear_comment(p_id uuid) returns void
language plpgsql security definer set search_path to 'public' as $$
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  update ticket_listings set comment = null where id = p_id;
  if not found then raise exception 'NO_ACTIVE_LISTING'; end if;
end $$;

-- Approve a matched pair: new person, NEXT FREE guest number, new QR. Old numbers are retired for good.
-- A coordinator seat becomes a normal guest seat; a former coordinator loses both their numbers.
create or replace function approve_transfer(p_id uuid, p_payment_confirmed boolean default false) returns jsonb
language plpgsql security definer set search_path to 'public' as $$
declare s settings%rowtype; v uuid; t tickets%rowtype; b bookings%rowtype; x ticket_transfers%rowtype;
        r text; new_no int; k text;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  select * into s from settings where id = 1 for update;          -- same lock order as the gate: settings, ticket, ...
  select ticket_id into v from ticket_transfers where id = p_id;
  if not found then raise exception 'INVALID_TRANSFER'; end if;
  select * into t from tickets where id = v for update;
  select * into x from ticket_transfers where id = p_id for update;
  if x.status <> 'pending_admin' then raise exception 'NOT_PENDING'; end if;
  select * into b from bookings where id = t.booking_id;
  r := _transfer_block_reason(t, b);                                -- checked again now: it may have changed while waiting
  if r is not null then raise exception '%', r; end if;
  if x.mode = 'public' then
    if x.amount_confirmed_at is null then raise exception 'AMOUNT_NOT_CONFIRMED'; end if;
    if x.payment_received_at is null then raise exception 'PAYMENT_NOT_RECEIVED'; end if;
  end if;
  k := _seller_kind(t);
  new_no := s.next_ticket;
  update ticket_transfers set status = 'done',
    from_name = t.name, from_phone = t.phone, from_location = t.location, from_attendance = t.attendance,
    from_food = t.food, from_ticket_no = t.ticket_no, to_ticket_no = new_no,
    from_kind = k,
    from_coord_no = case k when 'coordinator' then t.coord_no when 'former_coordinator' then t.prev_coord_no end,
    payment_confirmed = coalesce(p_payment_confirmed, false) or x.payment_received_at is not null,
    decided_by = auth.uid(), decided_at = now()
  where id = x.id;
  update tickets set ticket_no = new_no, secret = substr(replace(gen_random_uuid()::text, '-', ''), 1, 12),
    kind = 'guest', coord_no = null, orig_secret = null, prev_coord_no = null, prev_coord_secret = null,
    marked_by = null, marked_at = null,
    name = x.new_name, phone = x.new_phone, location = x.new_location,
    attendance = x.new_attendance, food = x.new_food
  where id = t.id;
  update settings set next_ticket = next_ticket + 1 where id = 1;
  update ticket_listings set status = 'closed', closed_at = now() where ticket_id = t.id and status = 'active';
  return jsonb_build_object('id', t.id, 'kind', k, 'mode', x.mode, 'agreed_amount', x.agreed_amount, 'payout', x.payout,
    'old_label', _ticket_label(t.kind, t.ticket_no, t.coord_no),
    'label', _ticket_label('guest', new_no, null), 'name', x.new_name);
end $$;

-- 6. GATE: retired guest numbers AND retired coordinator numbers say TICKET CANCELLED ---------------
CREATE OR REPLACE FUNCTION public.admit_ticket(p_ticket_no integer DEFAULT NULL::integer, p_secret text DEFAULT NULL::text, p_approve boolean DEFAULT false, p_coord boolean DEFAULT false, p_id uuid DEFAULT NULL::uuid)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare t tickets%rowtype; b bookings%rowtype; info jsonb; who text;
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

-- 7. WHO MAY CALL WHAT ---------------------------------------------------------------------------
-- (Supabase hands out run rights to anon/authenticated by default, so they are taken away explicitly here.)
revoke all on function _parse_ticket(text) from public, anon, authenticated;
revoke all on function _seller_kind(tickets) from public, anon, authenticated;
revoke all on function _clean_comment(text) from public, anon, authenticated;
revoke all on function _clean_payout(text) from public, anon, authenticated;
revoke all on function _norm_code(text) from public, anon, authenticated;
revoke all on function _transfer_block_reason(tickets, bookings) from public, anon, authenticated;
revoke all on function _seller_ticket(text, text) from public, anon, authenticated;

revoke all on function list_board() from public, anon, authenticated;
revoke all on function post_listing(text, text, integer, text, text, text, boolean) from public, anon, authenticated;
revoke all on function edit_listing(text, text, integer, text) from public, anon, authenticated;
revoke all on function manage_ticket(text, text) from public, anon, authenticated;
revoke all on function close_listing(text, text, boolean) from public, anon, authenticated;
revoke all on function express_interest(uuid, text, text, text) from public, anon, authenticated;
revoke all on function check_request(uuid, text) from public, anon, authenticated;
revoke all on function start_transfer(text, text, integer, text, text, uuid, boolean) from public, anon, authenticated;
revoke all on function withdraw_transfer(text, text) from public, anon, authenticated;
revoke all on function apply_receive(text, text, text, text, text, text, text) from public, anon, authenticated;
revoke all on function submit_transfer_payment(text, text, text) from public, anon, authenticated;
revoke all on function lookup_transfer(text) from public, anon, authenticated;
revoke all on function admin_confirm_amount(uuid, integer) from public, anon, authenticated;
revoke all on function admin_mark_payment_received(uuid, boolean) from public, anon, authenticated;
revoke all on function admin_mark_seller_paid(uuid, text) from public, anon, authenticated;
revoke all on function admin_mark_refunded(uuid, text) from public, anon, authenticated;
revoke all on function admin_clear_comment(uuid) from public, anon, authenticated;
revoke all on function approve_transfer(uuid, boolean) from public, anon, authenticated;
revoke all on function admit_ticket(integer, text, boolean, boolean, uuid) from public, anon, authenticated;
-- the part 1 helpers and admin functions that were not touched here: close the same gap
revoke all on function get_transfer_status() from public, anon, authenticated;
revoke all on function decline_transfer(uuid, text) from public, anon, authenticated;
revoke all on function admin_remove_listing(uuid) from public, anon, authenticated;
revoke all on function admin_set_transfer_settings(boolean, integer) from public, anon, authenticated;

-- website visitors (no login)
grant execute on function get_transfer_status() to anon, authenticated;
grant execute on function list_board() to anon, authenticated;
grant execute on function post_listing(text, text, integer, text, text, text, boolean) to anon, authenticated;
grant execute on function edit_listing(text, text, integer, text) to anon, authenticated;
grant execute on function manage_ticket(text, text) to anon, authenticated;
grant execute on function close_listing(text, text, boolean) to anon, authenticated;
grant execute on function express_interest(uuid, text, text, text) to anon, authenticated;
grant execute on function check_request(uuid, text) to anon, authenticated;
grant execute on function start_transfer(text, text, integer, text, text, uuid, boolean) to anon, authenticated;
grant execute on function withdraw_transfer(text, text) to anon, authenticated;
grant execute on function apply_receive(text, text, text, text, text, text, text) to anon, authenticated;
grant execute on function submit_transfer_payment(text, text, text) to anon, authenticated;
grant execute on function lookup_transfer(text) to anon, authenticated;
-- signed-in staff only (admins are checked again inside each function)
grant execute on function admin_set_transfer_settings(boolean, integer) to authenticated;
grant execute on function admin_confirm_amount(uuid, integer) to authenticated;
grant execute on function admin_mark_payment_received(uuid, boolean) to authenticated;
grant execute on function admin_mark_seller_paid(uuid, text) to authenticated;
grant execute on function admin_mark_refunded(uuid, text) to authenticated;
grant execute on function admin_clear_comment(uuid) to authenticated;
grant execute on function approve_transfer(uuid, boolean) to authenticated;
grant execute on function decline_transfer(uuid, text) to authenticated;
grant execute on function admin_remove_listing(uuid) to authenticated;
grant execute on function admit_ticket(integer, text, boolean, boolean, uuid) to authenticated;
