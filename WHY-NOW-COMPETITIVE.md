# Why the (generator × simulation × AI-drafting) triad is unbuilt — and our position
Research-agent synthesis, 2026-07-15. Companion to PRIOR-ART-AUTOPSY.md.
The three pieces: G = compositional generator · S = deterministic simulation
of real stateful systems · A = LLM drafts atoms/invariants, human ratifies.

## Why nobody has built-and-succeeded (ranked)
1. Everyone with G+S became a CONSULTANCY not a product, because the model was
   expensive expert labor. Direct evidence: Quviq (QuickCheck+PULSE, 2009,
   generation+schedule control) = ~20yr boutique; Jepsen (generator+nemesis+
   Elle oracle) = deliberately one person. Both chose consulting for the same
   reason. The LLM (A) is the first thing to attack this — the timing gate.
2. The deterministic simulator is the scarcest, most capital/expertise-heavy
   ingredient: FDB built the simulator ~18mo BEFORE the DB; TigerBeetle
   designed for it day one; Antithesis raised $47M SEED Feb2024 + ~$30M 2025 + $105M Series A (Jane Street) Dec2025 = ~$182M total on a
   determinism hypervisor. Teams who can build G usually can't build S.
3. Three non-overlapping cultures (systems-sim · formal-methods · ML-agents);
   no public team spans all three, and the systems camp is actively skeptical
   of GENERATED oracles (Jepsen ethos = expert writes the oracle).
4. Model checkers (TLA+) never crossed the model↔impl gap; property testers
   (Hypothesis) never crossed single-process→distributed-with-faults.

## Near-misses (had / lacked)
- Quviq QuickCheck+PULSE: G + partial-S(BEAM scheduler only), no A → consulting.
- FoundationDB: S(archetype), no G(hand-written Flow workloads), no A.
- Antithesis: S(best) + search≈partial-G + PARTIAL-A (their AI generates
  WORKLOAD/calling-code, but NOT invariants/oracles). Closest competitor,
  ~$182M raised. CRUCIAL: they have publicly bet AGAINST our piece A — their
  2025 manifesto "AI testing done right" argues FOR human-authored correctness
  properties and AGAINST LLM-generated tests. Humans define WHAT correct means,
  their AI explores WHETHER it holds. So not a quiet fast-follower — a
  philosophical opposite. If our LLM-drafts-the-oracle thesis is right, they
  are publicly wrong; if they're right, that's our risky leg.
- Coyote/P (MSFT): G(state machines)+controlled scheduling, but tests YOUR
  .NET code not real external systems; authoring-tax → niche.
- TLA+/stateright: purest G, zero S (no real execution), model↔impl gap.
- Jepsen: G(bespoke)+partial-S(real, NON-deterministic)+oracle, no A, consulting.
  Our direct incumbent for OSS-maintainer mindshare (the fleet motion).
- Meta TestGen-LLM: rigorous A, no S, no distributed G — validates the
  "LLM drafts, machine filters, human ratifies" pattern works.

## Verdict: in-between, leaning genuine-new-window
Timing gate real (G+S possible for a decade, throttled by model-authoring
cost, LLM removes it). Window narrow + "LLM+testing" already rushed — but on
UI/unit tests, NOT stateful-systems+simulation. Defensibility is NOT the LLM
(commoditizing) and NOT the generator (formal-methods people can build one) —
it is deterministic simulation of real stateful systems.

## The S question — CHECKED, we have it (the report's scariest flag, refuted)
Report warned we might have "real VMs + fault injection" mislabeled as
simulation (Jepsen-class, non-deterministic). Our own hypervisor docs refute
this: same-seed determinism is an audited "non-negotiable product promise"
(docs/hypervisor/determinism-review.html, findings G1–G7 cited to files) with
a same-seed DIVERGENCE REGISTRY (non-determinism.html, ND-1–ND-4 closed) —
FDB-grade discipline. Plus seed-based interleaving + instr-preemption +
virtual time for concurrency search. The deterministic/fast toggle was just
REMOVED (commit e423fb5) — determinism became default, not optional. So the
one leg the report flagged as weakest-verified is the audited core of what we
shipped. We own the exact moat the report says decides the category.

