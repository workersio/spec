#!/usr/bin/env python3
"""Create and verify content-stamped workload-model critic reports."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn, Protocol, Sequence


FORMAT = "wio-model-critic"
VERSION = 1
SOURCE_SUFFIXES = {".py", ".ts", ".tsx"}
GOTCHAS_HEADING = "## 7. Hard-won gotchas (each already cost us once)"
LAW = "BUILD §7: entry-state expectations belong in declared preconditions"
ROOT_FIELDS = {"findings", "format", "input_sha256", "verdict", "version"}
FINDING_FIELDS = {"detail", "id", "law", "line", "path"}


class CriticError(ValueError):
    """An input or report violates the critic contract."""


class _Digest(Protocol):
    def update(self, data: bytes, /) -> object: ...


@dataclass(frozen=True, order=True)
class Finding:
    id: str
    path: str
    line: int
    law: str
    detail: str

    def to_json(self) -> dict[str, object]:
        return {
            "id": self.id,
            "path": self.path,
            "line": self.line,
            "law": self.law,
            "detail": self.detail,
        }


def _fail(prefix: str, detail: str) -> NoReturn:
    raise CriticError(f"{prefix}: {detail}")


def _read_regular(path: Path, owner: str) -> bytes:
    if path.is_symlink():
        _fail("model-critic-input", f"{owner} must not be a symlink: {path}")
    if not path.is_file():
        _fail("model-critic-input", f"{owner} must be a regular file: {path}")
    try:
        return path.read_bytes()
    except OSError as error:
        _fail("model-critic-input", f"cannot read {owner} {path}: {error}")


def _atom_files(root: Path) -> list[tuple[str, Path, bytes]]:
    if root.is_symlink() or not root.is_dir():
        _fail("model-critic-input", f"atoms must be a non-symlink directory: {root}")
    files: list[tuple[str, Path, bytes]] = []
    try:
        candidates = sorted(root.rglob("*"), key=lambda path: path.relative_to(root).as_posix())
    except OSError as error:
        _fail("model-critic-input", f"cannot traverse atoms {root}: {error}")
    for path in candidates:
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            _fail("model-critic-input", f"atom tree contains symlink: {relative}")
        if path.is_file() and path.suffix.lower() in SOURCE_SUFFIXES:
            files.append((relative, path, _read_regular(path, f"atom {relative}")))
    if not files:
        _fail("model-critic-input", "atom tree has no Python or TypeScript sources")
    return files


def _gotchas_section(path: Path) -> bytes:
    raw = _read_regular(path, "gotchas")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        _fail("model-critic-input", f"gotchas are not UTF-8: {error}")
    lines = text.splitlines(keepends=True)
    starts = [index for index, line in enumerate(lines) if line.rstrip("\r\n") == GOTCHAS_HEADING]
    if len(starts) != 1:
        _fail(
            "model-critic-input",
            f"gotchas must contain exactly one {GOTCHAS_HEADING!r} heading",
        )
    start = starts[0]
    end = next(
        (index for index in range(start + 1, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    section = "".join(lines[start:end]).encode("utf-8")
    if not section.strip():
        _fail("model-critic-input", "gotchas section is empty")
    return section


def _feed(digest: _Digest, label: str, payload: bytes) -> None:
    label_bytes = label.encode("utf-8")
    digest.update(len(label_bytes).to_bytes(8, "big"))
    digest.update(label_bytes)
    digest.update(len(payload).to_bytes(8, "big"))
    digest.update(payload)


def _input_digest(
    files: Sequence[tuple[str, Path, bytes]],
    laws: Sequence[Path],
    gotchas: Path,
) -> str:
    resolved_laws = [path.resolve(strict=False) for path in laws]
    if not laws:
        _fail("model-critic-input", "at least one --skill-law is required")
    if len(set(resolved_laws)) != len(resolved_laws):
        _fail("model-critic-input", "duplicate --skill-law paths are forbidden")
    digest = hashlib.sha256()
    for relative, _, payload in files:
        _feed(digest, f"atom:{relative}", payload)
    for index, law in enumerate(laws):
        _feed(digest, f"skill-law:{index}", _read_regular(law, "skill law"))
    _feed(digest, "gotchas:section-7", _gotchas_section(gotchas))
    return digest.hexdigest()


def _decorator_name(node: ast.expr) -> str | None:
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def _is_flow(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    return any(_decorator_name(decorator) == "flow" for decorator in function.decorator_list)


class _BodyEvents(ast.NodeVisitor):
    def __init__(self, root: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.root = root
        self.checkpoints: list[int] = []
        self.entry_failures: list[tuple[int, str]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        if node is self.root:
            self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        if node is self.root:
            self.generic_visit(node)

    def visit_Lambda(self, node: ast.Lambda) -> None:  # noqa: N802
        return

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        function = node.func
        if (
            isinstance(function, ast.Attribute)
            and function.attr == "checkpoint"
            and isinstance(function.value, ast.Name)
            and function.value.id == "ctx"
        ):
            self.checkpoints.append(node.lineno)
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert) -> None:  # noqa: N802
        self.entry_failures.append((node.lineno, "assertion"))
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:  # noqa: N802
        self.entry_failures.append((node.lineno, "raise"))
        self.generic_visit(node)


def _python_findings(relative: str, payload: bytes) -> list[Finding]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        _fail("model-critic-input", f"atom {relative} is not UTF-8: {error}")
    try:
        tree = ast.parse(text, filename=relative)
    except SyntaxError as error:
        _fail("model-critic-input", f"cannot parse Python atom {relative}:{error.lineno}: {error.msg}")
    findings: list[Finding] = []
    functions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_flow(node)
    ]
    for function in functions:
        events = _BodyEvents(function)
        events.visit(function)
        first_checkpoint = min(events.checkpoints, default=sys.maxsize)
        for line, kind in events.entry_failures:
            if line < first_checkpoint:
                findings.append(
                    Finding(
                        id="entry-state-before-checkpoint",
                        path=relative,
                        line=line,
                        law=LAW,
                        detail=(
                            f"flow {function.name!r} has an explicit {kind} before its "
                            "first ctx.checkpoint; declare the entry condition in model semantics"
                        ),
                    )
                )
    return findings


def _mask_typescript(text: str) -> str:
    output: list[str] = []
    index = 0
    state = "code"
    quote = ""
    while index < len(text):
        char = text[index]
        next_char = text[index + 1] if index + 1 < len(text) else ""
        if state == "code":
            if char == "/" and next_char == "/":
                output.extend("  ")
                index += 2
                state = "line-comment"
                continue
            if char == "/" and next_char == "*":
                output.extend("  ")
                index += 2
                state = "block-comment"
                continue
            if char in {'"', "'", "`"}:
                quote = char
                output.append(" ")
                index += 1
                state = "string"
                continue
            output.append(char)
            index += 1
            continue
        if state == "line-comment":
            output.append("\n" if char == "\n" else " ")
            index += 1
            if char == "\n":
                state = "code"
            continue
        if state == "block-comment":
            if char == "*" and next_char == "/":
                output.extend("  ")
                index += 2
                state = "code"
            else:
                output.append("\n" if char == "\n" else " ")
                index += 1
            continue
        if char == "\\" and index + 1 < len(text):
            output.extend("\n " if next_char == "\n" else "  ")
            index += 2
        elif char == quote:
            output.append(" ")
            index += 1
            state = "code"
        else:
            output.append("\n" if char == "\n" else " ")
            index += 1
    return "".join(output)


def _matching_delimiter(text: str, start: int, opening: str, closing: str) -> int | None:
    if start >= len(text) or text[start] != opening:
        return None
    depth = 0
    for index in range(start, len(text)):
        if text[index] == opening:
            depth += 1
        elif text[index] == closing:
            depth -= 1
            if depth == 0:
                return index
    return None


def _function_body(text: str, function_start: int, limit: int) -> tuple[int, int] | None:
    parameters = text.find("(", function_start, limit)
    if parameters < 0:
        return None
    parameters_end = _matching_delimiter(text, parameters, "(", ")")
    if parameters_end is None or parameters_end >= limit:
        return None
    body = text.find("{", parameters_end + 1, limit)
    if body < 0:
        return None
    body_end = _matching_delimiter(text, body, "{", "}")
    return (body, body_end) if body_end is not None and body_end <= limit else None


def _typescript_atom_bodies(text: str) -> list[tuple[int, int]]:
    bodies: list[tuple[int, int]] = []
    for flow in re.finditer(r"\bflow\s*\(", text):
        configuration = text.find("(", flow.start(), flow.end())
        configuration_end = _matching_delimiter(text, configuration, "(", ")")
        if configuration_end is None:
            continue
        invocation = configuration_end + 1
        while invocation < len(text) and text[invocation].isspace():
            invocation += 1
        if invocation >= len(text) or text[invocation] != "(":
            continue
        invocation_end = _matching_delimiter(text, invocation, "(", ")")
        if invocation_end is None:
            continue
        callback = re.search(r"\b(?:async\s+)?function\b", text[invocation:invocation_end])
        if callback is not None:
            body = _function_body(text, invocation + callback.start(), invocation_end)
        else:
            arrow = text.find("=>", invocation, invocation_end)
            body_start = text.find("{", arrow + 2, invocation_end) if arrow >= 0 else -1
            body_end = (
                _matching_delimiter(text, body_start, "{", "}") if body_start >= 0 else None
            )
            body = (
                (body_start, body_end)
                if body_end is not None and body_end <= invocation_end
                else None
            )
        if body is not None:
            bodies.append(body)
    if bodies:
        return bodies

    # Standalone exported functions are accepted as atom-shaped fixtures. Real
    # TypeScript models use flow(...)(callback), handled above.
    for function in re.finditer(r"\bexport\s+(?:async\s+)?function\b", text):
        body = _function_body(text, function.start(), len(text))
        if body is not None:
            bodies.append(body)
    return bodies


def _typescript_findings(relative: str, payload: bytes) -> list[Finding]:
    try:
        masked = _mask_typescript(payload.decode("utf-8"))
    except UnicodeDecodeError as error:
        _fail("model-critic-input", f"atom {relative} is not UTF-8: {error}")
    findings = []
    for body_start, body_end in _typescript_atom_bodies(masked):
        checkpoint = re.search(
            r"\bctx\s*\.\s*checkpoint\s*\(", masked[body_start:body_end]
        )
        boundary = body_start + checkpoint.start() if checkpoint else body_end
        candidates = re.finditer(
            r"\bthrow\b|\bassert\s*\(", masked[body_start:boundary]
        )
        for candidate in candidates:
            position = body_start + candidate.start()
            line = masked.count("\n", 0, position) + 1
            kind = (
                "throw"
                if candidate.group(0).lstrip().startswith("throw")
                else "assertion"
            )
            findings.append(
                Finding(
                    id="entry-state-before-checkpoint",
                    path=relative,
                    line=line,
                    law=LAW,
                    detail=(
                        f"TypeScript atom has an explicit {kind} before its first "
                        "ctx.checkpoint; declare the entry condition in model semantics"
                    ),
                )
            )
    return findings


def build_report(atoms: Path, laws: Sequence[Path], gotchas: Path) -> dict[str, object]:
    files = _atom_files(atoms)
    findings: list[Finding] = []
    for relative, _, payload in files:
        if Path(relative).suffix.lower() == ".py":
            findings.extend(_python_findings(relative, payload))
        else:
            findings.extend(_typescript_findings(relative, payload))
    findings.sort()
    return {
        "format": FORMAT,
        "version": VERSION,
        "input_sha256": _input_digest(files, laws, gotchas),
        "verdict": "findings" if findings else "clean",
        "findings": [finding.to_json() for finding in findings],
    }


def _validate_report(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != ROOT_FIELDS:
        _fail("model-critic-schema", "report fields differ from format 1")
    if (
        value.get("format") != FORMAT
        or type(value.get("version")) is not int
        or value["version"] != VERSION
    ):
        _fail("model-critic-schema", "unsupported report identity")
    digest = value.get("input_sha256")
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        _fail("model-critic-schema", "input_sha256 must be lowercase SHA-256")
    verdict = value.get("verdict")
    findings = value.get("findings")
    if (
        not isinstance(verdict, str)
        or verdict not in {"clean", "findings"}
        or not isinstance(findings, list)
    ):
        _fail("model-critic-schema", "verdict/findings have invalid types")
    for finding in findings:
        if not isinstance(finding, dict) or set(finding) != FINDING_FIELDS:
            _fail("model-critic-schema", "finding fields differ from format 1")
        if not all(isinstance(finding.get(key), str) and finding[key] for key in ("id", "path", "law", "detail")):
            _fail("model-critic-schema", "finding strings must be nonempty")
        line = finding.get("line")
        if isinstance(line, bool) or not isinstance(line, int) or line <= 0:
            _fail("model-critic-schema", "finding line must be a positive integer")
    if (verdict == "clean") != (findings == []):
        _fail("model-critic-schema", "verdict disagrees with findings")
    ordered = sorted(findings, key=lambda finding: (
        finding["id"], finding["path"], finding["line"], finding["law"], finding["detail"]
    ))
    if findings != ordered:
        _fail("model-critic-schema", "findings are not in canonical order")
    return value


def _write_report(path: Path, report: dict[str, object]) -> None:
    try:
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError as error:
        _fail("model-critic-report", f"cannot write report {path}: {error}")


def _read_report(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail("model-critic-report", f"cannot read report {path}: {error}")
    return _validate_report(value)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("review", "verify"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--atoms", required=True, type=Path)
        subparser.add_argument("--skill-law", required=True, action="append", type=Path)
        subparser.add_argument("--gotchas", required=True, type=Path)
        if command == "review":
            subparser.add_argument("--out", required=True, type=Path)
        else:
            subparser.add_argument("--report", required=True, type=Path)
            subparser.add_argument("--require-clean", action="store_true")
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "review":
        _write_report(
            arguments.out,
            build_report(arguments.atoms, arguments.skill_law, arguments.gotchas),
        )
        return 0
    report = _read_report(arguments.report)
    expected = build_report(arguments.atoms, arguments.skill_law, arguments.gotchas)
    if report["input_sha256"] != expected["input_sha256"]:
        _fail("model-critic-stale", "report input stamp differs from current inputs")
    if report != expected:
        _fail("model-critic-stale", "report content differs from deterministic review")
    if arguments.require_clean and report["verdict"] != "clean":
        _fail("model-critic-findings", "current report contains blocking findings")
    return 0


def main() -> int:
    try:
        return run()
    except CriticError as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
