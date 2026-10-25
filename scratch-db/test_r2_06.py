from lib import *
import json, uuid, subprocess, re
F = ['r2_01_prep.sql','r2_02_lookup.sql','r2_02c_close_old_transfer_doors.sql','r2_02b_cutover.sql','r2_03_private_transfer.sql','r2_04_public_via_code.sql','r2_05_cleanup_and_ip.sql','r2_06_transfer_settings.sql']
FILES = ['/home/claude/scratch/'+f for f in F]
t = T()
def setup():
    fresh(FILES); S = seed(); sql("update settings set transfers_open=false")
    for nm, role, k in [('gate','gate','Gate One'),('admin2','admin','Admin Two')]:
        u = uuid.uuid4(); sql("insert into auth.users (id,email) values (%s,%s)", (str(u), nm+'@test')); sql("insert into staff (user_id,name,role) values (%s,%s,%s)", (str(u), k, role)); S[nm] = u
    return S
def A_(q, p=(), uid=None, role='anon'):
    r = call(role, q, p, uid=uid)
    return r[1][0][0] if r[0]=='ok' and r[1] else (('ERR', r[1]) if r[0]=='err' else None)
def setx(*a, uid=None, role='authenticated', **kw):
    # call with named arguments: admin_set_transfer_settings(p_open => true, ...)
    names = ', '.join(f"{k} => %s" for k in kw)
    return call(role, f"select admin_set_transfer_settings({names})", tuple(kw.values()), uid=uid)
def ok(r): return r[0]=='ok'
def err(r, w): return r[0]=='err' and w in r[1]
def label(n): return 'E26-%03d' % n
def row(): return sql("select transfers_open, transfer_cutoff_at, transfer_food_locked, private_code_hours, ip_flag_threshold from settings where id=1")[0]

S = setup(); admin = S['admin']; admin2 = S['admin2']; gate = S['gate']

# ---------------------------------------------------------------- 1. who may call it
r0 = row()
LOGQ = "select count(*) from settings_log where field in ('transfers_open','transfer_cutoff_at','transfer_food_locked','private_code_hours','ip_flag_threshold')"
log0 = sql(LOGQ)[0][0]
t.check("1.1 starting state: transfers off, no cut-off, food unlocked, 2-hour codes, threshold 5", r0==(False,None,False,2,5), r0)
for who, uid, nm in [('anon',None,'a visitor'),('authenticated',gate,'gate staff'),('authenticated',uuid.uuid4(),'a logged-in stranger who is not staff')]:
    r = setx(role=who, uid=uid, p_open=True)
    t.check(f"1.2 {nm} cannot change transfer settings", r[0]=='err', r)
    t.check(f"1.2b ...and nothing changed ({nm})", row()==r0, row())
r = call('authenticated', "update settings set transfers_open=true", uid=admin)
t.check("1.3 even an admin cannot write the settings table directly (only through functions)", r[0]=='err', r)
r = call('authenticated', "select admin_set_transfer_settings(p_open => true)", uid=gate)
t.check("1.4 gate staff are refused with NOT_ALLOWED (the function checks the role itself, not only the grant)",
        err(r,'NOT_ALLOWED') or err(r,'permission denied'), r)

# ---------------------------------------------------------------- 2. validation: every bad value refused, nothing half-applied
bad = [(dict(p_code_hours=0),'INVALID_HOURS'), (dict(p_code_hours=169),'INVALID_HOURS'), (dict(p_code_hours=-5),'INVALID_HOURS'),
       (dict(p_ip_threshold=1),'INVALID_THRESHOLD'), (dict(p_ip_threshold=1001),'INVALID_THRESHOLD'), (dict(p_ip_threshold=0),'INVALID_THRESHOLD')]
for kw, code in bad:
    r = setx(uid=admin, **kw)
    t.check(f"2.1 bad value refused with the clear code {code}: {kw}", err(r, code), r)
