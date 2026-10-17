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
rows = sql("select name, email from tickets order by created_at, name")
t.check("seed stores emails (lower-cased, trimmed)", all(r[1] and r[1]==r[1].lower() for r in rows), rows)
r = booking([person(name='Zed', email='  Zed.Test@Example.COM ')])
t.check("valid email accepted", r[0]=='ok', r)
em = sql("select email from tickets where name='Zed'")[0][0]
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
d = sql("select resale_min_price, max_resale_price, transfer_cutoff_at, transfer_food_locked, private_code_hours, reservation_minutes from settings")[0]
t.check("setting defaults (min 0, max 250, no cutoff, food unlocked, 2h, 30min)", d==(0,250,None,False,2,30), d)
for sqlx, nm in [("update settings set resale_min_price=300","min above max"), ("update settings set resale_min_price=-1","negative min"),
                 ("update settings set private_code_hours=0","code hours 0"), ("update settings set private_code_hours=25","code hours 25"),
                 ("update settings set reservation_minutes=4","reservation 4"), ("update settings set reservation_minutes=121","reservation 121")]:
    r = call('postgres', sqlx); t.check(f"setting refused: {nm}", r[0]=='err', r)
r = call('postgres', "update settings set resale_min_price=50, transfer_cutoff_at=now()+interval '5 days', transfer_food_locked=true, private_code_hours=3, reservation_minutes=20")
t.check("valid new settings accepted", r[0]=='ok', r)
n = sql("select count(*) from settings_log where field in ('resale_min_price','transfer_cutoff_at','transfer_food_locked','private_code_hours','reservation_minutes')")[0][0]
t.check("every new setting change is written to the settings log", n==5, n)
sql("update settings set resale_min_price=0, transfer_cutoff_at=null, transfer_food_locked=false, private_code_hours=2, reservation_minutes=30")

# --- report view
cols = [r[0] for r in sql("select column_name from information_schema.columns where table_name='report' and table_schema='public' order by ordinal_position")]
t.check("report view ends with email, transferred_out_at, booking_kind", cols[-3:]==['email','transferred_out_at','booking_kind'], cols[-4:])
t.check("report view keeps all old columns first", cols[:4]==['sl_no','name','phone','location'] and 'ticket_label' in cols, cols)
r = call('anon', "select * from report limit 1"); t.check("anonymous visitors cannot read the report", r[0]=='err', r)

# --- regression: numbering still works
nums = [r[0] for r in sql("select ticket_no from tickets where ticket_no is not null order by ticket_no")]
t.check("tickets were numbered 1..n when marked paid (numbering unchanged)", nums==list(range(1,len(nums)+1)) and len(nums)==3, nums)
# unaffected anon surfaces still reachable
r = call('anon', "select get_public_status(null)"); t.check("public status still works", r[0]=='ok', r)
r = call('anon', "select lookup_booking(%s)", (S['A'],)); t.check("old booking lookup still works (replaced in a later piece)", r[0]=='ok', r)
t.report("R2-1 piece 1 tests")
