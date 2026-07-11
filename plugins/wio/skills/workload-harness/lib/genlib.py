#!/usr/bin/env python3
"""genlib -- product-agnostic seeded generator + differential harness core.

Design contract:
  * A single integer seed FULLY determines a generated Program (Config + Ops).
    Generation is deterministic across processes: it never depends on dict order,
    hash randomization, wall-clock, or the random module's global state. Every
    random draw goes through a seed-derived random.Random built from a sha256 of
    (root_seed, label), so the same seed yields a byte-identical program anywhere.
  * A Program is data: a Config (key->value drawn from declared sweep AXES) plus an
    ordered list of Ops (DDL / DML / QUERY / LIFECYCLE / EXPECT_ERROR). Axes and
    value pools are declared as tables, never pinned to a single magic combo, so an
    auditor can see the generator sweeps rather than telegraphing a known bug.
  * Runners are adapters (execute a script, reopen, return rows+error+rc). The
    reference runner is stdlib sqlite3; a thin CliRunner drives a subprocess binary
    (tursodb) and is mockable. Universal, product-independent ORACLES compare the two
    runners: differential-rows, differential-error-class, integrity, panic/abort,
    terminal-state, reopen-persistence.
  * A declarative KNOWN-DIVERGENCE allowlist is consulted before any differential is
    called RED. Suppression is never silent: every suppressed diff is emitted as an
    INVARIANT ... PASS carrying a divergence:<id> note.
  * run_case(seed, axes, runners) emits the INVARIANT/VERDICT stdout protocol and
    returns exit 0 (GREEN) / 1 (RED) / 3 (VOID), matching turso_workload_common.
"""
import hashlib
import os
import random
import re
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Deterministic seeding
# ---------------------------------------------------------------------------

def _digest_int(text: str) -> int:
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")


def root_seed_from(raw: str) -> int:
    """Map an arbitrary seed string to a stable 64-bit root seed."""
    return _digest_int(f"genlib:{raw}")


def seeded_rng(root: int, label: str) -> random.Random:
    """A random.Random fully determined by (root, label) -- no global state."""
    return random.Random(_digest_int(f"{root}:{label}"))


# ---------------------------------------------------------------------------
# Axes and value pools (data, not code)
# ---------------------------------------------------------------------------

# Each axis is a name -> ordered tuple of candidate values. The generator picks
# exactly one value per axis per program; the coverage probe asserts every listed
# value is reachable. These are GENERIC config axes -- no target-specific tuple is
# pinned. Product adapters extend AXES via config_axes passed into run_case.
CORE_AXES: dict[str, tuple] = {
    # SQLite/Turso page sizes are powers of two 512..65536. Sweeping the whole
    # ladder (not just 4096) is what lets a page_size x encryption combo surface.
    "page_size": (512, 1024, 2048, 4096, 8192, 16384, 32768, 65536),
    "journal_mode": ("delete", "truncate", "persist", "memory", "wal", "off"),
    "synchronous": ("off", "normal", "full"),
    "foreign_keys": (0, 1),
    "encryption": (0, 1),
}

# ---------------------------------------------------------------------------
# Known-class quarantines (calibration lever 1a) -- visible, never silent
# ---------------------------------------------------------------------------
#
# A confirmed crashing config family MASKS the rest of a program: the candidate panics
# mid-run and every op after the panic is lost, so no OTHER oracle on that program can fire.
# WP-025 is exactly this -- encryption=1 with a non-4096 page_size aborts the tursodb process
# (assertion "Page data must be exactly 4096 bytes" at core/storage/encryption.rs:742). Left
# unmanaged it killed ~44% of cases (calibration: 66/150 encryption-panic), starving the four
# outstanding differential matchers (WP-002/005/008/015/023) of programs that run to the end.
#
# The fix is a DECLARED quarantine, not a silent skip: a predicate over the config identifies
# the known-crash family; a quarantined config is DOWNWEIGHTED to a small canary fraction
# (enough runs to keep the WP-025 panic matcher alive) and re-rolled to a non-quarantined
# config otherwise. Every skip/downweight emits a `SUPPRESSED <rule> <reason>` line so the
# quarantine is auditable -- it is management of a KNOWN finding, never suppression of an
# unknown one. Generic: a predicate over swept axis values + a canary rate, both data.
@dataclass(frozen=True)
class ConfigQuarantine:
    rule: str                              # short id emitted in the SUPPRESSED line
    predicate: Callable[[dict], bool]      # True if this config is in the known-crash family
    reason: str                            # human reason (cited to the confirmed finding)
    reference: str                         # the confirmed finding this quarantines
    canary_rate: float                     # fraction of quarantined draws kept (matcher alive)


CONFIG_QUARANTINES: tuple[ConfigQuarantine, ...] = (
    ConfigQuarantine(
        rule="wp025-enc-nonstd-pagesize",
        predicate=lambda c: bool(c.get("encryption")) and c.get("page_size") != 4096,
        reason="encryption=1 with page_size!=4096 aborts tursodb "
               "(assert 'Page data must be exactly 4096 bytes', encryption.rs:742); "
               "the abort truncates the program and masks every later oracle",
        reference="WP-025 / turso #7610",
        canary_rate=0.05,   # ~5% of would-be-quarantined draws kept, to keep the panic matcher alive
    ),
)


def match_config_quarantine(config: dict) -> Optional[ConfigQuarantine]:
    """Return the first quarantine whose predicate matches this config, else None."""
    for q in CONFIG_QUARANTINES:
        if q.predicate(config):
            return q
    return None


# Known-integrity-signature allowlist (calibration lever 1b) -- the confirmed WP-024 FTS
# integrity message. The integrity oracle CONTINUES the case on a match (emitting a SUPPRESSED
# line) AND keeps checking every OTHER integrity message: a non-matching integrity failure
# still reds. Left un-allowlisted, the WP-024 signature fired on essentially every FTS-bearing
# program (calibration: 84/150) and drowned out attach/pager integrity failures (WP-008 lives
# there). The allowlist is DATA (signature regex + finding ref); suppression is always emitted.
@dataclass(frozen=True)
class IntegritySignature:
    rule: str            # short id emitted in the SUPPRESSED line
    pattern: str         # regex tested against an integrity_check message line
    reason: str
    reference: str


KNOWN_INTEGRITY_SIGNATURES: tuple[IntegritySignature, ...] = (
    IntegritySignature(
        rule="known-fts-integrity",
        # The confirmed WP-024 message: integrity_check reports a wrong entry count for the
        # internal FTS directory index. The index name varies per table, so match the stable
        # prefix, not a pinned name.
        pattern=r"wrong # of entries in index __turso_internal_fts",
        reason="confirmed FTS-index integrity_check miscount after valid FTS inserts",
        reference="WP-024 / turso #7611",
    ),
)


def match_integrity_signature(message: str) -> Optional[IntegritySignature]:
    for s in KNOWN_INTEGRITY_SIGNATURES:
        if re.search(s.pattern, message):
            return s
    return None


# Boundary literal pool -- the values scalar functions and DML are stressed over.
# Declared once, as data, so an auditor sees the boundary space is swept.
BOUNDARY_VALUES: tuple[Any, ...] = (
    None,
    0,
    1,
    -1,
    9223372036854775807,      # INT64 max
    -9223372036854775808,     # INT64 min
    9223372036854775808,      # overflows INT64 -> real/text in engines
    0.0,
    -0.0,
    3.14159265358979,
    1e308,
    "",
    "0",
    "12abc",                  # numeric-prefix string
    "3.9suffix",
    "  7  ",                  # whitespace-padded numeric
    "abc",
    "O'Brien",                # embedded quote
    "åß☃",   # unicode: aa, sharp-s, snowman
    "\U0001f600",             # astral emoji
    "tab\tsep",               # embedded tab (round-trips through `-m list`)
    b"ABC\x01Z",              # blob with a control byte -> exercises blob affinity, byte-faithful
    "zeroblob:5",             # sentinel expanded to zeroblob(5) by renderer
)
# NOTE: embedded-newline literals are deliberately NOT in the pool. tursodb's `-m list`
# output is line-oriented, so a newline inside a projected value is indistinguishable
# from a row boundary on stdout -- a transport ambiguity, not a product divergence. Such
# values are still exercised through DML/storage paths (they round-trip via the DB, not
# via stdout parsing); only bare scalar projection of a newline would be unparseable.
# NOTE : the blob pool value is a control-byte blob whose bytes are all valid UTF-8
# (`ABC\x01Z`), NOT a non-UTF8 blob like `x'0001ff'`. tursodb's `-m list` renders a BLOB as
# text with LOSSY U+FFFD replacement of non-UTF8 bytes, so a NON-UTF8 blob bare-projected
# through a scalar/aggregate (coalesce(blob), max(blob), a CTE `max(x)`) is transport-ambiguous
# for the SAME reason as an embedded newline -- two distinct non-UTF8 bytes both print as U+FFFD,
# an irrecoverable stdout loss, not a product divergence. A clean-UTF8 blob still stores as a
# BLOB (exercises blob affinity, storage, durability) and reads back byte-faithfully through
# bare projection (control bytes hex-encode symmetrically on both sides), so blob VALUES are
# still compared exactly.
# Known trade-off (reviewer note): non-UTF8 BLOB STORAGE coverage is lost from the shared
# pool. A storage-only reintroduction is NOT sound as-is: a non-UTF8 blob stored by DML leaks
# to bare projection through `max(col)` / agg-over-join / the CTE `max(x)` over the same
# tables, and quote()-wrapping those aggregates would strip _RealText provenance and turn
# tursodb's 17-digit REAL rendering into false reds. Reintroducing it needs a transport-safe
# aggregate projection design first -- recorded as follow-up, not silently dropped.

# Identifier styles for DDL -- a GENERIC sweep of the SQLite identifier-quoting grammar
# (calibration lever 2). Every DDL object (tables, columns, indexes, views, triggers) draws a
# style from this pool, so the generator exercises the whole quoting surface rather than one
# safe style. WP-005 (quoted trigger schema-reload mismatch) is ONE inhabitant of this family,
# not a pinned constant -- the axis sweeps bare / "double-quoted" / [bracketed] / `backticked` /
# mixed-CASE / reserved-adjacent / space- and dot-containing quoted names, and the durability
# read-back tail (lever 3) re-projects every object AFTER a reopen so the schema-reload path is
# the comparison point. `render_identifier` maps each style to valid SQL both engines parse.
#   plain        -- bare lowercase identifier (no quoting)
#   quoted       -- "double-quoted" (SQL-standard delimited identifier)
#   bracketed    -- [bracketed] (SQLite/T-SQL delimited identifier)
#   backticked   -- `backticked` (MySQL-compat delimited identifier SQLite also accepts)
#   keywordish   -- a reserved-word-adjacent name, double-quoted so it stays legal
#   mixedcase    -- MixedCase bare identifier (case-folding / case-preservation on reload)
#   unicode      -- non-ASCII delimited identifier ("...é☃")
#   spaced       -- a space-containing delimited identifier ("... col")
#   dotted       -- a dot-containing delimited identifier ("a.b") -- the quoted-dot name that
#                   must NOT be parsed as schema.table (a classic quoting-reload hazard)
IDENTIFIER_STYLES: tuple[str, ...] = (
    "plain", "quoted", "bracketed", "backticked", "keywordish",
    "mixedcase", "unicode", "spaced", "dotted",
)

# Scalar functions shared by SQLite and Turso, called over the boundary pool.
SCALAR_FUNCS: tuple[str, ...] = (
    "length", "hex", "quote", "typeof", "abs", "upper", "lower", "trim",
    "unicode", "round", "substr2", "coalesce2",
)

# Aggregate functions for QUERY ops (incl. empty-group / ungrouped-over-join).
AGG_FUNCS: tuple[str, ...] = ("count", "sum", "total", "avg", "min", "max", "group_concat")

# Join styles -- LEFT/outer is what makes empty-aggregate-over-join null rows appear.
JOIN_STYLES: tuple[str, ...] = ("inner", "left", "cross")

OP_FAMILIES: tuple[str, ...] = ("DDL", "DML", "QUERY", "LIFECYCLE", "EXPECT_ERROR")

# Per-table POPULATION MODES (calibration lever 1) -- a generic data-population axis so tables
# do NOT all end up populated the same way. Drawn per base table at DDL time. `empty` leaves
# the table with no rows; `all_null` inserts rows whose columns are ALL NULL; `populated`
# is the ordinary boundary-value fill. Making some tables empty and some all-NULL is what
# makes degenerate outer-join groups and all-NULL aggregate inputs appear BY DESIGN (the
# WP-002 empty/null-group shape) rather than incidentally. Weighted as data, never pinned:
# populated dominates so the base surface stays realistic, but a meaningful minority are
# degenerate. Generic across any SQL engine.
POPULATION_MODES: tuple[tuple[str, int], ...] = (
    ("populated", 6),
    ("empty", 2),
    ("all_null", 2),
)


# ---------------------------------------------------------------------------
# Feature families (generic op-kind families) and their reference-comparability
# ---------------------------------------------------------------------------
#
# Beyond the base op families above, the generator sweeps GENERIC FEATURE FAMILIES:
# whole classes of SQL surface (full-text search, JSON table-valued functions,
# triggers, attached auxiliary databases). Each is declared here as DATA -- a family
# name -> descriptor -- so an auditor sees the generator exercises a feature CLASS, never
# a bug-specific constant. `ref_comparable` records whether the stdlib sqlite3 reference
# can express the family with the SAME syntax/semantics (so a differential row/error
# comparison is meaningful). Where it cannot, the family's ops still run through every
# universal oracle (panic / integrity / terminal / reopen / error-class self-consistency).
#
# `weight` biases how often the family is chosen among feature ops (kept modest so the
# base op mix still dominates); `enabled_default` lets a product adapter's config gate a
# family. These are generic knobs, not target tuples.
@dataclass(frozen=True)
class FeatureFamily:
    name: str
    ref_comparable: bool
    weight: int
    # calibration lever 1c -- FEATURE-FAMILY SUBSET MASK. Each program draws an independent
    # per-family inclusion decision from a seed-derived rng: the family is included in that
    # program with probability `include_prob`, else it is masked OUT entirely (no ops of that
    # family are generated, and the coverage guarantee does not force it in). This is what
    # makes a real fraction of programs contain NO FTS at all -- which UNMASKS the universal
    # integrity oracle for attach/pager corruption (WP-008), since the confirmed WP-024 FTS
    # signature no longer fires on every program's integrity tail and drown out other integrity
    # failures. Generic: an independent Bernoulli inclusion per family, probability declared as
    # data. FTS gets the lowest inclusion so FTS-free programs are common; the comparable
    # families stay high so their differentials still run most of the time.
    include_prob: float = 1.0


FEATURE_FAMILIES: tuple[FeatureFamily, ...] = (
    # FTS: Turso spells virtual full-text as `CREATE INDEX ... USING fts(cols)` plus the
    # `fts_match(cols, term)` / `col MATCH term` predicate. The reference (sqlite3) only
    # has fts5's `CREATE VIRTUAL TABLE ... USING fts5` + `MATCH` -- different DDL and no
    # `fts_match` scalar -- so it is NOT reference-comparable; universal oracles only.
    # include_prob=0.5: HALF of programs are FTS-free, so the WP-024 integrity signature does
    # not blanket every program and mask non-FTS (attach/pager) integrity failures (WP-008).
    FeatureFamily("fts", ref_comparable=False, weight=2, include_prob=0.5),
    # JSON TVF: json_each / json_tree as table-valued functions in joins / correlated
    # subqueries / CTE reuse. Python's sqlite3 ships JSON1 with identical syntax, so this
    # family IS reference-comparable (full differential). Kept common (comparable + WP-023).
    FeatureFamily("json_tvf", ref_comparable=True, weight=2, include_prob=0.85),
    # Triggers exercised THROUGH a reopen boundary (create trigger, reopen db, then fire
    # it) with the shared identifier-style pool. Both engines have triggers -> comparable.
    FeatureFamily("trigger", ref_comparable=True, weight=1, include_prob=0.85),
    # Attached auxiliary databases: ATTACH + DDL/DROP in aux + checkpoint/reopen. Standard
    # SQL both engines share -> comparable (row set + accept/reject). Kept high: WP-008 lives
    # here and its integrity failure is only visible when FTS is NOT masking the tail.
    FeatureFamily("attach", ref_comparable=True, weight=1, include_prob=0.85),
    # Scalar-function boundary persisted read-back (calibration lever 3): persist scalar results
    # over swept boundary values, reopen, read back -- WP-015 lives here. Fully comparable.
    FeatureFamily("scalar_persist", ref_comparable=True, weight=2, include_prob=0.85),
    # calibration -- AGGREGATE-OVER-JOIN across populated / empty / all-NULL tables, with the
    # PLAN-STATE (ANALYZE) axis so both fresh and statistics-perturbed plans are exercised. The
    # empty-inner aggregate-over-join returns a single null-row group (COUNT=0, other cols NULL);
    # a divergent engine panics on the null-row cursor path (WP-002). Fully reference-comparable.
    FeatureFamily("agg_join", ref_comparable=True, weight=2, include_prob=0.85),
)

