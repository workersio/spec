# Workload harness v3 — documentation structure (target spec)

Status: ALIGNED 2026-07-16 · refactor executed and published; the §5 cross-check
passed (3 iterations). This file remains the set's map. 🏛 Product Book URL:
https://claude.ai/code/artifact/5f152ab6-7e22-4a5e-9dbf-d56f89b40ee9

Principle: **one fact, one home**. Normative rules live as **contract blocks**
inline in the doc they impact (`<div class="contract" id="c-…" data-dec="pending">`,
chip "CONTRACT · awaiting DEC"). A contract block wins over any prose anywhere.
The interception-ledger (wiki) is the statute book (append-only DEC events);
the docs are the codified current law; 📜 is only the queue + the index of blocks.

## 1 · Target set (6 docs + 🔬 added same day → 7 rows incl. index)

| Doc | URL | File | Role | Change cadence |
|---|---|---|---|---|
| 🧭 Index | 79db9361 (in place) | design-index.html | front door: reading order, set laws, change rules | structural only |
| 📜 Decisions | f5abbeac (in place) | contract-and-decisions.html | pending-card queue + contract-block traceability | on DECs |
| ⚗️ Rationale | 3aa3de51 (in place) | compositional-scenarios.html | the why: stable essay, onboarding + belief | on new arguments |
| 📖 Spec | 5f600e91 (in place) | language-reference.html | reference manual: language, SDK, schemas, search & measurement contracts, CLI | on build learnings |
| 🏛 Product Book | NEW URL | product-book.html | the machine + the experience (merged 🧩+🧱+🧠) | on UX/packaging change |
| 🛠️ Plan | 8636168f (in place) | path-and-build.html | two goals, no dates: Goal 1 baseline (assemble + run once) · Goal 2 experiment harness (J1–J6 + E1–E4); later deliberately unplanned | stale by design |
| 🔬 Search surfaces | 089f4233 (added 2026-07-16) | search-surfaces.html | six experiment surfaces × eval suites in the codebase; the lab decomposed | on surface/instrument changes |

Stubs (kept URLs, pointer-only): 🧩 ab7a9551 → "merged into 🏛" · 🧱 884a9e4d →
"merged into 🏛" · 🧠 fb5d9a9b → tombstone "folded into 🏛 + 📜, per charter".

## 2 · Content mapping (source § → destination)

### 📜 contract-and-decisions.html — SHRINKS to Decisions page
| Current content | Destination |
|---|---|
| F1 compatibility boundary | 🏛 Part II contract block c-migration (merged with item 10) |
| F2 agent-drafts-user-ratifies (+ NEW mode split) | 🏛 Part I contract block c-review-gates |
| F3 gate on publication | 🏛 Part II contract block c-lifecycle |
| Item 01 atom schema | 📖 §3 contract block c-atom-schema |
| Item 02 oracle families/tiers/debt | 📖 §5 contract block c-oracles |
| Item 03 operator set/nesting/closure | 📖 §1 contract block c-operators |
| Item 04 applicability | 📖 new §6c contract block c-applicability |
| Item 05 breadth floors | 📖 new §6c contract block c-floors (stays flagged) |
| Item 06 budget/stop | 📖 new §6c contract block c-budget-stop (stays flagged) |
| Item 07 load & environment safety | 📖 new §6c contract block c-load-env |
| Item 08 review gates (+ non-blocking holds) | 🏛 Part I contract block c-review-gates |
| Item 09 storage/versioning/wire freeze | 📖 new §12 contract block c-formats |
| Item 10 migration boundary | 🏛 Part II contract block c-migration |
| Item 11 prototype bar | 🛠️ contract block c-prototype-bar (already the phase-1 gate; stays flagged) |
| Item 12 split + openness amendment | 🏛 Part I contract block c-openness (stays flagged) |
| Item 13 product companions | 🏛 Part II contract block c-pages |
| Canonical terms table | 📖 new §0 vocabulary |
| Cell states · 12 ledgers · exhaustion | 📖 §6c (block c-budget-stop carries exhaustion) |
| Misuse negation library | 📖 §6b (merged into state grammar, block c-misuse) |
| Explain endpoint + rails | 🏛 Part I (block c-openness carries rails); response shape in 📖 §12 |
| Evaluation law | 📖 new §13 measurement contract, block c-evaluation |
| Turso census amendments | 📖: event vocab → §2 interrupt note; severity precedence → §13; oracle axis → §5 area |
| What ratification triggers | 📜 keeps (part of queue page) |
| REMAINS in 📜 | pending cards (owed: 05, 06, 11, 12-packaging, F2-mode · parked: Q1–Q5 with triggers), traceability table, ratification instructions, statutes/code note |

