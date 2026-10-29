"""The picture made by Share QR / Download QR (blobQR in index.html): it must still SCAN, and it must show the amount and the UPI ID.
Uses the REAL qrcode-generator library (npm, installed in /home/claude/qrtest) and the real logo, then decodes the finished PNG with OpenCV.
Set up once:  mkdir -p /home/claude/qrtest && cd /home/claude/qrtest && npm i qrcode-generator@1.4.4
Run:  cd scratch-db/browser && python3 run_qrimage.py | tail -1        (PAGE=/path/to/index.html tests another copy)"""
import os, sys, json, base64, re
import numpy as np, cv2
from playwright.sync_api import sync_playwright
ROOT = '/home/claude/ca-meetup-register/'
HTML = open(os.environ.get('PAGE', ROOT + 'index.html'), encoding='utf-8').read()
QRLIB = open('/home/claude/qrtest/node_modules/qrcode-generator/qrcode.js', encoding='utf-8').read()
res = []
def check(n, c, d=''): res.append(bool(c)); print(('  PASS  ' if c else '  FAIL  ') + n + ('' if c else '  ' + str(d)[:300]))
FAKE_SB = "window.supabase={createClient:()=>({auth:{},rpc:async()=>({data:null,error:{message:'x'}}),storage:{from:()=>({upload:async()=>({data:{},error:null})})}})};"
SPY = ("window.__text=[];const _ft=CanvasRenderingContext2D.prototype.fillText;"
       "CanvasRenderingContext2D.prototype.fillText=function(t){window.__text.push(String(t));return _ft.apply(this,arguments)};")

def run(p, html, cases, outdir=None):
    b = p.chromium.launch(); pg = b.new_page(viewport={'width': 420, 'height': 900}); errs = []
    pg.on('pageerror', lambda e: errs.append(str(e)))
    def handler(r):
        u = r.request.url
        if u.endswith('/test.html'): r.fulfill(body=html, content_type='text/html')
        elif 'qrcode' in u and u.split('?')[0].endswith('.js'): r.fulfill(body=QRLIB, content_type='text/javascript')
        elif '@supabase/supabase-js' in u: r.fulfill(body=FAKE_SB, content_type='text/javascript')
        elif '/assets/' in u and u.split('?')[0].endswith('.png'): r.fulfill(path=ROOT + 'assets/' + u.split('/assets/')[1].split('?')[0])
        elif 'logo-fluid.js' in u: r.fulfill(body='', content_type='text/javascript')
        else: r.fulfill(status=204, body='')
    pg.route('**/*', handler); pg.add_init_script(SPY)
    pg.goto('https://example.test/test.html', wait_until='commit'); pg.wait_for_selector('#app .invite')
    out = []
    for i, cs in enumerate(cases):
        step = cs.get('step', 'pay')
        setup = ("S.status={price_per_head:%d,max_group:5,accepting:true,deadline:'2026-10-31T18:29:59Z'};S.n=%d;S.pay={upi:%s,payee:%s,wa:'919999999999'};S.payLoading=false;S.payFail=false;"
                 % (cs['price'], cs['n'], json.dumps(cs['upi']), json.dumps(cs['payee'])))
        if step == 'tpay': setup += "S.xp={amount:%d,code:'AB12CD34',ph:'9000000001',busy:false,err:'',file:null,sid:'x'};" % cs['amount']
        pg.evaluate(setup + "S.step=%s;render();" % json.dumps(step))
        pg.wait_for_function("document.getElementById('qr')&&document.getElementById('qr').width>100&&QRLOGO.complete", timeout=5000); pg.wait_for_timeout(300)
        link = pg.evaluate("S.step==='tpay'?upiLink(S.xp.amount,'Meetup ticket transfer'):upiLink()")
        pg.evaluate("window.__text=[]")
        data = pg.evaluate("(async()=>{const b=await blobQR();const u=new Uint8Array(await b.arrayBuffer());let s='';for(const x of u)s+=String.fromCharCode(x);return btoa(s)})()")
        page = pg.evaluate("(()=>{const v=document.querySelector('.verify'),q=document.getElementById('qr'),u=document.getElementById('uid');return {txt:v?v.textContent:'',n:document.querySelectorAll('.verify').length,between:!!(v&&q&&u&&(q.compareDocumentPosition(v)&4)&&(v.compareDocumentPosition(u)&4))}})()")
        texts = pg.evaluate("window.__text"); shown = pg.evaluate("shownAmt()"); onscreen = pg.evaluate("document.getElementById('qr').width")
        png = base64.b64decode(data)
        if outdir: open(os.path.join(outdir, f'case{i}.png'), 'wb').write(png)
        img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
        det = cv2.QRCodeDetector(); dec = det.detectAndDecode(img)[0] if img is not None else ''
        out.append(dict(page=page, link=link, decoded=dec, texts=texts, shown=shown, size=(img.shape[1], img.shape[0]) if img is not None else None, qrw=onscreen))
    out.append(dict(errs=errs)); b.close(); return out

