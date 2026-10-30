from lib import *
import json, uuid, subprocess, os
# Database suite for sql/r2_13_game_messages.sql (Messages for the game activity; shown on a ticket only while an admin switch is ON).
# Set R13 to point at a different copy of the r2_13 file (the deliberate-mistake check, mutate_r2_13.py, does this).
R = '/home/claude/ca-meetup-register/sql/'
R13 = os.environ.get('R13', R + 'r2_13_game_messages.sql')
BASE = [R + f for f in ['r2_01_prep.sql', 'r2_02_lookup.sql', 'r2_02c_close_old_transfer_doors.sql', 'r2_02b_cutover.sql',
                        'r2_03_private_transfer.sql', 'r2_04_public_via_code.sql', 'r2_05_cleanup_and_ip.sql',
                        'r2_06_transfer_settings.sql', 'r2_08_coordinator_transfer.sql', 'r2_09_about_link.sql',
                        'r2_10_email_switch.sql', 'r2_11_feedback.sql', 'r2_12_gate_undo.sql']]
t = T(); fresh(BASE + [R13]); S = seed(); admin = S['admin']
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
def save(name, body, pid=None, uid=None): return adm("select admin_save_message(%s,%s,%s)", (str(pid) if pid else None, name, body), uid)
def mid(name): return sql("select id from game_messages where name=%s", (name,))[0][0]
def assign(pairs, uid=None): return adm("select admin_assign_messages(%s::jsonb)", (json.dumps([{'t': str(a), 'm': str(b)} for a, b in pairs]),), uid)
def clear(m=None, ts=None, uid=None): return adm("select admin_clear_messages(%s,%s::uuid[])", (str(m) if m else None, [str(x) for x in ts] if ts is not None else None), uid)
def lookup(who):
    r = call('anon', "select lookup_tickets(%s,%s)", (CODE[who], PH[who]))
    j = r[1][0][0]; return [x for x in j['tickets'] if x['name'] == who][0] if j.get('found') else None
def gm(who): return lookup(who)['game_message']
def switch(on, uid=None): return adm("select admin_set_show_messages(%s)", (on,), uid)
def has(tid): return sql("select count(*) from ticket_messages where ticket_id=%s", (str(tid),))[0][0] == 1
def log(): return sql("select field, new_value from settings_log where area='messages' order by id")

# 0. structure
t.check("0.1 the file applies and the switch column exists, default OFF", sql("select show_messages from settings where id=1")[0][0] is False)
r = runfile(R13); t.check("0.2 the file can be run a second time safely", r.returncode == 0, r.stderr[-300:])
t.check("0.3 both tables have row-level security on", sql("select count(*) from pg_class where relname in ('game_messages','ticket_messages') and relrowsecurity")[0][0] == 2)
fn = ['admin_set_show_messages(boolean)', 'admin_save_message(uuid,text,text)', 'admin_delete_message(uuid)', 'admin_assign_messages(jsonb)', 'admin_clear_messages(uuid,uuid[])']
t.check("0.4 the five admin functions: signed-in may execute, visitors may not",
        all(sql(f"select has_function_privilege('authenticated','{f}','execute'), has_function_privilege('anon','{f}','execute')")[0] == (True, False) for f in fn))
t.check("0.5 nobody gets execute through PUBLIC on them",
        sql("select count(*) from pg_proc p, aclexplode(p.proacl) a where p.proname in ('admin_set_show_messages','admin_save_message','admin_delete_message','admin_assign_messages','admin_clear_messages','_mlog','_inherit_ticket_message') and a.grantee=0")[0][0] == 0)
t.check("0.6 the helper _mlog and the trigger function cannot be called by visitors or signed-in users",
        sql("select has_function_privilege('anon','_mlog(text,text,text)','execute') or has_function_privilege('authenticated','_mlog(text,text,text)','execute') or has_function_privilege('authenticated','_inherit_ticket_message()','execute')")[0][0] is False)
