"""The game message on the PUBLIC ticket (index.html): shown only when the database sends one, and then as a panel under the ticket.
Real qrcode-generator library and real logo; fake database. Visual copies of the tickets are saved in /tmp/gm_*.png (look at them).
Set up once: mkdir -p /home/claude/qrtest && cd /home/claude/qrtest && npm i qrcode-generator@1.4.4
Run: cd scratch-db/browser && python3 run_gamemsg.py | tail -1        (PAGE=/path/to/index.html tests another copy)"""
import os, json, base64
from playwright.sync_api import sync_playwright
ROOT = '/home/claude/ca-meetup-register/'
HTML = open(os.environ.get('PAGE', ROOT + 'index.html'), encoding='utf-8').read()
QRLIB = open('/home/claude/qrtest/node_modules/qrcode-generator/qrcode.js', encoding='utf-8').read()
res = []
def check(n, c, d=''): res.append(bool(c)); print(('  PASS  ' if c else '  FAIL  ') + n + ('' if c else '  ' + str(d)[:300]))
FAKE = r"""(function(){const calls=window.__CALLS=[];window.__R={};
 const ok=d=>({data:d,error:null});
 window.supabase={createClient:()=>({auth:{},rpc:async(n,a)=>{calls.push({name:n,args:a});const h=window.__R[n];
    if(window.__REJ===n)throw new Error('network down');
    if(n==='get_site_flags')return ok({show_about:false,ask_email:false,ask_feedback:false});
    if(n==='get_event_info')return ok({event_at:'2026-11-22T08:30:00Z',venue:'Savoury Business Hotel, Madiwala'});
    if(n==='get_payment_info')return ok({upi_id:'org@upi',payee_name:'Org',whatsapp:'919999999999'});
    if(n==='get_transfer_info')return ok({open:false,cutoff_passed:false});
    if(!h)return {data:null,error:{message:'function '+n+' does not exist'}};
    if(typeof h==='function'){try{return await h(a)}catch(e){return {data:null,error:{message:String(e)}}}}return ok(h)},
  storage:{from:()=>({upload:async()=>({data:{},error:null})})}})};})();"""
SPY = "window.__text=[];const _ft=CanvasRenderingContext2D.prototype.fillText;CanvasRenderingContext2D.prototype.fillText=function(t){window.__text.push(String(t));(window.__w=window.__w||{})[String(t)]=[this.font,this.measureText(String(t)).width];return _ft.apply(this,arguments)};"
def booking(msgs, prizes=None, heads=None):
    prizes = prizes or {}; heads = heads or {}
    return {'found':True,'kind':'registration','booking_code':'AB12CD34','status':'paid','people_count':len(msgs),'amount_expected':250*len(msgs),
            'tickets':[{'name':n,'food':'Veg' if i % 2 == 0 else 'Non-veg','label':f'E26-00{i+1}','secret':'abcdef'*2,'transferred':False,'kind':'guest','ticket_no':i+1,'coord_no':None,'location':'x','attendance':'y','game_message':m,'game_prize':prizes.get(n),'game_prize_heading':(heads.get(n, 'You are a winner!') if prizes.get(n) else None)}
                       for i, (n, m) in enumerate(msgs)]}
def open_view(p, rpc_js, html=None, w=420):
    b = p.chromium.launch(); pg = b.new_page(viewport={'width': w, 'height': 900}); errs = []
    pg.on('pageerror', lambda e: errs.append(str(e)))
    def handler(r):
        u = r.request.url
        if u.endswith('/test.html'): r.fulfill(body=html or HTML, content_type='text/html')
        elif 'qrcode' in u and u.split('?')[0].endswith('.js'): r.fulfill(body=QRLIB, content_type='text/javascript')
        elif '@supabase/supabase-js' in u: r.fulfill(body='', content_type='text/javascript')
        elif '/assets/' in u and u.split('?')[0].endswith('.png'): r.fulfill(path=ROOT + 'assets/' + u.split('/assets/')[1].split('?')[0])
        elif u.endswith('.js'): r.fulfill(body='', content_type='text/javascript')
        else: r.fulfill(status=204, body='')
    pg.route('**/*', handler); pg.add_init_script(FAKE); pg.add_init_script(SPY); pg.add_init_script("window.addEventListener('DOMContentLoaded',()=>{});")
    pg.goto('https://example.test/test.html', wait_until='commit'); pg.wait_for_selector('#app .invite')
    pg.evaluate(rpc_js); pg.click('#go-tickets'); pg.wait_for_selector('#bq'); pg.fill('#bq', 'AB12CD34'); pg.fill('#tkph', '9000000001'); pg.click('#tsearch'); pg.wait_for_selector('[data-view]')
    return b, pg, errs