### 🧩 the-system.html — RETIRES into 🏛 Part I
| Current content | Destination |
|---|---|
| §1 one picture | 🏛 Part I §1 |
| §2 pieces 1–7 | 🏛 Part I §2 (piece 5 expanded with 🧠 content) |
| §3 four frozen formats table | 📖 §12 (schemas belong in Spec); 🏛 keeps one-line pointer |
| §4 one run end-to-end | 🏛 Part I §4 |
| §5 update train + never-ships callout | 🏛 Part I §5 |

### 🧱 stable-repo-evolving-skill.html — SPLITS: argument → ⚗️, experience → 🏛 Part II
| Current content | Destination |
|---|---|
| §1 background (two things/two places, churn history) | ⚗️ new §9 (compressed intro) |
| §2 four principles | ⚗️ new §9 |
| §3 three zones, change-kinds table, ledger/balance, migration drafting, rehearsal | 🏛 Part II §6 |
| §4 search-vs-replay, draft→official, partial-run board | 🏛 Part II §7 |
| §5 seven pages, two worlds, pyramid | 🏛 Part II §8 |
| §6 three layers, who-writes-nobody, five pieces/never ships | 🏛 Part II §9 |
| §7 quiz (6 questions) | 🏛 Part II §10 |

### 🧠 skill-structure-whiteboard.html — FOLDS and tombstones
| Current content | Destination |
|---|---|
| §1 design law | 🏛 Part I §3 |
| §2 package layout | 🏛 Part I §3 |
| §3 four episodes | 🏛 Part I §3 |
| §4 choreography (+ NEW: both ratification modes) | 🏛 Part I §3 |
| §5 subagent roster | 🏛 Part I §3 |
| §6 worked wake | 🏛 Part I §3 |
| §7 Q1–Q5 | 📜 parked cards with triggers + provisional defaults |

### ⚗️ compositional-scenarios.html — GAINS §9–§10, quiz renumbers to §11
New §9 "Why the repo stays stable while the skill churns" (from 🧱 §1–2).
New §10 "The openness posture" (verifier/generator asymmetry, extraction ceiling,
no-valid-ratifier argument for fleet lanes / maintainer as ground truth).
All 🧱/🧩 hrefs → 🏛.

### 📖 language-reference.html — GAINS §0, §6c, §12, §13; contract blocks
§0 vocabulary (terms table) · §6c the search contract (applicability, floors,
budget/stop + exhaustion, load-env) · §12 wire formats (4 formats + explain
response, freeze rules) · §13 measurement contract (evaluation law, severity
weights w4..w0, Turso precedence) · CLI verb table (client-local vs service)
appended to §12. Blocks: c-operators (§1), c-atom-schema (§3), c-oracles (§5),
c-misuse (§6b), c-applicability/c-floors/c-budget-stop/c-load-env (§6c),
c-formats (§12), c-evaluation (§13).

### 🛠️ path-and-build.html — status strip → one-line pointer; block c-prototype-bar
"Where we are now" callout replaced by pointer to 📜 queue + ROADMAP.
Phase-0 text updated (DEC = the 📜 queue). c-prototype-bar block wraps the
item-11 gate. Cross-links 🧩/🧱 → 🏛.

### 🧭 design-index.html — new card set + set laws
Cards: ⚗️ → 🏛 → 📖 → 📜 → 🛠️ (reading order). Status strip removed; 📜 card
carries "the queue". Rules block gains: one-fact-one-home, contract blocks win,
ownership-by-change-type, staleness contract, brainstorm=queue, change rules
(auto-apply vs DEC).

