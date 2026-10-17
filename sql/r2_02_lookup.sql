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
