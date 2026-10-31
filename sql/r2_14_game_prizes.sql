-- ============================================================================
-- Release 2, piece 14: "Random picks" (a line on a ticket given to randomly picked people, separate from the team message), shown under the same admin switch
-- Written 30 Oct 2026. Run AFTER r2_13. Tested on the scratch database before use. Safe to run twice. Changes no existing data.
--
--   ticket_prizes: at most one such line per ticket (up to 200 characters) with its own heading (up to 60 characters, default "You are a winner!"),
--   so it can be a prize, a clue, a task or anything else. Readable and changeable by ADMINS ONLY. (The table keeps its first name "ticket_prizes".)
--   It is separate from ticket_messages (the team message): a ticket can have a team message, a prize, both, or neither.
--   The same switch settings.show_messages decides whether anyone sees them: OFF = the database sends neither; ON = a ticket holder
--   who enters the right Booking ID + phone gets "game_message", and "game_prize" with "game_prize_heading" (paid booking, ticket not transferred away).
--   Who wins is drawn in the admin page with the browser's secure random generator (shown as a preview first); the database only stores the result.
--   A ticket made by a transfer inherits the prize as well as the team message. Changes are written to the Settings log (area "messages").
-- ============================================================================
create table if not exists public.ticket_prizes (
  ticket_id  uuid primary key references public.tickets(id) on delete cascade,
  body       text not null check (char_length(body) between 1 and 200),
  heading    text not null default 'You are a winner!' check (char_length(heading) between 1 and 60),
  created_at timestamptz not null default now()
);
alter table public.ticket_prizes enable row level security;
drop policy if exists admin_read_ticket_prizes on public.ticket_prizes;
create policy admin_read_ticket_prizes on public.ticket_prizes for select to authenticated using (is_admin());
revoke all on public.ticket_prizes from public, anon, authenticated;
grant select on public.ticket_prizes to authenticated;

-- give one line (with a heading) to a list of tickets (the picked people). All or nothing. Replaces an earlier line on those tickets. Returns how many.
-- A blank or missing heading means the default "You are a winner!".
create or replace function public.admin_set_prizes(p_tickets uuid[], p_body text, p_heading text default null) returns integer
 language plpgsql security definer set search_path to 'public' as $function$
declare b text := trim(coalesce(p_body, '')); h text := coalesce(nullif(trim(coalesce(p_heading, '')), ''), 'You are a winner!'); cnt int; n int;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  if char_length(b) not between 1 and 200 or b ~ '[[:cntrl:]]' then raise exception 'INVALID_MESSAGE'; end if;
  if char_length(h) > 60 or h ~ '[[:cntrl:]]' then raise exception 'INVALID_NAME'; end if;
  if p_tickets is null then raise exception 'INVALID_PAIRS'; end if;
  cnt := coalesce(cardinality(p_tickets), 0);
  if cnt = 0 then return 0; end if;
  if cnt > 1000 then raise exception 'TOO_MANY'; end if;
  if array_position(p_tickets, null) is not null then raise exception 'INVALID_PAIRS'; end if;
  if (select count(distinct x) from unnest(p_tickets) x) <> cnt then raise exception 'DUPLICATE_TICKET'; end if;
  if (select count(*) from tickets where id = any (p_tickets) and transferred_out_at is null) <> cnt then raise exception 'TICKET_NOT_FOUND'; end if;
  insert into ticket_prizes (ticket_id, body, heading) select x, b, h from unnest(p_tickets) x
    on conflict (ticket_id) do update set body = excluded.body, heading = excluded.heading, created_at = now();
  get diagnostics n = row_count;
  perform _mlog('prizes given', null, n || ' ticket(s): ' || h || ' / ' || b);
  return n;
end $function$;
revoke all on function public.admin_set_prizes(uuid[], text, text) from public, anon, authenticated, service_role;
grant execute on function public.admin_set_prizes(uuid[], text, text) to authenticated;

-- take prizes away. No argument = from everyone; a list = only those tickets. Returns how many.
create or replace function public.admin_clear_prizes(p_tickets uuid[] default null) returns integer
 language plpgsql security definer set search_path to 'public' as $function$
declare n int;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  delete from ticket_prizes where p_tickets is null or ticket_id = any (p_tickets);
  get diagnostics n = row_count;
  perform _mlog('prizes cleared', null, n || ' ticket(s)' || case when p_tickets is not null then ' (chosen tickets)' else '' end);
  return n;
end $function$;
revoke all on function public.admin_clear_prizes(uuid[]) from public, anon, authenticated, service_role;
grant execute on function public.admin_clear_prizes(uuid[]) to authenticated;

-- a ticket made by a transfer keeps the team message AND the picked-people line (with its heading) of the ticket it came from
create or replace function public._inherit_ticket_message() returns trigger
 language plpgsql security definer set search_path to 'public' as $function$
begin
  if new.transferred_from is not null then
    insert into ticket_messages (ticket_id, message_id)
      select new.id, message_id from ticket_messages where ticket_id = new.transferred_from
      on conflict (ticket_id) do nothing;
    insert into ticket_prizes (ticket_id, body, heading)
      select new.id, body, heading from ticket_prizes where ticket_id = new.transferred_from
      on conflict (ticket_id) do nothing;
  end if;
  return null;
end $function$;
revoke all on function public._inherit_ticket_message() from public, anon, authenticated, service_role;

-- the ticket lookup: as in r2_13, plus "game_prize" and "game_prize_heading" (same rules as "game_message": switch ON, paid booking, ticket not transferred away; otherwise null)
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
           'game_prize', case when gm_on and b.status = 'paid' and t.transferred_out_at is null
                              then (select z.body from ticket_prizes z where z.ticket_id = t.id) else null end,
           'game_prize_heading', case when gm_on and b.status = 'paid' and t.transferred_out_at is null
                              then (select z.heading from ticket_prizes z where z.ticket_id = t.id) else null end,
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
