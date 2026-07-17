# TypeScript SDK authoring

Use the declaration-only types from `@workers-io/wio-sdk`. The extractor reads
the TypeScript AST and does not execute the target:

Before authoring, verify the package and its extractor command resolve in the
target's pinned package-manager environment. If they do not, install the
product SDK prerequisite; do not copy extractor code into `.workers/`.

```typescript
import {
  Resource,
  Value,
  flow,
  invariant,
  type Creates,
  type Plain,
} from "@workers-io/wio-sdk";

class Records extends Resource {}
class RecordId extends Value {}

const identity = invariant(
  "RECORD_IDENTITY",
  "a record retains its accepted identity"
);

// wio-source: docs/api.md#create symbol create
export const createRecord = flow({
  key: "create-record",
  resources: [Records],
  invariants: [identity],
  modalities: ["sync"],
})(
  (_ctx: unknown, _id: Creates<RecordId, {
    malformed: "MalformedId";
    reused: "AlreadyExists";
  }>, _body: Plain<string>): boolean => true
);
```

Use `Consumes<T, {...}>` with the documented subset of engine misuse keys for
an existing identity; the checker emits named debt for omitted negations. Use
`Plain<T>` for non-reference inputs. Keep expected error maps on the function
parameter type, never on the `Value` subclass.

Run the installed extractor command from the TypeScript SDK package and write
its canonical format-1 JSON to `.workers/generated/manifest.json`. Consult the
installed SDK's package scripts or `--help` for the exact runtime command; do
not duplicate extractor logic in the target repository or this skill.
