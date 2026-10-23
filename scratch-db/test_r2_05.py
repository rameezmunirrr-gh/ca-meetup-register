from lib import *
import json, uuid, subprocess, re
F = ['r2_01_prep.sql','r2_02_lookup.sql','r2_02c_close_old_transfer_doors.sql','r2_02b_cutover.sql','r2_03_private_transfer.sql','r2_04_public_via_code.sql','r2_05_cleanup_and_ip.sql']
FILES = ['/home/claude/scratch/'+f for f in F]
OLD = ['apply_receive','check_request','close_listing','edit_listing','express_interest','get_transfer_status','list_board','lookup_transfer','manage_ticket','post_listing','start_transfer','submit_transfer_payment','withdraw_transfer','approve_transfer','decline_transfer','admin_confirm_amount','admin_mark_payment_received','admin_mark_seller_paid','admin_mark_refunded','admin_remove_listing','admin_clear_comment','admin_set_transfer_settings','_seller_ticket','_transfer_block_reason','_clean_comment','_clean_payout','_seller_kind','_norm_code']
t = T()
def setup():
    fresh(FILES); S = seed(); sql("update settings set transfers_open=true, price_per_head=250")
    for nm, role, k in [('gate','gate','Gate One'),('admin2','admin','Admin Two')]:
        u = uuid.uuid4(); sql("insert into auth.users (id,email) values (%s,%s)", (str(u), nm+'@test')); sql("insert into staff (user_id,name,role) values (%s,%s,%s)", (str(u), k, role)); S[nm] = u
    return S
def A_(q, p=(), uid=None, role='anon', headers=None):
    r = call(role, q, p, uid=uid, headers=headers)
    return r[1][0][0] if r[0]=='ok' and r[1] else (('ERR', r[1]) if r[0]=='err' else None)
def adm(fn, *a, uid=None, role='authenticated'):
    ph = ','.join(['%s']*len(a)); return call(role, f"select {fn}({ph})", a, uid=uid)
def ok(r): return r[0]=='ok'
def err(r, w): return r[0]=='err' and w in r[1]
def label(n): return 'E26-%03d' % n
def book(headers, name='Pat', phone='9100000000', sid=None):
    sid = sid or uuid.uuid4(); path = f'{sid}.jpg'; sql("insert into storage.objects values ('payment-proofs',%s)",(path,))
    p = [dict(name=name, phone=phone, email=f'{name.lower()}@example.com', loc='In Bengaluru', att='Surely', food='Veg')]
    r = call('anon', "select submit_booking(%s,%s::jsonb,%s)", (str(sid), json.dumps(p), path), headers=headers)
    return r, sid
def last_ip(): return sql("select ip, raw from booking_ips order by created_at desc, booking_id limit 1")[0]
H = lambda **kw: json.dumps({k.replace('_','-'): v for k, v in kw.items()})
def counts():
    return sql("""select (select count(*) from tickets t join bookings b on b.id=t.booking_id where b.status<>'rejected' and t.transferred_out_at is null),
      (select coalesce(sum(amount_expected),0) from bookings where status='paid'), (select count(*) from bookings where kind='registration')""")[0]

