from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model_critic import CriticError, build_report, run


PYTHON_FLAW = '''\
from wio_sdk import checkpoint, flow
READY = checkpoint("READY")

@flow(key="read", resources=(), invariants=(), modalities=("sync",))
def read(ctx):
    raise AssertionError("not ready")
    ctx.checkpoint(READY)
'''

PYTHON_CLEAN = '''\
from wio_sdk import checkpoint, flow
READY = checkpoint("READY")

@flow(key="read", resources=(), invariants=(), modalities=("sync",))
def read(ctx):
    ctx.checkpoint(READY)
    assert ctx.client.read() is not None
'''

TYPESCRIPT_FLAW = '''\
export const read = flow({ key: "read" })(function read(ctx: Context): void {
  // throw in a comment must not count
  const message = "throw in a string";
  throw new Error(message);
  ctx.checkpoint("READY");
});
'''

TYPESCRIPT_CLEAN_WITH_THROWING_HELPER = '''\
function helper(): never {
  throw new Error("helper failure");
}

export const read = flow({ key: "read" })(function read(ctx: Context): void {
  ctx.checkpoint("READY");
  helper();
});
'''


class ModelCriticTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.atoms = self.root / "atoms"
        self.atoms.mkdir()
        self.law = self.root / "SKILL.md"
        self.law.write_text("# Model law\n", encoding="utf-8")
        self.gotchas = self.root / "BUILD.md"
        self.gotchas.write_text(
            "# Build\n\n## 7. Hard-won gotchas (each already cost us once)\n\n"
            "- Entry state is declared.\n\n## 8. Next\n",
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def report(self) -> dict[str, object]:
        return build_report(self.atoms, [self.law], self.gotchas)

    def test_python_and_typescript_findings_are_sorted(self) -> None:
        (self.atoms / "z.py").write_text(PYTHON_FLAW, encoding="utf-8")
        (self.atoms / "a.ts").write_text(TYPESCRIPT_FLAW, encoding="utf-8")
        report = self.report()
        self.assertEqual(report["verdict"], "findings")
        self.assertEqual(
            [(finding["path"], finding["line"]) for finding in report["findings"]],
            [("a.ts", 4), ("z.py", 6)],
        )

    def test_typescript_helper_is_not_an_atom_body(self) -> None:
        (self.atoms / "read.ts").write_text(
            TYPESCRIPT_CLEAN_WITH_THROWING_HELPER, encoding="utf-8"
        )
        self.assertEqual(self.report()["findings"], [])

    def test_post_checkpoint_assertion_is_clean_and_deterministic(self) -> None:
        (self.atoms / "read.py").write_text(PYTHON_CLEAN, encoding="utf-8")
        first = self.report()
        second = self.report()
        self.assertEqual(first, second)
        self.assertEqual(first["verdict"], "clean")
        self.assertEqual(first["findings"], [])

    def test_hash_changes_with_atom_law_and_gotcha_section_only(self) -> None:
        atom = self.atoms / "read.py"
        atom.write_text(PYTHON_CLEAN, encoding="utf-8")
        original = self.report()["input_sha256"]
        atom.write_text(PYTHON_CLEAN + "\n", encoding="utf-8")
        atom_changed = self.report()["input_sha256"]
        self.assertNotEqual(original, atom_changed)
        atom.write_text(PYTHON_CLEAN, encoding="utf-8")
        self.law.write_text("# Changed law\n", encoding="utf-8")
        law_changed = self.report()["input_sha256"]
        self.assertNotEqual(original, law_changed)
        self.law.write_text("# Model law\n", encoding="utf-8")
        self.gotchas.write_text(
            "# Build\n\n## 7. Hard-won gotchas (each already cost us once)\n\n"
            "- Changed.\n\n## 8. Next\n",
            encoding="utf-8",
        )
        self.assertNotEqual(original, self.report()["input_sha256"])
        self.gotchas.write_text(
            "# Build\n\n## 7. Hard-won gotchas (each already cost us once)\n\n"
            "- Entry state is declared.\n\n"
            "## 8. Next\nchanged outside section\n",
            encoding="utf-8",
        )
        self.assertEqual(original, self.report()["input_sha256"])

    def test_skill_law_command_order_is_hashed(self) -> None:
        (self.atoms / "read.py").write_text(PYTHON_CLEAN, encoding="utf-8")
        second_law = self.root / "model-authoring.md"
        second_law.write_text("# Second model law\n", encoding="utf-8")
        first = build_report(self.atoms, [self.law, second_law], self.gotchas)
        reversed_laws = build_report(
            self.atoms, [second_law, self.law], self.gotchas
        )
        self.assertNotEqual(first["input_sha256"], reversed_laws["input_sha256"])

    def test_verify_rejects_stale_and_unknown_waiver_field(self) -> None:
        atom = self.atoms / "read.py"
        atom.write_text(PYTHON_CLEAN, encoding="utf-8")
        report = self.root / "critic.json"
        review = [
            "review",
            "--atoms",
            str(self.atoms),
            "--skill-law",
            str(self.law),
            "--gotchas",
            str(self.gotchas),
            "--out",
            str(report),
        ]
        self.assertEqual(run(review), 0)
        verify = [
            "verify",
            "--atoms",
            str(self.atoms),
            "--skill-law",
            str(self.law),
            "--gotchas",
            str(self.gotchas),
            "--report",
            str(report),
            "--require-clean",
        ]
        self.assertEqual(run(verify), 0)
        atom.write_text(PYTHON_CLEAN + "\n", encoding="utf-8")
        with self.assertRaisesRegex(CriticError, "model-critic-stale"):
            run(verify)
        atom.write_text(PYTHON_CLEAN, encoding="utf-8")
        value = json.loads(report.read_text(encoding="utf-8"))
        value["waived"] = True
        report.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(CriticError, "model-critic-schema"):
            run(verify)

    def test_schema_rejects_boolean_version_and_non_string_verdict(self) -> None:
        (self.atoms / "read.py").write_text(PYTHON_CLEAN, encoding="utf-8")
        report = self.root / "critic.json"
        value = self.report()
        value["version"] = True
        report.write_text(json.dumps(value), encoding="utf-8")
        arguments = [
            "verify",
            "--atoms",
            str(self.atoms),
            "--skill-law",
            str(self.law),
            "--gotchas",
            str(self.gotchas),
            "--report",
            str(report),
        ]
        with self.assertRaisesRegex(CriticError, "model-critic-schema"):
            run(arguments)
        value = self.report()
        value["verdict"] = []
        report.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(CriticError, "model-critic-schema"):
            run(arguments)

    def test_findings_cannot_satisfy_require_clean(self) -> None:
        (self.atoms / "read.py").write_text(PYTHON_FLAW, encoding="utf-8")
        report = self.root / "critic.json"
        self.assertEqual(
            run(
                [
                    "review",
                    "--atoms",
                    str(self.atoms),
                    "--skill-law",
                    str(self.law),
                    "--gotchas",
                    str(self.gotchas),
                    "--out",
                    str(report),
                ]
            ),
            0,
        )
        with self.assertRaisesRegex(CriticError, "model-critic-findings"):
            run(
                [
                    "verify",
                    "--atoms",
                    str(self.atoms),
                    "--skill-law",
                    str(self.law),
                    "--gotchas",
                    str(self.gotchas),
                    "--report",
                    str(report),
                    "--require-clean",
                ]
            )

    def test_symlink_and_duplicate_law_paths_fail_closed(self) -> None:
        (self.atoms / "read.py").write_text(PYTHON_CLEAN, encoding="utf-8")
        (self.atoms / "linked.py").symlink_to(self.atoms / "read.py")
        with self.assertRaisesRegex(CriticError, "symlink"):
            self.report()
        (self.atoms / "linked.py").unlink()
        with self.assertRaisesRegex(CriticError, "duplicate --skill-law"):
            build_report(self.atoms, [self.law, self.law], self.gotchas)

    def test_missing_or_ambiguous_gotchas_fail_closed(self) -> None:
        (self.atoms / "read.py").write_text(PYTHON_CLEAN, encoding="utf-8")
        self.gotchas.write_text("# no section\n", encoding="utf-8")
        with self.assertRaisesRegex(CriticError, "exactly one"):
            self.report()
        self.gotchas.write_text(
            "## 7. Hard-won gotchas (each already cost us once)\nA\n## 8. Other\n"
            "## 7. Hard-won gotchas (each already cost us once)\nB\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(CriticError, "exactly one"):
            self.report()


if __name__ == "__main__":
    unittest.main()
