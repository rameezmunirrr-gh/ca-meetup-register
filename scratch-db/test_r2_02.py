from lib import *
import json, uuid
fresh(['/home/claude/scratch/r2_01_prep.sql','/home/claude/scratch/r2_02_lookup.sql'])
OLD=['apply_receive','check_request','close_listing','edit_listing','express_interest','get_transfer_status','list_board','lookup_transfer','manage_ticket','post_listing','start_transfer','submit_transfer_payment','withdraw_transfer']
S = seed(); A, B, admin = S['A'], S['B'], S['admin']
t = T()
NF = {'found': False}
def L(code, phone): 
    r = call('anon', "select lookup_tickets(%s,%s)", (code, phone))
    return r[1][0][0] if r[0]=='ok' else ('ERR', r[1])

# --- the right details
r = L(A, '9000000001')
t.check("right Booking ID + phone returns found", isinstance(r, dict) and r.get('found') is True, r)
names = [x['name'] for x in r.get('tickets', [])]
t.check("Asha's lookup shows ONLY Asha (not Ben)", names==['Asha'], names)
r2 = L(A, '9000000002'); names2 = [x['name'] for x in r2.get('tickets', [])]
t.check("Ben's phone shows ONLY Ben (booker does one lookup per phone)", names2==['Ben'], names2)
t.check("paid booking: QR secret present for the matching person", r['tickets'][0]['secret'] and r['status']=='paid', r['status'])
t.check("email is never returned by the lookup", all('email' not in x for x in r['tickets']), r['tickets'][0].keys())
t.check("tickets are not marked transferred normally", r['tickets'][0]['transferred'] is False, r['tickets'][0])

# --- every failure looks identical
wrong_phone = L(A, '9555555555')            # valid phone, not in this booking
other_booking_phone = L(A, '9000000003')    # Carl's phone with Asha's booking
wrong_code = L('ABCD1234', '9000000001')    # real phone, no such booking
t.check("wrong phone -> exactly {found:false}", wrong_phone==NF, wrong_phone)
t.check("another booking's phone -> exactly {found:false}", other_booking_phone==NF, other_booking_phone)
t.check("wrong Booking ID -> exactly {found:false}", wrong_code==NF, wrong_code)
t.check("all three failures are byte-identical", json.dumps(wrong_phone)==json.dumps(other_booking_phone)==json.dumps(wrong_code))
bad_inputs = [(None,'9000000001'),('', '9000000001'),(A,None),(A,''),(A[:7],'9000000001'),(A+'9','9000000001'),
              (A,'900000000'),(A,'90000000011'),(A,'+919000000001'),(A,'09000000001'),(A,'abcdefghij'),(A,"9000000001' or '1'='1"),
              ("x' or 1=1 --",'9000000001'), (A,'9000000001;drop table tickets')]
for code, ph in bad_inputs:
    t.check(f"bad input gives {{found:false}} and no error: {str(code)[:14]!r},{str(ph)[:22]!r}", L(code, ph)==NF, L(code, ph))

# --- Booking ID cleaning still works as before; phone spaces tolerated
t.check("lower-case Booking ID works", L(A.lower(), '9000000001').get('found') is True)
t.check("spaces and dashes in Booking ID work", L(A[:4]+' - '+A[4:], '9000000001').get('found') is True)
t.check("spaces in phone work", L(A, '90000 00001').get('found') is True)
# letter O for zero (same rule as the old lookup)
if '0' in A:
    t.check("letter O typed for zero works", L(A.replace('0','O'), '9000000001').get('found') is True)

# --- statuses
sql("update bookings set status='pending' where booking_code=%s", (A,))
r = L(A, '9000000001')
t.check("pending booking: found, status pending, NO secret", r.get('found') and r['status']=='pending' and r['tickets'][0]['secret'] is None, r)
sql("update bookings set status='rejected' where booking_code=%s", (A,))
r = L(A, '9000000001')
t.check("rejected booking: status rejected, NO secret", r.get('found') and r['status']=='rejected' and r['tickets'][0]['secret'] is None, r)
sql("update bookings set status='paid' where booking_code=%s", (A,))

# --- same phone for two people in one booking
sid = uuid.uuid4(); path=f'{sid}.jpg'; sql("insert into storage.objects values ('payment-proofs',%s)",(path,))
ppl=[dict(name='Fam1',phone='9333333333',email='f1@example.com',loc='In Bengaluru',att='Surely',food='Veg'),
     dict(name='Fam2',phone='9333333333',email='f2@example.com',loc='In Bengaluru',att='Surely',food='Veg'),
     dict(name='Fam3',phone='9444444444',email='f3@example.com',loc='In Bengaluru',att='Surely',food='Veg')]
call('anon', "select submit_booking(%s,%s::jsonb,%s)", (str(sid), json.dumps(ppl), path))
FC = sql("select booking_code from bookings where id=(select booking_id from tickets where name='Fam1')")[0][0]
r = L(FC, '9333333333')
t.check("one phone on two people returns both of their tickets", sorted(x['name'] for x in r['tickets'])==['Fam1','Fam2'], r)
t.check("pending group booking shows no secrets", all(x['secret'] is None for x in r['tickets']), r)

# --- transferred-out ticket: visible to its own holder as 'transferred', never with a secret
sql("update tickets set transferred_out_at=now() where name='Asha'")
r = L(A, '9000000001')
tk = r['tickets'][0]
t.check("transferred-out ticket shows transferred:true", tk['transferred'] is True, tk)
t.check("transferred-out ticket never returns its QR secret", tk['secret'] is None, tk)
t.check("seller's lookup shows only their own row (no buyer, no other seat)", len(r['tickets'])==1 and r['tickets'][0]['name']=='Asha', r)
sql("update tickets set transferred_out_at=null where name='Asha'")