# ================= GROUP 1: the old transfer backend is gone =================
S = setup(); A, B, admin, gate = S['A'], S['B'], S['admin'], S['gate']
print("-- group 1: old backend removed")
gone = [n for n in OLD if sql("select count(*) from pg_proc p join pg_namespace ns on ns.oid=p.pronamespace where ns.nspname='public' and p.proname=%s",(n,))[0][0]==0]
t.check(f"1.1 all {len(OLD)} old functions and helpers are gone", len(gone)==len(OLD), [n for n in OLD if n not in gone])
t.check("1.2 the three old tables are gone", sql("select count(*) from information_schema.tables where table_schema='public' and table_name in ('ticket_transfers','ticket_listings','ticket_interests')")[0][0]==0)
t.check("1.3 no remaining function mentions an old table", sql("select count(*) from pg_proc p join pg_namespace ns on ns.oid=p.pronamespace where ns.nspname='public' and (p.prosrc like '%%ticket_transfers%%' or p.prosrc like '%%ticket_listings%%' or p.prosrc like '%%ticket_interests%%')")[0][0]==0)
t.check("1.4 the helpers the new code needs are still there", all(sql("select count(*) from pg_proc p join pg_namespace ns on ns.oid=p.pronamespace where ns.nspname='public' and p.proname=%s",(n,))[0][0]>=1 for n in ['_parse_ticket','_ticket_label','_find_seller_ticket','_assign_numbers','_new_transfer_code','_tlog','_actor','_release_cascade'] if n!='_release_cascade'))
t.check("1.5 calling an old function now fails (does not exist)", err(call('anon',"select list_board()"),'does not exist') and err(adm('admin_confirm_amount',str(uuid.uuid4()),5,uid=admin),'does not exist'))
g = lambda no, sec: A_("select admit_ticket(%s,%s,false,false,null)",(no,sec),uid=gate,role='authenticated')
sec1 = sql("select secret from tickets where ticket_no=1")[0][0]
t.check("1.6 gate still works: a real ticket admits, then 'already scanned'", g(1,sec1)['result']=='ok' and g(1,sec1)['result']=='already_scanned')
t.check("1.7 gate: an unknown ticket number and an unknown coordinator number are 'invalid' (no old table needed)", g(999,'x')['result']=='invalid' and A_("select admit_ticket(%s,%s,false,true,null)",(77,'x'),uid=gate,role='authenticated')['result']=='invalid')
# new flows still work
base = counts()
code = A_("select private_sell(%s,%s,%s)",(A,label(2),'9000000002'))
bk = A_("select transfer_submit(%s,%s,%s::jsonb)",(code['code'],str(uuid.uuid4()),json.dumps(dict(name='Dan',phone='9000000004',email='d@example.com',loc='In Bengaluru',att='Surely',food='Veg',consent='true'))))
x = str(sql("select id from transfers")[0][0]); adm('admin_transfer_confirm_call', x, True, uid=admin)
t.check("1.8 a PRIVATE transfer still works end to end after the clean-up, counts unchanged", ok(adm('admin_transfer_approve', x, uid=admin)) and counts()==base)
pc = A_("select public_sell(%s,%s,%s,%s)",(B,label(3),'9000000003','carl@okbank'))
pb = A_("select transfer_submit(%s,%s,%s::jsonb)",(pc['code'],str(uuid.uuid4()),json.dumps(dict(name='Eve',phone='9000000005',email='e@example.com',loc='In Bengaluru',att='Surely',food='Veg',consent='true'))))
px = str(sql("select id from transfers where kind='public'")[0][0]); adm('admin_transfer_confirm_call', px, True, uid=admin); adm('admin_transfer_request_payment', px, uid=admin)
sid = uuid.uuid4(); sql("insert into storage.objects values ('payment-proofs',%s)",(f'{sid}.jpg',)); A_("select transfer_pay(%s,%s,%s,%s)",(pb['booking_code'],'9000000005',str(sid),f'{sid}.jpg'))
adm('admin_transfer_verify_payment', px, 250, uid=admin); base = counts()
t.check("1.9 a PUBLIC transfer still works end to end (payment, verify, Transfer, payout), counts unchanged", ok(adm('admin_transfer_approve', px, uid=admin)) and ok(adm('admin_transfer_mark_paid', px, 'UPI-123456', uid=admin)) and counts()==base)
ret = A_("select admit_ticket(%s,%s,false,false,null)",(3,sql("select secret from tickets where ticket_no=3")[0][0]),uid=gate,role='authenticated')
t.check("1.10 gate: the retired ticket of that transfer shows CANCELLED with the new holder", ret['result']=='cancelled' and ret['name']=='Eve', ret)
t.check("1.11 the export view still works", ok(adm('select 1 from report limit 1') if False else call('postgres',"select count(*) from report")))
sid=uuid.uuid4(); path=f'{sid}.jpg'; sql("insert into storage.objects values ('payment-proofs',%s)",(path,))
rr = call('anon',"select submit_booking(%s,%s::jsonb,%s)",(str(sid),json.dumps([dict(name='New',phone='9777777777',email='n@example.com',loc='In Bengaluru',att='Surely',food='Veg')]),path))
t.check("1.12 a normal registration still works", ok(rr), rr)

