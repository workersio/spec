# Deterministic local loop

Use the installed `wio` and SDK versions as the command authority. Check
`wio harness --help`, `wio evidence --help`, and the SDK extractor help before
running; do not copy their algorithms into the model or skill.

## Ratified inputs

- `.workers/model/atoms/`: cited, human-ratified declarations.
- `.workers/generated/manifest.json`: format-1 SDK extraction.
- local policy and seed: explicit inputs to compilation.
- target commit and local client factory: explicit execution identity.

## Order

1. Extract with the selected SDK using strict lint handling.
2. Run `<this-skill>/scripts/check_model.py`, where `<this-skill>` is the
   directory containing the active `SKILL.md`, not the target repository.
3. Run `wio harness compile`, then `wio harness digest`.
4. Present the model diff and digest for human ratification.
5. Ask the deterministic budget planner for the next owed cell. Do not rank or
   stop in prose.
6. Run `wio harness materialize` for that cell.
7. Execute a clean control and the generated scenario with `wio harness run`.
   Use the declared local package, client factory, flags, and expectation.
8. Convert output with `wio harness verdict`.
9. Build an immutable envelope with `wio evidence envelope`. Append it only to
   the local evidence service, then verify retrieval by digest.
10. Recompute the budget plan from the lattice plus immutable evidence. Repeat
    only while its deterministic stop state says work remains.
11. Query `wio harness explain` through the loopback generation service for a
    citation-grade explanation of selected public state.

Write replaceable artifacts under `.workers/generated/`, canonical envelopes
under `.workers/evidence/`, and service/process state under `.workers/.local/`.
Never modify an evidence envelope after creation.

## Local boundary

Unset cloud and production credential variables. Use loopback URLs and locally
minted project-scoped keys. Allowed substrates before metal are `r1-local`,
`r2-process-local`, and `r3-sim-local`. Stop if a command resolves a non-loopback
service, requests a production credential, or proposes `r4-metal`.

Success is not “the skill chose good tests.” Success is that the same ratified
manifest, policy, seed, target commit, and evidence reproduce the same cells,
artifacts, verdicts, budget state, and explanations through public contracts.
