from lib import *
import json, uuid, subprocess
D='/home/claude/ca-meetup-register/scratch-db/'; R='/home/claude/ca-meetup-register/sql/'
F=[D+f for f in ['r2_01_prep.sql','r2_02_lookup.sql','r2_02c_close_old_transfer_doors.sql','r2_02b_cutover.sql','r2_03_private_transfer.sql','r2_04_public_via_code.sql','r2_05_cleanup_and_ip.sql','r2_06_transfer_settings.sql']]+[R+'r2_08_coordinator_transfer.sql']
t=T(); fresh(F); S=seed()
gate=uuid.uuid4(); sql("insert into auth.users (id,email) values (%s,'g@t')",(str(gate),)); sql("insert into staff (user_id,name,role) values (%s,'Gate','gate')",(str(gate),))
rows=sql("select count(*) from information_schema.columns where table_name='settings' and column_name='show_about'")[0][0]
t.check("0.1 before piece 9 there is no show_about column (the test sees the difference)", rows==0)
rr=subprocess.run(["psql","-h","/tmp","-p","5544","-q","-d","postgres","-U","postgres","-v","ON_ERROR_STOP=1","-f",R+"r2_09_about_link.sql"],capture_output=True,text=True)
t.check("1.1 piece 9 applies", rr.returncode==0, rr.stderr[-300:])
rr=subprocess.run(["psql","-h","/tmp","-p","5544","-q","-d","postgres","-U","postgres","-v","ON_ERROR_STOP=1","-f",R+"r2_09_about_link.sql"],capture_output=True,text=True)
t.check("1.2 piece 9 can be run twice safely", rr.returncode==0, rr.stderr[-300:])
g=lambda role,uid=None: call(role,"select get_site_flags()",uid=uid)
t.check("2.1 default: the About link is ON", g('anon')==('ok',[({'show_about':True},)]), g('anon'))
t.check("2.2 logged-in staff can read the flags too", g('authenticated',gate)[0]=='ok')
sa=lambda role,v,uid=None: call(role,"select admin_set_show_about(%s)",(v,),uid=uid)
t.check("3.1 anonymous visitors cannot change it", sa('anon',False)[0]=='err' and val(g('anon'))['show_about'] is True)
r=sa('authenticated',False,gate); t.check("3.2 a gate user cannot change it (NOT_ALLOWED)", r[0]=='err' and 'NOT_ALLOWED' in r[1], r)
r=sa('authenticated',None,S['admin']); t.check("3.3 admin: a missing value is refused (INVALID_VALUE)", r[0]=='err' and 'INVALID_VALUE' in r[1], r)
r=sa('authenticated',False,S['admin']); t.check("3.4 an admin can switch it OFF", r[0]=='ok' and val(g('anon'))['show_about'] is False, r)
t.check("3.5 the change is written to the settings log with the admin's name", sql("select count(*) from settings_log where field='show_about' and new_value='false' and who='Admin One'")[0][0]==1)
r=sa('authenticated',True,S['admin']); t.check("3.6 ...and back ON", r[0]=='ok' and val(g('anon'))['show_about'] is True)
t.check("3.7 visitors cannot write the settings table directly", call('anon',"update settings set show_about=false")[0]=='err' or sql("select show_about from settings")[0][0] is True)
t.check("3.8 visitors cannot read the settings table directly", call('anon',"select show_about from settings")[0]=='err')
t.check("3.9 piece 9 changes no existing setting", sql("select price_per_head, cap, transfers_open from settings")[0]==(250,150,True))
t.report("test_r2_09: About link switch")
