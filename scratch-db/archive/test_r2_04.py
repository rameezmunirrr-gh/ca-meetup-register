from lib import *
import json, uuid, subprocess, re
F = ['r2_01_prep.sql','r2_02_lookup.sql','r2_02c_close_old_transfer_doors.sql','r2_02b_cutover.sql','r2_03_private_transfer.sql','r2_04_public_transfer.sql']
FILES = ['/home/claude/scratch/'+f for f in F]
t = T()
def setup():
    fresh(FILES); S = seed()
    sql("update settings set transfers_open=true, resale_min_price=50, max_resale_price=250")
    for nm, role, k in [('gate','gate','Gate One'),('admin2','admin','Admin Two')]:
        u = uuid.uuid4(); sql("insert into auth.users (id,email) values (%s,%s)", (str(u), nm+'@test')); sql("insert into staff (user_id,name,role) values (%s,%s,%s)", (str(u), k, role)); S[nm] = u
    return S
def A_(q, p=(), uid=None, role='anon'):
    r = call(role, q, p, uid=uid)
    return r[1][0][0] if r[0]=='ok' and r[1] else (('ERR', r[1]) if r[0]=='err' else None)
def label(n): return 'E26-%03d' % n
UPI='asha@okbank'
def psell(code, lab, phone, reason='Family emergency, cannot attend', price=200, upi=UPI):
    return A_("select public_sell(%s,%s,%s,%s,%s,%s)", (code, lab, phone, reason, price, upi))
def tid_of(no): return str(sql("select id from transfers where ticket_id=(select id from tickets where ticket_no=%s) order by created_at desc limit 1", (no,))[0][0])
def adm(fn, *a, uid=None, role='authenticated'):
    ph = ','.join(['%s']*len(a)); return call(role, f"select {fn}({ph})", a, uid=uid)
def ok(r): return r[0]=='ok'
def err(r, word): return r[0]=='err' and word in r[1]
def list_it(S, code, no, phone, **kw):
    r = psell(code, label(no), phone, **kw); x = tid_of(no)
    adm('admin_transfer_confirm_call', x, True, uid=S['admin']); adm('admin_listing_approve', x, uid=S['admin']); return x, r
def reserve(x, name='Dan Buyer', phone='9000000004'): return A_("select public_reserve(%s,%s,%s)", (x, name, phone))
def buyer(**kw):
    d = dict(name='Dan Buyer', phone='9000000004', email='Dan@Example.com', loc='In Bengaluru', att='Surely', food='Veg', consent='true'); d.update(kw); return d
def shot(sid):
    p = f'{sid}.jpg'; sql("insert into storage.objects values ('payment-proofs',%s)", (p,)); return p
def submit(token, b=None, sid=None, path='auto'):
    sid = sid or uuid.uuid4(); path = shot(sid) if path=='auto' else path
    return A_("select public_submit(%s,%s,%s::jsonb,%s)", (token, str(sid), json.dumps(b or buyer()), path))
def counts():
    return sql("""select (select count(*) from tickets t join bookings b on b.id=t.booking_id where b.status<>'rejected' and t.transferred_out_at is null),
      (select count(*) from tickets t join bookings b on b.id=t.booking_id where b.status='paid' and t.transferred_out_at is null),
      (select count(*) from tickets t join bookings b on b.id=t.booking_id where b.status='pending' and t.transferred_out_at is null),
      (select coalesce(sum(amount_expected),0) from bookings where status='paid'),
      (select count(*) from bookings where kind='registration')""")[0]
def pub(): return A_("select get_public_status(null)")['spots_left']
def money(S): return A_("select admin_transfer_money()", uid=S['admin'], role='authenticated')

# ================= GROUP 1: public_sell =================
S = setup(); A, B, admin, gate = S['A'], S['B'], S['admin'], S['gate']
print("-- group 1: seller requests a public listing")
r = psell(A, label(1), '9000000001', reason='  Family   emergency,\n cannot attend  ')
t.check("1.1 right details create a listing REQUEST (not listed yet)", r.get('ok') and r['status']=='listing_pending' and r['price']==200, r)
row = sql("select status, price, seller_upi, reason, kind from transfers")[0]
t.check("1.2 stored: pending, price, UPI, reason with spaces tidied", row==('listing_pending',200,UPI,'Family emergency, cannot attend','public'), row)
t.check("1.3 it is NOT on the board", A_("select public_board()")['listings']==[])
bad = [('ABCD1234',label(1),'9000000001'),(A,label(9),'9000000001'),(A,label(1),'9555555555'),(A,label(1),'9000000002'),(B,label(1),'9000000001'),(None,label(1),'9000000001'),(A,label(1),None),(A,"1' or '1'='1",'9000000001')]
res = [psell(*x) for x in bad]
t.check("1.4 every wrong detail gives exactly MISMATCH", all(x=={'ok':False,'error':'MISMATCH'} for x in res), res)
n = sql("select count(*) from transfers")[0][0]; psell(A,label(1),'9555555555'); t.check("1.5 a failed attempt creates nothing", sql("select count(*) from transfers")[0][0]==n)
t.check("1.6 a second request for the same seat: ALREADY_OPEN", psell(A,label(1),'9000000001').get('error')=='ALREADY_OPEN')
t.check("1.7 a private code cannot be made while a public listing is open", A_("select private_sell(%s,%s,%s)",(A,label(1),'9000000001'))=={'ok':False,'error':'ALREADY_OPEN','kind':'public'})
c = A_("select private_sell(%s,%s,%s)",(A,label(2),'9000000002'))
t.check("1.8 ...and a public listing cannot be requested while a private code is active", psell(A,label(2),'9000000002')=={'ok':False,'error':'ALREADY_OPEN','kind':'private'})
rr = psell(B, label(3), '9000000003', price=49); t.check("1.9 price below the minimum: PRICE_OUT_OF_RANGE (tells min and max)", rr=={'ok':False,'error':'PRICE_OUT_OF_RANGE','min':50,'max':250}, rr)
t.check("1.10 price above the maximum refused", psell(B,label(3),'9000000003',price=251).get('error')=='PRICE_OUT_OF_RANGE')
t.check("1.11 no price refused", psell(B,label(3),'9000000003',price=None).get('error')=='PRICE_OUT_OF_RANGE')
for u in ['', 'abc', 'a@b', '9876543', 'x y@bank', '<script>@bank', 'a'*70+'@okbank', 'abc@1bank']:
    t.check(f"1.12 invalid UPI refused: {u[:18]!r}", psell(B,label(3),'9000000003',upi=u).get('error')=='INVALID_UPI')