FEATURE_FAMILY_NAMES: tuple[str, ...] = tuple(f.name for f in FEATURE_FAMILIES)
_FEATURE_BY_NAME: dict[str, FeatureFamily] = {f.name: f for f in FEATURE_FAMILIES}

# FTS tokenizers Turso accepts (generic sweep of the tokenizer grammar, not one value).
FTS_TOKENIZERS: tuple[str, ...] = ("default", "raw", "ngram")

# JSON document shapes fed to json_each/json_tree -- a generic pool of nesting/quoting
# shapes, not a single crafted payload. Deep objects, arrays, quoted keys, primitives,
# empties: the shape space the TVF cursor must reset across on re-entry.
JSON_SHAPES: tuple[str, ...] = (
    '{"a":{"b":1,"c":[2,{"target":"needle"}]},"items":[{"name":"one","v":10}],"z":"last"}',
    '{"items":[{"name":"flat","v":30}],"a":"b","c":"d"}',
    '{"items":[{"name":"array0"},{"nested":{"target":"needle"}},[7,8]],"meta":{"ok":true}}',
    # Docs carrying dotted / spaced / unicode keys so the swept path-pool segments (dotted,
    # spaced, unicode) actually RESOLVE to root rows -- the WP-023 quoted-two-arg-path shape.
    '{"a.b":{"space key":9,"arr":[{"b":11},{"target":"needle"}]},"items":[]}',
    '{"x.y":{"nested":1},"café":{"v":2},"arr":[10,20,30],"items":[{"v":3}]}',
    '{"a b c":{"k":1},"ключ":[1,2],"a":{"b":{"c":9}},"items":[{"v":4}]}',
    '{"scalar":42,"items":[1,2,3],"tail":{"b":12}}',
    '{"items":[],"empty":{},"a":{"c":[]},"target":"top"}',
)

# ---------------------------------------------------------------------------
# NEW generic axis  -- JSON PATH-ARGUMENT POOL
# ---------------------------------------------------------------------------
#
# The second argument to json_tree/json_each is a PATH. This axis sweeps that path over a
# generic component grammar so the whole path surface is exercised, NOT one crafted literal.
# It is a database-argument family available to ALL strata (tvf-dense makes it dense, but any
# program that emits a TVF draws its path from here). Anti-telegraphing: every path is BUILT
# from generic components (a plain key, a quoted key, a dotted key, a spaced key, an array
# index, root vs deep) -- there is NO hardcoded `$."a.b"` literal. A quoted-dot path emerges
# because "dotted key" is one of the generic key kinds crossed with "quote this segment",
# exactly as a quoted key with spaces or unicode would; the generator sweeps the class.
#
# PATH_KEY_KINDS are the per-segment key kinds; a path is 0..N segments deep, each segment
# either an object key (one of these kinds) or an array index. `render_json_path` assembles a
# valid SQLite/JSON path string from a drawn segment plan. The coverage probe locks that a
# floor of DISTINCT paths and every key kind are reached.
PATH_KEY_KINDS: tuple[str, ...] = (
    "plain",     # a bare object key:  .items
    "quoted",    # a quoted object key: ."k"      (quoted but no special chars)
    "dotted",    # a quoted key CONTAINING a dot:   ."a.b"   (must NOT split into two segments)
    "spaced",    # a quoted key containing a space: ."space key"
    "unicode",   # a quoted key containing non-ASCII: ."ключ"
    "index",     # an array index:  [0]  /  [2]
    "missing",   # a key that is absent from the doc (exercises the not-found path)
)
# Generic key-name components used to BUILD keys of each kind (no target-specific name pinned).
_PATH_PLAIN_KEYS: tuple[str, ...] = ("a", "b", "c", "items", "meta", "arr", "nested", "tail")
_PATH_DOT_SEGMENTS: tuple[tuple[str, str], ...] = (("a", "b"), ("x", "y"), ("k", "v"))
_PATH_SPACE_KEYS: tuple[str, ...] = ("space key", "two words", "a b c")
_PATH_UNICODE_KEYS: tuple[str, ...] = ("ключ", "café", "☃key")
_PATH_INDICES: tuple[int, ...] = (0, 1, 2)
_PATH_MISSING_KEYS: tuple[str, ...] = ("nope", "absent", "zzz")


def render_json_path(rng: random.Random) -> str:
    """Assemble a JSON path argument from the generic segment grammar. Depth 0 yields the root
    `$`; deeper paths chain object/array segments, each an independently drawn PATH_KEY_KIND.
    A quoted-dot segment (kind='dotted') produces the `$."a.b"` shape as a GENERATED case, not a
    pinned literal. Pure function of the passed rng, so the path is seed-stable."""
    depth = rng.randrange(4)  # 0..3 segments -> root, shallow, and deep paths all reachable
    parts = ["$"]
    for _ in range(depth):
        kind = PATH_KEY_KINDS[rng.randrange(len(PATH_KEY_KINDS))]
        if kind == "plain":
            parts.append("." + _PATH_PLAIN_KEYS[rng.randrange(len(_PATH_PLAIN_KEYS))])
        elif kind == "quoted":
            parts.append('."' + _PATH_PLAIN_KEYS[rng.randrange(len(_PATH_PLAIN_KEYS))] + '"')
        elif kind == "dotted":
            a, b = _PATH_DOT_SEGMENTS[rng.randrange(len(_PATH_DOT_SEGMENTS))]
            parts.append('."' + a + "." + b + '"')   # a QUOTED dot: one segment, not schema split
        elif kind == "spaced":
            parts.append('."' + _PATH_SPACE_KEYS[rng.randrange(len(_PATH_SPACE_KEYS))] + '"')
        elif kind == "unicode":
            parts.append('."' + _PATH_UNICODE_KEYS[rng.randrange(len(_PATH_UNICODE_KEYS))] + '"')
        elif kind == "index":
            parts.append("[" + str(_PATH_INDICES[rng.randrange(len(_PATH_INDICES))]) + "]")
        else:  # missing
            parts.append("." + _PATH_MISSING_KEYS[rng.randrange(len(_PATH_MISSING_KEYS))])
    return "".join(parts)


def path_kinds_in(path: str) -> set[str]:
    """Classify which PATH_KEY_KINDS a rendered path exercises -- used by the coverage probe to
    assert the path pool is genuinely swept (every kind reached), without re-deriving the rng."""
    kinds: set[str] = set()
    # segment tokens: [n] indices, or ."..." / .plain object keys
    for m in re.finditer(r'\[\d+\]|\."(?:[^"]*)"|\.[A-Za-z_][A-Za-z0-9_]*', path):
        seg = m.group(0)
        if seg.startswith("["):
            kinds.add("index")
        elif seg.startswith('."'):
            inner = seg[2:-1]
            if "." in inner:
                kinds.add("dotted")
            elif " " in inner:
                kinds.add("spaced")
            elif any(ord(ch) > 127 for ch in inner):
                kinds.add("unicode")
            elif inner in _PATH_MISSING_KEYS:
                kinds.add("missing")
            else:
                kinds.add("quoted")
        else:
            key = seg[1:]
            kinds.add("missing" if key in _PATH_MISSING_KEYS else "plain")
    return kinds


# ---------------------------------------------------------------------------
# NEW generic axis  -- PLAN-STATE (ANALYZE) INJECTION
# ---------------------------------------------------------------------------
#
# `ANALYZE` populates the sqlite_stat tables and can tip the query planner onto a DIFFERENT
# plan for the SAME query. Some defects are plan-selection-sensitive (a zero-row aggregate-join
# path is only reached under a stats-perturbed plan). This axis injects ANALYZE at a swept POINT
# in the program so BOTH fresh (no-stats) and statistics-perturbed plans are exercised. Generic:
# a database-state family (run ANALYZE / not) available to ALL strata, driven by a swept enum,
# no target query pinned. `never` keeps the fresh-plan surface; the others perturb at different
# times so stats interact with different amounts of data.
PLAN_STATES: tuple[str, ...] = ("never", "early", "mid", "pre_query")


def render_analyze() -> str:
    return "ANALYZE;"


# ---------------------------------------------------------------------------
# Program model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Op:
    family: str            # one of OP_FAMILIES
    kind: str              # sub-kind, e.g. "create_table", "select_join"
    sql: str               # rendered SQL statement (single statement)
    expect_error: bool = False
    # ref_comparable=False marks an op whose semantics the stdlib sqlite3 reference
    # CANNOT express identically (e.g. Turso `USING fts(...)` + `fts_match(...)`, which
    # has no fts5-syntax equivalent the reference would parse the same way). For such
    # ops the DIFFERENTIAL oracles (diff_rows / error_class) are skipped -- there is no
    # apples-to-apples reference row set or accept/reject to compare against -- but the
    # UNIVERSAL, product-independent oracles (panic, integrity, terminal_state, reopen,
    # and the error-class self-consistency variant) still bind. This is the "reference-
    # comparable?" flag the targets file requires, carried per-op so the logic stays
    # generic: a whole family (FTS) is declared non-comparable via its axis data, and
    # every op it emits inherits the flag; families whose syntax IS shared (JSON TVF,
    # triggers, ATTACH) stay fully differential.
    ref_comparable: bool = True


@dataclass(frozen=True)
class Program:
    seed: int
    config: dict[str, Any]
    ops: tuple[Op, ...]

    def signature(self) -> str:
        """A byte-stable textual rendering -- used by the determinism probe."""
        parts = [f"SEED {self.seed}"]
        for key in sorted(self.config):
            parts.append(f"CFG {key}={self.config[key]!r}")
        for i, op in enumerate(self.ops):
            parts.append(
                f"OP {i} {op.family} {op.kind} err={int(op.expect_error)} "
                f"refcmp={int(op.ref_comparable)} {op.sql}"
            )
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# SQL rendering helpers
# ---------------------------------------------------------------------------

