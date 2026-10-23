from lib import *
import json, uuid, subprocess, re
F = ['r2_01_prep.sql','r2_02_lookup.sql','r2_02c_close_old_transfer_doors.sql','r2_02b_cutover.sql','r2_03_private_transfer.sql','r2_04_public_transfer.sql']
FILES = ['/home/claude/scratch/'+f for f in F]
t = T()
def setup(**settings):
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
    psell(code, label(no), phone, **kw); x = tid_of(no)
    adm('admin_transfer_confirm_call', x, True, uid=S['admin']); adm('admin_listing_approve', x, uid=S['admin']); return x
def P(name, phone, **kw):
    d = dict(name=name, phone=phone, email=f'{name.lower()}@example.com', loc='In Bengaluru', att='Surely', food='Veg'); d.update(kw); return d
def interest(people, together=False, sid=None, consent=True):
    return A_("select interest_submit(%s,%s::jsonb,%s,%s)", (str(sid or uuid.uuid4()), json.dumps(people), together, consent))
def iid(code): return str(sql("select ti.id from transfer_interests ti join bookings b on b.id=ti.booking_id where b.booking_code=%s",(code,))[0][0])
def pid(code, pos): return str(sql("select tp.id from transfer_interest_people tp join transfer_interests ti on ti.id=tp.interest_id join bookings b on b.id=ti.booking_id where b.booking_code=%s and tp.position=%s",(code,pos))[0][0])
def mid(listing): return str(sql("select id from transfer_matches where listing_id=%s order by matched_at desc limit 1",(listing,))[0][0])
def match(*pairs, uid=None, override=False, S=None):
    return adm('admin_transfer_match', json.dumps([{'person':p,'listing':l} for p,l in pairs]), override, uid=uid)
def shot(sid):
    p = f'{sid}.jpg'; sql("insert into storage.objects values ('payment-proofs',%s)", (p,)); return p
def pay(code, phone, payid, sid=None, path='auto'):
    sid = sid or uuid.uuid4(); path = shot(sid) if path=='auto' else path
    return A_("select interest_pay(%s,%s,%s,%s,%s)", (code, phone, payid, str(sid), path))
def lk(code, phone): return A_("select lookup_tickets(%s,%s)", (code, phone))
def counts():
    return sql("""select (select count(*) from tickets t join bookings b on b.id=t.booking_id where b.status<>'rejected' and t.transferred_out_at is null),
      (select count(*) from tickets t join bookings b on b.id=t.booking_id where b.status='paid' and t.transferred_out_at is null),
      (select count(*) from tickets t join bookings b on b.id=t.booking_id where b.status='pending' and t.transferred_out_at is null),
      (select coalesce(sum(amount_expected),0) from bookings where status='paid'),
      (select count(*) from bookings where kind='registration')""")[0]
def pub(): return A_("select get_public_status(null)")['spots_left']
def money(S): return A_("select admin_transfer_money()", uid=S['admin'], role='authenticated')
def full_flow(S, buyer_code, listing_ids, together=False, verify=True):
    """match person 1.. to listings, confirm, pay, verify; returns payment id"""
    pairs = [(pid(buyer_code, i+1), l) for i, l in enumerate(listing_ids)]
    match(*pairs, uid=S['admin']); r = adm('admin_match_confirm', iid(buyer_code), uid=S['admin'])
    payid = str(sql("select id from transfer_payments where interest_id=%s order by created_at desc limit 1",(iid(buyer_code),))[0][0])
    phone = sql("select phone from transfer_interest_people where id=%s",(pairs[0][0],))[0][0]
    pay(buyer_code, phone, payid)
    amt = sql("select amount from transfer_payments where id=%s",(payid,))[0][0]
    if verify: adm('admin_payment_verify', payid, amt, uid=S['admin'])
    return payid

# ================= GROUP 1: seller requests a listing =================
S = setup(); A, B, admin, gate = S['A'], S['B'], S['admin'], S['gate']
print("-- group 1: seller requests a public listing")
r = psell(A, label(1), '9000000001', reason='  Family   emergency,\n cannot attend  ')
t.check("1.1 right details create a listing REQUEST (not listed yet)", r.get('ok') and r['status']=='listing_pending' and r['price']==200, r)
row = sql("select status, price, seller_upi, reason, kind from transfers")[0]
t.check("1.2 stored: pending, price, UPI, reason with spaces tidied", row==('listing_pending',200,UPI,'Family emergency, cannot attend','public'), row)
bad = [('ABCD1234',label(1),'9000000001'),(A,label(9),'9000000001'),(A,label(1),'9555555555'),(A,label(1),'9000000002'),(B,label(1),'9000000001'),(None,label(1),'9000000001'),(A,label(1),None),(A,"1' or '1'='1",'9000000001')]
res = [psell(*x) for x in bad]
t.check("1.3 every wrong detail gives exactly MISMATCH", all(x=={'ok':False,'error':'MISMATCH'} for x in res), res)
n = sql("select count(*) from transfers")[0][0]; psell(A,label(1),'9555555555'); t.check("1.4 a failed attempt creates nothing", sql("select count(*) from transfers")[0][0]==n)
t.check("1.5 a second request for the same seat: ALREADY_OPEN", psell(A,label(1),'9000000001').get('error')=='ALREADY_OPEN')
t.check("1.6 a private code cannot be made while a public listing is open", A_("select private_sell(%s,%s,%s)",(A,label(1),'9000000001'))=={'ok':False,'error':'ALREADY_OPEN','kind':'public'})
A_("select private_sell(%s,%s,%s)",(A,label(2),'9000000002'))
t.check("1.7 ...and a public listing cannot be requested while a private code is active", psell(A,label(2),'9000000002')=={'ok':False,'error':'ALREADY_OPEN','kind':'private'})
t.check("1.8 price below the minimum: PRICE_OUT_OF_RANGE (with min and max)", psell(B,label(3),'9000000003',price=49)=={'ok':False,'error':'PRICE_OUT_OF_RANGE','min':50,'max':250})
t.check("1.9 price above the maximum / no price refused", psell(B,label(3),'9000000003',price=251).get('error')=='PRICE_OUT_OF_RANGE' and psell(B,label(3),'9000000003',price=None).get('error')=='PRICE_OUT_OF_RANGE')
for u in ['', 'abc', 'a@b', '9876543', 'x y@bank', '<script>@bank', 'a'*70+'@okbank', 'abc@1bank']:
    t.check(f"1.10 invalid UPI refused: {u[:18]!r}", psell(B,label(3),'9000000003',upi=u).get('error')=='INVALID_UPI')
for rs in ['', 'ab', 'x'*301, '   ']:
    t.check(f"1.11 bad reason refused (len {len(rs)})", psell(B,label(3),'9000000003',reason=rs).get('error')=='INVALID_REASON')
t.check("1.12 nothing was created by those refusals", sql("select count(*) from transfers where seller_name='Carl'")[0][0]==0)
t.check("1.13 minimum price + a 10-digit phone as payout ID accepted", psell(B,label(3),'9000000003',price=50,upi='9876543210').get('ok') is True)
sql("update transfers set status='withdrawn' where seller_name='Carl'")
t.check("1.14 maximum price + a dotted UPI ID accepted", psell(B,label(3),'9000000003',price=250,upi='first.last-1@ybl').get('ok') is True)
sql("update transfers set status='withdrawn' where seller_name='Carl'")
sql("update bookings set status='pending' where booking_code=%s",(B,)); t.check("1.15 unconfirmed booking: NOT_CONFIRMED", psell(B,label(3),'9000000003').get('error')=='NOT_CONFIRMED'); sql("update bookings set status='paid' where booking_code=%s",(B,))
sql("update tickets set checked_in_at=now() where ticket_no=3"); t.check("1.16 checked in: ALREADY_CHECKED_IN", psell(B,label(3),'9000000003').get('error')=='ALREADY_CHECKED_IN'); sql("update tickets set checked_in_at=null where ticket_no=3")
sql("update tickets set kind='coordinator', coord_no=1 where ticket_no=3"); t.check("1.17 coordinator: COORDINATOR", psell(B,'1C','9000000003').get('error')=='COORDINATOR'); sql("update tickets set kind='guest', coord_no=null where ticket_no=3")
t.check("1.18 problems are not revealed to people with wrong details", psell(B,label(3),'9555555555')=={'ok':False,'error':'MISMATCH'})
sql("update settings set transfers_open=false"); t.check("1.19 transfers off: TRANSFERS_CLOSED", psell(B,label(3),'9000000003').get('error')=='TRANSFERS_CLOSED')
sql("update settings set transfers_open=true, transfer_cutoff_at=now()-interval '1 minute'"); t.check("1.20 after the cut-off: CUTOFF_PASSED", psell(B,label(3),'9000000003').get('error')=='CUTOFF_PASSED'); sql("update settings set transfer_cutoff_at=null")