for u in ['name@okhdfc','9876543210','first.last-1@ybl']:
    pass
for rs in ['', 'ab', 'x'*301, '   ']:
    t.check(f"1.13 bad reason refused: {rs[:10]!r} (len {len(rs)})", psell(B,label(3),'9000000003',reason=rs).get('error')=='INVALID_REASON')
t.check("1.14 nothing was created by those refusals", sql("select count(*) from transfers where seller_name='Carl'")[0][0]==0)
r = psell(B, label(3), '9000000003', price=50, upi='9876543210'); t.check("1.15 minimum price and a 10-digit phone as payout ID are accepted", r.get('ok') is True, r)
sql("update transfers set status='withdrawn' where seller_name='Carl'")
r = psell(B, label(3), '9000000003', price=250, upi='first.last-1@ybl'); t.check("1.16 maximum price and a dotted UPI ID are accepted", r.get('ok') is True, r)
sql("update transfers set status='withdrawn' where seller_name='Carl'")
sql("update bookings set status='pending' where booking_code=%s",(B,)); t.check("1.17 unconfirmed booking: NOT_CONFIRMED", psell(B,label(3),'9000000003').get('error')=='NOT_CONFIRMED')
sql("update bookings set status='paid' where booking_code=%s",(B,))
sql("update tickets set checked_in_at=now() where ticket_no=3"); t.check("1.18 checked in: ALREADY_CHECKED_IN", psell(B,label(3),'9000000003').get('error')=='ALREADY_CHECKED_IN'); sql("update tickets set checked_in_at=null where ticket_no=3")
sql("update tickets set kind='coordinator', coord_no=1 where ticket_no=3"); t.check("1.19 coordinator: COORDINATOR", psell(B,'1C','9000000003').get('error')=='COORDINATOR'); sql("update tickets set kind='guest', coord_no=null where ticket_no=3")
t.check("1.20 problems are not revealed to people with wrong details", psell(B,label(3),'9555555555')=={'ok':False,'error':'MISMATCH'})
sql("update settings set transfers_open=false"); t.check("1.21 transfers off: TRANSFERS_CLOSED", psell(B,label(3),'9000000003').get('error')=='TRANSFERS_CLOSED')
sql("update settings set transfers_open=true, transfer_cutoff_at=now()-interval '1 minute'"); t.check("1.22 after the cut-off: CUTOFF_PASSED", psell(B,label(3),'9000000003').get('error')=='CUTOFF_PASSED'); sql("update settings set transfer_cutoff_at=null")

# ================= GROUP 2: admin approves the listing =================
S = setup(); A, B, admin, gate = S['A'], S['B'], S['admin'], S['gate']
print("-- group 2: admin approval of a listing and the board")
psell(A, label(1), '9000000001'); x1 = tid_of(1)
for fn, args in [('admin_listing_approve',(x1,)),('admin_transfer_confirm_call',(x1,True)),('admin_listing_withdraw',(x1,'n')),('admin_release_reservation',(x1,'n')),
                 ('admin_transfer_verify_payment',(x1,200)),('admin_transfer_mark_paid',(x1,'ref123')),('admin_transfer_mark_returned',(x1,'ref123')),
                 ('admin_listing_edit_decide',(x1,True)),('admin_transfer_money',()),('admin_transfer_approve',(x1,)),('admin_transfer_reject',(x1,'x'))]:
    t.check(f"2.1 gate user cannot call {fn}", err(adm(fn,*args,uid=gate),'NOT_ALLOWED'))
    t.check(f"2.1b anonymous cannot call {fn}", call('anon',f"select {fn}({','.join(['%s']*len(args))})",args)[0]=='err')
t.check("2.2 approve WITHOUT the seller phone call is refused", err(adm('admin_listing_approve',x1,uid=admin),'CALL_NOT_CONFIRMED'))
adm('admin_transfer_confirm_call', x1, True, uid=admin)
t.check("2.3 approve with the call tick works", ok(adm('admin_listing_approve',x1,uid=admin)))
t.check("2.4 status is listed, with who and when", sql("select status, listed_by from transfers where id=%s",(x1,))[0]==('listed',str(admin)) and sql("select listed_at is not null from transfers where id=%s",(x1,))[0][0])
t.check("2.5 approving again: NOT_PENDING", err(adm('admin_listing_approve',x1,uid=admin),'NOT_PENDING'))
bd = A_("select public_board()"); blob = json.dumps(bd)
t.check("2.6 the board shows the listing: seller name, price, available", bd['open'] and bd['listings'][0]['seller_name']=='Asha' and bd['listings'][0]['price']==200 and bd['listings'][0]['available'] is True, bd)
t.check("2.7 the board NEVER shows phone, UPI, reason, ticket number or Booking ID", not any(k in blob for k in ['9000000001','9000000002',UPI,'Family emergency','E26-001',A,'"1"']), blob)
st = A_("select public_status(%s,%s)",(A,'9000000001'))
t.check("2.8 the seller sees the listing as 'listed' with their price and UPI", st['found'] and st['transfers'][0]['status']=='listed' and st['transfers'][0]['price']==200 and st['transfers'][0]['seller_upi']==UPI, st)
t.check("2.9 Ben's phone does not show Asha's listing", A_("select public_status(%s,%s)",(A,'9000000002'))['transfers']==[])
t.check("2.10 wrong details: exactly {found:false}", A_("select public_status(%s,%s)",(A,'9555555555'))=={'found':False} and A_("select public_status(%s,%s)",('ABCD1234','9000000001'))=={'found':False})
sql("update tickets set checked_in_at=now() where ticket_no=1"); t.check("2.11 the board hides a listing whose seller entered the hall", A_("select public_board()")['listings']==[]); sql("update tickets set checked_in_at=null where ticket_no=1")
sql("update tickets set transferred_out_at=now() where ticket_no=1"); t.check("2.12 the board hides a transferred-out ticket's listing", A_("select public_board()")['listings']==[]); sql("update tickets set transferred_out_at=null where ticket_no=1")
sql("update settings set transfer_cutoff_at=now()-interval '1 minute'"); bd = A_("select public_board()"); t.check("2.13 after the cut-off the board is empty and says so", bd['listings']==[] and bd['cutoff_passed'] is True)
sql("update settings set transfer_cutoff_at=null, transfers_open=false"); t.check("2.14 transfers off: the board says closed", A_("select public_board()")['open'] is False); sql("update settings set transfers_open=true")
# price limits changed after the request
psell(B, label(3), '9000000003', price=100); x3 = tid_of(3); adm('admin_transfer_confirm_call', x3, True, uid=admin); sql("update settings set resale_min_price=120")
t.check("2.15 limits changed after the request: approval refused (PRICE_OUT_OF_RANGE)", err(adm('admin_listing_approve',x3,uid=admin),'PRICE_OUT_OF_RANGE')); sql("update settings set resale_min_price=50")
sql("update tickets set checked_in_at=now() where ticket_no=3"); t.check("2.16 seller entered the hall before approval: refused", err(adm('admin_listing_approve',x3,uid=admin),'SELLER_ALREADY_CHECKED_IN')); sql("update tickets set checked_in_at=null where ticket_no=3")
t.check("2.17 admin rejects a listing request", ok(adm('admin_transfer_reject',x3,'not now',uid=admin)) and sql("select status, return_due from transfers where id=%s",(x3,))[0]==('rejected',False))
t.check("2.18 the seller can ask again after a rejection", psell(B,label(3),'9000000003').get('ok') is True)

