from lib import *
import json, uuid, subprocess, os
# Database suite for sql/r2_12_gate_undo.sql: gate_undo_checkin(p_id uuid).
# Rule under test: any signed-in organiser (gate) may undo an admission for 2 minutes; admins may undo any time;
# everyone else (visitors, signed-in non-staff) is refused. A row that does not match raises UNDO_EXPIRED.
# Builds the database from the repo's sql/ folder (no copies needed). Set R12 to point at a different copy of the
# r2_12 file (the deliberate-mistake check, mutate_r2_12.py, does this).
R = '/home/claude/ca-meetup-register/sql/'
R12 = os.environ.get('R12', R + 'r2_12_gate_undo.sql')
BASE = [R + f for f in ['r2_01_prep.sql', 'r2_02_lookup.sql', 'r2_02c_close_old_transfer_doors.sql', 'r2_02b_cutover.sql',
                        'r2_03_private_transfer.sql', 'r2_04_public_via_code.sql', 'r2_05_cleanup_and_ip.sql',
                        'r2_06_transfer_settings.sql', 'r2_08_coordinator_transfer.sql', 'r2_09_about_link.sql',
                        'r2_10_email_switch.sql', 'r2_11_feedback.sql']]
t = T(); fresh(BASE + [R12]); S = seed(); admin = S['admin']

def mkuser(email, role=None, name=None):
    u = uuid.uuid4(); sql("insert into auth.users (id,email) values (%s,%s)", (str(u), email))
    if role: sql("insert into staff (user_id,name,role) values (%s,%s,%s)", (str(u), name or email, role))
    return u
gate1 = mkuser('g1@t', 'gate', 'Gate One'); gate2 = mkuser('g2@t', 'gate', 'Gate Two')
admin2 = mkuser('a2@t', 'admin', 'Admin Two'); visitor = mkuser('v@t')   # signed in, but NOT staff

tk = {r[1]: r[0] for r in sql("select id, name from tickets order by name")}   # Asha, Ben, Carl (all paid)
A, B, C = tk['Asha'], tk['Ben'], tk['Carl']
def runfile(p): return subprocess.run(["psql", "-h", "/tmp", "-p", "5544", "-q", "-d", "postgres", "-U", "postgres", "-v", "ON_ERROR_STOP=1", "-f", p], capture_output=True, text=True)
def undo(uid, tid, role='authenticated'): return call(role, "select gate_undo_checkin(%s)", (str(tid) if tid else None,), uid=uid)
def admit(uid, tid):
    r = call('authenticated', "select admit_ticket(p_id := %s)", (str(tid),), uid=uid)
    return r[1][0][0]['result'] if r[0] == 'ok' else r[1]
def state(tid): return sql("select checked_in_at, checked_in_by from tickets where id=%s", (str(tid),))[0]
def present(tid): return state(tid)[0] is not None
def clear(tid): sql("update tickets set checked_in_at=null, checked_in_by=null where id=%s", (str(tid),))
def age(tid, secs): sql("update tickets set checked_in_at = now() - make_interval(secs => %s) where id=%s", (secs, str(tid)))
def fresh_in(tid, uid=None):
    """Admit through the real function (so checked_in_by is set the real way) and return True if it worked."""
    clear(tid); return admit(uid or gate1, tid) == 'ok'
def err(r, code): return r[0] == 'err' and code in r[1]
def isvoid(r): return r[0] == 'ok' and r[1][0][0] in ('', None)

# 0. the function itself
t.check("0.1 the file applies (it was applied in the build)", sql("select count(*) from pg_proc where proname='gate_undo_checkin'")[0][0] == 1)
r = runfile(R12); t.check("0.2 the file can be run a second time safely", r.returncode == 0, r.stderr[-300:])
pr = sql("select prosecdef, proconfig, pg_get_function_identity_arguments(oid), prorettype::regtype::text from pg_proc where proname='gate_undo_checkin'")[0]
t.check("0.3 it takes one uuid and returns nothing", pr[2] == 'p_id uuid' and pr[3] == 'void', pr)
t.check("0.4 it runs with the owner's rights and a fixed search path", pr[0] is True and any('search_path=public' in x for x in (pr[1] or [])), pr)
t.check("0.5 execute rights: signed-in users yes, visitors no, nobody via PUBLIC",
        sql("select has_function_privilege('authenticated','gate_undo_checkin(uuid)','execute'), has_function_privilege('anon','gate_undo_checkin(uuid)','execute')")[0] == (True, False)
        and sql("select count(*) from pg_proc p, aclexplode(p.proacl) a where p.proname='gate_undo_checkin' and a.grantee=0")[0][0] == 0)
