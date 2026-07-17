# Python SDK authoring

Import declarations from `wio_sdk`. Annotate every function input with one
role. Put `ExpectedErrors` beside `CREATES` or `CONSUMES`, on that operation's
input:

First verify the SDK is installed in the environment that will extract and run
the model:

```bash
python -c 'import wio_sdk; print(wio_sdk.__file__)'
python -m wio_sdk.extract --help
```

If this fails, install the product's Python SDK or activate the target's pinned
SDK environment. Do not vendor extractor code into `.workers/`.

```python
from typing import Annotated

from wio_sdk import CREATES, PLAIN, ExpectedErrors, Resource, Value, flow, invariant


class Records(Resource):
    pass


class RecordId(Value):
    pass


IDENTITY = invariant("RECORD_IDENTITY", "a record retains its accepted identity")


# wio-source: docs/api.md#create symbol create
@flow(
    key="create-record",
    resources=(Records,),
    invariants=(IDENTITY,),
    modalities=("sync",),
)
def create(
    ctx: object,
    record_id: Annotated[
        RecordId,
        CREATES,
        ExpectedErrors({"malformed": "MalformedId", "reused": "AlreadyExists"}),
    ],
    body: Annotated[str, PLAIN],
) -> bool:
    return bool(ctx and record_id and body)
```

For a consuming input, use `CONSUMES` and map only misuse names backed by real
public errors. The checker records every omitted engine negation as named
debt. Do not set `Value.expected_errors`; it cannot express an operation-local
role.

Extract without importing target application code beyond the atom package:

```bash
python -m wio_sdk.extract .workers/model/atoms --strict \
  > .workers/generated/manifest.json
```

The extractor imports atom modules, so declarations must be hermetic and must
not contact services or execute the system under test at import time.