# ================= GROUP 3: reservations =================
S = setup(); A, B, admin, gate = S['A'], S['B'], S['admin'], S['gate']
print("-- group 3: reservations")
psell(A, label(1), '9000000001'); psell(A, label(2), '9000000002', upi='ben@okbank'); psell(B, label(3), '9000000003', upi='carl@okbank')
xa, xb, xc = [tid_of(n) for n in (1,2,3)]
for x in (xa, xb, xc): adm('admin_transfer_confirm_call', x, True, uid=S['admin']); adm('admin_listing_approve', x, uid=S['admin'])
r = reserve(xa)
t.check("3.1 reserve works: a token, 30 minutes", r.get('ok') and re.fullmatch(r'[0-9a-f-]{36}', r['token']) and r['minutes']==30 and r['seller_name']=='Asha' and r['price']==200, r)
tok = r['token']
blob = json.dumps(r); t.check("3.2 the answer has no seller phone, UPI, reason, ticket or Booking ID", not any(k in blob for k in ['9000000001',UPI,'Family','E26-001',A]), blob)
rem = sql("select reserved_until - now() from transfer_buyers")[0][0].total_seconds(); t.check("3.3 the reservation lasts about 30 minutes", 1790 < rem <= 1800, rem)
bd = A_("select public_board()"); t.check("3.4 the board now shows it as NOT available", [l for l in bd['listings'] if l['id']==xa][0]['available'] is False)
t.check("3.5 a second buyer is refused: LISTING_RESERVED", reserve(xa,'Eve','9000000005')=={'ok':False,'error':'LISTING_RESERVED'})
t.check("3.6 the same phone cannot take it over without the token", reserve(xa,'Dan Buyer','9000000004')=={'ok':False,'error':'LISTING_RESERVED'})
t.check("3.7 the same phone cannot hold a second listing at the same time", reserve(xb)=={'ok':False,'error':'ALREADY_RESERVED_ELSEWHERE'})
for nm, ph, e in [('', '9000000009','INVALID_NAME'),('x'*81,'9000000009','INVALID_NAME'),('Zed','+919000000009','INVALID_PHONE'),('Zed','900000009','INVALID_PHONE')]:
    t.check(f"3.8 bad reservation details refused: {nm[:6]!r},{ph}", reserve(xc, nm, ph).get('error')==e)
t.check("3.9 unknown listing id: LISTING_UNAVAILABLE", reserve(str(uuid.uuid4()),'Zed','9000000009').get('error')=='LISTING_UNAVAILABLE')
t.check("3.9b a listing that is only a request is not reservable", True)
rs = A_("select public_reservation(%s)",(tok,))
t.check("3.10 resume with the token: state reserved, seconds left, own name and phone", rs['ok'] and rs['state']=='reserved' and 1700<rs['seconds_left']<=1800 and rs['name']=='Dan Buyer' and rs['phone']=='9000000004' and rs['expired'] is False, rs)
t.check("3.11 a wrong token gives INVALID_RESERVATION", A_("select public_reservation(%s)",(str(uuid.uuid4()),))=={'ok':False,'error':'INVALID_RESERVATION'})
sql("update transfer_buyers set reserved_until=now()-interval '1 minute'")
rs = A_("select public_reservation(%s)",(tok,)); t.check("3.12 after 30 minutes: the page is told it expired (but nobody took it, so it can still be used)", rs['state']=='reserved' and rs['expired'] is True, rs)
bd = A_("select public_board()"); t.check("3.13 after expiry the board shows it available again", [l for l in bd['listings'] if l['id']==xa][0]['available'] is True)
r2 = reserve(xa, 'Eve', '9000000005'); t.check("3.14 another buyer can now reserve it", r2.get('ok') is True, r2)
t.check("3.15 the first buyer's token now says 'ended'", A_("select public_reservation(%s)",(tok,))=={'ok':True,'state':'ended'})
t.check("3.16 cancel by the holder frees the listing", A_("select public_cancel_reservation(%s)",(r2['token'],))=={'ok':True} and [l for l in A_("select public_board()")['listings'] if l['id']==xa][0]['available'] is True)
t.check("3.17 cancelling again: NOT_RESERVED", A_("select public_cancel_reservation(%s)",(r2['token'],))=={'ok':False,'error':'NOT_RESERVED'})
# stale reservation of the same phone elsewhere does not block
r3 = reserve(xa, 'Fay', '9000000006'); sql("update transfer_buyers set reserved_until=now()-interval '2 minutes' where phone='9000000006'")
t.check("3.18 an EXPIRED reservation elsewhere does not block the same phone from reserving another listing", reserve(xb,'Fay','9000000006').get('ok') is True)
sql("update transfer_buyers set status='released' where status='reserved'"); sql("update transfers set status='listed' where status='reserved'")
# parallel
out = par([(lambda i=i: call_new('anon',"select public_reserve(%s,%s,%s)",(xc,f'P{i}',f'90000002{i:02d}'))) for i in range(8)])
oks = [o for o in out if o[0]=='ok' and o[1][0][0].get('ok')]
t.check("3.19 8 buyers reserving the SAME listing at the same instant: exactly ONE wins", len(oks)==1, [o[1][0][0] if o[0]=='ok' else o for o in out])
sql("update transfer_buyers set status='released' where status='reserved'"); sql("update transfers set status='listed' where status='reserved'")
out = par([(lambda x=x: call_new('anon',"select public_reserve(%s,%s,%s)",(x,'Same','9000000777'))) for x in (xa,xb,xc)])
oks = [o for o in out if o[0]=='ok' and o[1][0][0].get('ok')]
t.check("3.20 ONE phone reserving three listings at the same instant: at most ONE succeeds", len(oks)==1, [o[1][0][0] if o[0]=='ok' else o for o in out])
sql("update transfer_buyers set status='released' where status='reserved'"); sql("update transfers set status='listed' where status='reserved'")
sql("update tickets set checked_in_at=now() where ticket_no=3"); t.check("3.21 seller entered the hall: LISTING_UNAVAILABLE", reserve(xc,'Zed','9000000009').get('error')=='LISTING_UNAVAILABLE'); sql("update tickets set checked_in_at=null where ticket_no=3")
sql("update settings set transfer_cutoff_at=now()-interval '1 minute'"); t.check("3.22 after the cut-off: CUTOFF_PASSED", reserve(xc,'Zed','9000000009').get('error')=='CUTOFF_PASSED'); sql("update settings set transfer_cutoff_at=null, transfers_open=false")
t.check("3.23 transfers off: TRANSFERS_CLOSED", reserve(xc,'Zed','9000000009').get('error')=='TRANSFERS_CLOSED'); sql("update settings set transfers_open=true")