t.check("0.6 fixtures: three paid tickets, nobody checked in yet", len(tk) == 3 and not any(present(x) for x in (A, B, C)))

# 1. people who may not undo anything
t.check("1.1 setup: a gate person admits Asha through the real function", fresh_in(A))
before = state(A)
t.check("1.2 a visitor (no login) cannot even call it", (lambda r: r[0] == 'err' and 'permission denied' in r[1])(undo(None, A, 'anon')), undo(None, A, 'anon'))
r = undo(visitor, A); t.check("1.3 a signed-in non-staff user: NOT_ALLOWED", err(r, 'NOT_ALLOWED'), r)
r = undo(None, A); t.check("1.4 signed in with no user id at all: NOT_ALLOWED", err(r, 'NOT_ALLOWED'), r)
t.check("1.5 after those refusals Asha is still checked in, unchanged", state(A) == before and present(A))
age(A, 3600); before = state(A)
r = undo(visitor, A); t.check("1.6 a non-staff user is refused for an old check-in too", err(r, 'NOT_ALLOWED'), r)
t.check("1.7 ... and nothing changed", state(A) == before)

# 2. gate staff inside the 2 minutes
t.check("2.1 setup: Asha admitted just now by Gate One", fresh_in(A, gate1) and str(state(A)[1]) == str(gate1))
r = undo(gate1, A); t.check("2.2 the same gate person can undo straight away", isvoid(r), r)
t.check("2.3 the check-in is cleared (time and person)", state(A) == (None, None), state(A))
t.check("2.4 a different gate person can also undo it (any organiser, by design)", fresh_in(A, gate1) and isvoid(undo(gate2, A)) and not present(A))
fresh_in(A); age(A, 60); r = undo(gate1, A); t.check("2.5 one minute later it still works", isvoid(r) and not present(A), r)
fresh_in(A); age(A, 119); r = undo(gate1, A); t.check("2.6 at 119 seconds (just inside) it still works", isvoid(r) and not present(A), r)

# 3. gate staff after the 2 minutes
for i, (secs, label) in enumerate([(121, '121 seconds (just outside)'), (300, '5 minutes'), (3600, '1 hour'), (3 * 86400, '3 days')]):
    fresh_in(A); age(A, secs); before = state(A); r = undo(gate1, A)
    t.check(f"3.{2*i+1} gate person at {label}: UNDO_EXPIRED", err(r, 'UNDO_EXPIRED'), r)
    t.check(f"3.{2*i+2} ... and the check-in at {label} is untouched", state(A) == before and present(A))
fresh_in(A); age(A, 200); r = undo(gate2, A); t.check("3.9 a second gate person is refused too after 2 minutes", err(r, 'UNDO_EXPIRED'), r)

# 4. admins any time
fresh_in(A); age(A, 10); r = undo(admin, A); t.check("4.1 admin, 10 seconds after: works", isvoid(r) and state(A) == (None, None), r)
for i, (secs, label) in enumerate([(121, '121 seconds'), (3600, '1 hour'), (3 * 86400, '3 days')]):
    fresh_in(A); age(A, secs); r = undo(admin, A)
    t.check(f"4.{i+2} admin at {label}: works and clears both columns", isvoid(r) and state(A) == (None, None), r)
fresh_in(A); age(A, 7200); r = undo(admin2, A); t.check("4.5 a second admin also works after 2 hours", isvoid(r) and not present(A), r)