## What should scare us
1. Antithesis is BETTER CAPITALIZED than assumed (~$182M, Jane Street/Amplify/
   Spark; customers Jane Street, Ethereum, MongoDB, TigerBeetle, etcd). BUT
   they've publicly committed AGAINST LLM-drafted oracles — so the risk is not
   "they bolt on A overnight" but "the whole category leader says our
   differentiator is a mistake," which shapes how buyers hear us. Our counter:
   we also own audited S + fleet credibility + compositional G/coverage-debt (a
   different bet than their coverage-fuzzing); and the strong external proofs of
   our pattern are OSS-Fuzz-gen (LLM drafts driver → real CVEs incl 20yr
   OpenSSL) and Meta ACH (LLM drafts tests, 73% human-accept).
2b. THE unsolved problem in our differentiator, flagged across all C-research
   (Vikram arXiv:2307.04346 onward): LLM-drafted invariants are frequently
   TRIVIAL or FALSE. Whoever first makes LLM-drafted *strong* stateful
   invariants + real DST work owns unclaimed ground. That is exactly our wedge
   AND our biggest technical risk — it maps 1:1 to M2 + the two-tier universal
   oracle. Antithesis avoids it by making humans write oracles; we must solve
   it. This is the crux the whole bet rests on.
2. Oracle-trust: a wrong LLM-drafted invariant = confident-false-green. This
   IS our M2 metric + the two-tier universal-oracle safety net. If ratification
   is expensive we've reinvented Quviq — so M1 (onboarding cost) + M2
   (invariant trust) are the right survival metrics, independently confirmed.

## Verified evidence (3rd deep-dive) + two honest counters
STRONGEST VERIFIED SUPPORT:
- MBT abandonment is real, named by practitioners (Empirical Softw. Eng. 2022,
  PMC9149667): "too much maintenance. It was difficult to keep up with
  development." The model-drift/rot problem, quoted. Best-sourced proof the
  model-authoring cost was THE killer.
- The systems community's OWN leaders say hand-authored fault testing doesn't
  scale: Alvaro & Tymon, "Abstracting the Geniuses Away from Failure Testing"
  (ACM Queue 2018) — "all bugs discovered by Jepsen to date were discovered by
  its inventor, Kyle Kingsbury"; Alvaro SoCC'16 — "Programmer-guided approaches
  to failure testing are only as good as human intuition and only scale with
  human effort." The incumbents NAME the scaling ceiling we target. (But their
  own pre-LLM automation, LDFI/Gremlin, stayed niche — LLM is the new variable.)
- Our pattern works for shallow oracles TODAY: OSS-Fuzz-gen (26 real bugs incl.
  20yr OpenSSL CVE-2024-9143), Meta ACH (73% human-accept). And LLM tests CAN
  out-detect humans WITH context: arXiv:2606.08588 — 69% vs 17.2% fault
  detection (coverage near-identical → coverage is not the metric).

TWO COUNTERS TO FLAG HONESTLY (do not bury in a pitch):
1. The "LLM gate revives MBT" narrative is INFERENTIAL — no crisp pre-LLM
   prophecy of the form "cheap model authoring would revive MBT" exists. The
   honest framing: the whole cost-reduction research thread is a standing bet
   that cheap models = adoption, not a named prediction. Don't overclaim.
2. THE #1 TECHNICAL RISK — oracle independence (structural, not fixable by
   scale): an LLM that both MODELS the system and JUDGES it shares the
   implementation's blind spots; "a more capable model writes more
   sophisticated tests that still share its own blind spots." Critics (Seemann,
   ploeh 2026: "AI-generated tests as ceremony… lull you into false security")
   WILL raise this. Our mitigation is real and is exactly what they say is
   missing: model authors the adversarial WORKLOAD and the promise-derived
   ORACLE separately, red-proof is unwaivable, REWARD RED, two-tier universal
   oracle needs zero declarations. But we counter with design + 2606.08588, we
   never deny the critique. This risk = M2, and it is the crux the bet rests on.

## One-line bottom line
The triad is genuinely unbuilt; the LLM gate is a real new window; our
defensibility is audited deterministic simulation (owned) + solving
LLM-drafted STRONG stateful oracles (unclaimed, and our single biggest technical
risk). Antithesis owns S and bet publicly AGAINST our A. Win on oracle-trust
(M1/M2) or the category leader's thesis wins.
