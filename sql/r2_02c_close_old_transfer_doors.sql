-- ============================================================================
-- Release 2, Step 1, piece 2c: close public access to the OLD transfer functions
-- Written 17 Oct 2026. Safe to apply at any time: no page calls these functions
-- (checked in index.html, admin/index.html and gate/index.html), and transfers
-- are switched off. The functions themselves are dropped in a later piece.
-- Admin-only functions (approve_transfer, admin_* ...) are NOT touched.
-- ============================================================================
do $$
declare r record;
begin
  for r in
    select p.oid::regprocedure as sig
      from pg_proc p join pg_namespace n on n.oid = p.pronamespace
     where n.nspname = 'public'
       and p.proname = any (array[
             'apply_receive','check_request','close_listing','edit_listing','express_interest',
             'get_transfer_status','list_board','lookup_transfer','manage_ticket','post_listing',
             'start_transfer','submit_transfer_payment','withdraw_transfer'])
  loop
    execute 'revoke all on function ' || r.sig || ' from public, anon, authenticated';
  end loop;
end $$;
