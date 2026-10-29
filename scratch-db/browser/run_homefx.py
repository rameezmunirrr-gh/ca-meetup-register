"""Tests for the Home-page motion (assets/home-fx.js + the motion CSS in index.html).
Covers: a short entrance that never hides the buttons for long, background-only particles (never on the cards), press ripple, row flash,
the CSS-only effects, desktop-only tilt and logo-look (not on a phone), clean unmount, entrance only once, and nothing at all for reduced motion.
Every rule has a deliberate-mistake control at the end: the same checks must FAIL on a broken copy.
Run:  cd scratch-db/browser && python3 run_homefx.py | tail -1        (PAGE=/path/index.html, FX=/path/home-fx.js test other copies)"""
import os, sys, json, time
from playwright.sync_api import sync_playwright
ROOT = '/home/claude/ca-meetup-register/'
HTML = open(os.environ.get('PAGE', ROOT + 'index.html'), encoding='utf-8').read()
FX = open(os.environ.get('FX', ROOT + 'assets/home-fx.js'), encoding='utf-8').read()
LOGO = open(ROOT + 'assets/logo-fluid.js', encoding='utf-8').read()
res = []
def check(n, c, d=''): res.append(bool(c)); print(('  PASS  ' if c else '  FAIL  ') + n + ('' if c else '  ' + str(d)[:300]))
FAKE_SB = ("window.supabase={createClient:()=>({auth:{},rpc:async(n)=>n==='get_site_flags'?{data:{show_about:true,ask_email:true,ask_feedback:true},error:null}:"
           "n==='get_event_info'?{data:{event_at:'2026-11-22T08:30:00Z',venue:'Test Hall'},error:null}:{data:null,error:{message:'x'}},storage:{from:()=>({upload:async()=>({data:{},error:null})})}})};")
SAMPLER = r'''(()=>{window.__s=[];let t0=null;const op=e=>e?+getComputedStyle(e).opacity:null;
 function f(now){const inv=document.querySelector('.invite');if(inv&&t0===null)t0=now;
  if(t0!==null){const L=[...document.querySelectorAll('.invite .fxl')].map(op),R=[...document.querySelectorAll('.when>div')].map(op);
   window.__s.push({t:now-t0,btn:op(document.getElementById('go-register')),letters:L.length?Math.min(...L):null,rows:R.length?Math.min(...R):null,pres:op(document.querySelector('.pres'))})}
  if(t0===null||now-t0<3000)requestAnimationFrame(f)}
 requestAnimationFrame(f)})();'''

def new_page(p, html=None, fx=None, kind='phone', reduced=False):
    b = p.chromium.launch()
    if kind == 'phone': ctx = b.new_context(viewport={'width': 390, 'height': 844}, device_scale_factor=2, is_mobile=True, has_touch=True, reduced_motion='reduce' if reduced else 'no-preference')
    else: ctx = b.new_context(viewport={'width': 1280, 'height': 900}, reduced_motion='reduce' if reduced else 'no-preference')
    pg = ctx.new_page(); errs = []
    pg.on('pageerror', lambda e: errs.append(str(e)))
    H = HTML if html is None else html; F = FX if fx is None else fx
    def h(r):
        u = r.request.url
        if u.endswith('/test.html'): r.fulfill(body=H, content_type='text/html')
        elif '@supabase' in u: r.fulfill(body=FAKE_SB, content_type='text/javascript')
        elif 'qrcode' in u and u.split('?')[0].endswith('.js'): r.fulfill(body='window.qrcode=function(){}', content_type='text/javascript')
        elif 'logo-fluid.js' in u: r.fulfill(body=LOGO, content_type='text/javascript')
        elif 'home-fx.js' in u: r.fulfill(body=F, content_type='text/javascript')
        elif '/assets/' in u and u.split('?')[0].endswith('.png'): r.fulfill(path=ROOT + 'assets/' + u.split('/assets/')[1].split('?')[0])
        else: r.fulfill(status=204, body='')
    pg.route('**/*', h); pg.add_init_script(SAMPLER)
    pg.goto('https://example.test/test.html', wait_until='commit'); pg.wait_for_selector('#app .invite')
    return b, pg, errs

