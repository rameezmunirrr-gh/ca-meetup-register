-- CLEAN-UP AFTER THE REHEARSAL (written 25 Oct 2026).
-- Deletes ALL bookings, tickets, emails, transfers, address records, screenshot scans and visitor sessions,
-- and restarts ticket numbering at 1. It KEEPS: staff, settings (price, UPI ID, payee, WhatsApp, deadline, venue...),
-- the settings log, and the database structure. It also switches transfers OFF.
-- Safety: it refuses to run while registration is OPEN (so real bookings cannot be wiped by accident).
do $$
begin
  if (select is_open from settings where id = 1) then
    raise exception 'REGISTRATION_IS_OPEN: close registration first, then run this again';
  end if;
end $$;

truncate table transfer_buyers, transfers, ticket_emails, booking_ips, screenshot_scans, tickets, bookings, reg_sessions
  restart identity cascade;

update settings set next_ticket = 1, next_coord = 1, transfers_open = false where id = 1;
