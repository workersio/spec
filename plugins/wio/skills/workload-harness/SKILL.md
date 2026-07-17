---
name: workload-harness
description: Author and ratify code-native WIO workload models from a repository, then drive the deterministic local harness through evidence and explanation. Use when modeling product operations, assigning creates/consumes/plain input roles, or running the pre-metal interception loop.
---

# WIO Workload Harness

Author the product model. Let the installed SDK and CLI compute everything
mechanical.

## Start safely

1. Work in the target repository. Do not read or use evaluation keys,
   production credentials, production endpoints, or unpublished expected
   findings.
2. Verify the installed language SDK extractor and `wio harness --help` run in
   the target environment. If either is unavailable, stop and install the
   product prerequisite; do not copy or recreate its logic inside the target.
3. Run `python3 scripts/scaffold.py --repo <repo> --language python|typescript`
   from this skill directory. Existing identical scaffolds are preserved;
   conflicts stop without overwriting.
4. Read [references/model-authoring.md](references/model-authoring.md), then
   the reference for the selected language:
   [references/python-sdk.md](references/python-sdk.md) or
   [references/typescript-sdk.md](references/typescript-sdk.md).
5. Inspect public documentation, exports, implementation, tests, examples, and
   executable controls. Treat each as evidence, not as an automatic atom list.

`.workers/model/` is the human-ratified source of truth. `.workers/generated/`
is replaceable output, `.workers/evidence/` is immutable run evidence, and
`.workers/.local/` is ignored machine state.

## Author the model

1. Identify externally meaningful operations and the invariant each promises.
   Prefer a small falsifiable operation over a broad story.
2. Put a `wio-source:` comment immediately above every declaration, naming the
   repository path and section, symbol, or line that supports it.
3. Declare nonempty invariants and modalities. Declare executable resources,
   values, checkpoints, and semantics only when the repository supports them.
4. Assign every input an explicit operation-local role:

   - `CREATES`: this operation makes the supplied identity live. Absence before
     entry is normal. Only `malformed` and `reused` are applicable.
   - `CONSUMES`: the identity must already be live on entry. Declare only the
     documented subset of `foreign`, `malformed`, `nonexistent`, `reused`,
     `stale`, and `wrong-lifecycle-state`; the checker reports each omitted
     engine negation as named debt.
   - `PLAIN`: the input is not a lifecycle reference and has no misuse errors.

   Classify the operation's use of the input, never the value type by itself.
   Put expected errors on the annotated atom input, never globally on `Value`.
   If one proposed atom creates and later consumes the same identity, split it
   into separately observable operations.
5. Use real public error type names. Do not invent a mapping merely to satisfy
   the checker; omitted consumer mappings remain named debt until a public
   contract supports them.

## Validate and ratify

1. Extract format-1 JSON with the installed language SDK into
   `.workers/generated/manifest.json`.
2. Run the checker by its installed skill path:
   `python3 <this-skill>/scripts/check_model.py --manifest
   <repo>/.workers/generated/manifest.json --atoms
   <repo>/.workers/model/atoms`. Fix every failure at the declaration or cited
   source. `<this-skill>` means the directory containing this `SKILL.md`, not a
   `scripts/` directory in the target.
3. Generate the human digest with the public CLI. Show the user the cited model
   diff and digest. Do not execute cells until the user ratifies the model.
4. Commit the ratified model separately from generated output and evidence when
   the user's repository policy permits it. Never push without explicit user
   authorization.

## Drive the public loop

After ratification, follow
[references/local-loop.md](references/local-loop.md). Invoke the public SDK and
CLI for extract, model check, compile, digest, materialize, clean control, run,
verdict, immutable evidence, budget selection, and explanation.

Do not implement ranking, policy, debt, validity, evidence interpretation,
coverage, or stopping in this skill. Do not choose a cell by intuition when the
budget planner is available. Do not rewrite a red into green. A model change
requires another cited diff and ratification; a generated artifact never does.

Stop before any metal substrate unless the user separately authorizes it. A
fully local run must use only loopback services, local credentials, and the
`r1-local`, `r2-process-local`, or `r3-sim-local` substrate.
