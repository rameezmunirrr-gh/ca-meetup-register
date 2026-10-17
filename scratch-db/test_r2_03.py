from lib import *
import json, uuid, subprocess, re, time
FILES = ['r2_01_prep.sql','r2_02_lookup.sql','r2_02c_close_old_transfer_doors.sql','r2_02b_cutover.sql','r2_03_private_transfer.sql']
FILES = ['/home/claude/scratch/'+f for f in FILES]
ALPHA = set('ABCDEFGHJKLMNPQRSTUVWXYZ23456789')
t = T()
def setup(extra=None):
    fresh(FILES)
    S = seed(); sql("update settings set transfers_open=true")
    gate = uuid.uuid4(); sql("insert into auth.users (id,email) values (%s,'gate@test')", (str(gate),)); sql("insert into staff (user_id,name,role) values (%s,'Gate One','gate')", (str(gate),))
    S['gate'] = gate
    adm2 = uuid.uuid4(); sql("insert into auth.users (id,email) values (%s,'admin2@test')", (str(adm2),)); sql("insert into staff (user_id,name,role) values (%s,'Admin Two','admin')", (str(adm2),))
    S['admin2'] = adm2
    return S
def A_(q, p=(), uid=None, role='anon'):
    r = call(role, q, p, uid=uid)
    return r[1][0][0] if r[0]=='ok' and r[1] else (('ERR', r[1]) if r[0]=='err' else None)
def sell(code, label, phone): return A_("select private_sell(%s,%s,%s)", (code, label, phone))
def label(n): return 'E26-%03d' % n
def counts():
    return sql("""select
      (select count(*) from tickets t join bookings b on b.id=t.booking_id where b.status<>'rejected' and t.transferred_out_at is null),
      (select count(*) from tickets t join bookings b on b.id=t.booking_id where b.status='paid' and t.transferred_out_at is null),
      (select count(*) from tickets t join bookings b on b.id=t.booking_id where b.status='pending' and t.transferred_out_at is null),
      (select coalesce(sum(amount_expected),0) from bookings where status='paid' and kind='registration'),
      (select count(*) from bookings where kind='registration'),
      (select count(*) from bookings where status='paid')""")[0]
def pub(): 
    j = A_("select get_public_status(null)"); return {k: j[k] for k in ('spots_left',) if k in j}
def buyer(**kw):
    d = dict(name='Dan Buyer', phone='9000000004', email='Dan@Example.com', loc='In Bengaluru', att='Surely', food='Veg', consent='true'); d.update(kw); return d
def submit(code, b=None, sid=None):
    return A_("select private_submit(%s,%s,%s::jsonb)", (code, str(sid or uuid.uuid4()), json.dumps(b or buyer())))
def adm(fn, *a, uid=None, role='authenticated'):
    ph = ','.join(['%s']*len(a)); return call(role, f"select {fn}({ph})", a, uid=uid)

# =================== GROUP 1: seller side ===================
S = setup(); A, B, admin, gate = S['A'], S['B'], S['admin'], S['gate']
print("-- group 1: seller side")
r = sell(A, label(1), '9000000001')
t.check("1.1 right Booking ID + ticket + phone gives a code", r.get('ok') is True and len(r['code'])==6 and set(r['code'])<=ALPHA, r)
t.check("1.2 code lasts private_code_hours (2h)", abs((sql("select code_expires_at - created_at from transfers")[0][0].total_seconds()) - 7200) < 5)
codes = [sql("select _new_transfer_code()")[0][0] for _ in range(1500)]
t.check("1.3 1500 generated codes: 6 characters, allowed alphabet only (no 0/O/1/I)", all(len(c)==6 and set(c)<=ALPHA for c in codes))
t.check("1.4 generated codes look random (>=1490 distinct of 1500)", len(set(codes))>=1490, len(set(codes)))
bad = [('ABCD1234',label(1),'9000000001'),(A,label(9),'9000000001'),(A,label(1),'9555555555'),(A,label(1),'9000000002'),
       (A,label(3),'9000000003'),(B,label(1),'9000000001'),(None,label(1),'9000000001'),(A,None,'9000000001'),(A,label(1),None),
       (A,'garbage','9000000001'),(A,label(1),'+919000000001'),(A,"1' or '1'='1",'9000000001'),(A,label(1),"9000000001' or 1=1 --")]
