from lib import *
import json, uuid, subprocess, re
F = ['r2_01_prep.sql','r2_02_lookup.sql','r2_02c_close_old_transfer_doors.sql','r2_02b_cutover.sql','r2_03_private_transfer.sql','r2_04_public_via_code.sql']
FILES = ['/home/claude/scratch/'+f for f in F]
ALPHA = set('ABCDEFGHJKLMNPQRSTUVWXYZ23456789')
UPI = 'asha@okbank'
t = T()
def setup():
    fresh(FILES); S = seed()
    sql("update settings set transfers_open=true, price_per_head=250")
    for nm, role, k in [('gate','gate','Gate One'),('admin2','admin','Admin Two')]:
        u = uuid.uuid4(); sql("insert into auth.users (id,email) values (%s,%s)", (str(u), nm+'@test')); sql("insert into staff (user_id,name,role) values (%s,%s,%s)", (str(u), k, role)); S[nm] = u
    return S
def A_(q, p=(), uid=None, role='anon'):
    r = call(role, q, p, uid=uid)
    return r[1][0][0] if r[0]=='ok' and r[1] else (('ERR', r[1]) if r[0]=='err' else None)
def label(n): return 'E26-%03d' % n
def psell(code, lab, phone, upi=UPI): return A_("select public_sell(%s,%s,%s,%s)", (code, lab, phone, upi))
def vsell(code, lab, phone): return A_("select private_sell(%s,%s,%s)", (code, lab, phone))
def tid(no): return str(sql("select id from transfers where ticket_id=(select id from tickets where ticket_no=%s) order by created_at desc limit 1",(no,))[0][0])
def buyer(**kw):
    d = dict(name='Dan Buyer', phone='9000000004', email='Dan@Example.com', loc='In Bengaluru', att='Surely', food='Veg', consent='true'); d.update(kw); return d
def tsubmit(code, b=None, sid=None): return A_("select transfer_submit(%s,%s,%s::jsonb)", (code, str(sid or uuid.uuid4()), json.dumps(b or buyer())))
def adm(fn, *a, uid=None, role='authenticated'):
    ph = ','.join(['%s']*len(a)); return call(role, f"select {fn}({ph})", a, uid=uid)
def ok(r): return r[0]=='ok'
def err(r, w): return r[0]=='err' and w in r[1]
def shot(sid): p=f'{sid}.jpg'; sql("insert into storage.objects values ('payment-proofs',%s)",(p,)); return p
def pay(booking, phone, sid=None, path='auto'):
    sid = sid or uuid.uuid4(); path = shot(sid) if path=='auto' else path
    return A_("select transfer_pay(%s,%s,%s,%s)", (booking, phone, str(sid), path))
def lk(code, phone): return A_("select lookup_tickets(%s,%s)", (code, phone))
def money(S): return A_("select admin_transfer_money()", uid=S['admin'], role='authenticated')
def counts():
    return sql("""select (select count(*) from tickets t join bookings b on b.id=t.booking_id where b.status<>'rejected' and t.transferred_out_at is null),
      (select count(*) from tickets t join bookings b on b.id=t.booking_id where b.status='paid' and t.transferred_out_at is null),
      (select count(*) from tickets t join bookings b on b.id=t.booking_id where b.status='pending' and t.transferred_out_at is null),
      (select coalesce(sum(amount_expected),0) from bookings where status='paid'),
      (select count(*) from bookings where kind='registration')""")[0]
def pubflow(S, book, no, phone, stage='verified', amount=250, upi=UPI, **bkw):
    """seller makes a public code, buyer submits, admin ticks call; stage: submitted | call | requested | paid | verified"""
    r = psell(book, label(no), phone, upi=upi); code = r['code']; x = tid(no)
    sb = tsubmit(code, buyer(**bkw)); bcode = sb['booking_code']; bphone = bkw.get('phone', '9000000004')
    out = dict(code=code, x=x, b=bcode, bphone=bphone)
    if stage=='submitted': return out
    adm('admin_transfer_confirm_call', x, True, uid=S['admin'])
    if stage=='call': return out
    adm('admin_transfer_request_payment', x, uid=S['admin'])
    if stage=='requested': return out
    pay(bcode, bphone)
    if stage=='paid': return out
    adm('admin_transfer_verify_payment', x, amount, uid=S['admin']); return out

