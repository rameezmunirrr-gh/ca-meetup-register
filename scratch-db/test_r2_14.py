from lib import *
import json, uuid, subprocess, os
# Database suite for sql/r2_14_game_prizes.sql (a prize line on a ticket, separate from the team message; same admin switch).
# Set R14 to point at a different copy of the r2_14 file (mutate_r2_14.py does this).
R = '/home/claude/ca-meetup-register/sql/'
R14 = os.environ.get('R14', R + 'r2_14_game_prizes.sql')
BASE = [R + f for f in ['r2_01_prep.sql', 'r2_02_lookup.sql', 'r2_02c_close_old_transfer_doors.sql', 'r2_02b_cutover.sql', 'r2_03_private_transfer.sql',
        'r2_04_public_via_code.sql', 'r2_05_cleanup_and_ip.sql', 'r2_06_transfer_settings.sql', 'r2_08_coordinator_transfer.sql', 'r2_09_about_link.sql',
        'r2_10_email_switch.sql', 'r2_11_feedback.sql', 'r2_12_gate_undo.sql', 'r2_13_game_messages.sql']]
t = T(); fresh(BASE + [R14]); S = seed(); admin = S['admin']
def mkuser(email, role=None, name=None):
    u = uuid.uuid4(); sql("insert into auth.users (id,email) values (%s,%s)", (str(u), email))
    if role: sql("insert into staff (user_id,name,role) values (%s,%s,%s)", (str(u), name or email, role))
    return u
gate = mkuser('g@t', 'gate', 'Gate One'); admin2 = mkuser('a2@t', 'admin', 'Admin Two'); visitor = mkuser('v@t')
tk = {r[1]: r[0] for r in sql("select id, name from tickets order by name")}; A, B, C = tk['Asha'], tk['Ben'], tk['Carl']
CODE = {'Asha': S['A'], 'Ben': S['A'], 'Carl': S['B']}; PH = {'Asha': '9000000001', 'Ben': '9000000002', 'Carl': '9000000003'}
def runfile(p): return subprocess.run(["psql", "-h", "/tmp", "-p", "5544", "-q", "-d", "postgres", "-U", "postgres", "-v", "ON_ERROR_STOP=1", "-f", p], capture_output=True, text=True)
def adm(q, p=(), uid=None): return call('authenticated', q, p, uid=uid or admin)
def err(r, code): return r[0] == 'err' and code in r[1]
def prize(ts, body, uid=None, heading=None): return adm("select admin_set_prizes(%s::uuid[],%s,%s)", ([str(x) for x in ts] if ts is not None else None, body, heading), uid)
def hd(tid): return sql("select heading from ticket_prizes where ticket_id=%s", (str(tid),))[0][0]
def pclear(ts=None, uid=None): return adm("select admin_clear_prizes(%s::uuid[])", ([str(x) for x in ts] if ts is not None else None,), uid)
def look(who):
    j = call('anon', "select lookup_tickets(%s,%s)", (CODE[who], PH[who]))[1][0][0]
    return [x for x in j['tickets'] if x['name'] == who][0]
def has(tid): return sql("select count(*) from ticket_prizes where ticket_id=%s", (str(tid),))[0][0] == 1
def body(tid): return sql("select body from ticket_prizes where ticket_id=%s", (str(tid),))[0][0]
def switch(on): return adm("select admin_set_show_messages(%s)", (on,))
def plog(): return sql("select field, new_value, who from settings_log where area='messages' and field like 'prizes%%' order by id", ())

# 0. structure
t.check("0.1 the table exists, has row-level security, and nothing is in it", sql("select relrowsecurity from pg_class where relname='ticket_prizes'")[0][0] and sql("select count(*) from ticket_prizes")[0][0] == 0)
r = runfile(R14); t.check("0.2 the file can be run a second time safely", r.returncode == 0, r.stderr[-300:])
fn = ['admin_set_prizes(uuid[],text,text)', 'admin_clear_prizes(uuid[])']
t.check("0.3 both functions: signed-in may execute, visitors may not", all(sql(f"select has_function_privilege('authenticated','{f}','execute'), has_function_privilege('anon','{f}','execute')")[0] == (True, False) for f in fn))
t.check("0.4 nobody gets execute through PUBLIC", sql("select count(*) from pg_proc p, aclexplode(p.proacl) a where p.proname in ('admin_set_prizes','admin_clear_prizes','_inherit_ticket_message') and a.grantee=0")[0][0] == 0)
t.check("0.5 both run with the owner's rights and a fixed search path", sql("select count(*) from pg_proc where proname in ('admin_set_prizes','admin_clear_prizes') and prosecdef and proconfig::text like '%%search_path=public%%'", ())[0][0] == 2)
t.check("0.6 the trigger function cannot be called by signed-in users or visitors", sql("select has_function_privilege('anon','_inherit_ticket_message()','execute') or has_function_privilege('authenticated','_inherit_ticket_message()','execute')")[0][0] is False)
t.check("0.7 the lookup is still executable by visitors and signed-in users", sql("select has_function_privilege('anon','lookup_tickets(text,text)','execute'), has_function_privilege('authenticated','lookup_tickets(text,text)','execute')")[0] == (True, True))

