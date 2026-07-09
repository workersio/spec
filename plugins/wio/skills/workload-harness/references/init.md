# Init — deterministic scaffold

Init is mechanical: same inputs → same tree. No judgment, no LLM authoring of
content beyond filling names the user already gave. Judgment starts with the
first producer episode.

## Preconditions

- A checkout of the target repo (our fork, workers-side overlay, or the user's
  own repo — see the no-push rule in SKILL.md).
- A connected wio project (project ID) whose prepare works, or a named plan to
  get there (`build.sh` authoring is producer/executor work, not init).
  Connecting needs no browser: `projects:createFromGithub` over convex HTTP
  with the saved wio bearer works headlessly.
- For compiled SUTs, prefer the vendored-static-binary pattern over building
  in-image: commit the upstream musl/static release binary under
  `.workers/vendor/bin/`, and `build.sh` just verifies, chmods, and stages
  it. Offline, toolchain-free, proven first-try (S2).

## Steps

1. Create the tree (skip anything that exists — init is idempotent, never
   destructive):

```
.workers/
  map.md
  backlog.md
  areas/
  promises/
  workloads/
  lib/          ← copied from the plugin skill's lib/ (see step 1a)
  recipes/      ← copied from the plugin skill's references/recipes/
  runs/
  loop-state.md
  publish.py
```

`publish.py` is generic (no project-specifics beyond `WIO_PROJECT_ID`): copy
it from the s2-workload fork — it walks `promises/*.md`, publishes every
`status: done` exploration with key/command/depth read from the same
frontmatter entry, and rewrites `published:` ids.

1a. Copy the workload library and service recipes from the plugin into the
   scaffold: the skill's `lib/*.py` (+ `lib/README.md`) → `.workers/lib/`,
   and `references/recipes/` → `.workers/recipes/`. Copies, not symlinks —
   the guest sees only the repo, so the library must be committed with it.
   On an existing corpus, re-copying newer plugin versions over
   `.workers/lib/` is safe (the library is append-only in spirit: workloads
   pin behavior by seed and declared spaces, not by lib internals).

2. `map.md` — the factual index header: target repo, pinned ref, wio project
   ID/branch, an empty areas table, an empty promoted-findings table. If the
   loop uses a locally built wio (a flag not yet released to npm), record the
   binary's absolute path here too — shells in this harness don't source
   `.zshrc`, so PATH tricks are fragile; the map is the one place every
   episode already reads. Carry the DBOS map discipline verbatim: the map is
   a static evidence index, not a queue — no owner/claim/priority/next-action
   columns, ever.

3. `backlog.md` — seed only the empty shape per spec-format §Backlog: the
   summary header (`active: 0`, empty per-area counts, `top-score: 0`,
   `threshold: 20` default) and empty `## Active` / `## Archive` sections.
   No candidates — the first producer episode's scout fan-out fills it.

4. `loop-state.md` — dispatcher state, mechanical:

```markdown
# Loop state
- rails: { loops: 100, workloads: 250 }   # from /goal args or defaults — safety rails, not targets
- counters: { episodes: 0, producer: 0, executor: 0, workloads: 0 }
- no-new-info: { streak: 0, K: 5 }
- in-flight unit: none
- re-entry: none
- last-scanned-sha: <target ref at init>   # diff-directed detection compares this to target HEAD
- target-head-sha: <target ref at init>    # same as last-scanned at init (no unscanned commits yet)
- re-plan triggers: none
- publish-pending: []
- last episode summary: (init)
```

`last-scanned-sha` and `target-head-sha` are both the pinned target ref at init
(recorded in `map.md`); they diverge only when the target ref later advances,
which arms the diff-directed trigger (dispatcher row 4, producer.md
§Diff-directed episodes).

5. Seed nothing else. No placeholder areas, no example promises — empty
   directories are the honest state; the first producer episode fills them
   from the product's own claims (docs, README, API contracts) with
   `provenance` recorded per promise.

6. If migrating an existing corpus (e.g. the DBOS work-items), that is a
   **backfill producer episode**, not init: init scaffolds the empty shape,
   then the producer maps existing specs into
   [spec-format.md](spec-format.md) keys — re-keying is judgment (area
   granularity changes), so it never runs inside init.

## Output

One commit on the working branch: `harness: init .workers/ scaffold`. Report
the tree and the safety rails read from the invocation, then hand control to
the dispatcher.