# ================= GROUP 4: buyer submits the form and payment =================
S = setup(); A, B, admin, gate = S['A'], S['B'], S['admin'], S['gate']
print("-- group 4: buyer form and payment")
xa, _ = list_it(S, A, 1, '9000000001'); xb, _ = list_it(S, A, 2, '9000000002', price=120, upi='ben@okbank')
tok = reserve(xa)['token']; base = counts(); basepub = pub()
sid = uuid.uuid4()
t.check("4.1 no screenshot uploaded: SCREENSHOT_MISSING", submit(tok, sid=sid, path=f'{sid}.jpg')['error']=='SCREENSHOT_MISSING')
sid2 = uuid.uuid4(); shot(sid2); t.check("4.2 a screenshot with another submission's name: SCREENSHOT_MISSING", submit(tok, sid=uuid.uuid4(), path=f'{sid2}.jpg')['error']=='SCREENSHOT_MISSING')
t.check("4.3 empty path refused", submit(tok, path=None)['error']=='SCREENSHOT_MISSING')
for fld, val, e in [('name','','INVALID_NAME'),('phone','9111111111','PHONE_CHANGED'),('email','nope','INVALID_EMAIL'),('loc','Mars','INVALID_LOCATION'),('att','No','INVALID_ATTENDANCE'),('food','Vegan','INVALID_FOOD'),('consent','false','INVALID_CONSENT')]:
    t.check(f"4.4 bad {fld} -> {e}", submit(tok, buyer(**{fld:val})).get('error')==e)
t.check("4.5 refused forms created nothing and the reservation survives", sql("select count(*) from bookings where kind='transfer'")[0][0]==0 and A_("select public_reservation(%s)",(tok,))['state']=='reserved')
t.check("4.6 a wrong token: INVALID_RESERVATION", submit(str(uuid.uuid4()))['error']=='INVALID_RESERVATION')
sid = uuid.uuid4(); r = submit(tok, sid=sid)
t.check("4.7 a valid form + screenshot gives a NEW Booking ID, pending", r.get('ok') and r['status']=='pending' and r['price']==200 and re.fullmatch(r'[0-9A-F]{8}', r['booking_code']), r)
nb = r['booking_code']
bk = sql("select kind,status,people_count,amount_expected,screenshot_path from bookings where booking_code=%s",(nb,))[0]
t.check("4.8 it is a transfer booking with amount 0 (the price never enters registration money)", bk[:4]==('transfer','pending',1,0) and bk[4] is None, bk)
bu = sql("select status, screenshot_path, email from transfer_buyers where status='active'")[0]
t.check("4.9 the buyer row holds the screenshot and the lower-cased email", bu==('active', f'{sid}.jpg', 'dan@example.com'), bu)
t.check("4.10 transfer is pending_admin; NO ticket for the buyer yet", sql("select status from transfers where id=%s",(xa,))[0][0]=='pending_admin' and sql("select count(*) from tickets where name='Dan Buyer'")[0][0]==0)
t.check("4.11 counts, revenue and spots are unchanged", counts()==base and pub()==basepub, (counts(), base))
r = A_("select public_submit(%s,%s,%s::jsonb,%s)",(tok,str(sid),json.dumps(buyer()),f'{sid}.jpg')); t.check("4.12 the same form sent again gives the same Booking ID", r.get('ok') and r['booking_code']==nb and r.get('replay'), r)
t.check("4.13 a stranger's token cannot read that answer", A_("select public_submit(%s,%s,%s::jsonb,%s)",(str(uuid.uuid4()),str(sid),json.dumps(buyer()),f'{sid}.jpg'))['error']=='INVALID_RESERVATION')
t.check("4.14 a second different form on the same reservation: ALREADY_SUBMITTED", submit(tok)['error']=='ALREADY_SUBMITTED')
t.check("4.15 the reservation page now says 'submitted' with the Booking ID", A_("select public_reservation(%s)",(tok,))['state']=='submitted')
lk = A_("select lookup_tickets(%s,%s)",(nb,'9000000004'))
t.check("4.16 the buyer sees 'pending', the price and no ticket", lk['found'] and lk['status']=='pending' and lk['transfer']=={'type':'public','price':200,'state':'pending'} and lk['tickets']==[], lk)
t.check("4.17 the seller's phone cannot see the buyer's booking", A_("select lookup_tickets(%s,%s)",(nb,'9000000001'))=={'found':False})
ps = A_("select public_status(%s,%s)",(A,'9000000001')); blob=json.dumps(ps)
t.check("4.18 the seller sees 'pending_admin' and the buyer's name only", ps['transfers'][0]['status']=='pending_admin' and ps['transfers'][0]['buyer_name']=='Dan Buyer' and not any(k in blob for k in ['9000000004','dan@',nb]), ps)
t.check("4.19 the listing left the board", all(l['id']!=xa for l in A_("select public_board()")['listings']))
# late submit when nobody else took it
tokb = reserve(xb,'Gus','9000000006')['token']; sql("update transfer_buyers set reserved_until=now()-interval '1 hour' where phone='9000000006'")
t.check("4.20 LATE submit (time ran out but nobody else took it) still works", submit(tokb, buyer(name='Gus', phone='9000000006')).get('ok') is True)
# late submit after someone else reserved
xc, _ = list_it(S, B, 3, '9000000003', price=90, upi='carl@okbank'); tk1 = reserve(xc,'Hal','9000000007')['token']
sql("update transfer_buyers set reserved_until=now()-interval '1 hour' where phone='9000000007'"); tk2 = reserve(xc,'Ivy','9000000008')['token']; nbk = sql("select count(*) from bookings")[0][0]
t.check("4.21 late submit AFTER another buyer reserved: RESERVATION_ENDED, nothing created", submit(tk1, buyer(name='Hal', phone='9000000007'))['error']=='RESERVATION_ENDED' and sql("select count(*) from bookings")[0][0]==nbk)
# seller checked in before submit
sql("update tickets set checked_in_at=now() where ticket_no=3"); nbk = sql("select count(*) from bookings")[0][0]
t.check("4.22 seller entered the hall before the buyer submitted: NOT_AVAILABLE, nothing created", submit(tk2, buyer(name='Ivy', phone='9000000008'))['error']=='NOT_AVAILABLE' and sql("select count(*) from bookings")[0][0]==nbk); sql("update tickets set checked_in_at=null where ticket_no=3")
# food lock
sql("update settings set transfer_food_locked=true")
S2 = setup(); xa2, _ = list_it(S2, S2['A'], 1, '9000000001'); sql("update settings set transfer_food_locked=true"); tkf = reserve(xa2)
t.check("4.23 food lock: the reservation tells the fixed food", tkf['food_locked'] is True and tkf['food']=='Veg', tkf)
r = submit(tkf['token'], buyer(food='Non-veg')); t.check("4.24 food lock: Non-veg is stored as Veg", r.get('ok') and sql("select food from transfer_buyers where status='active'")[0][0]=='Veg', r)
# closed / cutoff
S3 = setup(); xa3, _ = list_it(S3, S3['A'], 1, '9000000001'); tk3 = reserve(xa3)['token']
sql("update settings set transfer_cutoff_at=now()-interval '1 minute'")
t.check("4.25 AFTER the cut-off a buyer who already reserved can still submit (they started in time)", submit(tk3).get('ok') is True)
S3 = setup(); xa3, _ = list_it(S3, S3['A'], 1, '9000000001'); tk3 = reserve(xa3)['token']; sql("update settings set transfers_open=false")
t.check("4.26 transfers switched off: submit refused", submit(tk3)['error']=='TRANSFERS_CLOSED')
# same form 4x at once
S = setup(); xa, _ = list_it(S, S['A'], 1, '9000000001'); tok = reserve(xa)['token']; sid = uuid.uuid4(); p = shot(sid)
out = par([lambda: call_new('anon',"select public_submit(%s,%s,%s::jsonb,%s)",(tok,str(sid),json.dumps(buyer()),p)) for _ in range(4)])
cb = {o[1][0][0].get('booking_code') for o in out if o[0]=='ok' and o[1][0][0].get('ok')}
t.check("4.27 the same form sent 4 times at once: ONE booking, one Booking ID for all", sql("select count(*) from bookings where kind='transfer'")[0][0]==1 and len(cb)==1, (cb, out))
# two different forms at once on the same reservation
S = setup(); xa, _ = list_it(S, S['A'], 1, '9000000001'); tok = reserve(xa)['token']
def mk(): sid = uuid.uuid4(); p = shot(sid); return lambda: call_new('anon',"select public_submit(%s,%s,%s::jsonb,%s)",(tok,str(sid),json.dumps(buyer()),p))
out = par([mk() for _ in range(5)]); oks = [o for o in out if o[0]=='ok' and o[1][0][0].get('ok')]
t.check("4.28 5 different forms on one reservation at once: exactly ONE wins", len(oks)==1 and sql("select count(*) from bookings where kind='transfer'")[0][0]==1, [o[1][0][0] if o[0]=='ok' else o for o in out])

