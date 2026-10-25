-- ============================================================================
-- Release 2, piece 9: the "About" link on the home page, with an admin on/off switch
-- Written 26 Oct 2026. Tested on the scratch database before use. Safe to run twice. Changes no data.
-- show_about = true : the home page shows an About link; for now it opens an "Under construction" page.
-- show_about = false: the link is hidden. Only admins can change it; every change is logged automatically.
-- ============================================================================
alter table public.settings add column if not exists show_about boolean not null default true;

-- visitors: which optional parts of the site are switched on (nothing secret)
create or replace function public.get_site_flags() returns jsonb
 language sql stable security definer set search_path to 'public' as $function$
  select jsonb_build_object('show_about', s.show_about) from settings s where s.id = 1
$function$;

-- admin: switch the About link on or off
create or replace function public.admin_set_show_about(p_show boolean) returns void
 language plpgsql security definer set search_path to 'public' as $function$
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  if p_show is null then raise exception 'INVALID_VALUE'; end if;
  update settings set show_about = p_show where id = 1;
end $function$;

revoke all on function public.get_site_flags() from public, anon, authenticated, service_role;
grant execute on function public.get_site_flags() to anon, authenticated;
revoke all on function public.admin_set_show_about(boolean) from public, anon, authenticated, service_role;
grant execute on function public.admin_set_show_about(boolean) to authenticated;
