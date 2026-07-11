#!/usr/bin/env python3
"""Bare-runnable selftest for wallclock.py — python3 test_wallclock.py."""

import io
import random
import sys
from contextlib import redirect_stdout

from wallclock import WallClock, check_clock

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


class FakeClock:
    """Deterministic clock source: returns queued values on each call."""

    def __init__(self, values):
        self._values = list(values)
        self._i = 0

    def __call__(self) -> float:
        v = self._values[self._i]
        self._i += 1
        return v


# --- (b) green path + (f) exact INVARIANT format ---------------------------
wc = WallClock(clock=FakeClock([0.0, 0.5]))
with wc.bound("commit", 1.0):
    pass
cap: list[str] = []
ck(check_clock(wc, emit=cap.append) == "GREEN", "green_verdict")
ck(cap == ["INVARIANT wall_clock wall-clock PASS 0 -"], "green_exact_line")

# --- (c) real violation turns RED ------------------------------------------
wc2 = WallClock(clock=FakeClock([0.0, 2.0]))
with wc2.bound("slow", 1.0):
    pass
v2 = wc2.check()
ck(len(v2) == 1 and v2[0].code == "latency_exceeded", "latency_exceeded_detected")
cap2: list[str] = []
ck(check_clock(wc2, emit=cap2.append) == "RED", "over_bound_red")
ck(cap2[0].startswith("INVARIANT wall_clock wall-clock FAIL 1 "), "fail_line_format")

# elapsed still recorded when the body raises
wc_raise = WallClock(clock=FakeClock([0.0, 0.2]))
try:
    with wc_raise.bound("boom", 1.0):
        raise RuntimeError("x")
except RuntimeError:
    pass
ck(not wc_raise.vacuous, "records_elapsed_on_exception")

# --- (a) determinism: identical clock inputs -> identical measurement ------
wa = WallClock(clock=FakeClock([0.0, 0.3]))
wb = WallClock(clock=FakeClock([0.0, 0.3]))
with wa.bound("s", 1.0):
    pass
with wb.bound("s", 1.0):
    pass
ck(wa._measurements[0].elapsed == wb._measurements[0].elapsed, "elapsed_deterministic")

# --- (d) redproof_corrupt flips green->RED and prints PLANTED ---------------
wc3 = WallClock(clock=FakeClock([0.0, 0.1]))
with wc3.bound("s", 1.0):
    pass
ck(check_clock(wc3, emit=_sink) == "GREEN", "pre_redproof_green")
buf = io.StringIO()
with redirect_stdout(buf):
    wc3.redproof_corrupt(random.Random(3))
ck("ORACLE_SELFTEST PLANTED wall-clock s" in buf.getvalue(), "planted_line_printed")
ck(check_clock(wc3, emit=_sink) == "RED", "redproof_flips_red")


def _build_multi() -> WallClock:
    # 6 within-bound steps, each elapsed 0.1 < bound 1.0
    wc = WallClock(clock=FakeClock([v for i in range(6) for v in (i * 1.0, i * 1.0 + 0.1)]))
    for i in range(6):
        with wc.bound(f"s{i}", 1.0):
            pass
    return wc


# redproof determinism: same seed picks the same label
ma, mb = _build_multi(), _build_multi()
with redirect_stdout(io.StringIO()):
    ma.redproof_corrupt(random.Random(5))
    mb.redproof_corrupt(random.Random(5))
va, vb = ma.check(), mb.check()
ck(len(va) == 1 and len(vb) == 1 and va[0].label == vb[0].label,
   "redproof_deterministic")

# --- (e) VOID floor: nothing timed -----------------------------------------
wc4 = WallClock()
ck(wc4.vacuous, "empty_is_vacuous")
capv: list[str] = []
ck(check_clock(wc4, emit=capv.append) == "VOID", "void_floor")
ck(capv == ["INVARIANT wall_clock wall-clock PASS 0 -"], "void_still_emits_line")


print("SELFTEST OK" if _fails == 0 else "SELFTEST FAIL")
sys.exit(0 if _fails == 0 else 1)