# 1. who may do what (with a real prize in the table so "sees nothing" means something)
sql("insert into ticket_prizes(ticket_id, body) values (%s,'seed prize')", (str(A),))
for label, uid, role in [('a visitor (no login)', None, 'anon'), ('a signed-in non-staff user', visitor, 'authenticated'), ('gate staff', gate, 'authenticated')]:
    rs = [call(role, "select admin_set_prizes(%s::uuid[],'x')", ([str(B)],), uid=uid), call(role, "select admin_clear_prizes()", uid=uid)]
    t.check(f"1.x {label}: both functions refused", all(x[0] == 'err' and ('NOT_ALLOWED' in x[1] or 'permission denied' in x[1]) for x in rs), rs)
    r = call(role, "select count(*) from ticket_prizes", uid=uid)
    t.check(f"1.x {label}: sees no prize rows", r[0] == 'err' or r[1][0][0] == 0, r)
t.check("1.8 admin does see the seeded row", adm("select count(*) from ticket_prizes")[1][0][0] == 1)
t.check("1.9 the refused calls changed nothing", has(A) and not has(B) and body(A) == 'seed prize')
t.check("1.10 nobody (not even an admin) can write the table directly", all(call('authenticated', q, uid=admin)[0] == 'err' for q in ["insert into ticket_prizes(ticket_id,body) values (gen_random_uuid(),'x')", "delete from ticket_prizes", "update ticket_prizes set body='z'"]))
sql("delete from ticket_prizes")

