# Model authoring contract

## Evidence order

Read the target in this order:

1. public documentation and examples;
2. exported API signatures and documented errors;
3. implementation boundaries and lifecycle transitions;
4. tests that demonstrate observable guarantees;
5. executable controls needed to run those guarantees locally.

Record disagreements instead of silently choosing the easiest source. A test
can reveal behavior but cannot make an internal detail a public promise.

## Atom boundary

An atom is one externally meaningful operation with a falsifiable invariant.
Its key is stable kebab-case. Its resources describe state that must be
provisioned. Its modalities name supported execution forms, not aspirations.

Keep lifecycle boundaries observable. Split a composite operation when an
identity is created in one phase and required to exist in a later phase. This
allows the engine to generate the correct negations without guessing history.

## Input roles

| Role | Entry condition | Applicable expected errors |
|---|---|---|
| `creates` | Supplied identity need not exist; operation makes it live | Any documented subset of `malformed`, `reused` |
| `consumes` | Supplied identity must already be live | Exactly `foreign`, `malformed`, `nonexistent`, `reused`, `stale`, `wrong-lifecycle-state` |
| `plain` | Not a lifecycle reference | None |

The same value class can be `creates` in one atom and `consumes` in another.
Expected errors therefore belong to the atom input annotation, not the value
class. Use the target's public error names as values.

## Citation

Place one citation immediately above each declaration:

```text
# wio-source: docs/api.md#create symbol createThing
```

For TypeScript, use `// wio-source:`. Cite a repository-relative path plus a
specific section, symbol, or line. The deterministic checker verifies presence;
the human ratification verifies truth.

## Ratification

Present the model as a product contract, not generated test inventory. For each
atom show its citation, invariant, modalities, input roles, expected errors,
and any unsupported local control. Ask the user to approve that diff before
materializing or running cells.
