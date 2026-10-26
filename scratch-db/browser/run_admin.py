from admin_test import *
with sync_playwright() as p:
    # ---- 1. Overview: the retired ticket must not be counted
    b, pg, errs = open_page(p, db())
    txt = pg.inner_text('#v')
    cards = {c.query_selector('span').inner_text(): c.query_selector('b').inner_text() for c in pg.query_selector_all('.card.stat')}
    check('no page errors on load', not errs, errs)
    check('Active tickets = 3 (Ben, Carl, Dan; Asha retired)', cards.get('Active tickets')=='3', cards)
    check('Spots used = 3 (not 4)', cards.get('Spots used')=='3', cards)
    check('Pending = 0', cards.get('Pending')=='0', cards)
    check('Expected total = ₹750? (transfer booking has amount 0)', '750' in cards.get('Expected total',''), cards)
    check('chart data: food counts Veg 2, Non-veg 1', pg.evaluate('window.__CHARTS[0].data.datasets[0].data').__eq__([2,1]), pg.evaluate('window.__CHARTS[0].data.datasets[0].data'))
    check('Transfers tab is shown with a to-do count', 'Transfers (' in pg.inner_text('.tabs'), pg.inner_text('.tabs'))
    # ---- 2. Bookings: transfer booking hidden
    pg.click('button[data-tab="bookings"]'); t = pg.inner_text('#tbl')
    check('Bookings tab hides the transfer booking', 'CODE0003' not in t and 'CODE0001' in t, t[:200])
    check('Bookings tab explains where it went', 'Transfers tab' in pg.inner_text('#v'))
    # ---- 3. People
    pg.click('button[data-tab="people"]'); t = pg.inner_text('#tbl')
    check('People: retired Asha hidden by default', 'Asha' not in t and 'Dan' in t, t[:300])
    check('People: email column shown for admins', 'dan@example.com' in t)
    pg.check('#fmoved'); t = pg.inner_text('#tbl')
    check('People: toggle shows retired ticket as Transferred, with no buttons', 'Asha' in t and 'Transferred' in t)
    rows = pg.query_selector_all('#tbl tr'); asha=[r for r in rows if 'Asha' in r.inner_text()][0]
    check('retired row has no Make-coordinator button', asha.query_selector('button') is None)
    # ---- 4. Scan queue ignores transfer bookings
    pg.click('button[data-tab="scan"]'); t = pg.inner_text('#v')
    check('Scan screenshots: 2 not scanned (transfer booking excluded)', '2 not scanned yet' in t, t[:200])
    # ---- 5. Transfers tab content
    pg.click('button[data-tab="transfers"]'); t = pg.inner_text('#v')
    check('money panel shows ₹230 held', '230' in t and 'Held by you' in t)
    check('waiting card shows seller and buyer', 'Eve Buyer' in t and '9000000002' in t and 'eve@example.com' in t)
    check('active code listed and flagged expired', 'expired' in t and 'carl@upi' in t and 'Code ABC234' in t, t[:100])
    check('payout list shows Asha ₹230', 'Pay the seller (1)' in t and '₹230' in t)
    check('Transfer button disabled until call ticked', pg.query_selector('[data-tact="approve"]').is_disabled())
    b.close()
    # ---- 6. clicking the call tick, Transfer and error mapping
    d = db(); d['rpc']['admin_transfer_confirm_call']=None; d['rpc']['admin_transfer_approve']={'new_label':'E26-005','old_label':'E26-002','booking_code':'X'}
    b, pg, errs = open_page(p, d, 'transfers')
    pg.click('[data-tcall="x1"]'); pg.wait_for_timeout(200)
    c = pg.evaluate('window.__CALLS'); cc=[x for x in c if x['name']=='admin_transfer_confirm_call']
    check('ticking the call box calls the database with the right transfer', cc and cc[-1]['args']=={'p_transfer':'x1','p_confirmed':True}, c[-3:])
    pg.once('dialog', lambda dlg: dlg.accept())
    pg.eval_on_selector('[data-tact="approve"]', 'e=>e.disabled=false'); pg.click('[data-tact="approve"]'); pg.wait_for_timeout(300)
    check('Transfer button calls admin_transfer_approve', any(x['name']=='admin_transfer_approve' and x['args']=={'p_transfer':'x1'} for x in pg.evaluate('window.__CALLS')))
    b.close()
    d = db(); d['rpc']['admin_transfer_approve']='SELLER_CHECKED_IN'
    b, pg, errs = open_page(p, d, 'transfers'); pg.once('dialog', lambda dlg: dlg.accept())
    pg.eval_on_selector('[data-tact="approve"]', 'e=>e.disabled=false'); pg.click('[data-tact="approve"]'); pg.wait_for_timeout(300)
    check('database error is shown in plain words, never as a raw code', 'already entered the hall' in pg.inner_text('.toast') and 'SELLER_CHECKED_IN' not in pg.inner_text('.toast'), pg.inner_text('.toast') if pg.query_selector('.toast') else 'no toast')
    b.close()
    # ---- 7. public flow buttons appear in the right order
    t3 = dict(TRANSFERS[0], id='x4', kind='public', seller_upi='s@upi', seller_call_confirmed_at='2026-10-24T09:00:00Z', payment_requested_at='2026-10-24T09:05:00Z', amount_due=250, payment_submitted_at='2026-10-24T09:20:00Z', payment_screenshot_path='x.jpg')
    d = db(tables=dict(transfers=[t3], transfer_buyers=[dict(BUYERS[0], transfer_id='x4')]))
    b, pg, errs = open_page(p, d, 'transfers'); t = pg.inner_text('#v')
    check('public: shows screenshot and amount box once buyer uploaded', pg.query_selector('[data-tact="shot"]') and pg.query_selector('#amt-x4'))
    check('public: Transfer still disabled (payment not verified)', pg.query_selector('[data-tact="approve"]').is_disabled())
    check('public: payout UPI shown to read back', 's@upi' in t)
    msgs=[]
    pg.fill('#amt-x4','230'); pg.once('dialog', lambda dlg: (msgs.append(dlg.message), dlg.accept())); pg.click('[data-tact="verify"]'); pg.wait_for_timeout(200)
    check('a typed amount different from the asked amount shows a strong warning with both figures', msgs and 'CHECK THE AMOUNT' in msgs[0] and '₹250' in msgs[0] and '₹230' in msgs[0] and 'LESS' in msgs[0], msgs)
    check('verify sends the typed amount', any(x['name']=='admin_transfer_verify_payment' and x['args'].get('p_amount')==230 for x in pg.evaluate('window.__CALLS')), pg.evaluate('window.__CALLS')[-2:])
    b.close()
    # ---- 8. the page still works on a database WITHOUT the Release 2 update
    old_tickets = [{k:v for k,v in t.items() if k not in ('transferred_out_at','transferred_from')} for t in TICKETS[1:3]]
    d = db(tables=dict(tickets=old_tickets, bookings=[{k:v for k,v in x.items() if k!='kind'} for x in BOOKINGS[:2]], ticket_emails=None, transfers=None, transfer_buyers=None, settings={k:v for k,v in SETTINGS.items() if k not in('transfers_open','transfer_cutoff_at','transfer_food_locked','private_code_hours','ip_flag_threshold')}),
          rpc=dict(admin_transfer_money='function does not exist', admin_ip_flags='function does not exist'))
    b, pg, errs = open_page(p, d)
    cards = {c.query_selector('span').inner_text(): c.query_selector('b').inner_text() for c in pg.query_selector_all('.card.stat')}
    check('old database: page loads without errors', not errs and 'Active tickets' in cards, (errs, cards))
    check('old database: no Transfers tab', 'Transfers' not in pg.inner_text('.tabs'))
    pg.click('button[data-tab="people"]'); check('old database: People works without email column', 'Email' not in pg.inner_text('#tbl') and 'Ben' in pg.inner_text('#tbl'))
    pg.click('button[data-tab="settings"]'); check('old database: Settings shows the setup-step notice instead of crashing', 'One setup step is missing' in pg.inner_text('#v'))
    b.close()
    # ---- 8b. look and feel
    b, pg, errs = open_page(p, db())
    check('look: admin has the slim header with the logo and the Organiser label', pg.is_visible('.top') and pg.query_selector('.top img') is not None and 'Organiser' in pg.inner_text('.top'))
    check('look: admin uses the brand colours, not the old green', '#0e5a43' not in pg.content().lower())
    b.close()
    # ---- 9. settings save for transfers
    d = db(); d['rpc']['admin_set_transfer_settings']=None
    b, pg, errs = open_page(p, d, 'settings')
    pg.fill('#thours','12'); pg.check('#tfood'); pg.click('#tsave'); pg.wait_for_timeout(200)
    c=[x for x in pg.evaluate('window.__CALLS') if x['name']=='admin_set_transfer_settings']
    check('saving transfer settings sends the right values (no cut-off, food locked, 12 h)', c and c[-1]['args'].get('p_code_hours')==12 and c[-1]['args'].get('p_food_locked') is True and c[-1]['args'].get('p_cutoff') is None and c[-1]['args'].get('p_clear_cutoff') is False, c)
    b.close()
    # ---- 9b. About link switch
    d = db(); d['tables']['settings']=dict(d['tables']['settings'], show_about=True); d['rpc']['admin_set_show_about']=None
    b, pg, errs = open_page(p, d, 'settings')
    check('About card shows, ticked', pg.query_selector('#aboutshow') and pg.is_checked('#aboutshow'))
    pg.uncheck('#aboutshow'); pg.click('#aboutsave'); pg.wait_for_timeout(200)
    c=[x for x in pg.evaluate('window.__CALLS') if x['name']=='admin_set_show_about']
    check('saving sends show = false', c and c[-1]['args']=={'p_show':False}, c); b.close()
    b, pg, errs = open_page(p, db(), 'settings')
    check('About card is hidden before the database update (no crash)', pg.query_selector('#aboutshow') is None and not errs); b.close()
    # ---- 9c. Email box switch
    d = db(); d['tables']['settings']=dict(d['tables']['settings'], ask_email=True); d['rpc']['admin_set_ask_email']=None
    b, pg, errs = open_page(p, d, 'settings')
    check('Email card shows, ticked', pg.query_selector('#askemail') and pg.is_checked('#askemail'))
    pg.uncheck('#askemail'); pg.click('#askemailsave'); pg.wait_for_timeout(200)
    c=[x for x in pg.evaluate('window.__CALLS') if x['name']=='admin_set_ask_email']
    check('saving sends ask = false', c and c[-1]['args']=={'p_ask':False}, c); b.close()
    b, pg, errs = open_page(p, db(), 'settings')
    check('Email card is hidden before the database update (no crash)', pg.query_selector('#askemail') is None and not errs); b.close()
    # ---- 9d. Feedback switch and tab
    d = db(tables=dict(booking_feedback=[dict(booking_id=BOOKINGS[0]['id'],rating=5,comment='Cannot wait!\nMore snacks',created_at='2026-10-26T10:00:00Z',updated_at='2026-10-26T10:00:00Z'),dict(booking_id=BOOKINGS[1]['id'],rating=3,comment=None,created_at='2026-10-26T11:00:00Z',updated_at='2026-10-26T11:00:00Z')]))
    d['tables']['settings']=dict(d['tables']['settings'], ask_feedback=True); d['rpc']['admin_set_ask_feedback']=None
    b, pg, errs = open_page(p, d, 'settings')
    check('Feedback card shows, ticked', pg.query_selector('#askfb') and pg.is_checked('#askfb'))
    pg.uncheck('#askfb'); pg.click('#askfbsave'); pg.wait_for_timeout(200)
    c=[x for x in pg.evaluate('window.__CALLS') if x['name']=='admin_set_ask_feedback']
    check('saving sends ask = false', c and c[-1]['args']=={'p_ask':False}, c)
    pg.click('button[data-tab="feedback"]'); t=pg.inner_text('#v')
    check('Feedback tab shows count, average 4.0 / 5 and the comment', 'Answers received' in t and '4.0 / 5' in t and 'More snacks' in t and not errs, (t[:300], errs))
    check('Feedback tab: a 2-person booking shows "<name> and others", a 1-person booking shows just the name', t.count(' and others')==1, t)
    b.close()
    b, pg, errs = open_page(p, db(), 'settings')
    check('no Feedback tab and no card before the database update (no crash)', pg.query_selector('button[data-tab="feedback"]') is None and pg.query_selector('#askfb') is None and not errs); b.close()
    # ---- 10. IP flag banner and booking flag
    d = db(rpc=dict(admin_ip_flags={'threshold':2,'ips':[{'ip':'203.0.113.9','bookings':2,'people':3,'pending':1,'paid':1,'rejected':0,'last_at':'2026-10-24T10:00:00Z'}],'by_booking':{'CODE0001':{'ip':'203.0.113.9','count':2},'CODE0002':{'ip':'203.0.113.9','count':2}}}))
    b, pg, errs = open_page(p, d)
    check('IP banner on Overview', '203.0.113.9' in pg.inner_text('#app') and 'flag only' in pg.inner_text('#app'))
    pg.click('button[data-tab="bookings"]'); check('booking flagged with the repeat-address note', 'Same network address' in pg.inner_text('#tbl'))
    b.close()
print(f'{sum(results)} passed, {len(results)-sum(results)} failed')
