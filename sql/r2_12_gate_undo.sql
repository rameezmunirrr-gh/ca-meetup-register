-- Gate undo: lets ANY signed-in organiser (gate or admin) take back an admission, but only for 30 minutes.
-- Why: the old undo_checkin works for admins only. A gate volunteer who admits the wrong person needs to fix it on the spot.
-- Safe to run more than once. Run it in the Supabase SQL editor. The Gate page uses this if it exists, and falls back to undo_checkin if not.
create or replace function public.gate_undo_checkin(p_id uuid) returns void
language plpgsql security definer set search_path to 'public' as $function$
declare n int;
begin
  if not is_staff() then raise exception 'NOT_ALLOWED'; end if;
  update tickets set checked_in_at = null, checked_in_by = null
   where id = p_id and checked_in_at is not null and checked_in_at > now() - interval '30 minutes';
  get diagnostics n = row_count;
  if n = 0 then raise exception 'UNDO_EXPIRED'; end if;
end $function$;

revoke execute on function public.gate_undo_checkin(uuid) from public, anon;
grant execute on function public.gate_undo_checkin(uuid) to authenticated;
