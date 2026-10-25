-- ============================================================================
-- Release 2, Step 1, piece 6: transfer settings (admin) and transfer info (visitors)
-- Written 24 Oct 2026. Tested on the scratch database before use.
-- REQUIRES r2_01 to r2_05 (run it AFTER r2_05: that file drops every function named
-- admin_set_transfer_settings, including this one if it already existed).
-- Changes no data. Transfers stay OFF until an admin switches them on here.
-- ============================================================================

-- 1. Admin: change the transfer settings (the only way to do it from the app)
--    p_open          true/false      turn transfers on or off
--    p_cutoff        timestamp       no NEW codes, buyer forms or payment uploads after this moment
--    p_clear_cutoff  true            remove the cut-off again (cannot be combined with p_cutoff)
--    p_food_locked   true/false      the buyer gets the seller's food (use after the food order is placed)
--    p_code_hours    1 to 168        how long a new code stays valid
--    p_ip_threshold  2 to 1000       how many registrations from one address raise a flag
--    A null parameter means "keep as it is". Every change is written to the settings log automatically.
create or replace function public.admin_set_transfer_settings(
  p_open boolean default null,
  p_cutoff timestamptz default null,
  p_clear_cutoff boolean default false,
  p_food_locked boolean default null,
  p_code_hours integer default null,
  p_ip_threshold integer default null) returns void
 language plpgsql security definer set search_path to 'public' as $function$
declare s settings%rowtype;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  if p_code_hours is not null and p_code_hours not between 1 and 168 then raise exception 'INVALID_HOURS'; end if;
  if p_ip_threshold is not null and p_ip_threshold not between 2 and 1000 then raise exception 'INVALID_THRESHOLD'; end if;
  if p_cutoff is not null and coalesce(p_clear_cutoff, false) then raise exception 'INVALID_CUTOFF'; end if;
  select * into s from settings where id = 1 for update;
  -- do not open a feature that would show buyers an empty Pay screen or a dead Contact button
  if p_open is true and (s.upi_id is null or s.payee_name is null or s.whatsapp_number is null) then
    raise exception 'PAYMENT_INFO_MISSING';
  end if;
  update settings set
    transfers_open       = coalesce(p_open, transfers_open),
    transfer_cutoff_at   = case when coalesce(p_clear_cutoff, false) then null else coalesce(p_cutoff, transfer_cutoff_at) end,
    transfer_food_locked = coalesce(p_food_locked, transfer_food_locked),
    private_code_hours   = coalesce(p_code_hours, private_code_hours),
    ip_flag_threshold    = coalesce(p_ip_threshold, ip_flag_threshold)
  where id = 1;
end $function$;

-- 2. Visitors: is the transfer feature available right now, and with which rules?
--    Nothing secret: no phone numbers, no UPI ID, no counts.
--    The page shows the Transfer menu only when open is true and cutoff_passed is false.
create or replace function public.get_transfer_info() returns jsonb
 language sql stable security definer set search_path to 'public' as $function$
  select jsonb_build_object(
    'open',          s.transfers_open,
    'cutoff_at',     s.transfer_cutoff_at,
    'cutoff_passed', (s.transfer_cutoff_at is not null and now() > s.transfer_cutoff_at),
    'food_locked',   s.transfer_food_locked,
    'code_hours',    s.private_code_hours,
    'ask_price',     s.price_per_head,
    'server_now',    now())
  from settings s where s.id = 1
$function$;

-- 3. Who may call them
revoke all on function public.admin_set_transfer_settings(boolean, timestamptz, boolean, boolean, integer, integer)
  from public, anon, authenticated, service_role;
grant execute on function public.admin_set_transfer_settings(boolean, timestamptz, boolean, boolean, integer, integer) to authenticated;
revoke all on function public.get_transfer_info() from public, anon, authenticated, service_role;
grant execute on function public.get_transfer_info() to anon, authenticated;
