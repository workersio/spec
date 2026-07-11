#!/usr/bin/env python3
"""Acked-durability-watch oracle — anything the API 200-acked must remain observable.

Ships with the wio workload-harness skill; copy into the repo's .workers/lib/.

The universal claim: **an effect the product acknowledged (200 / committed) must still be
observable later, byte-identical, after a delay.** Immediate asserts miss *delayed*
erasure — S2 #627's loss did not land at ack time, it landed at +64s. So the oracle
records every acked effect in a *manifest* and re-observes each one at a declared **delay
ladder** (default ``[0s, +30s, +75s]``); a missing or mutated effect at any rung is an
``INVARIANT durability_watch_<rung> FAIL`` (RED). A transient disappearance that later
returns is a *visibility flap* — not a hard loss, but a near-miss line that feeds backlog
scores.

Product-agnostic by construction: the library owns manifests, delays, payload hashing,
invariant emission, VOID floors and the selftest. The **workload** supplies exactly one
thing — ``observe(effect) -> payload|None`` — that re-reads the effect from the product
(a GET, a SELECT, a HEAD). No product imports live here.

Composes with crash-clock: a kill/restart *between* the ack and a watch rung is the
S4×durability product. So the manifest is **persisted to the case tmp dir** and the ladder
is checkpointed; ``resume_or_start`` reloads it after a restart and continues from the rung
it was on. The watch survives the process dying.

Contract emitted (parsed by the wio runtime / sweep triage):
  * ``DURAWATCH <case> manifest effects=<n> ladder=<r0,r1,...>`` — one line per armed watch.
  * ``DURAWATCH <case> rung <r> observed=<ok>/<total> flaps=<f>`` — one per rung checked.
  * ``INVARIANT durability_watch_<rung> <name> PASS|FAIL <summary>`` — the oracle verdict.
  * ``NEARMISS <case> flap effect=<id> rung=<r> ...`` — visibility flap (not a FAIL).
  * ``VERDICT GREEN|RED|VOID`` (exit 0/1/3) + VOID anti-vacuity floors (``void()``).
  * ``ORACLE_SELFTEST`` — plant one erasure (drop a manifest row's observability); must RED.

Exit codes (corpus convention): 0 green, 1 red (finding), 3 void/blocked.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Optional

# ---------------------------------------------------------------------------
# Deterministic payload hashing (process-independent)
# ---------------------------------------------------------------------------
#
# An effect's identity-under-durability is the hash of its *observable payload*, not the
# raw object: two GETs that return equal bytes are equal even if the transport reordered
# whitespace. We normalize then sha256 — sha256 (not Python hash()) so the same payload
# hashes identically in every process and machine, which is what makes a manifest written
# before a restart still validate after it.


def payload_hash(payload: Any) -> str:
    """Deterministic 64-hex digest of an observable payload.

    ``bytes`` hash as-is. Everything else is canonicalized to JSON with sorted keys, so
    ``{"a":1,"b":2}`` and ``{"b":2,"a":1}`` — the same object observed twice — collide.
    ``None`` is reserved for *unobservable* and never reaches here.
    """
    if payload is None:
        raise ValueError("payload_hash(None): None means unobservable, not a payload")
    if isinstance(payload, bytes):
        data = payload
    elif isinstance(payload, str):
        data = payload.encode("utf-8")
    else:
        data = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                          default=str).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


# ---------------------------------------------------------------------------
# Effect + delay-ladder declarations (the audited data)
# ---------------------------------------------------------------------------


@dataclass
class Effect:
    """One acked effect the product promised to keep observable.

    ``eid``       — stable id (the workload's key for this effect).
    ``query``     — opaque observation key the workload's ``observe`` uses to re-read it
                    (e.g. the object path, the row's primary key). Stored so the manifest is
                    self-describing across a restart — a fresh process reloads it and knows
                    *what* to re-observe without in-memory state.
    ``phash``     — payload_hash at ack time; the value durability must preserve.
    ``acked_at``  — monotonic-independent wall ack timestamp (epoch seconds), for reference.
    """

    eid: str
    query: Any
    phash: str
    acked_at: float


# Default ladder: check now, at +30s, at +75s. The +75s rung exists because S2 #627's loss
# landed at +64s — an immediate-only assert would call it green. Declared as data so a
# workload sweeps or extends it (e.g. tighter early rungs, a +300s soak) without code edits.
DEFAULT_LADDER = (0.0, 30.0, 75.0)


def rung_name(rung_s: float) -> str:
    """Canonical ``durability_watch_<rung>`` invariant id suffix for a rung.

    ``0`` -> ``t0``, ``30`` -> ``t30s``, ``75`` -> ``t75s`` — stable so a sweep can bucket
    reds by which rung caught the loss (an immediate loss vs a delayed erasure look
    different in the panel).
    """
    if rung_s == 0.0:
        return "t0"
    if float(rung_s).is_integer():
        return f"t{int(rung_s)}s"
    return f"t{rung_s:g}s"


# ---------------------------------------------------------------------------
# Manifest — persisted to the case tmp dir, reloads across restarts
# ---------------------------------------------------------------------------


@dataclass
class WatchState:
    """The full durability watch for one case, persisted as JSON so it survives a restart.

    ``effects``       — every acked effect (the manifest rows).
    ``ladder``        — the delay ladder (seconds after ``t0``).
    ``t0``            — epoch of the first rung (ladder is relative to this); pinned on the
                        first ``run_ladder`` so a restart resumes on the ORIGINAL clock, not
                        a fresh one — a kill must not reset the +75s deadline.
    ``done_rungs``    — indices already checked (idempotent resume: don't re-check a rung).
    ``flaps``         — per-effect flap counts observed so far (visibility backlog signal).
    ``void_floor``    — minimum acked effects for the watch to mean anything.
    """

    effects: list = field(default_factory=list)
    ladder: list = field(default_factory=lambda: list(DEFAULT_LADDER))
    t0: Optional[float] = None
    done_rungs: list = field(default_factory=list)
    flaps: dict = field(default_factory=dict)
    void_floor: int = 1

    # --- persistence -------------------------------------------------------
    def to_json(self) -> str:
        d = asdict(self)
        return json.dumps(d, sort_keys=True, separators=(",", ":"), default=str)

    @classmethod
    def from_json(cls, s: str) -> "WatchState":
        d = json.loads(s)
        st = cls(
            ladder=list(d.get("ladder", DEFAULT_LADDER)),
            t0=d.get("t0"),
            done_rungs=list(d.get("done_rungs", [])),
            flaps=dict(d.get("flaps", {})),
            void_floor=int(d.get("void_floor", 1)),
        )
        st.effects = [Effect(**e) if isinstance(e, dict) else e for e in d.get("effects", [])]
        return st


class Manifest:
    """A durability watch bound to a persistence path in the case tmp dir.

    Usage (single process, no restart)::

        m = Manifest(case="dw", path=os.path.join(tmpdir, "durawatch.json"))
        m.record(eid, query, payload)   # after each 200-ack
        m.run_ladder(observe)           # sleeps the ladder, re-observes, emits verdict

    Usage (crash-clock composition — process may die between rungs)::

        m = Manifest.resume_or_start(case, path, ladder=..., void_floor=...)
        # if fresh: record acked effects, then run_ladder(observe)
        # if resumed: run_ladder(observe) picks up on the original clock at the next rung

    Every mutation is flushed+fsync'd to ``path`` so a SIGKILL between the ack and a rung
    cannot lose the manifest.
    """

    def __init__(self, case: str, path: str, state: Optional[WatchState] = None):
        self.case = case
        self.path = path
        self.state = state if state is not None else WatchState()

    # --- construction ------------------------------------------------------
    @classmethod
    def start(cls, case: str, path: str, ladder=DEFAULT_LADDER, void_floor: int = 1) -> "Manifest":
        st = WatchState(ladder=list(ladder), void_floor=int(void_floor))
        m = cls(case, path, st)
        m._flush()
        return m

    @classmethod
    def resume_or_start(cls, case: str, path: str, ladder=DEFAULT_LADDER,
                        void_floor: int = 1) -> "Manifest":
        """Reload the persisted watch if it exists (post-restart), else start fresh.

        The reload is what makes durawatch composable with crash-clock: after a kill, a
        fresh process calls this, gets the SAME manifest (effects, original ``t0``, which
        rungs are already done) and continues the ladder without losing state.
        """
        if os.path.exists(path):
            try:
                with open(path) as f:
                    st = WatchState.from_json(f.read())
                return cls(case, path, st)
            except (json.JSONDecodeError, ValueError, KeyError):
                # Corrupt/partial write — treat as fresh rather than crash the watch.
                pass
        return cls.start(case, path, ladder=ladder, void_floor=void_floor)

    # --- persistence -------------------------------------------------------
    def _flush(self) -> None:
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            f.write(self.state.to_json())
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)  # atomic swap — never a half-written manifest on disk
        # fsync the directory so the rename is durable too (best-effort; not all FS).
        try:
            dfd = os.open(os.path.dirname(self.path) or ".", os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:
            pass

    # --- recording effects -------------------------------------------------
    def record(self, eid: str, query: Any, payload: Any) -> Effect:
        """Record one acked effect. Call immediately after the product returns 200.

        ``payload`` is the observable value at ack time; its hash is what durability must
        preserve. Flushed to disk before returning so a crash right after the ack still
        leaves the effect in the manifest.
        """
        eff = Effect(eid=eid, query=query, phash=payload_hash(payload), acked_at=time.time())
        # Replace any prior row for this eid (a re-PUT re-acks the same key with new bytes).
        self.state.effects = [e for e in self.state.effects if e.eid != eid]
        self.state.effects.append(eff)
        self._flush()
        return eff

    def effect_count(self) -> int:
        return len(self.state.effects)

    # --- the watch ladder --------------------------------------------------
    def run_ladder(self, observe: Callable[[Effect], Optional[Any]],
                   sleep: Callable[[float], None] = time.sleep,
                   selftest_victim: Optional[str] = None) -> "None":
        """Walk the delay ladder, re-observing every effect at each rung, then verdict.

        ``observe(effect) -> payload | None`` re-reads the effect from the product;
        ``None`` means *currently unobservable*. At each rung:
          * a missing (None) or mutated (hash != phash) effect that does NOT recover by the
            final rung is a hard loss -> ``INVARIANT durability_watch_<rung> FAIL`` (RED).
          * an effect that is None/mutated at one rung but correct at a later rung is a
            *visibility flap* -> a NEARMISS line, not a FAIL.

        ``selftest_victim`` (or the ``ORACLE_SELFTEST`` env) forces one effect permanently
        unobservable, so the machinery must go RED — proof it isn't vacuously green.

        This method is restart-tolerant: ``t0`` is pinned on first entry and persisted, so a
        process that dies and calls ``resume_or_start`` + ``run_ladder`` again resumes on the
        original clock and skips rungs already done.
        """
        st = self.state

        # VOID floor: too few acked effects and the watch proves nothing.
        if self.effect_count() < st.void_floor:
            void(f"only {self.effect_count()} acked effect(s) < floor {st.void_floor} — "
                 f"durability watch vacuous")

        # Selftest: pick a victim to permanently erase (first effect if unspecified).
        victim = selftest_victim
        if victim is None and selftest_active() and st.effects:
            victim = st.effects[0].eid
        if victim is not None:
            log(f"ORACLE_SELFTEST: forcing effect {victim!r} permanently unobservable")

        # Pin the clock on first entry; a resumed process keeps the original t0.
        if st.t0 is None:
            st.t0 = time.time()
            self._flush()

        ladder = list(st.ladder)
        log(f"DURAWATCH {self.case} manifest effects={self.effect_count()} "
            f"ladder={','.join(rung_name(r) for r in ladder)}")

        # Per-effect worst state across rungs, to distinguish a flap from a hard loss.
        last_bad: dict = {}   # eid -> reason at its last check ("" == last seen good)
        ever_flapped: dict = {}

        for idx, rung_s in enumerate(ladder):
            if idx in st.done_rungs:
                continue  # resumed past this rung already
            # Sleep until this rung's absolute deadline on the ORIGINAL clock.
            target = st.t0 + rung_s
            now = time.time()
            if target > now:
                sleep(target - now)

            observed_ok = 0
            flaps_this_rung = 0
            rung_id = rung_name(rung_s)
            for eff in st.effects:
                if victim is not None and eff.eid == victim:
                    payload = None  # planted erasure
                else:
                    payload = observe(eff)

                if payload is None:
                    reason = "missing"
                elif payload_hash(payload) != eff.phash:
                    reason = "mutated"
                else:
                    reason = ""  # good

                prev = last_bad.get(eff.eid, "")
                if reason == "":
                    observed_ok += 1
                    if prev != "":
                        # was bad, now good => a flap (temporarily unobservable, returned)
                        flaps_this_rung += 1
                        ever_flapped[eff.eid] = ever_flapped.get(eff.eid, 0) + 1
                        st.flaps[eff.eid] = st.flaps.get(eff.eid, 0) + 1
                        nearmiss(self.case, eff.eid, rung_id, f"recovered from {prev}")
                last_bad[eff.eid] = reason

            log(f"DURAWATCH {self.case} rung {rung_id} observed={observed_ok}/"
                f"{self.effect_count()} flaps={flaps_this_rung}")
            st.done_rungs.append(idx)
            self._flush()

        # Final verdict: any effect still bad at the LAST rung is a hard durability loss.
        lost = [(eid, reason) for eid, reason in last_bad.items() if reason != ""]
        for idx, rung_s in enumerate(ladder):
            pass  # (rungs already emitted above)

        # Emit an invariant line per rung so the panel shows which rung caught it.
        final_rung_id = rung_name(ladder[-1]) if ladder else "t0"
        if lost:
            missing = [e for e, r in lost if r == "missing"]
            mutated = [e for e, r in lost if r == "mutated"]
            summary = (f"{len(lost)} acked effect(s) not durable at {final_rung_id}: "
                       f"missing={missing[:8]} mutated={mutated[:8]}")
            red(summary, inv=(f"durability_watch_{final_rung_id}", "acked-effect-durable"))

        # All effects survived every rung — PASS, one line per rung for the audit trail.
        for rung_s in ladder:
            rid = rung_name(rung_s)
            invariant(f"durability_watch_{rid}", "acked-effect-durable", True,
                      f"{self.effect_count()}/{self.effect_count()} acked effects observable "
                      f"at {rid}"
                      + (f" (flaps recovered: {dict(st.flaps)})" if st.flaps else ""))
        flap_note = f" ({sum(st.flaps.values())} flap(s) recovered)" if st.flaps else ""
        green(f"all {self.effect_count()} acked effects durable across "
              f"{len(ladder)} rungs{flap_note}")


# ---------------------------------------------------------------------------
# Case protocol: event lines, INVARIANT/VERDICT, VOID floors, selftest
# (mirrors crashclock's protocol so the two libraries compose in one workload)
# ---------------------------------------------------------------------------


def log(msg: str) -> None:
    print(msg, flush=True)


def invariant(inv_id: str, name: str, ok: bool, summary: str) -> None:
    """Structured line the wio runtime parses into the invariants panel."""
    log(f"INVARIANT {inv_id} {name} {'PASS' if ok else 'FAIL'} {summary}")


def nearmiss(case: str, eid: str, rung: str, detail: str) -> None:
    """Visibility flap: an effect was temporarily unobservable but returned. Not a FAIL —
    a backlog signal (recurring flaps on the same effect predict a coming hard loss)."""
    log(f"NEARMISS {case} flap effect={eid} rung={rung} {detail}")


def red(msg: str, inv: Optional[tuple] = None) -> "None":
    """Emit a finding (exit 1). ``inv`` = (inv_id, name) for the failed invariant line."""
    if inv:
        invariant(inv[0], inv[1], False, msg)
    log(f"VERDICT: RED — {msg}")
    sys.exit(1)


def void(msg: str) -> "None":
    """Anti-vacuity floor: the watch never established its precondition (exit 3).

    e.g. fewer acked effects than the VOID floor — a green here would be meaningless.
    """
    log(f"VERDICT: VOID — {msg}")
    sys.exit(3)


def green(msg: str = "") -> None:
    log(f"VERDICT: GREEN{(' — ' + msg) if msg else ''}")


def selftest_active() -> bool:
    """Workloads gate the planted-erasure branch on this so a green run is quantified.

    If ``ORACLE_SELFTEST`` is set, ``run_ladder`` forces one effect unobservable and MUST
    go RED; the probe asserts that RED fires.
    """
    return bool(os.environ.get("ORACLE_SELFTEST"))


def case_tmpdir() -> str:
    """The mutable per-case scratch dir. Guest: /tmp is writable, /workspace is read-only,
    so the manifest must live under /tmp. ``DURAWATCH_DIR`` overrides for local probes."""
    d = os.environ.get("DURAWATCH_DIR") or os.path.join(
        os.environ.get("TMPDIR", "/tmp"), "durawatch")
    os.makedirs(d, exist_ok=True)
    return d


def manifest_path(case: str) -> str:
    return os.path.join(case_tmpdir(), f"{case}.durawatch.json")


__all__ = [
    "payload_hash", "Effect", "Manifest", "WatchState",
    "DEFAULT_LADDER", "rung_name",
    "log", "invariant", "nearmiss", "red", "void", "green",
    "selftest_active", "case_tmpdir", "manifest_path",
]
