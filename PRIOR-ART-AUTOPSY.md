# Prior-art failure autopsy: autonomous testing of stateful systems
(Research agent report, 2026-07-15 — six parallel web-research passes; UNVERIFIED marks preserved.
Companion to WORKLOAD-HARNESS-COMPOSITIONAL-END-STATE.md and -DECISIONS.md.)

**TL;DR:** Everything in this family has been tried, and each piece works *technically*. What killed or capped every predecessor was one of five things: (1) the cost/skill of authoring the model or properties, (2) the oracle problem, (3) model–code drift, (4) the non-retrofittability of determinism, (5) a market that pays for found bugs and expertise, not for test-generation frameworks. The flow-atoms approach genuinely attacks (1) and (3), partially attacks (2), and does nothing structural about (4) and (5) — those two are where the real risk lives.

## 1. Model-based testing (MBT) — closest analog, deepest graveyard
- **Microsoft Spec Explorer** (~2002–2012): model programs → FSM exploration → test generation. One giant success: the antitrust-driven Windows protocol documentation compliance program (Grieskamp et al., STVR 2011) — worked, but needed a captive, court-ordered, ~hundreds-of-engineer-years program with specialist modelers. Shipped as a VS power tool, last updated ~VS 2012, quietly abandoned (exact final supported version UNVERIFIED).
- **Conformiq**: ~20 years as a small telecom/enterprise vendor; ended in acquisition rather than scale (acquirer UNVERIFIED).
- **Smartesting**: the most instructive — pivoted AWAY from model authoring: CertifyIt → Yest → Gravity (infers models from production traces). A 20-year MBT vendor concluding "nobody will write the model, so mine it from usage" is the market's verdict.
- **GraphWalker**: alive, hobby-scale.
- **Tricentis Tosca**: the one commercial "MBT" success — and its "model" is a UI object model, NOT a behavioral spec. Succeeded by removing exactly the semantic part.
- **Why (sourced):** ACM Queue 2015 "Model-Based Testing: Where Does It Stand?" (2014 user survey: top inhibitors = modeling skill + effort); Utting & Legeard 2007 (ROI gated on authoring cost); Dias Neto 2007 systematic review (hundreds of techniques, near-zero transfer).
- **What atoms do differently:** small, independently-trusted, *executable*, AI-draftable units; typed code so drift breaks builds. Honest caveat: the improvement comes from the LLM, not the algebra — invariants/checkpoints are still the part MBT users couldn't write.

## 2. Combinatorial testing / covering arrays
NIST ACTS (Kuhn & Kacker; IPOG; Kuhn/Wallace/Gallo TSE 2004: most field failures = ≤2–6 factor interactions), Microsoft PICT, Hexawise (stayed tiny; disposition UNVERIFIED). Sequence covering arrays existed (~2012) and still didn't spread (adoption UNVERIFIED). Permanently niche (aerospace/defense/medical; Lockheed ~20% test-cost reduction per NIST case study).
- **Why:** Bach & Schroeder, "Pairwise Testing: A Best Practice That Isn't" (PNSQC 2004) — combination coverage is meaningless without an ORACLE; parameters/constraints modeling is manual; says nothing about state/sequence bugs. CT solved test selection while the binding constraint was test meaning.
- **Lesson:** our lattice+debt is CT over behaviors — fine, but the oracle story (invariants in atoms) is the load-bearing part; enumeration is the easy 20%.