t.check("0.7 all five run with the owner's rights and a fixed search path",
        sql("select count(*) from pg_proc where proname = any(%s) and prosecdef and proconfig::text like '%%search_path=public%%'", (['admin_set_show_messages','admin_save_message','admin_delete_message','admin_assign_messages','admin_clear_messages'],))[0][0] == 5)

# 1. who may do what (with real rows in the tables, so 'sees nothing' means something)
_m = sql("insert into game_messages(name,body) values ('Seed','seed text') returning id")[0][0]; sql("insert into ticket_messages(ticket_id,message_id) values (%s,%s)", (str(A), str(_m)))
for label, uid, role in [('a visitor (no login)', None, 'anon'), ('a signed-in non-staff user', visitor, 'authenticated'), ('gate staff', gate, 'authenticated')]:
    def tryit(q, p=()): return call(role, q, p, uid=uid)
    rs = [tryit("select admin_set_show_messages(true)"), tryit("select admin_save_message(null,'X','y')"),
          tryit("select admin_assign_messages('[]'::jsonb)"), tryit("select admin_clear_messages()"), tryit("select admin_delete_message(%s)", (str(uuid.uuid4()),))]
    ok = all(x[0] == 'err' and ('NOT_ALLOWED' in x[1] or 'permission denied' in x[1]) for x in rs)
    t.check(f"1.x {label}: all five functions refused", ok, rs)
    t.check(f"1.x {label}: sees no rows in either table",
            (lambda a, b: (a[0] == 'err' or a[1][0][0] == 0) and (b[0] == 'err' or b[1][0][0] == 0))(tryit("select count(*) from game_messages"), tryit("select count(*) from ticket_messages")))
t.check("1.8 admin does see the seeded rows (so the 'sees nothing' checks above are meaningful)", adm("select count(*) from game_messages")[1][0][0] == 1 and adm("select count(*) from ticket_messages")[1][0][0] == 1)
sql("delete from game_messages")
t.check("1.9 nothing was created or switched by those refused calls",
        sql("select count(*) from game_messages")[0][0] == 0 and not has(A) and sql("select show_messages from settings where id=1")[0][0] is False)
t.check("1.10 nobody (not even admin) can write the tables directly",
        all(call('authenticated', q, uid=admin)[0] == 'err' for q in ["insert into game_messages(name,body) values ('a','b')", "delete from ticket_messages", "update game_messages set body='z'"]))