# ================= GROUP 2: admin approves / edits / revokes listings =================
S = setup(); A, B, admin, gate = S['A'], S['B'], S['admin'], S['gate']
print("-- group 2: admin listing approval, edits, revoke")
psell(A, label(1), '9000000001'); x1 = tid_of(1)
for fn, args in [('admin_listing_approve',(x1,)),('admin_transfer_confirm_call',(x1,True)),('admin_listing_revoke',(x1,'n')),('admin_listing_edit_decide',(x1,True)),
                 ('admin_interest_revoke',(x1,'n')),('admin_transfer_match',('[]',False)),('admin_match_confirm',(x1,)),('admin_match_release',(x1,'n')),
                 ('admin_payment_verify',(x1,200)),('admin_match_transfer',(x1,)),('admin_transfer_mark_paid',(x1,'ref123')),('admin_transfer_mark_returned',(x1,'ref123')),('admin_transfer_money',())]:
    t.check(f"2.1 gate user cannot call {fn}", err(adm(fn,*args,uid=gate),'NOT_ALLOWED'))
    t.check(f"2.1b anonymous cannot call {fn}", call('anon',f"select {fn}({','.join(['%s']*len(args))})",args)[0]=='err')
t.check("2.2 approve WITHOUT the seller phone call is refused", err(adm('admin_listing_approve',x1,uid=admin),'CALL_NOT_CONFIRMED'))
adm('admin_transfer_confirm_call', x1, True, uid=admin)
t.check("2.3 approve with the call tick works; status listed with who and when", ok(adm('admin_listing_approve',x1,uid=admin)) and sql("select status, listed_by from transfers where id=%s",(x1,))[0]==('listed',str(admin)))
t.check("2.4 approving again: NOT_PENDING", err(adm('admin_listing_approve',x1,uid=admin),'NOT_PENDING'))
st = A_("select public_status(%s,%s)",(A,'9000000001'))
t.check("2.5 the seller sees 'listed' with their price and UPI, and nothing about any buyer", st['found'] and st['transfers'][0]['status']=='listed' and st['transfers'][0]['price']==200 and st['transfers'][0]['seller_upi']==UPI, st)
t.check("2.6 Ben's phone does not show Asha's listing; wrong details give {found:false}", A_("select public_status(%s,%s)",(A,'9000000002'))['transfers']==[] and A_("select public_status(%s,%s)",(A,'9555555555'))=={'found':False})
t.check("2.7 NO public function lists listings (there is no board)", sql("select count(*) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='public' and p.proname in ('public_board','public_reserve')")[0][0]==0)
# price limits changed after the request
psell(B, label(3), '9000000003', price=100); x3 = tid_of(3); adm('admin_transfer_confirm_call', x3, True, uid=admin); sql("update settings set resale_min_price=120")
t.check("2.8 limits changed after the request: approval refused (PRICE_OUT_OF_RANGE)", err(adm('admin_listing_approve',x3,uid=admin),'PRICE_OUT_OF_RANGE')); sql("update settings set resale_min_price=50")
sql("update tickets set checked_in_at=now() where ticket_no=3"); t.check("2.9 seller entered the hall before approval: refused", err(adm('admin_listing_approve',x3,uid=admin),'SELLER_ALREADY_CHECKED_IN')); sql("update tickets set checked_in_at=null where ticket_no=3")
t.check("2.10 admin revokes a plain listing request", ok(adm('admin_listing_revoke',x3,'not now',uid=admin)) and sql("select status from transfers where id=%s",(x3,))[0][0]=='withdrawn')
t.check("2.11 the seller can ask again afterwards", psell(B,label(3),'9000000003').get('ok') is True)
t.check("2.12 revoking something already closed: NOT_OPEN; long note refused", err(adm('admin_listing_revoke',x3,'n',uid=admin),'NOT_OPEN') and err(adm('admin_listing_revoke',x1,'x'*301,uid=admin),'INVALID_NOTE'))
# edits
ed = lambda **kw: A_("select public_edit(%s,%s,%s,%s,%s,%s)",(A,label(1),'9000000001',kw.get('reason','New reason here'),kw.get('price',150),kw.get('upi','new@okbank')))
t.check("2.13 a seller's change becomes a PENDING request; the live listing is unchanged", ed()=={'ok':True,'status':'edit_pending'} and sql("select price, seller_upi from transfers where id=%s",(x1,))[0]==(200,UPI))
ps = A_("select public_status(%s,%s)",(A,'9000000001')); t.check("2.14 the seller sees edit_pending and the requested price", ps['transfers'][0]['edit_pending'] is True and ps['transfers'][0]['edit_price']==150)
t.check("2.15 wrong details cannot request a change", A_("select public_edit(%s,%s,%s,%s,%s,%s)",(A,label(1),'9555555555','x reason',100,'a@okbank'))=={'ok':False,'error':'MISMATCH'})
t.check("2.16 edit price out of range / bad UPI / bad reason refused", ed(price=300).get('error')=='PRICE_OUT_OF_RANGE' and ed(price=10).get('error')=='PRICE_OUT_OF_RANGE' and ed(upi='bad').get('error')=='INVALID_UPI' and ed(reason='x').get('error')=='INVALID_REASON')
ed(price=120); t.check("2.17 a newer request replaces the older pending one", sql("select edit_price from transfers where id=%s",(x1,))[0][0]==120)
t.check("2.18 admin approves the change: applied and cleared", ok(adm('admin_listing_edit_decide',x1,True,uid=admin)) and sql("select price, seller_upi, reason, edit_price, edit_requested_at from transfers where id=%s",(x1,))[0]==(120,'new@okbank','New reason here',None,None))
t.check("2.19 deciding when nothing is pending: NO_EDIT_PENDING", err(adm('admin_listing_edit_decide',x1,True,uid=admin),'NO_EDIT_PENDING'))
ed(price=90); t.check("2.20 admin rejects a change: cleared, listing unchanged", ok(adm('admin_listing_edit_decide',x1,False,uid=admin)) and sql("select price, edit_price from transfers where id=%s",(x1,))[0]==(120,None))
ed(price=90); sql("update settings set resale_min_price=100"); t.check("2.21 limits changed after a change request: approval refused", err(adm('admin_listing_edit_decide',x1,True,uid=admin),'PRICE_OUT_OF_RANGE')); sql("update settings set resale_min_price=50"); adm('admin_listing_edit_decide',x1,False,uid=admin)
t.check("2.22 a listing that is still only a request cannot be edited (EDIT_BLOCKED); no listing: NOTHING_TO_EDIT",
        A_("select public_edit(%s,%s,%s,%s,%s,%s)",(B,label(3),'9000000003','New reason here',100,'a@okbank'))['error']=='EDIT_BLOCKED' and
        A_("select public_edit(%s,%s,%s,%s,%s,%s)",(A,label(2),'9000000002','New reason here',100,'a@okbank'))['error']=='NOTHING_TO_EDIT')

