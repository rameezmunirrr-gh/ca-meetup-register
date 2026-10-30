"""Deliberate-mistake check for test_r2_13.py.

A green test run alone proves little. This script breaks sql/r2_13_game_messages.sql in one way at a time (a "mutant"),
runs test_r2_13.py against each broken copy, and expects the suite to FAIL every time.
  - CAUGHT   = the suite failed (good: the test notices that mistake)
  - SURVIVED = the suite still passed (bad: the test has a blind spot)
  - BROKEN   = the broken SQL would not even load (the mutant is not a useful test; fix the mutant)
It never touches the real file: broken copies go in a temporary folder. Run:  python3 mutate_r2_13.py
"""
import os, re, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = '/home/claude/ca-meetup-register/sql/r2_13_game_messages.sql'
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
    ("lookup shows the message even when the switch is OFF", patch("case when gm_on and b.status", "case when true and b.status")),
    ("lookup shows the message for unpaid bookings", patch("gm_on and b.status = 'paid' and", "gm_on and")),
    ("lookup shows the message on transferred-away tickets", patch("b.status = 'paid' and t.transferred_out_at is null\n                                then", "b.status = 'paid'\n                                then")),
    ("lookup reads the switch backwards", patch("case when gm_on and", "case when not gm_on and")),
    ("lookup returns the admin's NAME instead of the text", patch("select m.body from ticket_messages", "select m.name from ticket_messages")),
    ("switch defaults to ON", patch("show_messages boolean not null default false", "show_messages boolean not null default true")),
    ("anyone signed in may flip the switch", patch("create or replace function public.admin_set_show_messages(p_show boolean) returns void\n language plpgsql security definer set search_path to 'public' as $function$\nbegin\n  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;", "create or replace function public.admin_set_show_messages(p_show boolean) returns void\n language plpgsql security definer set search_path to 'public' as $function$\nbegin\n")),
    ("save_message: no admin check", patch("if not is_admin() then raise exception 'NOT_ALLOWED'; end if;\n  if char_length(n)", "if false then raise exception 'NOT_ALLOWED'; end if;\n  if char_length(n)")),
    ("assign_messages: no admin check", patch("if not is_admin() then raise exception 'NOT_ALLOWED'; end if;\n  if p_pairs is null", "if false then raise exception 'NOT_ALLOWED'; end if;\n  if p_pairs is null")),
    ("clear_messages: no admin check", patch("if not is_admin() then raise exception 'NOT_ALLOWED'; end if;\n  if p_message is not null", "if false then raise exception 'NOT_ALLOWED'; end if;\n  if p_message is not null")),
    ("delete_message: no admin check", patch("if not is_admin() then raise exception 'NOT_ALLOWED'; end if;\n  select * into o from game_messages where id = p_id for update;\n  if not found then raise exception 'NOT_FOUND'; end if;\n  select count", "select count_placeholder"), ) if False else ("delete_message: no admin check", patch("  if not is_admin() then raise exception 'NOT_ALLOWED'; end if;\n  select * into o from game_messages where id = p_id for update;\n  if not found then raise exception 'NOT_FOUND'; end if;\n  select count(*)", "  select * into o from game_messages where id = p_id for update;\n  if not found then raise exception 'NOT_FOUND'; end if;\n  select count(*)")),
    ("gate staff / any signed-in user can read game_messages", patch("for select to authenticated using (is_admin());\ndrop policy if exists admin_read_ticket_messages", "for select to authenticated using (true);\ndrop policy if exists admin_read_ticket_messages")),
    ("gate staff / any signed-in user can read ticket_messages", patch("create policy admin_read_ticket_messages on public.ticket_messages for select to authenticated using (is_admin());", "create policy admin_read_ticket_messages on public.ticket_messages for select to authenticated using (true);")),
    ("visitors can read the tables", lambda s: s + "\ngrant select on public.game_messages, public.ticket_messages to anon;\ncreate policy anon_all on public.ticket_messages for select to anon using (true);\n"),
    ("signed-in users can write the table directly", lambda s: s + "\ngrant insert, update, delete on public.ticket_messages to authenticated;\ncreate policy w on public.ticket_messages for all to authenticated using (true) with check (true);\n"),
    ("visitors may execute the assign function", lambda s: s + "\ngrant execute on function public.admin_assign_messages(jsonb) to anon;\n"),
    ("visitors may execute the switch function", lambda s: s + "\ngrant execute on function public.admin_set_show_messages(boolean) to anon;\n"),
    ("everyone (PUBLIC) may execute clear", lambda s: s + "\ngrant execute on function public.admin_clear_messages(uuid, uuid[]) to public;\n"),
    ("the helper _mlog can be called by signed-in users", lambda s: s + "\ngrant execute on function public._mlog(text, text, text) to authenticated;\n"),
    ("body limit 201 instead of 200 (function)", patch("char_length(b) not between 1 and 200", "char_length(b) not between 1 and 300")),
    ("name limit loosened (function)", patch("char_length(n) not between 1 and 60", "char_length(n) not between 1 and 100")),
    ("control characters allowed in the text", patch("b ~ '[[:cntrl:]]'", "false")),
    ("names may repeat (case-insensitive check dropped)", patch("where lower(name) = lower(n))", "where name = n)")),
    ("renaming onto another message's name allowed", patch("lower(name) = lower(n) and id <> p_id", "false")),
    ("assign: a bad ticket in the list is skipped, not refused", patch("if (select count(*) from tickets where id = any (ids_t) and transferred_out_at is null) <> cnt then raise exception 'TICKET_NOT_FOUND'; end if;", "")),
    ("assign: a bad message in the list is not refused", patch("then raise exception 'MESSAGE_NOT_FOUND'; end if;", "then null; end if;")),
    ("assign: same ticket twice allowed", patch("if (select count(distinct x) from unnest(ids_t) x) <> cnt then raise exception 'DUPLICATE_TICKET'; end if;", "")),
    ("assign: transferred-away tickets allowed", patch("id = any (ids_t) and transferred_out_at is null) <> cnt", "id = any (ids_t)) <> cnt")),
    ("assign: does not replace an earlier message", patch("on conflict (ticket_id) do update set message_id = excluded.message_id, assigned_at = now();", "on conflict (ticket_id) do nothing;")),
    ("assign: no size limit", patch("if cnt > 1000 then raise exception 'TOO_MANY'; end if;", "")),
    ("clear: ignores the message filter (clears everyone)", patch("(p_message is null or message_id = p_message)", "true")),
    ("clear: ignores the ticket filter (clears everyone)", patch("(p_tickets is null or ticket_id = any (p_tickets))", "true")),
    ("clear: an empty ticket list clears everyone", patch("(p_tickets is null or ticket_id = any (p_tickets))", "(coalesce(cardinality(p_tickets),0) = 0 or ticket_id = any (p_tickets))")),
    ("delete: leaves the assignments behind (no cascade)", patch("message_id  uuid not null references public.game_messages(id) on delete cascade", "message_id  uuid not null references public.game_messages(id) on delete set null")),
    ("transfer trigger removed (new holder gets nothing)", patch("create trigger tickets_inherit_message_trg after insert on public.tickets for each row execute function public._inherit_ticket_message();", "")),
    ("transfer trigger gives every new ticket some other ticket's message", patch("select new.id, message_id from ticket_messages where ticket_id = new.transferred_from", "select new.id, message_id from ticket_messages limit 1")),
    ("log: creating a message is not logged", patch("perform _mlog('message added', null, n || ': ' || b);", "")),
    ("log: giving messages is not logged", patch("perform _mlog('messages given'", "perform null::text; --")),
    ("log: clearing is not logged", patch("perform _mlog('messages cleared', null, n || ' ticket(s)' || case when nm is not null then ' of ' || nm else '' end\n                || case when p_tickets is not null then ' (chosen tickets)' else '' end);", "")),
    ("log: deleting is not logged", patch("perform _mlog('message deleted'", "perform null::text; --")),
    ("log: area not allowed (log insert fails)", patch("array['settings','staff','transfer','messages']", "array['settings','staff','transfer']")),
    ("function is no longer security definer (assign)", patch("create or replace function public.admin_assign_messages(p_pairs jsonb) returns integer\n language plpgsql security definer", "create or replace function public.admin_assign_messages(p_pairs jsonb) returns integer\n language plpgsql")),
    ("search_path not fixed (save)", patch("create or replace function public.admin_save_message(p_id uuid, p_name text, p_body text) returns uuid\n language plpgsql security definer set search_path to 'public' as", "create or replace function public.admin_save_message(p_id uuid, p_name text, p_body text) returns uuid\n language plpgsql security definer as")),
    ("lookup now publishes the switch/flag through get_site_flags too", lambda s: s + "\ncreate or replace function public.get_site_flags() returns jsonb language sql stable security definer set search_path to 'public' as $f$ select jsonb_build_object('show_about', s.show_about, 'ask_email', s.ask_email, 'ask_feedback', s.ask_feedback, 'show_messages', s.show_messages) from settings s where s.id = 1 $f$;\n"),
]
tmp = tempfile.mkdtemp(prefix='mut_r2_13_')
rows, bad = [], 0
for i, (name, fn) in enumerate(MUTANTS, 1):
    path = os.path.join(tmp, f'mutant_{i:02d}.sql')
    open(path, 'w').write(fn(orig))
    assert open(path).read() != orig, "mutant is identical to the original"
    r = subprocess.run([sys.executable, os.path.join(HERE, 'test_r2_13.py')], capture_output=True, text=True,
                       env=dict(os.environ, R13=path), cwd=HERE, timeout=600)
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
