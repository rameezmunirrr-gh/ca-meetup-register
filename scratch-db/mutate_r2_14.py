"""Deliberate-mistake check for test_r2_14.py.

A green test run alone proves little. This script breaks sql/r2_14_game_prizes.sql in one way at a time (a "mutant"),
runs test_r2_14.py against each broken copy, and expects the suite to FAIL every time.
  - CAUGHT   = the suite failed (good: the test notices that mistake)
  - SURVIVED = the suite still passed (bad: the test has a blind spot)
  - BROKEN   = the broken SQL would not even load (the mutant is not a useful test; fix the mutant)
It never touches the real file: broken copies go in a temporary folder. Run:  python3 mutate_r2_14.py
"""
import os, re, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = '/home/claude/ca-meetup-register/sql/r2_14_game_prizes.sql'
orig = open(SRC).read()

def patch(old, new, expect=1, nth=None):
    """Return a function that edits the SQL text. It asserts the old text exists exactly `expect` times,
    so a mutant can never silently do nothing."""
    def f(s):
        assert s.count(old) == expect, f"expected {expect} x {old!r}, found {s.count(old)}"
        if nth is None: return s.replace(old, new)
        parts = s.split(old); return old.join(parts[:nth]) + new + old.join(parts[nth:])
    return f

MUTANTS = [
    ("lookup shows the prize even when the switch is OFF", patch("'game_prize', case when gm_on and", "'game_prize', case when true and")),
    ("lookup shows the prize for unpaid bookings", patch("'game_prize', case when gm_on and b.status = 'paid' and", "'game_prize', case when gm_on and")),
    ("lookup shows the prize on transferred-away tickets", patch("'game_prize', case when gm_on and b.status = 'paid' and t.transferred_out_at is null", "'game_prize', case when gm_on and b.status = 'paid'")),
    ("lookup shows the prize when the switch is OFF and hides it when ON", patch("'game_prize', case when gm_on and", "'game_prize', case when not gm_on and")),
    ("lookup puts the team message in the prize field", patch("(select z.body from ticket_prizes z where z.ticket_id = t.id)", "(select m.body from ticket_messages tm join game_messages m on m.id = tm.message_id where tm.ticket_id = t.id)")),
    ("set_prizes: no admin check", patch("if not is_admin() then raise exception 'NOT_ALLOWED'; end if;\n  if char_length(b)", "if false then raise exception 'NOT_ALLOWED'; end if;\n  if char_length(b)")),
    ("clear_prizes: no admin check", patch("if not is_admin() then raise exception 'NOT_ALLOWED'; end if;\n  delete from ticket_prizes", "delete from ticket_prizes")),
    ("any signed-in user can read the prize table", patch("create policy admin_read_ticket_prizes on public.ticket_prizes for select to authenticated using (is_admin());", "create policy admin_read_ticket_prizes on public.ticket_prizes for select to authenticated using (true);")),
    ("visitors can read the prize table", lambda s: s + "\ngrant select on public.ticket_prizes to anon;\ncreate policy anon_all on public.ticket_prizes for select to anon using (true);\n"),
    ("signed-in users can write the prize table directly", lambda s: s + "\ngrant insert, update, delete on public.ticket_prizes to authenticated;\ncreate policy w on public.ticket_prizes for all to authenticated using (true) with check (true);\n"),
    ("visitors may execute set_prizes", lambda s: s + "\ngrant execute on function public.admin_set_prizes(uuid[], text, text) to anon;\n"),
    ("everyone (PUBLIC) may execute clear_prizes", lambda s: s + "\ngrant execute on function public.admin_clear_prizes(uuid[]) to public;\n"),
    ("text limit loosened to 300", patch("char_length(b) not between 1 and 200 or", "char_length(b) not between 1 and 300 or")),
    ("table allows 201+ (check loosened) and function too", patch("body       text not null check (char_length(body) between 1 and 200)", "body       text not null")),
    ("control characters allowed in the text", patch("or b ~ '[[:cntrl:]]'", "")),
    ("text is not trimmed", patch("b text := trim(coalesce(p_body, ''));", "b text := coalesce(p_body, '');")),
    ("same ticket twice allowed", patch("if (select count(distinct x) from unnest(p_tickets) x) <> cnt then raise exception 'DUPLICATE_TICKET'; end if;", "")),
    ("an unknown ticket in the list is skipped, not refused", patch("if (select count(*) from tickets where id = any (p_tickets) and transferred_out_at is null) <> cnt then raise exception 'TICKET_NOT_FOUND'; end if;", "")),
    ("transferred-away tickets may win", patch("where id = any (p_tickets) and transferred_out_at is null) <> cnt", "where id = any (p_tickets)) <> cnt")),
    ("a null inside the list is accepted", patch("if array_position(p_tickets, null) is not null then raise exception 'INVALID_PAIRS'; end if;", "")),
    ("no limit on how many at once", patch("if cnt > 1000 then raise exception 'TOO_MANY'; end if;", "")),
    ("a new prize does not replace the old one", patch("on conflict (ticket_id) do update set body = excluded.body, heading = excluded.heading, created_at = now();", "on conflict (ticket_id) do nothing;")),
    ("clear ignores the ticket list (clears everyone)", patch("where p_tickets is null or ticket_id = any (p_tickets);", "where true;")),
    ("an empty list clears everyone", patch("where p_tickets is null or ticket_id = any (p_tickets);", "where coalesce(cardinality(p_tickets),0) = 0 or ticket_id = any (p_tickets);")),
    ("transfer: the prize is not carried over", patch("insert into ticket_prizes (ticket_id, body, heading)\n      select new.id, body, heading from ticket_prizes where ticket_id = new.transferred_from\n      on conflict (ticket_id) do nothing;", "")),
    ("transfer: the team message is no longer carried over", patch("insert into ticket_messages (ticket_id, message_id)\n      select new.id, message_id from ticket_messages where ticket_id = new.transferred_from\n      on conflict (ticket_id) do nothing;", "")),
    ("transfer: every new ticket gets some prize", patch("select new.id, body, heading from ticket_prizes where ticket_id = new.transferred_from", "select new.id, body, heading from ticket_prizes limit 1")),
    ("log: giving prizes is not logged", patch("perform _mlog('prizes given', null, n || ' ticket(s): ' || h || ' / ' || b);", "")),
    ("log: clearing prizes is not logged", patch("perform _mlog('prizes cleared', null, n || ' ticket(s)' || case when p_tickets is not null then ' (chosen tickets)' else '' end);", "")),
    ("set_prizes is no longer security definer", patch("returns integer\n language plpgsql security definer set search_path to 'public' as $function$\ndeclare b text", "returns integer\n language plpgsql set search_path to 'public' as $function$\ndeclare b text")),
    ("clear_prizes search path not fixed", patch("create or replace function public.admin_clear_prizes(p_tickets uuid[] default null) returns integer\n language plpgsql security definer set search_path to 'public' as", "create or replace function public.admin_clear_prizes(p_tickets uuid[] default null) returns integer\n language plpgsql security definer as")),
    ("trigger function callable by signed-in users", lambda s: s + "\ngrant execute on function public._inherit_ticket_message() to authenticated;\n"),
    ("get_site_flags starts publishing prize info", lambda s: s + "\ncreate or replace function public.get_site_flags() returns jsonb language sql stable security definer set search_path to 'public' as $f$ select jsonb_build_object('show_about', s.show_about, 'ask_email', s.ask_email, 'ask_feedback', s.ask_feedback, 'prizes', (select count(*) from ticket_prizes)) from settings s where s.id = 1 $f$;\n"),
    ("heading: not replaced when giving again", patch("do update set body = excluded.body, heading = excluded.heading,", "do update set body = excluded.body,")),
    ("heading: blank heading is stored blank", patch("coalesce(nullif(trim(coalesce(p_heading, '')), ''), 'You are a winner!')", "coalesce(p_heading, '')")),
    ("heading: wrong default text", patch("coalesce(nullif(trim(coalesce(p_heading, '')), ''), 'You are a winner!')", "coalesce(nullif(trim(coalesce(p_heading, '')), ''), 'Winner')")),
    ("heading: not trimmed", patch("nullif(trim(coalesce(p_heading, '')), '')", "nullif(coalesce(p_heading, ''), '')")),
    ("heading: no length limit in the function", patch("if char_length(h) > 60 or h ~", "if h ~")),
    ("heading: limit loosened to 80 in the function", patch("if char_length(h) > 60 or h ~", "if char_length(h) > 80 or h ~")),
    ("heading: control characters allowed", patch("if char_length(h) > 60 or h ~ '[[:cntrl:]]'", "if char_length(h) > 60")),
    ("heading: table check on length removed", patch("check (char_length(heading) between 1 and 60)", "check (char_length(heading) >= 1)")),
    ("heading: transfer child gets the default instead", patch("select new.id, body, heading from ticket_prizes where", "select new.id, body, 'You are a winner!' from ticket_prizes where")),
    ("heading: returned even when the switch is OFF", patch("'game_prize_heading', case when gm_on and", "'game_prize_heading', case when true and")),
    ("heading: returned for unpaid bookings", patch("'game_prize_heading', case when gm_on and b.status = 'paid' and", "'game_prize_heading', case when gm_on and")),
    ("heading: returned for transferred-away tickets", patch("'game_prize_heading', case when gm_on and b.status = 'paid' and t.transferred_out_at is null", "'game_prize_heading', case when gm_on and b.status = 'paid'")),
    ("heading: lookup returns the prize text as the heading", patch("(select z.heading from ticket_prizes z where z.ticket_id = t.id)", "(select z.body from ticket_prizes z where z.ticket_id = t.id)")),
    ("heading: the log leaves the heading out", patch("n || ' ticket(s): ' || h || ' / ' || b", "n || ' ticket(s): ' || b")),
    ("heading: old 2-argument call no longer works (no default)", patch("p_heading text default null)", "p_heading text)")),
]
tmp = tempfile.mkdtemp(prefix='mut_r2_14_')
rows, bad = [], 0
for i, (name, fn) in enumerate(MUTANTS, 1):
    path = os.path.join(tmp, f'mutant_{i:02d}.sql')
    open(path, 'w').write(fn(orig))
    assert open(path).read() != orig, "mutant is identical to the original"
    r = subprocess.run([sys.executable, os.path.join(HERE, 'test_r2_14.py')], capture_output=True, text=True,
                       env=dict(os.environ, R14=path), cwd=HERE, timeout=600)
    out = r.stdout + r.stderr
    m = re.search(r'=> (\d+) passed, (\d+) failed', out)
    if 'SQL FILE FAILED' in out or not m: verdict, detail = 'BROKEN', out.strip()[-300:]
    elif int(m.group(2)) > 0:
        verdict = 'CAUGHT'; first = next((l.strip() for l in out.splitlines() if 'FAIL' in l), '')
        detail = f"{m.group(2)} check(s) failed, first: {first[:90]}"
    else: verdict, detail = 'SURVIVED', 'suite still passed: blind spot'
    if verdict != 'CAUGHT': bad += 1
    print(f"{i:2d}. {verdict:8s} {name}\n      {detail}", flush=True)

print(f"\n{len(MUTANTS) - bad} of {len(MUTANTS)} deliberate mistakes caught." + ("" if not bad else f"  {bad} NOT caught: see above."))
sys.exit(1 if bad else 0)