def view(pg): pg.click('[data-view]'); pg.wait_for_selector('canvas.tk', state='attached'); pg.wait_for_function('S.cv&&S.cv[0]', timeout=15000); pg.wait_for_timeout(300)
def dims(pg): return pg.evaluate('S.cv.map(c=>[c.width,c.height])')
def lookups(pg): return [x for x in pg.evaluate('window.__CALLS') if x['name'] == 'lookup_tickets']
def js(d): return "window.__R.lookup_tickets=()=>({data:" + json.dumps(d) + ",error:null})"
def shot(pg, name, i=0):
    d = pg.evaluate(f'S.cv[{i}].toDataURL("image/png")'); open(f'/tmp/gm_{name}.png', 'wb').write(base64.b64decode(d.split(',')[1]))

with sync_playwright() as p:
    # 1. switch OFF (database sends null): the ticket is exactly the old size
    b, pg, errs = open_view(p, js(booking([('Asha', None), ('Ben', None)]))); view(pg)
    check('1.1 no message: both tickets are the old 900 x 1480', dims(pg) == [[900, 1480], [900, 1480]], dims(pg)); shot(pg, 'none')
    check('1.2 no message: the canvas label has no "Secret message"', 'Secret message' not in pg.get_attribute('#tc0', 'aria-label')); b.close()
    # 2. switch ON: one with a message, one without, in the same booking
    b, pg, errs = open_view(p, js(booking([('Asha', 'You are in team TIGER 🐯'), ('Ben', None)]))); pg.click('[data-view]'); pg.wait_for_selector('canvas.tk', state='attached'); pg.wait_for_function('S.cv&&S.cv[1]', timeout=15000); pg.wait_for_timeout(300)
    d = dims(pg); check('2.1 the ticket with a message is taller, the other is unchanged', d[0][0] == 900 and d[0][1] > 1480 and d[1] == [900, 1480], d); shot(pg, 'short', 0)
    check('2.2 the label read out by screen readers carries the message', 'Secret message: You are in team TIGER' in pg.get_attribute('#tc0', 'aria-label'))
    texts = pg.evaluate("(()=>{const t=[];const f=CanvasRenderingContext2D.prototype.fillText;return 1})()")
    tx = pg.evaluate('window.__text')
    check('2.3 the panel really draws the label and the exact message (and only once: one ticket has it)', tx.count('Your secret message') == 1 and 'You are in team TIGER 🐯' in tx, [x for x in tx if 'ecret' in x or 'TIGER' in x])
    check('2.3b no page errors', not errs, errs)
    # download keeps the whole ticket: PDF page is as tall as the picture
    pg.evaluate("(()=>{window.__saved=[];saveBlob=(b,n)=>{window.__saved.push([n,b.size,b.type])}})()"); pg.click('[data-dl="pdf"][data-i="0"]'); pg.wait_for_timeout(800)
    sv = pg.evaluate('window.__saved'); check('2.4 the PDF download works for a ticket with a message', sv and sv[0][0].endswith('.pdf') and sv[0][1] > 5000, sv)
    pdf_h = pg.evaluate("""async()=>{const b=await pdfOf([0]);const t=new TextDecoder('latin1').decode(new Uint8Array(await b.arrayBuffer()).slice(0,600));const m=t.match(/MediaBox \\[0 0 (\\d+) (\\d+)\\]/);return m?[+m[1],+m[2]]:null}""")
    check('2.5 the PDF page size matches the taller picture (half the pixels)', pdf_h == [450, S_h // 2] if (S_h := d[0][1]) else False, (pdf_h, d))
    b.close()
    # 3. lengths: 200 characters, one 200-letter word, emoji only, a line break typed by mistake
    long200 = ('Find the person wearing a red cap and say the word BANYAN to them. They will give you the next clue. ' * 3)[:200].strip()
    cases = [('long', long200), ('word', 'W' * 200), ('emoji', '🐯' * 100 + '🦓' * 100), ('one', 'Tiger')]
    b, pg, errs = open_view(p, js(booking([(f'P{i}', m) for i, (_, m) in enumerate(cases)]))); pg.click('[data-view]'); pg.wait_for_selector('canvas.tk', state='attached'); pg.wait_for_function('S.cv&&S.cv[3]', timeout=15000); pg.wait_for_timeout(300)
    d = dims(pg); check('3.1 all four tickets are drawn, none absurdly tall', all(900 == x[0] and 1480 < x[1] < 2300 for x in d), d)
    for i, (nm, _) in enumerate(cases): shot(pg, nm, i)
    r = pg.evaluate("""()=>{const out={};['long','word','emoji','one'].forEach((k,i)=>{const m=[...document.querySelectorAll('canvas.tk')][i];});return 1}""")
    wl = pg.evaluate("""(msgs)=>msgs.map(s=>{const x=document.createElement('canvas').getContext('2d'),L=msgLines(s);x.font='700 '+L.size+'px '+FD;return {n:L.lines.length,size:L.size,max:Math.max(...L.lines.map(l=>x.measureText(l).width)),joined:L.lines.join('').replace(/\\s/g,'')===s.replace(/\\s/g,'')}})""", [m for _, m in cases])
    check('3.2 every wrapped line fits inside the panel width (740)', all(x['max'] <= 740.5 for x in wl), wl)
    check('3.3 no character is lost or invented by wrapping (spaces aside)', all(x['joined'] for x in wl), wl)
    check('3.4 text gets smaller for long messages, and even 200 wide letters or 200 emoji stay within 12 lines', all(x['n'] <= 12 for x in wl) and wl[0]['size'] <= 46, wl)
    check('3.5 an emoji is never cut in half, even when it sits at an odd position (every line is valid text and they join back to the original)', pg.evaluate("""()=>['🐯'.repeat(100),'x'+'🐯'.repeat(99),'ab'+'🦓'.repeat(60)+'cde'].every(s=>{const L=msgLines(s).lines;return L.join('')===s&&L.every(l=>!/[\\ud800-\\udbff]$/.test(l)&&!/^[\\udc00-\\udfff]/.test(l))})"""))
    exp = pg.evaluate("""(msgs)=>msgs.map(s=>{const L=msgLines(s);return 1476+138+L.lines.length*L.lh+34})""", [m for _, m in cases])
    check('3.6 each ticket is exactly as tall as its text needs (panel + margins), so nothing spills out or is cut off', [x[1] for x in d] == exp, (d, exp))
    check('3.7 no page errors', not errs, errs); b.close()
    # 4. markup typed by an admin is only ever text
    b, pg, errs = open_view(p, js(booking([('Asha', '<img src=x onerror=alert(1)> "quotes" & more')]))); view(pg)
    check('4.1 markup, quotes and & in a message are kept as plain text in the label (no element created, label not cut short)', pg.query_selector('#app img[src="x"]') is None and 'Secret message: <img src=x onerror=alert(1)> "quotes" & more' in pg.get_attribute('#tc0', 'aria-label'), pg.get_attribute('#tc0', 'aria-label'))
    check('4.2 and nothing broke', not errs, errs); b.close()
    # 5. "View Ticket" asks the database again, so a message switched on a minute ago appears
    state = {'on': False}
    b, pg, errs = open_view(p, "window.__ON=false;window.__R.lookup_tickets=()=>({data:" + json.dumps(booking([('Asha', None)])) .replace('null', '(window.__ON?\"TEAM LION\":null)') + ",error:null})".replace('(window.__ON?\"TEAM LION\":null)', 'null'))
    b.close()
    mk = lambda msg: json.dumps(booking([('Asha', msg)]))
    b, pg, errs = open_view(p, "window.__ON=false;window.__R.lookup_tickets=()=>({data:JSON.parse(window.__ON?" + json.dumps(mk('TEAM LION')) + ":" + json.dumps(mk(None)) + "),error:null})")
    n0 = len(lookups(pg)); pg.evaluate('window.__ON=true'); view(pg)
    check('5.1 View Ticket made a fresh lookup with the same Booking ID and phone', len(lookups(pg)) == n0 + 1 and lookups(pg)[-1]['args'] == {'p_code': 'AB12CD34', 'p_phone': '9000000001'}, lookups(pg))
    check('5.2 the message that was switched on after the search is on the ticket', dims(pg)[0][1] > 1480 and 'TEAM LION' in pg.get_attribute('#tc0', 'aria-label'), dims(pg)); b.close()
    b, pg, errs = open_view(p, "window.__FAILNOW=false;window.__R.lookup_tickets=()=>{if(window.__FAILNOW)throw new Error('offline');return {data:JSON.parse(" + json.dumps(mk(None)) + "),error:null}}")
    pg.evaluate('window.__FAILNOW=true'); view(pg)
    check('5.3 if the fresh lookup fails (no signal) the ticket still opens from what was already loaded', dims(pg) == [[900, 1480]] and not errs, (dims(pg), errs)); b.close()
    b, pg, errs = open_view(p, "window.__R.lookup_tickets=a=>({data:window.__SW?{found:false}:JSON.parse(" + json.dumps(mk(None)) + "),error:null})")
    pg.evaluate('window.__SW=true'); view(pg)
    check('5.4 if the fresh lookup says "not found" the old result is kept (nothing changes under the person)', dims(pg) == [[900, 1480]], dims(pg)); b.close()
    b, pg, errs = open_view(p, "window.__R.lookup_tickets=()=>({data:JSON.parse(" + json.dumps(mk(None)) + "),error:null})")
    pg.evaluate("window.__REJ='lookup_tickets'"); view(pg)
    check('5.5 if the fresh lookup fails with a network error (it throws), the ticket still opens', dims(pg) == [[900, 1480]] and not errs, (dims(pg), errs)); b.close()
    b, pg, errs = open_view(p, js(booking([('Asha', None)], prizes={'Asha': '<b>"win"</b> & more'}))); view(pg)
    check('4.3 the prize line is also kept as plain text in the label (quotes, & and tags do not break it)', 'You are a winner!: <b>"win"</b> & more' in pg.get_attribute('#tc0', 'aria-label') and pg.query_selector('#app b') is None, pg.get_attribute('#tc0', 'aria-label')); b.close()
    # 5b. the prize line: separate panel, only when it exists
    names = ['Neither', 'TeamOnly', 'PrizeOnly', 'Both']
    bk = booking([('Neither', None), ('TeamOnly', 'You are in team LION 🦁'), ('PrizeOnly', None), ('Both', 'You are in team TIGER 🐯')], prizes={'PrizeOnly': 'You won extra food! 🍛', 'Both': 'Free dessert for you'})
    b, pg, errs = open_view(p, js(bk)); pg.click('[data-view]'); pg.wait_for_selector('canvas.tk', state='attached'); pg.wait_for_function('S.cv&&S.cv[3]', timeout=15000); pg.wait_for_timeout(300)
    d = dims(pg); lh = lambda txt: pg.evaluate("(s)=>{const L=msgLines(s);return L.lines.length*L.lh}", txt)
    one = lambda txt: 1476 + 138 + lh(txt) + 34
    exp = [1480, one('You are in team LION 🦁'), one('You won extra food! 🍛'), 1476 + 138 + lh('You are in team TIGER 🐯') + 18 + 138 + lh('Free dessert for you') + 34]
    check('5b.1 no blank space: a ticket with neither is the old size, one panel is as tall as its text needs, two panels stack with a small gap', [x[1] for x in d] == exp, (d, exp))
    tx = pg.evaluate('window.__text')
    check('5b.2 labels: "Your secret message" is drawn twice (two tickets), "You are a winner!" twice (two tickets)', tx.count('Your secret message') == 2 and tx.count('You are a winner!') == 2, [x for x in tx if 'ecret' in x or 'winner' in x])
    check('5b.3 the prize text is drawn exactly as written', 'You won extra food! 🍛' in tx and 'Free dessert for you' in tx)
    check('5b.4 screen-reader labels: prize named, nothing about a prize for tickets without one', 'You are a winner!: You won extra food' in pg.get_attribute('#tc2', 'aria-label') and 'winner' not in pg.get_attribute('#tc1', 'aria-label') and 'Secret message' in pg.get_attribute('#tc3', 'aria-label') and 'You are a winner!: Free dessert' in pg.get_attribute('#tc3', 'aria-label'))
    for i, n in enumerate(names): shot(pg, 'p_' + n, i)
    check('5b.5 no page errors', not errs, errs); b.close()
    # 5c. the editable heading
    hk = booking([('Custom', None), ('Blank', None), ('Missing', None), ('Long', None)], prizes={'Custom': 'Go to the bar', 'Blank': 'Line B', 'Missing': 'Line M', 'Long': 'Line L'}, heads={'Custom': '  Secret mission 🎯 ', 'Blank': '   ', 'Long': 'H' * 60})
    for t_ in hk['tickets']:
        if t_['name'] == 'Missing': t_['game_prize_heading'] = None
    b, pg, errs = open_view(p, js(hk)); pg.click('[data-view]'); pg.wait_for_selector('canvas.tk', state='attached'); pg.wait_for_function('S.cv&&S.cv[3]', timeout=15000); pg.wait_for_timeout(300)
    tx = pg.evaluate('window.__text')
    check('5c.1 a custom heading is drawn instead of "You are a winner!" (trimmed, emoji kept)', 'Secret mission 🎯' in tx and tx.count('You are a winner!') == 2, [x for x in tx if 'ecret mission' in x or 'winner' in x])
    check('5c.2 a blank or missing heading falls back to "You are a winner!" (the two tickets Blank and Missing)', tx.count('You are a winner!') == 2)
    check('5c.3 the screen-reader label uses the custom heading', 'Secret mission 🎯: Go to the bar' in pg.get_attribute('#tc0', 'aria-label') and 'winner' not in pg.get_attribute('#tc0', 'aria-label'), pg.get_attribute('#tc0', 'aria-label'))
    w = pg.evaluate("(()=>{const x=document.createElement('canvas').getContext('2d');return null})()")
    lw = pg.evaluate("window.__fontw||null")
    fw = pg.evaluate('window.__w')['H' * 60]
    check('5c.4 a 60-character heading is drawn in full, its font was shrunk and it is narrower than the panel text area (740 px)', fw[1] <= 740 and '30px' not in fw[0], fw)
    hk2 = booking([('Mk', None)], prizes={'Mk': 'L'}, heads={'Mk': '<i>"q"</i> & x'})
    b2, pg2, errs2 = open_view(p, js(hk2)); pg2.click('[data-view]'); pg2.wait_for_selector('canvas.tk', state='attached'); pg2.wait_for_timeout(300)
    check('5c.4b markup, quotes and & in a heading are kept as plain text in the label', '<i>"q"</i> & x: L' in pg2.get_attribute('#tc0', 'aria-label') and pg2.query_selector('#app i') is None and not errs2, pg2.get_attribute('#tc0', 'aria-label')); b2.close()
    check('5c.5 no page errors', not errs, errs); b.close()
    # a long prize line and a long team message together
    b, pg, errs = open_view(p, js(booking([('Both', long200)], prizes={'Both': 'W' * 150}))); view(pg)
    d = dims(pg); check('5b.6 two long panels together still produce a sane ticket (under 3200 px tall)', 1480 < d[0][1] < 3200 and not errs, (d, errs)); shot(pg, 'p_long_both'); b.close()
    # the switch OFF: the database sends nulls, the ticket is exactly the old one
    b, pg, errs = open_view(p, js(booking([('Asha', None)], prizes={}))); view(pg)
    check('5b.7 switch OFF (nulls): the ticket is exactly the old 900 x 1480', dims(pg) == [[900, 1480]], dims(pg)); b.close()
    # 6. a phone-width look at it
    b, pg, errs = open_view(p, js(booking([('Asha', 'You are in team TIGER 🐯')])), w=360); view(pg)
    check('6.1 no sideways scroll on a 360 px phone with the taller ticket', pg.evaluate('document.documentElement.scrollWidth') <= 360, pg.evaluate('document.documentElement.scrollWidth'))
    pg.screenshot(path='/tmp/gm_page360.png', full_page=True); b.close()
print(f'{sum(res)} passed, {len(res)-sum(res)} failed')