# ================= GROUP 3: the buyer's interest form =================
S = setup(); A, B, admin, gate = S['A'], S['B'], S['admin'], S['gate']
print("-- group 3: buyer interest form")
base = counts(); basepub = pub()
r = interest([P('Dan','9000000004', max_price=200)])
t.check("3.1 a valid form gives a new Booking ID", r.get('ok') and re.fullmatch(r'[0-9A-F]{8}', r['booking_code']) and r['people']==1 and r['all_together'] is False, r)
d = r['booking_code']
bk = sql("select kind,status,people_count,amount_expected,screenshot_path from bookings where booking_code=%s",(d,))[0]
t.check("3.2 it is a transfer booking: pending, amount 0, no screenshot", bk==('transfer','pending',1,0,None), bk)
pr = sql("select name, email, status, food, max_price, position from transfer_interest_people")[0]
t.check("3.3 the person is stored (email lower-cased, status waiting, max price)", pr==('Dan','dan@example.com','waiting','Veg',200,1), pr)
t.check("3.4 NO ticket exists; counts, revenue, spots unchanged", sql("select count(*) from tickets where name='Dan'")[0][0]==0 and counts()==base and pub()==basepub)
big = [P(f'Pat{i}', f'9000001{i:03d}', max_price=100+i) for i in range(5)]
r5 = interest(big, together=True); t.check("3.5 five people, 'all together': accepted", r5.get('ok') and r5['people']==5 and r5['all_together'] is True, r5)
t.check("3.6 their positions are 1 to 5", [x[0] for x in sql("select position from transfer_interest_people tp join transfer_interests ti on ti.id=tp.interest_id where ti.all_together order by position")]==[1,2,3,4,5])
t.check("3.7 six people refused", interest([P(f'X{i}', f'9111111{i:03d}') for i in range(6)])=={'ok':False,'error':'INVALID_PEOPLE'})
for bad in [[], 'x', None, {'a':1}, ['notanobject']]:
    t.check(f"3.8 invalid people list refused: {str(bad)[:16]}", interest(bad).get('error')=='INVALID_PEOPLE')
nb = sql("select count(*) from bookings")[0][0]
for fld, val, e in [('name','','INVALID_NAME'),('name','x'*81,'INVALID_NAME'),('phone','+919111111111','INVALID_PHONE'),('phone','91111','INVALID_PHONE'),('email','nope','INVALID_EMAIL'),
                    ('loc','Mars','INVALID_LOCATION'),('att','No','INVALID_ATTENDANCE'),('food','Vegan','INVALID_FOOD'),('max_price','-5','INVALID_MAX_PRICE'),('max_price','251','INVALID_MAX_PRICE'),('max_price','12a','INVALID_MAX_PRICE')]:
    bad_person = P('Bad','9222222222'); bad_person[fld] = val
    r = interest([P('Ok','9111111111'), bad_person])
    t.check(f"3.9 bad {fld}={val[:8]!r} on person 2 -> {e}, naming person 2", r.get('error')==e and r.get('person')==2, r)
t.check("3.10 refused forms created nothing", sql("select count(*) from bookings")[0][0]==nb)
t.check("3.11 consent missing/false refused", interest([P('Ok','9111111111')], consent=False).get('error')=='INVALID_CONSENT' and interest([P('Ok','9111111111')], consent=None).get('error')=='INVALID_CONSENT')
r = interest([P('NoMax','9333333333')]); pm = sql("select max_price from transfer_interest_people where name='NoMax'")[0][0]; t.check("3.12 a form without a maximum price is fine (stored empty)", r.get('ok') and pm is None)
t.check("3.13 the same phone for two people in one form is fine", interest([P('Fam1','9444444444'), P('Fam2','9444444444')]).get('ok') is True)
sid = uuid.uuid4(); r1 = interest([P('Rep','9555555551')], sid=sid); r2 = interest([P('Rep','9555555551')], sid=sid)
t.check("3.14 the same form sent twice returns the same Booking ID (safe retry), one booking", r1['booking_code']==r2['booking_code'] and r2.get('replay') and sql("select count(*) from transfer_interests where submission_id=%s",(str(sid),))[0][0]==1)
for i in range(3): interest([P(f'Cap{i}','9666666666')])
t.check("3.15 a 4th OPEN form from the same first phone is refused (TOO_MANY_OPEN)", interest([P('Cap4','9666666666')]).get('error')=='TOO_MANY_OPEN')
adm('admin_interest_revoke', iid(sql("select booking_code from bookings b join transfer_interests ti on ti.booking_id=b.id join transfer_interest_people tp on tp.interest_id=ti.id and tp.position=1 where tp.phone='9666666666' limit 1")[0][0]), 'x', uid=admin)
t.check("3.16 after one is closed, the phone can submit again", interest([P('Cap5','9666666666')]).get('ok') is True)
sql("update settings set transfers_open=false"); t.check("3.17 transfers off: TRANSFERS_CLOSED", interest([P('Z','9777777771')]).get('error')=='TRANSFERS_CLOSED')
sql("update settings set transfers_open=true, transfer_cutoff_at=now()-interval '1 minute'"); t.check("3.18 after the cut-off: CUTOFF_PASSED", interest([P('Z','9777777771')]).get('error')=='CUTOFF_PASSED'); sql("update settings set transfer_cutoff_at=null")
sql("update settings set interest_max_price_enabled=false"); r = interest([P('Off','9888888881', max_price=9999)])
t.check("3.19 with the maximum-price switch OFF the field is ignored (stored empty, no error)", r.get('ok') and sql("select max_price from transfer_interest_people where name='Off'")[0][0] is None, r)
sql("update settings set interest_max_price_enabled=true, transfer_food_locked=true"); r = interest([{k:v for k,v in P('Lock','9888888882').items() if k!='food'}])
t.check("3.20 with the food lock ON the form needs no food; none is stored", r.get('ok') and sql("select food from transfer_interest_people where name='Lock'")[0][0] is None, r)
sql("update settings set transfer_food_locked=false")
v = lk(d, '9000000004')
t.check("3.21 the buyer can look it up with Booking ID + phone: state waiting, one person", v['found'] and v['kind']=='transfer' and v['transfer']['type']=='interest' and v['transfer']['state']=='waiting' and v['transfer']['people']==[{'name':'Dan','status':'waiting','price':None}] and v['tickets']==[], v)
t.check("3.22 any person on the form can look it up with their own phone", lk(r5['booking_code'], '9000001003')['found'] is True and lk(r5['booking_code'], '9000001003')['name']=='Pat3')
t.check("3.23 a wrong phone / a seller's phone find nothing", lk(d,'9555555555')=={'found':False} and lk(d,'9000000001')=={'found':False})
t.check("3.24 paying before any payment exists: MISMATCH", pay(d,'9000000004',str(uuid.uuid4()))=={'ok':False,'error':'MISMATCH'})
for tb in ['transfer_interests','transfer_interest_people','transfer_payments','transfer_matches']:
    t.check(f"3.25 anon has no access to {tb}; logged-in users can only read", sql(f"select has_table_privilege('anon','public.{tb}','select') or has_table_privilege('anon','public.{tb}','insert') or has_table_privilege('anon','public.{tb}','update') or has_table_privilege('anon','public.{tb}','delete')")[0][0] is False
            and sql(f"select has_table_privilege('authenticated','public.{tb}','select'), has_table_privilege('authenticated','public.{tb}','insert') or has_table_privilege('authenticated','public.{tb}','update') or has_table_privilege('authenticated','public.{tb}','delete')")[0]==(True, False))
t.check("3.26 a gate user sees ZERO interest rows; an admin sees them", A_("select count(*) from transfer_interests", uid=gate, role='authenticated')==0 and A_("select count(*) from transfer_interests", uid=admin, role='authenticated')>=3)

