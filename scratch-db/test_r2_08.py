from lib import *
import json, uuid, subprocess, sys
BASE = ['r2_01_prep.sql','r2_02_lookup.sql','r2_02c_close_old_transfer_doors.sql','r2_02b_cutover.sql','r2_03_private_transfer.sql','r2_04_public_via_code.sql','r2_05_cleanup_and_ip.sql','r2_06_transfer_settings.sql']
D = '/home/claude/ca-meetup-register/scratch-db/'; import os
R8 = os.environ.get('R8','/home/claude/ca-meetup-register/sql/r2_08_coordinator_transfer.sql')
UPI = 'asha@okbank'
t = T()
def A_(q, p=(), uid=None, role='anon'):
    r = call(role, q, p, uid=uid)
    return r[1][0][0] if r[0]=='ok' and r[1] else (('ERR', r[1]) if r[0]=='err' else None)
def adm(fn, *a, uid=None, role='authenticated'):
    ph = ','.join(['%s']*len(a)); return call(role, f"select {fn}({ph})", a, uid=uid)
def err(r, w): return r[0]=='err' and w in r[1]
def buyer(**kw):
    d = dict(name='Dan Buyer', phone='9000000004', email='Dan@Example.com', loc='In Bengaluru', att='Surely', food='Veg', consent='true'); d.update(kw); return d
def tsubmit(code, b=None): return A_("select transfer_submit(%s,%s,%s::jsonb)", (code, str(uuid.uuid4()), json.dumps(b or buyer())))
def make_coord(S, phone):
    tid_ = str(sql("select id from tickets where phone=%s",(phone,))[0][0]); return adm('set_coordinator', tid_, True, uid=S['admin'])
def tkid(phone): return str(sql("select id from tickets where phone=%s",(phone,))[0][0])
def xid(phone): return str(sql("select id from transfers where ticket_id=%s order by created_at desc limit 1",(tkid(phone),))[0][0])
def setup(with_r8=True):
    fresh([D+f for f in BASE] + ([R8] if with_r8 else []))
    S = seed(); sql("update settings set transfers_open=true, price_per_head=250")
    for nm, role, k in [('gate','gate','Gate One'),('admin2','admin','Admin Two')]:
        u = uuid.uuid4(); sql("insert into auth.users (id,email) values (%s,%s)", (str(u), nm+'@test')); sql("insert into staff (user_id,name,role) values (%s,%s,%s)", (str(u), k, role)); S[nm] = u
    return S
def live(): return sql("select count(*) from tickets t join bookings b on b.id=t.booking_id where b.status='paid' and t.transferred_out_at is null")[0][0]

# ---------- the old behaviour is really there without piece 8 (so the test can tell the difference)
S = setup(with_r8=False); make_coord(S,'9000000003')
r = A_("select private_sell(%s,'E26-001C','9000000003')", (S['B'],))
t.check("0.1 WITHOUT piece 8 a coordinator is refused (COORDINATOR): the test can see the difference", r.get('error')=='COORDINATOR', r)

