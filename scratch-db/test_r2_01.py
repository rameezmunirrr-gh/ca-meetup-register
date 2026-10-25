from lib import *
import json, uuid
fresh(['/home/claude/scratch/r2_01_prep.sql'])
S = seed(); admin = S['admin']
t = T()
def booking(people, tag='x'):
    sid = uuid.uuid4(); path = f'{sid}.jpg'
    sql("insert into storage.objects values ('payment-proofs', %s)", (path,))
    return call('anon', "select submit_booking(%s,%s::jsonb,%s)", (str(sid), json.dumps(people), path))
def person(**kw):
    d = dict(name='Test', phone='9111111111', email='t@example.com', loc='In Bengaluru', att='Surely', food='Veg'); d.update(kw); return d

# --- seed worked with emails; stored lower-case
rows = sql("select t.name, e.email from tickets t left join ticket_emails e on e.ticket_id = t.id order by t.created_at, t.name")
t.check("seed stores emails (lower-cased, trimmed)", all(r[1] and r[1]==r[1].lower() for r in rows), rows)
r = booking([person(name='Zed', email='  Zed.Test@Example.COM ')])
t.check("valid email accepted", r[0]=='ok', r)
em = sql("select e.email from tickets t join ticket_emails e on e.ticket_id = t.id where t.name='Zed'")[0][0]
t.check("email stored trimmed and lower-case", em=='zed.test@example.com', em)

# --- email validation
bad = ['', None, 'abc', 'a@b', 'a b@c.com', '@x.com', 'x@.com', 'x@y.', 'a@b@c.com', 'x'*120+'@y.com']
for e in bad:
    p = person(); 
    if e is None: p.pop('email')
    else: p['email'] = e
    r = booking([p])
    t.check(f"bad email refused: {str(e)[:22]!r}", r[0]=='err' and 'INVALID_EMAIL' in r[1], r)
# one bad person in a group blocks the whole group
r = booking([person(), person(name='Two', email='nope')])
t.check("one bad email in a group refuses the whole booking", r[0]=='err' and 'INVALID_EMAIL' in r[1], r)
n = sql("select count(*) from bookings")[0][0]
t.check("refused submissions leave no booking behind", n==3, n)

# --- phone stays strictly 10 digits (+91 is display only)
for ph in ['+919111111111', '09111111111', '911111111', '91111111111', '91111 11111', 'abcdefghij']:
    r = booking([person(phone=ph)])
    t.check(f"phone refused: {ph}", r[0]=='err' and 'INVALID_PHONE' in r[1], r)

# --- counting: transferred-out tickets do not count
st = lambda: call('anon', "select get_public_status(null)")[1][0][0]['spots_left']
used0 = sql("select count(*) from tickets")[0][0]
t.check("spots_left = cap - people", st()==150-used0, (st(), used0))
tid = sql("select id from tickets order by created_at limit 1")[0][0]
sql("update tickets set transferred_out_at = now() where id=%s", (str(tid),))
t.check("a transferred-out ticket frees its spot in the public count", st()==150-used0+1, st())
# cap enforcement uses the same rule
sql("update settings set cap=%s", (used0,))   # exactly full counting the cancelled one -> one free
r = booking([person(name='Fits')])
t.check("with cap full, a new person fits because one ticket was transferred out", r[0]=='ok', r)
r = booking([person(name='Overflow')])
t.check("and the next person is refused (cap is full again)", r[0]=='err' and 'NOT_ENOUGH_SPOTS' in r[1], r)
sql("update tickets set transferred_out_at = null where id=%s", (str(tid),))
sql("update settings set cap=150")

# --- booking kind
k = sql("select kind, count(*) from bookings group by kind")
t.check("all bookings are 'registration' by default", k==[('registration', sql("select count(*) from bookings")[0][0])], k)
r = call('postgres', "update bookings set kind='weird' where false or id=(select id from bookings limit 1)")
t.check("booking kind must be registration or transfer", r[0]=='err', r)
r = call('postgres', "update bookings set kind='transfer' where id=(select id from bookings limit 1)")
t.check("booking kind 'transfer' is allowed", r[0]=='ok', r)
sql("update bookings set kind='registration'")

# --- settings constraints and defaults
d = sql("select max_resale_price, transfer_cutoff_at, transfer_food_locked, private_code_hours from settings")[0]
t.check("setting defaults (old max price 250, no cutoff, food unlocked, codes last 2h)", d==(250,None,False,2), d)
for sqlx, nm in [("update settings set private_code_hours=0","code hours 0"), ("update settings set private_code_hours=169","code hours 169")]:
    r = call('postgres', sqlx); t.check(f"setting refused: {nm}", r[0]=='err', r)
r = call('postgres', "update settings set transfer_cutoff_at=now()+interval '5 days', transfer_food_locked=true, private_code_hours=168")
t.check("valid new settings accepted", r[0]=='ok', r)
n = sql("select count(*) from settings_log where field in ('transfer_cutoff_at','transfer_food_locked','private_code_hours')")[0][0]
t.check("every new setting change is written to the settings log", n==3, n)
sql("update settings set transfer_cutoff_at=null, transfer_food_locked=false, private_code_hours=2")