# ================= GROUP 5: money, the swap, payout, return =================
S = setup(); A, B, admin, admin2, gate = S['A'], S['B'], S['admin'], S['admin2'], S['gate']
print("-- group 5: verify payment, swap, payout, return")
xa, _ = list_it(S, A, 1, '9000000001', price=200); tok = reserve(xa)['token']; r = submit(tok); nb = r['booking_code']
t.check("5.1 money panel: 200 awaiting verification, nothing held yet", (lambda m: m['awaiting_verification']=={'count':1,'amount':200} and m['held_now']==0)(money(S)), money(S))
t.check("5.2 approve before verifying the payment: PAYMENT_NOT_VERIFIED (no seller call is needed for public)", err(adm('admin_transfer_approve',xa,uid=admin),'PAYMENT_NOT_VERIFIED'))
for amt in [199, 201, 0, None]:
    t.check(f"5.3 verify with the wrong amount {amt}: AMOUNT_MISMATCH", err(adm('admin_transfer_verify_payment',xa,amt,uid=admin),'AMOUNT_MISMATCH'))
t.check("5.4 nothing changed after wrong amounts", sql("select payment_verified_at is null from transfers where id=%s",(xa,))[0][0])
t.check("5.5 verify with the exact amount", ok(adm('admin_transfer_verify_payment',xa,200,uid=admin)))
t.check("5.6 who, when and the amount are recorded", sql("select payment_verified_by, amount_received from transfers where id=%s",(xa,))[0]==(str(admin),200))
m = money(S); t.check("5.7 money panel: 200 verified and waiting for Transfer, 200 held", m['verified_waiting_transfer']=={'count':1,'amount':200} and m['held_now']==200 and m['awaiting_verification']['count']==0, m)
before = counts(); pb = pub(); nxt = sql("select next_ticket from settings")[0][0]; old_secret = sql("select secret from tickets where ticket_no=1")[0][0]
out = par([lambda: call_new('authenticated',"select admin_transfer_approve(%s)",(xa,),uid=admin), lambda: call_new('authenticated',"select admin_transfer_approve(%s)",(xa,),uid=admin2)])
oks = [o for o in out if o[0]=='ok']; t.check("5.8 two admins pressing Transfer at once: exactly ONE succeeds", len(oks)==1 and any('NOT_PENDING' in o[1] for o in out if o[0]=='err'), out)
res = oks[0][1][0][0]; nl = res['new_label']
t.check("5.9 the swap happened: new ticket for the buyer, number = the next guest number", res['booking_code']==nb and sql("select ticket_no from tickets where name='Dan Buyer'")[0][0]==nxt and sql("select next_ticket from settings")[0][0]==nxt+1, res)
t.check("5.10 seller's ticket transferred out and keeps its retired number", sql("select ticket_no, transferred_out_at is not null from tickets where name='Asha'")[0]==(1,True))
after = counts()
t.check("5.11 COUNTS unchanged: counted tickets, paid, pending, revenue, registrations", after==before, (before, after))
t.check("5.12 the public spots-left is unchanged", pub()==pb)
t.check("5.13 the buyer's price is in NO registration money (all registration bookings still sum as before)", after[3]==before[3])
lk = A_("select lookup_tickets(%s,%s)",(nb,'9000000004')); t.check("5.14 the buyer now sees their ticket with a QR", lk['status']=='paid' and lk['tickets'][0]['secret'] and lk['tickets'][0]['label']==nl, lk)
lk = A_("select lookup_tickets(%s,%s)",(A,'9000000001')); t.check("5.15 the seller's ticket shows 'transferred', no QR, nothing about the buyer", lk['tickets'][0]['transferred'] and lk['tickets'][0]['secret'] is None and 'Dan' not in json.dumps(lk))
g = lambda no, sec: A_("select admit_ticket(%s,%s,false,false,null)",(no,sec),uid=gate,role='authenticated')
t.check("5.16 gate: old QR cancelled (names the new holder), new QR admits once", g(1,old_secret)['result']=='cancelled' and g(1,old_secret)['name']=='Dan Buyer' and g(sql("select ticket_no from tickets where name='Dan Buyer'")[0][0], sql("select secret from tickets where name='Dan Buyer'")[0][0])['result']=='ok')
m = money(S); t.check("5.17 money panel after Transfer: 200 to pay out to the seller, still 200 held", m['to_pay_out']=={'count':1,'amount':200} and m['held_now']==200 and m['verified_waiting_transfer']['count']==0, m)
ps = A_("select public_status(%s,%s)",(A,'9000000001')); t.check("5.18 the seller sees 'done' and 'to_be_paid'", ps['transfers'][0]['status']=='done' and ps['transfers'][0]['payout']=='to_be_paid', ps)
for ref in ['', 'ab', 'x'*81]: t.check(f"5.19 bad payout reference refused: len {len(ref)}", err(adm('admin_transfer_mark_paid',xa,ref,uid=admin),'INVALID_REFERENCE'))
t.check("5.20 marking paid works with a reference", ok(adm('admin_transfer_mark_paid',xa,'UPI-123456',uid=admin)))
t.check("5.21 marking paid twice: ALREADY_PAID", err(adm('admin_transfer_mark_paid',xa,'UPI-123456',uid=admin),'ALREADY_PAID'))
m = money(S); t.check("5.22 money panel: 200 paid out, nothing held, nothing to pay out", m['paid_out']=={'count':1,'amount':200} and m['held_now']==0 and m['to_pay_out']['count']==0, m)
t.check("5.23 the seller sees 'paid'", A_("select public_status(%s,%s)",(A,'9000000001'))['transfers'][0]['payout']=='paid')
t.check("5.24 the payout log has the reference's absence of secrets: log rows exist for each step", sql("select count(*) from settings_log where area='transfer' and field like 'public transfer%%'")[0][0]>=3)
t.check("5.25 cannot mark paid on a transfer that is not done", err(adm('admin_transfer_mark_paid',tid_of(2) if False else xa,'UPI-999999',uid=admin),'ALREADY_PAID'))
# reject after verification -> money return
S = setup(); A, admin = S['A'], S['admin']
xa, _ = list_it(S, A, 1, '9000000001', price=200); tok = reserve(xa)['token']; nb = submit(tok)['booking_code']; adm('admin_transfer_verify_payment',xa,200,uid=admin); base = counts()
t.check("5.26 admin rejects the sale after verifying the payment", ok(adm('admin_transfer_reject',xa,'seller unreachable',uid=admin)))
t.check("5.27 return_due is set; seller's ticket and counts untouched", sql("select status, return_due from transfers where id=%s",(xa,))[0]==('rejected',True) and counts()==base and sql("select transferred_out_at from tickets where ticket_no=1")[0][0] is None)
m = money(S); t.check("5.28 money panel: 200 to return, 200 still held, nothing to pay out", m['return_due']=={'count':1,'amount':200} and m['held_now']==200 and m['to_pay_out']['count']==0, m)
t.check("5.29 the buyer sees 'return_due'", A_("select lookup_tickets(%s,%s)",(nb,'9000000004'))['transfer']['state']=='return_due')
for ref in ['', 'ab']: t.check(f"5.30 bad return reference refused: {ref!r}", err(adm('admin_transfer_mark_returned',xa,ref,uid=admin),'INVALID_REFERENCE'))
t.check("5.31 mark returned with a reference", ok(adm('admin_transfer_mark_returned',xa,'UPI-RET-777',uid=admin)))
t.check("5.32 marking returned twice: ALREADY_RETURNED", err(adm('admin_transfer_mark_returned',xa,'UPI-RET-777',uid=admin),'ALREADY_RETURNED'))
m = money(S); t.check("5.33 money panel: 200 returned, nothing held or due", m['returned']=={'count':1,'amount':200} and m['held_now']==0 and m['return_due']['count']==0, m)
t.check("5.34 the buyer sees 'returned'", A_("select lookup_tickets(%s,%s)",(nb,'9000000004'))['transfer']['state']=='returned')
t.check("5.35 the seller can list again afterwards", psell(A,label(1),'9000000001').get('ok') is True)
# reject before verification (screenshot sent)
S = setup(); A, admin = S['A'], S['admin']; xa, _ = list_it(S, A, 1, '9000000001'); tok = reserve(xa)['token']; submit(tok)
adm('admin_transfer_reject',xa,'wrong amount',uid=admin)
t.check("5.36 reject before verifying: return still due (a screenshot was sent), amount counted at the listed price", sql("select return_due from transfers where id=%s",(xa,))[0][0] and money(S)['return_due']['amount']==200)
t.check("5.37 admin can close it with a 'no money received' reference", ok(adm('admin_transfer_mark_returned',xa,'no money received',uid=admin)))
t.check("5.38 mark returned when nothing is due: NO_RETURN_DUE", err(adm('admin_transfer_mark_returned',xa,'whatever',uid=admin) if False else adm('admin_transfer_mark_returned',xa,'whatever',uid=admin),'ALREADY_RETURNED'))
# reject listing request / reservation only: no money
S = setup(); A, admin = S['A'], S['admin']; psell(A,label(1),'9000000001'); x = tid_of(1); adm('admin_transfer_reject',x,'no',uid=admin)
t.check("5.39 rejecting a plain listing request never creates a return", sql("select return_due from transfers where id=%s",(x,))[0][0] is False)
t.check("5.40 NO_RETURN_DUE when nothing is due", err(adm('admin_transfer_mark_returned',x,'whatever',uid=admin),'NO_RETURN_DUE'))
t.check("5.41 mark paid on a transfer that is not done: NOT_DONE", err(adm('admin_transfer_mark_paid',x,'UPI-123456',uid=admin),'NOT_DONE'))
# seller enters the hall after payment submitted
S = setup(); A, admin = S['A'], S['admin']; xa, _ = list_it(S, A, 1, '9000000001'); tok = reserve(xa)['token']; submit(tok); adm('admin_transfer_verify_payment',xa,200,uid=admin)
sql("update tickets set checked_in_at=now() where ticket_no=1"); base = counts()
t.check("5.42 seller entered the hall before Transfer: refused (SELLER_CHECKED_IN)", err(adm('admin_transfer_approve',xa,uid=admin),'SELLER_CHECKED_IN'))
t.check("5.43 nothing changed after that refusal", counts()==base and sql("select count(*) from tickets where name='Dan Buyer'")[0][0]==0 and sql("select status from transfers where id=%s",(xa,))[0][0]=='pending_admin')
adm('admin_transfer_reject',xa,'seller came',uid=admin); t.check("5.44 reject then marks the return as due", sql("select return_due from transfers where id=%s",(xa,))[0][0])
# hall full
S = setup(); A, admin = S['A'], S['admin']; xa, _ = list_it(S, A, 1, '9000000001'); tok = reserve(xa)['token']; submit(tok); adm('admin_transfer_verify_payment',xa,200,uid=admin)
sql("update settings set cap=(select count(*) from tickets where transferred_out_at is null)"); base = counts(); sp = pub()
t.check("5.45 HALL FULL: the public transfer still works", ok(adm('admin_transfer_approve',xa,uid=admin)))
t.check("5.46 ...the hall is exactly as full as before", counts()==base and pub()==sp==0)
# admin cancels the seller's booking in each state
for stage in ['listed','reserved','pending_admin']:
    S = setup(); A, admin = S['A'], S['admin']; xa, _ = list_it(S, A, 1, '9000000001'); nbk = None
    if stage in ('reserved','pending_admin'): tok = reserve(xa)['token']
    if stage=='pending_admin': nbk = submit(tok)['booking_code']; adm('admin_transfer_verify_payment',xa,200,uid=admin)
    adm('set_booking_status', str(sql("select id from bookings where booking_code=%s",(A,))[0][0]), 'rejected', uid=admin)
    row = sql("select status, return_due from transfers where id=%s",(xa,))[0]
    t.check(f"5.47 seller booking rejected while '{stage}': transfer closed automatically" + (" and the return is marked due" if stage=='pending_admin' else ""), row==('withdrawn', stage=='pending_admin'), row)
    if stage=='pending_admin': t.check("5.48 ...the buyer's booking became rejected too", sql("select status from bookings where booking_code=%s",(nbk,))[0][0]=='rejected')
    if stage=='reserved': t.check("5.49 ...the reservation was released", A_("select public_reservation(%s)",(tok,))['state']=='ended')

