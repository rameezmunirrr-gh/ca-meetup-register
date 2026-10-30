"""Deliberate-mistake check for run_gamemsg.py (the game message on the public ticket). Breaks index.html one way at a time in a temporary copy (PAGE)."""
import os, re, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__)); orig = open('/home/claude/ca-meetup-register/index.html', encoding='utf-8').read()
def P(old, new):
    def f(s): assert s.count(old) == 1, (old[:60], s.count(old)); return s.replace(old, new)
    return f
M = [
 ("the panel ignores the prize and always says Tiger", P('["You are a winner!",t.game_prize]', '["You are a winner!","Tiger"]')),
 ("the panel ignores the message and always says Tiger", P('["Your secret message",t.game_message]', '["Your secret message","Tiger"]')),
 ("the page reads the wrong field name", P('["Your secret message",t.game_message]', '["Your secret message",t.message]')),
 ("text is allowed to run past the panel edge", P("const W_MSG=740;", "const W_MSG=1100;")),
 ("long messages never shrink", P("while(L.length>4&&size>30){size-=4;L=wrap(size)}", "")),
 ("View Ticket no longer asks the database again", P("if(T.code&&T.ph){try{const r=await Promise.race", "if(false&&T.code&&T.ph){try{const r=await Promise.race")),
 ("a 'not found' answer replaces the booking on screen", P("r.data&&r.data.found&&r.data.kind===d.kind", "r.data")),
 ("a failed fresh lookup blocks the ticket", P("T.res=r.data;d=r.data}}catch(_){}}", "T.res=r.data;d=r.data}}catch(_){return}}")),
 ("label for screen readers is not escaped", P('${t.game_message?". Secret message: "+esc(t.game_message):""}', '${t.game_message?". Secret message: "+t.game_message:""}')),
 ("panel is too short for its text (text spills out)", P("PH:138+m.lines.length*m.lh", "PH:138")),
 ("the ticket is not made taller (messages drawn off the picture)", P("const H=PANELS.length?PY+34:TH;", "const H=TH;")),
 ("the prize panel is never drawn", P('["You are a winner!",t.game_prize]', '["You are a winner!",""]')),
 ("the prize panel shows the team message text", P('["You are a winner!",t.game_prize]', '["You are a winner!",t.game_message]')),
 ("no gap between two panels (height does not match the layout)", P("PY+=pn.PH+(i<PANELS.length-1?18:0)", "PY+=pn.PH")),
 ("a blank panel is drawn for a missing prize", P(".map(a=>[a[0],String(a[1]||\"\").trim()]).filter(a=>a[1])", ".map(a=>[a[0],String(a[1]||\"\").trim()||\" \"])")),
 ("the prize is left out of the screen-reader label", P('${t.game_prize?". Prize: "+esc(t.game_prize):""}', '')),
 ("prize text is not escaped in the screen-reader label", P('". Prize: "+esc(t.game_prize)', '". Prize: "+t.game_prize')),
]
tmp = tempfile.mkdtemp(prefix='mut_gm_'); bad = 0
for i, (name, fn) in enumerate(M, 1):
    path = os.path.join(tmp, f'm{i:02d}.html'); open(path, 'w', encoding='utf-8').write(fn(orig))
    r = subprocess.run([sys.executable, os.path.join(HERE, 'run_gamemsg.py')], capture_output=True, text=True, env=dict(os.environ, PAGE=path), cwd=HERE, timeout=900)
    out = r.stdout + r.stderr; m = re.search(r'(\d+) passed, (\d+) failed', out)
    if not m and r.returncode != 0 and 'Traceback' in out: v, d = 'CAUGHT', 'the test script stopped with an error (counts as caught): ' + out.strip().splitlines()[-1][:80]
    elif not m: v, d = 'BROKEN', out.strip()[-250:]
    elif int(m.group(2)) > 0: v = 'CAUGHT'; d = next((l.strip() for l in out.splitlines() if 'FAIL' in l), '')[:100]
    else: v, d = 'SURVIVED', 'suite still passed: blind spot'
    if v != 'CAUGHT': bad += 1
    print(f"{i:2d}. {v:8s} {name}\n      {d}", flush=True)
print(f"\n{len(M)-bad} of {len(M)} deliberate mistakes caught." + ("" if not bad else f"  {bad} NOT caught."))
sys.exit(1 if bad else 0)