# ================= GROUP 4: matching =================
S = setup(); A, B, admin, admin2, gate = S['A'], S['B'], S['admin'], S['admin2'], S['gate']
print("-- group 4: the admin matches buyers to listings")
L1 = list_it(S, A, 1, '9000000001', price=200); L2 = list_it(S, A, 2, '9000000002', price=120, upi='ben@okbank'); L3 = list_it(S, B, 3, '9000000003', price=90, upi='carl@okbank')
D = interest([P('Dan','9000000004', max_price=250)])['booking_code']
E = interest([P('Eve','9000000005', max_price=100), P('Fay','9000000006', max_price=250)])['booking_code']
G = interest([P('Gus','9000000007', max_price=250), P('Hal','9000000008', max_price=250)], together=True)['booking_code']
r = match((pid(D,1), L1), uid=admin)
t.check("4.1 match one person to one listing: ok, nobody older was skipped", ok(r) and r[1][0][0]=={'matches':1,'older_waiting':0}, r)
t.check("4.2 listing is 'matched', person 'matched', match 'held' at the listing's price", sql("select status from transfers where id=%s",(L1,))[0][0]=='matched' and sql("select status from transfer_interest_people where id=%s",(pid(D,1),))[0][0]=='matched' and sql("select status, price, matched_by from transfer_matches")[0]==('held',200,str(admin)))
t.check("4.3 the listing cannot be matched again (LISTING_NOT_AVAILABLE)", err(match((pid(E,2), L1), uid=admin),'LISTING_NOT_AVAILABLE'))
t.check("4.4 the same person cannot be matched twice (PERSON_NOT_WAITING)", err(match((pid(D,1), L2), uid=admin),'PERSON_NOT_WAITING'))
t.check("4.5 seller sees 'matched' and NOTHING about the buyer", (lambda s: s['transfers'][0]['status']=='matched' and 'Dan' not in json.dumps(s) and D not in json.dumps(s))(A_("select public_status(%s,%s)",(A,'9000000001'))))
t.check("4.6 a matched listing cannot be edited by the seller (EDIT_BLOCKED)", A_("select public_edit(%s,%s,%s,%s,%s,%s)",(A,label(1),'9000000001','New reason here',150,'new@okbank'))['error']=='EDIT_BLOCKED')
v = lk(D,'9000000004'); t.check("4.7 the buyer sees state 'matched' with their price", v['transfer']['state']=='matched' and v['transfer']['people'][0]=={'name':'Dan','status':'matched','price':200}, v)
t.check("4.8 unknown person / unknown listing / duplicates / empty are refused",
        err(match((str(uuid.uuid4()), L2), uid=admin),'PERSON_NOT_FOUND') and err(match((pid(E,1), str(uuid.uuid4())), uid=admin),'LISTING_NOT_AVAILABLE')
        and err(match((pid(E,1), L2),(pid(E,1), L3), uid=admin),'DUPLICATE_IN_PAIRS') and err(match((pid(E,1), L2),(pid(E,2), L2), uid=admin),'DUPLICATE_IN_PAIRS')
        and err(adm('admin_transfer_match','[]',False,uid=admin),'INVALID_PAIRS') and err(adm('admin_transfer_match','{}',False,uid=admin),'INVALID_PAIRS'))
t.check("4.9 nothing was matched by those refusals", sql("select count(*) from transfer_matches")[0][0]==1)
t.check("4.11 price above the buyer's maximum: PRICE_ABOVE_MAX", err(match((pid(E,1), L2), uid=admin),'PRICE_ABOVE_MAX'))
t.check("4.12 ...unless the admin overrides (after agreeing on the call)", ok(match((pid(E,1), L2), uid=admin, override=True)))
r = match((pid(E,2), L3), uid=admin); t.check("4.13 matching the 2nd person of a normal form works; older_waiting counts the skipped older buyer", ok(r) and r[1][0][0]['older_waiting']==0, r)
S = setup(); A, B, admin, admin2 = S['A'], S['B'], S['admin'], S['admin2']
L1 = list_it(S, A, 1, '9000000001', price=200); L2 = list_it(S, A, 2, '9000000002', price=120, upi='ben@okbank'); L3 = list_it(S, B, 3, '9000000003', price=90, upi='carl@okbank')
D = interest([P('Dan','9000000004', max_price=250)])['booking_code']
G = interest([P('Gus','9000000007', max_price=250), P('Hal','9000000008', max_price=250)], together=True)['booking_code']
r = match((pid(G,1), L1), uid=admin); t.check("4.15 'all together': one person only -> ALL_TOGETHER_REQUIRED", err(r,'ALL_TOGETHER_REQUIRED'), r)
t.check("4.16 ...and nothing at all was matched (all or nothing)", sql("select count(*) from transfer_matches")[0][0]==0 and sql("select status from transfers where id=%s",(L1,))[0][0]=='listed')
sql("update transfers set status='withdrawn' where id=%s",(L3,))
r = match((pid(G,1), L1),(pid(G,2), L3), uid=admin); t.check("4.17 'all together' with one unavailable listing: refused as a whole", err(r,'LISTING_NOT_AVAILABLE') and sql("select count(*) from transfer_matches")[0][0]==0, r)
sql("update transfers set status='listed' where id=%s",(L3,))
r = match((pid(G,1), L1),(pid(G,2), L3), uid=admin); t.check("4.18 'all together' with all listings available: both matched in one step", ok(r) and r[1][0][0]['matches']==2 and sql("select count(*) from transfer_matches where status='held'")[0][0]==2, r)
r = match((pid(D,1), L2), uid=admin); t.check("4.19 matching a newer buyer when every older one is already matched: nobody skipped", ok(r) and r[1][0][0]['older_waiting']==0, r)
S = setup(); A, B, admin, admin2 = S['A'], S['B'], S['admin'], S['admin2']
L1 = list_it(S, A, 1, '9000000001', price=200); L2 = list_it(S, A, 2, '9000000002', price=120, upi='ben@okbank')
D1 = interest([P('Dan','9000000004')])['booking_code']; D2 = interest([P('Eve','9000000005')])['booking_code']
r = match((pid(D2,1), L1), uid=admin); t.check("4.20 matching the NEWER buyer while an older one still waits: allowed, with a warning count", ok(r) and r[1][0][0]['older_waiting']==1, r)
sql("update tickets set checked_in_at=now() where ticket_no=2"); t.check("4.21 seller entered the hall: LISTING_NOT_AVAILABLE", err(match((pid(D1,1), L2), uid=admin),'LISTING_NOT_AVAILABLE')); sql("update tickets set checked_in_at=null where ticket_no=2")
psell(B, label(3), '9000000003'); Lp = tid_of(3)
t.check("4.21b a listing that is only a request (not approved) cannot be matched, even with an override", err(match((pid(D1,1), Lp), uid=admin, override=True),'LISTING_NOT_AVAILABLE'))
# parallel
S = setup(); A, B, admin, admin2 = S['A'], S['B'], S['admin'], S['admin2']
L1 = list_it(S, A, 1, '9000000001', price=100); L2 = list_it(S, A, 2, '9000000002', price=100, upi='ben@okbank')
D1 = interest([P('Dan','9000000004')])['booking_code']; D2 = interest([P('Eve','9000000005')])['booking_code']
out = par([lambda: call_new('authenticated',"select admin_transfer_match(%s,false)",(json.dumps([{'person':pid(D1,1),'listing':L1}]),),uid=admin),
           lambda: call_new('authenticated',"select admin_transfer_match(%s,false)",(json.dumps([{'person':pid(D2,1),'listing':L1}]),),uid=admin2)])
