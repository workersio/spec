#!/usr/bin/env python3
"""Bare-runnable selftest for errorcontract.py — python3 test_errorcontract.py."""

import io
import random
import sys
from contextlib import redirect_stdout

from errorcontract import ErrorContract, Outcome, check_contract

_fails = 0


def ck(cond: bool, name: str) -> None:
    global _fails
    if cond:
        print(f"PASS {name}")
    else:
        print(f"FAIL {name}")
        _fails += 1


def _sink(_):
    pass


class Declined(Exception):
    pass


# --- (b) green path: success + exact INVARIANT format ----------------------
ec = ErrorContract({"pay": (Declined,)})
with ec.expect("pay") as oc:
    pass  # success
ck(oc.raised is None and oc.ok, "success_outcome_ok")
cap: list[str] = []
ck(check_contract(ec, emit=cap.append) == "GREEN", "green_verdict")
ck(cap == ["INVARIANT error_contract error-contract PASS 0 -"], "green_exact_line")

# documented error: recorded fine, swallowed, flow continues
ec2 = ErrorContract({"pay": (Declined,)})
reached = False
with ec2.expect("pay") as oc2:
    raise Declined("card declined")
reached = True
ck(reached, "documented_error_swallowed")
ck(oc2.raised is not None and oc2.documented and oc2.ok, "documented_outcome_ok")
ck(check_contract(ec2, emit=_sink) == "GREEN", "documented_green")

# --- (c) undocumented error -> RED, swallowed ------------------------------
ec3 = ErrorContract({"pay": (Declined,)})
reached3 = False
with ec3.expect("pay") as oc3:
    raise KeyError("internal")
reached3 = True
ck(reached3, "undocumented_error_swallowed")
ck(oc3.raised is not None and not oc3.documented and not oc3.ok, "undocumented_not_ok")
cap3: list[str] = []
ck(check_contract(ec3, emit=cap3.append) == "RED", "undocumented_red")
ck(cap3[0].startswith("INVARIANT error_contract error-contract FAIL 1 "),
   "fail_line_format")

# must-fail silent success -> RED
ec4 = ErrorContract({"pay": (Declined,)})
with ec4.expect("pay", outcome="must-fail"):
    pass
v4 = ec4.check()
ck(len(v4) == 1 and v4[0].code == "silent_success", "silent_success_detected")
ck(check_contract(ec4, emit=_sink) == "RED", "silent_success_red")

# fatal=True re-raises undocumented after recording
ec5 = ErrorContract({"pay": (Declined,)})
raised = False
try:
    with ec5.expect("pay", fatal=True):
        raise KeyError("boom")
except KeyError:
    raised = True
ck(raised, "fatal_reraises")
ck(check_contract(ec5, emit=_sink) == "RED", "fatal_still_recorded_red")

# --- (d) redproof_corrupt flips green->RED and prints PLANTED ---------------
ec6 = ErrorContract({"pay": (Declined,)})
with ec6.expect("pay"):
    pass
ck(check_contract(ec6, emit=_sink) == "GREEN", "pre_redproof_green")
buf = io.StringIO()
with redirect_stdout(buf):
    ec6.redproof_corrupt(random.Random(1))
ck("ORACLE_SELFTEST PLANTED error-contract pay" in buf.getvalue(),
   "planted_line_printed")
ck(check_contract(ec6, emit=_sink) == "RED", "redproof_flips_red")


def _build_multi() -> ErrorContract:
    ec = ErrorContract({f"op{i}": (Declined,) for i in range(6)})
    for i in range(6):
        with ec.expect(f"op{i}"):
            pass
    return ec


# --- (a) determinism: same seed picks the same op --------------------------
ea, eb = _build_multi(), _build_multi()
with redirect_stdout(io.StringIO()):
    ea.redproof_corrupt(random.Random(11))
    eb.redproof_corrupt(random.Random(11))
va, vb = ea.check(), eb.check()
ck(len(va) == 1 and len(vb) == 1 and va[0].op_label == vb[0].op_label,
   "redproof_deterministic")

# --- (e) VOID floor: nothing recorded --------------------------------------
ec7 = ErrorContract({})
ck(ec7.vacuous, "empty_is_vacuous")
capv: list[str] = []
ck(check_contract(ec7, emit=capv.append) == "VOID", "void_floor")
ck(capv == ["INVARIANT error_contract error-contract PASS 0 -"],
   "void_still_emits_line")


print("SELFTEST OK" if _fails == 0 else "SELFTEST FAIL")
sys.exit(0 if _fails == 0 else 1)
