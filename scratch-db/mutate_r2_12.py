"""Deliberate-mistake check for test_r2_12.py.

A green test run alone proves little. This script breaks sql/r2_12_gate_undo.sql in one way at a time (a "mutant"),
runs test_r2_12.py against each broken copy, and expects the suite to FAIL every time.
  - CAUGHT   = the suite failed (good: the test notices that mistake)
  - SURVIVED = the suite still passed (bad: the test has a blind spot)
  - BROKEN   = the broken SQL would not even load (the mutant is not a useful test; fix the mutant)
It never touches the real file: broken copies go in a temporary folder. Run:  python3 mutate_r2_12.py
"""
import os, re, subprocess, sys, tempfile
HERE = os.path.dirname(os.path.abspath(__file__))
SRC = '/home/claude/ca-meetup-register/sql/r2_12_gate_undo.sql'
orig = open(SRC).read()

def patch(old, new, expect=1, nth=None):
    """Return a function that edits the SQL text. It asserts the old text exists exactly `expect` times,
    so a mutant can never silently do nothing."""
    def f(s):
        assert s.count(old) == expect, f"expected {expect} x {old!r}, found {s.count(old)}"
        if nth is None: return s.replace(old, new)
        parts = s.split(old); return old.join(parts[:nth]) + new + old.join(parts[nth:])
    return f

SET_NULL = ", checked_in_by = null"
MUTANTS = [
    ("no staff check at all (anyone signed in can undo)", patch("if not is_staff() then raise exception 'NOT_ALLOWED'; end if;", "")),
    ("window is 20 minutes instead of 2", patch("interval '2 minutes'", "interval '20 minutes'")),
    ("window is 1 minute instead of 2", patch("interval '2 minutes'", "interval '1 minute'")),
    ("every staff member is treated as an admin", patch("if is_admin() then", "if true then")),
    ("admins get no special power (same 2-minute rule)", patch("if is_admin() then", "if false then")),
    ("time comparison flipped (only OLD check-ins can be undone)", patch("checked_in_at > now()", "checked_in_at < now()")),
    ("admin branch also 'undoes' tickets that were never admitted", patch("where id = p_id and checked_in_at is not null;", "where id = p_id;")),
    ("admin branch clears EVERY admitted ticket, not just the one", patch("where id = p_id and checked_in_at is not null;", "where checked_in_at is not null;")),
    ("gate branch clears every ticket admitted in the last 2 minutes", patch("where id = p_id and checked_in_at is not null and checked_in_at", "where checked_in_at is not null and checked_in_at")),
    ("no error when nothing matched (silent success)", patch("if n = 0 then raise exception 'UNDO_EXPIRED'; end if;", "")),
    ("admin undo forgets to clear who admitted", patch(SET_NULL, "", expect=2, nth=1)),
    ("gate undo forgets to clear who admitted", patch(SET_NULL, "", expect=2, nth=2)),
    ("visitors (anon) are allowed to execute it", lambda s: s + "\ngrant execute on function public.gate_undo_checkin(uuid) to anon;\n"),
    ("everyone (PUBLIC) is allowed to execute it", lambda s: s + "\ngrant execute on function public.gate_undo_checkin(uuid) to public;\n"),
    ("function is no longer security definer", patch(" security definer", "")),
    ("search_path is no longer fixed", patch(" set search_path to 'public'", "")),
]

tmp = tempfile.mkdtemp(prefix='mut_r2_12_')
rows, bad = [], 0
for i, (name, fn) in enumerate(MUTANTS, 1):
    path = os.path.join(tmp, f'mutant_{i:02d}.sql')
    open(path, 'w').write(fn(orig))
    assert open(path).read() != orig, "mutant is identical to the original"
    r = subprocess.run([sys.executable, os.path.join(HERE, 'test_r2_12.py')], capture_output=True, text=True,
                       env=dict(os.environ, R12=path), cwd=HERE, timeout=600)
    out = r.stdout + r.stderr
    m = re.search(r'=> (\d+) passed, (\d+) failed', out)
    if 'SQL FILE FAILED' in out or not m: verdict, detail = 'BROKEN', out.strip()[-300:]
    elif int(m.group(2)) > 0:
        verdict = 'CAUGHT'; first = next((l.strip() for l in out.splitlines() if 'FAIL' in l), '')
        detail = f"{m.group(2)} check(s) failed, first: {first[:90]}"
    else: verdict, detail = 'SURVIVED', 'suite still passed: blind spot'
    if verdict != 'CAUGHT': bad += 1
    print(f"{i:2d}. {verdict:8s} {name}\n      {detail}", flush=True)

print(f"\n{len(MUTANTS) - bad} of {len(MUTANTS)} deliberate mistakes caught." + ("" if not bad else f"  {bad} NOT caught: see above."))
sys.exit(1 if bad else 0)