r = setx(uid=admin, p_cutoff='2030-01-01 00:00+05:30', p_clear_cutoff=True)
t.check("2.2 a cut-off and 'clear the cut-off' in the same call is refused (INVALID_CUTOFF)", err(r,'INVALID_CUTOFF'), r)
r = setx(uid=admin, p_food_locked=True, p_code_hours=500)
t.check("2.3 one bad value refuses the WHOLE call: the good food-lock change is not applied either", r[0]=='err' and row()==r0, (r, row()))
t.check("2.4 refused calls wrote nothing to the settings log", sql(LOGQ)[0][0]==log0, (sql(LOGQ)[0][0], log0))

# ---------------------------------------------------------------- 3. the payment-details guard
sql("update settings set upi_id=null, payee_name=null, whatsapp_number=null")
r = setx(uid=admin, p_open=True)
t.check("3.1 cannot switch transfers ON while payment details are not set up (PAYMENT_INFO_MISSING)", err(r,'PAYMENT_INFO_MISSING') and row()[0] is False, r)
for col in ('upi_id','payee_name','whatsapp_number'):
    sql("update settings set upi_id='test@upi', payee_name='Test', whatsapp_number='919999999999'")
    sql(f"update settings set {col}=null")
    r = setx(uid=admin, p_open=True)
    t.check(f"3.2 missing only {col}: still refused", err(r,'PAYMENT_INFO_MISSING'), r)
r = setx(uid=admin, p_code_hours=6, p_food_locked=True)
t.check("3.3 other transfer settings can still be changed while payment details are missing", ok(r) and row()[2] is True and row()[3]==6, (r,row()))
sql("update settings set upi_id='test@upi', payee_name='Test', whatsapp_number='919999999999', transfer_food_locked=false, private_code_hours=2")
sql("update settings set upi_id=null, payee_name=null, whatsapp_number=null, transfers_open=true")
r = setx(uid=admin, p_open=False)
t.check("3.4 turning transfers OFF always works, even with payment details missing", ok(r) and row()[0] is False, (r,row()))
sql("update settings set upi_id='test@upi', payee_name='Test', whatsapp_number='919999999999'")

# ---------------------------------------------------------------- 4. each setting changes, alone and in combination; null keeps
r = setx(uid=admin, p_open=True)
t.check("4.1 admin turns transfers ON", ok(r) and row()[0] is True, (r,row()))
r = setx(uid=admin, p_code_hours=12)
t.check("4.2 changing only the code lifetime keeps everything else", ok(r) and row()==(True,None,False,12,5), row())
r = setx(uid=admin, p_cutoff='2030-05-01 18:00+05:30')
c = sql("select transfer_cutoff_at from settings")[0][0]
t.check("4.3 admin sets a cut-off; the rest is kept", ok(r) and c is not None and row()[0] is True and row()[3]==12, (r, c))
r = setx(uid=admin, p_food_locked=True, p_ip_threshold=7)
t.check("4.4 two settings at once; cut-off still kept", ok(r) and row()[2] is True and row()[4]==7 and row()[1] is not None, row())
r = setx(uid=admin)
t.check("4.5 a call with nothing to change is harmless", ok(r) and row()[2] is True and row()[4]==7, (r,row()))
r = setx(uid=admin, p_clear_cutoff=True)
t.check("4.6 admin clears the cut-off; the rest is kept", ok(r) and row()[1] is None and row()[3]==12 and row()[0] is True, row())
r = setx(uid=admin, p_clear_cutoff=True)
t.check("4.7 clearing a cut-off that is already empty is harmless", ok(r) and row()[1] is None, r)
for h in (1, 168):
    r = setx(uid=admin, p_code_hours=h); t.check(f"4.8 boundary value accepted: {h} hours", ok(r) and row()[3]==h, r)
for th in (2, 1000):
    r = setx(uid=admin, p_ip_threshold=th); t.check(f"4.9 boundary value accepted: threshold {th}", ok(r) and row()[4]==th, r)
r = setx(uid=admin2, p_food_locked=False)
t.check("4.10 a second admin may also change settings (every admin has the authority)", ok(r) and row()[2] is False, r)