# 2. giving prizes
r = prize([A], 'Extra food 🍛'); t.check("2.1 admin gives one prize", r == ('ok', [(1,)]) and body(A) == 'Extra food 🍛', r)
r = prize([B, C], '  Free dessert  '); t.check("2.2 two winners at once, the text is trimmed", r == ('ok', [(2,)]) and body(B) == 'Free dessert' and body(C) == 'Free dessert', r)
r = prize([A], 'Second prize'); t.check("2.3 giving again replaces the old prize (one per ticket)", r[0] == 'ok' and body(A) == 'Second prize' and sql("select count(*) from ticket_prizes")[0][0] == 3)
t.check("2.4 an empty list gives nothing and says 0", prize([], 'x') == ('ok', [(0,)]))
t.check("2.5 a null list: INVALID_PAIRS", err(prize(None, 'x'), 'INVALID_PAIRS'))
t.check("2.6 empty / blank / missing text: INVALID_MESSAGE", all(err(prize([A], b), 'INVALID_MESSAGE') for b in ['', '   ', None]))
t.check("2.7 text of 201 characters refused, 200 accepted", err(prize([A], 'm' * 201), 'INVALID_MESSAGE') and prize([A], 'm' * 200)[0] == 'ok')
t.check("2.8 200 emoji accepted, 201 refused", prize([A], '🍛' * 200)[0] == 'ok' and err(prize([A], '🍛' * 201), 'INVALID_MESSAGE'))
t.check("2.9 line break or tab inside the text refused", err(prize([A], 'a\nb'), 'INVALID_MESSAGE') and err(prize([A], 'a\tb'), 'INVALID_MESSAGE'))
sql("delete from ticket_prizes where ticket_id=%s", (str(C),))
t.check("2.9b the table itself also refuses 201 characters and empty text, even for the database owner", call("postgres", "insert into ticket_prizes(ticket_id,body) values (%s,%s)", (str(C), "m" * 201))[0] == "err" and call("postgres", "insert into ticket_prizes(ticket_id,body) values (%s,%s)", (str(C), ""))[0] == "err")
prize([C], "Free dessert")
bad = uuid.uuid4(); before = sql("select ticket_id, body from ticket_prizes order by ticket_id")
r = prize([A, bad], 'zzz'); t.check("2.10 one unknown ticket: TICKET_NOT_FOUND and NOTHING changed", err(r, 'TICKET_NOT_FOUND') and sql("select ticket_id, body from ticket_prizes order by ticket_id") == before, r)
r = prize([A, A], 'zzz'); t.check("2.11 the same ticket twice: DUPLICATE_TICKET, nothing changed", err(r, 'DUPLICATE_TICKET') and sql("select ticket_id, body from ticket_prizes order by ticket_id") == before, r)
r = adm("select admin_set_prizes(array[%s::uuid, null],'x')", (str(A),)); t.check("2.12 a null inside the list: INVALID_PAIRS", err(r, 'INVALID_PAIRS'), r)
t.check("2.13 more than 1000 at once: TOO_MANY", err(adm("select admin_set_prizes(%s::uuid[],'x')", ([str(uuid.uuid4()) for _ in range(1001)],)), 'TOO_MANY'))
sql("update tickets set transferred_out_at=now() where id=%s", (str(B),))
t.check("2.14 a ticket transferred away is refused", err(prize([B], 'x'), 'TICKET_NOT_FOUND'))
sql("update tickets set transferred_out_at=null where id=%s", (str(B),))
sql("alter table tickets disable trigger user")
bk = sql("select id from bookings limit 1")[0][0]; extra = [sql("insert into tickets (secret, booking_id, name, phone, location, attendance, food) values (%s,%s,%s,'9111111111','In Bengaluru','Surely','Veg') returning id", ('s%03d' % i + uuid.uuid4().hex, str(bk), f'P{i}'))[0][0] for i in range(150)]
sql("alter table tickets enable trigger user")
t.check("2.15 150 winners in one call", prize(extra, 'Everyone wins') == ('ok', [(150,)]) and sql("select count(*) from ticket_prizes")[0][0] == 153)
sql("delete from ticket_prizes where ticket_id = any(%s::uuid[])", ([str(x) for x in extra],))

# 2b. the heading above the line
sql("delete from ticket_prizes"); DEF = 'You are a winner!'
prize([A], 'x'); prize([B], 'x', heading='   '); 
t.check("2b.1 no heading, or a blank one, means the default 'You are a winner!'", hd(A) == DEF and hd(B) == DEF, (hd(A), hd(B)))
prize([C], 'x', heading='  A message for you  '); t.check("2b.2 a typed heading is saved, trimmed", hd(C) == 'A message for you', hd(C))
prize([C], 'y', heading='Secret mission 🎯'); t.check("2b.3 giving again replaces the heading as well as the text", hd(C) == 'Secret mission 🎯' and body(C) == 'y')
t.check("2b.4 a heading of 60 characters is accepted, 61 refused (INVALID_NAME), nothing changed", prize([A], 'x', heading='h' * 60)[0] == 'ok' and hd(A) == 'h' * 60 and err(prize([A], 'zz', heading='h' * 61), 'INVALID_NAME') and body(A) == 'x')
t.check("2b.5 60 emoji accepted, 61 refused", prize([A], 'x', heading='🎯' * 60)[0] == 'ok' and err(prize([A], 'x', heading='🎯' * 61), 'INVALID_NAME'))
t.check("2b.6 a line break or tab in the heading is refused", err(prize([A], 'x', heading='a\nb'), 'INVALID_NAME') and err(prize([A], 'x', heading='a\tb'), 'INVALID_NAME'))
t.check("2b.7 a refused heading changes nothing for the other tickets in the call", (lambda before: (prize([A, B], 'zz', heading='h' * 61), sql("select ticket_id, body, heading from ticket_prizes order by ticket_id") == before)[1])(sql("select ticket_id, body, heading from ticket_prizes order by ticket_id")))
t.check("2b.8 the table itself refuses a 61-character or empty heading, even for the database owner", call("postgres", "insert into ticket_prizes(ticket_id,body,heading) select id,'b',%s from tickets where name='Carl' on conflict do nothing", ("h" * 61,))[0] == "err" and (call("postgres", "update ticket_prizes set heading='' where ticket_id=%s", (str(C),))[0] == "err"))
t.check("2b.9 a row inserted without a heading gets the default", (lambda: (sql("delete from ticket_prizes where ticket_id=%s", (str(C),)), sql("insert into ticket_prizes(ticket_id,body) values (%s,'q')", (str(C),)), hd(C) == DEF)[2])())
t.check("2b.10 the old two-argument call (text only) still works", adm("select admin_set_prizes(%s::uuid[],'two args')", ([str(A)],)) == ('ok', [(1,)]) and body(A) == 'two args' and hd(A) == DEF)
sql("delete from ticket_prizes")

