from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scaffold import scaffold


class ScaffoldTests(unittest.TestCase):
    def test_scaffold_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            scaffold(repo, "python")
            before = {
                path.relative_to(repo): path.read_bytes()
                for path in sorted((repo / ".workers").rglob("*"))
                if path.is_file()
            }
            scaffold(repo, "python")
            after = {
                path.relative_to(repo): path.read_bytes()
                for path in sorted((repo / ".workers").rglob("*"))
                if path.is_file()
            }
            self.assertEqual(before, after)

    def test_conflict_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            scaffold(repo, "python")
            config = repo / ".workers" / "harness.toml"
            config.write_text("owned = true\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "conflicting scaffold"):
                scaffold(repo, "typescript")
            self.assertEqual(config.read_text(encoding="utf-8"), "owned = true\n")


if __name__ == "__main__":
    unittest.main()
