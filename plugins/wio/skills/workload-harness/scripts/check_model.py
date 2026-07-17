#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROLES = {"creates", "consumes", "plain"}
CREATE_ERRORS = {"malformed", "reused"}
CONSUME_ERRORS = {
    "foreign",
    "malformed",
    "nonexistent",
    "reused",
    "stale",
    "wrong-lifecycle-state",
}
SOURCE_SUFFIXES = (".py", ".ts", ".tsx")


class ModelError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ModelError(message)


def check_manifest(manifest: Any, atoms_dir: Path) -> dict[str, Any]:
    require(isinstance(manifest, dict), "manifest must be an object")
    require(
        manifest.get("format") == "manifest" and manifest.get("version") == 1,
        "manifest must use format 'manifest' version 1",
    )
    require(manifest.get("lints") == [], "manifest must contain zero extractor lints")
    atoms = manifest.get("atoms")
    require(isinstance(atoms, dict) and bool(atoms), "manifest atoms must be nonempty")
    require(atoms_dir.is_dir(), f"atom source directory does not exist: {atoms_dir}")

    roles: Counter[str] = Counter()
    module_atoms: dict[str, int] = defaultdict(int)
    for key in sorted(atoms):
        atom = atoms[key]
        require(isinstance(key, str) and isinstance(atom, dict), "atoms must map strings to objects")
        require(atom.get("key") == key, f"atom {key!r} key does not match its map key")
        inputs = atom.get("inputs")
        require(isinstance(inputs, dict), f"atom {key!r} inputs must be an object")
        require(
            all(isinstance(name, str) and isinstance(kind, str) for name, kind in inputs.items()),
            f"atom {key!r} inputs must map strings to type names",
        )
        input_roles = atom.get("input_roles")
        require(
            isinstance(input_roles, dict) and set(input_roles) == set(inputs),
            f"atom {key!r} requires explicit input_roles for every input",
        )
        expected = atom.get("expected_errors")
        require(
            isinstance(expected, dict) and set(expected) == set(inputs),
            f"atom {key!r} expected_errors must cover every input",
        )
        invariants = atom.get("invariants")
        require(
            isinstance(invariants, list)
            and bool(invariants)
            and all(
                isinstance(item, dict)
                and isinstance(item.get("name"), str)
                and bool(item["name"])
                and isinstance(item.get("text"), str)
                and bool(item["text"])
                for item in invariants
            ),
            f"atom {key!r} invariants must be nonempty named statements",
        )
        modalities = atom.get("modalities")
        require(
            isinstance(modalities, list)
            and bool(modalities)
            and all(isinstance(item, str) and bool(item) for item in modalities),
            f"atom {key!r} modalities must be nonempty strings",
        )

        for name in sorted(inputs):
            role = input_roles[name]
            errors = expected[name]
            require(role in ROLES, f"atom {key!r} input {name!r} has unknown role {role!r}")
            require(
                isinstance(errors, dict)
                and all(
                    isinstance(misuse, str)
                    and bool(misuse)
                    and isinstance(error, str)
                    and bool(error)
                    for misuse, error in errors.items()
                ),
                f"atom {key!r} input {name!r} expected errors must map nonempty strings",
            )
            error_keys = set(errors)
            if role == "plain":
                require(not error_keys, f"atom {key!r} plain input {name!r} cannot declare misuse errors")
            elif role == "creates":
                require(
                    error_keys <= CREATE_ERRORS,
                    f"atom {key!r} creates input {name!r} permits only malformed/reused",
                )
            else:
                require(
                    error_keys == CONSUME_ERRORS,
                    f"atom {key!r} consumes input {name!r} requires all six engine negations",
                )
            roles[role] += 1

        module = atom.get("module")
        require(isinstance(module, str) and bool(module), f"atom {key!r} has no source module")
        module_atoms[module] += 1

    sources: dict[str, list[Path]] = defaultdict(list)
    for path in sorted(atoms_dir.rglob("*")):
        if path.is_file() and path.suffix in SOURCE_SUFFIXES:
            sources[path.stem].append(path)
    for module, count in sorted(module_atoms.items()):
        candidates = sources.get(Path(module).stem, [])
        require(len(candidates) == 1, f"module {module!r} must resolve to exactly one atom source")
        citation_count = candidates[0].read_text(encoding="utf-8").count("wio-source:")
        require(
            citation_count >= count,
            f"module {module!r} requires one wio-source citation per atom",
        )

    return {
        "atoms": len(atoms),
        "format": "model-check",
        "roles": {role: roles[role] for role in sorted(roles)},
        "version": 1,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a ratified WIO format-1 model")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--atoms", type=Path, required=True)
    args = parser.parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        summary = check_manifest(manifest, args.atoms.expanduser().resolve())
    except (OSError, json.JSONDecodeError, ModelError) as error:
        print(f"model-check: {error}", file=sys.stderr)
        return 1
    print(json.dumps(summary, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