# ---------------------------------------------------------------- 5. the settings log
lg = sql("select who, field from settings_log where field in ('transfers_open','transfer_cutoff_at','transfer_food_locked','private_code_hours','ip_flag_threshold') order by at, id")
fields = {f for _, f in lg}
t.check("5.1 every changed setting is written to the settings log", {'transfers_open','transfer_cutoff_at','transfer_food_locked','private_code_hours','ip_flag_threshold'} <= fields, fields)
t.check("5.2 the log names the admin who did it", ('Admin One','transfers_open') in lg and ('Admin Two','transfer_food_locked') in lg, lg[:6])
blob = json.dumps(sql("select field, old_value, new_value from settings_log where field in ('transfers_open','transfer_cutoff_at','transfer_food_locked','private_code_hours','ip_flag_threshold')"), default=str)
t.check("5.3 the log holds no UPI ID or phone number", 'test@upi' not in blob and '919999999999' not in blob and not re.search(r'\d{10}', blob))

# ---------------------------------------------------------------- 6. get_transfer_info for visitors
sql("update settings set transfers_open=true, transfer_cutoff_at=null, transfer_food_locked=false, private_code_hours=2, price_per_head=250")
g = A_("select get_transfer_info()")
t.check("6.1 visitors get exactly these fields and nothing else", set(g)=={'open','cutoff_at','cutoff_passed','food_locked','code_hours','ask_price','server_now'}, sorted(g))
t.check("6.2 values: open, no cut-off, food free, 2-hour codes, price 250", g['open'] is True and g['cutoff_at'] is None and g['cutoff_passed'] is False and g['food_locked'] is False and g['code_hours']==2 and g['ask_price']==250, g)
t.check("6.3 works without any login", call('anon', "select get_transfer_info()")[0]=='ok')
t.check("6.4 and for logged-in users", call('authenticated', "select get_transfer_info()", uid=gate)[0]=='ok')
sql("update settings set transfers_open=false"); t.check("6.5 reports closed when transfers are off", A_("select get_transfer_info()")['open'] is False)
sql("update settings set transfers_open=true, transfer_cutoff_at=now()+interval '1 day'"); g = A_("select get_transfer_info()")
t.check("6.6 a future cut-off: given, not yet passed", g['cutoff_at'] is not None and g['cutoff_passed'] is False, g)
sql("update settings set transfer_cutoff_at=now()-interval '1 minute'"); g = A_("select get_transfer_info()")
t.check("6.7 a past cut-off: passed", g['cutoff_passed'] is True, g)
sql("update settings set transfer_food_locked=true, private_code_hours=9, price_per_head=300"); g = A_("select get_transfer_info()")
t.check("6.8 food lock, code hours and the asked price follow the settings", g['food_locked'] is True and g['code_hours']==9 and g['ask_price']==300, g)
t.check("6.9 the answer carries no payment details or contact numbers", not re.search(r'test@upi|919999999999|Test', json.dumps(g)), g)
r = call('anon', "select admin_set_transfer_settings(p_open => true)")
t.check("6.10 a visitor cannot run the admin function (no execute right)", r[0]=='err' and 'permission denied' in r[1], r)
sql("update settings set transfer_cutoff_at=null, transfer_food_locked=false, private_code_hours=2, price_per_head=250")

