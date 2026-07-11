#!/usr/bin/env python3
"""Persona-ledger oracle — what the product *told an actor* must match the world.

Ships with the wio workload-harness skill; copy into the repo's .workers/lib/.

The universal claim, per actor: **every acknowledgement the product handed this
actor is honoured by a later re-read of the world, and every refusal it handed
this actor did not secretly happen.** One ``PersonaLedger`` records, from the
point of view of a single actor (a persona instance in a scenario), the three
things that make an interaction falsifiable:

  * ``acked(kind, key, value)``  — "the product told me ``kind/key`` succeeded
    (optionally with ``value``)."
  * ``denied(kind, key, reason)`` — "the product told me ``kind/key`` was refused."
  * ``observe(kind, key, value, present)`` — what a later, independent re-read of
    the world actually shows for ``kind/key``.

``check()`` cross-checks the two channels and yields a ``Violation`` for each
divergence:

  * ``acked_lost``      — acked but a re-read cannot observe it (durability /
    lost-write). No observation recorded counts as lost: an ack the flow never
    re-read back is unproven, and this oracle only calls green what it saw.
  * ``acked_mutated``   — acked with a value, but the re-read shows a *different*
    value (silent corruption). Only compared when a value was acked; an ack that
    carried no value (``value=None``) is checked for presence only.
  * ``denied_happened`` — denied, yet a re-read observes it present (the refusal
    was a lie; a phantom write).

Product-agnostic by construction: ``kind``/``key``/``value`` are opaque tokens the
workload supplies. No product imports live here.

Contract emitted (parsed by the wio runtime / sweep triage), via ``check_all``:
  * ``INVARIANT ledger_<actor> persona-ledger PASS|FAIL <n_violations> <detail|-> ``
    — one line per actor.
  * ``ORACLE_SELFTEST PLANTED ledger <actor> <kind>/<key>`` — ``redproof_corrupt``
    plants one lost effect IN THE OBSERVATION CHANNEL ONLY (never the SUT), so a
    green recording must flip RED — proof the oracle isn't vacuously green.

Anti-vacuity: a ledger that recorded no acks and no denials is ``vacuous``;
``check_all`` returns VOID only when *every* ledger is vacuous (nothing was
witnessed, so a green would be meaningless).

Aggregate verdicts mirror the corpus convention: GREEN (all honoured), RED (a
divergence — a finding), VOID (nothing witnessed).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

# A sentinel would let us distinguish "no value tracked" from "acked None"; the
# contract fixes ``value=None`` as the default, so we adopt the documented rule:
# ``value=None`` means presence-only (no mutation comparison for that entry).


def log(msg: str) -> None:
    print(msg, flush=True)


@dataclass
class Violation:
    """One divergence between what an actor was told and what the world shows."""

    actor: str
    code: str      # acked_lost | acked_mutated | denied_happened
    kind: str
    key: str
    detail: str


@dataclass
class _Obs:
    present: bool
    value: Any


class PersonaLedger:
    """The told-vs-observed ledger for a single actor.

    Insertion order is preserved so ``check()`` and ``redproof_corrupt`` are
    deterministic (the first-recorded violation is the one ``check_all`` prints).
    """

    def __init__(self, actor_id: str):
        self.actor_id = actor_id
        self._acked: dict[tuple[str, str], Any] = {}
        self._denied: dict[tuple[str, str], str] = {}
        self._obs: dict[tuple[str, str], _Obs] = {}

    # --- the told channel (what the product claimed to this actor) ----------
    def acked(self, kind: str, key: str, value=None) -> None:
        """Record that the product told this actor ``kind/key`` succeeded."""
        self._acked[(kind, key)] = value

    def denied(self, kind: str, key: str, reason: str = "") -> None:
        """Record that the product told this actor ``kind/key`` was refused."""
        self._denied[(kind, key)] = reason

    # --- the observed channel (what a later re-read of the world shows) -----
    def observe(self, kind: str, key: str, value=None, present: bool = True) -> None:
        """Record what an independent re-read shows for ``kind/key``."""
        self._obs[(kind, key)] = _Obs(present=present, value=value)

    # --- the cross-check ----------------------------------------------------
    def check(self) -> list["Violation"]:
        vios: list[Violation] = []
        for (kind, key), av in self._acked.items():
            obs = self._obs.get((kind, key))
            if obs is None or not obs.present:
                vios.append(Violation(
                    self.actor_id, "acked_lost", kind, key,
                    f"{kind}/{key} acked but not observed"))
            elif av is not None and obs.value != av:
                vios.append(Violation(
                    self.actor_id, "acked_mutated", kind, key,
                    f"{kind}/{key} acked={av!r} observed={obs.value!r}"))
        for (kind, key), _reason in self._denied.items():
            obs = self._obs.get((kind, key))
            if obs is not None and obs.present:
                vios.append(Violation(
                    self.actor_id, "denied_happened", kind, key,
                    f"{kind}/{key} denied but observed present"))
        return vios

    # --- redproof (observation channel only) --------------------------------
    def redproof_corrupt(self, rng) -> None:
        """Plant one violation in the OBSERVATION channel — never the SUT.

        Prefers a currently-green acked entry, flips its observation to absent
        (an ``acked_lost``). With no acked entries, corrupts a denied entry into
        an observed-present (a ``denied_happened``). ``rng`` (a ``random.Random``)
        selects the target so the plant is deterministic under the case seed.
        """
        acked_keys = list(self._acked.keys())
        if acked_keys:
            kind, key = acked_keys[rng.randrange(len(acked_keys))]
            self._obs[(kind, key)] = _Obs(present=False, value=None)
            log(f"ORACLE_SELFTEST PLANTED ledger {self.actor_id} {kind}/{key}")
            return
        denied_keys = list(self._denied.keys())
        if denied_keys:
            kind, key = denied_keys[rng.randrange(len(denied_keys))]
            self._obs[(kind, key)] = _Obs(present=True, value=None)
            log(f"ORACLE_SELFTEST PLANTED ledger {self.actor_id} {kind}/{key}")
            return
        # Vacuous ledger: nothing to corrupt (the VOID floor handles it).

    @property
    def vacuous(self) -> bool:
        return not self._acked and not self._denied


def check_all(ledgers, emit=print) -> str:
    """Emit one INVARIANT line per actor; return the aggregate verdict.

    ``INVARIANT ledger_<actor> persona-ledger PASS|FAIL <n> <first-detail|->``

    Returns ``"VOID"`` only when every ledger is vacuous (nothing witnessed),
    ``"RED"`` if any actor has a violation, else ``"GREEN"``.
    """
    ledgers = list(ledgers)
    any_nonvacuous = False
    any_violation = False
    for lg in ledgers:
        vios = lg.check()
        n = len(vios)
        if not lg.vacuous:
            any_nonvacuous = True
        if n:
            any_violation = True
        detail = vios[0].detail if vios else "-"
        status = "FAIL" if n else "PASS"
        emit(f"INVARIANT ledger_{lg.actor_id} persona-ledger {status} {n} {detail}")
    if not any_nonvacuous:
        return "VOID"
    return "RED" if any_violation else "GREEN"


__all__ = ["PersonaLedger", "Violation", "check_all", "log"]