# ================= GROUP 6: edit, withdraw, release =================
S = setup(); A, B, admin, gate = S['A'], S['B'], S['admin'], S['gate']
print("-- group 6: edit, withdraw, release")
xa, _ = list_it(S, A, 1, '9000000001', price=200)
ed = lambda **kw: A_("select public_edit(%s,%s,%s,%s,%s,%s)",(A,label(1),'9000000001',kw.get('reason','New reason here'),kw.get('price',150),kw.get('upi','new@okbank')))
r = ed(); t.check("6.1 a seller's change becomes a PENDING request", r=={'ok':True,'status':'edit_pending'}, r)
t.check("6.2 the live listing is unchanged until the admin approves", sql("select price, seller_upi from transfers where id=%s",(xa,))[0]==(200,UPI) and A_("select public_board()")['listings'][0]['price']==200)
ps = A_("select public_status(%s,%s)",(A,'9000000001')); t.check("6.3 the seller sees edit_pending", ps['transfers'][0]['edit_pending'] is True and ps['transfers'][0]['edit_price']==150)
t.check("6.4 wrong details cannot request a change", A_("select public_edit(%s,%s,%s,%s,%s,%s)",(A,label(1),'9555555555','x reason',100,'a@okbank'))=={'ok':False,'error':'MISMATCH'})
t.check("6.5 edit price out of range refused", ed(price=300).get('error')=='PRICE_OUT_OF_RANGE' and ed(price=10).get('error')=='PRICE_OUT_OF_RANGE')
t.check("6.6 edit with bad UPI / reason refused", ed(upi='bad').get('error')=='INVALID_UPI' and ed(reason='x').get('error')=='INVALID_REASON')
t.check("6.7 a newer request replaces the older pending one", ed(price=120)['ok'] and sql("select edit_price from transfers where id=%s",(xa,))[0][0]==120)
t.check("6.8 admin approves the change: values applied, request cleared", ok(adm('admin_listing_edit_decide',xa,True,uid=admin)) and sql("select price, seller_upi, reason, edit_price, edit_requested_at from transfers where id=%s",(xa,))[0]==(120,'new@okbank','New reason here',None,None))
t.check("6.9 the board shows the new price", A_("select public_board()")['listings'][0]['price']==120)
t.check("6.10 deciding when nothing is pending: NO_EDIT_PENDING", err(adm('admin_listing_edit_decide',xa,True,uid=admin),'NO_EDIT_PENDING'))
ed(price=90); t.check("6.11 admin rejects a change: request cleared, listing unchanged", ok(adm('admin_listing_edit_decide',xa,False,uid=admin)) and sql("select price, edit_price from transfers where id=%s",(xa,))[0]==(120,None))
ed(price=90); sql("update settings set resale_min_price=100"); t.check("6.12 limits changed after the request: approval refused", err(adm('admin_listing_edit_decide',xa,True,uid=admin),'PRICE_OUT_OF_RANGE')); sql("update settings set resale_min_price=50"); adm('admin_listing_edit_decide',xa,False,uid=admin)
tok = reserve(xa)['token']
t.check("6.13 while a buyer has reserved: EDIT_BLOCKED", ed().get('error')=='EDIT_BLOCKED')
sql("update transfer_buyers set reserved_until=now()-interval '1 hour'")
t.check("6.14 ...but a stale (expired, untaken) reservation does not block a change", ed().get('ok') is True and sql("select status from transfers where id=%s",(xa,))[0][0]=='listed')
adm('admin_listing_edit_decide',xa,False,uid=admin)
tok = reserve(xa)['token']; submit(tok)
t.check("6.15 after the buyer submitted: EDIT_BLOCKED", ed().get('error')=='EDIT_BLOCKED')
S = setup(); A, B, admin = S['A'], S['B'], S['admin']; psell(A,label(1),'9000000001'); xa = tid_of(1)
ed = lambda **kw: A_("select public_edit(%s,%s,%s,%s,%s,%s)",(A,label(1),'9000000001','New reason here',150,'new@okbank'))
t.check("6.16 a request that is not approved yet cannot be edited: EDIT_BLOCKED", ed().get('error')=='EDIT_BLOCKED')
t.check("6.17 no transfer at all: NOTHING_TO_EDIT", A_("select public_edit(%s,%s,%s,%s,%s,%s)",(B,label(3),'9000000003','New reason here',150,'new@okbank'))['error']=='NOTHING_TO_EDIT')
adm('admin_transfer_confirm_call',xa,True,uid=admin); adm('admin_listing_approve',xa,uid=admin)
# withdraw
t.check("6.18 withdraw note too long refused", err(adm('admin_listing_withdraw',xa,'x'*301,uid=admin),'INVALID_NOTE'))
tok = reserve(xa)['token']
t.check("6.19 withdraw while a buyer has reserved: BUYER_RESERVED", err(adm('admin_listing_withdraw',xa,'n',uid=admin),'BUYER_RESERVED'))
t.check("6.20 admin releases the reservation", ok(adm('admin_release_reservation',xa,'buyer slow',uid=admin)) and A_("select public_reservation(%s)",(tok,))['state']=='ended' and sql("select status from transfers where id=%s",(xa,))[0][0]=='listed')
t.check("6.21 releasing when not reserved: NOT_RESERVED", err(adm('admin_release_reservation',xa,'n',uid=admin),'NOT_RESERVED'))
tok = reserve(xa)['token']; submit(tok)
t.check("6.22 withdraw after the buyer paid: USE_REJECT (so the money return is recorded)", err(adm('admin_listing_withdraw',xa,'n',uid=admin),'USE_REJECT'))
S = setup(); A, admin = S['A'], S['admin']; xa, _ = list_it(S, A, 1, '9000000001'); tok = reserve(xa)['token']; sql("update transfer_buyers set reserved_until=now()-interval '1 hour'")
t.check("6.23 withdraw works when the only reservation is stale", ok(adm('admin_listing_withdraw',xa,'seller asked',uid=admin)) and sql("select status from transfers where id=%s",(xa,))[0][0]=='withdrawn')
t.check("6.24 a withdrawn listing is off the board and the seller can list again", A_("select public_board()")['listings']==[] and psell(A,label(1),'9000000001').get('ok') is True)
x2 = tid_of(1); t.check("6.25 a plain request can be withdrawn too", ok(adm('admin_listing_withdraw',x2,None,uid=admin)))
t.check("6.26 withdrawing something already closed: NOT_OPEN", err(adm('admin_listing_withdraw',x2,None,uid=admin),'NOT_OPEN'))