## 3 · Contract block inventory (📜 traceability must list exactly these)

| id | home | carries |
|---|---|---|
| c-operators | 📖 §1 | catalog closed at 12, depth ≤3, extension rule |
| c-atom-schema | 📖 §3 | code-native atoms, decorator surface, no sidecar |
| c-oracles | 📖 §5 | two tiers, universal plane, oracle debt |
| c-misuse | 📖 §6b | engine-owned library, six negations, states never authored |
| c-applicability | 📖 §6c | inferred+cited, unknown default, parks face refutation |
| c-floors | 📖 §6c | mandatory breadth floors (FLAGGED 05) |
| c-budget-stop | 📖 §6c | 60/25/15, stop semantics, exhaustion criteria (FLAGGED 06) |
| c-load-env | 📖 §6c | ladder, gates, rails |
| c-formats | 📖 §12 | 4+1 wire formats, additive-only, versioned |
| c-evaluation | 📖 §13 | one treatment/measurement, freeze, blessed instruments, severity+precedence |
| c-review-gates | 🏛 I | item 08 two gates + F2 mode split + non-blocking holds (FLAGGED F2-mode) |
| c-openness | 🏛 I | language public/search private + explain rails (FLAGGED 12) |
| c-lifecycle | 🏛 II | F3: gate publication never execution |
| c-migration | 🏛 II | F1 + item 10: boundary, wio migrate tiers, launch gates |
| ~~c-pages~~ | — | REMOVED 2026-07-16: read-pages design parked (📜 PAGES card); lifecycle/scoping semantics survive in c-lifecycle |
| c-prototype-bar | 🛠️ | item 11 five criteria (FLAGGED 11) |
| c-search-surfaces | 🔬 | lab-decompose: blessed evals, held-out law, blind-draft, rows retire on coverage (FLAGGED LAB) |

## 4 · Link map
All internal hrefs use artifact URLs. After refactor: zero references to
ab7a9551 (🧩) / 884a9e4d (🧱) / fb5d9a9b (🧠) outside stub files + 📜 history
note. 🏛 URL is minted at publish; placeholder `PRODUCT_BOOK_URL` in sources
until then, then swept.

## 5 · Cross-check list (run until clean)
1. Coverage: every mapping row in §2 has its content present at destination (grep anchor phrases).
2. One-home: normative statements appear in exactly one NORMATIVE doc (📖 🏛 🛠️ 📜). ⚗️ is
   expository-exempt — it may narrate contract content but must carry a pointer to the
   binding block where it does. Match on exact normative phrasings (e.g.
   "documented-surface census floor", "zero invalid emissions /100"), not loose substrings;
   📜 cards cite, don't restate (≤1 line shorthand).
3. Blocks: all 16 ids in §3 exist, each with data-dec attr; 📜 traceability lists all 16, no extras.
4. Links: no 🧩/🧱/🧠 URLs outside stubs/📜-history; no PRODUCT_BOOK_URL placeholder after publish sweep; all hrefs in set resolve to the 6 live URLs + stubs.
5. HTML sanity: no <html>/<head>/<body> wrappers in sources; every doc has <title>; theme tokens define :root, dark media query, and both data-theme overrides; quizzes' JS intact where moved.
6. Retired files: the-system/stable-repo/whiteboard sources replaced by stub content; END-STATE.md marked retired in DESIGN-TRUTH.md (absorption = 📜/📖/🏛 refactor).

## 6 · Post-alignment amendments (2026-07-16, same day)
- 🔬 added; c-search-surfaces block (LAB-decompose). c-pages REMOVED (pages parked).
- Plan de-phased to two goals, no dates; P1–P8 removed (later, unplanned); E1–E4 added.
- 🏛 §5 update-train REPLACED by the end-state repo layout (formal monorepo: Rust
  wio (substrate) + interception/ umbrella: composition (spec public, source private) · generation (never distributed) · sdk · evals, per-language SDKs, evals/,
  environment, convex, apps/web; skills-git = plugin + design only).
- Queue: six owed (05 06 11 12 F2-mode LAB) · six parked (Q1–Q5 + PAGES). 16 blocks.
