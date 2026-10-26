from lib import *
import json, uuid, subprocess, os
D='/home/claude/scratch/'; R='/home/claude/ca-meetup-register/sql/'
R10=os.environ.get('R10',R+'r2_10_email_switch.sql')
F=[D+f for f in ['r2_01_prep.sql','r2_02_lookup.sql','r2_02c_close_old_transfer_doors.sql','r2_02b_cutover.sql','r2_03_private_transfer.sql','r2_04_public_via_code.sql','r2_05_cleanup_and_ip.sql','r2_06_transfer_settings.sql']]+[R+'r2_08_coordinator_transfer.sql',R+'r2_09_about_link.sql']
t=T(); fresh(F); S=seed(); admin=S['admin']
gate=uuid.uuid4(); sql("insert into auth.users (id,email) values (%s,'g@t')",(str(gate),)); sql("insert into staff (user_id,name,role) values (%s,'Gate','gate')",(str(gate),))
def book(people):
    sid=uuid.uuid4(); path=f'{sid}.jpg'; sql("insert into storage.objects values ('payment-proofs',%s)",(path,))
    return call('anon',"select submit_booking(%s,%s::jsonb,%s)",(str(sid),json.dumps(people),path))
def person(**kw):
    d=dict(name='Zed',phone='9111111111',email='zed@example.com',loc='In Bengaluru',att='Surely',food='Veg'); d.update(kw); return d
def runfile(p):
    return subprocess.run(["psql","-h","/tmp","-p","5544","-q","-d","postgres","-U","postgres","-v","ON_ERROR_STOP=1","-f",p],capture_output=True,text=True)
t.check("0.1 before piece 10 there is no ask_email column", sql("select count(*) from information_schema.columns where table_name='settings' and column_name='ask_email'")[0][0]==0)
r=runfile(R10); t.check("1.1 piece 10 applies", r.returncode==0, r.stderr[-300:])
r=runfile(R10); t.check("1.2 piece 10 can be run twice safely", r.returncode==0, r.stderr[-300:])
flags=lambda: call('anon',"select get_site_flags()")
t.check("2.1 default: the switch is ON and the flags show it (About stays on too)", flags()==('ok',[({'show_about':True,'ask_email':True},)]), flags())
n0=sql("select count(*) from ticket_emails")[0][0]
r=book([person(email='')]); t.check("2.2 ON: a booking without an email is refused (INVALID_EMAIL)", r[0]=='err' and 'INVALID_EMAIL' in r[1], r)
r=book([person(email='nonsense')]); t.check("2.3 ON: an invalid email is refused", r[0]=='err' and 'INVALID_EMAIL' in r[1], r)
r=book([person(phone='9111111112')]); t.check("2.4 ON: a normal booking works and the email is stored", r[0]=='ok' and sql("select count(*) from ticket_emails")[0][0]==n0+1, r)
sa=lambda role,v,uid=None: call(role,"select admin_set_ask_email(%s)",(v,),uid=uid)
t.check("3.1 visitors cannot change the switch", sa('anon',False)[0]=='err')
r=sa('authenticated',False,gate); t.check("3.2 a gate user cannot (NOT_ALLOWED)", r[0]=='err' and 'NOT_ALLOWED' in r[1], r)
r=sa('authenticated',None,admin); t.check("3.3 a missing value is refused (INVALID_VALUE)", r[0]=='err' and 'INVALID_VALUE' in r[1], r)
r=sa('authenticated',False,admin); t.check("3.4 an admin can switch it OFF", r[0]=='ok' and val(flags())['ask_email'] is False, r)
t.check("3.5 the change is logged with the admin's name", sql("select count(*) from settings_log where field='ask_email' and new_value='false' and who='Admin One'")[0][0]==1)
n1=sql("select count(*) from ticket_emails")[0][0]
r=book([person(phone='9111111113',email='')]); t.check("4.1 OFF: a booking without an email works", r[0]=='ok', r)
r=book([person(phone='9111111114',email='Someone@Example.com')]); t.check("4.2 OFF: an email that is sent anyway is ignored (nothing stored)", r[0]=='ok' and sql("select count(*) from ticket_emails")[0][0]==n1, r)
r=book([person(phone='9111111115',email=''),person(name='Yan',phone='9111111116',email='')]); t.check("4.3 OFF: a group booking without emails works", r[0]=='ok', r)
t.check("4.4 OFF: the admin report still lists those bookings (email empty)", sql("select count(*) from report where email is null")[0][0]>=3)
# transfers
def sell(book_code,label,phone): return call('anon',"select private_sell(%s,%s,%s)",(book_code,label,phone))[1][0][0]
rs=sell(S['A'],'E26-001','9000000001'); code=rs['code']
def tsubmit(code,b): return call('anon',"select transfer_submit(%s,%s,%s::jsonb)",(code,str(uuid.uuid4()),json.dumps(b)))[1][0][0]
buyer=dict(name='Dan Buyer',phone='9000000004',email='',loc='In Bengaluru',att='Surely',food='Veg',consent='true')
r=tsubmit(code,buyer); t.check("5.1 OFF: a transfer buyer without an email can apply", r.get('ok') is True, r)
t.check("5.2 OFF: the buyer record has no email", sql("select email from transfer_buyers")[0][0] is None)
x=str(sql("select id from transfers order by created_at desc limit 1")[0][0])
call('authenticated',"select admin_transfer_confirm_call(%s,true)",(x,),uid=admin); ap=call('authenticated',"select admin_transfer_approve(%s)",(x,),uid=admin)
t.check("5.3 OFF: the admin can complete the transfer", ap[0]=='ok', ap)
t.check("5.4 OFF: the new ticket exists, has no email row, and is a guest", sql("select count(*) from tickets t where phone='9000000004' and kind='guest' and not exists (select 1 from ticket_emails e where e.ticket_id=t.id)")[0][0]==1)
# switch back ON
r=sa('authenticated',True,admin); t.check("6.1 an admin can switch it back ON", r[0]=='ok' and val(flags())['ask_email'] is True)
r=book([person(phone='9111111117',email='')]); t.check("6.2 ON again: email is required again", r[0]=='err' and 'INVALID_EMAIL' in r[1], r)
rs=sell(S['B'],'E26-003','9000000003'); r=tsubmit(rs['code'],buyer|dict(phone='9000000005',email=''))
t.check("6.3 ON again: a transfer buyer without an email is refused (INVALID_EMAIL)", r=={'ok':False,'error':'INVALID_EMAIL'}, r)
r=tsubmit(rs['code'],buyer|dict(phone='9000000005',email='eve@example.com')); t.check("6.4 ON again: with an email it works", r.get('ok') is True, r)
t.check("6.5 emails still readable only by admins (visitors get permission denied)", call('anon',"select email from ticket_emails")[0]=='err')
t.check("6.6 the About switch from piece 9 still works", call('authenticated',"select admin_set_show_about(false)",uid=admin)[0]=='ok' and val(flags())['show_about'] is False)
t.report("test_r2_10: email switch")