t.check("4.22 two admins matching the SAME listing at the same instant: exactly one wins", sum(1 for o in out if o[0]=='ok')==1 and sql("select count(*) from transfer_matches")[0][0]==1, out)
S = setup(); A, B, admin, admin2 = S['A'], S['B'], S['admin'], S['admin2']
L1 = list_it(S, A, 1, '9000000001', price=100); L2 = list_it(S, A, 2, '9000000002', price=100, upi='ben@okbank'); D1 = interest([P('Dan','9000000004')])['booking_code']
out = par([lambda: call_new('authenticated',"select admin_transfer_match(%s,false)",(json.dumps([{'person':pid(D1,1),'listing':L1}]),),uid=admin),
           lambda: call_new('authenticated',"select admin_transfer_match(%s,false)",(json.dumps([{'person':pid(D1,1),'listing':L2}]),),uid=admin2)])
t.check("4.23 the SAME buyer matched to two listings at the same instant: exactly one wins", sum(1 for o in out if o[0]=='ok')==1 and sql("select count(*) from transfer_matches")[0][0]==1, out)

# ================= GROUP 5: confirm, pay, verify, transfer, payout =================
S = setup(); A, B, admin, admin2, gate = S['A'], S['B'], S['admin'], S['admin2'], S['gate']
print("-- group 5: confirm, one payment, verify, transfer, payout")
L1 = list_it(S, A, 1, '9000000001', price=200); D = interest([P('Dan','9000000004')])['booking_code']
t.check("5.1 confirm with no held match: NO_HELD_MATCH", err(adm('admin_match_confirm', iid(D), uid=admin),'NO_HELD_MATCH'))
match((pid(D,1), L1), uid=admin); m1 = mid(L1)
t.check("5.2 transfer before confirmation: NOT_CONFIRMED", err(adm('admin_match_transfer', m1, uid=admin),'NOT_CONFIRMED'))
r = adm('admin_match_confirm', iid(D), uid=admin); res = r[1][0][0]
t.check("5.3 confirm after the phone call: ONE payment of 200 for 1 ticket", ok(r) and res['amount']==200 and res['tickets']==1, r)
t.check("5.4 the match is 'confirmed' and tied to the payment", sql("select status, payment_id is not null, confirmed_by from transfer_matches")[0]==('confirmed',True,str(admin)))
payid = res['payment_id']; v = lk(D,'9000000004')
t.check("5.5 the buyer sees 'payment_due' with the amount and payment id", v['transfer']['state']=='payment_due' and v['transfer']['payment']=={'id':payid,'amount':200,'status':'awaiting'}, v)
t.check("5.6 confirming again: NO_HELD_MATCH", err(adm('admin_match_confirm', iid(D), uid=admin),'NO_HELD_MATCH'))
m = money(S); t.check("5.7 money panel: 200 awaiting payment, nothing held", m['awaiting_payment']=={'count':1,'amount':200} and m['held_now']==0, m)
t.check("5.8 wrong Booking ID / phone / payment id: MISMATCH", pay('ABCD1234','9000000004',payid)['error']=='MISMATCH' and pay(D,'9555555555',payid)['error']=='MISMATCH' and pay(D,'9000000004',str(uuid.uuid4()))['error']=='MISMATCH')
sid = uuid.uuid4(); t.check("5.9 no screenshot uploaded: SCREENSHOT_MISSING", pay(D,'9000000004',payid,sid=sid,path=f'{sid}.jpg')['error']=='SCREENSHOT_MISSING')
sid2 = uuid.uuid4(); shot(sid2); t.check("5.10 a screenshot named for another submission: SCREENSHOT_MISSING", pay(D,'9000000004',payid,sid=uuid.uuid4(),path=f'{sid2}.jpg')['error']=='SCREENSHOT_MISSING')
t.check("5.11 transfer before the payment is verified: PAYMENT_NOT_VERIFIED", err(adm('admin_match_transfer', m1, uid=admin),'PAYMENT_NOT_VERIFIED'))
t.check("5.12 verify before the buyer paid: NOT_SUBMITTED", err(adm('admin_payment_verify', payid, 200, uid=admin),'NOT_SUBMITTED'))
sid = uuid.uuid4(); r = pay(D,'9000000004',payid,sid=sid); t.check("5.13 the buyer pays: ok", r=={'ok':True,'amount':200}, r)
r = A_("select interest_pay(%s,%s,%s,%s,%s)",(D,'9000000004',payid,str(sid),f'{sid}.jpg')); t.check("5.14 the same upload sent again is a safe retry", r.get('ok') and r.get('replay'), r)
t.check("5.15 a second different payment on the same request: ALREADY_SUBMITTED", pay(D,'9000000004',payid)['error']=='ALREADY_SUBMITTED')
t.check("5.16 the buyer sees 'payment_submitted'; money panel: 200 awaiting verification", lk(D,'9000000004')['transfer']['state']=='payment_submitted' and money(S)['awaiting_verification']=={'count':1,'amount':200})
for amt in [199, 201, 0, None]: t.check(f"5.17 verify with the wrong amount {amt}: AMOUNT_MISMATCH", err(adm('admin_payment_verify', payid, amt, uid=admin),'AMOUNT_MISMATCH'))
t.check("5.18 verify with the exact amount; who, when and amount recorded", ok(adm('admin_payment_verify', payid, 200, uid=admin)) and sql("select status, verified_by, amount_received from transfer_payments")[0]==('verified',str(admin),200))
m = money(S); t.check("5.19 money panel: 200 verified and waiting for Transfer, 200 held", m['verified_waiting_transfer']=={'count':1,'amount':200} and m['held_now']==200 and m['awaiting_verification']['count']==0, m)
t.check("5.20 buyer sees 'payment_verified'", lk(D,'9000000004')['transfer']['state']=='payment_verified')
before = counts(); pb = pub(); nxt = sql("select next_ticket from settings")[0][0]; old_secret = sql("select secret from tickets where ticket_no=1")[0][0]
out = par([lambda: call_new('authenticated',"select admin_match_transfer(%s)",(m1,),uid=admin), lambda: call_new('authenticated',"select admin_match_transfer(%s)",(m1,),uid=admin2)])
oks = [o for o in out if o[0]=='ok']; t.check("5.21 two admins pressing Transfer at the same instant: exactly ONE succeeds", len(oks)==1 and len([o for o in out if o[0]=='err'])==1, out)
res = oks[0][1][0][0]['transferred'][0]; nl = res['new_label']
t.check("5.22 the swap: Dan has a new ticket with the next guest number, in the interest's booking", sql("select ticket_no from tickets where name='Dan'")[0][0]==nxt and sql("select next_ticket from settings")[0][0]==nxt+1 and sql("select b.booking_code from tickets t join bookings b on b.id=t.booking_id where t.name='Dan'")[0][0]==D, res)
t.check("5.23 the seller's ticket is transferred out and keeps its retired number", sql("select ticket_no, transferred_out_at is not null from tickets where name='Asha'")[0]==(1,True))
t.check("5.24 listing, match, person and interest are all 'done'; the booking is paid", sql("select status from transfers where id=%s",(L1,))[0][0]=='done' and sql("select status from transfer_matches")[0][0]=='done' and sql("select status from transfer_interest_people where name='Dan'")[0][0]=='done' and sql("select status from transfer_interests")[0][0]=='done' and sql("select status from bookings where booking_code=%s",(D,))[0][0]=='paid')
after = counts(); t.check("5.25 COUNTS unchanged: counted, paid, pending, revenue, registrations", after==before, (before, after))
t.check("5.26 the public spots-left number is unchanged", pub()==pb)
v = lk(D,'9000000004'); t.check("5.27 the buyer sees state 'done' and their ticket with a QR", v['transfer']['state']=='done' and v['tickets'][0]['secret'] and v['tickets'][0]['label']==nl, v)
t.check("5.28 the seller sees their ticket as transferred (no QR) and the listing 'done / to be paid'", lk(A,'9000000001')['tickets'][0]['transferred'] and lk(A,'9000000001')['tickets'][0]['secret'] is None and A_("select public_status(%s,%s)",(A,'9000000001'))['transfers'][0]['payout']=='to_be_paid')
g = lambda no, sec: A_("select admit_ticket(%s,%s,false,false,null)",(no,sec),uid=gate,role='authenticated')
dn = sql("select ticket_no, secret from tickets where name='Dan'")[0]
t.check("5.29 gate: old QR CANCELLED (names the new holder); the new QR admits once, then 'already scanned'", g(1,old_secret)['result']=='cancelled' and g(1,old_secret)['name']=='Dan' and g(*dn)['result']=='ok' and g(*dn)['result']=='already_scanned')
m = money(S); t.check("5.30 money panel: 200 to pay out to the seller, still 200 held", m['to_pay_out']=={'count':1,'amount':200} and m['held_now']==200 and m['verified_waiting_transfer']['count']==0, m)
for ref in ['', 'ab', 'x'*81]: t.check(f"5.31 bad payout reference refused (len {len(ref)})", err(adm('admin_transfer_mark_paid',L1,ref,uid=admin),'INVALID_REFERENCE'))
t.check("5.32 mark the seller paid with a reference; again -> ALREADY_PAID", ok(adm('admin_transfer_mark_paid',L1,'UPI-123456',uid=admin)) and err(adm('admin_transfer_mark_paid',L1,'UPI-123456',uid=admin),'ALREADY_PAID'))
m = money(S); t.check("5.33 money panel: 200 paid out, nothing held", m['paid_out']=={'count':1,'amount':200} and m['held_now']==0 and m['to_pay_out']['count']==0, m)
t.check("5.34 the seller sees 'paid'", A_("select public_status(%s,%s)",(A,'9000000001'))['transfers'][0]['payout']=='paid')
t.check("5.35 Dan was admitted at the gate, so selling that ticket is refused (ALREADY_CHECKED_IN)", A_("select private_sell(%s,%s,%s)",(D,nl,'9000000004')).get('error')=='ALREADY_CHECKED_IN')
sql("update tickets set checked_in_at=null where name='Dan'")
t.check("5.35b ...before the hall, a transferred ticket sells on like any ticket (Dan's Booking ID + ticket + phone)", A_("select private_sell(%s,%s,%s)",(D,nl,'9000000004')).get('ok') is True)
# a form of two normal people: ONE payment for two tickets, transfer one at a time
S = setup(); A, B, admin = S['A'], S['B'], S['admin']
L1 = list_it(S, A, 1, '9000000001', price=200); L2 = list_it(S, A, 2, '9000000002', price=120, upi='ben@okbank'); L3 = list_it(S, B, 3, '9000000003', price=90, upi='carl@okbank')
E = interest([P('Eve','9000000005'), P('Fay','9000000006'), P('Gus','9000000007')])['booking_code']
payid = full_flow(S, E, [L1, L2, L3])
t.check("5.36 three tickets confirmed together: ONE payment of 410, one screenshot", sql("select count(*), sum(amount) from transfer_payments")[0]==(1,410))
m = money(S); t.check("5.37 money panel: 410 verified, 3 tickets waiting", m['verified_waiting_transfer']=={'count':3,'amount':410} and m['held_now']==410, m)
before = counts(); r = adm('admin_match_transfer', mid(L2), uid=admin)
t.check("5.38 a NORMAL (not all-together) buyer: Transfer swaps only the chosen ticket", ok(r) and len(r[1][0][0]['transferred'])==1 and sql("select count(*) from tickets where booking_id=(select id from bookings where booking_code=%s)",(E,))[0][0]==1, r)
t.check("5.39 the other two stay confirmed; the interest stays open; counts unchanged", sql("select count(*) from transfer_matches where status='confirmed'")[0][0]==2 and sql("select status from transfer_interests")[0][0]=='waiting' and counts()==before)
t.check("5.40 Fay (2nd person) sees her ticket only through her own phone; Eve's phone does not show it", lk(E,'9000000006')['tickets'][0]['name']=='Fay' and lk(E,'9000000005')['tickets']==[] )
adm('admin_match_transfer', mid(L1), uid=admin); adm('admin_match_transfer', mid(L3), uid=admin)
t.check("5.41 after the last transfer the interest is 'done' and all 3 people hold tickets", sql("select status from transfer_interests")[0][0]=='done' and sql("select count(*) from tickets where booking_id=(select id from bookings where booking_code=%s)",(E,))[0][0]==3 and counts()==before)
nos = [r[0] for r in sql("select ticket_no from tickets order by ticket_no")]; t.check("5.42 every ticket number is unique", len(nos)==len(set(nos)), nos)
# 'all together': transferred in one step
S = setup(); A, B, admin = S['A'], S['B'], S['admin']
L1 = list_it(S, A, 1, '9000000001', price=200); L2 = list_it(S, A, 2, '9000000002', price=120, upi='ben@okbank')
G = interest([P('Gus','9000000007'), P('Hal','9000000008')], together=True)['booking_code']; full_flow(S, G, [L1, L2]); before = counts()
r = adm('admin_match_transfer', mid(L1), uid=admin)
t.check("5.43 'all together': one press of Transfer swaps BOTH tickets", ok(r) and len(r[1][0][0]['transferred'])==2 and sql("select count(*) from tickets where booking_id=(select id from bookings where booking_code=%s)",(G,))[0][0]==2 and sql("select status from transfer_interests")[0][0]=='done' and counts()==before, r)
# 'all together' with one seller who entered the hall
S = setup(); A, B, admin = S['A'], S['B'], S['admin']
L1 = list_it(S, A, 1, '9000000001', price=200); L2 = list_it(S, A, 2, '9000000002', price=120, upi='ben@okbank')
G = interest([P('Gus','9000000007'), P('Hal','9000000008')], together=True)['booking_code']; full_flow(S, G, [L1, L2])
sql("update tickets set checked_in_at=now() where ticket_no=2"); before = counts()
r = adm('admin_match_transfer', mid(L1), uid=admin)
t.check("5.44 'all together' and ONE seller is in the hall: the WHOLE transfer is refused", err(r,'SELLER_CHECKED_IN'), r)
t.check("5.45 nothing changed at all (no ticket for either person)", sql("select count(*) from tickets where name in ('Gus','Hal')")[0][0]==0 and counts()==before and sql("select count(*) from transfer_matches where status='confirmed'")[0][0]==2)
adm('admin_match_release', mid(L2), 'seller came to the hall', uid=admin)
t.check("5.46 releasing one match sends ALL of that buyer's matches back (cascade)", sql("select count(*) from transfer_matches where status='released'")[0][0]==2 and sql("select status from transfers where id=%s",(L1,))[0][0]=='listed' and sql("select count(*) from transfer_interest_people where status='waiting'")[0][0]==2)
m = money(S); t.check("5.47 money panel: 320 to return (payment was verified), 320 still held", m['return_due']=={'count':2,'amount':320} and m['held_now']==320, m)
t.check("5.48 the buyer sees 'waiting' again (and the payment is no longer asked)", lk(G,'9000000007')['transfer']['state']=='waiting')
ms = [str(r[0]) for r in sql("select id from transfer_matches order by id")]
for mm in ms: t.check("5.49 return each share with a reference", ok(adm('admin_transfer_mark_returned', mm, 'UPI-RET-'+mm[:4], uid=admin)))
t.check("5.50 returning twice: ALREADY_RETURNED", err(adm('admin_transfer_mark_returned', ms[0], 'UPI-RET-9999', uid=admin),'ALREADY_RETURNED'))
m = money(S); t.check("5.51 money panel: 320 returned, nothing held or due", m['returned']=={'count':2,'amount':320} and m['held_now']==0 and m['return_due']['count']==0, m)
t.check("5.52 the freed listings are available again, but not to the same buyer without an override", err(match((pid(G,1), L1),(pid(G,2), L2), uid=admin),'PAIR_RELEASED_BEFORE'))
sql("update tickets set checked_in_at=null where ticket_no=2")
t.check("5.52b ...with the override (seller no longer in the hall) it works", ok(match((pid(G,1), L1),(pid(G,2), L2), uid=admin, override=True)))
# a free ticket needs no payment
S = setup(); A, admin = S['A'], S['admin']; sql("update settings set resale_min_price=0")
L1 = list_it(S, A, 1, '9000000001', price=0); D = interest([P('Dan','9000000004')])['booking_code']; match((pid(D,1), L1), uid=admin)
r = adm('admin_match_confirm', iid(D), uid=admin); t.check("5.53 a price-0 listing: confirm creates an already-verified payment of 0", ok(r) and r[1][0][0]['amount']==0 and sql("select status, amount_received from transfer_payments")[0]==('verified',0), r)
t.check("5.54 ...and Transfer works straight away", ok(adm('admin_match_transfer', mid(L1), uid=admin)))
# hall full
S = setup(); A, admin = S['A'], S['admin']; L1 = list_it(S, A, 1, '9000000001', price=200); D = interest([P('Dan','9000000004')])['booking_code']; full_flow(S, D, [L1])
sql("update settings set cap=(select count(*) from tickets where transferred_out_at is null)"); base = counts(); sp = pub()
t.check("5.55 HALL FULL: the swap still works", ok(adm('admin_match_transfer', mid(L1), uid=admin)))
t.check("5.56 ...the hall is exactly as full as before; a normal registration is still refused", counts()==base and pub()==sp==0)
sid=uuid.uuid4(); path=shot(sid); rr = call('anon',"select submit_booking(%s,%s::jsonb,%s)",(str(sid),json.dumps([dict(name='Extra',phone='9666666660',email='x@example.com',loc='In Bengaluru',att='Surely',food='Veg')]),path))
t.check("5.57 (NOT_ENOUGH_SPOTS for the normal registration)", rr[0]=='err' and 'NOT_ENOUGH_SPOTS' in rr[1], rr)
# transfers off blocks paying
S = setup(); A, admin = S['A'], S['admin']; L1 = list_it(S, A, 1, '9000000001'); D = interest([P('Dan','9000000004')])['booking_code']
match((pid(D,1), L1), uid=admin); adm('admin_match_confirm', iid(D), uid=admin); payid = str(sql("select id from transfer_payments")[0][0]); sql("update settings set transfers_open=false")
t.check("5.58 transfers switched off: the buyer's payment upload is refused", pay(D,'9000000004',payid)['error']=='TRANSFERS_CLOSED')