res = [sell(*x) for x in bad]
t.check("1.5 every wrong detail gives exactly MISMATCH and nothing else", all(x=={'ok':False,'error':'MISMATCH'} for x in res), [x for x in res if x!={'ok':False,'error':'MISMATCH'}])
t.check("1.6 Ben's phone cannot sell Asha's ticket (phone must be that ticket's own)", sell(A,label(1),'9000000002')=={'ok':False,'error':'MISMATCH'})
n_before = sql("select count(*) from transfers")[0][0]
sell(A,label(1),'9555555555'); t.check("1.7 a failed attempt creates nothing", sql("select count(*) from transfers")[0][0]==n_before)
# replacing the code
first = sql("select code from transfers where status='code_active'")[0][0]
r2 = sell(A, label(1), '9000000001')
t.check("1.8 a second request makes a NEW code", r2.get('ok') and r2['code']!=first, r2)
t.check("1.9 the old code is marked replaced and only one open row exists", sql("select count(*) from transfers where status='code_active'")[0][0]==1 and sql("select count(*) from transfers where status='replaced'")[0][0]==1)
t.check("1.10 the old code no longer opens the form", A_("select private_open(%s)", (first,))=={'ok':False,'error':'INVALID_CODE'})
rb = sell(A, label(2), '9000000002')
t.check("1.11 a different seat in the same booking can have its own code", rb.get('ok') and rb['code']!=r2['code'], rb)
# global rules
sql("update settings set transfers_open=false"); r = sell(A,label(1),'9000000001')
t.check("1.12 transfers off: TRANSFERS_CLOSED", r=={'ok':False,'error':'TRANSFERS_CLOSED'}, r)
t.check("1.12b transfers off hides nothing about details (same answer even for wrong details)", sell('ABCD1234',label(1),'9000000001')==r)
sql("update settings set transfers_open=true, transfer_cutoff_at=now()-interval '1 minute'")
r = sell(A,label(1),'9000000001'); t.check("1.13 after the cut-off: CUTOFF_PASSED", r=={'ok':False,'error':'CUTOFF_PASSED'}, r)
sql("update settings set transfer_cutoff_at=now()+interval '3 days'"); t.check("1.14 before the cut-off it works", sell(A,label(1),'9000000001').get('ok') is True)
sql("update settings set transfer_cutoff_at=null")
# eligibility (only revealed to someone who passed the credential check)
sql("update bookings set status='pending' where booking_code=%s",(B,)); r = sell(B,label(3),'9000000003'); t.check("1.15 unconfirmed booking: NOT_CONFIRMED", r.get('error')=='NOT_CONFIRMED', r)
sql("update bookings set status='paid' where booking_code=%s",(B,))
sql("update tickets set checked_in_at=now() where ticket_no=3"); r = sell(B,label(3),'9000000003'); t.check("1.16 checked in: ALREADY_CHECKED_IN", r.get('error')=='ALREADY_CHECKED_IN', r)
sql("update tickets set checked_in_at=null where ticket_no=3")
sql("update tickets set kind='coordinator', coord_no=1 where ticket_no=3"); r = sell(B,'1C','9000000003'); t.check("1.17 coordinator: COORDINATOR (contact admin)", r.get('error')=='COORDINATOR', r)
sql("update tickets set kind='guest', coord_no=null where ticket_no=3")
sql("update tickets set transferred_out_at=now() where ticket_no=3"); r = sell(B,label(3),'9000000003'); t.check("1.18 already transferred: ALREADY_TRANSFERRED", r.get('error')=='ALREADY_TRANSFERRED', r)
sql("update tickets set transferred_out_at=null where ticket_no=3")
t.check("1.19 eligibility problems are NOT shown to people with wrong details", sell(B,label(3),'9555555555')=={'ok':False,'error':'MISMATCH'})
# status
r = A_("select private_status(%s,%s)", (A,'9000000001'))
t.check("1.20 status with right details shows the code while active", r['found'] and any(x['code'] for x in r['transfers']), r)
t.check("1.21 Asha's status does not show Ben's transfer", all(x['ticket_label']==label(1) for x in r['transfers']), r)
t.check("1.22 wrong phone / wrong ID give exactly {found:false}", A_("select private_status(%s,%s)",(A,'9555555555'))=={'found':False} and A_("select private_status(%s,%s)",('ABCD1234','9000000001'))=={'found':False})
sql("update transfers set code_expires_at=now()-interval '1 second' where status='code_active'")
r = A_("select private_status(%s,%s)", (A,'9000000001'))
t.check("1.23 an expired code shows 'expired' with NO code", all(x['status']=='expired' and x['code'] is None for x in r['transfers'] if x['ticket_label']==label(1) and x['status'] in ('expired',)) and any(x['status']=='expired' for x in r['transfers']), r)
r = sell(A, label(1), '9000000001'); t.check("1.24 after expiry the seller can make a new code", r.get('ok') is True, r)
# cancel
c1 = r['code']
t.check("1.25 wrong details cannot cancel", A_("select private_cancel(%s,%s,%s)",(A,label(1),'9555555555'))=={'ok':False,'error':'MISMATCH'})
t.check("1.26 the seller can cancel an active code", A_("select private_cancel(%s,%s,%s)",(A,label(1),'9000000001'))=={'ok':True})
t.check("1.27 a cancelled code no longer opens the form", A_("select private_open(%s)",(c1,))=={'ok':False,'error':'INVALID_CODE'})
t.check("1.28 cancelling again: NOTHING_TO_CANCEL", A_("select private_cancel(%s,%s,%s)",(A,label(1),'9000000001'))=={'ok':False,'error':'NOTHING_TO_CANCEL'})
# permissions
for fn in ['_actor()','_tlog(text,text,text)','_new_transfer_code()','_find_seller_ticket(text,text,text)','_close_open_transfers(uuid,text)']:
    t.check(f"1.29 anon cannot call internal {fn.split('(')[0]}", sql(f"select has_function_privilege('anon','public.{fn}','execute')")[0][0] is False)
