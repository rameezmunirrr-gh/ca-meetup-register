import re
src = open('/home/claude/scratch/r2_01_prep.sql', encoding='utf-8').read()
start = src.index('CREATE OR REPLACE FUNCTION public.submit_booking(')
first = src.index('$function$', start); end = src.index('$function$', first + 10) + len('$function$')
sb = src[start:end]
old = "  insert into bookings (booking_code, submission_id, people_count, amount_expected, screenshot_path)\n  values (code, p_submission_id, n, n * s.price_per_head, p_screenshot_path) returning * into b;\n"
assert sb.count(old) == 1
sb = sb.replace(old, old + "  insert into booking_ips (booking_id, ip, raw) values (b.id, _client_ip(), _client_ip_raw());   -- flag only, never blocks\n")

OLD_FUNCS = ['apply_receive','check_request','close_listing','edit_listing','express_interest','get_transfer_status','list_board','lookup_transfer',
 'manage_ticket','post_listing','start_transfer','submit_transfer_payment','withdraw_transfer','approve_transfer','decline_transfer','admin_confirm_amount',
 'admin_mark_payment_received','admin_mark_seller_paid','admin_mark_refunded','admin_remove_listing','admin_clear_comment','admin_set_transfer_settings',
 '_seller_ticket','_transfer_block_reason','_clean_comment','_clean_payout','_seller_kind','_norm_code']
names = ",\n             ".join("'%s'" % n for n in OLD_FUNCS)