# ================= GROUP 1: public_sell =================
S = setup(); A, B, admin, gate = S['A'], S['B'], S['admin'], S['gate']
print("-- group 1: the seller makes a public code")
r = psell(A, label(1), '9000000001')
t.check("1.1 right details give a 6-character code, mode public, 2 hours", r.get('ok') and r['mode']=='public' and len(r['code'])==6 and set(r['code'])<=ALPHA and r['hours']==2, r)
row = sql("select kind, status, seller_upi, code_expires_at - created_at from transfers")[0]
t.check("1.2 stored as a public code with the payout UPI ID", row[:3]==('public','code_active',UPI) and abs(row[3].total_seconds()-7200)<5, row)
bad = [('ABCD1234',label(1),'9000000001'),(A,label(9),'9000000001'),(A,label(1),'9555555555'),(A,label(1),'9000000002'),(B,label(1),'9000000001'),(None,label(1),'9000000001'),(A,label(1),None),(A,"1' or '1'='1",'9000000001')]
res = [psell(*x) for x in bad]
t.check("1.3 every wrong detail gives exactly MISMATCH", all(x=={'ok':False,'error':'MISMATCH'} for x in res), res)
n = sql("select count(*) from transfers")[0][0]; psell(A,label(1),'9555555555'); t.check("1.4 a failed attempt creates nothing", sql("select count(*) from transfers")[0][0]==n)
for u in ['', 'abc', 'a@b', '9876543', 'x y@bank', '<script>@bank', 'a'*70+'@okbank', 'abc@1bank', None]:
    t.check(f"1.5 invalid payout UPI refused: {str(u)[:16]!r}", psell(B,label(3),'9000000003',upi=u).get('error')=='INVALID_UPI')
t.check("1.6 nothing created by those refusals", sql("select count(*) from transfers where seller_name='Carl'")[0][0]==0)
for u in ['9876543210','first.last-1@ybl','name@okhdfc']:
    r = psell(B,label(3),'9000000003',upi=u); t.check(f"1.7 valid payout ID accepted: {u}", r.get('ok') is True, r); sql("update transfers set status='withdrawn' where seller_name='Carl'")
sql("update bookings set status='pending' where booking_code=%s",(B,)); t.check("1.8 unconfirmed booking: NOT_CONFIRMED", psell(B,label(3),'9000000003').get('error')=='NOT_CONFIRMED'); sql("update bookings set status='paid' where booking_code=%s",(B,))
sql("update tickets set checked_in_at=now() where ticket_no=3"); t.check("1.9 checked in: ALREADY_CHECKED_IN", psell(B,label(3),'9000000003').get('error')=='ALREADY_CHECKED_IN'); sql("update tickets set checked_in_at=null where ticket_no=3")
sql("update tickets set kind='coordinator', coord_no=1 where ticket_no=3"); t.check("1.10 coordinator: COORDINATOR", psell(B,'1C','9000000003').get('error')=='COORDINATOR'); sql("update tickets set kind='guest', coord_no=null where ticket_no=3")
sql("update tickets set transferred_out_at=now() where ticket_no=3"); t.check("1.11 already transferred: ALREADY_TRANSFERRED", psell(B,label(3),'9000000003').get('error')=='ALREADY_TRANSFERRED'); sql("update tickets set transferred_out_at=null where ticket_no=3")
t.check("1.12 those problems are not revealed to people with wrong details", psell(B,label(3),'9555555555')=={'ok':False,'error':'MISMATCH'})
sql("update settings set transfers_open=false"); t.check("1.13 transfers off: TRANSFERS_CLOSED", psell(B,label(3),'9000000003').get('error')=='TRANSFERS_CLOSED')
sql("update settings set transfers_open=true, transfer_cutoff_at=now()-interval '1 minute'"); t.check("1.14 after the cut-off: CUTOFF_PASSED", psell(B,label(3),'9000000003').get('error')=='CUTOFF_PASSED'); sql("update settings set transfer_cutoff_at=null")
first = sql("select code from transfers where status='code_active' and seller_name='Asha'")[0][0]; r2 = psell(A, label(1), '9000000001')
t.check("1.15 a second request makes a NEW code; the old one stops working", r2.get('ok') and r2['code']!=first and A_("select transfer_open(%s)",(first,))=={'ok':False,'error':'INVALID_CODE'})
r3 = vsell(A, label(1), '9000000001'); t.check("1.16 a PRIVATE code for the same seat replaces the public one (and the reverse)", r3.get('ok') and sql("select count(*) from transfers where status='code_active' and ticket_id=(select id from tickets where ticket_no=1)")[0][0]==1 and psell(A,label(1),'9000000001').get('ok'))
st = A_("select transfer_status(%s,%s)",(A,'9000000001')); blob=json.dumps(st)
t.check("1.17 the seller sees mode 'public' and the code, but not their UPI echoed back or any buyer", any(x['mode']=='public' and x['code'] for x in st['transfers']) and UPI not in blob, st)
t.check("1.18 an admin can read the code in the table; a gate user and a visitor cannot", A_("select count(*) from transfers where status='code_active'",uid=admin,role='authenticated')>=1 and A_("select count(*) from transfers",uid=gate,role='authenticated')==0 and call('anon',"select count(*) from transfers")[0]=='err')
sql("update settings set private_code_hours=168"); psell(B,label(3),'9000000003'); t.check("1.19 the code lifetime setting can be 168 hours", abs(sql("select extract(epoch from code_expires_at-created_at)/3600 from transfers where seller_name='Carl' order by created_at desc limit 1")[0][0]-168)<0.01)
sql("update settings set private_code_hours=2")