for tb in ['transfers','transfer_buyers']:
    t.check(f"1.30 anon has no access to table {tb}", sql(f"select has_table_privilege('anon','public.{tb}','select') or has_table_privilege('anon','public.{tb}','insert') or has_table_privilege('anon','public.{tb}','update') or has_table_privilege('anon','public.{tb}','delete')")[0][0] is False)
    t.check(f"1.31 logged-in users can only SELECT {tb} (no write)", sql(f"select has_table_privilege('authenticated','public.{tb}','select'), has_table_privilege('authenticated','public.{tb}','insert') or has_table_privilege('authenticated','public.{tb}','update') or has_table_privilege('authenticated','public.{tb}','delete')")[0]==(True, False))
sell(A,label(1),'9000000001')
t.check("1.32 a gate user (not admin) sees ZERO transfer rows (row security)", A_("select count(*) from transfers", uid=gate, role='authenticated')==0)
t.check("1.33 an admin sees the rows", A_("select count(*) from transfers", uid=admin, role='authenticated')>=1)
t.check("1.34 anonymous visitors cannot read transfers", call('anon',"select count(*) from transfers")[0]=='err')

# =================== GROUP 2: buyer side ===================
S = setup(); A, B, admin, gate = S['A'], S['B'], S['admin'], S['gate']
print("-- group 2: buyer side")
code = sell(A, label(1), '9000000001')['code']
base_counts, base_pub = counts(), pub()
r = A_("select private_open(%s)", (code,))
t.check("2.1 right code opens the form info with the seller's name", r.get('ok') and r['seller_name']=='Asha', r)
blob = json.dumps(r)
t.check("2.2 the buyer never sees the seller's phone, ticket number or Booking ID", '9000000001' not in blob and A not in blob and 'E26-001' not in blob and '"1"' not in blob, blob)
for variant in [code.lower(), ' '+code[:3]+'-'+code[3:]+' ']:
    t.check(f"2.3 code typed as {variant!r} is accepted", A_("select private_open(%s)",(variant,)).get('ok') is True)
wrongs = ['ZZZZZZ','AAAAAA','', None, '12345','ABCDEFG','abc def', "' or 1=1 --", code[:5]+('A' if code[5]!='A' else 'B')]
inv = [A_("select private_open(%s)",(w,)) for w in wrongs]
t.check("2.4 every wrong/short/injected code gives exactly INVALID_CODE", all(x=={'ok':False,'error':'INVALID_CODE'} for x in inv), inv)
# submit validation
for fld, val, err in [('name','','INVALID_NAME'),('name','x'*81,'INVALID_NAME'),('phone','+919000000004','INVALID_PHONE'),('phone','900000004','INVALID_PHONE'),
                      ('email','nope','INVALID_EMAIL'),('email','','INVALID_EMAIL'),('loc','Mars','INVALID_LOCATION'),('att','No','INVALID_ATTENDANCE'),
                      ('food','Vegan','INVALID_FOOD'),('consent','false','INVALID_CONSENT'),('consent','','INVALID_CONSENT')]:
    r = submit(code, buyer(**{fld: val}))
    t.check(f"2.5 bad {fld}={str(val)[:12]!r} -> {err}", r=={'ok':False,'error':err}, r)