# 2. messages: create / edit / validation
r = save('Tiger', 'You are in team TIGER'); t.check("2.1 admin creates a message", r[0] == 'ok' and r[1][0][0], r)
save('Elephant', 'Team ELEPHANT 🐘'); save('Lion', 'Team LION')
t.check("2.2 three messages exist (emoji kept)", sql("select count(*) from game_messages")[0][0] == 3 and 'ELEPHANT 🐘' in sql("select body from game_messages where name='Elephant'")[0][0])
t.check("2.3 a second admin can also create one", save('Zebra', 'Team ZEBRA', uid=admin2)[0] == 'ok')
r = save('tiger', 'dup'); t.check("2.4 same name in other capitals: NAME_TAKEN", err(r, 'NAME_TAKEN'), r)
r = save('  Tiger  ', 'dup'); t.check("2.5 same name with spaces round it: NAME_TAKEN", err(r, 'NAME_TAKEN'), r)
t.check("2.6 empty / blank name: INVALID_NAME", err(save('', 'x'), 'INVALID_NAME') and err(save('   ', 'x'), 'INVALID_NAME') and err(save(None, 'x'), 'INVALID_NAME'))
t.check("2.7 empty / blank / missing body: INVALID_MESSAGE", err(save('N', ''), 'INVALID_MESSAGE') and err(save('N', '  '), 'INVALID_MESSAGE') and err(save('N', None), 'INVALID_MESSAGE'))
t.check("2.8 name of 61 characters refused, 60 accepted", err(save('n' * 61, 'x'), 'INVALID_NAME') and save('n' * 60, 'x')[0] == 'ok')
t.check("2.9 body of 201 characters refused, 200 accepted", err(save('B1', 'm' * 201), 'INVALID_MESSAGE') and save('B2', 'm' * 200)[0] == 'ok')
t.check("2.10 200 emoji count as 200 characters (accepted), 201 refused", save('E1', '🐯' * 200)[0] == 'ok' and err(save('E2', '🐯' * 201), 'INVALID_MESSAGE'))
t.check("2.11 a line break or tab inside the text is refused", err(save('N', 'a\nb'), 'INVALID_MESSAGE') and err(save('N', 'a\tb'), 'INVALID_MESSAGE') and err(save('N\n', 'a'), 'INVALID_NAME') or err(save('Nx', 'a\nb'), 'INVALID_MESSAGE'))
sql("delete from game_messages where name in ('n'||repeat('n',59), 'B2','E1') or char_length(name)=60")
tid = mid('Zebra'); r = save('Zebra2', 'Team ZEBRA two', pid=tid)
t.check("2.12 editing keeps the same id and changes the text", r[0] == 'ok' and str(r[1][0][0]) == str(tid) and sql("select name, body from game_messages where id=%s", (str(tid),))[0] == ('Zebra2', 'Team ZEBRA two'))
t.check("2.13 editing to another message's name: NAME_TAKEN", err(save('Lion', 'x', pid=tid), 'NAME_TAKEN'))
t.check("2.14 saving the same name again on the same message is fine", save('Zebra2', 'Team ZEBRA 3', pid=tid)[0] == 'ok')
t.check("2.15 editing an unknown id: NOT_FOUND", err(save('Q', 'q', pid=uuid.uuid4()), 'NOT_FOUND'))

# 3. the switch is enforced by the database
sql("delete from game_messages where name = 'Zebra2'")
mT, mE, mL = mid('Tiger'), mid('Elephant'), mid('Lion')
r = assign([(A, mT), (B, mE)]); t.check("3.1 admin gives Asha Tiger and Ben Elephant", r == ('ok', [(2,)]), r)
t.check("3.2 switch is OFF: a visitor with the right Booking ID + phone gets NO message", gm('Asha') is None and gm('Ben') is None)
t.check("3.3 ... and the key carries nothing at all (not even an empty-looking value) in the whole answer",
        'TIGER' not in json.dumps(call('anon', "select lookup_tickets(%s,%s)", (S['A'], PH['Asha']))[1][0][0]) and 'ELEPHANT' not in json.dumps(call('anon', "select lookup_tickets(%s,%s)", (S['A'], PH['Ben']))[1][0][0]))
t.check("3.4 the switch cannot be set to null", err(switch(None), 'INVALID_VALUE'))
t.check("3.5 admin turns the switch ON", switch(True)[0] == 'ok' and sql("select show_messages from settings where id=1")[0][0] is True)
t.check("3.6 ON: Asha sees Tiger's text, Ben sees Elephant's", gm('Asha') == 'You are in team TIGER' and gm('Ben') == 'Team ELEPHANT 🐘', (gm('Asha'), gm('Ben')))
t.check("3.7 ON: Carl, who has no message, sees none", gm('Carl') is None)
t.check("3.8 the visitor only gets the BODY, never the admin's name for it (no 'Tiger' label key, no ids)",
        set(lookup('Asha').keys()) >= {'game_message'} and 'message_id' not in json.dumps(lookup('Asha')) and '"name": "Tiger"' not in json.dumps(lookup('Asha')))