# ================= GROUP 2: admin extends a code =================
S = setup(); A, B, admin, gate = S['A'], S['B'], S['admin'], S['gate']
print("-- group 2: extending a code")
code = psell(A, label(1), '9000000001')['code']; x = tid(1)
for who, uid, role in [('a gate user', gate, 'authenticated'), ('anonymous', None, 'anon')]:
    r = adm('admin_transfer_extend_code', x, 48, uid=uid, role=role); t.check(f"2.1 {who} cannot extend a code", r[0]=='err')
t.check("2.2 an admin extends it to 48 hours from now", ok(adm('admin_transfer_extend_code',x,48,uid=admin)) and abs(sql("select extract(epoch from code_expires_at-now())/3600 from transfers where id=%s",(x,))[0][0]-48)<0.05)
sql("update transfers set code_expires_at=now()-interval '1 hour' where id=%s",(x,))
t.check("2.3 an expired code does not open the form", A_("select transfer_open(%s)",(code,))=={'ok':False,'error':'INVALID_CODE'})
adm('admin_transfer_extend_code', x, 24, uid=admin); t.check("2.4 extending an expired code brings it back", A_("select transfer_open(%s)",(code,)).get('ok') is True)
for h in [0, 169, -1, None]: t.check(f"2.5 invalid hours {h}: INVALID_HOURS", err(adm('admin_transfer_extend_code',x,h,uid=admin),'INVALID_HOURS'))
t.check("2.6 unknown transfer: INVALID_TRANSFER", err(adm('admin_transfer_extend_code',str(uuid.uuid4()),24,uid=admin),'INVALID_TRANSFER'))
tsubmit(code); t.check("2.7 once the buyer submitted the code cannot be extended (NOT_ACTIVE)", err(adm('admin_transfer_extend_code',x,24,uid=admin),'NOT_ACTIVE'))
t.check("2.8 extending is in the log", sql("select count(*) from settings_log where area='transfer' and field like '%%code extended%%'")[0][0]==2)
pc = vsell(B, label(3), '9000000003')['code']; xp = tid(3); t.check("2.9 a PRIVATE code can be extended too", ok(adm('admin_transfer_extend_code',xp,72,uid=admin)))