def sql_quote_str(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


_AUX_PLACEHOLDER_RE = re.compile(r"@@AUX_DB:([A-Za-z0-9_]+)@@")


def _subst_aux_placeholders(sql: str, resolve: Callable[[str], str]) -> str:
    """Replace @@AUX_DB:<alias>@@ tokens with a runner-specific aux-db file path. The
    ATTACH family emits these placeholders so the generated Program stays runner-agnostic
    (the reference and candidate each attach THEIR OWN aux file); each runner substitutes
    its own path at execution time."""
    return _AUX_PLACEHOLDER_RE.sub(lambda m: resolve(m.group(1)), sql)


def render_literal(value: Any) -> str:
    """Render a boundary-pool value as a SQL literal (product-agnostic)."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value:
            return "NULL"  # NaN not representable as a literal
        return repr(value)
    if isinstance(value, bytes):
        return "x'" + value.hex() + "'"
    if isinstance(value, str):
        if value.startswith("zeroblob:"):
            n = value.split(":", 1)[1]
            return f"zeroblob({int(n)})"
        return sql_quote_str(value)
    return sql_quote_str(str(value))


_KEYWORDS = ("select", "table", "order", "group", "index", "where", "from")
# Reserved words used bare-adjacent by the keywordish style (double-quoted so legal).
_RESERVED_ADJ = ("order", "group", "index", "table", "where", "select", "having", "join")


def render_identifier(base: str, style: str) -> str:
    """Render a table/column identifier in the given style. Delimited styles are quoted so
    the SQL stays valid across engines; each engine must resolve the SAME quoted name to the
    SAME object after a schema reload (the WP-005 quoting-reload contract). Generic: a style
    pool swept as data, no target-specific identifier pinned."""
    if style == "plain":
        return base
    if style == "mixedcase":
        # Bare identifier with mixed case -- exercises case-folding on reload (SQLite folds
        # unquoted identifiers to a case-insensitive match; both engines must agree).
        return base[:1].upper() + base[1:] + "X"
    if style == "quoted":
        return '"' + base + '"'
    if style == "bracketed":
        return "[" + base + "]"
    if style == "backticked":
        return "`" + base + "`"
    if style == "keywordish":
        kw = _RESERVED_ADJ[len(base) % len(_RESERVED_ADJ)]
        return '"' + kw + "_" + base + '"'
    if style == "unicode":
        return '"' + base + "_é☃" + '"'
    if style == "spaced":
        return '"' + base + " col" + '"'
    if style == "dotted":
        # A quoted DOT-containing name -- must be treated as one identifier, NOT schema.table.
        # The reload path is where an engine that mis-splits this diverges.
        return '"' + base + ".d" + '"'
    return base


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

# SUPPRESSED-line sink. Every quarantine/allowlist action appends one line here AND (when
# emit is on) prints it, so a sweep's stdout carries a visible, greppable audit trail of every
# known-class management action. A test can read the buffer without capturing stdout.
_SUPPRESSED_LOG: list[str] = []


def emit_suppressed(rule: str, detail: str, emit: bool = True) -> None:
    """Record (and optionally print) a `SUPPRESSED <rule> <detail>` line. This is the
    never-silent half of the quarantine contract: a known-class skip/downweight/allowlist is
    ALWAYS surfaced, never dropped."""
    line = f"SUPPRESSED {rule} {detail}"
    _SUPPRESSED_LOG.append(line)
    if emit:
        print(line, flush=True)


def choose_config(root: int, axes: dict[str, tuple], emit_suppress: bool = False) -> dict[str, Any]:
    """Pick one value per axis. Iterate axis names in sorted order so the result is
    independent of dict insertion order across processes.

    calibration lever 1a -- KNOWN-CRASH CONFIG QUARANTINE. After the raw draw, if the config falls
    in a declared known-crash family (CONFIG_QUARANTINES), it is kept only as a small canary
    fraction (canary_rate) -- otherwise it is RE-ROLLED to a non-quarantined config drawn from
    the same axes. The canary keep/drop and the re-roll are both seed-derived (a dedicated
    'config-quarantine' rng stream), so the whole decision stays a pure function of the seed
    and is byte-reproducible across processes. Every keep and every re-roll emits a SUPPRESSED
    line, so the quarantine is auditable. This is management of a CONFIRMED finding (WP-025),
    never suppression of an unknown one: the panic matcher still fires on the canary fraction."""
    rng = seeded_rng(root, "config")
    config: dict[str, Any] = {}
    for name in sorted(axes):
        values = axes[name]
        config[name] = values[rng.randrange(len(values))]

    q = match_config_quarantine(config)
    if q is not None:
        qrng = seeded_rng(root, "config-quarantine")
        if qrng.random() < q.canary_rate:
            # Keep as a canary -- the WP-025 panic matcher stays alive on this small fraction.
            emit_suppressed(
                q.rule,
                f"canary-kept config={_config_brief(config)} reason={q.reason!r} ref={q.reference}",
                emit_suppress,
            )
        else:
            # Re-roll to a NON-quarantined config so the rest of the program runs to the end
            # (unmasking the differential matchers). Bounded re-rolls; if every re-roll is
            # still quarantined (cannot happen with the current single predicate, but kept
            # generic), force page_size to the safe 4096 as a last resort.
            original = dict(config)
            for _ in range(8):
                for name in sorted(axes):
                    config[name] = axes[name][qrng.randrange(len(axes[name]))]
                if match_config_quarantine(config) is None:
                    break
            else:
                config["page_size"] = 4096
            emit_suppressed(
                q.rule,
                f"downweighted config={_config_brief(original)} -> {_config_brief(config)} "
                f"reason={q.reason!r} ref={q.reference}",
                emit_suppress,
            )
    return config


def _config_brief(config: dict) -> str:
    """A compact key config summary for SUPPRESSED lines (the axes that matter to quarantines)."""
    return f"enc={config.get('encryption')},ps={config.get('page_size')}"


def feature_mask(root: int, families: tuple[str, ...]) -> tuple[str, ...]:
    """calibration lever 1c -- per-program feature-family inclusion mask. Each enabled family is
    independently included with its declared `include_prob`, drawn from a seed-derived
    'feature-mask' rng so the mask is a pure function of the seed. Returns the subset of
    `families` included in THIS program; a masked-out family contributes no ops and is not
    forced in by the coverage guarantee. This is what makes a real fraction of programs
    FTS-free (unmasking the integrity oracle for non-FTS corruption, WP-008)."""
    rng = seeded_rng(root, "feature-mask")
    included: list[str] = []
    for name in families:
        fam = _FEATURE_BY_NAME.get(name)
        prob = fam.include_prob if fam is not None else 1.0
        # Draw for every family in declared order (stable) so the stream stays seed-stable
        # regardless of which are ultimately kept.
        if rng.random() < prob:
            included.append(name)
    return tuple(included)


def _pool_value(rng: random.Random) -> Any:
    return BOUNDARY_VALUES[rng.randrange(len(BOUNDARY_VALUES))]


# Text-safe subset of the boundary pool: values that render byte-identically across the CLI
# `-m list` transport (no raw-blob bytes, no float-format ambiguity, no NULL-vs-empty-string
# collision), so a differential on a value that passed through string concatenation is a real
# product divergence rather than a transport artifact. Used where a swept value flows through
# a TEXT path (trigger `||` concat, aux insert) whose stdout rendering must be unambiguous.
# DERIVED from BOUNDARY_VALUES (single source of truth) -- the plain `str` members that are not
# the zeroblob sentinel; adding a string edge to BOUNDARY_VALUES automatically widens this sweep.
_TEXT_BOUNDARY_VALUES: tuple[str, ...] = tuple(
    v for v in BOUNDARY_VALUES if isinstance(v, str) and not v.startswith("zeroblob:")
)


def _text_boundary(rng: random.Random) -> str:
    return _TEXT_BOUNDARY_VALUES[rng.randrange(len(_TEXT_BOUNDARY_VALUES))]


def _weighted_choice(rng: random.Random, pairs: tuple[tuple[Any, int], ...]) -> Any:
    """Pick one item from a (value, weight) table. Generic; used by the population-mode and
    other data-driven weighted axes so weights live in DATA, never as inline magic."""
    total = sum(w for _, w in pairs)
    r = rng.randrange(total)
    acc = 0
    for val, w in pairs:
        acc += w
        if r < acc:
            return val
    return pairs[-1][0]


def _gen_ddl(rng: random.Random, tables: list[dict]) -> list[Op]:
    """Create a table (varied identifier styles) plus sometimes an index/view."""
    ops: list[Op] = []
    idx = len(tables)
    style = IDENTIFIER_STYLES[rng.randrange(len(IDENTIFIER_STYLES))]
    tname = render_identifier(f"t{idx}", style)
    ncols = rng.randint(2, 4)
    cols = [render_identifier(f"c{j}", IDENTIFIER_STYLES[rng.randrange(len(IDENTIFIER_STYLES))]) for j in range(ncols)]
    coldefs = ", ".join(f"{c} {tp}" for c, tp in zip(cols, _col_types(rng, ncols)))
    ops.append(Op("DDL", "create_table", f"CREATE TABLE {tname}({coldefs});"))
    # Assign a generic population mode (calibration lever 1). _gen_dml reads it so an `empty`
    # table gets no rows and an `all_null` table gets all-NULL rows -- degenerate shapes
    # that make empty/all-null aggregate-over-join groups appear by design, not by luck.
    pop_mode = _weighted_choice(rng, POPULATION_MODES)
    tables.append({"name": tname, "cols": cols, "pop": pop_mode})
    # Optional secondary DDL over the just-created table.
    roll = rng.random()
    if roll < 0.4:
        iname = render_identifier(f"i{idx}", style)
        ops.append(Op("DDL", "create_index", f"CREATE INDEX {iname} ON {tname}({cols[0]});"))
    elif roll < 0.6:
        vname = render_identifier(f"v{idx}", style)
        ops.append(Op("DDL", "create_view", f"CREATE VIEW {vname} AS SELECT {cols[0]} FROM {tname};"))
    elif roll < 0.75:
        trg = render_identifier(f"trg{idx}", style)
        # AFTER INSERT trigger with a quoted-identifier body (WP-005 shape).
        ops.append(Op(
            "DDL", "create_trigger",
            f"CREATE TRIGGER {trg} AFTER INSERT ON {tname} BEGIN "
            f"UPDATE {tname} SET {cols[1]} = {cols[1]}; END;",
        ))
    return ops


def _col_types(rng: random.Random, n: int) -> list[str]:
    pool = ("INTEGER", "TEXT", "REAL", "BLOB", "")  # "" = no affinity
    return [pool[rng.randrange(len(pool))] for _ in range(n)]


def _gen_dml(rng: random.Random, tables: list[dict]) -> list[Op]:
    ops: list[Op] = []
    tbl = tables[rng.randrange(len(tables))]
    ncols = len(tbl["cols"])
    pop = tbl.get("pop", "populated")
    if pop == "empty":
        # Deliberately leave this table empty -- no rows inserted. An outer join against it
        # yields the degenerate empty-group shape (WP-002). Emit a real, aligned no-op that
        # both engines accept identically and that inserts nothing: a WHERE-guarded DELETE on
        # the still-empty table (deletes zero rows, zero result rows). A bare SQL comment is
        # NOT used -- the CLI's one-statement-per-process transport parses a comment-only op
        # inconsistently, drifting statement alignment; a real DELETE keeps ref/cand aligned.
        ops.append(Op("DML", "insert_skipped_empty",
                      f"DELETE FROM {tbl['name']} WHERE 1=0;"))
        return ops
    nrows = rng.randint(1, 4)
    tuples = []
    for _ in range(nrows):
        if pop == "all_null":
            # All-NULL row: every column NULL, so aggregates over this column see an all-null
            # input (min/max/avg -> NULL, count(col) -> 0) -- the all-null degenerate group.
            tuples.append("(" + ", ".join("NULL" for _ in range(ncols)) + ")")
        else:
            tuples.append("(" + ", ".join(render_literal(_pool_value(rng)) for _ in range(ncols)) + ")")
    ops.append(Op("DML", "insert", f"INSERT INTO {tbl['name']} VALUES {', '.join(tuples)};"))
    roll = rng.random()
    if roll < 0.3:
        col = tbl["cols"][0]
        ops.append(Op("DML", "update", f"UPDATE {tbl['name']} SET {col} = {render_literal(_pool_value(rng))};"))
    elif roll < 0.5:
        col = tbl["cols"][0]
        ops.append(Op("DML", "delete", f"DELETE FROM {tbl['name']} WHERE {col} = {render_literal(_pool_value(rng))};"))
    return ops


def _gen_query(rng: random.Random, tables: list[dict]) -> list[Op]:
    ops: list[Op] = []
    kind_roll = rng.random()
    if len(tables) >= 2 and kind_roll < 0.4:
        # Join, including LEFT/outer, with an aggregate over it (empty-group shape).
        a, b = rng.sample(range(len(tables)), 2)
        ta, tb = tables[a], tables[b]
        join = JOIN_STYLES[rng.randrange(len(JOIN_STYLES))]
        agg = AGG_FUNCS[rng.randrange(len(AGG_FUNCS))]
        acol = tb["cols"][0]
        join_clause = "" if join == "cross" else f" ON {ta['cols'][0]} = {tb['cols'][0]}"
        sql = (
            f"SELECT {_render_agg(agg, acol)} FROM {ta['name']} "
            f"{join.upper()} JOIN {tb['name']}{join_clause};"
        )
        ops.append(Op("QUERY", "agg_over_join", sql))
    elif kind_roll < 0.6:
        # Scalar-function call over a boundary value.
        fn = SCALAR_FUNCS[rng.randrange(len(SCALAR_FUNCS))]
        val = render_literal(_pool_value(rng))
        ops.append(Op("QUERY", "scalar_fn", f"SELECT {_render_scalar(fn, val)};"))
    elif kind_roll < 0.8:
        # CTE / subquery over a table.
        tbl = tables[rng.randrange(len(tables))]
        col = tbl["cols"][0]
        ops.append(Op(
            "QUERY", "cte_subquery",
            f"WITH cte AS (SELECT {col} AS x FROM {tbl['name']}) "
            f"SELECT count(*), (SELECT max(x) FROM cte) FROM cte;",
        ))
    else:
        # Ungrouped aggregate over a single table (empty-input shape when no rows).
        tbl = tables[rng.randrange(len(tables))]
        agg = AGG_FUNCS[rng.randrange(len(AGG_FUNCS))]
        ops.append(Op("QUERY", "agg_ungrouped", f"SELECT {_render_agg(agg, tbl['cols'][0])} FROM {tbl['name']};"))
    return ops


def _render_agg(agg: str, col: str) -> str:
    if agg == "group_concat":
        return f"group_concat({col})"
    if agg == "count":
        return f"count({col})"
    return f"{agg}({col})"


def _render_scalar(fn: str, val: str) -> str:
    if fn == "substr2":
        return f"substr({val}, 1, 2)"
    if fn == "coalesce2":
        return f"coalesce({val}, 'x')"
    if fn == "round":
        return f"round({val})"
    return f"{fn}({val})"


def _gen_lifecycle(rng: random.Random, plug: tuple[str, ...]) -> list[Op]:
    kinds = ("integrity_check", "reopen") + plug
    kind = kinds[rng.randrange(len(kinds))]
    if kind == "integrity_check":
        return [Op("LIFECYCLE", "integrity_check", "PRAGMA integrity_check;")]
    if kind == "reopen":
        return [Op("LIFECYCLE", "reopen", "-- reopen --")]  # handled by runner boundary
    # Product-pluggable lifecycle op (e.g. checkpoint); rendered as-is. A checkpoint PRAGMA
    # ECHOES a (busy, log, checkpointed) triple that legitimately differs across engines
    # (sqlite3 emits -1,-1 outside WAL; tursodb emits 0,0), so checkpoint echoes are marked
    # non-comparable -- a maintenance echo, not a query result under test. quick_check stays
    # comparable (it is a health oracle like integrity_check).
    comparable = "checkpoint" not in kind.lower()
    return [Op("LIFECYCLE", kind, kind, ref_comparable=comparable)]


def _gen_expect_error(rng: random.Random, tables: list[dict]) -> list[Op]:
    """Statements EXPECTED to error in BOTH engines -- drives error-class differential."""
    catalog = [
        ("syntax", "SELECT FROM;"),
        ("no_such_table", "SELECT * FROM __no_such_table_zzz__;"),
        ("no_such_func", "SELECT __no_such_func_zzz__(1);"),
        ("type_arity", "SELECT abs(1, 2, 3);"),
        ("bad_pragma_arg", "SELECT nonexistent_col FROM (SELECT 1) WHERE zzz_missing = 1;"),
    ]
    kind, sql = catalog[rng.randrange(len(catalog))]
    return [Op("EXPECT_ERROR", kind, sql, expect_error=True)]


# ---------------------------------------------------------------------------
# Feature-family generators (generic op-kind families)
# ---------------------------------------------------------------------------
#
# Each returns a self-contained op sequence that creates its own base table (so it does
# not depend on the randomly-typed base tables) and exercises the family. FTS ops are
# tagged ref_comparable=False (the differential oracles skip them); the rest are fully
# comparable. Every family sweeps a generic sub-grammar (tokenizers, JSON shapes/paths,
# trigger identifier styles, attach DDL kinds) rather than pinning a target constant.

def _fresh_name(rng: random.Random, prefix: str) -> str:
    return f"{prefix}{rng.randrange(1_000_000)}"


def _gen_fts(rng: random.Random) -> list[Op]:
    """Turso full-text: CREATE INDEX ... USING fts(cols) [WITH (tokenizer=...)] + a
    populate + fts_match / MATCH query. NOT reference-comparable (fts5 syntax differs),
    so tagged ref_comparable=False -- universal oracles still bind (integrity is the
    WP-024 oracle: a valid FTS insert must leave integrity_check == ok)."""
    ops: list[Op] = []
    t = _fresh_name(rng, "fts_t")
    idx = _fresh_name(rng, "fts_i")
    ops.append(Op("DDL", "fts_create_table",
                  f"CREATE TABLE {t}(id INTEGER PRIMARY KEY, title TEXT, body TEXT);",
                  ref_comparable=False))
    tok = FTS_TOKENIZERS[rng.randrange(len(FTS_TOKENIZERS))]
    ncols = rng.choice((1, 2))
    cols = "title, body" if ncols == 2 else "title"
    with_clause = "" if tok == "default" else f" WITH (tokenizer = '{tok}')"
    ops.append(Op("DDL", "fts_create_index",
                  f"CREATE INDEX {idx} ON {t} USING fts({cols}){with_clause};",
                  ref_comparable=False))
    # Populate with a couple of rows drawn from the boundary/text pool (valid FTS inserts).
    terms = ("alpha search", "beta engine", "gamma full text", "delta note")
    n = rng.randint(1, 3)
    tuples = []
    for i in range(n):
        title = terms[rng.randrange(len(terms))]
        body = terms[rng.randrange(len(terms))]
        tuples.append(f"({i + 1}, {sql_quote_str(title)}, {sql_quote_str(body)})")
    ops.append(Op("DML", "fts_insert",
                  f"INSERT INTO {t}(id, title, body) VALUES {', '.join(tuples)};",
                  ref_comparable=False))
    # Query form: fts_match(cols, term) or the MATCH operator, over a swept term.
    term = terms[rng.randrange(len(terms))].split()[0]
    if rng.random() < 0.5:
        pred = f"fts_match({cols}, {sql_quote_str(term)})"
    else:
        pred = f"title MATCH {sql_quote_str(term)}"
    ops.append(Op("QUERY", "fts_query",
                  f"SELECT group_concat(id, ',') FROM (SELECT id FROM {t} WHERE {pred} ORDER BY id);",
                  ref_comparable=False))
    # WP-024 shape: after valid FTS ops, integrity_check must still report ok.
    ops.append(Op("LIFECYCLE", "fts_integrity", "PRAGMA integrity_check;", ref_comparable=False))
    return ops


def _gen_json_tvf(rng: random.Random, dense: bool = False) -> list[Op]:
    """JSON table-valued functions (json_each / json_tree) used in a JOIN, correlated
    subquery, or CTE reuse -- the re-entry shapes (WP-023). Reference-comparable: Python
    sqlite3 ships JSON1 with identical syntax.

    calibration: the stored path column and a NEW direct two-arg-path form both draw from the
    generic JSON PATH-ARGUMENT POOL (render_json_path) so the quoted/dotted/spaced/index path
    surface is swept -- the WP-023 quoted-two-arg-path shape is one GENERATED inhabitant. When
    `dense` (tvf-dense stratum), every call emits MULTIPLE re-entry forms AND the direct-path
    form, so a single program exercises correlated/join/CTE re-entry over swept paths heavily."""
    ops: list[Op] = []
    t = _fresh_name(rng, "jdoc")
    ops.append(Op("DDL", "json_create_table",
                  f"CREATE TABLE {t}(id INTEGER PRIMARY KEY, payload TEXT, root_path TEXT);"))
    n = rng.randint(2, 4)
    tuples = []
    for i in range(n):
        shape = JSON_SHAPES[rng.randrange(len(JSON_SHAPES))]
        path = render_json_path(rng)   # NEW: swept path-argument pool, not a static literal
        tuples.append(f"({i + 1}, {sql_quote_str(shape)}, {sql_quote_str(path)})")
    ops.append(Op("DML", "json_insert",
                  f"INSERT INTO {t}(id, payload, root_path) VALUES {', '.join(tuples)};"))

    def _emit_form(form: int) -> None:
        if form == 0:
            # JOIN over json_tree, per-row root path (resets cursor state across rows).
            sql = (
                f"SELECT d.id, jt.fullkey, jt.type FROM {t} AS d "
                f"JOIN json_tree(d.payload, d.root_path) AS jt "
                f"WHERE jt.type IN ('object','array','integer','text') "
                f"ORDER BY d.id, jt.fullkey, jt.type;"
            )
            kind = "json_join_tree"
        elif form == 1:
            # Correlated scalar subquery re-entering json_tree twice per outer row.
            sql = (
                f"SELECT d.id, COALESCE((SELECT jt.fullkey FROM json_tree(d.payload) AS jt "
                f"WHERE jt.type='text' ORDER BY jt.id LIMIT 1), '<none>') "
                f"FROM {t} AS d ORDER BY d.id;"
            )
            kind = "json_correlated_subquery"
        elif form == 2:
            # CTE built on json_tree, referenced twice (UNION ALL) -- cursor-leakage shape.
            sql = (
                f"WITH jt AS (SELECT d.id AS did, j.fullkey AS fk, j.type AS ty "
                f"FROM {t} AS d JOIN json_tree(d.payload) AS j) "
                f"SELECT 'leaf', did, fk FROM jt WHERE ty NOT IN ('object','array') "
                f"UNION ALL SELECT 'cont', did, fk FROM jt WHERE ty IN ('object','array') "
                f"ORDER BY did, fk;"
            )
            kind = "json_cte_reuse"
        else:
            # json_each outer feeding a nested json_tree (double TVF re-entry).
            sql = (
                f"SELECT d.id, e.key, t.fullkey, t.type FROM {t} AS d "
                f"JOIN json_each(d.payload, '$.items') AS e "
                f"JOIN json_tree(e.value) AS t "
                f"WHERE t.type NOT IN ('object','array') OR t.fullkey='$' "
                f"ORDER BY d.id, CAST(e.key AS INTEGER), t.id;"
            )
            kind = "json_each_then_tree"
        ops.append(Op("QUERY", kind, sql))

    if dense:
        # tvf-dense: exercise ALL four re-entry forms in one program.
        for form in range(4):
            _emit_form(form)
    else:
        _emit_form(rng.randrange(4))

    # NEW direct two-arg-path form (all strata): json_tree over a LITERAL doc + a SWEPT LITERAL
    # path, projecting the `path`/`fullkey` columns. This is the WP-023 surface -- a quoted/dotted
    # two-arg path whose per-row `path` column must match sqlite. The doc is drawn to carry the
    # kind of keys the path may reference; the path is a generated pool member (no pinned literal).
    doc = JSON_SHAPES[rng.randrange(len(JSON_SHAPES))]
    lit_path = render_json_path(rng)
    ops.append(Op(
        "QUERY", "json_two_arg_path",
        f"SELECT key, type, fullkey, path FROM json_tree({sql_quote_str(doc)}, "
        f"{sql_quote_str(lit_path)}) ORDER BY fullkey, path, key, type;",
    ))
    return ops


def _gen_trigger(rng: random.Random, dense: bool = False) -> list[Op]:
    """A trigger created with the shared identifier-style pool, then a reopen boundary,
    then a DML that FIRES it -- the create/reopen/use sequence (WP-005 shape). Fully
    reference-comparable (both engines have triggers with this syntax).

    calibration: between the trigger CREATE and the reopen/fire, an UNRELATED schema mutation
    (ALTER TABLE <other> DROP COLUMN / ADD COLUMN, or a DROP of an unrelated object) runs, so
    the schema is reloaded with the trigger's referenced (possibly quoted) table name having to
    re-resolve across a schema change -- the WP-005 reload precondition (a quoted trigger-target
    name that must NOT be mis-parsed after an unrelated DDL). Generic: an unrelated schema-change
    axis, no target name pinned. `dense` (trigger-dense stratum) fires the trigger MORE and adds
    a re-CREATE/re-fire cycle so trigger lifecycle churn is heavy in every program."""
    ops: list[Op] = []
    style = IDENTIFIER_STYLES[rng.randrange(len(IDENTIFIER_STYLES))]
    # In trigger-dense, force a DELIMITED (quoted) style on the target/trigger names so the
    # quoted-reload contract is exercised in every dense program; otherwise sweep the full pool.
    if dense:
        style = ("quoted", "spaced", "dotted", "bracketed", "backticked")[
            rng.randrange(5)]
    base = _fresh_name(rng, "trg")
    tgt = render_identifier(f"{base}_t", style)
    audit = render_identifier(f"{base}_a", style)
    trg = render_identifier(f"{base}_g", style)
    # An UNRELATED table that the intervening schema mutation touches (not the trigger target).
    other = render_identifier(f"{base}_o", IDENTIFIER_STYLES[rng.randrange(len(IDENTIFIER_STYLES))])
    ops.append(Op("DDL", "trigger_target_table",
                  f"CREATE TABLE {tgt}(id INTEGER PRIMARY KEY, a TEXT, b TEXT);"))
    ops.append(Op("DDL", "trigger_audit_table",
                  f"CREATE TABLE {audit}(msg TEXT);"))
    ops.append(Op("DDL", "trigger_unrelated_table",
                  f"CREATE TABLE {other}(id INTEGER PRIMARY KEY, x TEXT, z TEXT);"))
    ops.append(Op("DDL", "trigger_create",
                  f"CREATE TRIGGER {trg} AFTER INSERT ON {tgt} BEGIN "
                  f"INSERT INTO {audit} VALUES('fired:' || NEW.a || ':' || NEW.b); END;"))
    # UNRELATED schema mutation between CREATE and fire -- forces a schema reload where the
    # trigger's (quoted) target name must re-resolve (the WP-005 precondition). Swept over ONLY
    # tursodb-supported DDL so the mutation ACCEPTS on both engines (an unsupported DDL would
    # accept-mismatch and truncate the program before the fire, masking WP-005 -- calibration smoke
    # found ALTER DROP COLUMN and ALTER RENAME COLUMN are unsupported by the pin, near-misses
    # recorded separately). ADD COLUMN, an unrelated CREATE INDEX, and dropping the unrelated
    # table all reload the schema and are accepted. Generic: an unrelated schema-change axis.
    mut = ("add_col", "add_index", "drop_unrelated")[rng.randrange(3)]
    if mut == "add_col":
        ops.append(Op("DDL", "trigger_schema_mutate",
                      f"ALTER TABLE {other} ADD COLUMN w TEXT;"))
    elif mut == "add_index":
        oidx = render_identifier(f"{base}_oi", style)
        ops.append(Op("DDL", "trigger_schema_mutate",
                      f"CREATE INDEX {oidx} ON {other}(x);"))
    else:
        ops.append(Op("DDL", "trigger_schema_mutate",
                      f"DROP TABLE {other};"))
    # SAME-CONNECTION fire: fire the trigger IMMEDIATELY after the unrelated schema change, with NO
    # intervening reopen, so the trigger's quoted target must re-resolve against a schema cache that
    # was just mutated in-connection (the WP-005 stale-schema path -- the corpus repro fires without
    # a reopen). Then ALSO reopen and fire again (the cross-reopen reload path). Both are swept.
    same_conn_a = render_literal(_text_boundary(rng))
    same_conn_b = render_literal(_text_boundary(rng))
    ops.append(Op("DML", "trigger_fire_sameconn",
                  f"INSERT INTO {tgt}(id, a, b) VALUES (900, {same_conn_a}, {same_conn_b});"))
    ops.append(Op("QUERY", "trigger_audit_read",
                  f"SELECT msg FROM {audit} ORDER BY msg;"))
    # Reopen so the trigger is also exercised after a full schema reload (the WP-005 precondition).
    ops.append(Op("LIFECYCLE", "reopen", "-- reopen --"))
    # calibration lever 2 -- SWEEP the fired values from the boundary pool, and fire the trigger
    # MORE THAN ONCE, so the trigger side-effect (concatenation of boundary values through
    # NEW.a/NEW.b) is exercised over the whole input space rather than one constant tuple.
    # WP-005 is a trigger-behavior-after-reload divergence: it only surfaces if the values the
    # trigger body transforms actually vary. Text-only boundary values are used for a/b (they
    # feed || string concatenation, where a raw blob would render differently per transport --
    # a transport artifact, not a product divergence); the whole boundary pool would reintroduce
    # the render-noise calibration closed. Generic: a swept pool of literals, no target tuple.
    n_fires = rng.randint(3, 5) if dense else rng.randint(1, 3)
    for f in range(n_fires):
        a_val = render_literal(_text_boundary(rng))
        b_val = render_literal(_text_boundary(rng))
        ops.append(Op("DML", "trigger_fire",
                     f"INSERT INTO {tgt}(id, a, b) VALUES ({f + 1}, {a_val}, {b_val});"))
    # Read back BOTH the fired audit rows (the trigger side-effect, projecting the transformed
    # values) AND the target-table rows (persisted-value read-back of the swept inputs).
    ops.append(Op("QUERY", "trigger_audit_read",
                 f"SELECT msg FROM {audit} ORDER BY msg;"))
    ops.append(Op("QUERY", "trigger_target_read",
                 f"SELECT id, a, b FROM {tgt} ORDER BY id;"))
    if dense:
        # trigger-dense: DROP + re-CREATE the trigger, reopen, and re-fire so trigger lifecycle
        # (create/fire/reopen/re-create/re-fire) is heavily exercised over the reload boundary.
        ops.append(Op("DDL", "trigger_drop", f"DROP TRIGGER {trg};"))
        ops.append(Op("DDL", "trigger_recreate",
                      f"CREATE TRIGGER {trg} AFTER INSERT ON {tgt} BEGIN "
                      f"INSERT INTO {audit} VALUES('refired:' || NEW.a); END;"))
        ops.append(Op("LIFECYCLE", "reopen", "-- reopen --"))
        rn = rng.randint(1, 2)
        for f in range(rn):
            av = render_literal(_text_boundary(rng))
            ops.append(Op("DML", "trigger_fire",
                         f"INSERT INTO {tgt}(id, a, b) VALUES ({100 + f}, {av}, 'r');"))
        ops.append(Op("QUERY", "trigger_audit_read",
                     f"SELECT msg FROM {audit} ORDER BY msg;"))
    return ops


def _gen_attach(rng: random.Random, run_ctx: dict, dense: bool = False) -> list[Op]:
    """ATTACH an auxiliary db, do DDL/DROP inside it, checkpoint, reopen, then read back
    -- the attached-db page-lifecycle sequence (WP-008 shape). Reference-comparable
    (ATTACH is standard SQL). The aux path is resolved by the runner at exec time via a
    placeholder, since the reference and candidate use different run dirs.

    calibration: the sequence adds the WP-008 preconditions generically -- a same-named table in
    BOTH main and aux, an INDEX on the aux table, PAGE-CHURN inserts (enough rows to span
    multiple pages), then DROP the indexed aux table and run a SCHEMA-QUALIFIED
    `PRAGMA aux.integrity_check` (the attached-db page free/reclaim corruption surface). `dense`
    (attach-dense stratum) makes every program run this FULL lifecycle with MORE aux tables and
    heavier churn. Generic: standard SQL, no target names pinned (fresh names each time)."""
    ops: list[Op] = []
    alias = _fresh_name(rng, "aux")
    # AUX_DB placeholder is substituted by each runner with its own aux file path, so the
    # generated program stays runner-independent (data), and the two engines each attach
    # THEIR OWN aux file -- the differential is on behavior, not on the shared path.
    ops.append(Op("LIFECYCLE", "attach", f"ATTACH '@@AUX_DB:{alias}@@' AS {alias};"))
    # calibration lever 4 -- ATTACH LIFECYCLE COMPLETENESS. Create TWO aux tables so the full
    # page-lifecycle sequence (aux-DDL + DROP + checkpoint + reopen + read-back) ALWAYS runs
    # in one program: one table is DROPped (exercising the attached-db page free/reclaim path,
    # the WP-008 precondition) while the SURVIVOR is read back after the reopen. Aux inserts
    # sweep text-boundary values so persisted aux values vary. Generic: standard SQL.
    at_drop = _fresh_name(rng, "at")
    at_keep = _fresh_name(rng, "at")
    ops.append(Op("DDL", "attach_create",
                  f"CREATE TABLE {alias}.{at_drop}(id INTEGER PRIMARY KEY, x TEXT, v TEXT);"))
    ops.append(Op("DDL", "attach_create2",
                  f"CREATE TABLE {alias}.{at_keep}(id INTEGER PRIMARY KEY, v TEXT);"))
    # WP-008 precondition 1: a table of the SAME NAME in main and aux (name-collision across the
    # attach boundary is part of the reported page-lifecycle corruption shape). Generic: the
    # collision is with the aux drop-target's base name; no target-specific name pinned.
    same_base = at_drop
    ops.append(Op("DDL", "attach_main_samename",
                  f"CREATE TABLE {same_base}(id INTEGER PRIMARY KEY, x TEXT, v TEXT);"))
    # WP-008 precondition 2: an INDEX on the aux drop-target (schema-qualified INDEX name, bare
    # table -- the syntax both Python-sqlite3 reference and tursodb accept), and one on the main
    # same-named table, so the DROP must reclaim indexed pages.
    ops.append(Op("DDL", "attach_index_aux",
                  f"CREATE INDEX {alias}.idx_{at_drop}_x ON {at_drop}(x);"))
    ops.append(Op("DDL", "attach_index_main",
                  f"CREATE INDEX idx_main_{same_base}_x ON {same_base}(x);"))
    dv = render_literal(_text_boundary(rng))
    kv = render_literal(_text_boundary(rng))
    ops.append(Op("DML", "attach_insert2",
                  f"INSERT INTO {alias}.{at_keep}(id, v) VALUES (1, {kv}), (2, {dv});"))
    # WP-008 precondition 3: PAGE CHURN -- insert enough rows into the indexed aux table to span
    # multiple pages, so DROP TABLE has real page-free work (the corruption manifests on reclaim).
    n_churn = rng.randint(120, 260) if dense else rng.randint(60, 140)
    churn_rows = ", ".join(f"({i}, 'pad{i}', 'v{i}')" for i in range(1, n_churn + 1))
    ops.append(Op("DML", "attach_insert",
                  f"INSERT INTO {alias}.{at_drop}(id, x, v) VALUES {churn_rows};"))
    ops.append(Op("DML", "attach_insert_main",
                  f"INSERT INTO {same_base}(id, x, v) VALUES {churn_rows};"))
    # DROP the indexed, page-spanning aux table (the page free/reclaim trigger -- WP-008).
    ops.append(Op("DDL", "attach_drop", f"DROP TABLE {alias}.{at_drop};"))
    ops.append(Op("LIFECYCLE", "attach_checkpoint", "PRAGMA wal_checkpoint(TRUNCATE);", ref_comparable=False))
    ops.append(Op("LIFECYCLE", "reopen", "-- reopen --"))
    # After reopen the ATTACH is gone (reopen is a fresh connection); re-attach to read.
    ops.append(Op("LIFECYCLE", "attach", f"ATTACH '@@AUX_DB:{alias}@@' AS {alias};"))
    # Persisted-value read-back of the SURVIVING aux table (projects the swept values).
    ops.append(Op("QUERY", "attach_read",
                 f"SELECT id, v FROM {alias}.{at_keep} ORDER BY id;"))
    # SCHEMA-QUALIFIED aux integrity check -- the WP-008 oracle (tursodb reports a page ShortRead
    # / corruption after the indexed-aux DROP; the reference reports ok). Kind attach_integrity so
    # the integrity oracle captures it; an accept-mismatch (tursodb rc!=0) reds via error_class.
    ops.append(Op("LIFECYCLE", "attach_integrity", f"PRAGMA {alias}.integrity_check;"))
    # Also the whole-db integrity check.
    ops.append(Op("LIFECYCLE", "attach_integrity", "PRAGMA integrity_check;"))
    ops.append(Op("LIFECYCLE", "attach", f"DETACH {alias};"))
    return ops


# Scalar functions whose RESULT is persisted to the UNTYPED r_any column then read back BARE
# (calibration lever 3). A generic sweep of the scalar-function grammar over the boundary pool;
# WP-015 (zeroblob / numeric-prefix persisted-value divergence) is ONE inhabitant, not pinned.
# Rendered by `_render_scalar_persist` so each takes a swept boundary value as its argument.
# calibrationc/d transport rule: the r_any column is read BARE (REAL-provenance-safe, reconciles
# 17-vs-15-digit REAL splits). So this pool must NOT contain a scalar that renders a NUMERIC
# input as representation-dependent TEXT with NO REAL provenance -- specifically `quote` and
# `hex`, whose result over an overflow-int-turned-REAL is engine-specific text ('9.2233..758e18'
# vs '9.22..581e18') stored as a plain string that cannot reconcile (a cross-engine float-format
# difference, not a WP-015 value divergence). `quote`/`hex` still ARE exercised -- in the
# BLOBTEXT_SCALAR_FUNCS pool over text-only inputs, where their output is deterministic and read
# back via quote() transport-safely. abs/round/cast_real DO produce REALs but land in r_any as
# a genuine REAL cell (typeof=real), so they reconcile by provenance.
# NUMERIC-result scalars: result is a genuine INT/REAL (or fixed short text like typeof), so
# stored in r_any it reads back with type provenance and reconciles even for the overflow REAL
# (bare projection carries _RealText). These take the FULL boundary pool as argument -- this is
# where WP-015's overflow / numeric-prefix / boundary VALUES are persisted and compared.
SCALAR_PERSIST_NUMERIC_FUNCS: tuple[str, ...] = (
    "cast_int", "cast_real", "abs", "round2", "length", "typeof",
)
# TEXT-result scalars: result is a STRING with no REAL provenance, so it must be fed CLEAN TEXT
# only (a text-boundary value) -- otherwise stringifying the overflow REAL yields engine-specific
# digits that cannot reconcile (the calibrationd false red). Over clean text they are deterministic.
SCALAR_PERSIST_TEXT_FUNCS: tuple[str, ...] = (
    "cast_text", "substr3", "replace3", "upper", "trim",
)


def _render_scalar_persist(fn: str, val: str) -> str:
    """Render a scalar-function call over one boundary literal `val` -- the value whose
    persisted round-trip is under test. Generic grammar sweep, no target tuple."""
    if fn == "cast_int":
        return f"CAST({val} AS INTEGER)"
    if fn == "cast_real":
        return f"CAST({val} AS REAL)"
    if fn == "cast_text":
        return f"CAST({val} AS TEXT)"
    if fn == "round2":
        return f"round({val}, 2)"
    if fn == "substr3":
        return f"substr({val}, 1, 3)"
    if fn == "replace3":
        return f"replace({val}, 'a', 'Z')"
    return f"{fn}({val})"


# Explicit zeroblob sizes to cover the boundary sizes 0 / 1 / 4096 the census calls out.
ZEROBLOB_SIZES: tuple[int, ...] = (0, 1, 4096)


# calibration -- NUMERIC-PREFIX STRING PATTERN. A generic family of strings that BEGIN with a numeric
# token then carry a non-numeric suffix (e.g. an integer/real prefix + letters/space/punctuation).
# Feeding one of these to a size-expecting function like zeroblob() exercises the string->integer
# COERCION boundary (SQLite truncates at the numeric prefix; a divergent engine coerces to 0 or
# differently) -- the WP-015 surface. This is a PATTERN built from generic components, NOT a
# pinned literal: the numeric prefix, the suffix, and their join are all drawn/assembled here, so
# the anti-telegraphing rule holds (no hardcoded '3.9suffix'-style constant special-cased).
_NUMPREFIX_HEADS: tuple[str, ...] = ("0", "1", "2", "3", "7", "12", "42", "100", "3.9", "1.5", "0.5", "10e2")
_NUMPREFIX_TAILS: tuple[str, ...] = ("abc", "suffix", "px", " x", "-tail", "_k", "e!", " and more", "XYZ")


def _numeric_prefix_string(rng: random.Random) -> str:
    """Assemble a numeric-prefix string from a generic numeric head + a non-numeric tail. Pure
    function of the passed rng. Sometimes leading/trailing whitespace is added (another coercion
    edge). No pinned literal -- the pieces and their join are all swept."""
    head = _NUMPREFIX_HEADS[rng.randrange(len(_NUMPREFIX_HEADS))]
    tail = _NUMPREFIX_TAILS[rng.randrange(len(_NUMPREFIX_TAILS))]
    s = head + tail
    lead = rng.randrange(3)
    if lead == 1:
        s = "  " + s
    elif lead == 2:
        s = s + "  "
    return s


# Scalar functions whose result is a genuine BLOB or TEXT -- safe to read back via quote()
# without hitting the quote(REAL) digit-count divergence. Only these feed the r_blobtext column,
# and ONLY over text-only inputs (_text_boundary), so `quote`/`hex` render a deterministic,
# engine-identical string (quote/hex of clean text has no float-format ambiguity). This is where
# `quote`/`hex` ARE swept -- moved out of the bare r_any pool where a numeric input made them
# render engine-specific REAL text (the calibrationd smoke false red).
BLOBTEXT_SCALAR_FUNCS: tuple[str, ...] = ("hex", "quote", "cast_text", "upper", "lower", "trim")


def _gen_scalar_persist(rng: random.Random, dense: bool = False) -> list[Op]:
    """calibration lever 3 -- SCALAR-FUNCTION BOUNDARY PERSISTED READ-BACK. Build a table, INSERT
    rows whose columns are scalar-function calls over swept boundary values (incl. numeric-
    prefix strings, overflow ints, zeroblob sizes 0/1/4096), then REOPEN and read the stored
    values back. The differential is on the PERSISTED value after a reload -- exactly the
    WP-015 divergence a bare SELECT would miss because it never hits the on-disk path. Fully
    reference-comparable (both engines share these scalars). Generic: a swept scalar grammar
    over the boundary pool, no pinned constant.

    Transport discipline (calibrationb, smoke-surfaced): the scalar result goes in the UNTYPED
    column `r_any` and is read back BARE -- bare projection carries REAL provenance so the
    reference REAL gets `_RealText`-tagged and print-format splits (17-vs-15-digit) reconcile in
    _cells_equal (the r_any column reconciled cleanly in the guest smoke). A SEPARATE column
    `r_blobtext` holds only genuine BLOB/TEXT-producing scalars and is read back via quote()
    (transport-safe because those never render as a REAL). quote() is DELIBERATELY NOT applied
    to the general scalar column: quote(REAL) strips REAL provenance and prints tursodb's
    shortest-roundtrip at a different digit count than sqlite3 -- the exact false red calibration
    reverted in the durability tail. So no scalar REAL is ever projected through quote()."""
    ops: list[Op] = []
    t = _fresh_name(rng, "scal")
    ops.append(Op("DDL", "scalar_create_table",
                  f"CREATE TABLE {t}(id INTEGER PRIMARY KEY, fn TEXT, r_any, r_blobtext);"))
    n = rng.randint(5, 9) if dense else rng.randint(3, 6)
    rows = []
    for i in range(n):
        # r_any: a NUMERIC-result scalar over the FULL boundary pool (overflow/numeric-prefix/
        # boundary VALUES -- the WP-015 surface), read back bare (typed -> reconciles), OR a
        # TEXT-result scalar over CLEAN TEXT only (deterministic string, no float-format hazard).
        if rng.random() < 0.6:
            fn = SCALAR_PERSIST_NUMERIC_FUNCS[rng.randrange(len(SCALAR_PERSIST_NUMERIC_FUNCS))]
            val = render_literal(_pool_value(rng))
        else:
            fn = SCALAR_PERSIST_TEXT_FUNCS[rng.randrange(len(SCALAR_PERSIST_TEXT_FUNCS))]
            val = render_literal(_text_boundary(rng))
        expr = _render_scalar_persist(fn, val)
        # r_blobtext: only a genuine BLOB/TEXT scalar (quote()-safe), over a text-only value.
        btfn = BLOBTEXT_SCALAR_FUNCS[rng.randrange(len(BLOBTEXT_SCALAR_FUNCS))]
        btval = render_literal(_text_boundary(rng))  # text-only so the result stays TEXT/BLOB
        btexpr = _render_scalar_persist(btfn, btval)
        rows.append(f"({i + 1}, {sql_quote_str(fn)}, {expr}, {btexpr})")
    ops.append(Op("DML", "scalar_insert",
                  f"INSERT INTO {t}(id, fn, r_any, r_blobtext) VALUES {', '.join(rows)};"))
    # Also persist the explicit zeroblob boundary sizes (0/1/4096) the census names -- the
    # zeroblob itself is a genuine BLOB (quote()-safe) in r_blobtext; r_any gets its length.
    zsize = ZEROBLOB_SIZES[rng.randrange(len(ZEROBLOB_SIZES))]
    ops.append(Op("DML", "scalar_insert_zeroblob",
                  f"INSERT INTO {t}(id, fn, r_any, r_blobtext) VALUES "
                  f"({n + 1}, 'zeroblob_lit', length(zeroblob({zsize})), zeroblob({zsize}));"))
    # WP-015 surface: zeroblob over a NUMERIC-PREFIX STRING (string->integer size coercion). The
    # reference coerces the leading numeric token (SQLite truncates at the first non-numeric
    # char); a divergent engine coerces differently (empty blob). Both sides are transport-safe:
    # length() is an INT (bare), and the zeroblob itself is a genuine BLOB read back via quote().
    # The argument is a GENERATED numeric-prefix string (pattern), not a pinned literal.
    n_np = rng.randint(2, 4) if dense else 1
    for k in range(n_np):
        nps = _numeric_prefix_string(rng)
        lit = sql_quote_str(nps)
        ops.append(Op("DML", "scalar_insert_zeroblob_numprefix",
                      f"INSERT INTO {t}(id, fn, r_any, r_blobtext) VALUES "
                      f"({n + 2 + k}, 'zeroblob_numprefix', length(zeroblob({lit})), zeroblob({lit}));"))
    # Reopen forces the stored values through the on-disk persistence path (the reload boundary).
    ops.append(Op("LIFECYCLE", "reopen", "-- reopen --"))
    # Read the PERSISTED values back: r_any bare (+ typeof/length so a type- or value-level
    # persisted divergence surfaces), r_blobtext via quote() (genuine blob/text -> transport-safe).
    ops.append(Op("QUERY", "scalar_readback",
                 f"SELECT id, fn, typeof(r_any), length(r_any), r_any, quote(r_blobtext) "
                 f"FROM {t} ORDER BY id;"))
    return ops


def _gen_agg_join(rng: random.Random, dense: bool = False) -> list[Op]:
    """AGGREGATE-OVER-JOIN across populated / empty / all-NULL tables, with the PLAN-STATE
    (ANALYZE) axis . Builds a left/right pair with composite (bucket,id) indexes and a
    population mode per table (populated / empty / all_null), runs ANALYZE at a swept POINT
    (never / early / mid / pre_query) so both fresh and stats-perturbed plans are exercised, then
    an ungrouped aggregate over the join whose INNER selection is EMPTY (WHERE left.id < 0) -- the
    single null-row group (COUNT=0, other cols NULL). A divergent engine panics on the null-row
    cursor path (WP-002). All generic: population axis + plan-state axis, no target tuple pinned.
    `dense` (agg-join-dense stratum) makes every program run the full populated/empty/all-NULL
    matrix with multiple aggregate shapes and ANALYZE perturbation."""
    ops: list[Op] = []
    base = _fresh_name(rng, "aj")
    lft = f"{base}_l"
    rgt = f"{base}_r"
    # Population mode per side -- an empty or all-NULL inner is what makes the degenerate group.
    pop_l = _weighted_choice(rng, POPULATION_MODES)
    pop_r = _weighted_choice(rng, POPULATION_MODES)
    plan_state = PLAN_STATES[rng.randrange(len(PLAN_STATES))]
    ops.append(Op("DDL", "agg_join_create_l",
                  f"CREATE TABLE {lft}(id INTEGER PRIMARY KEY, bucket INT, label TEXT);"))
    ops.append(Op("DDL", "agg_join_create_r",
                  f"CREATE TABLE {rgt}(id INTEGER PRIMARY KEY, bucket INT, label TEXT, metric REAL);"))
    ops.append(Op("DDL", "agg_join_index_l",
                  f"CREATE INDEX idx_{lft}_bk ON {lft}(bucket, id);"))
    ops.append(Op("DDL", "agg_join_index_r",
                  f"CREATE INDEX idx_{rgt}_bk ON {rgt}(bucket, id);"))

    def _fill(tbl: str, pop: str, with_metric: bool) -> None:
        if pop == "empty":
            return
        nrows = rng.randint(24, 96)
        tuples = []
        for i in range(nrows):
            if pop == "all_null":
                tuples.append(f"({i}, NULL, NULL" + (", NULL)" if with_metric else ")"))
            else:
                bk = i % 12
                if with_metric:
                    tuples.append(f"({i}, {bk}, 'R{i}', {i * 1.5})")
                else:
                    tuples.append(f"({i}, {bk}, 'L{i}')")
        cols = "(id, bucket, label, metric)" if with_metric else "(id, bucket, label)"
        ops.append(Op("DML", "agg_join_fill",
                      f"INSERT INTO {tbl}{cols} VALUES {', '.join(tuples)};"))

    _fill(lft, pop_l, with_metric=False)
    _fill(rgt, pop_r, with_metric=True)

    # PLAN-STATE axis: run ANALYZE at the swept point. `early` analyzes right after the initial
    # fill; `mid` perturbs the distribution with an extra insert then analyzes; `pre_query`
    # analyzes immediately before the aggregate; `never` leaves the fresh (no-stats) plan.
    if plan_state == "early":
        ops.append(Op("LIFECYCLE", "analyze", render_analyze(), ref_comparable=False))
    if plan_state == "mid":
        # a small extra insert then ANALYZE, so stats see a perturbed distribution
        if pop_l != "empty":
            ops.append(Op("DML", "agg_join_fill",
                          f"INSERT INTO {lft}(id, bucket, label) VALUES (1000, 0, 'x'), (1001, 1, 'y');"))
        ops.append(Op("LIFECYCLE", "analyze", render_analyze(), ref_comparable=False))
    if plan_state == "pre_query":
        ops.append(Op("LIFECYCLE", "analyze", render_analyze(), ref_comparable=False))

    # Empty-inner aggregate-over-join: WHERE left.id < 0 selects zero left rows, so the join is
    # empty and the ungrouped aggregate returns a single null-row group.
    join = ("JOIN", "LEFT JOIN")[rng.randrange(2)]
    ops.append(Op("QUERY", "agg_join_empty_inner",
                  f"SELECT COUNT(*), {lft}.label, {rgt}.label, SUM({rgt}.metric) "
                  f"FROM {lft} {join} {rgt} ON {lft}.bucket = {rgt}.bucket "
                  f"WHERE {lft}.id < 0;"))
    if dense:
        # Additional aggregate shapes over the same (possibly empty/all-NULL) join.
        ops.append(Op("QUERY", "agg_join_grouped",
                      f"SELECT {lft}.bucket, COUNT(*), AVG({rgt}.metric), MAX({rgt}.label) "
                      f"FROM {lft} {join} {rgt} ON {lft}.bucket = {rgt}.bucket "
                      f"WHERE {lft}.id < 0 GROUP BY {lft}.bucket ORDER BY {lft}.bucket;"))
        ops.append(Op("QUERY", "agg_join_total",
                      f"SELECT TOTAL({rgt}.metric), MIN({rgt}.metric) "
                      f"FROM {lft} {join} {rgt} ON {lft}.bucket = {rgt}.bucket WHERE {rgt}.id < 0;"))
    return ops


def _gen_feature(rng: random.Random, families: tuple[str, ...], run_ctx: dict) -> list[Op]:
    """Pick one enabled feature family (weighted) and emit its op sequence."""
    enabled = [f for f in FEATURE_FAMILIES if f.name in families]
    if not enabled:
        return []
    weights = [f.weight for f in enabled]
    total = sum(weights)
    r = rng.randrange(total)
    acc = 0
    chosen = enabled[-1]
    for fam, w in zip(enabled, weights):
        acc += w
        if r < acc:
            chosen = fam
            break
    if chosen.name == "fts":
        return _gen_fts(rng)
    if chosen.name == "json_tvf":
        return _gen_json_tvf(rng)
    if chosen.name == "trigger":
        return _gen_trigger(rng)
    if chosen.name == "attach":
        return _gen_attach(rng, run_ctx)
    if chosen.name == "scalar_persist":
        return _gen_scalar_persist(rng)
    if chosen.name == "agg_join":
        return _gen_agg_join(rng)
    return []


# ---------------------------------------------------------------------------
# STRATUM axis  -- stratified family-dense sweeps
# ---------------------------------------------------------------------------
#
# The five outstanding differential matchers (WP-002/005/008/015/023) each need a DIFFERENT
# feature family's full precondition chain to be present in the SAME program. In a mixed-grammar
# sweep, any one family's chain appears only intermittently, so the JOINT probability that ALL of
# one family's preconditions co-occur is diluted -- the misses were a search-strategy problem, not
# a coverage problem (calibration proved all 5 defects PRESENT at the pin). A STRATUM makes ONE family
# DENSE in every program of a batch while EVERY OTHER axis (config, quoting, population, plan-state,
# path-pool, quarantines, allowlists, durability tail) keeps sweeping normally. So a stratum sweep
# concentrates search pressure on one family's precondition chain without narrowing anything else.
#
# The stratum is seed-derived by default (so a plain seeded sweep still stratifies deterministically
# and covers all strata across a batch), OR pinned by the GENFUZZ_STRATUM env/workload-arg (so a
# per-stratum sweep can drive one family dense). Strata are GENERIC family-level names -- NO bug
# constants. The dense family is guaranteed present AND generated in `dense=True` mode (its full
# lifecycle every program); all other families still appear at their normal mask rate.
STRATA: tuple[str, ...] = (
    "trigger-dense",         # trigger lifecycle heavy + quoting at full strength (WP-005 inhabits)
    "attach-dense",          # full attach page-lifecycle every program (WP-008 inhabits)
    "scalar-persist-dense",  # scalar-boundary persist over the pool every program (WP-015 inhabits)
    "tvf-dense",             # json_each/json_tree re-entry + path-pool every program (WP-023 inhabits)
    "agg-join-dense",        # aggregate-over-join + plan-state every program (WP-002 inhabits)
    "mixed",                 # no forced density -- the pre-calibration behaviour, kept for the null sweep
)
# Which feature family each stratum makes dense (generic mapping; the stratum name is the axis).
_STRATUM_DENSE_FAMILY: dict[str, str] = {
    "trigger-dense": "trigger",
    "attach-dense": "attach",
    "scalar-persist-dense": "scalar_persist",
    "tvf-dense": "json_tvf",
    "agg-join-dense": "agg_join",
}


def choose_stratum(root: int, override: Optional[str] = None) -> str:
    """Pick this program's stratum. `override` (from GENFUZZ_STRATUM / a workload arg) pins it;
    otherwise a seed-derived draw over STRATA (excluding 'mixed' so a seeded sweep concentrates
    on a real family, cycling through all five across a batch). Pure function of (root, override)."""
    if override:
        if override in STRATA:
            return override
        return "mixed"
    # Seed-derived: draw from the five DENSE strata so a plain seeded sweep stratifies across all
    # of them deterministically (mixed is only reached via an explicit override for the null sweep).
    dense_strata = tuple(s for s in STRATA if s != "mixed")
    rng = seeded_rng(root, "stratum")
    return dense_strata[rng.randrange(len(dense_strata))]


def _gen_dense_family(rng: random.Random, family: str, run_ctx: dict) -> list[Op]:
    """Emit ONE dense-mode op sequence for the stratum's family (its full precondition lifecycle)."""
    if family == "trigger":
        return _gen_trigger(rng, dense=True)
    if family == "attach":
        return _gen_attach(rng, run_ctx, dense=True)
    if family == "scalar_persist":
        return _gen_scalar_persist(rng, dense=True)
    if family == "json_tvf":
        return _gen_json_tvf(rng, dense=True)
    if family == "agg_join":
        return _gen_agg_join(rng, dense=True)
    return []


def generate(seed: int, axes: dict[str, tuple], lifecycle_plug: tuple[str, ...] = (),
             feature_families: tuple[str, ...] = FEATURE_FAMILY_NAMES,
             emit_suppress: bool = False, stratum: Optional[str] = None) -> Program:
    """Produce a Program fully determined by seed. axes is CORE_AXES merged with any
    product axes. lifecycle_plug adds product lifecycle op kinds (e.g. checkpoint).
    emit_suppress prints the config-quarantine SUPPRESSED lines (on during a real sweep).

    calibration stratum: `stratum` pins the family-density stratum (else GENFUZZ_STRATUM env, else a
    seed-derived draw over the five dense strata). The stratum's family is forced DENSE (full
    lifecycle) in EVERY program of the batch, while every other axis keeps sweeping normally."""
    root = seed  # seed is already a root int
    stratum_choice = choose_stratum(root, stratum or os.environ.get("GENFUZZ_STRATUM"))
    dense_family = _STRATUM_DENSE_FAMILY.get(stratum_choice)
    config = choose_config(root, axes, emit_suppress=emit_suppress)
    # calibration lever 1c -- restrict this program's feature families to the seed-derived inclusion
    # mask, so a real fraction of programs are FTS-free (unmasking non-FTS integrity failures).
    # The mask is a pure function of the seed; the coverage guarantee below only forces in
    # families that survived the mask, never a masked-out one.
    active_families = feature_mask(root, feature_families)
    # The stratum's dense family is ALWAYS active (never masked out) -- the whole point is that it
    # runs its full lifecycle in every program. Other families keep their normal mask inclusion.
    if dense_family and dense_family in feature_families and dense_family not in active_families:
        active_families = active_families + (dense_family,)
    rng = seeded_rng(root, "ops")
    tables: list[dict] = []
    ops: list[Op] = []

    # Always begin with pragmas realizing the swept config so the config is load-bearing.
    # These config-realizing PRAGMAs ECHO the resulting mode, and engines legitimately
    # differ on the echo (tursodb is WAL-only, so `PRAGMA journal_mode = <x>` echoes 'wal'
    # for every requested mode; sqlite3 echoes the requested mode). That echo is a config
    # realization, not a query result under test, so the config PRAGMAs are marked
    # ref_comparable=False -- they still execute and realize the config, but their echoed
    # row is not differentially compared. (Real WP-025-style panics under a given config
    # still surface via the universal panic/terminal oracles, which bind regardless.)
    ops.append(Op("LIFECYCLE", "pragma_page_size", f"PRAGMA page_size = {config['page_size']};", ref_comparable=False))
    ops.append(Op("LIFECYCLE", "pragma_journal", f"PRAGMA journal_mode = {config['journal_mode']};", ref_comparable=False))
    ops.append(Op("LIFECYCLE", "pragma_sync", f"PRAGMA synchronous = {config['synchronous']};", ref_comparable=False))
    ops.append(Op("LIFECYCLE", "pragma_fk", f"PRAGMA foreign_keys = {config['foreign_keys']};", ref_comparable=False))

    n_ddl = rng.randint(2, 3)
    for _ in range(n_ddl):
        ops.extend(_gen_ddl(rng, tables))

    run_ctx: dict = {}
    # Interleave DML / QUERY / LIFECYCLE / EXPECT_ERROR / FEATURE. Fixed count for stable
    # coverage. Feature ops (fts/json/trigger/attach) are drawn from the same interleave so
    # they compose with the base surface rather than living in a separate phase.
    # STRATUM DENSITY: emit the dense family's full lifecycle up-front so EVERY program in the
    # stratum exercises that family's precondition chain. One dense emission here plus the
    # feature-force-in below (which also emits dense for the stratum family) guarantees density.
    if dense_family:
        ops.extend(_gen_dense_family(rng, dense_family, run_ctx))

    n_body = rng.randint(8, 14)
    for _ in range(n_body):
        pick = rng.random()
        if pick < 0.28:
            ops.extend(_gen_dml(rng, tables))
        elif pick < 0.50:
            ops.extend(_gen_query(rng, tables))
        elif pick < 0.68:
            # Feature op. In a stratum, bias the draw toward the dense family so it is exercised
            # repeatedly (density), while still letting OTHER masked-in families appear (the other
            # axes keep sweeping). Non-dense families keep their normal non-dense generation.
            if dense_family and rng.random() < 0.6:
                ops.extend(_gen_dense_family(rng, dense_family, run_ctx))
            else:
                ops.extend(_gen_feature(rng, active_families, run_ctx))
        elif pick < 0.84:
            ops.extend(_gen_lifecycle(rng, lifecycle_plug))
        else:
            ops.extend(_gen_expect_error(rng, tables))

    # Guarantee at least one of each op family appears for coverage (append if missing).
    present = {op.family for op in ops}
    if "EXPECT_ERROR" not in present:
        ops.extend(_gen_expect_error(rng, tables))
    if "LIFECYCLE" not in present:
        ops.extend(_gen_lifecycle(rng, lifecycle_plug))
    # Guarantee at least one op from EACH enabled feature family so every declared feature
    # class is reachable (the coverage probe asserts this -- the anti-telegraphing rule
    # requires whole families be swept, not a single crafted case).
    present_kinds = {op.kind for op in ops}
    _feature_marker = {
        "fts": "fts_create_index",
        "json_tvf": "json_insert",
        "trigger": "trigger_create",
        "attach": "attach_create",
        "scalar_persist": "scalar_create_table",
        "agg_join": "agg_join_create_l",
    }
    # Force in ONLY families that survived this program's inclusion mask (active_families) --
    # a masked-out family (e.g. FTS in an FTS-free program) is deliberately absent and must NOT
    # be forced back in, or the mask would be a no-op and the integrity tail never unmask. The
    # stratum's dense family is emitted in DENSE mode so its full precondition chain is present.
    for fam in active_families:
        if fam in _FEATURE_BY_NAME and _feature_marker.get(fam) not in present_kinds:
            is_dense = (fam == dense_family)
            if fam == "fts":
                ops.extend(_gen_fts(rng))
            elif fam == "json_tvf":
                ops.extend(_gen_json_tvf(rng, dense=is_dense))
            elif fam == "trigger":
                ops.extend(_gen_trigger(rng, dense=is_dense))
            elif fam == "attach":
                ops.extend(_gen_attach(rng, run_ctx, dense=is_dense))
            elif fam == "scalar_persist":
                ops.extend(_gen_scalar_persist(rng, dense=is_dense))
            elif fam == "agg_join":
                ops.extend(_gen_agg_join(rng, dense=is_dense))
            present_kinds = {op.kind for op in ops}

    # calibration lever 3 -- GENERIC DURABILITY READ-BACK TAIL. Every program ends with a reopen
    # followed by a full-column value read-back of every surviving base table. This is the
    # persisted-value differential the census's WP-015 class needs: written boundary values
    # must survive a reopen and read back IDENTICALLY on both engines, projecting the actual
    # columns (not count(*)). It is entirely generic -- no product, no target value -- and
    # applies to any SQL engine: "anything written and 200-acked must be observable after a
    # reopen." The reopen forces the values through the on-disk persistence path (the reload
    # boundary), and projecting ALL columns (ORDER BY every column for a stable multiset) is
    # what catches a value-level divergence a count(*) would hide. Empty tables read back as
    # zero rows on both sides (still a valid, cheap differential). Feature-family tables
    # (fts_*/jdoc*/trg*/aux*/at*) are excluded -- their own generators own their read-backs.
    ops.append(Op("LIFECYCLE", "reopen", "-- reopen --"))
    for tbl in tables:
        # BARE column projection, deliberately NOT quote()-wrapped. Bare projection flows
        # through the normalization machinery with full type provenance: the reference cell
        # arrives as a typed Python value, so REALs get `_RealText`-tagged and print-format
        # splits (17-vs-15-digit, signed zero) reconcile in _cells_equal. quote() was tried
        # here (calibration guest smoke) and REVERTED: engines render quote(REAL) with different
        # digit counts (sqlite3 '9.223372036854775808e+18' vs tursodb '9.22337203685477581e+18'
        # for the SAME double), and quoted output is plain text with NO provenance -- a false
        # red the reconciler is forbidden to absorb. Bare projection is transport-sound
        # because the boundary pool contains no value whose bare stdout rendering is lossy
        # (see the blob NOTE above BOUNDARY_VALUES); ORDER BY the same columns for a stable
        # multiset.
        proj = ", ".join(tbl["cols"])
        ops.append(Op(
            "QUERY", "durability_readback",
            f"SELECT {proj} FROM {tbl['name']} ORDER BY {proj};",
        ))
    # Always end with an integrity check + terminal reopen probe.
    ops.append(Op("LIFECYCLE", "integrity_check", "PRAGMA integrity_check;"))

    return Program(seed=seed, config=config, ops=tuple(ops))


# ---------------------------------------------------------------------------
# Runner adapter interface
# ---------------------------------------------------------------------------

@dataclass
class StmtResult:
    sql: str
    rc: int                       # 0 ok, nonzero error
    rows: list[tuple]             # normalized rows (empty for non-SELECT)
    error: str                    # error text ("" if none)
    ref_comparable: bool = True   # False -> differential oracles skip this stmt (see Op)


@dataclass
class RunResult:
    stmts: list[StmtResult] = field(default_factory=list)
    crashed: bool = False         # panic/abort (not a clean SQL error)
    crash_text: str = ""
    reopened_ok: bool = True      # db reopenable after run
    integrity_ok: Optional[bool] = None  # last integrity_check verdict, if run
    page_size_readback: str = ""  # PRAGMA page_size read back post-run (config-realized proof)
    # Every non-"ok" line reported by ANY integrity_check/quick_check run during the program.
    # The integrity oracle consults the KNOWN_INTEGRITY_SIGNATURES allowlist against these
    # messages (calibration lever 1b): a known-signature line is SUPPRESSED (emitted) and the case
    # continues; any OTHER non-ok line still reds. Captured on the CANDIDATE side (the engine
    # under test); the reference never reports non-ok.
    integrity_messages: list[str] = field(default_factory=list)


class Runner:
    """Abstract adapter: execute an op sequence, collect rows/error/rc per statement,
    support a reopen boundary, and report crash/integrity. Product-independent."""

    name: str = "runner"
    # True when the runner returns untyped text (e.g. a CLI in list mode) and thus
    # cannot preserve SQLite type tags. Row comparison collapses type tags when set.
    text_only: bool = False

    def run(self, program: Program) -> RunResult:  # pragma: no cover - interface
        raise NotImplementedError


# ---- Normalization (shared, so both runners are compared apples-to-apples) ----

_REAL_TEXT_RE = re.compile(r"[+-]?(\d+\.\d*|\.\d+|\d+)([eE][+-]?\d+)?")


class _RealText(str):
    """A normalized cell that PROVABLY came from a REAL (float) column on the reference side.
    Only these carry the type provenance that licenses `%!.15g` float reconciliation against
    the candidate; a genuine TEXT cell that merely looks numeric (e.g. lower('0.10') -> TEXT
    '0.10') is a plain str and is compared byte-exactly, so a real text-format divergence
    ('0.1' vs '0.10') is NEVER masked. The candidate side is untyped CLI text, so provenance
    is anchored on the reference (typed Python) side -- reconciliation fires iff the REFERENCE
    cell is a known REAL and the candidate text parses as the same double at 15 sig-digits."""
    __slots__ = ()


def _parse_finite_float(cell: str) -> Optional[float]:
    """Parse a cell as a finite float IFF it is a decimal-number rendering (has a '.' or
    exponent -- so a bare integer '42' and non-numeric/hex text like '302E30' are rejected).
    Returns None otherwise. Used only for the candidate side of a REAL reconciliation."""
    t = cell.strip()
    if not _REAL_TEXT_RE.fullmatch(t):
        return None
    if "." not in t and "e" not in t and "E" not in t:
        return None  # bare integer -- compare exactly, never float-reconcile
    try:
        f = float(t)
    except (ValueError, OverflowError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def _cells_equal(a: str, b: str) -> bool:
    """Two normalized cells are equal if byte-identical, OR one side is a provably-REAL
    reference cell (`_RealText`) and the other parses as the SAME double to 15 significant
    digits (SQLite's own `%!.15g` float-print precision). Gating on `_RealText` provenance is
    what keeps this from masking a genuine TEXT-format divergence: reconciliation only fires
    when the reference cell truly came from a REAL column, so '0.1' vs '0.10' as genuine TEXT
    (neither a `_RealText`) stays a red. The 15-sig-digit tolerance only absorbs print-format
    noise (tursodb's 17-digit shortest-roundtrip vs the reference's rendering of the SAME
    double); a genuinely different double diverges within 15 sig-digits and still reds."""
    if a == b:
        return True
    a_real = isinstance(a, _RealText)
    b_real = isinstance(b, _RealText)
    if not (a_real or b_real):
        return False  # no REAL provenance on either side -> exact text compare already failed
    fa = float(a) if a_real else _parse_finite_float(a)
    fb = float(b) if b_real else _parse_finite_float(b)
    if fa is None or fb is None:
        return False
    # Signed-zero: IEEE -0.0 == 0.0, but engines differ on the sign GLYPH (sqlite3 keeps the
    # sign -> '-0.0'; tursodb `-m list` drops it -> '0.0'). Both agree the VALUE is zero, so
    # collapse the sign on zero. This cannot mask a real divergence: any nonzero double keeps
    # its sign, so only the zero-vs-zero sign-render noise is absorbed. Live trigger sites
    # : any BARE REAL projection of a stored -0.0 -- the durability read-back tail,
    # `max(col)` in agg_ungrouped/agg_over_join, the CTE `max(x)` subquery, scalar round() --
    # where the reference cell IS a Python float and gets `_RealText`-tagged.
    if fa == 0.0:
        fa = 0.0
    if fb == 0.0:
        fb = 0.0
    return ("%.15g" % fa) == ("%.15g" % fb)


def normalize_value(value: Any, cli_text: bool = False) -> str:
    """Map any cell to a canonical string so type-affinity/float-format noise does not
    masquerade as a differential. Ints and integral floats collapse to the same form.

    cli_text mode: when EITHER runner is a text-only CLI (`-m list` emits untyped text,
    so it cannot preserve the int-vs-text or blob-vs-text distinction), the REFERENCE
    side is rendered exactly the way the CLI renders values (NULL->"", int->str,
    blob->hex, text verbatim) and the CLI side (a _CliText marker) is passed through
    unchanged. Comparison is thus on the CLI's own text projection -- a property of the
    transport, not a product-behavior suppression. It applies symmetrically and never
    hides a value difference, only the type tag the transport physically cannot carry."""
    # CLI cells arrive already in the CLI's text projection; never re-guess their type.
    # Float-precision reconciliation is NOT done here (a context-free cell like the hex text
    # '302E30' from hex(0.0) must not be mis-parsed as 3.02e+32); it is done pairwise against
    # the matching reference cell in _rows_equal, where both sides being REAL is established.
    if isinstance(value, _CliText):
        return _canon_ieee_special(str.__str__(value))
    if value is None:
        return "" if cli_text else "\x00NULL"
    if isinstance(value, bool):
        return ("1" if value else "0") if cli_text else f"\x00INT:{int(value)}"
    if isinstance(value, int):
        return str(value) if cli_text else f"\x00INT:{value}"
    if isinstance(value, float):
        if value != value:
            return "nan" if cli_text else "\x00NAN"
        if value in (float("inf"), float("-inf")):
            # cli_text canonical is lowercase 'inf'/'-inf'; the candidate CLI glyph is folded
            # to the same by _canon_ieee_special (tursodb emits 'Inf', sqlite3/Python 'inf').
            return ("inf" if value > 0 else "-inf") if cli_text else f"\x00REAL:{value!r}"
        # cli_text: render the reference REAL at shortest-roundtrip (repr), KEEPING a
        # trailing ".0" on integral reals -- we NO LONGER collapse REAL 0.0 to "0" (that
        # collapse was the harness bug that fired reds #2/#3/#6: total(), round(zeroblob),
        # round(emoji) all yield REAL 0.0). Tag it `_RealText` so _cells_equal knows this cell
        # provably came from a REAL and may reconcile print-format splits (17-vs-15-digit,
        # 1e+308 vs 1.0e+308) against the candidate -- a genuine TEXT '0.10' gets no such tag.
        if cli_text:
            return _RealText(repr(value))
        if abs(value) < 1e15 and value == int(value):
            return f"\x00INT:{int(value)}"
        return f"\x00REAL:{value!r}"
    if isinstance(value, bytes):
        if not cli_text:
            return "\x00BLOB:" + value.hex()
        # cli_text: render the reference blob EXACTLY as `-m list` renders the candidate
        # blob, so the same blob is the same text on both sides. `-m list` prints a BLOB's
        # RAW bytes; on our side, _coerce_cli_cell hex-encodes any candidate cell carrying
        # raw (non-clean-UTF8) bytes. So mirror that here: if the blob's bytes are clean
        # printable UTF-8 text (e.g. x'414243' -> 'ABC'), the CLI prints that text verbatim
        # and we compare as text; otherwise the candidate cell became hex, so we hex too.
        try:
            decoded = value.decode("utf-8")
        except UnicodeDecodeError:
            return value.hex()
        return decoded if not _has_raw_bytes(decoded) else value.hex()
    # str
    if not cli_text:
        return "\x00TXT:" + str(value)
    s = str(value)
    # A reference TEXT cell can carry raw bytes -- NULs from a zeroblob concatenated into a
    # group_concat, or a U+FFFD from decode-replacing a non-UTF8 byte fed to upper()/trim().
    # `-m list` prints those bytes raw and the candidate cell was hex-encoded by
    # _coerce_cli_cell, so hex-encode the reference the SAME way to keep both sides canonical.
    if _has_raw_bytes(s):
        return s.encode("utf-8", "surrogateescape").hex()
    return s


def normalize_row(row: tuple, cli_text: bool = False) -> tuple:
    return tuple(normalize_value(v, cli_text) for v in row)


def normalize_rowset(rows: list[tuple], cli_text: bool = False) -> list[tuple]:
    """Multiset compare: sort normalized rows so row ORDER never triggers a false red
    (only ORDER BY queries would care, and those are compared as multisets too here)."""
    return sorted(normalize_row(r, cli_text) for r in rows)


def _rows_equal(rref: list[tuple], rcand: list[tuple]) -> bool:
    """Multiset equality of two normalized rowsets, cell-comparison being _cells_equal (so
    float print-format differences reconcile). Same length required; each ref row must be
    matched one-to-one to a cand row. Rowsets are small (query results), so an O(n*m) greedy
    match is fine. Falls back to exact list equality fast-path first."""
    if rref == rcand:
        return True
    if len(rref) != len(rcand):
        return False
    remaining = list(rcand)
    for rr in rref:
        for j, rc in enumerate(remaining):
            if len(rr) == len(rc) and all(_cells_equal(x, y) for x, y in zip(rr, rc)):
                remaining.pop(j)
                break
        else:
            return False
    return True


# ---- sqlite3 reference runner ----

class Sqlite3Runner(Runner):
    """Reference runner over stdlib sqlite3. Deterministic; used both as the oracle
    reference and (two independent instances) for the null-differential probe."""

    def __init__(self, run_dir: Path, tag: str = "sqlite3"):
        self.run_dir = run_dir
        self.name = tag

    @staticmethod
    def _connect(db_path: str, config: Optional[dict[str, Any]] = None) -> sqlite3.Connection:
        conn = sqlite3.connect(db_path, isolation_level=None)
        # Decode-tolerant text factory: some queries (e.g. group_concat over a column that
        # ended up holding non-UTF8 bytes) produce a result Python's default TEXT decoder
        # cannot decode, raising OperationalError -- a REFERENCE-SIDE fragility, not a Turso
        # defect. Replace undecodable bytes so the reference returns a value (comparable to
        # the CLI's own rendering) rather than spuriously "rejecting" a statement the CLI
        # accepts. Bytes that are valid UTF-8 decode unchanged, so normal text is unaffected.
        conn.text_factory = lambda b: b.decode("utf-8", "replace")
        # Realize the swept config once at open, symmetric with the CliRunner preamble. On the
        # reference the connection is reused, so applying config here (before the first write)
        # is what makes page_size bind; the others just set the mode. Idempotent on reopen
        # (page_size is a no-op once the db exists; journal/sync/fk re-set harmlessly).
        if config:
            for pragma in ("page_size", "journal_mode", "synchronous", "foreign_keys"):
                if pragma in config:
                    try:
                        conn.execute(f"PRAGMA {pragma} = {config[pragma]};").fetchall()
                    except sqlite3.Error:
                        pass
        return conn

    def _aux_path(self, seed: int, alias: str) -> str:
        return str(self.run_dir / f"{self.name}-{seed}-{alias}.auxdb")

    def _subst_aux(self, sql: str, seed: int) -> str:
        return _subst_aux_placeholders(sql, lambda alias: self._aux_path(seed, alias))

    def run(self, program: Program) -> RunResult:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        db_path = self.run_dir / f"{self.name}-{program.seed}.db"
        db_path.unlink(missing_ok=True)
        # Clear any aux db files from a prior run of this tag/seed so ATTACH starts clean.
        for aux in self.run_dir.glob(f"{self.name}-{program.seed}-*.auxdb"):
            aux.unlink(missing_ok=True)
        result = RunResult()
        conn = self._connect(str(db_path), program.config)
        try:
            for op in program.ops:
                if op.kind == "reopen":
                    conn.close()
                    conn = self._connect(str(db_path), program.config)
                    continue
                self._exec_one(conn, op, result, program.seed)
            # config-realized proof: read page_size back (recorded, not compared)
            try:
                pr = conn.execute("PRAGMA page_size;").fetchall()
                result.page_size_readback = str(pr[0][0]) if pr and pr[0] else ""
            except sqlite3.Error:
                pass
            # terminal reopen probe
            conn.close()
            try:
                conn = self._connect(str(db_path), program.config)
                conn.execute("PRAGMA integrity_check;").fetchall()
                result.reopened_ok = True
            except sqlite3.Error:
                result.reopened_ok = False
        finally:
            try:
                conn.close()
            except sqlite3.Error:
                pass
        return result

    def _exec_one(self, conn: sqlite3.Connection, op: Op, result: RunResult, seed: int) -> None:
        sql = self._subst_aux(op.sql, seed)
        try:
            cur = conn.execute(sql)
            rows = cur.fetchall() if cur.description is not None else []
            result.stmts.append(StmtResult(sql, 0, [tuple(r) for r in rows], "", op.ref_comparable))
            if op.kind in ("integrity_check", "fts_integrity", "attach_integrity"):
                result.integrity_ok = bool(rows) and str(rows[0][0]).lower() == "ok"
                # Record every non-"ok" line so the oracle can allowlist-classify each message.
                for r in rows:
                    msg = str(r[0]) if r else ""
                    if msg.lower() != "ok":
                        result.integrity_messages.append(msg)
        except sqlite3.Error as exc:
            result.stmts.append(StmtResult(sql, 1, [], f"{type(exc).__name__}: {exc}", op.ref_comparable))


# ---- CLI runner skeleton (tursodb) ----

# Strings in CLI stderr/stdout that mean a crash rather than a clean SQL rejection.
CRASH_MARKERS: tuple[str, ...] = (
    "panicked", "panic", "RUST_BACKTRACE", "assertion failed", "abort",
    "SIGSEGV", "SIGABRT", "core dumped", "internal error", "unreachable",
)


class CliRunner(Runner):
    """Thin subprocess adapter for a SQL CLI binary (tursodb). Not executable on macOS
    (linux binary), so it is constructed here and exercised via mocking in tests. The
    argv/parse logic is real so the guest run  can use it unchanged."""

    text_only = True

    def __init__(
        self,
        binary: Path,
        base_args: tuple[str, ...],
        run_dir: Path,
        tag: str = "tursodb",
        loader: Optional[Path] = None,
        loader_lib: Optional[Path] = None,
        timeout: int = 60,
        _spawn: Optional[Callable[[list[str], str], tuple[int, str, str]]] = None,
        encryption: int = 0,
        cipher: str = "",
        hexkey: str = "",
    ):
        self.binary = binary
        self.base_args = base_args
        self.run_dir = run_dir
        self.name = tag
        self.loader = loader
        self.loader_lib = loader_lib
        self.timeout = timeout
        # Encryption config swept by the product adapter. When encryption=1, the main db is
        # opened via the cipher URI `file:<db>?cipher=<c>&hexkey=<k>` (Turso's encryption
        # form, per turso_encryption_reopen_corruption_boundary). The reference stays
        # unencrypted -- encryption is candidate-side config, and the differential contract
        # is unchanged (the same rows must come back whether or not the file is encrypted).
        self.encryption = encryption
        self.cipher = cipher
        self.hexkey = hexkey
        # _spawn is injectable for tests; defaults to real subprocess.
        self._spawn = _spawn or self._subprocess_spawn

    def argv(self, db: str, script: str) -> list[str]:
        if self.loader and self.loader_lib:
            head = [str(self.loader), "--library-path", str(self.loader_lib), str(self.binary)]
        else:
            head = [str(self.binary)]
        return [*head, "-q", "-m", "list", *self.base_args, db, script]

    def _subprocess_spawn(self, argv: list[str], _script: str) -> tuple[int, str, str]:  # pragma: no cover
        # Capture as BYTES, then decode with surrogateescape so raw blob bytes that `-m list`
        # emits (non-UTF8, e.g. 0x00/0xff) survive into the string instead of being replaced
        # or raising. _coerce_cli_cell hex-encodes any cell carrying such bytes so it matches
        # the reference's `.hex()` rendering of the same blob. Clean UTF-8 text is unaffected.
        proc = subprocess.run(argv, capture_output=True, timeout=self.timeout, check=False)
        out = proc.stdout.decode("utf-8", "surrogateescape")
        err = proc.stderr.decode("utf-8", "surrogateescape")
        return proc.returncode, out, err

    def _aux_path(self, seed: int, alias: str) -> str:
        return str(self.run_dir / f"{self.name}-{seed}-{alias}.auxdb")

    def _subst_aux(self, sql: str, seed: int) -> str:
        return _subst_aux_placeholders(sql, lambda alias: self._aux_path(seed, alias))

    def _db_arg(self, db_path: str) -> str:
        """The db argument passed to tursodb. When encryption is swept on, wrap the path in
        the cipher URI so the candidate actually opens an encrypted database; otherwise the
        bare path (plaintext). This is what makes the page_size x encryption target (WP-025
        / turso #7610) actually reachable rather than merely printed in the config."""
        if self.encryption and self.cipher and self.hexkey:
            return f"file:{db_path}?cipher={self.cipher}&hexkey={self.hexkey}"
        return db_path

    @staticmethod
    def _config_preamble(config: dict[str, Any]) -> list[str]:
        """Config-realizing pragmas, prepended to EVERY CliRunner invocation.

        The transport is one-statement-per-process, so the process that first writes the db
        is the one that must carry `PRAGMA page_size` -- `page_size` only binds if it runs
        before the db file is created (SQLite/tursodb semantics). generate() ALSO emits these
        pragmas as one-time program ops, but on the CliRunner that per-op form cannot bind
        page_size: the op ran in its own write-less process and exited, and the CREATE that
        actually made the db ran later at the DEFAULT page size -- so the swept page_size x
        encryption combo (WP-025 / turso #7610) never bound. (Those program ops are NOT dead:
        on the persistent-connection reference they DO realize config, and on both engines
        they exercise the pragma statement path and anchor LIFECYCLE-family coverage; they are
        just insufficient for the CliRunner's split-process transport.) Prepending them to
        every statement here makes them load-bearing on whichever invocation first creates the
        db, and harmlessly idempotent thereafter (page_size is silently ignored once the db
        exists; the others just re-set the mode). Generic: driven entirely by the swept config
        dict, no target-specific tuple."""
        pre: list[str] = []
        if "page_size" in config:
            pre.append(f"PRAGMA page_size = {config['page_size']};")
        if "journal_mode" in config:
            pre.append(f"PRAGMA journal_mode = {config['journal_mode']};")
        if "synchronous" in config:
            pre.append(f"PRAGMA synchronous = {config['synchronous']};")
        if "foreign_keys" in config:
            pre.append(f"PRAGMA foreign_keys = {config['foreign_keys']};")
        return pre

    def run(self, program: Program) -> RunResult:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        db_plain = str(self.run_dir / f"{self.name}-{program.seed}.db")
        db_path = self._db_arg(db_plain)
        for aux in self.run_dir.glob(f"{self.name}-{program.seed}-*.auxdb"):
            aux.unlink(missing_ok=True)
        result = RunResult()
        # The CLI executes a whole script at once; we render statement-by-statement so
        # per-op rc/rows still line up. Reopen is a natural boundary (new process).
        #
        # ATTACH state is per-connection and each CLI statement is a fresh process, so an
        # ATTACH alias would not survive to the next statement. We therefore keep a small
        # active-attach preamble: after an accepted ATTACH we replay it ahead of every
        # subsequent statement (so `aux.tbl` resolves) until the matching DETACH or a
        # reopen clears it. This makes the one-statement-per-process transport faithfully
        # reproduce a persistent-connection ATTACH session -- generic, not target-specific.
        # Config-realizing pragmas, prepended to EVERY invocation (the write-less-process
        # flaw fix -- see _config_preamble). They echo (`journal_mode` prints the mode), so a
        # sentinel SELECT separates their output from the real statement's rows; everything
        # up to and including the sentinel line is discarded before parsing.
        config_preamble = self._config_preamble(program.config)
        attach_preamble: list[str] = []
        for op in program.ops:
            if op.kind == "reopen":
                attach_preamble = []  # a reopen drops all attaches (fresh connection)
                continue
            stmt_sql = self._subst_aux(op.sql, program.seed)
            if op.kind == "attach" and stmt_sql.strip().upper().startswith("DETACH"):
                # Execute the detach (with current preamble) then drop it from the preamble.
                rc, stdout, stderr = self._spawn_stmt(db_path, config_preamble, attach_preamble, stmt_sql)
                attach_preamble = [s for s in attach_preamble if not self._same_attach(s, op.sql)]
                combined = f"{stdout}\n{stderr}"
                if self._is_crash(rc, combined):
                    result.crashed = True
                    result.crash_text = combined[-500:]
                    result.stmts.append(StmtResult(stmt_sql, rc, [], combined[-300:], op.ref_comparable))
                    break
                result.stmts.append(StmtResult(stmt_sql, 0 if rc == 0 else 1, [], "" if rc == 0 else stderr.strip(), op.ref_comparable))
                continue
            rc, stdout, stderr = self._spawn_stmt(db_path, config_preamble, attach_preamble, stmt_sql)
            combined = f"{stdout}\n{stderr}"
            if self._is_crash(rc, combined):
                result.crashed = True
                result.crash_text = combined[-500:]
                result.stmts.append(StmtResult(stmt_sql, rc, [], combined[-300:], op.ref_comparable))
                break
            rows = self._parse_rows(stdout) if rc == 0 else []
            result.stmts.append(StmtResult(stmt_sql, 0 if rc == 0 else 1, rows, "" if rc == 0 else stderr.strip(), op.ref_comparable))
            if op.kind == "attach" and rc == 0 and stmt_sql.strip().upper().startswith("ATTACH"):
                attach_preamble.append(stmt_sql)
            if op.kind in ("integrity_check", "fts_integrity", "attach_integrity") and rc == 0:
                result.integrity_ok = any(r and str(r[0]).lower() == "ok" for r in rows)
                # Record every non-"ok" line for allowlist classification (calibration lever 1b).
                for r in rows:
                    msg = str(r[0]) if r else ""
                    if msg.lower() != "ok":
                        result.integrity_messages.append(msg)
        # verify_config: read page_size back after a run so a sweep can SEE the config took
        # effect (ref_comparable=False -- recorded, not differentially compared). This is the
        # cheap generic probe that the swept page_size actually bound under this config.
        rc, stdout, stderr = self._spawn_stmt(db_path, config_preamble, [], "PRAGMA page_size;")
        if rc == 0 and not self._is_crash(rc, f"{stdout}\n{stderr}"):
            prows = self._parse_rows(stdout)
            result.page_size_readback = str(prows[0][0]) if prows and prows[0] else ""
        # terminal reopen probe
        rc, stdout, stderr = self._spawn_stmt(db_path, config_preamble, [], "PRAGMA integrity_check;")
        result.reopened_ok = rc == 0 and not self._is_crash(rc, f"{stdout}\n{stderr}")
        return result

    _SENTINEL = "__cfg_end_9f3a__"

    def _spawn_stmt(
        self, db_path: str, config_preamble: list[str], attach_preamble: list[str], stmt_sql: str
    ) -> tuple[int, str, str]:
        """Run ONE statement in a fresh process, prefixed by the config-realizing pragmas and
        any active ATTACHes. A sentinel SELECT sits between the preamble and the real
        statement; stdout up to and including the sentinel line is stripped so preamble echo
        (e.g. `journal_mode` -> 'wal') never masquerades as the statement's result rows.

        Invariant: when there is a config preamble and the process exited 0, the sentinel row
        MUST have printed exactly once. If it did not (0 occurrences -- a formatting change or
        an impossibly-unlucky content collision), we do NOT silently pass the polluted stdout
        through as result rows; we surface a HARNESS-SENTINEL error on stderr so the crash/
        error oracle flags the run loudly instead of the differential reading preamble echo as
        query output. On a nonzero rc the statement errored before the sentinel, which is the
        normal missing-sentinel case -- stdout is left as-is for the error/crash oracles."""
        if not config_preamble:
            body = "".join(s + "\n" for s in attach_preamble) + stmt_sql
            return self._spawn(self.argv(db_path, self._script_for(body)), self._script_for(body))
        preamble_lines = list(config_preamble) + [f"SELECT '{self._SENTINEL}';"] + list(attach_preamble)
        body = "".join(s + "\n" for s in preamble_lines) + stmt_sql
        script = self._script_for(body)
        rc, stdout, stderr = self._spawn(self.argv(db_path, script), script)
        count = stdout.count(self._SENTINEL + "\n")
        if rc == 0 and count == 0:
            # Sentinel should have printed on a clean run -- its absence means we cannot trust
            # which lines are the real statement's rows. Fail loud, don't guess.
            return 1, "", f"HARNESS-SENTINEL: sentinel absent on rc=0 (stdout {len(stdout)}B)"
        stripped = self._strip_to_sentinel(stdout)
        return rc, stripped, stderr

    @classmethod
    def _strip_to_sentinel(cls, stdout: str) -> str:
        """Drop everything up to and including the FIRST sentinel line, leaving only the real
        statement's output. The preamble runs before the real statement, so the true sentinel
        is the first occurrence; any echo of the literal in the real statement's own output
        comes AFTER it and is correctly preserved. If the sentinel is absent (statement errored
        before reaching it), return stdout unchanged so error text stays visible to the oracles."""
        marker = cls._SENTINEL + "\n"
        idx = stdout.find(marker)
        if idx == -1:
            return stdout
        return stdout[idx + len(marker):]

    @staticmethod
    def _same_attach(preamble_stmt: str, detach_sql: str) -> bool:
        """True if an ATTACH preamble line refers to the alias in a DETACH statement."""
        m = re.search(r"DETACH\s+(?:DATABASE\s+)?([A-Za-z0-9_]+)", detach_sql, re.IGNORECASE)
        if not m:
            return False
        alias = m.group(1)
        return re.search(rf"\bAS\s+{re.escape(alias)}\b", preamble_stmt, re.IGNORECASE) is not None

    @staticmethod
    def _script_for(sql: str) -> str:
        return f"{sql}\n"

    @staticmethod
    def _is_crash(rc: int, text: str) -> bool:
        if rc < 0:  # killed by signal
            return True
        low = text.lower()
        return any(marker.lower() in low for marker in CRASH_MARKERS)

    @staticmethod
    def _parse_rows(stdout: str) -> list[tuple]:
        """Parse `-m list` output for a SINGLE statement: pipe-separated columns, one row
        per line. A single-column NULL row renders as one empty line, which is NOT the
        same as an empty result set (zero lines) -- so we must NOT drop empty lines
        wholesale (that was a harness bug that made `SELECT max(x) FROM empty` look like
        it returned no rows instead of one NULL row). We strip only ONE trailing newline
        (shell artifact) and keep every remaining line as a row. Because run() invokes the
        CLI one statement at a time, all lines belong to that statement's result set."""
        if stdout == "":
            return []
        body = stdout[:-1] if stdout.endswith("\n") else stdout
        if body == "":
            # stdout was exactly "\n" -> one single-column NULL row.
            return [(None,)]
        rows: list[tuple] = []
        for line in body.split("\n"):
            line = line.rstrip("\r")
            rows.append(tuple(_coerce_cli_cell(c) for c in line.split("|")))
        return rows


class _CliText(str):
    """Marks a cell as already in the CLI's text projection. normalize_value treats it
    verbatim so we never re-guess its SQLite type. This sidesteps the transport ambiguity
    where the CLI's untyped text (e.g. hex of a blob that is all digits) would otherwise be
    mis-coerced to int -- we compare the reference AS THE CLI WOULD RENDER IT, not the CLI
    output re-typed to guess SQLite's tag."""
    __slots__ = ()


def _coerce_cli_cell(cell: str) -> Any:
    """A CLI text cell is untyped: empty string means NULL, everything else is opaque text
    in the CLI's own projection. We do NOT guess int/real/blob here -- guessing is what let
    a blob's hex (all digits) masquerade as an integer. Comparison happens in cli_text mode
    where the reference side is rendered the same way.

    Raw-blob bytes: `-m list` prints a BLOB as its raw bytes. Captured via surrogateescape,
    non-UTF8 blob bytes appear as surrogate-escaped chars (or bare control bytes). When a
    cell carries such bytes we hex-encode it so it compares against the reference's `.hex()`
    of the same blob -- normalizing BOTH sides to one canonical hex form (fix for red #5).
    A cell that is clean printable text is left verbatim."""
    if cell == "":
        return None
    if _has_raw_bytes(cell):
        raw = cell.encode("utf-8", "surrogateescape")
        return _CliText(raw.hex())
    return _CliText(cell)


def _has_raw_bytes(cell: str) -> bool:
    """True if the cell carries bytes that are NOT clean printable text -- i.e. it is a raw
    BLOB projection (surrogate-escaped non-UTF8 bytes, NULs, or other C0 controls except the
    tab that `-m list` legitimately passes through inside a text value)."""
    for ch in cell:
        o = ord(ch)
        if 0xDC80 <= o <= 0xDCFF:   # surrogateescape of a non-UTF8 byte
            return True
        if o < 0x20 and ch != "\t":  # NUL / control byte from a raw blob
            return True
    return False


# IEEE special-value glyphs the two engines render with different capitalization: tursodb
# `-m list` emits 'Inf'/'-Inf'/'NaN'; sqlite3/Python emit 'inf'/'-inf'/'nan'. Both denote the
# SAME IEEE value, so a bare projection of a stored/aggregated infinity (total()/avg() over
# 1e308 rows, calibration smoke) differs only in the glyph case -- a transport artifact, not a
# product divergence. Canonicalize to one lowercase form. This is normalization (the calibration
# discipline), NOT allowlisting: only the exact special-value token is folded; any other text
# ('Info', 'Infinity5', a value that merely starts with these letters) is left untouched.
_IEEE_SPECIALS = {
    "inf": "inf", "+inf": "inf", "-inf": "-inf",
    "nan": "nan", "+nan": "nan", "-nan": "nan",
}


def _canon_ieee_special(cell: str) -> str:
    return _IEEE_SPECIALS.get(cell.lower(), cell)


# ---------------------------------------------------------------------------
# Known-divergence allowlist
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Divergence:
    id: str
    stmt_pattern: str      # regex tested against the offending SQL
    error_pattern: str     # regex tested against combined error text ("" = any)
    rationale: str         # must cite a source before an entry is added


# Ships nearly empty. Entries are added ONLY with a citation. A matching diff is
# suppressed but still emitted as INVARIANT ... PASS divergence:<id> so it is visible.
KNOWN_DIVERGENCES: tuple[Divergence, ...] = (
    # Example placeholder documenting the format -- pattern that never matches a
    # generated statement, so it suppresses nothing today.
    Divergence(
        id="D000-format-example",
        stmt_pattern=r"^__genlib_never_matches__$",
        error_pattern="",
        rationale="Format example only; no real suppression. Real entries must cite "
                   "sqlite3 docs or a Turso issue justifying the accepted divergence.",
    ),
)


def match_divergence(sql: str, error_text: str) -> Optional[Divergence]:
    for d in KNOWN_DIVERGENCES:
        if re.search(d.stmt_pattern, sql) and (not d.error_pattern or re.search(d.error_pattern, error_text)):
            return d
    return None


# ---------------------------------------------------------------------------
# Universal oracles
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    oracle: str
    ok: bool
    summary: str
    divergence_id: Optional[str] = None  # set when a diff was suppressed by allowlist


def oracle_panic(ref: RunResult, cand: RunResult) -> Finding:
    """Candidate must not crash (panic/abort). The reference never crashes."""
    ok = not cand.crashed
    return Finding("panic_abort", ok, f"crashed={cand.crashed} text={cand.crash_text!r}")


def oracle_terminal_state(ref: RunResult, cand: RunResult) -> Finding:
    """Every submitted op reached accept-or-reject and the process exited (no hang);
    if the candidate produced a statement result for each non-reopen op, terminal."""
    ok = len(cand.stmts) >= 1 and not cand.crashed
    return Finding("terminal_state", ok, f"stmts={len(cand.stmts)} crashed={cand.crashed}")


def oracle_reopen(ref: RunResult, cand: RunResult) -> Finding:
    ok = cand.reopened_ok
    return Finding("reopen_persistence", ok, f"reopened_ok={cand.reopened_ok}")


def oracle_integrity(ref: RunResult, cand: RunResult, emit: bool = False) -> Finding:
    """If the candidate ran an integrity_check, it must report ok -- UNLESS every non-ok line
    matches a known-signature allowlist entry (calibration lever 1b). Classification is per
    message: a known signature (e.g. the confirmed WP-024 FTS miscount) is SUPPRESSED (emitted
    as a SUPPRESSED line) and the case continues; ANY line that does not match a known
    signature still reds. So the allowlist only mutes the CONFIRMED FTS finding while keeping
    integrity live for every OTHER corruption (attach/pager -- WP-008)."""
    if cand.integrity_ok is None:
        return Finding("integrity", True, "no_integrity_check_run")
    if cand.integrity_ok:
        return Finding("integrity", True, "integrity_ok=True")
    # Candidate reported non-ok. Classify each recorded message.
    messages = cand.integrity_messages or ["<non-ok, no message captured>"]
    unknown: list[str] = []
    suppressed_rules: set[str] = set()
    for msg in messages:
        sig = match_integrity_signature(msg)
        if sig is not None:
            suppressed_rules.add(sig.rule)
            emit_suppressed(sig.rule, f"{msg!r} ref={sig.reference}", emit)
        else:
            unknown.append(msg)
    if unknown:
        # A non-allowlisted integrity failure -- a real red (e.g. attach/pager corruption).
        return Finding("integrity", False,
                       f"integrity_ok=False unknown_messages={unknown[:3]!r} "
                       f"suppressed={sorted(suppressed_rules)}")
    # Every non-ok line was a known confirmed signature -> case continues (GREEN for this
    # oracle), but the suppression is on record (SUPPRESSED lines above + the note here).
    div_id = ",".join(sorted(suppressed_rules))
    return Finding("integrity", True, f"all-non-ok-allowlisted={sorted(suppressed_rules)}", div_id)


def oracle_error_class(ref: RunResult, cand: RunResult) -> Finding:
    """For each aligned statement, both engines must agree on accept vs reject. A
    mismatch (one accepts, other rejects) is a red -- unless allowlisted."""
    n = min(len(ref.stmts), len(cand.stmts))
    skipped = 0
    for i in range(n):
        r, c = ref.stmts[i], cand.stmts[i]
        # Skip statements the reference cannot express identically (e.g. FTS): there is no
        # meaningful accept/reject to compare. The universal oracles still bind on them.
        if not (r.ref_comparable and c.ref_comparable):
            skipped += 1
            continue
        r_ok, c_ok = r.rc == 0, c.rc == 0
        if r_ok != c_ok:
            d = match_divergence(c.sql, f"{r.error}\n{c.error}")
            if d is not None:
                return Finding("error_class", True, f"suppressed stmt={c.sql!r}", d.id)
            return Finding(
                "error_class", False,
                f"accept-mismatch stmt={c.sql!r} ref_ok={r_ok} cand_ok={c_ok} "
                f"ref_err={r.error!r} cand_err={c.error!r}",
            )
    return Finding("error_class", True, f"aligned={n} skipped_noncomparable={skipped}")


_INTEGRITY_SQL_RE = re.compile(r"PRAGMA\s+(integrity_check|quick_check)", re.IGNORECASE)


def _all_cells_known_integrity(rowset: list[tuple]) -> Optional[str]:
    """If EVERY cell of a candidate integrity/quick_check rowset matches a known integrity
    signature (the confirmed WP-024 FTS message), return the joined rule ids; else None. Used
    so the diff_rows oracle suppresses the SAME confirmed class the integrity oracle allowlists
    (an integrity_check's rows also flow through diff_rows), while ANY unknown integrity row
    -- e.g. an attach/pager corruption message (WP-008) -- still reds."""
    rules: set[str] = set()
    saw_any = False
    for row in rowset:
        for cell in row:
            text = str(cell)
            if text.lower() == "ok":
                continue
            saw_any = True
            sig = match_integrity_signature(text)
            if sig is None:
                return None  # an unknown non-ok message -> not fully known, must red
            rules.add(sig.rule)
    return ",".join(sorted(rules)) if saw_any else None


def oracle_diff_rows(ref: RunResult, cand: RunResult, cli_text: bool = False, emit: bool = False) -> Finding:
    """For each aligned statement that BOTH accepted, the normalized row multisets must
    match. Mismatch = red unless allowlisted. cli_text collapses type tags when either
    runner is a text-only CLI that cannot carry SQLite's typing.

    calibration: an integrity_check/quick_check statement's ROWS also flow through here, so a
    candidate integrity row that is entirely the confirmed WP-024 FTS signature would red in
    diff_rows even though oracle_integrity correctly allowlists it. Consult the SAME
    KNOWN_INTEGRITY_SIGNATURES allowlist for integrity/quick_check statements: if the reference
    said `ok` and every candidate non-ok cell is a known signature, SUPPRESS (emit a SUPPRESSED
    line, continue); any UNKNOWN integrity row (WP-008 attach/pager) still reds normally."""
    n = min(len(ref.stmts), len(cand.stmts))
    for i in range(n):
        r, c = ref.stmts[i], cand.stmts[i]
        if not (r.ref_comparable and c.ref_comparable):
            continue  # reference cannot express this stmt (e.g. FTS); no row comparison
        if r.rc != 0 or c.rc != 0:
            continue  # error-class oracle owns accept/reject disagreements
        rref = normalize_rowset(r.rows, cli_text)
        rcand = normalize_rowset(c.rows, cli_text)
        if not _rows_equal(rref, rcand):
            d = match_divergence(c.sql, "")
            if d is not None:
                return Finding("diff_rows", True, f"suppressed stmt={c.sql!r}", d.id)
            # Known-integrity-signature allowlist on integrity/quick_check statements: the same
            # confirmed WP-024 class the integrity oracle already suppressed. Only suppresses
            # when the reference is a clean `ok` and every candidate non-ok cell is known.
            if _INTEGRITY_SQL_RE.search(c.sql):
                # `bool(r.rows) and ...`: the reference must have ACTUALLY produced an `ok`
                # rowset, not vacuously (an empty reference rowset must NOT license suppression
                # -- that would silently mask a candidate integrity failure whenever the
                # reference integrity_check happened to return zero rows). Non-vacuous discipline.
                ref_ok = bool(r.rows) and all(str(cell).lower() == "ok" for row in r.rows for cell in row)
                known = _all_cells_known_integrity(c.rows)
                if ref_ok and known is not None:
                    emit_suppressed(known, f"diff_rows-on-integrity stmt={c.sql!r} "
                                           f"cand_rows={[tuple(str(x) for x in row) for row in c.rows][:2]!r}", emit)
                    continue
            return Finding(
                "diff_rows", False,
                f"rowset-mismatch stmt={c.sql!r} ref={rref[:4]!r} cand={rcand[:4]!r} "
                f"ref_n={len(rref)} cand_n={len(rcand)}",
            )
    return Finding("diff_rows", True, f"aligned={n}")


ORACLES: tuple[Callable[[RunResult, RunResult], Finding], ...] = (
    oracle_panic,
    oracle_terminal_state,
    oracle_reopen,
    oracle_integrity,
    oracle_error_class,
    oracle_diff_rows,
)


# ---------------------------------------------------------------------------
# Case protocol
# ---------------------------------------------------------------------------

@dataclass
class CaseResult:
    seed: int
    verdict: str            # GREEN / RED / VOID
    exit_code: int          # 0 / 1 / 3
    findings: list[Finding]


def _plant_corruption(ref: RunResult) -> None:
    """ORACLE_SELFTEST: mutate the reference so a DIFFERENTIAL oracle MUST fire RED. We
    only mutate REF-COMPARABLE statements (the differential oracles skip non-comparable
    ones, so corrupting those would not be caught). Drop a row from the first accepted,
    comparable SELECT that returned rows; if none, flip an accept to reject."""
    for st in ref.stmts:
        if st.ref_comparable and st.rc == 0 and st.rows:
            st.rows = st.rows[1:]
            return
    for st in ref.stmts:
        if st.ref_comparable and st.rc == 0:
            st.rc = 1
            st.error = "SELFTEST: planted rejection"
            return


def run_case(
    seed: int,
    axes: dict[str, tuple],
    runners: tuple[Runner, Runner],
    lifecycle_plug: tuple[str, ...] = (),
    case_id: str = "GEN",
    emit: bool = True,
    stratum: Optional[str] = None,
) -> CaseResult:
    """Generate a program from seed, run reference + candidate, apply every universal
    oracle, and emit the INVARIANT/VERDICT protocol. runners = (reference, candidate).

    Verdict: RED if any oracle fails; VOID if the harness itself errored; else GREEN.

    calibration: `stratum` forwards to generate() to pin the family-density stratum (else the
    seed-derived draw / GENFUZZ_STRATUM env is used)."""
    reference, candidate = runners
    program = generate(seed, axes, lifecycle_plug, emit_suppress=emit, stratum=stratum)
    findings: list[Finding] = []
    verdict = "GREEN"
    exit_code = 0

    try:
        ref_result = reference.run(program)
        cand_result = candidate.run(program)
        if os.environ.get("ORACLE_SELFTEST"):
            _plant_corruption(ref_result)
        cli_text = getattr(reference, "text_only", False) or getattr(candidate, "text_only", False)
        for oracle in ORACLES:
            if oracle is oracle_diff_rows:
                f = oracle(ref_result, cand_result, cli_text, emit)
            elif oracle is oracle_integrity:
                f = oracle(ref_result, cand_result, emit)
            else:
                f = oracle(ref_result, cand_result)
            findings.append(f)
    except Exception as exc:  # harness fault -> VOID, not a product verdict
        if emit:
            print(f"INVARIANT {case_id} harness_fault FAIL seed={seed} err={type(exc).__name__}: {exc}", flush=True)
            print(f"VERDICT: VOID seed={seed}", flush=True)
        return CaseResult(seed, "VOID", 3, findings)

    for f in findings:
        status = "PASS" if f.ok else "FAIL"
        note = f" divergence:{f.divergence_id}" if f.divergence_id else ""
        if emit:
            print(f"INVARIANT {case_id} {f.oracle} {status} seed={seed} {f.summary}{note}", flush=True)
        if not f.ok:
            verdict = "RED"
            exit_code = 1

    if emit:
        print(f"VERDICT: {'GREEN' if verdict == 'GREEN' else 'RED'} seed={seed} "
              f"page_size={program.config['page_size']} encryption={program.config['encryption']}", flush=True)
    return CaseResult(seed, verdict, exit_code, findings)


def merged_axes(product_axes: Optional[dict[str, tuple]] = None) -> dict[str, tuple]:
    axes = dict(CORE_AXES)
    if product_axes:
        axes.update(product_axes)
    return axes