# ---------- private transfer of a coordinator ticket
print("-- private transfer by a coordinator")
S = setup(); A, B, admin, gate = S['A'], S['B'], S['admin'], S['gate']
r = make_coord(S,'9000000003'); lab = r[1][0][0]['label']
t.check("1.0 setup: the label shown for Carl is a coordinator label", lab.endswith('C'), lab)
row = sql("select kind, ticket_no, coord_no, secret, orig_secret from tickets where phone='9000000003'")[0]
t.check("1.1 Carl is a coordinator with coordinator no. 1 and a guest number kept on record", row[0]=='coordinator' and row[2]==1 and row[1]==3, row)
csecret, gsecret = row[3], row[4]
before = live()
r = A_("select private_sell(%s,'E26-001C','9000000003')", (B,))
t.check("1.2 the coordinator gets a code (no COORDINATOR refusal)", r.get('ok') is True and len(r['code'])==6, r)
t.check("1.2b the coordinator's old guest label (E26-003) is not accepted: only the current coordinator label", A_("select private_sell(%s,'E26-003','9000000003')", (B,))=={'ok':False,'error':'MISMATCH'})
code = r['code']; sb = tsubmit(code); x = xid('9000000003')
t.check("1.3 the buyer can apply with that code", sb.get('ok') is True, sb)
t.check("1.4 approve without the call tick still refused", err(adm('admin_transfer_approve', x, uid=admin),'CALL_NOT_CONFIRMED'))
adm('admin_transfer_confirm_call', x, True, uid=admin)
ap = adm('admin_transfer_approve', x, uid=admin); t.check("1.5 the admin can approve the transfer", ap[0]=='ok', ap)
old = sql("select transferred_out_at is not null, kind, coord_no, ticket_no from tickets where phone='9000000003'")[0]
new = sql("select kind, ticket_no, coord_no, transferred_from, name from tickets where phone='9000000004'")[0]
t.check("1.6 the coordinator's ticket is retired and keeps both numbers on record", old[0] and old[1]=='coordinator' and old[2]==1 and old[3]==3, old)
t.check("1.7 the buyer is a normal GUEST with a NEW guest number, never a coordinator", new[0]=='guest' and new[1] is not None and new[1]!=3 and new[2] is None and new[4]=='Dan Buyer', new)
t.check("1.8 the number of live paid tickets is unchanged (one out, one in)", live()==before, (before, live()))
t.check("1.9 the buyer's email is in the admin-only table", sql("select email from ticket_emails where ticket_id=(select id from tickets where phone='9000000004')")[0][0]=='dan@example.com')
gres = lambda *a: A_("select admit_ticket(%s,%s,%s,%s,%s)", a, uid=gate, role='authenticated')
r = gres(1, csecret, False, True, None)
t.check("1.10 gate: the old COORDINATOR QR is cancelled and names the buyer's new ticket", r['result']=='cancelled' and r['name']=='Dan Buyer' and r['old_label']=='E26-001C', r)
r = gres(3, gsecret, False, False, None)
t.check("1.11 gate: the coordinator's cancelled guest QR is cancelled too", r['result']=='cancelled' and r['name']=='Dan Buyer', r)
r = gres(None, None, False, False, tkid('9000000003'))
t.check("1.12 gate: searching the old coordinator by name never admits", r['result']=='cancelled', r)
r = gres(new[1], sql("select secret from tickets where phone='9000000004'")[0][0], False, False, None)
t.check("1.13 gate: the buyer's new ticket admits normally", r['result']=='ok', r)
t.check("1.14 an admin cannot MAKE a coordinator of a retired ticket", err(adm('set_coordinator', tkid('9000000003'), True, uid=admin),'ALREADY_TRANSFERRED'))
t.check("1.15 an admin cannot REMOVE the coordinator status of a retired ticket", err(adm('set_coordinator', tkid('9000000003'), False, uid=admin),'ALREADY_TRANSFERRED'))
t.check("1.16 the retired coordinator can not sell again", A_("select private_sell(%s,'E26-001C','9000000003')", (B,)).get('error')=='ALREADY_TRANSFERRED')
t.check("1.17 coordinator numbers are never reused: the next new coordinator gets 2",
        make_coord(S,'9000000001')[0]=='ok' and sql("select coord_no from tickets where phone='9000000001'")[0][0]==2)

# ---------- other rules still hold for coordinators
print("-- the other rules still apply")
sql("update tickets set checked_in_at=now() where phone='9000000001'")
r = A_("select private_sell(%s,'E26-002C','9000000001')", (A,)); t.check("2.1 a coordinator already inside the hall: ALREADY_CHECKED_IN", r.get('error')=='ALREADY_CHECKED_IN', r)
sql("update tickets set checked_in_at=null where phone='9000000001'")
sql("update bookings set status='pending' where booking_code=%s",(A,)); r = A_("select private_sell(%s,'E26-002C','9000000001')", (A,))
t.check("2.2 a coordinator whose booking is not confirmed: NOT_CONFIRMED", r.get('error')=='NOT_CONFIRMED', r)
sql("update bookings set status='paid' where booking_code=%s",(A,))
t.check("2.3 wrong phone / wrong number for a coordinator: MISMATCH", A_("select private_sell(%s,'E26-002C','9000000002')", (A,))=={'ok':False,'error':'MISMATCH'} and A_("select private_sell(%s,'E26-009C','9000000001')", (A,))=={'ok':False,'error':'MISMATCH'})
# a coordinator that never had a guest number
sql("update tickets set ticket_no=null where phone='9000000001'")
r = A_("select private_sell(%s,'E26-002C','9000000001')", (A,)); t.check("2.4 a coordinator with no guest number can still sell (coordinator number is enough)", r.get('ok') is True, r)
x = xid('9000000001'); tsubmit(r['code'], buyer(name='Eve Buyer', phone='9000000005'))
adm('admin_transfer_confirm_call', x, True, uid=admin); ap = adm('admin_transfer_approve', x, uid=admin)
t.check("2.5 ...and the admin can complete it", ap[0]=='ok', ap)
n = sql("select kind, ticket_no from tickets where phone='9000000005'")[0]
t.check("2.6 the buyer gets a normal guest number", n[0]=='guest' and n[1] is not None, n)
nums = sql("select ticket_no from tickets where ticket_no is not null"); t.check("2.7 every guest number is unique", len(nums)==len(set(nums)), nums)

