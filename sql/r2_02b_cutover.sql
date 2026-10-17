-- ============================================================================
-- Release 2, Step 1, piece 2b: CUT-OVER. Apply ONLY together with the new Tickets page.
-- Removes the old lookup that showed tickets (and QR secrets) for a Booking ID alone.
-- After this, the old Tickets page stops working until the new page is live.
-- ============================================================================
drop function if exists public.lookup_booking(text);
