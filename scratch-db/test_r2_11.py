from lib import *
import json, uuid, subprocess, os
D='/home/claude/scratch/'; R='/home/claude/ca-meetup-register/sql/'
R11=os.environ.get('R11',R+'r2_11_feedback.sql')
F=[D+f for f in ['r2_01_prep.sql','r2_02_lookup.sql','r2_02c_close_old_transfer_doors.sql','r2_02b_cutover.sql','r2_03_private_transfer.sql','r2_04_public_via_code.sql','r2_05_cleanup_and_ip.sql','r2_06_transfer_settings.sql']]+[R+'r2_08_coordinator_transfer.sql',R+'r2_09_about_link.sql',R+'r2_10_email_switch.sql']
t=T(); fresh(F); S=seed(); admin=S['admin']
gate=uuid.uuid4(); sql("insert into auth.users (id,email) values (%s,'g@t')",(str(gate),)); sql("insert into staff (user_id,name,role) values (%s,'Gate','gate')",(str(gate),))
def runfile(p): return subprocess.run(["psql","-h","/tmp","-p","5544","-q","-d","postgres","-U","postgres","-v","ON_ERROR_STOP=1","-f",p],capture_output=True,text=True)
sid=uuid.uuid4(); path=f'{sid}.jpg'; sql("insert into storage.objects values ('payment-proofs',%s)",(path,))
bk=call('anon',"select submit_booking(%s,%s::jsonb,%s)",(str(sid),json.dumps([dict(name='Zed',phone='9111111111',email='z@example.com',loc='In Bengaluru',att='Surely',food='Veg')]),path))
code=bk[1][0][0]['booking_code']
t.check("0.1 before piece 11 there is no feedback table", sql("select count(*) from information_schema.tables where table_name='booking_feedback'")[0][0]==0)
r=runfile(R11); t.check("1.1 piece 11 applies", r.returncode==0, r.stderr[-300:])
r=runfile(R11); t.check("1.2 piece 11 can be run twice safely", r.returncode==0, r.stderr[-300:])
flags=lambda: call('anon',"select get_site_flags()")[1][0][0]
t.check("2.1 flags show all three switches, feedback ON by default", flags()=={'show_about':True,'ask_email':True,'ask_feedback':True}, flags())
fb=lambda c,r_,m,role='anon': call(role,"select submit_feedback(%s,%s,%s)",(c,r_,m))
def res(x): return x[1][0][0] if x[0]=='ok' else x
cnt=lambda: sql("select count(*) from booking_feedback")[0][0]
t.check("3.1 rating + comment saved", res(fb(code,5,'Cannot wait!'))=={'ok':True} and cnt()==1)
t.check("3.2 the code is accepted in lower case with spaces", res(fb(' '+code.lower()+' ',4,'Second'))=={'ok':True} and cnt()==1 and sql("select rating,comment from booking_feedback")[0]==(4,'Second'))
t.check("3.3 only a rating is fine (comment empty)", res(fb(code,3,'   '))=={'ok':True} and sql("select rating,comment from booking_feedback")[0]==(3,None))
t.check("3.4 only a comment is fine (no rating)", res(fb(code,None,'Idea: more snacks'))=={'ok':True} and sql("select rating,comment from booking_feedback")[0]==(None,'Idea: more snacks'))
t.check("3.5 both empty refused", res(fb(code,None,' '))=={'ok':False,'error':'EMPTY_FEEDBACK'})
t.check("3.6 rating 0 and 6 refused", res(fb(code,0,'x'))['error']=='INVALID_RATING' and res(fb(code,6,'x'))['error']=='INVALID_RATING')
t.check("3.7 a comment over 1000 characters refused", res(fb(code,3,'a'*1001))=={'ok':False,'error':'INVALID_COMMENT'})
t.check("3.8 exactly 1000 characters accepted", res(fb(code,3,'a'*1000))=={'ok':True})
t.check("3.9 unknown booking ID refused", res(fb('ZZZZZZZZ',3,'x'))=={'ok':False,'error':'BOOKING_NOT_FOUND'} and res(fb(None,3,'x'))['error']=='BOOKING_NOT_FOUND')
t.check("3.10 a refused answer leaves the saved one untouched", sql("select rating,char_length(comment) from booking_feedback")[0]==(3,1000))
t.check("3.11 a transfer booking ID is refused", (lambda c: c is None or res(fb(c,3,'x'))['error']=='BOOKING_NOT_FOUND')((sql("select booking_code from bookings where kind='transfer' limit 1") or [[None]])[0][0]))
t.check("4.1 visitors cannot read the answers", call('anon',"select * from booking_feedback")[0]=='err')
t.check("4.2 a gate user sees none", call('authenticated',"select count(*) from booking_feedback",uid=gate)[1][0][0]==0)
t.check("4.3 an admin can read them", call('authenticated',"select count(*) from booking_feedback",uid=admin)[1][0][0]==1)
t.check("4.4 visitors cannot write the table directly", call('anon',"insert into booking_feedback (booking_id,rating) select id,3 from bookings")[0]=='err')
sa=lambda role,v,uid=None: call(role,"select admin_set_ask_feedback(%s)",(v,),uid=uid)
t.check("5.1 visitors cannot change the switch", sa('anon',False)[0]=='err')
r=sa('authenticated',False,gate); t.check("5.2 gate user: NOT_ALLOWED", r[0]=='err' and 'NOT_ALLOWED' in r[1], r)
r=sa('authenticated',None,admin); t.check("5.3 missing value: INVALID_VALUE", r[0]=='err' and 'INVALID_VALUE' in r[1], r)
r=sa('authenticated',False,admin); t.check("5.4 admin switches OFF", r[0]=='ok' and flags()['ask_feedback'] is False and flags()['ask_email'] is True)
t.check("5.5 the change is logged", sql("select count(*) from settings_log where field='ask_feedback' and new_value='false' and who='Admin One'")[0][0]==1)
t.check("5.6 OFF: new answers refused (FEEDBACK_OFF), saved ones kept", res(fb(code,5,'x'))=={'ok':False,'error':'FEEDBACK_OFF'} and cnt()==1)
t.check("5.7 admin switches ON again and answers work", sa('authenticated',True,admin)[0]=='ok' and res(fb(code,2,'back'))=={'ok':True})
t.check("6.1 the clean-up (truncate bookings cascade) also empties the answers", (sql("truncate table bookings cascade") or True) and cnt()==0)
t.check("6.2 the email switch still works and keeps the feedback flag", call('authenticated',"select admin_set_ask_email(false)",uid=admin)[0]=='ok' and flags()=={'show_about':True,'ask_email':False,'ask_feedback':True})
t.report("test_r2_11: feedback")