# ================= GROUP 3: the buyer's side and the payment request =================
S = setup(); A, B, admin, gate = S['A'], S['B'], S['admin'], S['gate']
print("-- group 3: buyer form, payment request, payment upload")
r = psell(A, label(1), '9000000001'); code = r['code']; x = tid(1)
o = A_("select transfer_open(%s)",(code,)); blob = json.dumps(o)
t.check("3.1 the buyer's form opens: mode public, seller's NAME only (no phone, UPI, ticket number, Booking ID)", o.get('ok') and o['mode']=='public' and o['seller_name']=='Asha' and not any(k in blob for k in ['9000000001',UPI,'E26-001',A]), o)
base = counts()
sb = tsubmit(code); nb = sb['booking_code']
t.check("3.2 submit works for a public code: new Booking ID, mode public", sb.get('ok') and sb['mode']=='public' and re.fullmatch(r'[0-9A-F]{8}', nb), sb)
bk = sql("select kind,status,people_count,amount_expected,screenshot_path from bookings where booking_code=%s",(nb,))[0]
t.check("3.3 the transfer booking has amount 0 (the buyer's money never enters registration revenue)", bk[:4]==('transfer','pending',1,0) and bk[4] is None, bk)
t.check("3.4 counts, revenue and spots unchanged; no ticket yet", counts()==base and sql("select count(*) from tickets where name='Dan Buyer'")[0][0]==0)
v = lk(nb,'9000000004'); t.check("3.5 the buyer sees type public, state 'pending', no amount yet", v['transfer']=={'type':'public','state':'pending','amount_due':None} and v['tickets']==[], v)
t.check("3.6 the seller's phone cannot see the buyer's booking", lk(nb,'9000000001')=={'found':False})
t.check("3.7 request payment WITHOUT the seller phone call: CALL_NOT_CONFIRMED", err(adm('admin_transfer_request_payment',x,uid=admin),'CALL_NOT_CONFIRMED'))
for who, uid in [('a gate user', gate)]: t.check(f"3.8 {who} cannot request payment", err(adm('admin_transfer_request_payment',x,uid=uid),'NOT_ALLOWED'))
t.check("3.9 anonymous cannot request payment", call('anon',"select admin_transfer_request_payment(%s)",(x,))[0]=='err')
adm('admin_transfer_confirm_call', x, True, uid=admin)
t.check("3.10 payment not requested yet: the buyer's upload is refused (PAYMENT_NOT_REQUESTED)", pay(nb,'9000000004')=={'ok':False,'error':'PAYMENT_NOT_REQUESTED'})
r = adm('admin_transfer_request_payment', x, uid=admin)
t.check("3.11 after the call tick the payment is requested: the standard ticket price (250)", ok(r) and r[1][0][0]=={'amount_due':250} and sql("select amount_due, payment_requested_by from transfers where id=%s",(x,))[0]==(250,str(admin)), r)
sql("update settings set price_per_head=300"); t.check("3.12 the amount asked is fixed at request time (later price changes do not alter it)", lk(nb,'9000000004')['transfer']['amount_due']==250); sql("update settings set price_per_head=250")
t.check("3.13 requesting again: ALREADY_REQUESTED", err(adm('admin_transfer_request_payment',x,uid=admin),'ALREADY_REQUESTED'))
v = lk(nb,'9000000004'); t.check("3.14 the buyer now sees state 'payment_due' and the amount", v['transfer']=={'type':'public','state':'payment_due','amount_due':250}, v)
t.check("3.15 wrong Booking ID / phone / the seller's phone: MISMATCH", pay('ABCD1234','9000000004')['error']=='MISMATCH' and pay(nb,'9555555555')['error']=='MISMATCH' and pay(nb,'9000000001')['error']=='MISMATCH')
sid = uuid.uuid4(); t.check("3.16 screenshot not uploaded: SCREENSHOT_MISSING", pay(nb,'9000000004',sid=sid,path=f'{sid}.jpg')['error']=='SCREENSHOT_MISSING')
sid2 = uuid.uuid4(); shot(sid2); t.check("3.17 a screenshot named for another submission: SCREENSHOT_MISSING", pay(nb,'9000000004',sid=uuid.uuid4(),path=f'{sid2}.jpg')['error']=='SCREENSHOT_MISSING')
t.check("3.18 empty path / null refused", pay(nb,'9000000004',path=None)['error']=='SCREENSHOT_MISSING')
sid = uuid.uuid4(); r = pay(nb,'9000000004',sid=sid); t.check("3.19 the buyer uploads the payment screenshot", r=={'ok':True,'amount_due':250}, r)
r = A_("select transfer_pay(%s,%s,%s,%s)",(nb,'9000000004',str(sid),f'{sid}.jpg')); t.check("3.20 the same upload sent again is a safe retry", r.get('ok') and r.get('replay'), r)
t.check("3.21 a second different payment: ALREADY_SUBMITTED", pay(nb,'9000000004')['error']=='ALREADY_SUBMITTED')
t.check("3.22 the buyer sees 'payment_submitted'", lk(nb,'9000000004')['transfer']['state']=='payment_submitted')
t.check("3.23 payment steps changed no counts or revenue", counts()==base)
# private transfers stay out of the money flow
S = setup(); A, B, admin = S['A'], S['B'], S['admin']; pcode = vsell(A, label(1), '9000000001')['code']; px = tid(1); pb = tsubmit(pcode)['booking_code']; adm('admin_transfer_confirm_call', px, True, uid=admin)
t.check("3.24 a PRIVATE transfer cannot ask for payment (NOT_PUBLIC)", err(adm('admin_transfer_request_payment',px,uid=admin),'NOT_PUBLIC'))
t.check("3.25 a private transfer's buyer cannot upload a payment (MISMATCH)", pay(pb,'9000000004')['error']=='MISMATCH')
t.check("3.26 private: verify / pay out / return refuse (not a public transfer)", err(adm('admin_transfer_verify_payment',px,250,uid=admin),'INVALID_TRANSFER') and err(adm('admin_transfer_mark_paid',px,'UPI-123456',uid=admin),'INVALID_TRANSFER') and err(adm('admin_transfer_mark_returned',px,'UPI-123456',uid=admin),'INVALID_TRANSFER'))
t.check("3.27 a private transfer needs only the call tick: Transfer works and no money fields are touched", ok(adm('admin_transfer_approve',px,uid=admin)) and sql("select amount_due, amount_received, payment_requested_at from transfers where id=%s",(px,))[0]==(None,None,None))
pc2 = vsell(A, label(2), '9000000002')['code']; px2 = tid(2); tsubmit(pc2, buyer(name='Eve Buyer', phone='9000000005'))
t.check("3.27b a PRIVATE transfer without the seller call tick: Transfer refused (CALL_NOT_CONFIRMED)", err(adm('admin_transfer_approve',px2,uid=admin),'CALL_NOT_CONFIRMED') and sql("select count(*) from tickets where name='Eve Buyer'")[0][0]==0)
t.check("3.28 the money panel ignores private transfers", money(S)['held_now']==0 and money(S)['to_pay_out']['count']==0)
# transfers off blocks the upload
S = setup(); A, admin = S['A'], S['admin']; o = pubflow(S, A, 1, '9000000001', stage='requested'); sql("update settings set transfers_open=false")
t.check("3.29 transfers switched off: the payment upload is refused", pay(o['b'],'9000000004')['error']=='TRANSFERS_CLOSED')

