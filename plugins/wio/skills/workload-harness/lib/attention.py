#!/usr/bin/env python3
"""attention.py -- the attention-inversion probe (v0.2).

Computes, for every documented surface, five MECHANICAL counts from the
target repo -- no judgment, no model calls, fully reproducible (an auditor
re-running the probe must get byte-identical output):

  1. test_callsites   occurrences of the surface's tokens in test files
  2. test_situations  distinct test functions/blocks mentioning a token
  3. tested_modalities of {sync, async, threaded}: which appear syntactically
                      inside the mentioning test blocks
  4. churn            commits touching the surface's defining files in the
                      trailing window (default 540 days)
  5. issue_mentions   mentions in a frozen issue snapshot (optional jsonl)

and folds the FROZEN ranking formula (formula v2, cell-level -- calibrated
once by grader-side retrodiction, never tuned inside a run):

  realness(s)    = 1 + log2(1 + doc_mentions + 2 * issue_mentions)
  weight(s)      = realness(s) * 1 / (1 + test_situations)          # surface
  weight(s, ax)  = realness(s) * 1 / (1 + test_situations(s, ax))   # cell

The scoring unit is the lattice CELL: surface x axis, where axis is a
modality ({sync, async, threaded}, detected syntactically) or a mechanism
({race, recovery, retry, limit, misuse}, detected by keyword classes inside
the mentioning test block). Formula v1 scored bare surfaces and was refuted
by retrodiction: latent bugs cluster on heavily-tested surfaces whose
CELLS are empty (the async modality of a sync-hammered API, the retry path
of a nominal-tested step). High cell weight = users hit the surface, the
vendor's suite never exercises it THIS way. Churn and callsites are
reported for the producer as tie-breakers; they are NOT in the scalar.

Input surfaces file (JSON list; the producer's census, one entry per
documented surface):

  [{"name": "Shop.pay()", "tokens": ["pay"], "files": ["shop/_pay.py"]}, ...]

Usage:
  attention.py --repo DIR --surfaces surfaces.json
               [--issues issues.jsonl] [--churn-days 540] [--json]

Python 3.12 stdlib only. Zero product nouns.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys

TEST_FILE_PAT = re.compile(
    r"(^|/)(tests?|__tests__)(/|$)|(^|/)test_[^/]+\.(py|ts|js|mjs)$"
    r"|_test\.(py|go|ts|js)$|\.(test|spec)\.(ts|js|mjs|tsx|jsx)$")
DOC_FILE_PAT = re.compile(
    r"(^|/)(docs?|examples?|templates?)(/|$)|(^|/)README[^/]*$", re.IGNORECASE)
# A "test block" starts at a line matching one of these; the block owns all
# lines until the next block start. Coarse, language-agnostic, deterministic.
BLOCK_START = re.compile(
    r"^\s*(async\s+def\s+test_|def\s+test_|it\(|test\(|it\.each|test\.each"
    r"|func\s+Test)", re.MULTILINE)
ASYNC_PAT = re.compile(r"\basync\s+def\b|\bawait\b|asyncio\.")
THREAD_PAT = re.compile(r"\bThread\(|ThreadPool|threading\.|concurrent\.futures")
# Mechanism keyword classes -- coarse, deterministic, language-agnostic.
MECH_PATS = {
    "race": re.compile(r"\brace\b|concurrent|parallel|Thread\(|ThreadPool|interleav",
                       re.IGNORECASE),
    "recovery": re.compile(r"recover|restart|crash|resume|relaunch|reboot", re.IGNORECASE),
    "retry": re.compile(r"retry|retries|attempt|backoff|redeliver", re.IGNORECASE),
    "limit": re.compile(r"timeout|limit|max_|deadline|quota|overflow|full\b", re.IGNORECASE),
    "misuse": re.compile(r"raises|invalid|error|wrong|illegal|denied|forbidden|conflict",
                         re.IGNORECASE),
}
MODALITY_AXES = ("sync", "async", "threaded")
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist",
             "build", ".workers"}


def _walk(root: str):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            full = os.path.join(dirpath, name)
            yield os.path.relpath(full, root).replace(os.sep, "/"), full


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _token_res(tokens: list[str]) -> list[re.Pattern]:
    # \b-delimited where the token edge is a word char; plain find otherwise.
    out = []
    for t in tokens:
        pat = re.escape(t)
        if t and (t[0].isalnum() or t[0] == "_"):
            pat = r"\b" + pat
        if t and (t[-1].isalnum() or t[-1] == "_"):
            pat = pat + r"\b"
        out.append(re.compile(pat))
    return out


def _blocks(text: str) -> list[str]:
    starts = [m.start() for m in BLOCK_START.finditer(text)]
    if not starts:
        return []
    starts.append(len(text))
    return [text[starts[i]:starts[i + 1]] for i in range(len(starts) - 1)]


def _git_churn(repo: str, days: int) -> dict[str, int]:
    """{relpath: commit_count} over the trailing window. Empty dict when the
    tree is not a git checkout (counts then read 0 -- reported, never fatal)."""
    try:
        out = subprocess.run(
            ["git", "-C", repo, "log", f"--since={days} days ago",
             "--name-only", "--pretty=format:"],
            capture_output=True, text=True, timeout=120).stdout
    except (OSError, subprocess.TimeoutExpired):
        return {}
    counts: dict[str, int] = {}
    for ln in out.splitlines():
        ln = ln.strip()
        if ln:
            counts[ln] = counts.get(ln, 0) + 1
    return counts


def probe(repo: str, surfaces: list[dict], issues_path: str | None = None,
          churn_days: int = 540) -> list[dict]:
    test_texts: list[tuple[str, str]] = []
    doc_texts: list[str] = []
    for rel, full in _walk(repo):
        if TEST_FILE_PAT.search(rel):
            test_texts.append((rel, _read(full)))
        elif DOC_FILE_PAT.search(rel):
            doc_texts.append(_read(full))
    test_blocks = [(rel, b) for rel, t in test_texts for b in _blocks(t)]
    churn = _git_churn(repo, churn_days)
    issue_text = _read(issues_path) if issues_path else ""

    rows = []
    for s in surfaces:
        name = s.get("name", "?")
        tres = _token_res(list(s.get("tokens") or []))
        if not tres:
            continue

        def hits(text: str) -> int:
            return sum(len(r.findall(text)) for r in tres)

        callsites = sum(hits(t) for _rel, t in test_texts)
        mention_blocks = [b for _rel, b in test_blocks if any(r.search(b) for r in tres)]
        situations = len(mention_blocks)
        axis_n = {f"modality:{m}": 0 for m in MODALITY_AXES}
        axis_n.update({f"mechanism:{m}": 0 for m in MECH_PATS})
        axis_n.update({f"cross:{m}*{k}": 0 for m in MODALITY_AXES for k in MECH_PATS})
        modalities = set()
        for b in mention_blocks:
            is_async = bool(ASYNC_PAT.search(b))
            is_thread = bool(THREAD_PAT.search(b))
            block_mods = []
            if is_async:
                modalities.add("async")
                block_mods.append("async")
            if is_thread:
                modalities.add("threaded")
                block_mods.append("threaded")
            if not (is_async or is_thread):
                modalities.add("sync")
                block_mods.append("sync")
            for m in block_mods:
                axis_n[f"modality:{m}"] += 1
            for mech, mp in MECH_PATS.items():
                if mp.search(b):
                    axis_n[f"mechanism:{mech}"] += 1
                    for m in block_mods:
                        axis_n[f"cross:{m}*{mech}"] += 1
        churn_n = sum(churn.get(f, 0) for f in (s.get("files") or []))
        issue_n = hits(issue_text)
        doc_n = sum(hits(t) for t in doc_texts)

        realness = 1.0 + math.log2(1 + doc_n + 2 * issue_n)
        weight = realness / (1 + situations)
        rows.append({
            "surface": name,
            "test_callsites": callsites,
            "test_situations": situations,
            "tested_modalities": sorted(modalities),
            "axis_situations": axis_n,
            "cell_weights": {ax: round(realness / (1 + n), 4)
                             for ax, n in axis_n.items()},
            "churn": churn_n,
            "issue_mentions": issue_n,
            "doc_mentions": doc_n,
            "realness": round(realness, 4),
            "weight": round(weight, 4),
        })
    rows.sort(key=lambda r: (-r["weight"], r["surface"]))
    return rows


def cells(rows: list[dict]) -> list[dict]:
    """Flatten probe rows into ranked lattice cells (formula v2's unit)."""
    out = [{"surface": r["surface"], "axis": ax, "situations": r["axis_situations"][ax],
            "weight": w}
           for r in rows for ax, w in r["cell_weights"].items()]
    out.sort(key=lambda c: (-c["weight"], c["surface"], c["axis"]))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="attention-inversion probe (v0.2)")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--surfaces", required=True)
    ap.add_argument("--issues", default=None)
    ap.add_argument("--churn-days", type=int, default=540)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--cells", action="store_true",
                    help="rank lattice cells (surface x axis) instead of surfaces")
    args = ap.parse_args(argv)

    with open(args.surfaces, encoding="utf-8") as f:
        surfaces = json.load(f)
    rows = probe(args.repo, surfaces, args.issues, args.churn_days)
    if args.cells:
        cs = cells(rows)
        if args.json:
            json.dump(cs, sys.stdout, indent=1)
            print()
        else:
            print("weight\tsituations\taxis\tsurface")
            for c in cs:
                print(f"{c['weight']}\t{c['situations']}\t{c['axis']}\t{c['surface']}")
        return 0
    if args.json:
        json.dump(rows, sys.stdout, indent=1)
        print()
    else:
        print("weight\tsituations\tcallsites\tmodalities\tchurn\tissues\tdocs\tsurface")
        for r in rows:
            print(f"{r['weight']}\t{r['test_situations']}\t{r['test_callsites']}"
                  f"\t{','.join(r['tested_modalities']) or '-'}\t{r['churn']}"
                  f"\t{r['issue_mentions']}\t{r['doc_mentions']}\t{r['surface']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
