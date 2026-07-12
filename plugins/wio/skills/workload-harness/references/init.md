# Init — deterministic scaffold (.workers/ v2)

`/goal init the workload harness` scaffolds a fresh corpus. Init is
mechanical: no judgment, no model authoring (that is the first producer
episode). Idempotent — re-running over an existing tree only fills gaps,
never overwrites.

1. **Copy the library**: this skill's `lib/*.py` + `lib/CONTRACT.md` +
   `lib/README.md` → `.workers/lib/` (copies, not symlinks — the guest sees
   only the repo; behavior is version-pinned with the corpus). Copy
   `lib/check.py` → `.workers/check.py` and `chmod +x` it.
2. **Copy recipes**: `references/recipes/` → `.workers/recipes/` (plus any
   the target needs at its root, e.g. a postgres wrapper the `runner:`
   prefix names).
3. **Create the tree**: `scenarios/`, `flows/`, `findings/` (empty dirs with
   `.gitkeep`);
   - `usage-model.md` — frontmatter skeleton (`target:`, `runner:`,
     `actor-model:`, empty `personas:/flows:/events:/modules:`) + a body
     note: "first producer episode fills this";
   - `candidates.md` — the `<!-- emit:begin/end -->` markers +
     `threshold: 40` + an empty table;
   - `journal.md` — `## config` (rails: `max-loops: 100`, `max-runs: 250`,
     `staleness-k: 5`, `api-floor-share: 0.3` (binding, G-status),
     `event-min-amp: 10`) + `## log` with one init line.
4. **build.sh**: if the repo has no `.workers/build.sh`, create the stub
   that exits 0; a real SUT vendor/venv build is target work (the dbos
   corpus's build.sh is the reference shape).
5. **Verify**: `python3 .workers/lib/test_frontmatter.py` and every other
   `test_*.py` pass in place; then `.workers/check.py` exits **0 on the
   empty tree** (no scenarios yet = nothing to violate; the empty-but-valid
   model file must parse). `check.py --status` should print row 6 (producer:
   nothing exists → but with an unfilled model it prints row 4 —
   model-refresh — which is correct: the first episode is model work).
6. **Commit**: one commit, message `workers v2 scaffold (usage-first)`.
   Nothing publishes; there is nothing to publish.