# ---------------------------------------------------------------- 7. the settings really control behaviour
A, B = S['A'], S['B']
setx(uid=admin, p_open=False)
r = A_("select private_sell(%s,%s,%s)", (A, label(1), '9000000001'))
t.check("7.1 off through the function: selling is refused (TRANSFERS_CLOSED)", r.get('error')=='TRANSFERS_CLOSED', r)
setx(uid=admin, p_open=True)
r = A_("select private_sell(%s,%s,%s)", (A, label(1), '9000000001'))
t.check("7.2 on through the function: a code is issued", r.get('ok') is True, r)
code1 = r['code']
setx(uid=admin, p_code_hours=5)
r = A_("select private_sell(%s,%s,%s)", (A, label(1), '9000000001'))
t.check("7.3 a new 5-hour setting gives a 5-hour code", r.get('ok') is True and r['hours']==5, r); code2 = r['code']
setx(uid=admin, p_food_locked=True)
o = A_("select transfer_open(%s)", (code2,))
t.check("7.4 food lock switched on through the function: the buyer form is told to lock the food", o.get('ok') is True and o['food_locked'] is True and o.get('food')=='Veg', o)
setx(uid=admin, p_cutoff='2020-01-01 00:00+05:30')
r = A_("select private_sell(%s,%s,%s)", (B, label(3), '9000000003'))
t.check("7.5 a cut-off in the past blocks new codes (CUTOFF_PASSED)", r.get('error')=='CUTOFF_PASSED', r)
o = A_("select transfer_open(%s)", (code2,))
t.check("7.6 ...and the buyer form (CUTOFF_PASSED)", o.get('error')=='CUTOFF_PASSED', o)
setx(uid=admin, p_clear_cutoff=True)
r = A_("select private_sell(%s,%s,%s)", (B, label(3), '9000000003'))
t.check("7.7 clearing the cut-off through the function re-opens new codes", r.get('ok') is True, r)
setx(uid=admin, p_ip_threshold=2)
t.check("7.8 the IP flag threshold change is used by admin_ip_flags", A_("select admin_ip_flags()", uid=admin, role='authenticated')['threshold']==2)
setx(uid=admin, p_open=False)
t.check("7.9 turning off blocks the buyer form right away (TRANSFERS_CLOSED)", A_("select transfer_open(%s)", (code2,)).get('error')=='TRANSFERS_CLOSED')
t.check("7.10 registration is unaffected by any of this", call('anon', "select get_public_status(null)")[0]=='ok')

# ---------------------------------------------------------------- 8. two admins at the same instant
out = par([lambda: call_new('authenticated', "select admin_set_transfer_settings(p_code_hours => 3)", uid=admin),
           lambda: call_new('authenticated', "select admin_set_transfer_settings(p_food_locked => false)", uid=admin2)])
t.check("8.1 two admins saving different settings together: both succeed", all(o[0]=='ok' for o in out), out)
t.check("8.2 ...and both changes are kept (the settings row is locked, nothing is lost)", row()[3]==3 and row()[2] is False, row())
out = par([lambda: call_new('authenticated', "select admin_set_transfer_settings(p_code_hours => 10)", uid=admin),
           lambda: call_new('authenticated', "select admin_set_transfer_settings(p_code_hours => 20)", uid=admin2)])
t.check("8.3 two admins saving the SAME setting together: both succeed and one value wins", all(o[0]=='ok' for o in out) and row()[3] in (10, 20), (out, row()))

# ---------------------------------------------------------------- 9. file can be run again, rights are as intended
r = subprocess.run(["psql","-h","/tmp","-p","5544","-q","-d","postgres","-U","postgres","-v","ON_ERROR_STOP=1","-f",FILES[-1]],capture_output=True,text=True)
t.check("9.1 piece 6 can be run twice safely", r.returncode==0, r.stderr[-200:])
t.check("9.2 still works after the second run", ok(setx(uid=admin, p_code_hours=2)) and row()[3]==2)
can = lambda role, fn: sql(f"select bool_or(has_function_privilege('{role}', p.oid, 'execute')) from pg_proc p where p.pronamespace='public'::regnamespace and p.proname='{fn}'")[0][0]
t.check("9.3 execute rights: admin function not for anon, get_transfer_info for everyone",
        can('anon','admin_set_transfer_settings') is False and can('authenticated','admin_set_transfer_settings') is True
        and can('anon','get_transfer_info') is True and can('authenticated','get_transfer_info') is True)
t.check("9.4 the admin function is a single, unambiguous signature (no leftover old overload)", sql("select count(*) from pg_proc where pronamespace='public'::regnamespace and proname='admin_set_transfer_settings'")[0][0]==1)

# ---------------------------------------------------------------- 10. earlier pieces unaffected: the whole stack
t.check("10.1 still exactly one settings row", sql("select count(*) from settings")[0][0]==1)
t.check("10.2 emails still admin-only", call('authenticated',"select count(*) from ticket_emails", uid=gate)[1][0][0]==0)
t.report("R2-1 piece 6 tests")
