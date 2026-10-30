"""Deliberate-mistake check for the admin Messages tab (run_messages.py). Breaks admin/index.html one way at a time in a temporary
copy (ADMIN_HTML), runs the suite, expects it to FAIL. CAUGHT = good. SURVIVED = blind spot. BROKEN = the mutant did not load."""
import os, re, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); SRC = '/home/claude/ca-meetup-register/admin/index.html'; orig = open(SRC, encoding='utf-8').read()
def P(old, new):
    def f(s): assert s.count(old) == 1, (old[:60], s.count(old)); return s.replace(old, new)
    return f
M = [
 ("shuffle ignores balance (random message each time)", P("pick=c[rnd(c.length)];u.forEach", "pick=ids[rnd(ids.length)];u.forEach")),
 ("shuffle is not random (always the first of the tied messages)", P("pick=c[rnd(c.length)];u.forEach", "pick=c[0];u.forEach")),
 ("group 'paid' also includes pending people", P('(m.scope==="present"?!!p.checked_in_at:p.b.status==="paid")', '(m.scope==="present"?!!p.checked_in_at:true)')),
 ("group includes rejected people", P('p.b.status!=="rejected"&&(m.scope', '(m.scope')),
 ("'present' group ignores who is present", P('m.scope==="present"?!!p.checked_in_at:', 'm.scope==="present"?true:')),
 ("'only people with no message' is ignored", P("&&(!m.nomsg||!S.tm[p.id]))}", ")}")),
 ("existing holders are not counted when topping up", P("if(m.nomsg)live().forEach", "if(false)live().forEach")),
 ("'keep bookings together' is ignored", P("m.plan={pairs:planShuffle(sc,ids,base,m.together)}", "m.plan={pairs:planShuffle(sc,ids,base,false)}")),
 ("unticked messages are still used", P("ids=(m.use||S.msgs.map(x=>x.id)).filter", "ids=(S.msgs.map(x=>x.id)).filter")),
 ("'take away from this group' clears everyone", P("{p_message:null,p_tickets:sc.map(p=>p.id)}", "{p_message:null,p_tickets:null}")),
 ("'take away' on one message ignores the message", P('{p_message:d.mclear,p_tickets:null}', '{p_message:null,p_tickets:null}')),
 ("no question before showing messages", P('if(on&&!confirm("Show messages on tickets now?', 'if(false&&!confirm("Show messages on tickets now?')),
 ("no question before replacing messages on Save", P("if(!confirm(`Save these ${pl.pairs.length} messages?", "if(false&&!confirm(`Save these ${pl.pairs.length} messages?")),
 ("no warning about replaced messages in the preview", P("${rep?` <b>${rep} of them already have a different message, which will be replaced.</b>`:\"\"}", "")),
 ("Messages tab shown even before the database file is run", P("S.msgOk=!x.error&&!y.error;", "S.msgOk=true;")),
 ("names and texts are not escaped on the list", P('<div class="mtext">${esc(x.body)}</div>', '<div class="mtext">${x.body}</div>')),
 ("sends the pairs the wrong way round", P("pairs.map(x=>({t:x[0],m:x[1]}))", "pairs.map(x=>({t:x[1],m:x[0]}))")),
 ("one-person 'None' assigns an empty message instead of clearing", P('if(v)msgPairs([[t.dataset.pid,v]],"Message saved");else', 'if(true)msgPairs([[t.dataset.pid,v]],"Message saved");else')),
 ("database error shown as a raw code", P("Object.assign(TERR,{NAME_TAKEN:\"There is already a message with that name.\",", "Object.assign(TERR,{NAME_TAKEN_X:\"There is already a message with that name.\",")),
 ("edit sends no id (creates a duplicate instead)", P('{p_id:m.edit,p_name:m.name,p_body:m.body}', '{p_id:null,p_name:m.name,p_body:m.body}')),
 ("typed text lost when another control changes", P('if(e.target.id==="mname"){S.mf.name=e.target.value;return}if(e.target.id==="mbody"){S.mf.body=e.target.value;return}', '')),
 ("Settings card not shown", P("${S.msgOk?msgCard(s):\"\"}", "")),
 ("Settings switch saves the opposite", P('{p_show:$("#msgshow").checked}', '{p_show:!$("#msgshow").checked}')),
 ("mobile: grid can grow wider than the screen (the first bug I hit)", lambda t: P("{.msgrid{grid-template-columns:minmax(0,1fr)}", "{.msgrid{grid-template-columns:1fr}")(P(".msgrid>.card{margin:0;min-width:0}", ".msgrid>.card{margin:0}")(t))),
]
tmp = tempfile.mkdtemp(prefix='mut_msg_'); bad = 0
for i, (name, fn) in enumerate(M, 1):
    path = os.path.join(tmp, f'm{i:02d}.html'); open(path, 'w', encoding='utf-8').write(fn(orig))
    r = subprocess.run([sys.executable, os.path.join(HERE, 'run_messages.py')], capture_output=True, text=True, env=dict(os.environ, ADMIN_HTML=path), cwd=HERE, timeout=900)
    out = r.stdout + r.stderr; m = re.search(r'(\d+) passed, (\d+) failed', out)
    if not m and r.returncode != 0 and 'Traceback' in out: v, d = 'CAUGHT', 'the test script stopped with an error (counts as caught): ' + out.strip().splitlines()[-1][:80]
    elif not m: v, d = 'BROKEN', out.strip()[-250:]
    elif int(m.group(2)) > 0: v = 'CAUGHT'; d = next((l.strip() for l in out.splitlines() if 'FAIL' in l), '')[:100]
    else: v, d = 'SURVIVED', 'suite still passed: blind spot'
    if v != 'CAUGHT': bad += 1
    print(f"{i:2d}. {v:8s} {name}\n      {d}", flush=True)
print(f"\n{len(M)-bad} of {len(M)} deliberate mistakes caught." + ("" if not bad else f"  {bad} NOT caught."))
sys.exit(1 if bad else 0)