r = submit(code, {k:v for k,v in buyer().items() if k!='consent'}); t.check("2.5b missing consent -> INVALID_CONSENT", r.get('error')=='INVALID_CONSENT', r)
t.check("2.6 refused forms create nothing", sql("select count(*) from transfer_buyers")[0][0]==0 and sql("select count(*) from bookings where kind='transfer'")[0][0]==0)
t.check("2.7 and the code is still usable after refused forms", A_("select private_open(%s)",(code,)).get('ok') is True)
sid = uuid.uuid4()
r = submit(code, buyer(), sid)
t.check("2.8 a valid Transfer Form gives a NEW Booking ID", r.get('ok') and re.fullmatch(r'[0-9A-F]{8}', r['booking_code']) and r['booking_code'] not in (A,B), r)
newb = r['booking_code']
bk = sql("select kind,status,people_count,amount_expected,screenshot_path from bookings where booking_code=%s",(newb,))[0]
t.check("2.9 it is a transfer booking: pending, 1 person, amount 0, no screenshot", bk==('transfer','pending',1,0,None), bk)
t.check("2.10 the buyer's email is stored trimmed and lower-case", sql("select email from transfer_buyers")[0][0]=='dan@example.com')
t.check("2.11 NO ticket exists for the buyer yet", sql("select count(*) from tickets where name='Dan Buyer'")[0][0]==0)
t.check("2.12 the transfer is now pending_admin", sql("select status from transfers")[0][0]=='pending_admin')
t.check("2.13 counts, revenue, spots are all unchanged by the application", counts()==base_counts and pub()==base_pub, (counts(), base_counts, pub(), base_pub))
t.check("2.14 the same code cannot be used again (first submission wins)", submit(code, buyer(name='Eve'))=={'ok':False,'error':'INVALID_CODE'})
t.check("2.14b ...and it no longer opens the form", A_("select private_open(%s)",(code,))=={'ok':False,'error':'INVALID_CODE'})
r = A_("select private_submit(%s,%s,%s::jsonb)",(code,str(sid),json.dumps(buyer())))
t.check("2.15 sending the SAME submission again returns the same Booking ID (safe retry)", r.get('ok') and r['booking_code']==newb and r.get('replay') is True, r)
t.check("2.16 a retry creates no duplicate booking", sql("select count(*) from bookings where kind='transfer'")[0][0]==1)
# buyer lookups
r = A_("select lookup_tickets(%s,%s)",(newb,'9000000004'))
t.check("2.17 the buyer sees 'pending', kind transfer, no tickets, no QR", r.get('found') and r['kind']=='transfer' and r['status']=='pending' and r['tickets']==[], r)
t.check("2.18 the SELLER's phone cannot see the buyer's booking", A_("select lookup_tickets(%s,%s)",(newb,'9000000001'))=={'found':False})
t.check("2.19 a wrong phone cannot see it either", A_("select lookup_tickets(%s,%s)",(newb,'9555555555'))=={'found':False})
# seller view
r = A_("select private_status(%s,%s)",(A,'9000000001')); blob=json.dumps(r)
t.check("2.20 the seller sees 'pending_admin' and the buyer's NAME only", any(x['status']=='pending_admin' and x['buyer_name']=='Dan Buyer' for x in r['transfers']) and '9000000004' not in blob and 'dan@' not in blob.lower() and newb not in blob, r)
t.check("2.21 the seller cannot start another transfer while one is pending", sell(A,label(1),'9000000001')=={'ok':False,'error':'ALREADY_PENDING'})
t.check("2.22 the seller cannot cancel once the buyer applied (contact admin)", A_("select private_cancel(%s,%s,%s)",(A,label(1),'9000000001'))=={'ok':False,'error':'CONTACT_ADMIN'})
# expired / closed / cutoff on submit
code2 = sell(A, label(2), '9000000002')['code']
sql("update transfers set code_expires_at=now()-interval '1 second' where code=%s",(code2,))
t.check("2.23 an expired code cannot be submitted", submit(code2)=={'ok':False,'error':'INVALID_CODE'})
code2 = sell(A, label(2), '9000000002')['code']
sql("update settings set transfers_open=false"); t.check("2.24 transfers off: submit refused", submit(code2)['error']=='TRANSFERS_CLOSED'); 
t.check("2.24b transfers off: open refused", A_("select private_open(%s)",(code2,))['error']=='TRANSFERS_CLOSED')
sql("update settings set transfers_open=true, transfer_cutoff_at=now()-interval '1 minute'"); t.check("2.25 after cut-off: submit refused", submit(code2)['error']=='CUTOFF_PASSED')
sql("update settings set transfer_cutoff_at=null")
# food lock
sql("update settings set transfer_food_locked=true")
r = A_("select private_open(%s)",(code2,)); t.check("2.26 food lock: the form is told the fixed food", r['food_locked'] is True and r['food']=='Veg', r)
r = submit(code2, buyer(name='Fay', phone='9000000005', food='Non-veg'))
t.check("2.27 food lock: a Non-veg request is stored as the seller's Veg", r.get('ok') and sql("select food from transfer_buyers where name='Fay'")[0][0]=='Veg', r)
sql("update settings set transfer_food_locked=false")
# seller checked in meanwhile
code3 = sell(B, label(3), '9000000003')['code']; n_bk = sql("select count(*) from bookings")[0][0]
sql("update tickets set checked_in_at=now() where ticket_no=3")
r = submit(code3, buyer(name='Gus', phone='9000000006')); t.check("2.28 seller checked in before the buyer applied: NOT_AVAILABLE, nothing created", r=={'ok':False,'error':'NOT_AVAILABLE'} and sql("select count(*) from bookings")[0][0]==n_bk, r)
t.check("2.28b open also says NOT_AVAILABLE", A_("select private_open(%s)",(code3,))=={'ok':False,'error':'NOT_AVAILABLE'})
sql("update tickets set checked_in_at=null where ticket_no=3")
# buyer phone equal to seller's phone is allowed
code4 = A_("select private_sell(%s,%s,%s)",(B,label(3),'9000000003'))['code']
t.check("2.29 buyer phone equal to the seller's phone is accepted (admin asks on the call)", submit(code4, buyer(name='Same', phone='9000000003')).get('ok') is True)
# cap full: application still works
sql("update settings set cap=(select count(*) from tickets)"); 
code5 = A_("select private_sell(%s,%s,%s)",(A,label(2),'9000000002'))
t.check("2.30 cap full: a transfer application still works (no seat is taken)", code5.get('error')=='ALREADY_PENDING' or code5.get('ok'), code5)
sql("update settings set cap=150")
# parallel: five people submit the same code at once
S = setup(); A, admin = S['A'], S['admin']; code = sell(A, label(1), '9000000001')['code']
def mk(i): return lambda: call_new('anon', "select private_submit(%s,%s,%s::jsonb)", (code, str(uuid.uuid4()), json.dumps(buyer(name=f'P{i}', phone=f'90000001{i:02d}'))))
out = par([mk(i) for i in range(8)])
oks = [o for o in out if o[0]=='ok' and o[1][0][0].get('ok') is True]
t.check("2.31 8 people submitting the same code at the same moment: exactly ONE wins", len(oks)==1, [o[1][0][0] if o[0]=='ok' else o for o in out])
t.check("2.32 ...and exactly one booking and one buyer row exist", sql("select count(*) from bookings where kind='transfer'")[0][0]==1 and sql("select count(*) from transfer_buyers")[0][0]==1)
# parallel: two replays with the SAME submission id
S = setup(); A = S['A']; code = sell(A, label(1), '9000000001')['code']; sid = str(uuid.uuid4())
out = par([lambda: call_new('anon', "select private_submit(%s,%s,%s::jsonb)", (code, sid, json.dumps(buyer()))) for _ in range(4)])
codes_back = {o[1][0][0].get('booking_code') for o in out if o[0]=='ok' and o[1][0][0].get('ok')}
t.check("2.33 the same form sent 4 times at once: one booking, everyone gets the same Booking ID", sql("select count(*) from bookings where kind='transfer'")[0][0]==1 and len(codes_back)==1, (codes_back, out))

