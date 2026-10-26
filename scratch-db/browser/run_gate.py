import json
from playwright.sync_api import sync_playwright
import admin_test as A
HTML = open('/home/claude/ca-meetup-register/gate/index.html', encoding='utf-8').read()
res=[]
def check(n,c,d=''): res.append(bool(c)); print(('  PASS  ' if c else '  FAIL  ')+n+('' if c else '  '+str(d)[:200]))
def run(p, tickets, bookings, fail_col=False):
    b=p.chromium.launch(); pg=b.new_page(viewport={'width':420,'height':900}); errs=[]
    pg.on('pageerror', lambda e: errs.append(str(e)))
    pg.route('**/*', lambda r: (r.fulfill(body=HTML, content_type='text/html') if r.request.url.endswith('/gate/test.html') else r.fulfill(body='/*s*/', content_type='text/javascript') if r.request.url.endswith('.js') else r.fulfill(status=204, body='')))
    d=dict(tables=dict(staff=dict(name='Gate One',role='gate'), tickets=tickets, bookings=bookings), rpc={})
    if fail_col: d['tables']['tickets']={'error':'column tickets.transferred_out_at does not exist'}
    pg.add_init_script('window.__DB='+json.dumps(d)+';'); pg.add_init_script(A.MOCK)
    if fail_col:  # first call fails, the retry (without the column) must succeed: emulate by switching the table after first read
        pg.add_init_script("(function(){let n=0;const o=window.__DB.tables;Object.defineProperty(o,'tickets',{get(){n++;return n===1?{error:'column tickets.transferred_out_at does not exist'}:window.__OLD},configurable:true})})();")
        pg.add_init_script('window.__OLD='+json.dumps(tickets)+';')
    pg.goto('https://example.test/gate/test.html'); pg.wait_for_selector('#counts'); pg.wait_for_timeout(200); return b,pg,errs
with sync_playwright() as p:
    T=A.TICKETS; B=A.BOOKINGS
    b,pg,errs=run(p,T,B)
    c=pg.inner_text('#counts').replace('\n',' ')
    check('gate: Present / Confirmed = 0 / 3 (retired Asha not counted)', '0 / 3' in c, c)
    check('gate: Veg 0 / 2 and Non-veg 0 / 1', '0 / 2' in c and '0 / 1' in c, c)
    pg.fill('#q','Asha'); t=pg.inner_text('#results')
    check('gate: search finds the retired ticket and says Transferred', 'Transferred' in t and 'current ticket' in t, t)
    check('gate: retired ticket has NO Open/Admit button', pg.query_selector('#results button') is None)
    pg.fill('#q','Dan'); check('gate: the buyer Dan can be opened', pg.query_selector('#results button[data-pick]') is not None)
    check('look: gate has the slim header with the logo and the Gate label', pg.is_visible('.top') and pg.query_selector('.top img') is not None and 'Gate' in pg.inner_text('.top'))
    check('look: gate screen has no sideways scrolling at phone width', pg.evaluate('document.documentElement.scrollWidth<=window.innerWidth+1'))
    check('no page errors', not errs, errs); b.close()
    # database not updated yet: the first query fails on the missing column, the page must fall back
    old=[{k:v for k,v in t.items() if k!='transferred_out_at'} for t in T[1:3]]
    b,pg,errs=run(p,old,B[:2],fail_col=True); c=pg.inner_text('#counts').replace('\n',' ')
    check('gate on an old database: still loads and counts (0 / 2)', '0 / 2' in c and not errs, (c, errs)); b.close()
print(sum(res),'passed,',len(res)-sum(res),'failed')