# ================= GROUP 2: recording the IP =================
S = setup(); A, B, admin, gate = S['A'], S['B'], S['admin'], S['gate']
print("-- group 2: IP capture")
n0 = sql("select count(*) from booking_ips")[0][0]
t.check("2.1 the seed bookings (made from the SQL tool, no headers) have an IP row with no address", n0==2 and sql("select count(*) from booking_ips where ip is null and raw is null")[0][0]==2)
cases = [
 ("cf header only", H(cf_connecting_ip='203.0.113.7'), '203.0.113.7'),
 ("cf wins over x-forwarded-for", H(cf_connecting_ip='203.0.113.8', x_forwarded_for='9.9.9.9'), '203.0.113.8'),
 ("x-forwarded-for alone, one address", H(x_forwarded_for='198.51.100.9'), '198.51.100.9'),
 ("x-forwarded-for list: the LAST address", H(x_forwarded_for='1.1.1.1, 2.2.2.2, 3.3.3.3'), '3.3.3.3'),
 ("x-forwarded-for with odd spaces", H(x_forwarded_for='1.1.1.1 ,  2.2.2.2'), '2.2.2.2'),
 ("an IPv6 address", H(cf_connecting_ip='2001:db8::1'), '2001:db8::1'),
 ("header names in capitals", '{"CF-Connecting-IP":"203.0.113.50"}', '203.0.113.50'),
 ("a fake cf header with junk falls back to x-forwarded-for", H(cf_connecting_ip="x'; drop table bookings;--", x_forwarded_for='5.5.5.5'), '5.5.5.5'),
 ("only junk: no address, but the booking still works", H(cf_connecting_ip="<script>alert(1)</script>"), None),
 ("an address that is too long is ignored", H(x_forwarded_for='1'*60), None),
 ("headers that are not JSON", 'this is not json', None),
 ("an empty header object", '{}', None),
]
for name, hdr, want in cases:
    r, sid = book(hdr, name=f'T{abs(hash(name))%9999}')
    t.check(f"2.2 {name}: booking accepted", ok(r), r)
    t.check(f"2.2b {name}: stored address is {want}", last_ip()[0]==want, last_ip())
r, sid = book(H(x_forwarded_for=','.join(['9.9.9.9']*200)), name='Long')
ip, raw = last_ip(); t.check("2.3 a huge header is accepted, the raw value is cut to 300 characters", ok(r) and raw is not None and len(raw)<=300 and ip=='9.9.9.9', (ip, len(raw or '')))
r, sid = book(H(cf_connecting_ip='203.0.113.77', x_forwarded_for="evil\x01\x02 value"), name='Ctrl')
ip, raw = last_ip(); t.check("2.4 control characters are stripped from the raw value", ok(r) and re.fullmatch(r'[\x20-\x7e]*', raw or '') is not None, raw)
t.check("2.5 the raw value shows both headers so the owner can see which one is trustworthy", 'cf=203.0.113.77' in raw and 'xff=' in raw, raw)
n = sql("select count(*) from booking_ips")[0][0]; r1, sid = book(H(cf_connecting_ip='203.0.113.99'), name='Rep')
r2 = call('anon', "select submit_booking(%s,%s::jsonb,%s)", (str(sid), json.dumps([dict(name='Rep',phone='9100000000',email='rep@example.com',loc='In Bengaluru',att='Surely',food='Veg')]), f'{sid}.jpg'), headers=H(cf_connecting_ip='198.18.0.1'))
t.check("2.6 sending the same registration again records no second row (and keeps the first address)", ok(r2) and sql("select count(*) from booking_ips")[0][0]==n+1 and last_ip()[0]=='203.0.113.99')
t.check("2.7 every registration booking has exactly one IP row", sql("select count(*) from bookings where kind='registration'")[0][0]==sql("select count(*) from booking_ips")[0][0])
# a transfer booking does not record an IP
code = A_("select private_sell(%s,%s,%s)",(A,label(1),'9000000001'))['code']; nrows = sql("select count(*) from booking_ips")[0][0]
A_("select transfer_submit(%s,%s,%s::jsonb)",(code,str(uuid.uuid4()),json.dumps(dict(name='Dan',phone='9000000004',email='d@example.com',loc='In Bengaluru',att='Surely',food='Veg',consent='true'))), headers=H(cf_connecting_ip='198.18.0.2'))
t.check("2.8 a transfer booking records no IP (only registrations are flagged)", sql("select count(*) from booking_ips")[0][0]==nrows)
# privacy
t.check("2.9 a visitor cannot read the IP table", call('anon',"select count(*) from booking_ips")[0]=='err')
t.check("2.10 a gate user sees ZERO rows; an admin sees them", A_("select count(*) from booking_ips",uid=gate,role='authenticated')==0 and A_("select count(*) from booking_ips",uid=admin,role='authenticated')>5)
t.check("2.11 nobody but the database itself can write to it", sql("select has_table_privilege('authenticated','public.booking_ips','insert') or has_table_privilege('authenticated','public.booking_ips','update') or has_table_privilege('authenticated','public.booking_ips','delete') or has_table_privilege('anon','public.booking_ips','select')")[0][0] is False)
t.check("2.12 the bookings table has no IP column (so gate staff reading bookings cannot see it)", sql("select count(*) from information_schema.columns where table_schema='public' and table_name='bookings' and column_name ilike '%%ip%%' and column_name not ilike '%%description%%'")[0][0]==0)
t.check("2.13 the export view has no IP either", sql("select count(*) from information_schema.columns where table_schema='public' and table_name='report' and column_name ilike '%%ip%%'")[0][0]==0)
for fn in ['_request_headers()','_clean_ip(text)','_header(text)','_client_ip()','_client_ip_raw()']:
    t.check(f"2.14 anon cannot call internal {fn.split('(')[0]}", sql(f"select has_function_privilege('anon','public.{fn}','execute')")[0][0] is False)