# ================= GROUP 6: revoking, releasing, cascades =================
print("-- group 6: revoke, release, cascade")
S = setup(); A, B, admin, gate = S['A'], S['B'], S['admin'], S['gate']
L1 = list_it(S, A, 1, '9000000001', price=200); D = interest([P('Dan','9000000004')])['booking_code']; match((pid(D,1), L1), uid=admin); base = counts()
t.check("6.1 release a HELD match (note too long refused first)", err(adm('admin_match_release', mid(L1), 'x'*301, uid=admin),'INVALID_NOTE') and ok(adm('admin_match_release', mid(L1), 'buyer not reachable', uid=admin)))
t.check("6.2 the listing is available again, the person waits again, no money due", sql("select status from transfers where id=%s",(L1,))[0][0]=='listed' and sql("select status from transfer_interest_people where name='Dan'")[0][0]=='waiting' and sql("select return_due from transfer_matches")[0][0] is False and counts()==base)
t.check("6.3 releasing something already released: NOT_OPEN", err(adm('admin_match_release', mid(L1), None, uid=admin),'NOT_OPEN'))
t.check("6.4 the released pair cannot be matched again (PAIR_RELEASED_BEFORE) unless overridden", err(match((pid(D,1), L1), uid=admin),'PAIR_RELEASED_BEFORE') and ok(match((pid(D,1), L1), uid=admin, override=True)))
adm('admin_match_confirm', iid(D), uid=admin)
t.check("6.5 release after confirmation but BEFORE payment: the payment request is cancelled (void), nothing due", ok(adm('admin_match_release', mid(L1), 'changed mind', uid=admin)) and sql("select status from transfer_payments")[0][0]=='void' and sql("select count(*) from transfer_matches where return_due")[0][0]==0)
t.check("6.6 the buyer's page no longer asks for payment", lk(D,'9000000004')['transfer']['state']=='waiting' and lk(D,'9000000004')['transfer']['payment'] is None)
# release one of several awaiting payment: amount recomputed
S = setup(); A, B, admin = S['A'], S['B'], S['admin']
L1 = list_it(S, A, 1, '9000000001', price=200); L2 = list_it(S, A, 2, '9000000002', price=120, upi='ben@okbank'); E = interest([P('Eve','9000000005'), P('Fay','9000000006')])['booking_code']
match((pid(E,1), L1),(pid(E,2), L2), uid=admin); adm('admin_match_confirm', iid(E), uid=admin); adm('admin_match_release', mid(L2), 'seller out', uid=admin)
t.check("6.7 one of two released before payment: the payment amount drops to the remaining ticket (200)", sql("select amount, status from transfer_payments")[0]==(200,'awaiting') and lk(E,'9000000005')['transfer']['payment']['amount']==200)
# release after payment submitted (not yet verified)
S = setup(); A, B, admin = S['A'], S['B'], S['admin']; L1 = list_it(S, A, 1, '9000000001'); D = interest([P('Dan','9000000004')])['booking_code']; full_flow(S, D, [L1], verify=False)
adm('admin_match_release', mid(L1), 'seller out', uid=admin)
t.check("6.8 release after the payment was uploaded (unverified): return marked due, but NOT counted as held", sql("select return_due from transfer_matches")[0][0] and money(S)['return_due']['amount']==200 and money(S)['held_now']==0)
# listing revoke in each state
for stage in ['listing_pending','listed','held','paid']:
    S = setup(); A, B, admin = S['A'], S['B'], S['admin']
    if stage=='listing_pending': psell(A, label(1), '9000000001'); L1 = tid_of(1)
    else: L1 = list_it(S, A, 1, '9000000001', price=200)
    if stage in ('held','paid'):
        D = interest([P('Dan','9000000004')])['booking_code']
        if stage=='held': match((pid(D,1), L1), uid=admin)
        else: full_flow(S, D, [L1])
    r = adm('admin_listing_revoke', L1, 'seller changed mind', uid=admin)
    t.check(f"6.9 admin revokes a listing in state '{stage}'", ok(r) and sql("select status from transfers where id=%s",(L1,))[0][0]=='withdrawn', r)
    if stage in ('held','paid'):
        t.check(f"6.10 ...the buyer goes back to waiting" + (" and the verified money is marked due" if stage=='paid' else ""), sql("select status from transfer_interest_people where name='Dan'")[0][0]=='waiting' and (sql("select return_due from transfer_matches")[0][0] is (stage=='paid')))
    t.check(f"6.11 ...the seller can list the seat again", psell(A,label(1),'9000000001').get('ok') is True)