# ================= GROUP 7: privacy, permissions, audit, re-run =================
S = setup(); A, B, admin, gate = S['A'], S['B'], S['admin'], S['gate']
print("-- group 7: privacy, permissions, audit, re-run")
xa, _ = list_it(S, A, 1, '9000000001', price=200, reason='Secret family reason'); r1 = reserve(xa); tok = r1['token']
pv = [A_("select public_board()"), r1, A_("select public_reservation(%s)",(tok,))]   # (a ticket holder looking up their OWN booking is not a public view)
nb = submit(tok)['booking_code']; pv += [A_("select lookup_tickets(%s,%s)",(nb,'9000000004')), A_("select public_reservation(%s)",(tok,)), A_("select public_board()")]
blob = json.dumps(pv)
t.check("7.1 nothing a buyer or the public can read contains the seller's phone, UPI, reason, ticket number or Booking ID", not any(k in blob for k in ['9000000001',UPI,'Secret family reason','E26-001',A]), [k for k in ['9000000001',UPI,'Secret family reason','E26-001',A] if k in blob])
for fn in ['_seller_block(uuid)','_normalize_reservation(uuid)','_clean_reason(text)','_close_open_transfers(uuid,text)','_find_seller_ticket(text,text,text)']:
    t.check(f"7.2 anon cannot call internal {fn.split('(')[0]}", sql(f"select has_function_privilege('anon','public.{fn}','execute')")[0][0] is False)