# defence in depth: the admin's final check still refuses a seat that has lost its number while the transfer waited
rb = A_("select private_sell(%s,'E26-002','9000000002')", (A,))
if rb.get('ok'):
    xb = xid('9000000002'); tsubmit(rb['code'], buyer(name='Fay Buyer', phone='9000000006'))
    adm('admin_transfer_confirm_call', xb, True, uid=admin); sql("update tickets set ticket_no=null where phone='9000000002'")
    t.check("2.8 a seat with no number at all is refused at the final check (SELLER_TICKET_INVALID)", err(adm('admin_transfer_approve', xb, uid=admin),'SELLER_TICKET_INVALID'))
else: t.check("2.8 setup for the no-number check", False, rb)

# ---------- public transfer of a coordinator ticket
print("-- public transfer by a coordinator")
S = setup(); A, B, admin = S['A'], S['B'], S['admin']; make_coord(S,'9000000002')
r = A_("select public_sell(%s,'E26-001C','9000000002',%s)", (A, UPI)); t.check("3.1 the coordinator gets a PUBLIC code", r.get('ok') is True and r['mode']=='public', r)
x = xid('9000000002'); sb = tsubmit(r['code']); bc = sb['booking_code']
adm('admin_transfer_confirm_call', x, True, uid=admin); adm('admin_transfer_request_payment', x, uid=admin)
sid = uuid.uuid4(); path = f'{sid}.jpg'; sql("insert into storage.objects values ('payment-proofs',%s)",(path,))
A_("select transfer_pay(%s,%s,%s,%s)", (bc,'9000000004',str(sid),path))
t.check("3.2 transfer is refused before the money is verified", err(adm('admin_transfer_approve', x, uid=admin),'PAYMENT'), adm('admin_transfer_approve', x, uid=admin))
adm('admin_transfer_verify_payment', x, 250, uid=admin); ap = adm('admin_transfer_approve', x, uid=admin)
t.check("3.3 after the money is verified the admin can transfer", ap[0]=='ok', ap)
t.check("3.4 the buyer is a guest, the payout is now owed to the seller", sql("select kind from tickets where phone='9000000004'")[0][0]=='guest' and sql("select count(*) from transfers where status='done' and seller_paid_at is null")[0][0]==1)
m = A_("select admin_transfer_money()", uid=admin, role='authenticated'); t.check("3.5 the money panel still works", m is not None and not (isinstance(m,tuple) and m[0]=='ERR'), m)

# ---------- running the piece twice, and who may call what
print("-- safety")
rr = subprocess.run(["psql","-h","/tmp","-p","5544","-q","-d","postgres","-U","postgres","-v","ON_ERROR_STOP=1","-f",R8],capture_output=True,text=True)
t.check("4.1 piece 8 can be run twice safely", rr.returncode==0, rr.stderr[-300:])
acl = dict(sql("select p.proname, p.proacl::text from pg_proc p where p.pronamespace='public'::regnamespace and p.proname in ('private_sell','public_sell','admin_transfer_approve','set_coordinator')"))
t.check("4.2 who may run the four functions is exactly as before (visitor functions: anon+authenticated; admin functions: authenticated only)",
        all('anon' in acl[f] and 'authenticated' in acl[f] for f in ('private_sell','public_sell')) and
        all('anon' not in acl[f] and 'authenticated' in acl[f] for f in ('admin_transfer_approve','set_coordinator')) and
        all(not v.startswith('{=X') and ',=X' not in v for v in acl.values()), acl)
t.check("4.3 anonymous visitors still cannot call set_coordinator or admin_transfer_approve", all(call('anon', f"select {f}", (str(uuid.uuid4()),)+((True,) if f.startswith('set') else ()))[0]=='err' for f in ['admin_transfer_approve(%s)','set_coordinator(%s,%s)']))
t.report("test_r2_08: coordinators can transfer tickets")