# revoke the whole interest
S = setup(); A, B, admin = S['A'], S['B'], S['admin']
L1 = list_it(S, A, 1, '9000000001', price=200); L2 = list_it(S, A, 2, '9000000002', price=120, upi='ben@okbank')
E = interest([P('Eve','9000000005'), P('Fay','9000000006')])['booking_code']; full_flow(S, E, [L1, L2])
adm('admin_match_transfer', mid(L2), uid=admin)
r = adm('admin_interest_revoke', iid(E), 'buyer withdrew', uid=admin)
t.check("6.12 admin revokes an interest after one ticket was already transferred", ok(r) and sql("select status from transfer_interests")[0][0]=='revoked')
t.check("6.13 the not-yet-transferred ticket goes back: listing available, return due for that share only (200)", sql("select status from transfers where id=%s",(L1,))[0][0]=='listed' and money(S)['return_due']=={'count':1,'amount':200})
t.check("6.14 the booking stays 'paid' (one person already has a ticket); the other person shows 'revoked'", sql("select status from bookings where booking_code=%s",(E,))[0][0]=='paid' and lk(E,'9000000006')['tickets'][0]['name']=='Fay' and lk(E,'9000000005')['transfer']['state']=='revoked')
t.check("6.15 revoking again: NOT_OPEN; unknown id: INVALID_INTEREST", err(adm('admin_interest_revoke', iid(E), 'x', uid=admin),'NOT_OPEN') and err(adm('admin_interest_revoke', str(uuid.uuid4()), 'x', uid=admin),'INVALID_INTEREST'))
S = setup(); A, admin = S['A'], S['admin']; D = interest([P('Dan','9000000004')])['booking_code']
adm('admin_interest_revoke', iid(D), 'spam', uid=admin)
t.check("6.16 revoking an interest with no tickets rejects its booking", sql("select status from bookings where booking_code=%s",(D,))[0][0]=='rejected' and lk(D,'9000000004')['transfer']['state']=='revoked')
# buyer self-revoke
S = setup(); A, admin = S['A'], S['admin']; L1 = list_it(S, A, 1, '9000000001', price=200); D = interest([P('Dan','9000000004')])['booking_code']
t.check("6.17 buyer revoke: wrong phone -> MISMATCH", A_("select interest_revoke(%s,%s)",(D,'9555555555'))=={'ok':False,'error':'MISMATCH'})
match((pid(D,1), L1), uid=admin); adm('admin_match_confirm', iid(D), uid=admin)
t.check("6.18 the buyer revokes after a match but before paying: allowed, listing freed", A_("select interest_revoke(%s,%s)",(D,'9000000004'))=={'ok':True} and sql("select status from transfers where id=%s",(L1,))[0][0]=='listed')
t.check("6.19 revoking again: NOT_OPEN", A_("select interest_revoke(%s,%s)",(D,'9000000004'))=={'ok':False,'error':'NOT_OPEN'})
D2 = interest([P('Eve','9000000005')])['booking_code']; full_flow(S, D2, [L1], verify=False)
t.check("6.20 after the buyer sent money, only the organizers can end it: CONTACT_ADMIN", A_("select interest_revoke(%s,%s)",(D2,'9000000005'))=={'ok':False,'error':'CONTACT_ADMIN'})
# seller booking rejected
S = setup(); A, B, admin = S['A'], S['B'], S['admin']
L1 = list_it(S, A, 1, '9000000001', price=200); L2 = list_it(S, A, 2, '9000000002', price=120, upi='ben@okbank')
G = interest([P('Gus','9000000007'), P('Hal','9000000008')], together=True)['booking_code']; full_flow(S, G, [L1, L2])
adm('set_booking_status', str(sql("select id from bookings where booking_code=%s",(A,))[0][0]), 'rejected', uid=admin)
t.check("6.21 the seller's booking rejected: BOTH listings closed", sql("select count(*) from transfers where status='withdrawn' and kind='public'")[0][0]==2)
t.check("6.22 ...the 'all together' buyer's matches all went back with the money due (320), people waiting again", sql("select count(*) from transfer_matches where status='released' and return_due")[0][0]==2 and money(S)['return_due']['amount']==320 and sql("select count(*) from transfer_interest_people where status='waiting'")[0][0]==2)
t.check("6.23 set_booking_status refuses a transfer booking (USE_TRANSFER_TOOLS)", err(adm('set_booking_status', str(sql("select id from bookings where booking_code=%s",(G,))[0][0]), 'paid', uid=admin),'USE_TRANSFER_TOOLS'))

