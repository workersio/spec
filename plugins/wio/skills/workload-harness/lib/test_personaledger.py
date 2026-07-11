#!/usr/bin/env python3
"""Bare-runnable selftest for personaledger.py — python3 test_personaledger.py."""

import io
import random
import sys
from contextlib import redirect_stdout

from personaledger import PersonaLedger, Violation, check_all

_fails = 0


def ck(cond: bool, name: str) -> None:
    global _fails
    if cond:
        print(f"PASS {name}")
    else:
        print(f"FAIL {name}")
        _fails += 1


def _sink(_):  # emit that discards, for verdict-only assertions
    pass


# --- (b) green path + (f) exact INVARIANT line format ----------------------
lg = PersonaLedger("shopper1")
lg.acked("order", "o1", "paid")
lg.observe("order", "o1", "paid")
cap: list[str] = []
verdict = check_all([lg], emit=cap.append)
ck(verdict == "GREEN", "green_path_verdict")
ck(cap == ["INVARIANT ledger_shopper1 persona-ledger PASS 0 -"],
   "green_exact_line")

# presence-only ack (value=None) passes when observed present
lg_p = PersonaLedger("shopper1b")
lg_p.acked("session", "s1")
lg_p.observe("session", "s1")
ck(check_all([lg_p], emit=_sink) == "GREEN", "presence_only_green")

# --- (c) real violations turn RED ------------------------------------------
# acked_lost
lg2 = PersonaLedger("shopper2")
lg2.acked("order", "o2", "paid")
lg2.observe("order", "o2", present=False)
v2 = lg2.check()
ck(len(v2) == 1 and v2[0].code == "acked_lost", "acked_lost_detected")
cap2: list[str] = []
ck(check_all([lg2], emit=cap2.append) == "RED", "acked_lost_red")
ck(cap2[0].startswith("INVARIANT ledger_shopper2 persona-ledger FAIL 1 "),
   "fail_line_format")

# acked_mutated
lg3 = PersonaLedger("shopper3")
lg3.acked("order", "o3", "paid")
lg3.observe("order", "o3", "refunded")
v3 = lg3.check()
ck(len(v3) == 1 and v3[0].code == "acked_mutated", "acked_mutated_detected")

# denied_happened
lg4 = PersonaLedger("shopper4")
lg4.denied("order", "o4", "insufficient-funds")
lg4.observe("order", "o4", present=True)
v4 = lg4.check()
ck(len(v4) == 1 and v4[0].code == "denied_happened", "denied_happened_detected")
ck(check_all([lg4], emit=_sink) == "RED", "denied_happened_red")

# --- (d) redproof_corrupt flips green->RED and prints PLANTED ---------------
lg5 = PersonaLedger("shopper5")
lg5.acked("k", "key1", "v")
lg5.observe("k", "key1", "v")
ck(check_all([lg5], emit=_sink) == "GREEN", "pre_redproof_green")
buf = io.StringIO()
with redirect_stdout(buf):
    lg5.redproof_corrupt(random.Random(42))
out = buf.getvalue()
ck("ORACLE_SELFTEST PLANTED ledger shopper5 k/key1" in out, "planted_line_printed")
ck(check_all([lg5], emit=_sink) == "RED", "redproof_flips_red")


def _build_multi(actor: str) -> PersonaLedger:
    lg = PersonaLedger(actor)
    for i in range(6):
        lg.acked("k", f"key{i}", "v")
        lg.observe("k", f"key{i}", "v")
    return lg


# --- (a) determinism: same seed picks the same target ----------------------
la = _build_multi("a")
lb = _build_multi("b")
with redirect_stdout(io.StringIO()):
    la.redproof_corrupt(random.Random(7))
    lb.redproof_corrupt(random.Random(7))
va, vb = la.check(), lb.check()
ck(len(va) == 1 and len(vb) == 1 and va[0].key == vb[0].key,
   "redproof_deterministic")

# a different seed can pick a different target (sanity that rng is consulted)
lc = _build_multi("c")
with redirect_stdout(io.StringIO()):
    lc.redproof_corrupt(random.Random(99))
ck(len(lc.check()) == 1, "redproof_single_plant")

# --- (e) VOID floor fires when nothing was witnessed -----------------------
empty = PersonaLedger("z")
ck(empty.vacuous, "empty_is_vacuous")
capv: list[str] = []
ck(check_all([empty], emit=capv.append) == "VOID", "void_floor")
ck(capv == ["INVARIANT ledger_z persona-ledger PASS 0 -"], "void_still_emits_line")
ck(check_all([], emit=_sink) == "VOID", "no_ledgers_void")

# a vacuous ledger among non-vacuous does not force VOID
ck(check_all([empty, lg], emit=_sink) == "GREEN", "mixed_not_void")


print("SELFTEST OK" if _fails == 0 else "SELFTEST FAIL")
sys.exit(0 if _fails == 0 else 1)
