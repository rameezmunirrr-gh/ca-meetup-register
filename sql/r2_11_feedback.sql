-- ============================================================================
-- Release 2, piece 11: optional "excitement rating + suggestions" on the Booking ID page, with an admin on/off switch
-- Written 26 Oct 2026. Run AFTER r2_10. Tested on the scratch database before use. Safe to run twice. Changes no existing data.
-- ask_feedback = true : the "This is your Booking ID" page shows the two optional questions.
-- ask_feedback = false: they are hidden and the database refuses new answers (FEEDBACK_OFF). Saved answers are kept.
-- Answers are readable only by admins. One answer per booking; sending again replaces the earlier one.
-- ============================================================================
alter table public.settings add column if not exists ask_feedback boolean not null default true;

create table if not exists public.booking_feedback (
  booking_id uuid primary key references public.bookings(id) on delete cascade,
  rating     smallint check (rating between 1 and 5),
  comment    text check (char_length(comment) between 1 and 1000),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  check (rating is not null or comment is not null)
);
alter table public.booking_feedback enable row level security;
drop policy if exists admin_read_booking_feedback on public.booking_feedback;
create policy admin_read_booking_feedback on public.booking_feedback for select to authenticated using (is_admin());
revoke all on public.booking_feedback from public, anon, authenticated;
grant select on public.booking_feedback to authenticated;

create or replace function public.get_site_flags() returns jsonb
 language sql stable security definer set search_path to 'public' as $function$
  select jsonb_build_object('show_about', s.show_about, 'ask_email', s.ask_email, 'ask_feedback', s.ask_feedback) from settings s where s.id = 1
$function$;
revoke all on function public.get_site_flags() from public, anon, authenticated, service_role;
grant execute on function public.get_site_flags() to anon, authenticated;

create or replace function public.admin_set_ask_feedback(p_ask boolean) returns void
 language plpgsql security definer set search_path to 'public' as $function$
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  if p_ask is null then raise exception 'INVALID_VALUE'; end if;
  update settings set ask_feedback = p_ask where id = 1;
end $function$;
revoke all on function public.admin_set_ask_feedback(boolean) from public, anon, authenticated, service_role;
grant execute on function public.admin_set_ask_feedback(boolean) to authenticated;

-- visitor: save the answers for the booking whose ID they hold (a registration booking only)
create or replace function public.submit_feedback(p_booking_code text, p_rating integer, p_comment text) returns jsonb
 language plpgsql security definer set search_path to 'public' as $function$
declare s settings; bid uuid; c text := nullif(trim(coalesce(p_comment, '')), '');
begin
  select * into s from settings where id = 1;
  if not s.ask_feedback then return jsonb_build_object('ok', false, 'error', 'FEEDBACK_OFF'); end if;
  if p_rating is not null and p_rating not between 1 and 5 then return jsonb_build_object('ok', false, 'error', 'INVALID_RATING'); end if;
  if c is not null and char_length(c) > 1000 then return jsonb_build_object('ok', false, 'error', 'INVALID_COMMENT'); end if;
  if p_rating is null and c is null then return jsonb_build_object('ok', false, 'error', 'EMPTY_FEEDBACK'); end if;
  select id into bid from bookings where booking_code = upper(trim(coalesce(p_booking_code, ''))) and kind = 'registration';
  if bid is null then return jsonb_build_object('ok', false, 'error', 'BOOKING_NOT_FOUND'); end if;
  insert into booking_feedback (booking_id, rating, comment) values (bid, p_rating, c)
    on conflict (booking_id) do update set rating = excluded.rating, comment = excluded.comment, updated_at = now();
  return jsonb_build_object('ok', true);
end $function$;
revoke all on function public.submit_feedback(text, integer, text) from public, anon, authenticated, service_role;
grant execute on function public.submit_feedback(text, integer, text) to anon, authenticated;