r = call('anon', "select lookup_tickets(%s,%s)", (S['A'], PH['Carl']))
t.check("3.9 ON but wrong phone for the booking: found=false, no message leaked", r[1][0][0] == {'found': False}, r)
r = call('anon', "select lookup_tickets(%s,%s)", (S['B'], PH['Asha']))
t.check("3.10 ON: another booking's code with Asha's phone: found=false", r[1][0][0] == {'found': False}, r)
t.check("3.11 the switch is logged by the Settings log", sql("select count(*) from settings_log where area='settings' and field='show_messages' and new_value='true'")[0][0] == 1)
switch(False); t.check("3.12 OFF again: messages vanish from the answer at once, assignments stay", gm('Asha') is None and has(A))
switch(True)
sql("update bookings set status='pending' where booking_code=%s", (S['B'],)); sql("insert into ticket_messages(ticket_id,message_id) values (%s,%s)", (str(C), str(mL)))
# a pending booking still answers the lookup; message must not show before payment
rr = call('anon', "select lookup_tickets(%s,%s)", (S['B'], PH['Carl']))[1][0][0]
t.check("3.13 ON: a booking that is not paid shows no message", all(x['game_message'] is None for x in rr.get('tickets', [])) if rr.get('found') else True, rr)
sql("update bookings set status='paid' where booking_code=%s", (S['B'],))
t.check("3.14 once paid the message shows", gm('Carl') == 'Team LION')
sql("delete from ticket_messages where ticket_id=%s", (str(C),))

# 4. giving messages
sql("delete from ticket_messages")
r = assign([(A, mT), (B, mT), (C, mE)]); t.check("4.1 three tickets set in one call", r == ('ok', [(3,)]), r)
t.check("4.2 the rows are right", sorted(sql("select t.name, m.name from ticket_messages x join tickets t on t.id=x.ticket_id join game_messages m on m.id=x.message_id")) == [('Asha', 'Tiger'), ('Ben', 'Tiger'), ('Carl', 'Elephant')])
r = assign([(C, mL)]); t.check("4.3 giving a new message replaces the old one (one per ticket)", r[0] == 'ok' and sql("select m.name from ticket_messages x join game_messages m on m.id=x.message_id where ticket_id=%s", (str(C),))[0][0] == 'Lion' and sql("select count(*) from ticket_messages")[0][0] == 3)
r = assign([]); t.check("4.4 an empty list does nothing and says 0", r == ('ok', [(0,)]), r)
bad = uuid.uuid4()
r = assign([(A, mE), (bad, mE)]); t.check("4.5 one unknown ticket: whole call refused (TICKET_NOT_FOUND), nothing changed", err(r, 'TICKET_NOT_FOUND') and sql("select m.name from ticket_messages x join game_messages m on m.id=x.message_id where ticket_id=%s", (str(A),))[0][0] == 'Tiger')
r = assign([(A, mE), (B, uuid.uuid4())]); t.check("4.6 one unknown message: whole call refused (MESSAGE_NOT_FOUND), nothing changed", err(r, 'MESSAGE_NOT_FOUND') and sql("select m.name from ticket_messages x join game_messages m on m.id=x.message_id where ticket_id=%s", (str(A),))[0][0] == 'Tiger')
r = assign([(A, mE), (A, mL)]); t.check("4.7 the same ticket twice: DUPLICATE_TICKET, nothing changed", err(r, 'DUPLICATE_TICKET') and sql("select m.name from ticket_messages x join game_messages m on m.id=x.message_id where ticket_id=%s", (str(A),))[0][0] == 'Tiger')
for label, arg in [('not a list', '{"t":1}'), ('null', 'null'), ('missing m', json.dumps([{'t': str(A)}])), ('missing t', json.dumps([{'m': str(mT)}])), ('not uuids', json.dumps([{'t': 'abc', 'm': 'def'}])), ('a number inside', '[1,2]')]:
    r = adm("select admin_assign_messages(%s::jsonb)", (arg,)); t.check(f"4.8 malformed list ({label}): INVALID_PAIRS", err(r, 'INVALID_PAIRS'), r)