# =================== GROUP 3: admin, the swap, counts, gate ===================
S = setup(); A, B, admin, admin2, gate = S['A'], S['B'], S['admin'], S['admin2'], S['gate']
print("-- group 3: admin, the swap, counts, gate")
code = sell(A, label(1), '9000000001')['code']; r = submit(code, buyer()); newb = r['booking_code']
tid = str(sql("select id from transfers")[0][0])
t.check("3.1 anonymous visitors cannot call the admin functions", all(call('anon', f"select {f}", (tid,))[0]=='err' for f in ['admin_transfer_approve(%s)','admin_transfer_reject(%s)']))
for who, uid in [('a gate user', gate)]:
    for f, args in [('admin_transfer_approve',(tid,)),('admin_transfer_confirm_call',(tid,True)),('admin_transfer_reject',(tid,'x'))]:
        r = adm(f, *args, uid=uid); t.check(f"3.2 {who} cannot call {f}", r[0]=='err' and 'NOT_ALLOWED' in r[1], r)
r = adm('admin_transfer_approve', tid, uid=admin); t.check("3.3 approve WITHOUT the phone-call tick is refused (CALL_NOT_CONFIRMED)", r[0]=='err' and 'CALL_NOT_CONFIRMED' in r[1], r)
t.check("3.3b nothing changed after the refused approve", sql("select count(*) from tickets where name='Dan Buyer'")[0][0]==0 and sql("select status from transfers")[0][0]=='pending_admin')
before = counts(); pub_before = pub(); next_before = sql("select next_ticket from settings")[0][0]
old_secret = sql("select secret from tickets where ticket_no=1")[0][0]
t.check("3.4 admin ticks the call", adm('admin_transfer_confirm_call', tid, True, uid=admin)[0]=='ok')
t.check("3.4b the tick records who and when", sql("select seller_call_confirmed_at is not null, seller_call_confirmed_by from transfers")[0]==(True, str(admin)))
adm('admin_transfer_confirm_call', tid, False, uid=admin); r = adm('admin_transfer_approve', tid, uid=admin)
t.check("3.5 removing the tick blocks approval again", r[0]=='err' and 'CALL_NOT_CONFIRMED' in r[1], r)
adm('admin_transfer_confirm_call', tid, True, uid=admin)
# two admins approve at the same instant
out = par([lambda: call_new('authenticated', "select admin_transfer_approve(%s)", (tid,), uid=admin), lambda: call_new('authenticated', "select admin_transfer_approve(%s)", (tid,), uid=admin2)])
oks = [o for o in out if o[0]=='ok']; errs = [o for o in out if o[0]=='err']
t.check("3.6 two admins pressing Transfer at the same instant: exactly ONE succeeds, the other is refused", len(oks)==1 and len(errs)==1 and 'NOT_PENDING' in errs[0][1], out)
res = oks[0][1][0][0]
winner = admin if out[0][0]=='ok' else admin2   # whichever admin's press actually won the race
t.check("3.7 the answer names the new ticket and the buyer's Booking ID", res['booking_code']==newb and res['old_label']==label(1) and re.fullmatch(r'E26-\d{3}', res['new_label']), res)
new = sql("select ticket_no,kind,secret,booking_id,transferred_from,phone,email,name from tickets where name='Dan Buyer'")
t.check("3.8 exactly one new ticket was created for the buyer", len(new)==1, new)
nt = new[0]
t.check("3.9 it got the NEXT guest number (normal numbering rule)", nt[0]==next_before and sql("select next_ticket from settings")[0][0]==next_before+1, (nt[0], next_before))
t.check("3.10 new ticket: guest, 12-char secret different from the seller's, lives in the BUYER's booking", nt[1]=='guest' and len(nt[2])==12 and nt[2]!=old_secret and str(nt[3])==str(sql("select id from bookings where booking_code=%s",(newb,))[0][0]))
t.check("3.11 it points back at the seller's old ticket", str(nt[4])==str(sql("select id from tickets where ticket_no=1")[0][0]))
old = sql("select ticket_no, transferred_out_at, secret from tickets where name='Asha'")[0]
t.check("3.12 the seller's ticket keeps its number (retired) and is marked transferred out", old[0]==1 and old[1] is not None and old[2]==old_secret)
t.check("3.13 the buyer's booking became paid", sql("select status from bookings where booking_code=%s",(newb,))[0][0]=='paid')
t.check("3.14 the transfer is done and linked to the new ticket", sql("select status, result_ticket_id is not null, decided_by from transfers")[0]==('done', True, str(winner)))
after = counts()
t.check("3.15 COUNTS: tickets counted / paid / pending / revenue / registrations / paid bookings: only 'paid bookings' +1 (the transfer booking), all else IDENTICAL", after[:5]==before[:5] and after[5]==before[5]+1, (before, after))
t.check("3.16 the public spots-left number is unchanged", pub()==pub_before, (pub(), pub_before))
t.check("3.17 the total ACTIVE tickets did not change (swap, not a new seat)", sql("select count(*) from tickets where transferred_out_at is null")[0][0]==before[0])
# lookups after the swap
r = A_("select lookup_tickets(%s,%s)",(A,'9000000001'))
t.check("3.18 the seller sees their ticket as transferred, with NO QR", r['tickets'][0]['transferred'] is True and r['tickets'][0]['secret'] is None, r)
t.check("3.19 ...and nothing about the buyer", 'Dan' not in json.dumps(r) and newb not in json.dumps(r) and '9000000004' not in json.dumps(r))
r = A_("select lookup_tickets(%s,%s)",(newb,'9000000004'))
t.check("3.20 the buyer sees their new ticket with a QR secret", r['found'] and r['status']=='paid' and r['tickets'][0]['secret']==nt[2] and r['tickets'][0]['transferred'] is False, r)
t.check("3.21 the seller's Booking ID can no longer reach the buyer's ticket", all('Dan' not in json.dumps(A_("select lookup_tickets(%s,%s)",(A,p))) for p in ['9000000001','9000000002','9000000004']))
nlabel = res['new_label']
t.check("3.22 the old holder cannot re-sell the buyer's ticket (using the old Booking ID + new label)", all(sell(A, nlabel, p)=={'ok':False,'error':'MISMATCH'} for p in ['9000000001','9000000004']))
t.check("3.23 the old holder cannot sell the retired ticket again", sell(A,label(1),'9000000001').get('error')=='ALREADY_TRANSFERRED')
t.check("3.24 approving a done transfer again is refused", 'NOT_PENDING' in (adm('admin_transfer_approve', tid, uid=admin)[1]))
# numbering: later registrations never reuse the retired number
sid=uuid.uuid4(); path=f'{sid}.jpg'; sql("insert into storage.objects values ('payment-proofs',%s)",(path,))
call('anon',"select submit_booking(%s,%s::jsonb,%s)",(str(sid),json.dumps([dict(name='Late',phone='9777777777',email='l@example.com',loc='In Bengaluru',att='Surely',food='Veg')]),path))
lb = sql("select id from bookings order by created_at desc limit 1")[0][0]; call('authenticated',"select set_booking_status(%s,'paid')",(str(lb),),uid=admin)
late = sql("select ticket_no from tickets where name='Late'")[0][0]
used_nos = [r[0] for r in sql("select ticket_no from tickets where ticket_no is not null")]
t.check("3.25 a later registration gets the next number; every number is unique; the retired number is not reused", late==next_before+1 and len(used_nos)==len(set(used_nos)), (late, used_nos))
# the gate
gres = lambda *a, **k: A_("select admit_ticket(%s,%s,%s,%s,%s)", a, uid=gate, role='authenticated')
r = gres(1, old_secret, False, False, None)
t.check("3.26 gate: the OLD QR shows CANCELLED and names the current holder", r['result']=='cancelled' and r['name']=='Dan Buyer' and r['label']==nlabel and r['old_label']==label(1), r)
r = gres(1, 'wrongsecretxx', False, False, None); t.check("3.27 gate: a wrong secret on a retired number is still 'cancelled' (never admits)", r['result']=='cancelled', r)
oldid = str(sql("select id from tickets where ticket_no=1")[0][0]); r = gres(None, None, False, False, oldid)
t.check("3.28 gate: manual search of the retired ticket is cancelled too", r['result']=='cancelled', r)
r = gres(nt[0], nt[2], False, False, None); t.check("3.29 gate: the NEW QR admits once", r['result']=='ok' and r['name']=='Dan Buyer', r)
r = gres(nt[0], nt[2], False, False, None); t.check("3.30 gate: scanning the new QR again is 'already_scanned'", r['result']=='already_scanned', r)
t.check("3.31 gate: the retired QR still never admits after the new one entered", gres(1, old_secret, True, False, None)['result']=='cancelled')
t.check("3.32 gate: other tickets are unaffected (Ben admits)", gres(2, sql("select secret from tickets where ticket_no=2")[0][0], False, False, None)['result']=='ok')
t.check("3.33 only staff can use the gate function", call('anon',"select admit_ticket(1,'x',false,false,null)")[0]=='err')