# ================= GROUP 4: verify, Transfer, payout =================
S = setup(); A, B, admin, admin2, gate = S['A'], S['B'], S['admin'], S['admin2'], S['gate']
print("-- group 4: verify the amount received, Transfer, pay the seller")
o = pubflow(S, A, 1, '9000000001', stage='paid'); x = o['x']; nb = o['b']
t.check("4.1 Transfer before the payment is verified: PAYMENT_NOT_VERIFIED", err(adm('admin_transfer_approve',x,uid=admin),'PAYMENT_NOT_VERIFIED'))
m = money(S); t.check("4.2 money panel: 250 awaiting verification, nothing held", m['awaiting_verification']=={'count':1,'amount':250} and m['held_now']==0, m)
for a in [0, -5, None, 1000001]: t.check(f"4.3 an invalid amount {a}: INVALID_AMOUNT", err(adm('admin_transfer_verify_payment',x,a,uid=admin),'INVALID_AMOUNT'))
t.check("4.4 verify is refused for non-admins", err(adm('admin_transfer_verify_payment',x,250,uid=gate),'NOT_ALLOWED'))
t.check("4.5 verify with a SMALLER amount than asked (230): accepted, recorded", ok(adm('admin_transfer_verify_payment',x,230,uid=admin)) and sql("select amount_received, amount_due, payment_verified_by from transfers where id=%s",(x,))[0]==(230,250,str(admin)))
t.check("4.6 verifying twice: ALREADY_VERIFIED", err(adm('admin_transfer_verify_payment',x,230,uid=admin),'ALREADY_VERIFIED'))
m = money(S); t.check("4.7 money panel: 230 verified and waiting for Transfer, 230 held", m['verified_waiting_transfer']=={'count':1,'amount':230} and m['held_now']==230 and m['awaiting_verification']['count']==0, m)
t.check("4.8 the buyer sees 'payment_verified'", lk(nb,'9000000004')['transfer']['state']=='payment_verified')
adm('admin_transfer_confirm_call', x, False, uid=admin)
t.check("4.8b even with a verified payment, removing the seller call tick blocks Transfer (CALL_NOT_CONFIRMED)", err(adm('admin_transfer_approve',x,uid=admin),'CALL_NOT_CONFIRMED') and sql("select count(*) from tickets where name='Dan Buyer'")[0][0]==0)
adm('admin_transfer_confirm_call', x, True, uid=admin)
before = counts(); nxt = sql("select next_ticket from settings")[0][0]; old_secret = sql("select secret from tickets where ticket_no=1")[0][0]
out = par([lambda: call_new('authenticated',"select admin_transfer_approve(%s)",(x,),uid=admin), lambda: call_new('authenticated',"select admin_transfer_approve(%s)",(x,),uid=admin2)])
oks = [o2 for o2 in out if o2[0]=='ok']; t.check("4.9 two admins pressing Transfer at the same instant: exactly ONE succeeds", len(oks)==1 and any('NOT_PENDING' in o2[1] for o2 in out if o2[0]=='err'), out)
res = oks[0][1][0][0]; nl = res['new_label']
t.check("4.10 the swap: a new ticket with the next guest number in the buyer's booking; the seller's ticket is retired", res['booking_code']==nb and sql("select ticket_no from tickets where name='Dan Buyer'")[0][0]==nxt and sql("select transferred_out_at is not null, ticket_no from tickets where name='Asha'")[0]==(True,1))
t.check("4.10b public transfer: the buyer's email is in the admin-only ticket_emails table (not on tickets)", sql("select e.email from ticket_emails e join tickets t on t.id=e.ticket_id where t.name='Dan Buyer'")==[('dan@example.com',)])
t.check("4.11 COUNTS unchanged: counted, paid, pending, revenue, registrations", counts()==before, (before, counts()))
v = lk(nb,'9000000004'); t.check("4.12 the buyer sees their ticket with a QR", v['status']=='paid' and v['tickets'][0]['secret'] and v['tickets'][0]['label']==nl, v)
t.check("4.13 the seller sees their ticket as transferred (no QR)", lk(A,'9000000001')['tickets'][0]['transferred'] and lk(A,'9000000001')['tickets'][0]['secret'] is None)
st = A_("select transfer_status(%s,%s)",(A,'9000000001'))['transfers'][0]
t.check("4.14 the seller sees 'done', 'to_be_paid' and the amount they will receive (230)", st['status']=='done' and st['payout']=='to_be_paid' and st['amount_to_receive']==230, st)
g = lambda no, sec: A_("select admit_ticket(%s,%s,false,false,null)",(no,sec),uid=gate,role='authenticated'); dn = sql("select ticket_no, secret from tickets where name='Dan Buyer'")[0]
t.check("4.15 gate: old QR cancelled (names the new holder); the new QR admits once", g(1,old_secret)['result']=='cancelled' and g(1,old_secret)['name']=='Dan Buyer' and g(*dn)['result']=='ok' and g(*dn)['result']=='already_scanned')
m = money(S); t.check("4.16 money panel: 230 to pay out to the seller, 230 still held", m['to_pay_out']=={'count':1,'amount':230} and m['held_now']==230 and m['verified_waiting_transfer']['count']==0, m)
for ref in ['', 'ab', 'x'*81, None]: t.check(f"4.17 bad payout reference refused: {str(ref)[:6]!r}", err(adm('admin_transfer_mark_paid',x,ref,uid=admin),'INVALID_REFERENCE'))
t.check("4.18 mark the seller paid with a reference; again: ALREADY_PAID", ok(adm('admin_transfer_mark_paid',x,'UPI-123456',uid=admin)) and err(adm('admin_transfer_mark_paid',x,'UPI-123456',uid=admin),'ALREADY_PAID'))
m = money(S); t.check("4.19 money panel: 230 paid out, nothing held, nothing to pay", m['paid_out']=={'count':1,'amount':230} and m['held_now']==0 and m['to_pay_out']['count']==0, m)
t.check("4.20 the seller sees 'paid'", A_("select transfer_status(%s,%s)",(A,'9000000001'))['transfers'][0]['payout']=='paid')
sql("update tickets set checked_in_at=null where name='Dan Buyer'")
t.check("4.21 the new holder can sell on like any ticket (here privately: Booking ID + ticket + phone)", vsell(nb, nl, '9000000004').get('ok') is True)
# a LARGER amount than asked
S = setup(); A, admin = S['A'], S['admin']; o = pubflow(S, A, 1, '9000000001', stage='paid')
t.check("4.22 verify with a LARGER amount (300): accepted; the seller will be paid 300", ok(adm('admin_transfer_verify_payment',o['x'],300,uid=admin)) and ok(adm('admin_transfer_approve',o['x'],uid=admin)) and A_("select transfer_status(%s,%s)",(A,'9000000001'))['transfers'][0]['amount_to_receive']==300)
# two admins verify at once
S = setup(); A, admin, admin2 = S['A'], S['admin'], S['admin2']; o = pubflow(S, A, 1, '9000000001', stage='paid')
out = par([lambda: call_new('authenticated',"select admin_transfer_verify_payment(%s,%s)",(o['x'],250),uid=admin), lambda: call_new('authenticated',"select admin_transfer_verify_payment(%s,%s)",(o['x'],999),uid=admin2)])
t.check("4.23 two admins verifying at the same instant: exactly ONE succeeds and one amount is recorded", sum(1 for q in out if q[0]=='ok')==1 and sql("select amount_received from transfers where id=%s",(o['x'],))[0][0] in (250,999), out)
# the buyer double-submits the payment at once
S = setup(); A, admin = S['A'], S['admin']; o = pubflow(S, A, 1, '9000000001', stage='requested'); sid = uuid.uuid4(); p = shot(sid)
out = par([lambda: call_new('anon',"select transfer_pay(%s,%s,%s,%s)",(o['b'],'9000000004',str(sid),p)) for _ in range(4)])
t.check("4.24 the same upload sent 4 times at once: stored once, all answered ok", sum(1 for q in out if q[0]=='ok' and q[1][0][0].get('ok'))==4 and sql("select count(*) from transfers where payment_submission_id=%s",(str(sid),))[0][0]==1, out)
# hall full
S = setup(); A, admin = S['A'], S['admin']; o = pubflow(S, A, 1, '9000000001')
sql("update settings set cap=(select count(*) from tickets where transferred_out_at is null)"); base = counts(); sp = A_("select get_public_status(null)")['spots_left']
t.check("4.25 HALL FULL: the public transfer still works and leaves the hall exactly as full", ok(adm('admin_transfer_approve',o['x'],uid=admin)) and counts()==base and A_("select get_public_status(null)")['spots_left']==sp==0)
sid=uuid.uuid4(); path=shot(sid); rr = call('anon',"select submit_booking(%s,%s::jsonb,%s)",(str(sid),json.dumps([dict(name='Extra',phone='9666666660',email='x@example.com',loc='In Bengaluru',att='Surely',food='Veg')]),path))
t.check("4.26 a normal registration is still refused (NOT_ENOUGH_SPOTS)", rr[0]=='err' and 'NOT_ENOUGH_SPOTS' in rr[1], rr)
# food lock
S = setup(); A, admin = S['A'], S['admin']; sql("update settings set transfer_food_locked=true"); o = pubflow(S, A, 1, '9000000001', stage='submitted', food='Non-veg')
t.check("4.27 food lock: a Non-veg buyer gets the seller's Veg", sql("select food from transfer_buyers")[0][0]=='Veg')