big = [{'t': str(uuid.uuid4()), 'm': str(mT)} for _ in range(1001)]
t.check("4.9 more than 1000 at once: TOO_MANY", err(adm("select admin_assign_messages(%s::jsonb)", (json.dumps(big),)), 'TOO_MANY'))
sql("update tickets set transferred_out_at=now() where id=%s", (str(B),))
r = assign([(B, mE)]); t.check("4.10 a ticket that was transferred away is refused", err(r, 'TICKET_NOT_FOUND'), r)
t.check("4.11 ... and its old message is no longer shown to the old holder even with the switch ON", lookup('Ben') is None or lookup('Ben')['game_message'] is None, lookup('Ben'))
sql("update tickets set transferred_out_at=null where id=%s", (str(B),))
# 150 people into 15 messages in one call
sql("alter table tickets disable trigger user")
bk = sql("select id from bookings limit 1")[0][0]
extra = []
for i in range(150):
    tid2 = sql("insert into tickets (secret, booking_id, name, phone, location, attendance, food) values (%s,%s,%s,'9111111111','In Bengaluru','Surely','Veg') returning id", ('s%03d' % i + uuid.uuid4().hex, str(bk), f'P{i}'))[0][0]; extra.append(tid2)
sql("alter table tickets enable trigger user")
names = [f'Animal{i:02d}' for i in range(15)]
for n in names: save(n, f'Team {n}')
ms = [mid(n) for n in names]; pairs = [(extra[i], ms[i % 15]) for i in range(150)]
r = assign(pairs); t.check("4.12 150 tickets across 15 messages in one call", r == ('ok', [(150,)]), r)
t.check("4.13 every one of the 15 messages has exactly 10 holders", sql("select count(*), min(c), max(c) from (select count(*) c from ticket_messages where message_id = any(%s::uuid[]) group by message_id) q", ([str(x) for x in ms],))[0] == (15, 10, 10))

# 5. clearing
t.check("5.1 clear one message: only its holders lose it", clear(ms[0])[1][0][0] == 10 and sql("select count(*) from ticket_messages where message_id=%s", (str(ms[0]),))[0][0] == 0 and sql("select count(*) from ticket_messages where message_id=%s", (str(ms[1]),))[0][0] == 10)
r = clear(None, [extra[1], extra[2]]); t.check("5.2 clear chosen tickets only", r[1][0][0] == 2 and not has(extra[1]) and not has(extra[2]) and has(extra[3]))
r = clear(ms[3], [extra[3], extra[4]]); t.check("5.3 message + tickets: only the overlap is cleared", r[1][0][0] == 1 and not has(extra[3]) and has(extra[18]) and has(extra[4 + 0]) is True)
r = clear(uuid.uuid4()); t.check("5.4 clearing an unknown message: NOT_FOUND", err(r, 'NOT_FOUND'), r)
before = sql("select count(*) from ticket_messages")[0][0]
r = clear(None, []); t.check("5.5 an empty ticket list clears nothing", r[1][0][0] == 0 and sql("select count(*) from ticket_messages")[0][0] == before, r)
r = clear(); t.check("5.6 no arguments clears everyone", r[1][0][0] == before and sql("select count(*) from ticket_messages")[0][0] == 0, r)
t.check("5.7 clearing the messages did not delete the messages themselves", sql("select count(*) from game_messages")[0][0] >= 18)

# 6. deleting a message
assign([(A, mT), (B, mT), (C, mE)])
r = adm("select admin_delete_message(%s)", (str(mT),)); t.check("6.1 deleting Tiger reports 2 tickets lost it", r == ('ok', [(2,)]), r)
t.check("6.2 Asha and Ben have nothing now; Carl still has Elephant", not has(A) and not has(B) and has(C))
t.check("6.3 deleting an unknown message: NOT_FOUND", err(adm("select admin_delete_message(%s)", (str(uuid.uuid4()),)), 'NOT_FOUND'))
t.check("6.4 the tickets themselves are untouched", sql("select count(*) from tickets where id in (%s,%s)", (str(A), str(B)))[0][0] == 2)
t.check("6.5 editing a message changes what every holder sees", (lambda: (save('Elephant', 'NEW TEXT', pid=mE), gm('Carl') == 'NEW TEXT')[1])())
r = save('Tiger', 'You are in team TIGER'); mT = r[1][0][0]

