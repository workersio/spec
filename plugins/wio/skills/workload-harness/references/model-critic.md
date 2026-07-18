# Model critic

The model critic is a read-only, deterministic review boundary. It reads the
complete atom source tree, the workload-harness model laws, and BUILD's exact
`## 7. Hard-won gotchas (each already cost us once)` section. It does not edit
the model, materialize cells, run a workload, access credentials, or discover
inputs from a repository or the environment.

Run it from an explicit checkout with paths appropriate to that checkout:

```bash
python3 <this-skill>/scripts/model_critic.py review \
  --atoms <repo>/.workers/model/atoms \
  --skill-law <this-skill>/SKILL.md \
  --skill-law <this-skill>/references/model-authoring.md \
  --gotchas <formal>/interception/BUILD.md \
  --out <repo>/.workers/model/critic.json
```

`review` emits format `wio-model-critic`, version 1. The artifact contains a
SHA-256 stamp of all regular Python and TypeScript atom sources, each skill law
in command order, and the frozen BUILD gotchas section. Its verdict is either
`findings` or `clean`; findings are sorted and carry a stable rule ID, relative
path, one-based line, governing law, and detail.

Inspect every finding, change the cited model source, and rerun `review`. There
is no waiver, ignore, baseline, severity threshold, or force option. A findings
report is useful review history, but it cannot authorize ratification. Only the
current clean `.workers/model/critic.json` belongs in the proposed model
checkpoint.

The MODEL gate verifies the committed artifact against the same explicit
inputs:

```bash
python3 <this-skill>/scripts/model_critic.py verify \
  --atoms <repo>/.workers/model/atoms \
  --skill-law <this-skill>/SKILL.md \
  --skill-law <this-skill>/references/model-authoring.md \
  --gotchas <formal>/interception/BUILD.md \
  --report <repo>/.workers/model/critic.json \
  --require-clean
```

This verification must succeed before `RATIFICATION REQUIRED` is emitted.
Missing, malformed, stale, or findings-bearing reports stop the gate. Once it
succeeds, present the cited model diff and public digest for human ratification;
cell materialization and execution remain later steps.
