#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path


FILES = {
    ".gitignore": "generated/\n.local/\n",
    "model/atoms/.gitkeep": "",
    "generated/.gitkeep": "",
    "evidence/.gitkeep": "",
    ".local/.gitkeep": "",
}


def scaffold(repo: Path, language: str) -> None:
    root = repo.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"repository directory does not exist: {repo}")
    workers = root / ".workers"
    desired = dict(FILES)
    desired["harness.toml"] = f'format = 1\nlanguage = "{language}"\n'

    conflicts = [
        str(path)
        for relative, content in sorted(desired.items())
        if (path := workers / relative).exists()
        and (not path.is_file() or path.read_text(encoding="utf-8") != content)
    ]
    if conflicts:
        raise ValueError("conflicting scaffold files: " + ", ".join(conflicts))

    for relative, content in sorted(desired.items()):
        path = workers / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the WIO three-zone scaffold")
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--language", choices=("python", "typescript"), required=True)
    args = parser.parse_args()
    try:
        scaffold(args.repo, args.language)
    except (OSError, ValueError) as error:
        print(f"scaffold: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