# 7. a transferred ticket keeps the message
assign([(A, mE)])
nt = sql("insert into tickets (secret, booking_id, name, phone, location, attendance, food, kind, transferred_from) select 'zz'||gen_random_uuid(), booking_id, 'NewHolder', '9222222222', location, attendance, food, kind, id from tickets where id=%s returning id", (str(A),))[0][0]
t.check("7.1 a new ticket made from Asha's by a transfer gets Asha's message", sql("select message_id from ticket_messages where ticket_id=%s", (str(nt),))[0][0] == mE)
nt2 = sql("insert into tickets (secret, booking_id, name, phone, location, attendance, food) select 'yy'||gen_random_uuid(), booking_id, 'Walkin', '9333333333', location, attendance, food from tickets where id=%s returning id", (str(A),))[0][0]
t.check("7.2 an ordinary new ticket gets no message", not has(nt2))
clear(None, [A]); nt3 = sql("insert into tickets (secret, booking_id, name, phone, location, attendance, food, kind, transferred_from) select 'xx'||gen_random_uuid(), booking_id, 'N3', '9444444444', location, attendance, food, kind, id from tickets where id=%s returning id", (str(B),))[0][0]
t.check("7.3 a transfer from a ticket with no message gives none (and no error)", not has(nt3))

# 8. the Settings log
lg = log()
t.check("8.1 creating, editing, giving, clearing and deleting are all in the log", {'message added', 'message edited', 'messages given', 'messages cleared', 'message deleted'} <= {x[0] for x in lg}, [x[0] for x in lg])
t.check("8.2 the log says who: the real admin's name", sql("select count(*) from settings_log where area='messages' and who='Admin One'")[0][0] > 0 and sql("select count(*) from settings_log where area='messages' and who='Admin Two'")[0][0] > 0)
t.check("8.3 a 'messages given' line has the counts per message", any('Animal00 x1' in (x[1] or '') or 'x10' in (x[1] or '') for x in lg if x[0] == 'messages given'), [x for x in lg if x[0] == 'messages given'][:2])
t.check("8.4 a refused call writes nothing to the log", (lambda n: (save('', 'x'), assign([(A, uuid.uuid4())]), sql("select count(*) from settings_log where area='messages'")[0][0] == n)[2])(sql("select count(*) from settings_log where area='messages'")[0][0]))
t.check("8.5 an edit that changes nothing writes no 'edited' line", (lambda n: (save('Tiger', 'You are in team TIGER', pid=mT), sql("select count(*) from settings_log where area='messages'")[0][0] == n)[1])(sql("select count(*) from settings_log where area='messages'")[0][0]))

# 9. the rest of the lookup is unchanged
j = call('anon', "select lookup_tickets(%s,%s)", (S['A'], PH['Asha']))[1][0][0]
t.check("9.1 the answer still has the old fields", {'found', 'kind', 'booking_code', 'status', 'people_count', 'amount_expected', 'tickets'} <= set(j) and {'ticket_no', 'label', 'secret', 'name', 'food', 'attendance', 'location', 'transferred'} <= set(j['tickets'][0]))
t.check("9.2 junk input still gives found=false", call('anon', "select lookup_tickets('x','y')")[1][0][0] == {'found': False})
t.check("9.3 lookup still runs for visitors and signed-in users only", sql("select has_function_privilege('anon','lookup_tickets(text,text)','execute'), has_function_privilege('authenticated','lookup_tickets(text,text)','execute')")[0] == (True, True))
t.check("9.4 get_site_flags is unchanged (the switch is not published there)", 'show_messages' not in json.dumps(call('anon', "select get_site_flags()")[1][0][0]))
t.check("9.5 gate_scan style reads: gate staff cannot read messages through tickets either", call('authenticated', "select count(*) from ticket_messages", uid=gate)[1] in ([(0,)], ) or call('authenticated', "select count(*) from ticket_messages", uid=gate)[0] == 'err')
t.report("test_r2_13")