## 3. Stateful property-based testing — Quviq (the sharpest warning)
Quviq AB (Hughes & Arts, 2006): eqc_statem state-machine models + PULSE. Triumphs: Ericsson Media Proxy races; Volvo/AUTOSAR 200+ defects (ICST 2015); LevelDB race with a 17-op minimal counterexample ("Testing the Hard Stuff and Staying Sane").
- **Outcome:** technically triumphant, commercially a boutique that never grew (founder-plus-a-handful for two decades; registry figures UNVERIFIED); revenue = consulting/training.
- **Why (Hughes's own diagnosis):** customers can't/won't write properties and state models; every engagement collapsed into experts writing the model = services. Ecosystem corroboration: plain PBT went mainstream (Hypothesis in numpy/pandas), stateful PBT stayed rare (RuleBasedStateMachine underused per its own author; quickcheck-state-machine low-maintenance; proptest-state-machine 2023, few users). **Adoption dies exactly where the user must supply a model.**
- Quviq had our exact technical artifact with world-class results and could only sell consulting. What's different in 2026: (i) LLMs drafting atoms, (ii) selling found-bugs not tools. Neither proven yet.

## 4. Deterministic simulation testing — the branch that works
- **FoundationDB**: simulator built BEFORE the database (Flow; Strange Loop 2014; SIGMOD'21). Kingsbury declined to Jepsen it (paraphrase UNVERIFIED).
- **Antithesis** (FDB alumni, $47M, launched Feb 2024): deterministic HYPERVISOR — determinism imposed below arbitrary software + coverage-guided exploration + perfect repro. Customers: MongoDB, Palantir, Ethereum Foundation, Ramp, WarpStream. Enterprise/compute pricing, expensive. **Per their own docs: customers still write the workloads and assertions.** (Post-2024 funding UNVERIFIED.)
- **TigerBeetle VOPR**: FDB-style, possible because designed deterministic from day one. **madsim/turmoil/shuttle/loom**: require SUT written against their runtime; a few dozen sophisticated teams.
- **Why this branch works:** determinism is NOT retrofittable at the library level — succeeded only co-designed from birth, or capitalized past the problem with a hypervisor.
- **Our exposure:** the algebra does nothing here; our answer is niche selection (stateful infra is the most sim-amenable class) + the wio sim/bench. Also: our semantic layer is complementary to Antithesis — "we productize the layer Antithesis makes customers hand-write" — which also makes them a plausible fast-follower with a distribution head start.

## 5. Jepsen — the natural experiment
Ops=atoms, generators=operator algebra, nemesis=fault injection, checkers=invariants (Knossos, Elle — VLDB 2020). Massively influential, deliberately microscopic: one person, 3–6 analyses/year for a decade, 4–12 week engagements, flat weekly rate, NO public price (the $100–200k figure is NOT publicly confirmed). Framework + checkers productized (vendors self-run: CockroachDB nightly 2+ years, Scylla, ArcadeDB); **workload design + fault-model selection + interpretation never detached from the expert.**
- **The cleanest evidence against the easy version of our thesis:** the atoms-and-operators machinery was free for a decade, and without the expert the semantic layer still didn't get built well. Our counter-bet: 2024-class AI agents supply the judgment. That is the whole company, stated plainly.

## 6. AI-agent test generation, 2023–2026
Funded cohort ≈ all browser E2E (QA Wolf — explicitly services-heavy hybrid, Momentic, Octomind, Checksum, Meticulous) or unit-test gen (Meta TestGen-LLM: only ~¼ of generated tests kept; Diffblue niche after $50M+). Early pivots visible (CamelQA — UNVERIFIED). **Nobody targets durability/correctness invariants in stateful backends.** The autonomous bug-finding that works is security-shaped — Google Big Sleep (real SQLite bug), OSS-Fuzz AI fuzz targets (OpenSSL CVE-2024-9143), XBOW (~$75M, topped a HackerOne leaderboard) — because **crashes/exploits are free oracles. Semantic correctness has no free oracle.**
- Standing critique: LLM tests skew to change-detectors that enshrine bugs (green noise). Atoms + reward-RED is the right structural response; whether AI-drafted invariants are correct oracles (not merely plausible) is unproven, and false positives burn the maintainer-trust channel the GTM depends on.

# Synthesis — ranked recurring failure causes, with our scorecard
1. **Model-authoring cost & skill scarcity** (the #1 killer) — *partially neutralized* (atoms smaller/executable/AI-draftable; the improvement comes from the LLM, not the algebra).
2. **The oracle problem** — *partially neutralized at best* (invariants distributed into atoms; durability invariants are conveniently generic for our wedge; AI-authored invariant quality is the ceiling).
3. **Model–code drift** — *largely neutralized* (code-native typed atoms turn drift into build failures; semantic drift survives).
4. **Determinism is not retrofittable** — *not addressed by the algebra*; answered only by niche selection + our own sim/bench investment. Be precise internally about which targets are sim-viable; predecessors vague on this died on it.
5. **Market pays for bugs and expertise, not frameworks** — *not addressed structurally*. Every predecessor converged to services, a solo consultancy, a niche tool, or high-touch enterprise deals to a small buyer pool. Our GTM is Jepsen's playbook; it terminates in a consultancy unless per-target onboarding cost genuinely goes to ~zero.

**Bottom line:** nothing in this family failed because the idea was wrong; failures were economic. The two live existential questions: (1) can an AI agent produce *trustworthy* atoms/invariants without an expert in the loop (Jepsen's natural experiment says this is the hard part); (2) can we survive Antithesis building the semantic layer on top of the determinism layer they already own.

---
# Verification pass (deep-dive MBT researcher, same date) — corrections & strengthened facts

**CORRECTIONS to the synthesis above:**
- **Spec Explorer died earlier than stated:** last release v3.5, July 2013; official support never went past VS2012 (the VS2013–2019 "compatibility" on Wikipedia is a hobbyist's binding-redirect fork). Deprecation confirmed on learn.microsoft.com.
- **Conformiq was NOT acquired** (the earlier "ended in acquisition, UNVERIFIED" is wrong; likely confusion with Eggplant→Keysight 2020). Reality is worse for the category: still independent after 27 years, $12.9M total funding with a Series A in year 17, revenue est. $100K–5M, 25–100 employees, homepage rebranded to "AI-powered scriptless test design" with MBT vocabulary scrubbed.

**Strengthened facts (all source-verified):**
- Microsoft's flagship MBT success (protocol-docs program, court-ordered): ~250 person-years spent; MBT saved ~50 person-years = **~40% productivity gain — the ceiling of the payoff was 1.4×, not 10×** (MSDN Dec 2013, verified quote).
- **#1 abandonment cause, refined** (EMSE 2022 practitioner study): "loss of the skilled champion" — *"It is often because the people with competence disappear"*; maintenance-cost creep second. Skill scarcity in organizational form.
- **Adoption datum:** the flagship 2016/17 community-wide MBT user survey drew **61 respondents worldwide**; the community's survey sites are now offline.
- Smartesting's pivot chain extended: CertifyIt (UML/OCL) → Yest (visual) → Gravity (mine models from prod traces) → **Lynqa (LLM agents)** — CertifyIt gone from the homepage. Each pivot moved away from user-authored models.
- **Tricentis Tosca = the unicorn that proves the point:** its "model" is a UI-object scan, no behavioral state machine, no sequence generation — kept the maintenance benefit, dropped model authoring, built a unicorn.
- **The survival pattern:** MBT survives only where (i) the model already pre-exists as a first-class artifact (Reactis/Simulink — alive and healthy, V2024 shipped), (ii) a regulator forces the spend, or (iii) the "model" is degraded to what QA already understands. Everywhere else the model is a second implementation maintained by rare dual-skilled people, and it dies when they leave.
