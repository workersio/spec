from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from check_model import ModelError, check_manifest


def manifest(role: str = "creates") -> dict[str, object]:
    errors = {
        "creates": {"reused": "AlreadyExists"},
        "consumes": {
            "foreign": "ForeignId",
            "malformed": "MalformedId",
            "nonexistent": "NotFound",
            "reused": "ReusedId",
            "stale": "StaleId",
            "wrong-lifecycle-state": "ClosedId",
        },
        "plain": {},
    }[role]
    return {
        "format": "manifest",
        "version": 1,
        "lints": [],
        "atoms": {
            "create-record": {
                "key": "create-record",
                "module": "records",
                "inputs": {"record_id": "RecordId"},
                "input_roles": {"record_id": role},
                "expected_errors": {"record_id": errors},
                "invariants": [{"name": "identity", "text": "identity is stable"}],
                "modalities": ["sync"],
            }
        },
    }


class ModelCheckTests(unittest.TestCase):
    def test_accepts_explicit_roles_and_citation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            atoms = Path(directory)
            (atoms / "records.py").write_text("# wio-source: docs/api.md#create\n")
            summary = check_manifest(manifest(), atoms)
            self.assertEqual(summary["roles"], {"creates": 1})

    def test_rejects_implicit_role(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            atoms = Path(directory)
            (atoms / "records.py").write_text("# wio-source: docs/api.md#create\n")
            candidate = manifest()
            del candidate["atoms"]["create-record"]["input_roles"]  # type: ignore[index]
            with self.assertRaisesRegex(ModelError, "explicit input_roles"):
                check_manifest(candidate, atoms)

    def test_rejects_incomplete_consumer_negations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            atoms = Path(directory)
            (atoms / "records.py").write_text("# wio-source: docs/api.md#read\n")
            candidate = manifest("consumes")
            del candidate["atoms"]["create-record"]["expected_errors"]["record_id"]["stale"]  # type: ignore[index]
            with self.assertRaisesRegex(ModelError, "all six"):
                check_manifest(candidate, atoms)

    def test_rejects_uncited_atom(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            atoms = Path(directory)
            (atoms / "records.py").write_text("pass\n")
            with self.assertRaisesRegex(ModelError, "wio-source"):
                check_manifest(manifest(), atoms)


if __name__ == "__main__":
    unittest.main()