# --- transfer-kind bookings are not served yet (documented; a later piece adds them)
sql("update bookings set kind='transfer' where booking_code=%s", (B,))
t.check("kind='transfer' booking gives {found:false} for now", L(B, '9000000003')==NF, L(B,'9000000003'))
sql("update bookings set kind='registration' where booking_code=%s", (B,))
t.check("...and works again as a normal booking", L(B, '9000000003').get('found') is True)

# --- the function is read-only and permissions are right
n0 = sql("select count(*) from tickets")[0][0]; L(A,'9000000001'); L(A,'9999999999')
t.check("lookup changes nothing in the database", sql("select count(*) from tickets")[0][0]==n0)
t.check("anonymous visitors may call lookup_tickets", call('anon', "select lookup_tickets(%s,%s)", (A,'9000000001'))[0]=='ok')
t.check("old lookup_booking still exists before the cut-over", call('anon', "select lookup_booking(%s)", (A,))[0]=='ok')

# --- cut-over
import subprocess
r = subprocess.run(["psql","-h","/tmp","-p","5544","-q","-d","postgres","-U","postgres","-v","ON_ERROR_STOP=1","-f","/home/claude/scratch/r2_02b_cutover.sql"],capture_output=True,text=True)
t.check("cut-over SQL runs cleanly", r.returncode==0, r.stderr[-200:])
r = call('anon', "select lookup_booking(%s)", (A,))
t.check("after cut-over a Booking ID alone returns nothing (function is gone)", r[0]=='err' and 'does not exist' in r[1], r)
r = subprocess.run(["psql","-h","/tmp","-p","5544","-q","-d","postgres","-U","postgres","-v","ON_ERROR_STOP=1","-f","/home/claude/scratch/r2_02b_cutover.sql"],capture_output=True,text=True)
t.check("cut-over SQL can be run twice safely", r.returncode==0, r.stderr[-200:])
t.check("new lookup still works after cut-over", L(A,'9000000001').get('found') is True)
t.check("registration response still works (submit_booking unchanged)", call('anon',"select submit_booking(%s,%s::jsonb,%s)",(str(sid),json.dumps(ppl),path))[0]=='ok')

# --- piece 2c: close the old transfer doors
def can(role, fn):
    return sql(f"select bool_or(has_function_privilege('{role}', p.oid, 'execute')) from pg_proc p join pg_namespace n on n.oid=p.pronamespace where n.nspname='public' and p.proname='{fn}'")[0][0]
before = [fn for fn in OLD if can('anon', fn)]
t.check("before 2c: the old transfer functions are callable by anyone", len(before)==13, before)
admin_fns = ['approve_transfer','decline_transfer','admin_confirm_amount','admin_mark_payment_received','admin_mark_seller_paid','admin_mark_refunded','admin_remove_listing','admin_clear_comment','admin_set_transfer_settings']
admin_before = {fn: can('authenticated', fn) for fn in admin_fns}
r = subprocess.run(["psql","-h","/tmp","-p","5544","-q","-d","postgres","-U","postgres","-v","ON_ERROR_STOP=1","-f","/home/claude/scratch/r2_02c_close_old_transfer_doors.sql"],capture_output=True,text=True)
t.check("2c SQL runs cleanly", r.returncode==0, r.stderr[-200:])
after_anon = [fn for fn in OLD if can('anon', fn)]; after_auth = [fn for fn in OLD if can('authenticated', fn)]
t.check("after 2c: none of the 13 old transfer functions is callable by anon", after_anon==[], after_anon)
t.check("after 2c: none is callable by logged-in users either", after_auth==[], after_auth)
res = call('anon', "select manage_ticket('ABCD1234','E26-001')")
t.check("a real call as a visitor is refused with permission denied", res[0]=='err' and 'permission denied' in res[1], res)
res = call('anon', "select lookup_transfer('ABCDEFGHIJ')")
t.check("lookup_transfer (the one that returned QR secrets) is closed", res[0]=='err' and 'permission denied' in res[1], res)
t.check("the admin-only transfer functions are untouched", {fn: can('authenticated', fn) for fn in admin_fns}==admin_before, admin_before)
t.check("the superuser (SQL editor) can still call them", call('postgres', "select list_board()")[0]=='ok')
t.check("registration and the new lookup are unaffected", L(A,'9000000001').get('found') is True and call('anon',"select get_public_status(null)")[0]=='ok')
r = subprocess.run(["psql","-h","/tmp","-p","5544","-q","-d","postgres","-U","postgres","-v","ON_ERROR_STOP=1","-f","/home/claude/scratch/r2_02c_close_old_transfer_doors.sql"],capture_output=True,text=True)
t.check("2c SQL can be run twice safely", r.returncode==0, r.stderr[-200:])

# --- informational: other public functions that still take a Booking ID alone (old transfer code, replaced later)
rows = sql("""select p.proname from pg_proc p join pg_namespace n on n.oid=p.pronamespace
              where n.nspname='public' and has_function_privilege('anon', p.oid, 'execute')
                and pg_get_function_arguments(p.oid) ilike '%%p_code text%%' order by 1""")
print("INFO functions still callable by anyone that take a Booking ID/transfer code (old transfer backend, dropped in a later piece):", [r[0] for r in rows])
t.report("R2-1 piece 2 tests")