# 5. ids that do not match anything
fresh_in(A); before = state(A); ghost = uuid.uuid4()
r = undo(admin, ghost); t.check("5.1 a wrong id (admin): UNDO_EXPIRED (the one error used for 'nothing to undo')", err(r, 'UNDO_EXPIRED'), r)
r = undo(gate1, ghost); t.check("5.2 a wrong id (gate): UNDO_EXPIRED", err(r, 'UNDO_EXPIRED'), r)
r = undo(admin, None); t.check("5.3 an empty id (admin): UNDO_EXPIRED", err(r, 'UNDO_EXPIRED'), r)
r = undo(gate1, None); t.check("5.4 an empty id (gate): UNDO_EXPIRED", err(r, 'UNDO_EXPIRED'), r)
t.check("5.5 wrong ids changed nothing", state(A) == before and present(A))
clear(B)
r = undo(admin, B); t.check("5.6 a ticket that was never admitted (admin): UNDO_EXPIRED", err(r, 'UNDO_EXPIRED'), r)
r = undo(gate1, B); t.check("5.7 a ticket that was never admitted (gate): UNDO_EXPIRED", err(r, 'UNDO_EXPIRED'), r)
t.check("5.8 and it is still not admitted (no invented check-in)", not present(B))
r = call('authenticated', "select gate_undo_checkin('not-a-uuid')", uid=admin); t.check("5.9 text that is not an id is refused", r[0] == 'err')

# 6. only the right ticket, only the two columns
for x in (A, B, C): fresh_in(x)
age(A, 30); age(B, 30); age(C, 30); rows_before = {x: state(x) for x in (A, B, C)}
others_before = sql("select id, to_jsonb(t) - 'checked_in_at' - 'checked_in_by' from tickets t order by id")
r = undo(gate1, B); t.check("6.1 gate undoes Ben only", isvoid(r) and not present(B))
t.check("6.2 Asha and Carl are still checked in, same time and same person", state(A) == rows_before[A] and state(C) == rows_before[C])
t.check("6.3 nothing else on any ticket changed (name, numbers, secret, kind ...)", sql("select id, to_jsonb(t) - 'checked_in_at' - 'checked_in_by' from tickets t order by id") == others_before)
age(C, 500); r = undo(admin, C)
t.check("6.4 admin undoes Carl only", isvoid(r) and not present(C) and state(A) == rows_before[A])
t.check("6.5 an undo writes no booking or money changes", sql("select count(*) from bookings where status <> 'paid'")[0][0] == 0)

# 7. the older admin-only undo was not loosened
for x in (A,): fresh_in(x)
r = call('authenticated', "select undo_checkin(p_id := %s)", (str(A),), uid=gate1)
t.check("7.1 a gate person still cannot use the old undo_checkin", err(r, 'NOT_ALLOWED') and present(A), r)
t.check("7.2 a visitor still cannot call the old undo_checkin", call('anon', "select undo_checkin(p_id := %s)", (str(A),))[0] == 'err' and present(A))

# 8. undo, admit again, and the window starts again
fresh_in(A); age(A, 400); r = undo(gate1, A)
t.check("8.1 setup: after 400 seconds the gate person is refused", err(r, 'UNDO_EXPIRED') and present(A))
t.check("8.2 an admin undoes it", isvoid(undo(admin, A)) and not present(A))
t.check("8.3 the ticket can be admitted again normally", admit(gate1, A) == 'ok' and present(A))
t.check("8.4 the new admission has its own fresh 2 minutes (gate can undo again)", isvoid(undo(gate1, A)) and not present(A))
t.check("8.5 admitting the same ticket twice shows already_scanned, and an undo then lets it in again", admit(gate1, A) == 'ok' and admit(gate2, A) == 'already_scanned' and isvoid(undo(gate1, A)) and admit(gate2, A) == 'ok')

# 9. two undos at the same instant
fresh_in(A); age(A, 20)
res = par([lambda: call_new('authenticated', "select gate_undo_checkin(%s)", (str(A),), uid=gate1),
           lambda: call_new('authenticated', "select gate_undo_checkin(%s)", (str(A),), uid=gate2)])
oks = sum(1 for x in res if x[0] == 'ok'); exp = sum(1 for x in res if err(x, 'UNDO_EXPIRED'))
t.check("9.1 two simultaneous undos: exactly one works and the other says UNDO_EXPIRED", oks == 1 and exp == 1, res)
t.check("9.2 ... and the ticket ends not admitted", not present(A))
t.report("test_r2_12: gate_undo_checkin")