# ================= GROUP 5: when it fails: returns =================
print("-- group 5: failure and return")
S = setup(); A, B, admin, gate = S['A'], S['B'], S['admin'], S['gate']
o = pubflow(S, A, 1, '9000000001', stage='paid'); x = o['x']; base = counts()
t.check("5.1 admin rejects after the buyer sent a screenshot (not yet verified)", ok(adm('admin_transfer_reject',x,'wrong amount',uid=admin)) and sql("select status, return_due from transfers where id=%s",(x,))[0]==('rejected',True))
t.check("5.2 the seller's ticket and counts are untouched", sql("select transferred_out_at from tickets where ticket_no=1")[0][0] is None and counts()==base)
m = money(S); t.check("5.3 money panel: 250 to return (the amount asked), not counted as held (nothing was verified)", m['return_due']=={'count':1,'amount':250} and m['held_now']==0, m)
t.check("5.4 the buyer sees 'return_due'", lk(o['b'],'9000000004')['transfer']['state']=='return_due')
for ref in ['', 'ab']: t.check(f"5.5 bad return reference refused: {ref!r}", err(adm('admin_transfer_mark_returned',x,ref,uid=admin),'INVALID_REFERENCE'))
t.check("5.6 mark returned (a reference like 'no money received' is fine); twice: ALREADY_RETURNED", ok(adm('admin_transfer_mark_returned',x,'no money received',uid=admin)) and err(adm('admin_transfer_mark_returned',x,'no money received',uid=admin),'ALREADY_RETURNED'))
t.check("5.7 the buyer sees 'returned'; money panel: returned, nothing due", lk(o['b'],'9000000004')['transfer']['state']=='returned' and money(S)['returned']['count']==1 and money(S)['return_due']['count']==0)
t.check("5.8 the seller can start a new transfer after a rejection", psell(A,label(1),'9000000001').get('ok') is True)
# after verification: the received amount comes back
S = setup(); A, admin = S['A'], S['admin']; o = pubflow(S, A, 1, '9000000001', amount=230); x = o['x']
adm('admin_transfer_reject', x, 'seller unreachable', uid=admin)
m = money(S); t.check("5.9 reject after verification (230 received): 230 to return and 230 still held", m['return_due']=={'count':1,'amount':230} and m['held_now']==230, m)
adm('admin_transfer_mark_returned', x, 'UPI-RET-001', uid=admin); m = money(S); t.check("5.10 after returning: nothing held", m['held_now']==0 and m['returned']['amount']==230, m)
# reject before payment asked: nothing to return
S = setup(); A, admin = S['A'], S['admin']; o = pubflow(S, A, 1, '9000000001', stage='call'); adm('admin_transfer_reject', o['x'], 'no', uid=admin)
t.check("5.11 reject before any payment was requested: no return, and 'returned' is refused (NO_RETURN_DUE)", sql("select return_due from transfers where id=%s",(o['x'],))[0][0] is False and err(adm('admin_transfer_mark_returned',o['x'],'whatever',uid=admin),'NO_RETURN_DUE'))
t.check("5.12 a rejected transfer's buyer sees 'rejected'; buyer booking rejected", lk(o['b'],'9000000004')['transfer']['state']=='rejected' and sql("select status from bookings where booking_code=%s",(o['b'],))[0][0]=='rejected')
S = setup(); A, admin = S['A'], S['admin']; rc = psell(A, label(1), '9000000001'); xr = tid(1)
t.check("5.13 an admin can cancel a public code nobody used yet: no return, the code stops working, the seller can start again",
        ok(adm('admin_transfer_reject', xr, 'seller asked', uid=admin)) and sql("select status, return_due from transfers where id=%s",(xr,))[0]==('rejected',False)
        and A_("select transfer_open(%s)",(rc['code'],))=={'ok':False,'error':'INVALID_CODE'} and psell(A,label(1),'9000000001').get('ok') is True)