# 3. the switch decides what visitors get
sql("delete from ticket_prizes"); sql("delete from ticket_messages")
mid = adm("select admin_save_message(null,'Tiger','Team TIGER')")[1][0][0]
adm("select admin_assign_messages(%s::jsonb)", (json.dumps([{'t': str(A), 'm': str(mid)}]),)); prize([A, B], 'Extra food')
t.check("3.1 switch OFF (default): the visitor gets NO prize and NO message", look('Asha')['game_prize'] is None and look('Asha')['game_message'] is None and look('Ben')['game_prize'] is None)
t.check("3.2 ... and the words are nowhere in the whole answer", 'Extra food' not in json.dumps(call('anon', "select lookup_tickets(%s,%s)", (S['A'], PH['Asha']))[1][0][0]))
switch(True)
t.check("3.3 switch ON: Asha gets both, Ben only the prize, Carl nothing", (look('Asha')['game_prize'], look('Asha')['game_message'], look('Ben')['game_prize'], look('Ben')['game_message'], look('Carl')['game_prize'], look('Carl')['game_message']) == ('Extra food', 'Team TIGER', 'Extra food', None, None, None))
prize([A], 'Go to the bar', heading='Secret mission'); prize([B], 'x')
t.check("3.3b with the switch ON the visitor gets the line AND its heading; a ticket with no line has both null", look('Asha')['game_prize'] == 'Go to the bar' and look('Asha')['game_prize_heading'] == 'Secret mission' and look('Ben')['game_prize_heading'] == DEF and look('Carl')['game_prize_heading'] is None and look('Carl')['game_prize'] is None, (look('Asha'), look('Carl')))
switch(False); t.check("3.3c with the switch OFF neither the line nor the heading leaves the database", look('Asha')['game_prize'] is None and look('Asha')['game_prize_heading'] is None and 'Secret mission' not in json.dumps(call('anon', "select lookup_tickets(%s,%s)", (S['A'], PH['Asha']))[1][0][0])); switch(True)
prize([A, B], 'Extra food'); 
t.check("3.4 the visitor only gets the text (no ids, no admin name)", 'ticket_id' not in json.dumps(look('Asha')) and 'Tiger"' not in json.dumps(look('Asha')))
r = call('anon', "select lookup_tickets(%s,%s)", (S['A'], PH['Carl'])); t.check("3.5 wrong phone: found=false, no prize leaked", r[1][0][0] == {'found': False})
sql("update bookings set status='pending' where booking_code=%s", (S['A'],))
rr = call('anon', "select lookup_tickets(%s,%s)", (S['A'], PH['Asha']))[1][0][0]
t.check("3.6 booking not paid: no prize shown", all(x['game_prize'] is None for x in rr['tickets']), rr)
t.check("3.6b booking not paid: no heading shown either", len(rr['tickets']) > 0 and all(x['game_prize_heading'] is None for x in rr['tickets']), rr)
sql("update bookings set status='paid' where booking_code=%s", (S['A'],))
sql("update tickets set transferred_out_at=now() where id=%s", (str(B),))
bb = call('anon', "select lookup_tickets(%s,%s)", (S['A'], PH['Ben']))[1][0][0]
t.check("3.7 a transferred-away ticket shows no prize", all(x['game_prize'] is None for x in bb.get('tickets', [])) or not bb.get('found'), bb)
t.check("3.7b a transferred-away ticket shows no heading either (and the booking is still found)", bb.get('found') and any(x['transferred'] for x in bb['tickets']) and all(x['game_prize_heading'] is None for x in bb['tickets'] if x['transferred']), bb)
sql("update tickets set transferred_out_at=null where id=%s", (str(B),))
switch(False); t.check("3.8 OFF again: prize gone from the answer at once, still stored", look('Asha')['game_prize'] is None and has(A)); switch(True)