# --- email privacy: emails live in their OWN admin-only table (G3)
gate = uuid.uuid4(); sql("insert into auth.users (id,email) values (%s,'gate@test')", (str(gate),)); sql("insert into staff (user_id,name,role) values (%s,'Gate One','gate')", (str(gate),))
cols_t = [r[0] for r in sql("select column_name from information_schema.columns where table_name='tickets' and table_schema='public'")]
t.check("P1 the tickets table itself has NO email column", 'email' not in cols_t, cols_t)
nt_, ne_ = sql("select (select count(*) from tickets), (select count(*) from ticket_emails)")[0]
t.check("P2 every ticket made at registration has exactly one email row", nt_==ne_, (nt_, ne_))
t.check("P3 each email row belongs to a different ticket (one per person)", sql("select count(distinct ticket_id) from ticket_emails")[0][0]==ne_)
r = call('anon', "select * from ticket_emails limit 1"); t.check("P4 anonymous visitors cannot read ticket_emails", r[0]=='err', r)
r = call('authenticated', "select count(*) from ticket_emails", uid=gate)
t.check("P5 gate staff see ZERO email rows", r[0]=='ok' and r[1][0][0]==0, r)
r = call('authenticated', "select count(*) from tickets", uid=gate)
t.check("P6 gate staff can still read tickets (gate page keeps working)", r[0]=='ok' and r[1][0][0]==nt_, r)
r = call('authenticated', "select count(*) from ticket_emails", uid=admin)
t.check("P7 admins can read every email", r[0]=='ok' and r[1][0][0]==ne_, r)
r = call('authenticated', "select count(*) from report where email is not null", uid=gate)
t.check("P8 the report view shows NO emails to gate staff", r[0]=='ok' and r[1][0][0]==0, r)
r = call('authenticated', "select count(*) from report where email is not null", uid=admin)
t.check("P9 the report view shows emails to admins", r[0]=='ok' and r[1][0][0]==ne_, r)
for stmt, nm in [("insert into ticket_emails (ticket_id, email) select id, 'x@y.com' from tickets limit 1", "insert"),
                 ("update ticket_emails set email='x@y.com'", "update"), ("delete from ticket_emails", "delete")]:
    for who, uid in (('authenticated', admin), ('authenticated', gate), ('anon', None)):
        r = call(who, stmt, uid=uid)
        ok = r[0]=='err' or (r[0]=='ok' and not r[1])
        t.check(f"P10 nobody can {nm} ticket_emails directly ({'admin' if uid==admin else 'gate' if uid==gate else 'anon'})", r[0]=='err', r)
nb = sql("select count(*) from ticket_emails")[0][0]
r = booking([person(name='Bad Mail', email='nope')])
t.check("P11 a refused booking leaves no email row behind", r[0]=='err' and sql("select count(*) from ticket_emails")[0][0]==nb)
r = booking([person(name='G1', email='G1@Example.com'), person(name='G2', email=' g2@example.com ')])
em = sql("select t.name, e.email from tickets t join ticket_emails e on e.ticket_id=t.id where t.name in ('G1','G2') order by t.name")
t.check("P12 a group stores each person's own email, trimmed and lower-case, on the right person", em==[('G1','g1@example.com'),('G2','g2@example.com')], em)
sql("delete from tickets where name='G1'")
t.check("P13 deleting a ticket also removes its email (clean-up before launch stays simple)", sql("select count(*) from ticket_emails e where not exists (select 1 from tickets t where t.id=e.ticket_id)")[0][0]==0
        and sql("select count(*) from ticket_emails where email='g1@example.com'")[0][0]==0)
r = call('postgres', "insert into ticket_emails (ticket_id, email) select id, 'bad' from tickets limit 1 on conflict do nothing")
t.check("P14 the table itself refuses a malformed email (even if a function had a bug)", r[0]=='err', r)

# --- report view
cols = [r[0] for r in sql("select column_name from information_schema.columns where table_name='report' and table_schema='public' order by ordinal_position")]
t.check("report view ends with email, transferred_out_at, booking_kind", cols[-3:]==['email','transferred_out_at','booking_kind'], cols[-4:])
t.check("report view keeps all old columns first", cols[:4]==['sl_no','name','phone','location'] and 'ticket_label' in cols, cols)
r = call('anon', "select * from report limit 1"); t.check("anonymous visitors cannot read the report", r[0]=='err', r)
opt = sql("select reloptions from pg_class where relname='report' and relnamespace='public'::regnamespace")[0][0]
t.check("report view is still security_invoker (so it follows the caller's row security)", opt is not None and 'security_invoker=true' in opt, opt)

# --- regression: numbering still works
nums = [r[0] for r in sql("select ticket_no from tickets where ticket_no is not null order by ticket_no")]
t.check("tickets were numbered 1..n when marked paid (numbering unchanged)", nums==list(range(1,len(nums)+1)) and len(nums)==3, nums)
# unaffected anon surfaces still reachable
r = call('anon', "select get_public_status(null)"); t.check("public status still works", r[0]=='ok', r)
r = call('anon', "select lookup_booking(%s)", (S['A'],)); t.check("old booking lookup still works (replaced in a later piece)", r[0]=='ok', r)
t.report("R2-1 piece 1 tests")