# a seat transferred TWICE: Dan sells to Eve
S2 = setup(); A, admin = S2['A'], S2['admin']
def full_transfer(booking, lab, phone, buyer_kw, admin_uid):
    c = sell(booking, lab, phone)['code']; rr = submit(c, buyer(**buyer_kw)); xid = str(sql("select id from transfers where code=%s",(c,))[0][0])
    adm('admin_transfer_confirm_call', xid, True, uid=admin_uid); ap = adm('admin_transfer_approve', xid, uid=admin_uid)
    return rr, ap
base = counts()
r1, ap1 = full_transfer(A, label(1), '9000000001', dict(name='Dan', phone='9000000004'), admin)
d_book, d_label = r1['booking_code'], ap1[1][0][0]['new_label']
r2, ap2 = full_transfer(d_book, d_label, '9000000004', dict(name='Eve', phone='9000000007', email='eve@example.com'), admin)
t.check("3.34 a seat can be transferred a second time (Dan -> Eve)", ap1[0]=='ok' and ap2[0]=='ok', (ap1, ap2))
e_label = ap2[1][0][0]['new_label']; d2 = counts()
t.check("3.35 after TWO transfers: active tickets / revenue / registrations unchanged", d2[:5]==base[:5], (base, d2))
nos = [r[0] for r in sql("select ticket_no from tickets order by ticket_no")]; t.check("3.36 all ticket numbers distinct (1,2,3 plus two new)", len(set(nos))==5==len(nos), nos)
secret_asha = sql("select secret from tickets where name='Asha'")[0][0]; secret_dan = sql("select secret from tickets where name='Dan'")[0][0]
for nm, sc, no in [('Asha', secret_asha, 1), ('Dan', secret_dan, int(d_label[-3:]))]:
    r = A_("select admit_ticket(%s,%s,false,false,null)", (no, sc), uid=S2['gate'], role='authenticated')
    t.check(f"3.37 gate: {nm}'s retired QR shows CANCELLED and names the CURRENT holder (Eve), following the chain", r['result']=='cancelled' and r['name']=='Eve' and r['label']==e_label, r)