# seller enters the hall after the money was verified
S = setup(); A, admin = S['A'], S['admin']; o = pubflow(S, A, 1, '9000000001'); sql("update tickets set checked_in_at=now() where ticket_no=1"); base = counts()
t.check("5.14 the seller entered the hall before Transfer: refused (SELLER_CHECKED_IN)", err(adm('admin_transfer_approve',o['x'],uid=admin),'SELLER_CHECKED_IN'))
t.check("5.15 nothing changed after that refusal", counts()==base and sql("select count(*) from tickets where name='Dan Buyer'")[0][0]==0 and sql("select status from transfers where id=%s",(o['x'],))[0][0]=='pending_admin')
adm('admin_transfer_reject', o['x'], 'seller came', uid=admin); t.check("5.16 rejecting then marks the return as due", sql("select return_due from transfers where id=%s",(o['x'],))[0][0] is True)
# the seller's booking rejected while a public transfer is pending
for stage, due in [('submitted', False), ('paid', True)]:
    S = setup(); A, admin = S['A'], S['admin']; o = pubflow(S, A, 1, '9000000001', stage=stage)
    adm('set_booking_status', str(sql("select id from bookings where booking_code=%s",(A,))[0][0]), 'rejected', uid=admin)
    row = sql("select status, return_due from transfers where id=%s",(o['x'],))[0]
    t.check(f"5.17 seller booking rejected while '{stage}': transfer closed automatically" + (" and the return is marked due" if due else ", no return"), row==('withdrawn', due), row)
    t.check(f"5.18 ...the buyer's booking is rejected too", sql("select status from bookings where booking_code=%s",(o['b'],))[0][0]=='rejected')