SQL = f"""-- ============================================================================
-- Release 2, Step 1, piece 5: CLEAN-UP of the old transfer backend + the IP FLAG
-- Written 17 Oct 2026. Tested on the scratch database before use.
-- REQUIRES r2_01 to r2_04. Run when the new pages are live (nothing calls the old backend; checked).
-- 1. Drops the OLD transfer functions and tables (ticket_listings, ticket_interests, ticket_transfers).
-- 2. Records the visitor's IP on every registration, ADMIN-ONLY, FLAG ONLY (never blocks anyone).
-- ============================================================================

-- 1. The old transfer backend (replaced by the code flow in r2_03 / r2_04)
do $$
declare r record;
begin
  for r in
    select p.oid::regprocedure as sig
      from pg_proc p join pg_namespace n on n.oid = p.pronamespace
     where n.nspname = 'public'
       and p.proname = any (array[
             {names}])
  loop
    execute 'drop function ' || r.sig;
  end loop;
end $$;
drop table if exists public.ticket_transfers, public.ticket_interests, public.ticket_listings;   -- one statement: they reference each other

-- 2. IP flag. Kept in its own admin-only table so a gate login can never read it from the bookings table.
alter table public.settings add column if not exists ip_flag_threshold integer not null default 5;
alter table public.settings drop constraint if exists settings_ip_flag_check;
alter table public.settings add constraint settings_ip_flag_check check (ip_flag_threshold between 2 and 1000);

create table if not exists public.booking_ips (
  booking_id uuid primary key references public.bookings(id) on delete cascade,
  ip text,
  raw text,
  created_at timestamptz not null default now()
);
create index if not exists booking_ips_ip_idx on public.booking_ips (ip);
alter table public.booking_ips enable row level security;
drop policy if exists admin_read_booking_ips on public.booking_ips;
create policy admin_read_booking_ips on public.booking_ips for select to authenticated using (is_admin());
revoke all on table public.booking_ips from public, anon, authenticated, service_role;
grant select on table public.booking_ips to authenticated;

-- the request headers (empty when called from the SQL editor)
create or replace function public._request_headers() returns jsonb
 language plpgsql stable as $function$
declare h text;
begin
  h := current_setting('request.headers', true);
  if h is null or h = '' then return '{{}}'::jsonb; end if;
  begin return h::jsonb; exception when others then return '{{}}'::jsonb; end;
end $function$;

create or replace function public._clean_ip(p text) returns text language sql immutable as $$
  select case when btrim(coalesce(p, '')) ~ '^[0-9a-fA-F:.]{{2,45}}$' then btrim(p) end $$;

create or replace function public._header(p_name text) returns text language sql stable as $$
  select value from jsonb_each_text(_request_headers()) where lower(key) = lower(p_name) limit 1 $$;

-- Cloudflare's header when present (a visitor cannot fake it); otherwise the LAST address in x-forwarded-for
-- (the one added by the nearest proxy). Which header is trustworthy on the real project must be checked
-- from the stored raw values (see the notes); this only ever FLAGS.
create or replace function public._client_ip() returns text
 language plpgsql stable as $function$
declare ip text; xff text; parts text[];
begin
  ip := _clean_ip(_header('cf-connecting-ip'));
  if ip is not null then return ip; end if;
  xff := _header('x-forwarded-for');
  if xff is not null then
    parts := string_to_array(replace(xff, ' ', ''), ',');
    ip := _clean_ip(parts[array_length(parts, 1)]);
  end if;
  return ip;
end $function$;

create or replace function public._client_ip_raw() returns text language sql stable as $$
  select nullif(left(regexp_replace('cf=' || coalesce(_header('cf-connecting-ip'), '') || ' xff=' || coalesce(_header('x-forwarded-for'), ''), '[^\\x20-\\x7E]', '', 'g'), 300), 'cf= xff=') $$;

-- registration now records the IP (flag only)
{sb};

-- admin: addresses with many registrations (the threshold is a setting, default 5)
create or replace function public.admin_ip_flags() returns jsonb
 language plpgsql stable security definer set search_path to 'public' as $function$
declare th integer; res jsonb; bb jsonb;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  select ip_flag_threshold into th from settings where id = 1;
  select coalesce(jsonb_agg(q.j order by (q.j->>'bookings')::int desc, q.j->>'ip'), '[]'::jsonb) into res from (
    select jsonb_build_object('ip', i.ip, 'bookings', count(*), 'people', sum(b.people_count),
             'pending', count(*) filter (where b.status = 'pending'), 'paid', count(*) filter (where b.status = 'paid'),
             'rejected', count(*) filter (where b.status = 'rejected'),
             'first_at', min(b.created_at), 'last_at', max(b.created_at)) as j
      from booking_ips i join bookings b on b.id = i.booking_id
     where i.ip is not null and b.kind = 'registration'
     group by i.ip having count(*) >= th) q;
  select coalesce(jsonb_object_agg(b.booking_code, jsonb_build_object('ip', i.ip, 'count', c.n)), '{{}}'::jsonb) into bb
    from booking_ips i join bookings b on b.id = i.booking_id
    join (select ip, count(*) n from booking_ips bi join bookings bb2 on bb2.id = bi.booking_id where bi.ip is not null and bb2.kind = 'registration' group by ip having count(*) >= th) c on c.ip = i.ip
   where b.kind = 'registration';
  return jsonb_build_object('threshold', th, 'ips', res, 'by_booking', bb);
end $function$;

-- admin: delete every stored IP (to be done after the event)
create or replace function public.admin_clear_client_ips() returns integer
 language plpgsql security definer set search_path to 'public' as $function$
declare n integer;
begin
  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;
  delete from booking_ips; get diagnostics n = row_count;
  insert into settings_log (changed_by, who, area, field, old_value, new_value)
  values (auth.uid(), _actor(), 'settings', 'stored visitor IPs deleted', n::text || ' rows', null);
  return n;
end $function$;

revoke all on function public._request_headers(), public._clean_ip(text), public._header(text), public._client_ip(), public._client_ip_raw()
  from public, anon, authenticated, service_role;
revoke all on function public.admin_ip_flags(), public.admin_clear_client_ips() from public, anon;
grant execute on function public.admin_ip_flags(), public.admin_clear_client_ips() to authenticated;
"""
open('r2_05_cleanup_and_ip.sql', 'w').write(SQL)
print(len(SQL.splitlines()), 'lines')