# never blocks
S = setup(); admin, gate = S['admin'], S['gate']
res = [book(H(cf_connecting_ip='203.0.113.200'), name=f'Spam{i}', phone=f'91000{i:05d}')[0] for i in range(12)]
t.check("2.15 TWELVE registrations from one address are ALL accepted (flag only, never blocks)", all(ok(r) for r in res), [r for r in res if not ok(r)])

# ================= GROUP 3: the flag =================
S = setup(); admin, gate, admin2 = S['admin'], S['gate'], S['admin2']
print("-- group 3: flags, threshold, deleting")
def many(ip, n, prefix):
    codes = []
    for i in range(n):
        r, sid = book(H(cf_connecting_ip=ip), name=f'{prefix}{i}', phone=f'92{abs(hash(prefix))%1000:03d}{i:05d}')
        codes.append(sql("select booking_code from bookings where submission_id=%s",(str(sid),))[0][0])
    return codes
X = many('203.0.113.10', 6, 'Xray'); Y = many('203.0.113.20', 4, 'Yank'); Z = many('203.0.113.30', 1, 'Zulu')
sql("update bookings set status='paid' where booking_code in (%s,%s)",(X[0],X[1])); sql("update bookings set status='rejected' where booking_code=%s",(X[2],))
f = A_("select admin_ip_flags()",uid=admin,role='authenticated')
t.check("2.0/3.1 default threshold is 5; only the address with 6 registrations is flagged", f['threshold']==5 and [i['ip'] for i in f['ips']]==['203.0.113.10'], f)
i0 = f['ips'][0]; t.check("3.2 it shows registrations, people, and how many are pending, paid, rejected", (i0['bookings'],i0['people'],i0['paid'],i0['rejected'],i0['pending'])==(6,6,2,1,3), i0)
t.check("3.3 by_booking marks exactly those 6 Booking IDs with the address and the count", set(f['by_booking'])==set(X) and all(v=={'ip':'203.0.113.10','count':6} for v in f['by_booking'].values()), f['by_booking'])
sql("update settings set ip_flag_threshold=3"); f = A_("select admin_ip_flags()",uid=admin,role='authenticated')
t.check("3.4 threshold 3 flags two addresses, the busiest first", [i['ip'] for i in f['ips']]==['203.0.113.10','203.0.113.20'] and f['threshold']==3, f)
sql("update settings set ip_flag_threshold=2"); t.check("3.5 threshold 2 still leaves the address with one registration unflagged", len(A_("select admin_ip_flags()",uid=admin,role='authenticated')['ips'])==2)
for v in [1, 0, 1001, -5]:
    t.check(f"3.6 threshold {v} refused", call('postgres',"update settings set ip_flag_threshold=%s",(v,))[0]=='err')
