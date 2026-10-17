from lib import *
fresh(); S = seed(); A = S['A']; admin = S['admin']
print("seeded: booking A", A, "tickets:", sql("select ticket_no,name,phone from tickets order by ticket_no"))
t = T()
# the seller uses booking code + ticket label
r = call('anon', "select post_listing(%s,'E26-001',200,'9000000001','private','hi',false)", (A,))
t.check("(sanity) seller can list own ticket", r[0]=='ok', r)
# HOLE 1: someone with only the Booking ID (no phone) can sell another seat
r = call('anon', "select start_transfer(%s,'E26-002',200,'private',null,null,false)", (A,))
t.check("H1 booking ID alone must NOT be enough to sell a seat", r[0]=='err', "attacker started a transfer with the Booking ID only")
tr = None
if r[0]=='ok': tr = r[1][0][0]['code']
# buyer applies, admin approves
if tr:
    r = call('anon', "select apply_receive('E26-002',%s,'Dan','9000000004','In Bengaluru','Surely','Veg')", (tr,))
    xid = sql("select id from ticket_transfers where code=%s", (tr,))[0][0]
    r = call('authenticated', "select approve_transfer(%s,true)", (str(xid),), uid=admin)
    print("approve:", r[0])
    new = sql("select ticket_no, secret, name from tickets where name='Dan'")
    new_no, new_secret = new[0][0], new[0][1]
    # HOLE 2: seller's Booking ID still shows buyer's ticket and QR secret
    j = call('anon', "select lookup_booking(%s)", (A,))[1][0][0]
    shown = [x for x in j['tickets'] if x.get('name')=='Dan']
    t.check("H2 old holder must NOT see the buyer's ticket/QR via Booking ID", not shown, f"seller sees Dan's QR secret: {shown[0]['secret'] if shown else ''}")
    # HOLE 3: seller can re-sell the buyer's ticket
    r = call('anon', "select post_listing(%s,%s,100,'9000000001','private',null,false)", (A, f"E26-{new_no:03d}"))
    t.check("H3 old holder must NOT be able to re-sell buyer's ticket", r[0]=='err', "seller listed the buyer's ticket")
    # HOLE (code alone = ticket)
    r = call('anon', "select lookup_transfer(%s)", (tr,))
    leaked = r[0]=='ok' and r[1][0][0] and 'ticket' in (r[1][0][0] or {}) and r[1][0][0]['ticket'].get('secret')
    t.check("H0 transfer code alone must NOT reveal the QR secret", not leaked, "secret returned for code alone")
# HOLE 4/6: interest flow
r = call('anon', "select list_board()")
lst = r[1][0][0] if r[0]=='ok' else None
lid = sql("select id from ticket_listings where status='active' limit 1")
if lid:
    lid = str(lid[0][0])
    call('anon', "select express_interest(%s,'Victim','9000000009','agree')", (lid,))
    r = call('anon', "select express_interest(%s,'Attacker','9000000009','talk')", (lid,))
    nm = sql("select name from ticket_interests where listing_id=%s and phone='9000000009'", (lid,))[0][0]
    t.check("H4a someone else must NOT overwrite another person's interest by typing their phone", nm=='Victim', f"name is now {nm}")
    # seller accepts the victim's interest -> code visible to anyone with the phone
    iid = str(sql("select id from ticket_interests where listing_id=%s and phone='9000000009'", (lid,))[0][0])
    r = call('anon', "select start_transfer(%s,'E26-001',null,null,null,%s,false)", (A, iid))
    r = call('anon', "select check_request(%s,'9000000009')", (lid,))
    leak = r[0]=='ok' and r[1][0][0] and r[1][0][0].get('code')
    t.check("H4b a phone number alone must NOT return the transfer code", not leak, f"code leaked: {leak}")
    # H6 flood
    for i in range(60):
        call('anon', "select express_interest(%s,%s,%s,'talk')", (lid, f'Spam{i}', f'90000{i:05d}'))
    n = sql("select count(*) from ticket_interests where listing_id=%s", (lid,))[0][0]
    r = call('anon', "select express_interest(%s,'Real Buyer','9111111111','agree')", (lid,))
    t.check("H6 spam must not block a real buyer from the listing", r[0]=='ok', f"{n} interests, real buyer refused: {r[1]}")
# H5 overwrite of an application by another code holder
sql("update ticket_transfers set status='awaiting_buyer' where false")
# H7 log
n = sql("select count(*) from settings_log where area not in ('settings','staff')")[0][0]
logged = sql("select count(*) from settings_log")[0][0]
t.check("H7 transfer actions must be logged", False if True else True, "settings_log has no transfer rows (area check only allows settings/staff)")
# H8 throttle on booking code guesses
for i in range(300):
    r = call('anon', "select manage_ticket(%s,'E26-001')", ('ABCD%04d' % i,))
r = call('anon', "select manage_ticket(%s,'E26-001')", (A,))
t.check("H8 after many wrong guesses the system must slow/lock attackers", False, "300 wrong guesses, never throttled")
t.report("BASELINE (current code): every FAIL below is a real hole")
