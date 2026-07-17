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
            self.assertEqual(summary["debt"], [])

    def test_rejects_implicit_role(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            atoms = Path(directory)
            (atoms / "records.py").write_text("# wio-source: docs/api.md#create\n")
            candidate = manifest()
            del candidate["atoms"]["create-record"]["input_roles"]  # type: ignore[index]
            with self.assertRaisesRegex(ModelError, "explicit input_roles"):
                check_manifest(candidate, atoms)

    def test_incomplete_consumer_negations_emit_named_debt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            atoms = Path(directory)
            (atoms / "records.py").write_text("# wio-source: docs/api.md#read\n")
            candidate = manifest("consumes")
            del candidate["atoms"]["create-record"]["expected_errors"]["record_id"]["stale"]  # type: ignore[index]
            summary = check_manifest(candidate, atoms)
            self.assertEqual(
                summary["debt"],
                [
                    {
                        "atom": "create-record",
                        "class": "misuse-contract",
                        "detail": (
                            "consumes input create-record.record_id has no cited "
                            "expected error for engine negation stale"
                        ),
                        "input": "record_id",
                        "misuse": "stale",
                    }
                ],
            )

    def test_empty_consumer_mapping_emits_all_six_debts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            atoms = Path(directory)
            (atoms / "records.py").write_text("# wio-source: docs/api.md#read\n")
            candidate = manifest("consumes")
            candidate["atoms"]["create-record"]["expected_errors"]["record_id"] = {}  # type: ignore[index]
            summary = check_manifest(candidate, atoms)
            self.assertEqual(len(summary["debt"]), 6)

    def test_rejects_unknown_consumer_negation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            atoms = Path(directory)
            (atoms / "records.py").write_text("# wio-source: docs/api.md#read\n")
            candidate = manifest("consumes")
            candidate["atoms"]["create-record"]["expected_errors"]["record_id"]["teleported"] = "Impossible"  # type: ignore[index]
            with self.assertRaisesRegex(ModelError, "unknown engine negations"):
                check_manifest(candidate, atoms)

    def test_rejects_uncited_atom(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            atoms = Path(directory)
            (atoms / "records.py").write_text("pass\n")
            with self.assertRaisesRegex(ModelError, "wio-source"):
                check_manifest(manifest(), atoms)


if __name__ == "__main__":
    unittest.main()