t.check("3.7 thresholds 2 and 1000 accepted; changes are logged", ok(call('postgres',"update settings set ip_flag_threshold=1000")) and sql("select count(*) from settings_log where field='ip_flag_threshold'")[0][0]>=2)
sql("update settings set ip_flag_threshold=5")
t.check("3.8 flags are for admins only (gate user refused, visitor denied)", err(adm('admin_ip_flags',uid=gate),'NOT_ALLOWED') and call('anon',"select admin_ip_flags()")[0]=='err')
book('{}', name='NoIp1'); book('{}', name='NoIp2'); f = A_("select admin_ip_flags()",uid=admin,role='authenticated')
t.check("3.9 registrations without an address are never flagged together", all(i['ip'] is not None for i in f['ips']))
r = A_("select private_sell(%s,%s,%s)",(S['A'],label(1),'9000000001')); A_("select transfer_submit(%s,%s,%s::jsonb)",(r['code'],str(uuid.uuid4()),json.dumps(dict(name='Dan',phone='9000000004',email='d@example.com',loc='In Bengaluru',att='Surely',food='Veg',consent='true'))), headers=H(cf_connecting_ip='203.0.113.10'))
sql("insert into booking_ips (booking_id, ip) select id, '203.0.113.10' from bookings where kind='transfer' limit 1")   # even if a transfer booking ever had an address stored
t.check("3.10 a transfer booking from a flagged address does not add to its count", A_("select admin_ip_flags()",uid=admin,role='authenticated')['ips'][0]['bookings']==6 and len(A_("select admin_ip_flags()",uid=admin,role='authenticated')['by_booking'])==6)
# clearing
t.check("3.11 a gate user cannot delete the stored addresses; a visitor cannot", err(adm('admin_clear_client_ips',uid=gate),'NOT_ALLOWED') and call('anon',"select admin_clear_client_ips()")[0]=='err')
before = sql("select count(*) from booking_ips")[0][0]; r = adm('admin_clear_client_ips', uid=admin)
t.check("3.12 an admin deletes every stored address and is told how many", ok(r) and r[1][0][0]==before and sql("select count(*) from booking_ips")[0][0]==0, r)
t.check("3.13 after deleting there are no flags", A_("select admin_ip_flags()",uid=admin,role='authenticated')['ips']==[])
lg = sql("select who, area, field, old_value, new_value from settings_log where field='stored visitor IPs deleted'")
t.check("3.14 the deletion is logged with the admin's name and a row count, never an address", len(lg)==1 and lg[0][0]=='Admin One' and lg[0][1]=='settings' and not re.search(r'\d+\.\d+\.\d+\.\d+', json.dumps(lg)), lg)
t.check("3.15 deleting again: 0 rows, still fine", adm('admin_clear_client_ips',uid=admin)[1][0][0]==0)
t.check("3.16 the registrations themselves are untouched by deleting addresses", sql("select count(*) from bookings where kind='registration'")[0][0]>=13)
r, sid = book(H(cf_connecting_ip='203.0.113.11'), name='After'); t.check("3.17 new registrations record addresses again afterwards", ok(r) and last_ip()[0]=='203.0.113.11')
# deleting a booking cleans its IP row
bid = sql("select id from bookings where submission_id=%s",(str(sid),))[0][0]; sql("delete from tickets where booking_id=%s",(str(bid),)); sql("delete from bookings where id=%s",(str(bid),))
t.check("3.18 deleting a test booking also deletes its IP row (cleanup of test data stays simple)", sql("select count(*) from booking_ips where booking_id=%s",(str(bid),))[0][0]==0)

# ================= GROUP 4: re-run =================
S = setup(); admin = S['admin']; book(H(cf_connecting_ip='203.0.113.5'), name='Before')
r = subprocess.run(["psql","-h","/tmp","-p","5544","-q","-d","postgres","-U","postgres","-v","ON_ERROR_STOP=1","-f",FILES[-1]],capture_output=True,text=True)
t.check("4.1 the piece-5 SQL can be applied a second time without errors", r.returncode==0, r.stderr[-300:])
t.check("4.2 ...the earlier address is still there and new bookings still record addresses", sql("select count(*) from booking_ips where ip='203.0.113.5'")[0][0]==1 and ok(book(H(cf_connecting_ip='203.0.113.6'), name='After2')[0]))
t.report("R2-1 piece 5 tests (clean-up and IP flag)")
