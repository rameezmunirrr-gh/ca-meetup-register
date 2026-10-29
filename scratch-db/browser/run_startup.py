"""Startup behaviour of the public page (index.html): does Home draw early, stay put, and survive a slow or failed library?
Separate from run_public.py on purpose, because run_public.py injects a fake Supabase before the page starts and so cannot test
"what happens while the library is still downloading". Here the libraries come through the network route and can be held back.
Run:  cd scratch-db/browser && python3 run_startup.py | tail -1      (no -I needed; reads ../../index.html)
Set PAGE=/path/to/other/index.html to test a different copy."""
import os, sys, time
from playwright.sync_api import sync_playwright
ROOT = '/home/claude/ca-meetup-register/'
HTML = open(os.environ.get('PAGE', ROOT + 'index.html'), encoding='utf-8').read()
LOGO_JS = open(ROOT + 'assets/logo-fluid.js', encoding='utf-8').read()
res = []
def check(n, c, d=''): res.append(bool(c)); print(('  PASS  ' if c else '  FAIL  ') + n + ('' if c else '  ' + str(d)[:300]))

CLIENT_JS = r'''
(function(){
 const cfg = window.__CFG || {}, calls = window.__CALLS = window.__CALLS || [];
 const ok = d => ({data:d,error:null}), wait = ms => new Promise(r=>setTimeout(r,ms));
 const status = () => ok({accepting:true,spots_left:100,price_per_head:250,max_group:5,deadline:'2026-10-31T18:29:59Z',server_now:new Date().toISOString(),closed_reason:null});
 const rpcs = {
  get_event_info:()=>ok({event_at:'2026-11-22T08:30:00Z',venue:'Test Hall, Indiranagar'}),
  get_payment_info:()=>ok({upi_id:'org@upi',payee_name:'Org',whatsapp:'919999999999'}),
  get_site_flags:()=>ok({show_about:!!cfg.about,ask_email:true,ask_feedback:true}),
  get_public_status:status, registration_heartbeat:status,
 };
 const client = {auth:{},
  rpc: async (name,args)=>{ calls.push({name,args}); await wait((cfg.delay||{})[name]||0); const h=rpcs[name];
     return h ? h(args) : {data:null,error:{message:'function '+name+' does not exist'}} },
  storage:{from:()=>({upload: async (path)=>{calls.push({name:'UPLOAD',args:{path}});return {data:{},error:null}}})}};
 window.supabase = {createClient:()=>client};
})();
'''
QR_JS = 'window.qrcode=function(){return {addData(){},make(){},getModuleCount(){return 21},isDark(){return false}}};'
COUNT_JS = ("document.addEventListener('animationstart',e=>{const t=e.target;if(t&&t.classList&&t.classList.contains('invite'))"
            "window.__invite=(window.__invite||0)+1},true);")

def make(p, html=None, preloaded=True, cfg=None, sb='ok', qr='ok', w=420, h=900):
    """preloaded=True: a fake Supabase exists before the page starts (like run_public.py).
       preloaded=False: the fake library arrives through the network route like the real one, so it can be held back (sb='hold'),
       made to fail (sb='fail') or delivered (sb='ok'). qr works the same way for the QR library."""
    html = HTML if html is None else html
    b = p.chromium.launch(); pg = b.new_page(viewport={'width': w, 'height': h}); errs = []; held = []
    pg.on('pageerror', lambda e: errs.append(str(e)))
    def handler(r):
        u = r.request.url
        if u.endswith('/test.html'): r.fulfill(body=html, content_type='text/html')
        elif '@supabase/supabase-js' in u:
            if preloaded: r.fulfill(body='', content_type='text/javascript')
            elif sb == 'hold': held.append(('sb', r))
            elif sb == 'fail': r.abort()
            else: r.fulfill(body=CLIENT_JS, content_type='text/javascript')
        elif 'qrcode' in u and u.split('?')[0].endswith('.js'):
            if qr == 'hold': held.append(('qr', r))
            elif qr == 'fail': r.abort()
            else: r.fulfill(body=QR_JS, content_type='text/javascript')
        elif 'logo-fluid.js' in u: r.fulfill(body=LOGO_JS, content_type='text/javascript')
        else: r.fulfill(status=204, body='')
    pg.route('**/*', handler)
    import json
    pg.add_init_script('window.__CFG=' + json.dumps(cfg or {}) + ';' + COUNT_JS + (CLIENT_JS if preloaded else ''))
    def release(kind):
        for k, r in list(held):
            if k == kind:
                r.fulfill(body=CLIENT_JS if k == 'sb' else QR_JS, content_type='text/javascript'); held.remove((k, r))
    pg.goto('https://example.test/test.html')
    return b, pg, errs, release