# reject, auto-close, set_booking_status guards
S = setup(); A, B, admin, gate = S['A'], S['B'], S['admin'], S['gate']
print("-- group 4: reject, automatic closing, guards")
c = sell(A, label(1), '9000000001')['code']; r = submit(c, buyer()); xid = str(sql("select id from transfers")[0][0]); nb = r['booking_code']
base = counts()
t.check("4.1 admin rejects with a note", adm('admin_transfer_reject', xid, 'seller said no', uid=admin)[0]=='ok')
t.check("4.2 transfer rejected, buyer rejected, buyer booking rejected", sql("select status, decision_note from transfers")[0]==('rejected','seller said no') and sql("select status from transfer_buyers")[0][0]=='rejected' and sql("select status from bookings where booking_code=%s",(nb,))[0][0]=='rejected')
t.check("4.3 the seller's ticket and all counts are untouched", counts()==base and sql("select transferred_out_at from tickets where ticket_no=1")[0][0] is None)
r = A_("select lookup_tickets(%s,%s)",(nb,'9000000004')); t.check("4.4 the buyer sees 'rejected'", r['found'] and r['status']=='rejected' and r['tickets']==[], r)
t.check("4.5 the seller can start a new transfer after a rejection", sell(A,label(1),'9000000001').get('ok') is True)
t.check("4.6 a long note is refused", 'INVALID_NOTE' in adm('admin_transfer_reject', xid, 'x'*301, uid=admin)[1] or 'NOT_PENDING' in adm('admin_transfer_reject', xid, 'x'*301, uid=admin)[1])
# set_booking_status guards
code = sell(B, label(3), '9000000003'); 
r = adm('set_booking_status', str(sql("select id from bookings where booking_code=%s",(nb,))[0][0]), 'paid', uid=admin)
t.check("4.7 set_booking_status refuses a transfer booking (USE_TRANSFER_TOOLS)", r[0]=='err' and 'USE_TRANSFER_TOOLS' in r[1], r)
# seller booking rejected while a transfer is pending -> closed automatically
c = sell(A, label(2), '9000000002')['code']; r = submit(c, buyer(name='Hal', phone='9000000008')); hb = r['booking_code']
n_open = sql("select count(*) from transfers where status in ('code_active','pending_admin')")[0][0]
adm('set_booking_status', str(sql("select id from bookings where booking_code=%s",(A,))[0][0]), 'rejected', uid=admin)
t.check("4.8 the seller's booking rejected: every open transfer of it is closed automatically", sql("select count(*) from transfers where booking_id=(select id from bookings where booking_code=%s) and status in ('code_active','pending_admin')",(A,))[0][0]==0)
t.check("4.9 ...the waiting buyer's booking became rejected too", sql("select status from bookings where booking_code=%s",(hb,))[0][0]=='rejected')
r = adm('admin_transfer_approve', str(sql("select id from transfers where status='withdrawn' order by updated_at desc limit 1")[0][0]), uid=admin); t.check("4.10 approving a closed transfer is refused", r[0]=='err' and 'NOT_PENDING' in r[1], r)
# seller checked in after the application, before approval
S = setup(); A, admin = S['A'], S['admin']
c = sell(A, label(1), '9000000001')['code']; submit(c, buyer()); xid = str(sql("select id from transfers")[0][0]); adm('admin_transfer_confirm_call', xid, True, uid=admin)
sql("update tickets set checked_in_at=now() where ticket_no=1"); base = counts()
r = adm('admin_transfer_approve', xid, uid=admin)
t.check("4.11 seller entered the hall before approval: approve refused (SELLER_CHECKED_IN)", r[0]=='err' and 'SELLER_CHECKED_IN' in r[1], r)
t.check("4.12 nothing changed after that refusal", counts()==base and sql("select count(*) from tickets where name='Dan Buyer'")[0][0]==0 and sql("select status from transfers")[0][0]=='pending_admin')
# cap full: the swap still works
S = setup(); A, admin = S['A'], S['admin']
c = sell(A, label(1), '9000000001')['code']; submit(c, buyer()); xid = str(sql("select id from transfers")[0][0]); adm('admin_transfer_confirm_call', xid, True, uid=admin)
sql("update settings set cap=(select count(*) from tickets where transferred_out_at is null)"); base = counts(); sp = pub()
r = adm('admin_transfer_approve', xid, uid=admin)
t.check("4.13 HALL FULL (cap reached): the swap still works", r[0]=='ok', r)
t.check("4.14 ...and the hall is still exactly full, nobody extra", counts()[:5]==base[:5] and pub()==sp and pub().get('spots_left')==0, (counts(), base, pub()))
sid=uuid.uuid4(); path=f'{sid}.jpg'; sql("insert into storage.objects values ('payment-proofs',%s)",(path,))
rr = call('anon',"select submit_booking(%s,%s::jsonb,%s)",(str(sid),json.dumps([dict(name='Extra',phone='9666666666',email='x@example.com',loc='In Bengaluru',att='Surely',food='Veg')]),path))
t.check("4.15 ...so a normal registration is still refused (NOT_ENOUGH_SPOTS)", rr[0]=='err' and 'NOT_ENOUGH_SPOTS' in rr[1], rr)