# ================= GROUP 7: privacy, permissions, audit, re-run =================
S = setup(); A, B, admin, gate = S['A'], S['B'], S['admin'], S['gate']
print("-- group 7: privacy, permissions, audit, re-run")
L1 = list_it(S, A, 1, '9000000001', price=200, reason='Secret family reason'); D = interest([P('Dan','9000000004', max_price=210)])['booking_code']; full_flow(S, D, [L1])
buyer_view = json.dumps([lk(D,'9000000004'), A_("select interest_pay(%s,%s,%s,%s,%s)",(D,'9000000004',str(sql("select id from transfer_payments")[0][0]),str(uuid.uuid4()),'x'))])
t.check("7.1 nothing the buyer can read contains the seller's name, phone, UPI, reason, ticket number or Booking ID", not any(k in buyer_view for k in ['Asha','9000000001',UPI,'Secret family reason','E26-001',A]), [k for k in ['Asha','9000000001',UPI,'Secret family reason','E26-001',A] if k in buyer_view])
seller_view = json.dumps([A_("select public_status(%s,%s)",(A,'9000000001')), lk(A,'9000000001')])
t.check("7.2 nothing the seller can read contains the buyer's name, phone, email or Booking ID", not any(k in seller_view for k in ['Dan','9000000004','dan@example.com',D]), [k for k in ['Dan','9000000004','dan@example.com',D] if k in seller_view])
for fn in ['_seller_block(uuid)','_clean_reason(text)','_release_match(uuid,text)','_release_cascade(uuid,text)','_revoke_interest(uuid,text)','_close_open_transfers(uuid,text)']:
    t.check(f"7.3 anon cannot call internal {fn.split('(')[0]}", sql(f"select has_function_privilege('anon','public.{fn}','execute')")[0][0] is False)
adm('admin_match_transfer', mid(L1), uid=admin); adm('admin_transfer_mark_paid', L1, 'UPI-555555', uid=admin)
log = sql("select who, field, old_value, new_value from settings_log where area='transfer' order by id"); blob = json.dumps(log); fields=' | '.join(l[1] for l in log)
t.check("7.4 every step is in the log", all(k in fields for k in ['listing: requested','listing: APPROVED','interest: form submitted','match created','confirmed by buyer','payment submitted','payment VERIFIED','APPROVED','seller PAID']), fields)
t.check("7.5 the log has only 'visitor' and the admin's name", {l[0] for l in log}=={'visitor','Admin One'}, {l[0] for l in log})
t.check("7.6 the log never contains phones, emails, UPI IDs, reasons or QR secrets", not re.search(r'\d{10}', blob) and '@' not in blob and 'Secret family' not in blob and sql("select secret from tickets where ticket_no=1")[0][0] not in blob, blob[:150])
S = setup(); A, B, admin = S['A'], S['B'], S['admin']; L1 = list_it(S, A, 1, '9000000001'); pc = A_("select private_sell(%s,%s,%s)",(A,label(2),'9000000002'))['code']
t.check("7.7 a private code and a public listing on different seats work side by side", A_("select private_open(%s)",(pc,)).get('ok') is True)
D = interest([P('Dan','9000000004')])['booking_code']; match((pid(D,1), L1), uid=admin)
t.check("7.8 a MATCHED listing blocks a private code for that seat (ALREADY_OPEN)", A_("select private_sell(%s,%s,%s)",(A,label(1),'9000000001'))=={'ok':False,'error':'ALREADY_OPEN','kind':'public'})
r = subprocess.run(["psql","-h","/tmp","-p","5544","-q","-d","postgres","-U","postgres","-v","ON_ERROR_STOP=1","-f",FILES[-1]],capture_output=True,text=True)
t.check("7.9 the piece-4 SQL can be applied a second time without errors", r.returncode==0, r.stderr[-300:])
t.check("7.10 ...and everything still works afterwards", ok(adm('admin_match_confirm', iid(D), uid=admin)) and psell(B,label(3),'9000000003').get('ok') is True)
t.report("R2-1 piece 4 tests (public transfer, admin-matched)")