LIVE = 'Test Hall, Indiranagar'
def dd(pg): return pg.evaluate("[...document.querySelectorAll('#app .when dd')].map(e=>e.textContent)")

with sync_playwright() as p:
    # ===== A. Home is drawn once and live values are patched in (no rebuild, no second fade-in, no jump)
    def scenario_a(html=None, about=True):
        b, pg, errs, rel = make(p, html=html, cfg={'about': about, 'delay': {'get_event_info': 600, 'get_site_flags': 1000, 'get_payment_info': 300}}, h=380)
        pg.wait_for_selector('#app .invite')
        first = dd(pg)
        pg.evaluate("document.querySelector('.invite').__m=1; document.getElementById('logo').__m=1; window.scrollTo(0,40)")
        s0 = pg.evaluate("window.scrollY"); tall = pg.evaluate("document.documentElement.scrollHeight>window.innerHeight")
        pg.wait_for_function("document.querySelectorAll('.when dd')[2].textContent.includes('Test Hall')", timeout=5000)
        if about: pg.wait_for_function("!!document.getElementById('go-about')", timeout=5000)
        else: pg.wait_for_timeout(1300)
        pg.wait_for_timeout(500)   # time for any extra (unwanted) redraw to show up
        m = pg.evaluate("""({same:!!(document.querySelector('.invite')||{}).__m, logo:!!(document.getElementById('logo')||{}).__m,
            fades:window.__invite||0, y:window.scrollY, about:document.querySelectorAll('#go-about').length,
            order:(()=>{const a=document.getElementById('go-about'),t=document.getElementById('go-tickets');return !!(a&&t&&t.nextElementSibling===a)})()})""")
        out = dict(first=first, now=dd(pg), s0=s0, tall=tall, errs=errs, **m); b.close(); return out
    a = scenario_a()
    check('A1 Home is drawn before any live answer arrives (it starts with the built-in text)', a['first'] and LIVE not in a['first'][2], a['first'])
    check('A2 the live date, time and venue appear on the same card', 'Sunday, 22 November 2026' in a['now'][0] and '2:00 PM' in a['now'][1] and a['now'][2] == LIVE, a['now'])
    check('A3 the card is the SAME element afterwards (not rebuilt)', a['same'])
    check('A4 the logo element is the same one too (its animation is not restarted)', a['logo'])
    check('A5 the card fades in exactly once', a['fades'] == 1, a['fades'])
    check('A6 the page is tall enough to scroll in this test (so A7 means something)', a['tall'] and a['s0'] > 0, (a['tall'], a['s0']))
    check('A7 the scroll position is kept when live values arrive (no jump to the top)', a['y'] == a['s0'], (a['y'], a['s0']))
    check('A8 the About button appears once, right after Tickets, when the switch is on', a['about'] == 1 and a['order'], a)
    check('A9 no script errors during startup', not a['errs'], a['errs'])
    a2 = scenario_a(about=False)
    check('A10 with the About switch off, no About button ever appears', a2['about'] == 0 and a2['same'] and a2['fades'] == 1, a2)

    # ===== A-control: the OLD behaviour (redraw the whole card) must be detected by the same checks
    BAD = HTML.replace('if(S.step==="home")refreshHome()', 'if(S.step==="home")render()')
    check('control: the broken copy really differs (two places changed)', BAD != HTML and HTML.count('if(S.step==="home")refreshHome()') == 2)
    ab = scenario_a(html=BAD)
    check('control: redrawing the card is DETECTED (card replaced, extra fade-ins, page jumps)', (not ab['same']) and ab['fades'] > 1 and ab['y'] != ab['s0'], (ab['same'], ab['fades'], ab['y'], ab['s0']))

n = len(res); bad = res.count(False)
print(f"{n - bad} passed, {bad} failed")
sys.exit(1 if bad else 0)
