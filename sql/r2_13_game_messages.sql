-- ============================================================================
-- Release 2, piece 13: "Messages" for the game activity (a message on a ticket, shown only while an admin switch is ON)
-- Written 30 Oct 2026. Run AFTER r2_12. Tested on the scratch database before use. Safe to run twice. Changes no existing data.
--
--   game_messages  : the messages an admin writes (a short NAME for the admin, the BODY the ticket holder sees, up to 200 characters).
--   ticket_messages: which ticket has which message (at most one per ticket). Many tickets can share one message (a "team").
--   settings.show_messages: the switch. OFF (the default): the database sends NO message to anyone. ON: a ticket holder who
--                    enters the right Booking ID + phone gets their message with their ticket (paid bookings, tickets not transferred away).
--   Both tables are readable and changeable by ADMINS ONLY. Gate staff, visitors and signed-in non-staff see nothing.
--   A ticket created by a transfer inherits the message of the ticket it came from.
--   Every change by an admin is written to the Settings log (area "messages").
-- ============================================================================
alter table public.settings add column if not exists show_messages boolean not null default false;

alter table public.settings_log drop constraint if exists settings_log_area_check;
alter table public.settings_log add constraint settings_log_area_check check (area = any (array['settings','staff','transfer','messages']));

create table if not exists public.game_messages (
  id         uuid primary key default gen_random_uuid(),
  name       text not null check (char_length(name) between 1 and 60),
  body       text not null check (char_length(body) between 1 and 200),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create unique index if not exists game_messages_name_uq on public.game_messages (lower(name));

create table if not exists public.ticket_messages (
  ticket_id   uuid primary key references public.tickets(id) on delete cascade,
  message_id  uuid not null references public.game_messages(id) on delete cascade,
  assigned_at timestamptz not null default now()
);
create index if not exists ticket_messages_message_idx on public.ticket_messages (message_id);

alter table public.game_messages enable row level security;
alter table public.ticket_messages enable row level security;
drop policy if exists admin_read_game_messages on public.game_messages;
create policy admin_read_game_messages on public.game_messages for select to authenticated using (is_admin());
drop policy if exists admin_read_ticket_messages on public.ticket_messages;
create policy admin_read_ticket_messages on public.ticket_messages for select to authenticated using (is_admin());
revoke all on public.game_messages, public.ticket_messages from public, anon, authenticated;
grant select on public.game_messages, public.ticket_messages to authenticated;

-- the switch (the Settings log records the change by itself, like the other switches)
create or replace function public.admin_set_show_messages(p_show boolean) returns void
 language plpgsql security definer set search_path to 'public' as $function$
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  if p_show is null then raise exception 'INVALID_VALUE'; end if;
  update settings set show_messages = p_show where id = 1;
end $function$;
revoke all on function public.admin_set_show_messages(boolean) from public, anon, authenticated, service_role;
grant execute on function public.admin_set_show_messages(boolean) to authenticated;

create or replace function public._mlog(p_field text, p_old text, p_new text) returns void
 language sql security definer set search_path to 'public' as $function$
  insert into settings_log (changed_by, who, area, field, old_value, new_value)
  values (auth.uid(), _actor(), 'messages', p_field, left(p_old, 300), left(p_new, 300)) $function$;
revoke all on function public._mlog(text, text, text) from public, anon, authenticated, service_role;

-- create (p_id null) or edit a message. Returns its id.
create or replace function public.admin_save_message(p_id uuid, p_name text, p_body text) returns uuid
 language plpgsql security definer set search_path to 'public' as $function$
declare n text := trim(coalesce(p_name, '')); b text := trim(coalesce(p_body, '')); o game_messages; nid uuid;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  if char_length(n) not between 1 and 60 or n ~ '[[:cntrl:]]' then raise exception 'INVALID_NAME'; end if;
  if char_length(b) not between 1 and 200 or b ~ '[[:cntrl:]]' then raise exception 'INVALID_MESSAGE'; end if;
  if p_id is null then
    if exists (select 1 from game_messages where lower(name) = lower(n)) then raise exception 'NAME_TAKEN'; end if;
    insert into game_messages (name, body) values (n, b) returning id into nid;
    perform _mlog('message added', null, n || ': ' || b);
    return nid;
  end if;
  select * into o from game_messages where id = p_id for update;
  if not found then raise exception 'NOT_FOUND'; end if;
  if exists (select 1 from game_messages where lower(name) = lower(n) and id <> p_id) then raise exception 'NAME_TAKEN'; end if;
  update game_messages set name = n, body = b, updated_at = now() where id = p_id;
  if o.name is distinct from n or o.body is distinct from b then
    perform _mlog('message edited', o.name || ': ' || o.body, n || ': ' || b);
  end if;
  return p_id;
end $function$;
revoke all on function public.admin_save_message(uuid, text, text) from public, anon, authenticated, service_role;
grant execute on function public.admin_save_message(uuid, text, text) to authenticated;

-- delete a message (everyone holding it loses it). Returns how many tickets lost it.
create or replace function public.admin_delete_message(p_id uuid) returns integer
 language plpgsql security definer set search_path to 'public' as $function$
declare o game_messages; n int;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  select * into o from game_messages where id = p_id for update;
  if not found then raise exception 'NOT_FOUND'; end if;
  select count(*) into n from ticket_messages where message_id = p_id;
  delete from game_messages where id = p_id;
  perform _mlog('message deleted', o.name || ': ' || o.body, n || ' ticket(s) lost it');
  return n;
end $function$;
revoke all on function public.admin_delete_message(uuid) from public, anon, authenticated, service_role;
grant execute on function public.admin_delete_message(uuid) to authenticated;

-- give messages: p_pairs = [{"t": "<ticket id>", "m": "<message id>"}, ...]. All or nothing. Replaces a ticket's earlier message.
-- Tickets that were transferred away are refused. The same ticket twice in one list is refused. Returns how many tickets were set.
create or replace function public.admin_assign_messages(p_pairs jsonb) returns integer
 language plpgsql security definer set search_path to 'public' as $function$
declare n int; cnt int; summ text; ids_t uuid[]; ids_m uuid[];
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  if p_pairs is null or jsonb_typeof(p_pairs) <> 'array' then raise exception 'INVALID_PAIRS'; end if;
  cnt := jsonb_array_length(p_pairs);
  if cnt = 0 then return 0; end if;
  if cnt > 1000 then raise exception 'TOO_MANY'; end if;
  begin
    select array_agg((e->>'t')::uuid), array_agg((e->>'m')::uuid) into ids_t, ids_m from jsonb_array_elements(p_pairs) e;
  exception when others then raise exception 'INVALID_PAIRS';
  end;
  if array_position(ids_t, null) is not null or array_position(ids_m, null) is not null then raise exception 'INVALID_PAIRS'; end if;
  if (select count(distinct x) from unnest(ids_t) x) <> cnt then raise exception 'DUPLICATE_TICKET'; end if;
  if (select count(*) from tickets where id = any (ids_t) and transferred_out_at is null) <> cnt then raise exception 'TICKET_NOT_FOUND'; end if;
  if (select count(*) from game_messages where id = any (ids_m)) <> (select count(distinct x) from unnest(ids_m) x) then raise exception 'MESSAGE_NOT_FOUND'; end if;
  insert into ticket_messages (ticket_id, message_id)
    select t, m from unnest(ids_t, ids_m) as u(t, m)
    on conflict (ticket_id) do update set message_id = excluded.message_id, assigned_at = now();
  get diagnostics n = row_count;
  select string_agg(g.name || ' x' || c.k, ', ' order by g.name) into summ
    from (select m, count(*) k from unnest(ids_m) m group by m) c join game_messages g on g.id = c.m;
  perform _mlog('messages given', null, n || ' ticket(s): ' || summ);
  return n;
end $function$;
revoke all on function public.admin_assign_messages(jsonb) from public, anon, authenticated, service_role;
grant execute on function public.admin_assign_messages(jsonb) to authenticated;

-- take messages away. No arguments = from everyone. p_message = only that message's holders. p_tickets = only those tickets. Both = both rules.
create or replace function public.admin_clear_messages(p_message uuid default null, p_tickets uuid[] default null) returns integer
 language plpgsql security definer set search_path to 'public' as $function$
declare n int; nm text;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  if p_message is not null then
    select name into nm from game_messages where id = p_message;
    if not found then raise exception 'NOT_FOUND'; end if;
  end if;
  delete from ticket_messages
   where (p_message is null or message_id = p_message)
     and (p_tickets is null or ticket_id = any (p_tickets));
  get diagnostics n = row_count;
  perform _mlog('messages cleared', null, n || ' ticket(s)' || case when nm is not null then ' of ' || nm else '' end
                || case when p_tickets is not null then ' (chosen tickets)' else '' end);
  return n;
end $function$;
revoke all on function public.admin_clear_messages(uuid, uuid[]) from public, anon, authenticated, service_role;
grant execute on function public.admin_clear_messages(uuid, uuid[]) to authenticated;

-- a ticket made by a transfer keeps the message of the ticket it came from
create or replace function public._inherit_ticket_message() returns trigger
 language plpgsql security definer set search_path to 'public' as $function$
begin
  if new.transferred_from is not null then
    insert into ticket_messages (ticket_id, message_id)
      select new.id, message_id from ticket_messages where ticket_id = new.transferred_from
      on conflict (ticket_id) do nothing;
  end if;
  return null;
end $function$;
revoke all on function public._inherit_ticket_message() from public, anon, authenticated, service_role;
drop trigger if exists tickets_inherit_message_trg on public.tickets;
create trigger tickets_inherit_message_trg after insert on public.tickets for each row execute function public._inherit_ticket_message();

-- the ticket lookup (Booking ID + phone). Same as before, plus "game_message": filled ONLY while the switch is ON,
-- only for a paid booking, and only for a ticket that was not transferred away. Otherwise null.
create or replace FUNCTION public.lookup_tickets(p_code text, p_phone text)
 RETURNS jsonb
 LANGUAGE plpgsql
 STABLE SECURITY DEFINER
 SET search_path TO 'public'
AS $function$
declare b bookings%rowtype; c text; ph text; tk jsonb; bu transfer_buyers%rowtype; x transfers%rowtype; st text; gm_on boolean;
begin
  c  := replace(replace(replace(upper(coalesce(p_code, '')), 'O', '0'), ' ', ''), '-', '');
  ph := replace(replace(coalesce(p_phone, ''), ' ', ''), '-', '');
  if length(c) <> 8 or ph !~ '^[0-9]{10}$' then return jsonb_build_object('found', false); end if;
  select show_messages into gm_on from settings where id = 1;
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
           'game_message', case when gm_on and b.status = 'paid' and t.transferred_out_at is null
                                then (select m.body from ticket_messages tm join game_messages m on m.id = tm.message_id where tm.ticket_id = t.id) else null end,
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
revoke all on function public.lookup_tickets(text, text) from public, anon, authenticated, service_role;
grant execute on function public.lookup_tickets(text, text) to anon, authenticated;
