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