# 4. taking prizes away
sql("delete from ticket_prizes"); prize([A, B, C], 'P')
r = pclear([A, B]); t.check("4.1 clear chosen tickets only", r == ('ok', [(2,)]) and not has(A) and not has(B) and has(C), r)
t.check("4.2 an empty list clears nothing", pclear([]) == ('ok', [(0,)]) and has(C))
r = pclear(); t.check("4.3 no argument clears everyone", r == ('ok', [(1,)]) and sql("select count(*) from ticket_prizes")[0][0] == 0, r)
t.check("4.4 clearing a ticket that has none is fine (0)", pclear([A]) == ('ok', [(0,)]))
t.check("4.5 clearing did not touch the team messages", sql("select count(*) from ticket_messages")[0][0] == 1)

# 5. transfers keep the prize too
prize([A], 'Winner'); 
def child(frm, nm): return sql("insert into tickets (secret, booking_id, name, phone, location, attendance, food, kind, transferred_from) select 'zz'||gen_random_uuid(), booking_id, %s, '9222222222', location, attendance, food, kind, id from tickets where id=%s returning id", (nm, str(frm)))[0][0]
prize([A], 'Winner', heading='Clue 3'); n1 = child(A, 'NewA'); t.check("5.0 a transfer child gets the heading too", hd(n1) == 'Clue 3', hd(n1))
t.check("5.1 a transfer child gets the prize AND the team message of its parent", has(n1) and body(n1) == 'Winner' and sql("select count(*) from ticket_messages where ticket_id=%s", (str(n1),))[0][0] == 1)
n2 = child(C, 'NewC'); t.check("5.2 a child of a ticket with neither gets neither (no error)", not has(n2) and sql("select count(*) from ticket_messages where ticket_id=%s", (str(n2),))[0][0] == 0)
n3 = sql("insert into tickets (secret, booking_id, name, phone, location, attendance, food) select 'yy'||gen_random_uuid(), booking_id, 'Walk', '9333333333', location, attendance, food from tickets where id=%s returning id", (str(A),))[0][0]
t.check("5.3 an ordinary new ticket gets no prize", not has(n3))
# a prize on the parent only, no team message: the child gets the prize only
prize([B], 'WinnerB'); n4 = child(B, 'NewB')
t.check("5.4 prize but no team message on the parent: the child gets the prize only", has(n4) and sql("select count(*) from ticket_messages where ticket_id=%s", (str(n4),))[0][0] == 0)

# 6. the log
lg = plog()
t.check("6.1 giving and clearing prizes are logged, with the admin's name", {'prizes given', 'prizes cleared'} <= {x[0] for x in lg} and all(x[2] in ('Admin One', 'Admin Two') for x in lg), lg[:3])
prize([extra[0]], 'logged line', heading='Logged heading'); t.check("6.1b the log line contains the heading as well as the text", any('Logged heading / logged line' in (x[1] or '') for x in plog() if x[0] == 'prizes given'), plog()[-2:])
t.check("6.2 a log line says how many and what the text was", any('Extra food' in (x[1] or '') for x in lg if x[0] == 'prizes given') and any(x[1].startswith('150 ticket') for x in lg if x[0] == 'prizes given'))
n = sql("select count(*) from settings_log where area='messages'")[0][0]; prize([A], ''); prize([bad], 'x')
t.check("6.3 refused calls write nothing to the log", sql("select count(*) from settings_log where area='messages'")[0][0] == n)

# 7. what must not change
j = call('anon', "select lookup_tickets(%s,%s)", (S['A'], PH['Asha']))[1][0][0]
t.check("7.1 the old fields and game_message are still in the answer", {'found', 'kind', 'booking_code', 'status', 'people_count', 'amount_expected', 'tickets'} <= set(j) and {'ticket_no', 'label', 'secret', 'name', 'food', 'attendance', 'location', 'transferred', 'game_message', 'game_prize', 'game_prize_heading'} <= set(j['tickets'][0]))
t.check("7.2 junk input still gives found=false", call('anon', "select lookup_tickets('x','y')")[1][0][0] == {'found': False})
t.check("7.3 get_site_flags does not publish anything about prizes", 'prize' not in json.dumps(call('anon', "select get_site_flags()")[1][0][0]).lower())
t.check("7.4 the r2_13 functions still work (give, clear)", adm("select admin_save_message(null,'Z','z')")[0] == 'ok')
t.report("test_r2_14")