t.check("5.19 set_booking_status still refuses a transfer booking", err(adm('set_booking_status', str(sql("select id from bookings where booking_code=%s",(o['b'],))[0][0]), 'paid', uid=admin),'USE_TRANSFER_TOOLS'))

# ================= GROUP 6: privacy, permissions, audit, re-run =================
S = setup(); A, B, admin, gate = S['A'], S['B'], S['admin'], S['gate']
print("-- group 6: privacy, permissions, audit, re-run")
o = pubflow(S, A, 1, '9000000001', stage='verified'); x = o['x']
buyer_view = json.dumps([A_("select transfer_open(%s)",(o['code'],)), lk(o['b'],'9000000004')])
t.check("6.1 nothing the buyer can read contains the seller's phone, UPI, ticket number or Booking ID", not any(k in buyer_view for k in ['9000000001',UPI,'E26-001',A]), [k for k in ['9000000001',UPI,'E26-001',A] if k in buyer_view])
seller_view = json.dumps([A_("select transfer_status(%s,%s)",(A,'9000000001')), lk(A,'9000000001')])
t.check("6.2 nothing the seller can read contains the buyer's phone, email or Booking ID", not any(k in seller_view for k in ['9000000004','dan@example.com',o['b']]), [k for k in ['9000000004','dan@example.com',o['b']] if k in seller_view])
for fn, args in [('admin_transfer_extend_code',(x,24)),('admin_transfer_request_payment',(x,)),('admin_transfer_verify_payment',(x,250)),('admin_transfer_mark_paid',(x,'ref123')),('admin_transfer_mark_returned',(x,'ref123')),('admin_transfer_money',()),('admin_transfer_approve',(x,)),('admin_transfer_reject',(x,'n')),('admin_transfer_confirm_call',(x,True))]:
    t.check(f"6.3 a gate user cannot call {fn}; anonymous cannot either", err(adm(fn,*args,uid=gate),'NOT_ALLOWED') and call('anon',f"select {fn}({','.join(['%s']*len(args))})",args)[0]=='err')
for fn in ['admin_transfer_extend_code(uuid,integer)','admin_transfer_request_payment(uuid)','admin_transfer_verify_payment(uuid,integer)','admin_transfer_mark_paid(uuid,text)','admin_transfer_mark_returned(uuid,text)','admin_transfer_money()','admin_transfer_approve(uuid)','admin_transfer_reject(uuid,text)','admin_transfer_confirm_call(uuid,boolean)']:
    t.check(f"6.3b anon has NO execute right on {fn.split('(')[0]}", sql(f"select has_function_privilege('anon','public.{fn}','execute')")[0][0] is False)
for fn in ['public_sell(text,text,text,text)','transfer_pay(text,text,uuid,text)']:
    t.check(f"6.3c anon MAY call the visitor function {fn.split('(')[0]}", sql(f"select has_function_privilege('anon','public.{fn}','execute')")[0][0] is True)
t.check("6.4 anon cannot call the internal _close_open_transfers", sql("select has_function_privilege('anon','public._close_open_transfers(uuid,text)','execute')")[0][0] is False)
adm('admin_transfer_approve', x, uid=admin); adm('admin_transfer_mark_paid', x, 'UPI-555555', uid=admin)
log = sql("select who, field, old_value, new_value from settings_log where area='transfer' order by id"); blob = json.dumps(log); fields=' | '.join(l[1] for l in log)
t.check("6.5 every step is in the log", all(k in fields for k in ['public transfer: code created','buyer submitted','call confirmed','payment requested','payment submitted','payment VERIFIED','APPROVED','seller PAID']), fields)
t.check("6.6 the log has only 'visitor' and the admin's name", {l[0] for l in log}=={'visitor','Admin One'}, {l[0] for l in log})
t.check("6.7 the log never contains phones, emails, UPI IDs or QR secrets", not re.search(r'\d{10}', blob) and '@' not in blob and sql("select secret from tickets where ticket_no=1")[0][0] not in blob, blob[:160])
r = subprocess.run(["psql","-h","/tmp","-p","5544","-q","-d","postgres","-U","postgres","-v","ON_ERROR_STOP=1","-f",FILES[-1]],capture_output=True,text=True)
t.check("6.8 the piece-4 SQL can be applied a second time without errors", r.returncode==0, r.stderr[-300:])
t.check("6.9 ...and everything still works afterwards (a new public code)", psell(B,label(3),'9000000003').get('ok') is True)
t.report("R2-1 piece 4 tests (public transfer via code)")
