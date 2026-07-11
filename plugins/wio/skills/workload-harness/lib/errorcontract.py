#!/usr/bin/env python3
"""Error-contract oracle — every failure is the *promised* failure.

Ships with the wio workload-harness skill; copy into the repo's .workers/lib/.

The universal claim: **when a product operation fails, it fails with one of the
exceptions its contract documents; an undocumented exception (a raw driver
error, a ``KeyError``, an ``AssertionError``, any product-internal leak) is the
5xx class — a bug the caller could not have anticipated.** Symmetrically, an
operation the workload declared ``must-fail`` that returns success is a *silent
success* — the guard the flow relied on did not fire.

Usage is a context manager around each product call::

    errors = ErrorContract({"pay": (Declined, InsufficientFunds)})
    with errors.expect("pay") as oc:
        sut.pay(order)
    if oc.raised and oc.documented:
        ...            # a promised refusal — the flow branches on it
    elif oc.ok:
        ...            # success (or documented failure); flow continues

``expect`` records the outcome and **swallows** the exception so the flow keeps
running (an oracle observes; it does not abort the scenario) — unless
``fatal=True``, in which case an *undocumented* exception is re-raised after
recording. Documented exceptions are always recorded-as-fine and swallowed.

The yielded ``Outcome`` (see below) is the small result handle the flow branches
on — the CONTRACT names no result object, so this module adds ``Outcome`` as the
documented API extension.

``outcome`` modes:
  * ``"any"``       — success or a documented error are both fine.
  * ``"must-fail"`` — a silent success is a violation (``silent_success``).

Contract emitted (parsed by the wio runtime / sweep triage), via
``check_contract``:
  * ``INVARIANT error_contract error-contract PASS|FAIL <n> <detail|->``
  * ``ORACLE_SELFTEST PLANTED error-contract <op> documented->undocumented`` —
    ``redproof_corrupt`` rewrites one recorded fine outcome into an undocumented
    error IN THE RECORDED-OBSERVATION CHANNEL ONLY (never the SUT), so a green
    contract must flip RED.

Anti-vacuity: a contract that recorded zero ops is ``vacuous``; ``check_contract``
returns VOID (a green over nothing is meaningless).
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Optional


def log(msg: str) -> None:
    print(msg, flush=True)


@dataclass
class Violation:
    """One error-contract breach."""

    op_label: str
    code: str      # undocumented_error | silent_success
    detail: str


class Outcome:
    """Result handle yielded by ``ErrorContract.expect`` (module API extension).

    ``op_label``   — the op this outcome is for.
    ``raised``     — the exception instance the body raised, or ``None`` on success.
    ``documented`` — True iff ``raised`` is one of the op's documented classes.
    ``exception``  — alias of ``raised`` (readability at the call site).
    ``ok``         — True on success or a documented failure; False on an
                     undocumented error (the flow's "this went wrong unexpectedly").
    """

    def __init__(self, op_label: str):
        self.op_label = op_label
        self.raised: Optional[BaseException] = None
        self.documented: bool = False

    @property
    def exception(self) -> Optional[BaseException]:
        return self.raised

    @property
    def ok(self) -> bool:
        return self.raised is None or self.documented


@dataclass
class _Op:
    op_label: str
    outcome: str
    raised: Optional[BaseException]
    documented: bool


class ErrorContract:
    """Records each guarded op's outcome and grades it against the documented set.

    ``documented`` maps ``op_label -> tuple of exception classes`` that are the
    contractually-allowed failure modes for that op.
    """

    def __init__(self, documented: dict[str, tuple]):
        self.documented = dict(documented)
        self._ops: list[_Op] = []

    @contextmanager
    def expect(self, op_label: str, outcome: str = "any", fatal: bool = False):
        """Guard one product call; yield an ``Outcome`` the flow branches on.

        On an exception: record it, mark documented/undocumented, then swallow —
        unless it is undocumented and ``fatal=True`` (re-raised after recording).
        On success: record it (a ``must-fail`` op with no exception is a
        ``silent_success`` violation, surfaced by ``check``).
        """
        oc = Outcome(op_label)
        try:
            yield oc
        except Exception as e:  # noqa: BLE001 — the oracle grades every leak
            docs = self.documented.get(op_label, ())
            documented = isinstance(e, docs)
            oc.raised = e
            oc.documented = documented
            self._ops.append(_Op(op_label, outcome, e, documented))
            if not documented and fatal:
                raise
            return  # swallow: documented, or undocumented-non-fatal
        # success path
        self._ops.append(_Op(op_label, outcome, None, False))

    def check(self) -> list["Violation"]:
        vios: list[Violation] = []
        for op in self._ops:
            if op.raised is not None and not op.documented:
                vios.append(Violation(
                    op.op_label, "undocumented_error",
                    f"{op.op_label} raised undocumented "
                    f"{type(op.raised).__name__}: {op.raised}"))
            elif op.raised is None and op.outcome == "must-fail":
                vios.append(Violation(
                    op.op_label, "silent_success",
                    f"{op.op_label} succeeded but outcome was must-fail"))
        return vios

    def redproof_corrupt(self, rng) -> None:
        """Rewrite one recorded fine outcome into an undocumented error.

        Observation channel only — mutates the recorded ``_Op``, never the SUT.
        Prefers a currently-green op so a passing contract must flip RED. ``rng``
        (a ``random.Random``) picks the target for determinism under the seed.
        """
        if not self._ops:
            return  # vacuous — the VOID floor handles it
        bad_ids = {id(op) for op in self._ops
                   if (op.raised is not None and not op.documented)
                   or (op.raised is None and op.outcome == "must-fail")}
        fine = [op for op in self._ops if id(op) not in bad_ids]
        pool = fine or self._ops
        target = pool[rng.randrange(len(pool))]
        target.raised = RuntimeError("planted-undocumented")
        target.documented = False
        target.outcome = "any"  # so it grades as undocumented_error, not silent_success
        log(f"ORACLE_SELFTEST PLANTED error-contract {target.op_label} "
            f"documented->undocumented")

    @property
    def vacuous(self) -> bool:
        return not self._ops


def check_contract(contract, emit=print) -> str:
    """Emit the INVARIANT line; return the verdict.

    ``INVARIANT error_contract error-contract PASS|FAIL <n> <detail|->``
    Returns VOID if the contract witnessed no ops, else RED on any breach, else
    GREEN.
    """
    vios = contract.check()
    n = len(vios)
    detail = vios[0].detail if vios else "-"
    status = "FAIL" if n else "PASS"
    emit(f"INVARIANT error_contract error-contract {status} {n} {detail}")
    if contract.vacuous:
        return "VOID"
    return "RED" if n else "GREEN"


__all__ = ["ErrorContract", "Outcome", "Violation", "check_contract", "log"]
