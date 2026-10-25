import re
txt = open('/home/claude/sql/schema_snapshot.txt', encoding='utf-8').read().replace('\r', '')
def func(name):
    m = re.search(r'^CREATE OR REPLACE FUNCTION public\.' + re.escape(name) + r'\(.*?^\$function\$\n?', txt, re.S | re.M)
    # body ends at the second $function$ marker
    start = txt.index('CREATE OR REPLACE FUNCTION public.' + name + '(')
    first = txt.index('$function$', start)
    end = txt.index('$function$', first + 10) + len('$function$')
    return txt[start:end]
def sub(s, old, new):
    assert s.count(old) == 1, (s.count(old), old[:70])
    return s.replace(old, new)

ps = func('_public_state')
ps = sub(ps, "where b.status <> 'rejected';\n  remaining", "where b.status <> 'rejected' and t.transferred_out_at is null;\n  remaining")

sb = func('submit_booking')
sb = sub(sb, "where bk.status <> 'rejected';\n  if used + n > s.cap",
             "where bk.status <> 'rejected' and t.transferred_out_at is null;\n  if used + n > s.cap")
sb = sub(sb, "    if coalesce(r.value->>'loc','') not in",
             "    if length(trim(coalesce(r.value->>'email',''))) not between 5 and 120\n       or lower(trim(r.value->>'email')) !~ '^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$' then raise exception 'INVALID_EMAIL'; end if;\n    if coalesce(r.value->>'loc','') not in")
sb = sub(sb, "declare s settings%rowtype; b bookings%rowtype; n int; used int; r record; code text; pi jsonb;",
             "declare s settings%rowtype; b bookings%rowtype; n int; used int; r record; code text; pi jsonb; tid uuid;")
sb = sub(sb, """  insert into tickets (secret, booking_id, name, phone, location, attendance, food)
  select substr(replace(gen_random_uuid()::text, '-', ''), 1, 12), b.id,
         trim(value->>'name'), value->>'phone', value->>'loc', value->>'att', value->>'food'
  from jsonb_array_elements(p_people) with ordinality as e(value, ord) order by ord;
""", """  -- one ticket per person, in the order listed; the email goes to the admin-only table ticket_emails
  for r in select value, ord from jsonb_array_elements(p_people) with ordinality as e(value, ord) order by ord loop
    insert into tickets (secret, booking_id, name, phone, location, attendance, food)
    values (substr(replace(gen_random_uuid()::text, '-', ''), 1, 12), b.id,
            trim(r.value->>'name'), r.value->>'phone', r.value->>'loc', r.value->>'att', r.value->>'food')
    returning id into tid;
    insert into ticket_emails (ticket_id, email) values (tid, lower(trim(r.value->>'email')));
  end loop;
""")

sql = f"""-- ============================================================================
-- Release 2, Step 1, piece 1: preparation (email, transfer markers, settings)
-- Written 17 Oct 2026. Tested on the scratch database before use.
-- Safe to run once. Changes no existing data. Transfers stay OFF.
-- ============================================================================

-- 1. Email per person (required for new bookings). Kept in its OWN table that only admins can read,
--    so gate volunteers (who can read the tickets table) never see email addresses.
create table if not exists public.ticket_emails (
  ticket_id uuid primary key references public.tickets(id) on delete cascade,
  email text not null check (char_length(email) between 5 and 120 and email ~ '^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$')
);
alter table public.ticket_emails enable row level security;
drop policy if exists admin_read_ticket_emails on public.ticket_emails;
create policy admin_read_ticket_emails on public.ticket_emails for select to authenticated using (is_admin());
revoke all on table public.ticket_emails from public, anon, authenticated, service_role;
grant select on table public.ticket_emails to authenticated;

-- 2. Markers used by transfers (nothing writes them yet)
--    transferred_out_at: the seller's ticket after a transfer (cancelled, not counted anywhere)
--    transferred_from:   on the buyer's new ticket, points at the seller's old ticket
alter table public.tickets add column if not exists transferred_out_at timestamptz;
alter table public.tickets add column if not exists transferred_from uuid references public.tickets(id);
create unique index if not exists tickets_transferred_from_uq on public.tickets (transferred_from) where transferred_from is not null;

-- 3. A booking is a normal registration or a transfer (transfer bookings never count as seats or income)
alter table public.bookings add column if not exists kind text not null default 'registration';
alter table public.bookings drop constraint if exists bookings_kind_check;
alter table public.bookings add constraint bookings_kind_check check (kind in ('registration', 'transfer'));

-- 4. New settings (all logged automatically by settings_log_trg)
alter table public.settings add column if not exists transfer_cutoff_at timestamptz;
alter table public.settings add column if not exists transfer_food_locked boolean not null default false;
alter table public.settings add column if not exists private_code_hours integer not null default 2;
alter table public.settings drop constraint if exists settings_code_hours_check;
alter table public.settings add constraint settings_code_hours_check check (private_code_hours between 1 and 168);

-- 5. Counting: a ticket that was transferred away no longer counts toward the cap
{ps};

-- 6. Registration now requires an email for every person
{sb};

-- 7. Exports: add email (admins only, via ticket_emails) and the transfer marker at the end of the report view
create or replace view public.report with (security_invoker = true) as   -- keep it staff-only: it must follow the caller's row-level security
 select t.ticket_no as sl_no, t.name, t.phone, t.location, t.attendance, t.food,
        b.booking_code, b.status as payment_status, b.amount_expected, b.people_count, b.screenshot_path,
        (t.checked_in_at is not null) as present, t.checked_in_at, t.created_at, t.kind, t.coord_no,
        _ticket_label(t.kind, t.ticket_no, t.coord_no) as ticket_label,
        e.email, t.transferred_out_at, b.kind as booking_kind
   from tickets t join bookings b on b.id = t.booking_id
        left join ticket_emails e on e.ticket_id = t.id
  order by t.kind, t.coord_no, t.ticket_no, t.reg_seq;
"""
open('r2_01_prep.sql', 'w').write(sql)
print(len(sql.splitlines()), 'lines')