CASES = [
    dict(price=250, n=3, upi='org@upi', payee='Mallu Articles'),
    dict(price=250, n=5, upi='a-very-long-handle.with.many.parts.2026@okhdfcbank', payee='The Malayalee Chartered Accountants Association Bengaluru Chapter'),
    dict(price=1000, n=5, upi='9876543210@ybl', payee=''),
    dict(step='tpay', amount=12345, price=250, n=1, upi='org@upi', payee='Org'),
]
with sync_playwright() as p:
    outdir = os.environ.get('OUTDIR')
    if outdir: os.makedirs(outdir, exist_ok=True)
    r = run(p, HTML, CASES, outdir); errs = r.pop()['errs']
    names = ['normal', 'very long UPI ID and payee name', 'no payee name', 'transfer payment (amount 12345)']
    for cs, o, nm in zip(CASES, r, names):
        amt = cs.get('amount', cs['price'] * cs['n'])
        check(f'[{nm}] the image still SCANS and gives back exactly the payment link', o['decoded'] == o['link'], (o['decoded'], o['link']))
        check(f'[{nm}] the image shows the amount "Pay ₹{amt}"', f'Pay ₹{amt}' in o['texts'], o['texts'])
        check(f'[{nm}] the image shows the full UPI ID', cs['upi'] in o['texts'], o['texts'])
        joined = ' '.join(o['texts'])
        check(f'[{nm}] the picture carries the warning (after scanning, check the UPI ID matches the one below)', 'Important:' in joined and 'check that the UPI ID shown in your app matches the UPI ID below.' in joined, o['texts'])
        check(f'[{nm}] the pay screen shows the warning once, between the QR and the UPI ID', o['page']['n'] == 1 and o['page']['between'] and 'matches the UPI ID below' in o['page']['txt'], o['page'])
        if cs['payee']: check(f'[{nm}] the image shows who is being paid', 'to ' + cs['payee'] in o['texts'], o['texts'])
        else: check(f'[{nm}] with no payee name no "to ..." line is drawn', not any(t.startswith('to ') for t in o['texts']), o['texts'])
    check('the image is wider than the on-screen QR and the QR is not scaled (width at least 560)', r[0]['size'][0] >= 560 and r[0]['size'][1] > r[0]['qrw'], r[0]['size'])
    check('no script errors', not errs, errs)

    # ---- deliberate mistakes: the checks above must be able to FAIL
    def mutate(old, new):
        assert HTML.count(old) == 1, old; return HTML.replace(old, new)
    SMALL = mutate('x.drawImage(q,Math.round((W-q.width)/2),top);', 'x.drawImage(q,Math.round((W-q.width/5)/2),top,q.width/5,q.height/5);')
    m1 = run(p, SMALL, CASES[:1])[0]
    check('control: shrinking the QR inside the picture is DETECTED (it no longer scans)', m1['decoded'] != m1['link'], m1['decoded'])
    NOUPI = mutate('x.fillStyle="#0A2147";s=fit(upi,W-side*2,40,"800");x.fillText(upi,W/2,y+90);', '')
    m2 = run(p, NOUPI, CASES[:1])[0]
    check('control: leaving the UPI ID out of the picture is DETECTED', CASES[0]['upi'] not in m2['texts'], m2['texts'])
    NOAMT = mutate('x.fillText("Pay ₹"+amt,W/2,88);', '')
    m3 = run(p, NOAMT, CASES[:1])[0]
    check('control: leaving the amount out of the picture is DETECTED', 'Pay ₹750' not in m3['texts'], m3['texts'])

    NOWARN_IMG = mutate('const WARN="After you scan, check that the UPI ID shown in your app matches the UPI ID below.";', 'const WARN="";')
    m4 = run(p, NOWARN_IMG, CASES[:1])[0]
    check('control: dropping the warning from the picture is DETECTED', 'matches the UPI ID below.' not in ' '.join(m4['texts']), m4['texts'])
    NOWARN_PAGE = HTML.replace('<p class="verify" role="note">', '<p class="verifyX" role="note">')
    check('control: the page-warning mutant really differs', NOWARN_PAGE != HTML)
    m5 = run(p, NOWARN_PAGE, CASES[:1])[0]
    check('control: dropping the warning from the pay screen is DETECTED', m5['page']['n'] != 1, m5['page'])

n = len(res); bad = res.count(False)
print(f"{n - bad} passed, {bad} failed")
sys.exit(1 if bad else 0)