def timing(pg):
    pg.wait_for_timeout(3300); s = pg.evaluate('window.__s')
    vis = next((x['t'] for x in s if (x['btn'] or 0) > 0.05), None)
    ok = lambda x: all((x[k] is None) or x[k] >= 0.99 for k in ('btn', 'letters', 'rows', 'pres')) and x['btn'] is not None
    done = None
    for i, x in enumerate(s):
        if all(ok(y) for y in s[i:]): done = x['t']; break
    return vis, done, len(s), any(x['letters'] is not None for x in s)

def entrance_case(p, html=None, fx=None):
    b, pg, errs = new_page(p, html, fx); vis, done, n, split = timing(pg); b.close(); return vis, done, split, errs

with sync_playwright() as p:
    # ===================== PHONE =====================
    b, pg, errs = new_page(p)
    vis, done, n, split = timing(pg)
    check('P0 this test context really is a phone (no hover, coarse pointer)', pg.evaluate("matchMedia('(hover:none)').matches&&matchMedia('(pointer:coarse)').matches"))
    check('E1 the title was split into letters for the entrance (so the entrance is really running)', split)
    check('E2 the Register button starts appearing within 0.8 s (never hidden for long)', vis is not None and vis <= 800, vis)
    check('E3 the whole entrance (letters, rows, buttons) is finished within 1.6 s', done is not None and done <= 1600, (done, n))
    st = pg.evaluate("""(()=>{const g=e=>getComputedStyle(e),els=[...document.querySelectorAll('.pres,.invite .fxl,.when>div,.orn i,.orn b,#app button.big')];
      return {n:els.length,bad:els.filter(e=>+g(e).opacity<.99).length,h1:document.querySelector('.invite h1').textContent,al:document.querySelector('.invite h1').getAttribute('aria-label')}})()""")
    check('E4 afterwards everything is fully visible', st['n'] > 15 and st['bad'] == 0, st)
    check("E5 the title still reads exactly Ehsaas'26, and screen readers get it whole", st['h1'] == "Ehsaas'26" and st['al'] == "Ehsaas'26", st)
    cs = pg.evaluate("""(()=>{const a=(e,ps)=>{const c=getComputedStyle(e,ps);return c.animationName+'|'+c.animationDuration+'|'+c.animationDelay},inv=document.querySelector('.invite');
      return {d1:a(inv,'::before'),d2:a(inv,'::after'),band:a(inv.querySelector('.band')),dia:a(inv.querySelector('.orn b')),
              sw1:a(document.getElementById('go-register'),'::after'),sw2:a(document.getElementById('go-tickets'),'::after'),sw3:a(document.getElementById('go-about')||document.body,'::after')}})()""")
    check('C1 the two soft discs drift slowly (CSS animation, 18 s and 24 s)', cs['d1'].startswith('fxA|18s') and cs['d2'].startswith('fxB|24s'), cs)
    check('C2 the colour bands flow slowly (16 s loop)', cs['band'].startswith('fxFlow|16s'), cs)
    check('C3 the diamond pulses gently (3.8 s)', cs['dia'].startswith('fxDia|3.8s'), cs)
    check('C4 the sweep: on Register first after 3 s, then every 8 s; Tickets (5 s) and About (7 s) follow, so never two at once', cs['sw1'] == 'fxSh|8s|3s' and cs['sw2'] == 'fxSh|8s|5s' and cs['sw3'] == 'fxSh|8s|7s', cs)
    # particles: background only
    info = pg.evaluate('HomeFX.info()')
    check('PA1 exactly one particle canvas, few particles on a phone (12)', info['canvases'] == 1 and info['particles'] == 12, info)
    order = pg.evaluate("(()=>{const c=document.getElementById('fxc'),m=document.querySelector('main'),g=e=>getComputedStyle(e);return [g(c).position,+g(c).zIndex,g(m).position,+g(m).zIndex,g(c).pointerEvents]})()")
    check('PA2 the particle canvas sits behind the page content (main is above it) and ignores touches', order[0] == 'fixed' and order[2] == 'relative' and order[1] < order[3] and order[4] == 'none', order)
    pg.wait_for_timeout(3600)   # let the logo animation finish so the picture is still
    pg.add_style_tag(content="#fxc{background:#ff0000!important}*{animation-play-state:paused!important}")
    pg.wait_for_timeout(250)
    box = pg.evaluate("(()=>{const r=document.querySelector('.invite').getBoundingClientRect(),b=document.getElementById('go-register').getBoundingClientRect();return [r.left,r.top,r.width,r.height,b.left,b.top,b.width,b.height]})()")
    import io; from PIL import Image
    img = Image.open(io.BytesIO(pg.screenshot())).convert('RGB'); sc = 2
    red = lambda x, y: (lambda c: c[0] > 200 and c[1] < 60 and c[2] < 60)(img.getpixel((int(x * sc), int(y * sc))))
    cx_, cy_ = box[0] + box[2] / 2, box[1] + box[3] * .62
    check('PA3 painting the whole canvas red, the page edge shows red but the card does NOT (nothing can be drawn on the card)', red(3, 760) and not red(cx_, cy_) and not red(box[0] + 12, box[1] + box[3] / 2), (red(3, 760), red(cx_, cy_)))
    check('PA4 ... and the Register button is not painted over either', not red(box[4] + box[6] / 2, box[5] + box[7] / 2))
    check('PA5 no script errors', not errs, errs)
    # ripple and row flash
    pg.evaluate("window.scrollTo(0,0)")
    r1 = pg.evaluate("""(()=>{const b=document.getElementById('go-register'),r=b.getBoundingClientRect();
      b.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,clientX:r.left+30,clientY:r.top+20,pointerType:'touch'}));return b.querySelectorAll('.fxr').length})()""")
    pg.wait_for_timeout(1300)
    r2 = pg.evaluate("document.querySelectorAll('.fxr').length")
    check('R1 pressing a big button makes one ripple, and it is removed afterwards', r1 == 1 and r2 == 0, (r1, r2))
    f1 = pg.evaluate("(()=>{const w=document.querySelector('.when>div');w.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,pointerType:'touch'}));return w.classList.contains('fxh')})()")
    pg.wait_for_timeout(900); f2 = pg.evaluate("document.querySelectorAll('.fxh').length")
    check('R2 tapping a date / time / venue row flashes it, then it fades back', f1 and f2 == 0, (f1, f2))
    # desktop-only effects must not happen on a phone, even for mouse-type events
    pg.evaluate("window.__lk=[];const o=LogoFluid.look;LogoFluid.look=(x,y)=>{window.__lk.push([x,y]);return o(x,y)}")
    box2 = pg.evaluate("(()=>{const r=document.querySelector('.invite').getBoundingClientRect();return [r.left,r.top,r.width,r.height]})()")
    pg.mouse.move(box2[0] + box2[2] * .8, box2[1] + box2[3] * .2); pg.wait_for_timeout(300); pg.mouse.move(box2[0] + box2[2] * .7, box2[1] + box2[3] * .3); pg.wait_for_timeout(500)
    d = pg.evaluate("({tr:document.querySelector('.invite .inner').style.transform,glare:document.querySelectorAll('.fxg').length,lk:window.__lk.filter(a=>a[0]||a[1]).length})")
    check('D0 on a phone there is no tilt, no glare and the logo does not follow the pointer', d['tr'] == '' and d['glare'] == 0 and d['lk'] == 0, d)
    # leaving Home / coming back
    for _ in range(4):
        pg.evaluate("S.step='about';render()"); pg.wait_for_timeout(60)
        gone = pg.evaluate('HomeFX.info()'); pg.evaluate("S.step='home';render()"); pg.wait_for_timeout(120)
    back = pg.evaluate('HomeFX.info()')
    check('U1 other screens have no particle canvas; coming back four times never leaves a duplicate', gone['canvases'] == 0 and not gone['mounted'] and back['canvases'] == 1 and back['mounted'], (gone, back))
    w = pg.evaluate("({spans:document.querySelectorAll('.invite .fxl').length,waapi:document.getAnimations().filter(a=>a.constructor.name==='Animation').length})")
    check('U2 the entrance plays only once per visit (coming back to Home shows it straight away)', w['spans'] == 0 and w['waapi'] == 0, w)
    check('U3 no script errors after all that', not errs, errs); b.close()

    # ===================== DESKTOP =====================
    b, pg, errs = new_page(p, kind='desktop'); pg.wait_for_timeout(2200)
    check('K0 this test context really is a desktop (hover and fine pointer)', pg.evaluate("matchMedia('(hover:hover)').matches&&matchMedia('(pointer:fine)').matches"))
    check('K1 desktop: a few more particles (20), still one canvas', pg.evaluate('HomeFX.info()') == {'mounted': True, 'particles': 20, 'canvases': 1}, pg.evaluate('HomeFX.info()'))
    pg.evaluate("window.__lk=[];const o=LogoFluid.look;LogoFluid.look=(x,y)=>{window.__lk.push([x,y]);return o(x,y)}")
    bx = pg.evaluate("(()=>{const r=document.querySelector('.invite').getBoundingClientRect(),l=document.getElementById('logo').getBoundingClientRect();return [r.left,r.top,r.width,r.height,l.left+l.width/2,l.top+l.height/2]})()")
    pg.mouse.move(bx[0] + bx[2] * .85, bx[1] + bx[3] * .18); pg.wait_for_timeout(200); pg.mouse.move(bx[0] + bx[2] * .9, bx[1] + bx[3] * .2); pg.wait_for_timeout(900)
    tt = pg.evaluate("({tr:document.querySelector('.invite .inner').style.transform,go:getComputedStyle(document.querySelector('.invite')).getPropertyValue('--go').trim(),glare:document.querySelectorAll('.fxg').length,lk:window.__lk.slice(-1)[0]||null})")
    check('K2 desktop: the card tilts toward the mouse (perspective + rotation) with a light glare', 'perspective' in tt['tr'] and 'rotateY(0.00deg)' not in tt['tr'] and tt['glare'] == 1 and tt['go'] not in ('', '0'), tt)
    check('K3 desktop: the logo heads look toward the pointer (right of the logo, so x is positive)', tt['lk'] and tt['lk'][0] > 1, tt['lk'])
    pg.mouse.move(3, 3); pg.wait_for_timeout(400)
    near = pg.evaluate("window.__lk.slice(-1)[0]")
    check('K4a the pointer sitting at the page corner is still on the page, so the heads look toward it (left, x negative)', near and near[0] < -1, near)
    pg.evaluate("document.dispatchEvent(new MouseEvent('mouseout',{bubbles:true,relatedTarget:null}))"); pg.wait_for_timeout(1500)
    t2 = pg.evaluate("({tr:document.querySelector('.invite .inner').style.transform,go:getComputedStyle(document.querySelector('.invite')).getPropertyValue('--go').trim(),lk:window.__lk.slice(-1)[0]})")
    check('K4 pointer leaves the window: the card settles flat again, the glare goes, the heads look straight', t2['tr'] == '' and t2['go'] in ('0',) and abs(t2['lk'][0]) < .3, t2)
    pg.evaluate("S.step='about';render()"); pg.wait_for_timeout(100)
    k5 = pg.evaluate("({c:document.querySelectorAll('#fxc').length,g:document.querySelectorAll('.fxg').length,tr:!!document.querySelector('.invite')})")
    check('K5 leaving Home removes the particles and the glare', k5['c'] == 0 and k5['g'] == 0 and not k5['tr'], k5)
    check('K6 no script errors on desktop', not errs, errs); b.close()

    # ===================== REDUCED MOTION =====================
    b, pg, errs = new_page(p, kind='desktop', reduced=True); pg.wait_for_timeout(500)
    rm = pg.evaluate("""(()=>{const a=(e,ps)=>getComputedStyle(e,ps).animationName,inv=document.querySelector('.invite');
      return {canvas:document.querySelectorAll('#fxc').length,mounted:HomeFX.info().mounted,spans:document.querySelectorAll('.fxl').length,
              op:+getComputedStyle(document.getElementById('go-register')).opacity,d:a(inv,'::before'),band:a(inv.querySelector('.band')),dia:a(inv.querySelector('.orn b')),sw:a(document.getElementById('go-register'),'::after')}})()""")
    check('M1 reduced motion: no particles, no entrance, nothing animates, everything is visible at once',
          rm['canvas'] == 0 and not rm['mounted'] and rm['spans'] == 0 and rm['op'] == 1 and rm['d'] == 'none' and rm['band'] == 'none' and rm['dia'] == 'none' and rm['sw'] == 'none', rm)
    check('M2 reduced motion: no script errors', not errs, errs); b.close()

    # ===================== DELIBERATE MISTAKES =====================
    def mut(src, old, new):
        assert src.count(old) == 1, (old[:60], src.count(old)); return src.replace(old, new)
    # a) particles above the page content
    bad = mut(HTML, '#fxc{position:fixed;inset:0;width:100%;height:100%;z-index:0;', '#fxc{position:fixed;inset:0;width:100%;height:100%;z-index:3;')
    check('control: the broken copy (canvas above the page content) really differs', bad != HTML)
    b, pg, errs = new_page(p, html=bad); pg.wait_for_timeout(3800)
    pg.add_style_tag(content="#fxc{background:#ff0000!important}*{animation-play-state:paused!important}"); pg.wait_for_timeout(250)
    bb = pg.evaluate("(()=>{const r=document.querySelector('.invite').getBoundingClientRect();return [r.left,r.top,r.width,r.height]})()")
    im = Image.open(io.BytesIO(pg.screenshot())).convert('RGB'); px_ = im.getpixel((int((bb[0] + 12) * 2), int((bb[1] + bb[3] / 2) * 2)))   # card padding, not a letter
    check('control: particles drawn OVER the page content are DETECTED (the card turns red)', px_[0] > 200 and px_[1] < 60, px_); b.close()
    # b) slow entrance
    slow = mut(FX, '380+i*70)', '2380+i*70)')
    v, dn, sp, er = entrance_case(p, fx=slow)
    check('control: buttons that stay hidden for 2.4 s are DETECTED', not (v is not None and v <= 800 and dn is not None and dn <= 1600), (v, dn))
    # c) desktop effects leaking onto phones
    leak = mut(FX, 'const desk=FINE.matches&&inner;', 'const desk=inner;')
    b, pg, errs = new_page(p, fx=leak); pg.wait_for_timeout(2200)
    bx3 = pg.evaluate("(()=>{const r=document.querySelector('.invite').getBoundingClientRect();return [r.left,r.top,r.width,r.height]})()")
    pg.mouse.move(bx3[0] + bx3[2] * .8, bx3[1] + bx3[3] * .2); pg.wait_for_timeout(200); pg.mouse.move(bx3[0] + bx3[2] * .9, bx3[1] + bx3[3] * .25); pg.wait_for_timeout(600)
    lk = pg.evaluate("document.querySelector('.invite .inner').style.transform"); b.close()
    check('control: desktop-only tilt switched on for phones is DETECTED', lk != '', lk)
    # d) too many particles
    many = mut(FX, 'particlesPhone:12', 'particlesPhone:120')
    b, pg, errs = new_page(p, fx=many); pg.wait_for_timeout(500); inf = pg.evaluate('HomeFX.info()'); b.close()
    check('control: ten times too many particles is DETECTED', inf['particles'] != 12, inf)
    # e) reduced motion ignored
    ign = mut(FX, 'unmount();if(RM.matches)return;', 'unmount();')
    b, pg, errs = new_page(p, fx=ign, kind='desktop', reduced=True); pg.wait_for_timeout(500); c_ = pg.evaluate("document.querySelectorAll('#fxc').length"); b.close()
    check('control: ignoring "reduce motion" is DETECTED (a canvas appears)', c_ != 0, c_)
    # f) a canvas is left behind when leaving Home
    leak2 = mut(FX, 'cancelAnimationFrame(raf);ac.abort();timers.forEach(clearTimeout);cv.remove();', 'cancelAnimationFrame(raf);ac.abort();timers.forEach(clearTimeout);')
    b, pg, errs = new_page(p, fx=leak2); pg.wait_for_timeout(300)
    pg.evaluate("S.step='about';render()"); pg.wait_for_timeout(100); pg.evaluate("S.step='home';render()"); pg.wait_for_timeout(100); cc = pg.evaluate("document.querySelectorAll('#fxc').length"); b.close()
    check('control: a leftover particle canvas after leaving Home is DETECTED', cc != 1, cc)

n = len(res); bad = res.count(False)
print(f"{n - bad} passed, {bad} failed")
sys.exit(1 if bad else 0)