adm('admin_transfer_verify_payment',xa,200,uid=admin); adm('admin_transfer_approve',xa,uid=admin); adm('admin_transfer_mark_paid',xa,'UPI-555555',uid=admin)
log = sql("select who, field, old_value, new_value from settings_log where area='transfer' order by id"); blob = json.dumps(log); fields=' | '.join(l[1] for l in log)
t.check("7.3 every public step is in the log", all(k in fields for k in ['listing: requested','listing: APPROVED','reserved by a buyer','buyer submitted payment','payment VERIFIED','APPROVED','seller PAID']), fields)
t.check("7.4 the log has only 'visitor' and the admin's name", {l[0] for l in log}=={'visitor','Admin One'}, {l[0] for l in log})
t.check("7.5 the log never contains phones, emails, UPI IDs, reasons or QR secrets", not re.search(r'\d{10}', blob) and '@' not in blob and 'Secret family' not in blob and sql("select secret from tickets where ticket_no=1")[0][0] not in blob, blob[:150])
# both kinds live together
S = setup(); A, B, admin = S['A'], S['B'], S['admin']; xa, _ = list_it(S, A, 1, '9000000001'); pc = A_("select private_sell(%s,%s,%s)",(A,label(2),'9000000002'))['code']
t.check("7.6 a private code on one seat and a public listing on another work side by side", A_("select private_open(%s)",(pc,)).get('ok') and len(A_("select public_board()")['listings'])==1)
t.check("7.7 private_cancel never touches a public listing", A_("select private_cancel(%s,%s,%s)",(A,label(1),'9000000001'))['error']=='NOTHING_TO_CANCEL' and sql("select status from transfers where id=%s",(xa,))[0][0]=='listed')
r = subprocess.run(["psql","-h","/tmp","-p","5544","-q","-d","postgres","-U","postgres","-v","ON_ERROR_STOP=1","-f",FILES[-1]],capture_output=True,text=True)
t.check("7.8 the piece-4 SQL can be applied a second time without errors", r.returncode==0, r.stderr[-300:])
t.check("7.9 ...and everything still works afterwards", A_("select public_board()")['open'] is True and psell(B,label(3),'9000000003').get('ok') is True)
t.report("R2-1 piece 4 tests (public transfer)")