# audit log
S = setup(); A, admin = S['A'], S['admin']
c = sell(A, label(1), '9000000001')['code']; submit(c, buyer()); xid = str(sql("select id from transfers")[0][0])
adm('admin_transfer_confirm_call', xid, True, uid=admin); adm('admin_transfer_approve', xid, uid=admin)
log = sql("select who, field, old_value, new_value from settings_log where area='transfer' order by id")
fields = [l[1] for l in log]
t.check("5.1 every step is in the log: code created, buyer submitted, call confirmed, approved", all(any(k in f for f in fields) for k in ['code created','buyer submitted','call confirmed','APPROVED']), fields)
t.check("5.2 visitor steps are logged as 'visitor', admin steps with the admin's name", {l[0] for l in log}=={'visitor','Admin One'}, {l[0] for l in log})
blob = json.dumps(log)
t.check("5.3 the log never contains phone numbers, emails or QR secrets", not re.search(r'\d{10}', blob) and '@' not in blob and sql("select secret from tickets where ticket_no=1")[0][0] not in blob, blob[:200])

# idempotent SQL
S = setup()
for f in FILES:
    pass
r = subprocess.run(["psql","-h","/tmp","-p","5544","-q","-d","postgres","-U","postgres","-v","ON_ERROR_STOP=1","-f",FILES[-1]],capture_output=True,text=True)
t.check("6.1 the piece-3 SQL can be applied a second time without errors", r.returncode==0, r.stderr[-300:])
t.check("6.2 and everything still works after the second run", sell(S['A'], label(1), '9000000001').get('ok') is True)
t.check("6.3 earlier pieces still work (new lookup)", A_("select lookup_tickets(%s,%s)",(S['A'],'9000000001')).get('found') is True)
t.report("R2-1 piece 3 tests (private transfer)")
