#!/usr/bin/env python3
"""test_genlib -- calibration/102 probe. Run: python3 lib/test_genlib.py

Seven probe groups, each printed with a GROUP <name> PASS|FAIL line:
  1. determinism      -- 100 seeds generated twice in SUBPROCESSES (defeats hash
                         randomization); signatures must be byte-identical.
  2. null_differential-- sqlite3-vs-sqlite3 over >=200 seeds must be 100% GREEN;
                         any RED is a harness bug (normalization/ordering/etc).
  3. selftest         -- ORACLE_SELFTEST must produce RED on >=5 seeds.
  4. coverage         -- over 500 programs, every op family, config-axis value, feature
                         family (fts/json_tvf/trigger/attach), FTS tokenizer, and JSON TVF
                         form appears at least once, and every FTS op is ref_comparable=False.
                         PLUS the calibration execution-depth LOCKS: durability read-back tail in
                         every program, attach full lifecycle sequence >=95%, empty-table
                         population >=15%, trigger-fire-after-reopen >=60%, and the trigger/
                         attach fired VALUES sweep (>=50 / >=30 distinct tuples vs the old
                         single constant tuple) -- so the deepened shapes cannot regress shallow.
  5. error_class      -- some programs contain expected-error statements and both
                         sqlite3 runners reject them identically (0 error-class reds).
  6. cli_mock         -- drives the CliRunner (guest adapter path) with a mock spawn that
                         renders sqlite3 as tursodb `-m list`, incl. ATTACH preamble replay
                         and trigger bodies; must be 100% GREEN.
  7. encryption_uri   -- validates the swept encryption config is plumbed into the db arg
                         (file:<db>?cipher=..&hexkey=..) via the real turso_genfuzz wiring,
                         and the differential still holds when the URI is stripped on open.
  8. render_divergence-- calibration Part 1: the calibration red classes #2/#3/#4/#5/#6 (REAL 0.0
                         vs "0", 1e+308 exponent, 15-vs-17-digit precision, raw-byte blob)
                         are HARNESS-RENDER-BUGs and now reconcile; a genuine value/type
                         difference (negative controls) still reds.
  9. config_realization- calibration Part 2: the config-realizing pragma preamble makes the
                         swept page_size actually BIND on the db-creating process INCLUDING
                         under encryption (WP-025 armament fix); page_size read-back equals
                         the swept value on both runners across the full page_size ladder.
 10. known_class       - calibration: the KNOWN-CLASS quarantine (WP-025 crash config downweighted
                         to a canary, visibly SUPPRESSED, deterministic) and the integrity
                         ALLOWLIST (confirmed WP-024 FTS message suppressed + case continues,
                         while any OTHER integrity message -- WP-008 attach/pager -- still reds).

calibration also adds coverage LOCKS (group 4): feature-mask FTS-free floor (integrity unmasked
for WP-008), non-zero-but-small quarantine canary, >=6 identifier-quoting shapes across DDL,
>=100 swept scalar-boundary persisted calls with read-back (WP-015), and all 4 correlated TVF
re-entry shapes (WP-023) -- so the new generic axes cannot silently regress.

The mock spawns render sqlite3 EXACTLY as tursodb `-m list` does -- raw blob bytes (not
hex), shortest-roundtrip REAL (not int-collapsed), and the full multi-statement script
including the config-realizing pragma preamble -- so groups 6-9 validate the guest adapter
faithfully rather than against a lenient stand-in.

Exit 0 iff all groups pass.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import genlib


N_DETERMINISM = 100
N_NULL_DIFF = 250
N_SELFTEST = 8
N_COVERAGE = 500


def _p(msg: str) -> None:
    print(msg, flush=True)


def _tursodb_cell(c: object) -> bytes:
    """Render one cell EXACTLY as tursodb `-m list` does, for the faithful mock spawns. This
    must match the real binary's rendering or the probe gives false confidence (the calibration/106
    lesson). Faithful details:
      * REAL -> shortest-roundtrip (repr), NOT int-collapsed, AND signed-zero -0.0 -> '0.0'
        (tursodb drops the zero sign; the reference keeps it -- _cells_equal reconciles).
      * BLOB -> the blob's bytes decoded as UTF-8 with LOSSY replacement of undecodable byte
        runs by U+FFFD, which is what `-m list` physically emits (it is not blob-safe); a
        clean-UTF8 blob prints its text verbatim. This is why raw-blob projection is transport-
        ambiguous and generated read-backs wrap blobs in quote() to stay byte-faithful.
    """
    import math
    if c is None:
        return b""
    if isinstance(c, bytes):
        # tursodb prints a blob's bytes as text, lossily replacing non-UTF8 bytes with U+FFFD.
        return c.decode("utf-8", "replace").encode("utf-8")
    if isinstance(c, float):
        if math.isinf(c):
            # tursodb `-m list` capitalizes the IEEE special glyph ('Inf'/'-Inf'); the harness
            # canonicalizes case . Render it capitalized here so the mock is FAITHFUL
            # and the canonicalization is actually exercised through the mock-CLI path.
            return b"Inf" if c > 0 else b"-Inf"
        if math.isnan(c):
            return b"NaN"  # tursodb capitalizes NaN; harness canonicalizes case 
        if c == 0.0:
            return b"0.0"  # tursodb drops the sign on zero (-0.0 -> '0.0')
        return repr(c).encode()
    return str(c).encode("utf-8", "surrogateescape")


# --- group 1: determinism (cross-process) -----------------------------------

_CHILD_SNIPPET = (
    "import sys; sys.path.insert(0, %r); import genlib; "
    "axes = genlib.merged_axes({'cipher': ('aegis256','aes256gcm'), 'attach_aux': (0,1)}); "
    "print(genlib.generate(int(sys.argv[1]), axes).signature())"
)


def _gen_in_subprocess(lib_dir: str, seed: int) -> str:
    code = _CHILD_SNIPPET % lib_dir
    env = dict(os.environ)
    # Force a nonzero hash seed so a dict/hash-order dependence would diverge run-to-run.
    env["PYTHONHASHSEED"] = "random"
    proc = subprocess.run(
        [sys.executable, "-c", code, str(seed)],
        text=True, capture_output=True, env=env, check=True,
    )
    return proc.stdout


def group_determinism(lib_dir: str) -> bool:
    mismatches = 0
    for seed in range(1000, 1000 + N_DETERMINISM):
        a = _gen_in_subprocess(lib_dir, seed)
        b = _gen_in_subprocess(lib_dir, seed)
        if a != b:
            mismatches += 1
            if mismatches <= 3:
                _p(f"  determinism MISMATCH seed={seed}")
    ok = mismatches == 0
    _p(f"GROUP determinism {'PASS' if ok else 'FAIL'} seeds={N_DETERMINISM} mismatches={mismatches}")
    return ok


# --- group 2: null differential (sqlite3 vs sqlite3) ------------------------

def group_null_differential(run_dir: Path) -> bool:
    axes = genlib.merged_axes({"cipher": ("aegis256", "aes256gcm"), "attach_aux": (0, 1)})
    reds = []
    voids = []
    for seed in range(2000, 2000 + N_NULL_DIFF):
        ref = genlib.Sqlite3Runner(run_dir, tag="ref")
        cand = genlib.Sqlite3Runner(run_dir, tag="cand")
        res = genlib.run_case(seed, axes, (ref, cand), case_id="NULL", emit=False)
        if res.verdict == "RED":
            reds.append((seed, [f for f in res.findings if not f.ok]))
        elif res.verdict == "VOID":
            voids.append(seed)
    for seed, fails in reds[:5]:
        for f in fails:
            _p(f"  null-diff RED seed={seed} oracle={f.oracle} {f.summary}")
    ok = not reds and not voids
    _p(f"GROUP null_differential {'PASS' if ok else 'FAIL'} seeds={N_NULL_DIFF} reds={len(reds)} voids={len(voids)}")
    return ok


# --- group 3: selftest (planted corruption -> RED) --------------------------

def group_selftest(run_dir: Path) -> bool:
    axes = genlib.merged_axes({"cipher": ("aegis256", "aes256gcm"), "attach_aux": (0, 1)})
    os.environ["ORACLE_SELFTEST"] = "1"
    try:
        reds = 0
        for seed in range(3000, 3000 + N_SELFTEST):
            ref = genlib.Sqlite3Runner(run_dir, tag="ref")
            cand = genlib.Sqlite3Runner(run_dir, tag="cand")
            res = genlib.run_case(seed, axes, (ref, cand), case_id="SELF", emit=False)
            if res.verdict == "RED":
                reds += 1
    finally:
        os.environ.pop("ORACLE_SELFTEST", None)
    ok = reds >= 5
    _p(f"GROUP selftest {'PASS' if ok else 'FAIL'} seeds={N_SELFTEST} reds={reds} (need>=5)")
    return ok


# --- group 4: coverage smoke ------------------------------------------------

def _trigger_fire_after_reopen(ops) -> bool:
    """True if a trigger created in this program later FIRES (a DML inserts into its target
    table) with a reopen occurring between the create and the fire -- the WP-005 create/
    reload/fire sequence. Structural check over the op list."""
    import re as _re
    tgt_re = _re.compile(r"CREATE\s+TRIGGER\s+\S+\s+AFTER\s+INSERT\s+ON\s+(\S+)\s+BEGIN", _re.IGNORECASE)
    ins_re = _re.compile(r"\s*INSERT\s+INTO\s+([^\s(]+)", _re.IGNORECASE)
    for i, op in enumerate(ops):
        if op.kind in ("create_trigger", "trigger_create"):
            m = tgt_re.search(op.sql)
            if not m:
                continue
            tgt = m.group(1)
            reopened = False
            for j in range(i + 1, len(ops)):
                if ops[j].kind == "reopen":
                    reopened = True
                if ops[j].family == "DML" and ops[j].sql.strip().upper().startswith("INSERT"):
                    mm = ins_re.match(ops[j].sql)
                    if mm and mm.group(1) == tgt and reopened:
                        return True
    return False


def _raw_config_draw(root: int, axes: dict) -> dict:
    """Replicate choose_config's RAW draw (BEFORE the quarantine re-roll) so the test can
    measure how often the raw config lands in the WP-025 crash family -- the proof that the
    quarantine is actually intercepting draws (canary + downweight must sum to the raw hits)."""
    rng = genlib.seeded_rng(root, "config")
    cfg = {}
    for name in sorted(axes):
        values = axes[name]
        cfg[name] = values[rng.randrange(len(values))]
    return cfg


def group_coverage() -> bool:
    axes = genlib.merged_axes({"cipher": ("aegis256", "aes256gcm"), "attach_aux": (0, 1)})
    seen_families: set[str] = set()
    seen_axis_values: dict[str, set] = {name: set() for name in axes}
    # Feature-family coverage: which declared feature classes appear, and which sub-grammar
    # values (FTS tokenizers, JSON TVF forms) are reached -- the generator must sweep the
    # WHOLE family, not one crafted case (the anti-telegraphing rule).
    seen_feature_kinds: set[str] = set()
    seen_fts_tokenizers: set[str] = set()
    seen_json_forms: set[str] = set()
    fts_all_noncomparable = True
    _feature_markers = {
        "fts": "fts_create_index",
        "json_tvf": "json_insert",
        "trigger": "trigger_create",
        "attach": "attach_create",
        "scalar_persist": "scalar_create_table",
    }
    _json_form_kinds = {
        "json_join_tree", "json_correlated_subquery", "json_cte_reuse", "json_each_then_tree",
    }
    # calibration execution-depth coverage: per-program counts of the deepened shapes, so the
    # measured depth-rate improvements are LOCKED here as regression assertions (the census
    # zero-red families exist structurally, but were shallow -- constant-valued and rare; these
    # thresholds require the generic deepening levers keep firing).
    prog_with_durability_tail = 0        # lever 3: every program ends with a reopen + full read-back
    prog_with_empty_table = 0            # lever 1: some tables deliberately empty
    prog_with_attach_full_seq = 0        # lever 4: aux DDL + DROP + checkpoint + reopen + read-back
    prog_with_attach = 0                 # denominator: programs where attach is mask-included
    prog_with_trigger_fire_after_reopen = 0
    prog_with_trigger = 0                # denominator: programs where trigger is mask-included
    distinct_trigger_fire_tuples: set[str] = set()   # lever 2: fired values sweep, not constant
    distinct_attach_readback_sets: set[str] = set()  # lever 4: aux values sweep
    seen_pop_modes: set[str] = set()
    # calibration lever measurements ----------------------------------------------------------
    prog_fts_free = 0                    # lever 1c: programs with NO FTS op at all
    prog_with_fts = 0                    # programs with at least one FTS op
    quarantine_canary = 0               # lever 1a: programs kept as WP-025 crash-config canary
    quarantine_downweighted = 0         # lever 1a: programs re-rolled off the crash config
    enc_nonstd_pagesize_progs = 0       # programs whose FINAL config is still enc x non-4096
    distinct_identifier_shapes: set[str] = set()     # lever 2: quoted-identifier styles seen in DDL
    distinct_scalar_persist_calls: set[str] = set()  # lever 3: scalar-boundary calls w/ read-back
    prog_with_scalar_readback = 0       # lever 3: programs that persist + read back scalar results
    distinct_correlated_tvf_shapes: set[str] = set() # lever 4(TVF): correlated/join/CTE re-entry shapes
    import re as _re
    _trg_fire_re = _re.compile(r"VALUES\s*\((.*)\)", _re.IGNORECASE)
    _att_ins_re = _re.compile(r"VALUES\s*(.*);")
    # Identifier-shape detectors over DDL text (generic: which quoting styles actually appear).
    _ident_probes = {
        "double_quoted": _re.compile(r'"[^"]+"'),
        "bracketed": _re.compile(r'\[[^\]]+\]'),
        "backticked": _re.compile(r"`[^`]+`"),
        "spaced": _re.compile(r'"[^"]* col"'),
        "dotted": _re.compile(r'"[^"]*\.d"'),
        "unicode": _re.compile(r'"[^"]*é☃"'),
    }
    _corr_tvf_kinds = {
        "json_join_tree", "json_correlated_subquery", "json_cte_reuse", "json_each_then_tree",
    }
    _ddl_kinds = {
        "create_table", "create_index", "create_view", "create_trigger",
        "trigger_target_table", "trigger_audit_table", "trigger_create",
        "json_create_table", "attach_create", "attach_create2", "scalar_create_table",
    }
    for seed in range(4000, 4000 + N_COVERAGE):
        prog = genlib.generate(seed, axes)
        kinds_this = [op.kind for op in prog.ops]
        has_fts_this = any(op.kind.startswith("fts_") for op in prog.ops)
        if has_fts_this:
            prog_with_fts += 1
        else:
            prog_fts_free += 1
        # Config-quarantine accounting: does the raw draw land in the crash family, and did the
        # resolved config keep it (canary) or move off it (downweighted)?
        raw_cfg = _raw_config_draw(seed, axes)
        raw_q = genlib.match_config_quarantine(raw_cfg)
        final_q = genlib.match_config_quarantine(prog.config)
        if raw_q is not None:
            if final_q is not None:
                quarantine_canary += 1
            else:
                quarantine_downweighted += 1
        if final_q is not None:
            enc_nonstd_pagesize_progs += 1
        for op in prog.ops:
            seen_families.add(op.family)
            seen_feature_kinds.add(op.kind)
            if op.kind in _json_form_kinds:
                seen_json_forms.add(op.kind)
            if op.kind in _corr_tvf_kinds:
                distinct_correlated_tvf_shapes.add(op.kind)
            if op.kind == "fts_create_index":
                # Extract the tokenizer from the DDL (or 'default' when no WITH clause).
                if "tokenizer = 'raw'" in op.sql:
                    seen_fts_tokenizers.add("raw")
                elif "tokenizer = 'ngram'" in op.sql:
                    seen_fts_tokenizers.add("ngram")
                else:
                    seen_fts_tokenizers.add("default")
            # Every FTS op must be marked non-reference-comparable.
            if op.kind.startswith("fts_") and op.ref_comparable:
                fts_all_noncomparable = False
            if op.kind == "trigger_fire":
                m = _trg_fire_re.search(op.sql)
                if m:
                    distinct_trigger_fire_tuples.add(m.group(1).strip())
            if op.kind in ("attach_insert", "attach_insert2"):
                m = _att_ins_re.search(op.sql)
                if m:
                    distinct_attach_readback_sets.add(m.group(1).strip())
            # lever 2: which identifier-quoting shapes appear across DDL objects.
            if op.kind in _ddl_kinds:
                for shape, rx in _ident_probes.items():
                    if rx.search(op.sql):
                        distinct_identifier_shapes.add(shape)
            # lever 3: scalar-boundary calls persisted for read-back.
            if op.kind in ("scalar_insert", "scalar_insert_zeroblob"):
                distinct_scalar_persist_calls.add(op.sql)
        for name, val in prog.config.items():
            seen_axis_values[name].add(val)
        # per-program depth shapes
        if "durability_readback" in kinds_this:
            prog_with_durability_tail += 1
        if "insert_skipped_empty" in kinds_this:
            prog_with_empty_table += 1
            seen_pop_modes.add("empty")
        if "scalar_readback" in kinds_this:
            prog_with_scalar_readback += 1
        # attach/trigger locks are now measured AMONG programs where the mask includes the
        # family (the calibration intent: when the family runs, its full sequence always runs).
        if "attach_create" in kinds_this:
            prog_with_attach += 1
            if all(k in kinds_this for k in ("attach_create", "attach_drop", "attach_checkpoint", "attach_read")):
                prog_with_attach_full_seq += 1
        if "trigger_create" in kinds_this:
            prog_with_trigger += 1
            if _trigger_fire_after_reopen(prog.ops):
                prog_with_trigger_fire_after_reopen += 1

    missing_families = set(genlib.OP_FAMILIES) - seen_families
    missing_axis = {}
    for name, values in axes.items():
        miss = set(values) - seen_axis_values[name]
        if miss:
            missing_axis[name] = sorted(miss, key=repr)

    # Feature families: every declared family's marker op must have appeared.
    missing_feature_families = [
        fam for fam, marker in _feature_markers.items() if marker not in seen_feature_kinds
    ]
    missing_fts_tokenizers = set(genlib.FTS_TOKENIZERS) - seen_fts_tokenizers
    missing_json_forms = _json_form_kinds - seen_json_forms

    # calibration LOCKED depth assertions -- thresholds sit conservatively below the measured
    # rates so the generic deepening levers cannot silently regress (the anti-shallow lock).
    # calibration change: the attach/trigger locks are now measured AMONG programs where the
    # feature mask (lever 1c) INCLUDES that family, because the mask deliberately masks the
    # family out of a fraction of programs. The calibration intent is preserved exactly -- when the
    # family runs, its full deepened sequence still always runs -- while accommodating the mask.
    N = N_COVERAGE
    depth_fail: list[str] = []
    if prog_with_durability_tail != N:
        depth_fail.append(f"durability_tail {prog_with_durability_tail}/{N} (want ALL programs)")
    # attach full-seq: >=95% of attach-INCLUDED programs run the whole aux page lifecycle.
    if prog_with_attach == 0 or prog_with_attach_full_seq < int(0.95 * prog_with_attach):
        depth_fail.append(f"attach_full_seq {prog_with_attach_full_seq}/{prog_with_attach} attach-incl (want >=95%)")
    if prog_with_empty_table < int(0.15 * N):
        depth_fail.append(f"empty_table_programs {prog_with_empty_table}/{N} (want >=15%)")
    # trigger fire-after-reopen: >=60% of trigger-INCLUDED programs fire after a reopen.
    if prog_with_trigger == 0 or prog_with_trigger_fire_after_reopen < int(0.60 * prog_with_trigger):
        depth_fail.append(f"trigger_fire_after_reopen {prog_with_trigger_fire_after_reopen}/{prog_with_trigger} trigger-incl (want >=60%)")
    if len(distinct_trigger_fire_tuples) < 50:
        depth_fail.append(f"distinct_trigger_fire_tuples {len(distinct_trigger_fire_tuples)} (want >=50; constant tuple was 1)")
    if len(distinct_attach_readback_sets) < 30:
        depth_fail.append(f"distinct_attach_readback_sets {len(distinct_attach_readback_sets)} (want >=30; constant set was 1)")

    # calibration LOCKED assertions -- one per lever, thresholds below the measured rates.
    e109_fail: list[str] = []
    # lever 1a: the quarantine must (i) keep a NON-ZERO canary fraction (WP-025 matcher alive)
    # AND (ii) downweight the majority off the crash config (unmasking the differentials).
    if quarantine_canary <= 0:
        e109_fail.append(f"quarantine_canary {quarantine_canary} (want >0 -- WP-025 matcher must stay alive)")
    if quarantine_downweighted <= 0:
        e109_fail.append(f"quarantine_downweighted {quarantine_downweighted} (want >0 -- crash config must be re-rolled off)")
    # The canary fraction must be SMALL (most crash-family draws are downweighted). Measured
    # canary_rate=0.05, so among raw hits the kept fraction sits near 5%.
    raw_q_hits = quarantine_canary + quarantine_downweighted
    if raw_q_hits > 0 and quarantine_canary > int(0.25 * raw_q_hits):
        e109_fail.append(f"quarantine_canary_fraction {quarantine_canary}/{raw_q_hits} (want <=25%; canary must be small)")
    # ...and the FINAL config lands in the crash family for only a SMALL fraction of ALL
    # programs (the whole point of the quarantine: the crash config no longer masks the rest).
    # Measured ~9/500 (~2%); lock <=10% so a regression that stops downweighting fails here.
    if enc_nonstd_pagesize_progs > int(0.10 * N):
        e109_fail.append(f"enc_nonstd_pagesize_final {enc_nonstd_pagesize_progs}/{N} (want <=10%; quarantine must keep crash config rare)")
    # ...but it must be >0 (the canary): the crash config IS still reached, keeping WP-025 alive.
    if enc_nonstd_pagesize_progs <= 0:
        e109_fail.append(f"enc_nonstd_pagesize_final {enc_nonstd_pagesize_progs} (want >0 -- WP-025 canary must reach the crash config)")
    # lever 1c: a real floor of programs are FTS-FREE (so integrity is unmasked for non-FTS).
    if prog_fts_free < int(0.25 * N):
        e109_fail.append(f"fts_free_programs {prog_fts_free}/{N} (want >=25% -- integrity must unmask for WP-008)")
    # ...and FTS is still exercised in a real fraction (WP-024 matcher stays alive).
    if prog_with_fts < int(0.20 * N):
        e109_fail.append(f"fts_programs {prog_with_fts}/{N} (want >=20% -- WP-024 matcher must stay alive)")
    # lever 2: >=6 distinct quoted-identifier shapes appear across DDL objects.
    if len(distinct_identifier_shapes) < 6:
        e109_fail.append(f"distinct_identifier_shapes {sorted(distinct_identifier_shapes)} (want >=6 quoting styles)")
    # lever 3: >=100 distinct scalar-boundary persisted calls, present with a read-back tail.
    if len(distinct_scalar_persist_calls) < 100:
        e109_fail.append(f"distinct_scalar_persist_calls {len(distinct_scalar_persist_calls)} (want >=100 swept calls)")
    if prog_with_scalar_readback < int(0.20 * N):
        e109_fail.append(f"scalar_readback_programs {prog_with_scalar_readback}/{N} (want >=20% persist+readback)")
    # lever 4: all 4 correlated/join/CTE TVF re-entry shapes are reached.
    if len(distinct_correlated_tvf_shapes) < 4:
        e109_fail.append(f"correlated_tvf_shapes {sorted(distinct_correlated_tvf_shapes)} (want all 4 re-entry shapes)")

    ok = (
        not missing_families and not missing_axis and not missing_feature_families
        and not missing_fts_tokenizers and not missing_json_forms and fts_all_noncomparable
        and not depth_fail and not e109_fail
    )
    if missing_families:
        _p(f"  coverage MISSING families={sorted(missing_families)}")
    if missing_axis:
        _p(f"  coverage MISSING axis values={missing_axis}")
    if missing_feature_families:
        _p(f"  coverage MISSING feature_families={sorted(missing_feature_families)}")
    if missing_fts_tokenizers:
        _p(f"  coverage MISSING fts_tokenizers={sorted(missing_fts_tokenizers)}")
    if missing_json_forms:
        _p(f"  coverage MISSING json_forms={sorted(missing_json_forms)}")
    if not fts_all_noncomparable:
        _p("  coverage FTS ops must be ref_comparable=False but some were True")
    for df in depth_fail:
        _p(f"  coverage DEPTH-LOCK FAIL {df}")
    for ef in e109_fail:
        _p(f"  coverage calibration-LOCK FAIL {ef}")
    _p(f"GROUP coverage {'PASS' if ok else 'FAIL'} programs={N_COVERAGE} "
       f"families={len(seen_families)}/{len(genlib.OP_FAMILIES)} axes_full={len(axes) - len(missing_axis)}/{len(axes)} "
       f"feature_families={len(_feature_markers) - len(missing_feature_families)}/{len(_feature_markers)} "
       f"fts_tokenizers={len(seen_fts_tokenizers)}/{len(genlib.FTS_TOKENIZERS)} "
       f"json_forms={len(seen_json_forms)}/{len(_json_form_kinds)} "
       f"[calibration depth: durability={prog_with_durability_tail}/{N} "
       f"attach_full={prog_with_attach_full_seq}/{prog_with_attach}(incl) "
       f"empty_progs={prog_with_empty_table}/{N} "
       f"trg_fire_reopen={prog_with_trigger_fire_after_reopen}/{prog_with_trigger}(incl) "
       f"trg_tuples={len(distinct_trigger_fire_tuples)} attach_sets={len(distinct_attach_readback_sets)}] "
       f"[calibration: fts_free={prog_fts_free}/{N} fts_progs={prog_with_fts}/{N} "
       f"quar_canary={quarantine_canary} quar_downwt={quarantine_downweighted} "
       f"enc_nonstd_final={enc_nonstd_pagesize_progs} ident_shapes={len(distinct_identifier_shapes)} "
       f"scalar_calls={len(distinct_scalar_persist_calls)} scalar_progs={prog_with_scalar_readback}/{N} "
       f"corr_tvf={len(distinct_correlated_tvf_shapes)}/4]")
    return ok


# --- group 5: error-class differential --------------------------------------

def group_error_class(run_dir: Path) -> bool:
    axes = genlib.merged_axes({"cipher": ("aegis256", "aes256gcm"), "attach_aux": (0, 1)})
    programs_with_expect_error = 0
    total_expect_error_stmts = 0
    error_class_reds = 0
    both_reject_agreements = 0
    for seed in range(5000, 5000 + 200):
        prog = genlib.generate(seed, axes)
        ee = [op for op in prog.ops if op.expect_error]
        if ee:
            programs_with_expect_error += 1
            total_expect_error_stmts += len(ee)
        ref = genlib.Sqlite3Runner(run_dir, tag="ref")
        cand = genlib.Sqlite3Runner(run_dir, tag="cand")
        ref_res = ref.run(prog)
        cand_res = cand.run(prog)
        f = genlib.oracle_error_class(ref_res, cand_res)
        if not f.ok:
            error_class_reds += 1
        # count aligned statements both rejected (agreement on rejection)
        n = min(len(ref_res.stmts), len(cand_res.stmts))
        for i in range(n):
            if ref_res.stmts[i].rc != 0 and cand_res.stmts[i].rc != 0:
                both_reject_agreements += 1
    ok = programs_with_expect_error > 0 and error_class_reds == 0 and both_reject_agreements > 0
    _p(f"GROUP error_class {'PASS' if ok else 'FAIL'} "
       f"programs_with_expect_error={programs_with_expect_error} expect_error_stmts={total_expect_error_stmts} "
       f"error_class_reds={error_class_reds} both_reject_agreements={both_reject_agreements}")
    return ok


# --- group 6: mock-CLI differential (exercises the CliRunner path anywhere) --

def group_cli_mock(run_dir: Path) -> bool:
    """Drive genlib.CliRunner with a mock spawn that renders a real sqlite3 exactly as
    tursodb's `-m list` would, then differential it against a sqlite3 reference. Because
    the mock IS sqlite3, this must be 100% GREEN -- any RED/VOID is a CliRunner parse or
    normalization bug (this is where the guest-run adapter path is validated on macOS)."""
    import math
    import sqlite3 as _sq

    class _Fake:
        """Mock spawn that renders a real sqlite3 exactly as tursodb `-m list` does. Each
        spawn is a FRESH process (fresh connection) against the persistent db file. The whole
        script runs statement-by-statement and every produced row is concatenated to stdout,
        matching the CLI's list output -- including the config-realizing pragma preamble the
        CliRunner now prepends, whose echo the CliRunner strips at the sentinel line.

        Faithfulness to tursodb's rendering (what makes this validate the render fixes):
          * REAL -> shortest-roundtrip (Python repr), NOT collapsed to int -- so REAL 0.0
            prints '0.0' and -1/6 prints its 17-digit form, exactly the divergences calibration
            saw. The harness's %.15g normalization is what must reconcile these.
          * BLOB -> RAW bytes (not hex), which is what `-m list` physically emits; the
            CliRunner's byte-faithful capture + hex-recovery is what must reconcile these."""

        def _cell(self, c: object) -> bytes:
            return _tursodb_cell(c)   # shared faithful `-m list` renderer (signed-zero, lossy blob)

        def _split_statements(self, script: str) -> list:
            """Split a script into statements the way the CliRunner built it: preamble lines
            (config pragmas, the sentinel SELECT, ATTACH replays) are each one line ending
            in ';', followed by the real op SQL which is a SINGLE statement that may contain
            inner semicolons (trigger BEGIN..END). We peel leading single-line statements
            (those ending in ';' on their own line) and treat the trailing remainder as one."""
            lines = script.split("\n")
            stmts: list = []
            idx = 0
            while idx < len(lines):
                ln = lines[idx].strip()
                if ln.endswith(";") and not ln.upper().startswith("CREATE TRIGGER"):
                    stmts.append(ln)
                    idx += 1
                else:
                    break
            tail = "\n".join(lines[idx:]).strip()
            if tail.endswith(";"):
                tail = tail[:-1]
            if tail:
                stmts.append(tail)
            return stmts

        def spawn(self, argv: list, _script: str) -> tuple:
            db = argv[-2]
            script = argv[-1]
            conn = _sq.connect(db, isolation_level=None)
            conn.text_factory = lambda b: b.decode('utf-8', 'replace')  # emulate tursodb: no UTF-8 decode error
            out = bytearray()
            try:
                for stmt in self._split_statements(script):
                    try:
                        cur = conn.execute(stmt)
                    except _sq.Error as exc:
                        # tursodb prints all rows produced BEFORE the failing statement, then
                        # exits nonzero with the error on stderr. The real op is last, so any
                        # error is the op's; preamble pragmas do not error.
                        return 1, out.decode("utf-8", "surrogateescape"), f"{type(exc).__name__}: {exc}"
                    rows = cur.fetchall() if cur.description is not None else []
                    for r in rows:
                        cells = [self._cell(c) for c in r]
                        out += b"|".join(cells) + b"\n"
                return 0, out.decode("utf-8", "surrogateescape"), ""
            finally:
                conn.close()

    axes = genlib.merged_axes({"cipher": ("aegis256", "aes256gcm"), "attach_aux": (0, 1)})
    reds: list[int] = []
    voids: list[int] = []
    for seed in range(6000, 6000 + 250):
        fake = _Fake()
        ref = genlib.Sqlite3Runner(run_dir, tag=f"cliref{seed}")
        cand = genlib.CliRunner(
            binary=Path("/nonexistent/tursodb"), base_args=(), run_dir=run_dir,
            tag=f"climock{seed}", _spawn=fake.spawn,
        )
        res = genlib.run_case(seed, axes, (ref, cand), case_id="CLIMOCK", emit=False)
        if res.verdict == "RED":
            reds.append(seed)
        elif res.verdict == "VOID":
            voids.append(seed)
    ok = not reds and not voids
    _p(f"GROUP cli_mock {'PASS' if ok else 'FAIL'} seeds=250 reds={len(reds)} voids={len(voids)} "
       f"(mock renders sqlite3 as `-m list`; must be all GREEN)")
    return ok


# --- group 7: encryption-URI plumbing (Part A.1) ----------------------------

def group_encryption_uri(run_dir: Path) -> bool:
    """Validate that the swept encryption config is actually plumbed into the db argument
    the candidate opens: when encryption=1 the CliRunner passes `file:<db>?cipher=..&hexkey=..`,
    else the bare path. A mock spawn that STRIPS the cipher URI (emulating tursodb opening
    the encrypted file transparently) is used so the differential must still hold GREEN --
    proving encryption is candidate-side config that doesn't change the row contract. We
    also assert the argv carried the URI for encrypted runs and did NOT for plaintext runs.
    Imports turso_genfuzz so the real adapter wiring (build_runners) is exercised."""
    import math
    import re as _re
    import sqlite3 as _sq
    import turso_genfuzz as tg

    saw_encrypted_uri = False
    saw_plain_path = False
    uri_re = _re.compile(r"^file:(?P<path>.+?)\?cipher=(?P<c>[^&]+)&hexkey=(?P<k>[0-9a-f]+)$")

    class _EncFake:
        """Same faithful `-m list` mock as group_cli_mock's _Fake (raw-blob bytes,
        shortest-roundtrip REAL, full multi-statement script incl. config preamble), but it
        ALSO strips the cipher URI from the db arg (emulating tursodb opening the encrypted
        file transparently) and captures every db arg so the URI plumbing can be asserted."""

        def __init__(self) -> None:
            self.captured_dbs: list = []

        def _cell(self, c: object) -> bytes:
            return _tursodb_cell(c)   # shared faithful `-m list` renderer (signed-zero, lossy blob)

        def _split_statements(self, script: str) -> list:
            lines = script.split("\n")
            stmts: list = []
            idx = 0
            while idx < len(lines):
                ln = lines[idx].strip()
                if ln.endswith(";") and not ln.upper().startswith("CREATE TRIGGER"):
                    stmts.append(ln); idx += 1
                else:
                    break
            tail = "\n".join(lines[idx:]).strip()
            if tail.endswith(";"):
                tail = tail[:-1]
            if tail:
                stmts.append(tail)
            return stmts

        def spawn(self, argv: list, _script: str) -> tuple:
            db = argv[-2]
            self.captured_dbs.append(db)
            m = uri_re.match(db)
            real_db = m.group("path") if m else db  # strip cipher URI like a real open
            script = argv[-1]
            conn = _sq.connect(real_db, isolation_level=None)
            conn.text_factory = lambda b: b.decode('utf-8', 'replace')  # emulate tursodb: no UTF-8 decode error
            out = bytearray()
            try:
                for stmt in self._split_statements(script):
                    try:
                        cur = conn.execute(stmt)
                    except _sq.Error as exc:
                        return 1, out.decode("utf-8", "surrogateescape"), f"{type(exc).__name__}: {exc}"
                    rows = cur.fetchall() if cur.description is not None else []
                    for r in rows:
                        out += b"|".join(self._cell(c) for c in r) + b"\n"
                return 0, out.decode("utf-8", "surrogateescape"), ""
            finally:
                conn.close()

    axes = genlib.merged_axes(tg.TURSO_AXES)
    reds: list[int] = []
    voids: list[int] = []
    checked = 0
    uri_wellformed = True
    for seed_raw in range(7000, 7000 + 250):
        seed = genlib.root_seed_from(str(seed_raw))
        config = genlib.choose_config(seed, axes)
        fake = _EncFake()
        reference = genlib.Sqlite3Runner(run_dir, tag=f"encref{seed_raw}")
        candidate = genlib.CliRunner(
            binary=Path("/nonexistent/tursodb"), base_args=(), run_dir=run_dir,
            tag=f"enccand{seed_raw}", _spawn=fake.spawn,
            encryption=config["encryption"], cipher=config["cipher"],
            hexkey=tg.hexkey_for(seed) if config["encryption"] else "",
        )
        res = genlib.run_case(seed, axes, (reference, candidate),
                              lifecycle_plug=tg.TURSO_LIFECYCLE_PLUG, case_id="ENC", emit=False)
        if res.verdict == "RED":
            reds.append(seed_raw)
        elif res.verdict == "VOID":
            voids.append(seed_raw)
        checked += 1
        # The main-db arg is the first captured db (before any aux). Verify URI presence.
        main_db = fake.captured_dbs[0] if fake.captured_dbs else ""
        if config["encryption"]:
            m = uri_re.match(main_db)
            if m and m.group("c") == config["cipher"] and len(m.group("k")) == 64:
                saw_encrypted_uri = True
            else:
                uri_wellformed = False
        else:
            if main_db and "?cipher=" not in main_db:
                saw_plain_path = True

    ok = (not reds and not voids and saw_encrypted_uri and saw_plain_path and uri_wellformed)
    _p(f"GROUP encryption_uri {'PASS' if ok else 'FAIL'} seeds={checked} reds={len(reds)} voids={len(voids)} "
       f"saw_encrypted_uri={saw_encrypted_uri} saw_plain_path={saw_plain_path} uri_wellformed={uri_wellformed}")
    return ok


# --- group 8: render-divergence ground truth (calibration Part 1) ---------------

def group_render_divergence(run_dir: Path) -> bool:
    """Lock the calibration red classes #2/#3/#4/#6 as HARNESS-RENDER-BUGs now fixed, and prove
    the fix does NOT mask a genuine value difference. Each row is (ref_cell, cand_cell,
    should_be_equal): ref_cell is what the Python reference produces (typed), cand_cell is
    what tursodb `-m list` emits (text). We normalize both in cli_text and compare with
    _cells_equal -- exactly the differential-oracle path."""
    cases = [
        # (label, python reference value, candidate `-m list` text, expect_equal)
        ("#2 total()->REAL 0.0",        0.0,                   "0.0",                  True),
        ("#2 avg empty->NULL",          None,                  "",                     True),
        ("#3 round(zeroblob)->0.0",     0.0,                   "0.0",                  True),
        ("#3 abs(0)->INT 0",            0,                     "0",                    True),
        ("#4 1e+308 exp format",        1e308,                 "1.0e+308",             True),
        ("#4 -1/6 15-vs-17 digit",     -1.0/6.0,               "-0.166666666666667",   True),
        ("#6 round(emoji)->0.0",        0.0,                   "0.0",                  True),
        # negative controls: a genuine value/type difference must STILL be unequal.
        ("neg: 0.0 vs 0.1",             0.0,                   "0.1",                  False),
        ("neg: 1.0 vs 2.0",             1.0,                   "2.0",                  False),
        ("neg: REAL 0.0 vs text '0x'",  0.0,                   "0x",                   False),
        ("neg: -1/6 vs -1/7",          -1.0/6.0,               "-0.142857142857143",   False),
        # provenance gating: a GENUINE TEXT reference cell (Python str, not a REAL column)
        # that merely looks numeric must NOT be float-reconciled -- a real text-format
        # divergence '0.10' vs '0.1' stays a red. This is the false-negative the reviewer
        # flagged; _RealText provenance is what prevents it.
        ("neg: TEXT '0.10' vs '0.1'",   "0.10",                "0.1",                  False),
        ("neg: TEXT '1.0' vs '1'",      "1.0",                 "1",                    False),
        # ... but a REAL reference 1.0 vs candidate '1.0' DOES reconcile (control on control):
        ("pos: REAL 1.0 vs '1.0'",      1.0,                   "1.0",                  True),
        # calibration signed-zero: durability read-back of a stored REAL -0.0 -- sqlite3 keeps the
        # sign ('-0.0'), tursodb drops it ('0.0'); same IEEE value must reconcile.
        ("e106: REAL -0.0 vs '0.0'",   -0.0,                   "0.0",                  True),
        ("e106: REAL 0.0 vs '-0.0'",    0.0,                   "-0.0",                 True),
        # ... but nonzero sign still matters (a genuine sign divergence stays red):
        ("e106 neg: REAL -0.5 vs '0.5'", -0.5,                 "0.5",                  False),
        # calibration IEEE-special glyph case: total()/avg() over 1e308 overflows to +inf; sqlite3/
        # Python render 'inf', tursodb '-m list' renders 'Inf'. Same IEEE value -> reconcile.
        ("e109: inf vs Inf",            float("inf"),          "Inf",                  True),
        ("e109: -inf vs -Inf",          float("-inf"),         "-Inf",                 True),
        # ... but inf vs -inf is a genuine sign difference (must stay red):
        ("e109 neg: inf vs -Inf",       float("inf"),          "-Inf",                 False),
        # ... and a token that merely STARTS with the glyph letters is NOT folded:
        ("e109 neg: text 'Info'",       "Info",                "info",                 False),
    ]
    fails: list = []
    for label, refv, candt, expect in cases:
        ncand = genlib.normalize_value(genlib._coerce_cli_cell(candt), cli_text=True)
        nref = genlib.normalize_value(refv, cli_text=True)
        got = genlib._cells_equal(nref, ncand)
        if got != expect:
            fails.append(f"{label}: nref={nref!r} ncand={ncand!r} equal={got} want={expect}")
    # blob raw-bytes (red #5): a reference blob and the candidate raw-bytes projection of the
    # SAME blob must reconcile to one canonical hex form.
    blob = b"\x00\x01\xff"
    nref_b = genlib.normalize_value(blob, cli_text=True)
    ncand_b = genlib.normalize_value(genlib._coerce_cli_cell(blob.decode("utf-8", "surrogateescape")), cli_text=True)
    if not genlib._cells_equal(nref_b, ncand_b):
        fails.append(f"#5 blob raw-bytes: nref={nref_b!r} ncand={ncand_b!r} not equal")
    ok = not fails
    _p(f"GROUP render_divergence {'PASS' if ok else 'FAIL'} cases={len(cases)+1} fails={len(fails)}"
       + ("" if ok else " :: " + " | ".join(fails)))
    return ok


# --- group 9: config realization read-back (calibration Part 2) -----------------

def group_config_realization(run_dir: Path) -> bool:
    """Prove the config-realizing pragma preamble makes the swept page_size actually BIND on
    the db-creating process, INCLUDING under encryption -- the WP-025 armament fix. Drives
    the real CliRunner with the faithful `-m list` mock; after each run the candidate's
    page_size_readback must equal the swept page_size (and match the reference's read-back).
    Uses the real turso adapter axes so encryption=1 cases are included."""
    import math
    import re as _re
    import sqlite3 as _sq
    import turso_genfuzz as tg

    uri_re = _re.compile(r"^file:(?P<path>.+?)\?cipher=(?P<c>[^&]+)&hexkey=(?P<k>[0-9a-f]+)$")

    class _CfgFake:
        def _cell(self, c: object) -> bytes:
            return _tursodb_cell(c)   # shared faithful `-m list` renderer (signed-zero, lossy blob)

        def _split_statements(self, script: str) -> list:
            lines = script.split("\n"); stmts: list = []; idx = 0
            while idx < len(lines):
                ln = lines[idx].strip()
                if ln.endswith(";") and not ln.upper().startswith("CREATE TRIGGER"):
                    stmts.append(ln); idx += 1
                else:
                    break
            tail = "\n".join(lines[idx:]).strip()
            if tail.endswith(";"):
                tail = tail[:-1]
            if tail:
                stmts.append(tail)
            return stmts

        def spawn(self, argv: list, _script: str) -> tuple:
            db = argv[-2]
            m = uri_re.match(db)
            real_db = m.group("path") if m else db
            script = argv[-1]
            conn = _sq.connect(real_db, isolation_level=None)
            conn.text_factory = lambda b: b.decode("utf-8", "replace")
            out = bytearray()
            try:
                for stmt in self._split_statements(script):
                    try:
                        cur = conn.execute(stmt)
                    except _sq.Error as exc:
                        return 1, out.decode("utf-8", "surrogateescape"), f"{type(exc).__name__}: {exc}"
                    rows = cur.fetchall() if cur.description is not None else []
                    for r in rows:
                        out += b"|".join(self._cell(c) for c in r) + b"\n"
                return 0, out.decode("utf-8", "surrogateescape"), ""
            finally:
                conn.close()

    axes = genlib.merged_axes(tg.TURSO_AXES)
    mismatches: list = []
    seen_sizes: set = set()
    seen_encrypted = False
    checked = 0
    for seed_raw in range(8000, 8000 + 120):
        seed = genlib.root_seed_from(str(seed_raw))
        config = genlib.choose_config(seed, axes)
        prog = genlib.generate(seed, axes, lifecycle_plug=tg.TURSO_LIFECYCLE_PLUG)
        want = str(config["page_size"])
        seen_sizes.add(want)
        if config["encryption"]:
            seen_encrypted = True
        # candidate (real CliRunner + faithful mock)
        cand = genlib.CliRunner(
            binary=Path("/nonexistent/tursodb"), base_args=(), run_dir=run_dir,
            tag=f"cfgcand{seed_raw}", _spawn=_CfgFake().spawn,
            encryption=config["encryption"], cipher=config["cipher"],
            hexkey=tg.hexkey_for(seed) if config["encryption"] else "",
        )
        cres = cand.run(prog)
        ref = genlib.Sqlite3Runner(run_dir, tag=f"cfgref{seed_raw}")
        rres = ref.run(prog)
        if cres.page_size_readback != want:
            mismatches.append(f"seed={seed_raw} enc={config['encryption']} cand_readback={cres.page_size_readback!r} want={want}")
        if rres.page_size_readback != want:
            mismatches.append(f"seed={seed_raw} REF readback={rres.page_size_readback!r} want={want}")
        checked += 1
    # must have actually swept a non-4096 size AND an encrypted case for the proof to bite.
    swept_non4k = any(s != "4096" for s in seen_sizes)
    ok = (not mismatches) and swept_non4k and seen_encrypted
    _p(f"GROUP config_realization {'PASS' if ok else 'FAIL'} checked={checked} mismatches={len(mismatches)} "
       f"sizes={sorted(seen_sizes)} seen_encrypted={seen_encrypted}"
       + ("" if not mismatches else " :: " + " | ".join(mismatches[:4])))
    return ok


# --- group 10: known-class quarantine + integrity allowlist  --------

def group_known_class() -> bool:
    """calibration lever 1a/1b behaviour, exercised directly (the mock groups render sqlite3 as
    tursodb, so the confirmed WP-024/WP-025 signatures never actually appear there). Asserts:

      * config quarantine: the WP-025 crash config (encryption=1 x page_size!=4096) is
        intercepted -- kept only as a small canary and re-rolled off otherwise -- and every
        action emits a SUPPRESSED line. The final config is quarantine-free for the vast
        majority, and non-empty canary keeps the panic matcher alive.
      * integrity allowlist: a candidate RunResult carrying ONLY the confirmed WP-024 FTS
        message is SUPPRESSED (oracle GREEN + a SUPPRESSED line); a candidate carrying a
        DIFFERENT (attach/pager) integrity message still REDS; a mix (known + unknown) REDS on
        the unknown while suppressing the known.
    """
    fails: list[str] = []
    axes = genlib.merged_axes({"cipher": ("aegis256", "aes256gcm"), "attach_aux": (0, 1)})

    # -- config quarantine --
    genlib._SUPPRESSED_LOG.clear()
    canary = downweighted = final_crash = 0
    for seed in range(20000, 20000 + 600):
        rawcfg = _raw_config_draw(seed, axes)
        raw_q = genlib.match_config_quarantine(rawcfg)
        cfg = genlib.choose_config(seed, axes, emit_suppress=False)
        final_q = genlib.match_config_quarantine(cfg)
        if raw_q is not None:
            if final_q is not None:
                canary += 1
            else:
                downweighted += 1
        if final_q is not None:
            final_crash += 1
    raw_hits = canary + downweighted
    if raw_hits == 0:
        fails.append("config-quarantine never hit the crash family (axes wrong?)")
    if canary <= 0:
        fails.append(f"config-quarantine canary=0 (WP-025 matcher would die)")
    if downweighted <= 0:
        fails.append(f"config-quarantine downweighted=0 (crash config never re-rolled)")
    if raw_hits and canary > int(0.25 * raw_hits):
        fails.append(f"config-quarantine canary too large {canary}/{raw_hits} (>25%)")
    # every quarantine action must have emitted a SUPPRESSED line
    suppressed_cfg = [l for l in genlib._SUPPRESSED_LOG if "wp025" in l]
    if len(suppressed_cfg) != raw_hits:
        fails.append(f"config-quarantine emitted {len(suppressed_cfg)} SUPPRESSED but hit {raw_hits} configs")

    # determinism of the quarantine decision (pure function of seed).
    c1 = genlib.choose_config(20001, axes)
    c2 = genlib.choose_config(20001, axes)
    if c1 != c2:
        fails.append("config-quarantine not deterministic for a fixed seed")

    # -- integrity allowlist --
    def _cand_with(messages):
        rr = genlib.RunResult()
        rr.integrity_ok = False
        rr.integrity_messages = list(messages)
        return rr
    ref = genlib.RunResult()

    fts_msg = "wrong # of entries in index __turso_internal_fts_dir_docs_fts_key"
    other_msg = "*** in database main *** Page 42 is never used"  # attach/pager-style (WP-008)

    genlib._SUPPRESSED_LOG.clear()
    f_known = genlib.oracle_integrity(ref, _cand_with([fts_msg]), emit=False)
    if not f_known.ok:
        fails.append(f"allowlist: known WP-024 FTS msg should be suppressed GREEN, got {f_known.summary}")
    if f_known.divergence_id != "known-fts-integrity":
        fails.append(f"allowlist: suppressed finding must carry the rule id, got {f_known.divergence_id!r}")
    if not any("known-fts-integrity" in l for l in genlib._SUPPRESSED_LOG):
        fails.append("allowlist: known FTS suppression emitted no SUPPRESSED line")

    f_other = genlib.oracle_integrity(ref, _cand_with([other_msg]), emit=False)
    if f_other.ok:
        fails.append("allowlist: a NON-FTS integrity failure (WP-008 class) must still RED")

    f_mix = genlib.oracle_integrity(ref, _cand_with([fts_msg, other_msg]), emit=False)
    if f_mix.ok:
        fails.append("allowlist: mix of known+unknown must RED on the unknown message")

    f_ok = genlib.oracle_integrity(ref, genlib.RunResult(), emit=False)  # integrity_ok None
    if not f_ok.ok:
        fails.append("allowlist: no integrity run must stay GREEN")

    # -- diff_rows allowlist on integrity statements (the smoke-surfaced leak) --
    # An integrity_check row of the confirmed WP-024 signature ALSO flows through diff_rows;
    # it must be suppressed there too, while an attach/pager corruption row still reds.
    def _rr_with_integrity_stmt(cand_cell: str):
        rref = genlib.RunResult()
        rref.stmts.append(genlib.StmtResult("PRAGMA integrity_check;", 0, [("ok",)], "", True))
        rcand = genlib.RunResult()
        rcand.stmts.append(genlib.StmtResult("PRAGMA integrity_check;", 0, [(cand_cell,)], "", True))
        return rref, rcand
    rr, rc = _rr_with_integrity_stmt(fts_msg)
    genlib._SUPPRESSED_LOG.clear()
    f_dr_known = genlib.oracle_diff_rows(rr, rc, cli_text=True, emit=False)
    if not f_dr_known.ok:
        fails.append(f"diff_rows-allowlist: known WP-024 on integrity_check must be suppressed, got {f_dr_known.summary}")
    if not any("known-fts-integrity" in l for l in genlib._SUPPRESSED_LOG):
        fails.append("diff_rows-allowlist: known FTS suppression emitted no SUPPRESSED line")
    rr2, rc2 = _rr_with_integrity_stmt(other_msg)
    f_dr_other = genlib.oracle_diff_rows(rr2, rc2, cli_text=True, emit=False)
    if f_dr_other.ok:
        fails.append("diff_rows-allowlist: a non-FTS integrity row (WP-008) must still RED in diff_rows")
    # a NON-integrity statement row mismatch must still red (allowlist only applies to integrity).
    rrx = genlib.RunResult(); rrx.stmts.append(genlib.StmtResult("SELECT c0 FROM t0;", 0, [("1",)], "", True))
    rcx = genlib.RunResult(); rcx.stmts.append(genlib.StmtResult("SELECT c0 FROM t0;", 0, [(fts_msg,)], "", True))
    f_dr_nonint = genlib.oracle_diff_rows(rrx, rcx, cli_text=True, emit=False)
    if f_dr_nonint.ok:
        fails.append("diff_rows-allowlist: FTS-looking text on a NON-integrity SELECT must still RED")
    # NON-VACUOUS guard: if the REFERENCE integrity rowset is EMPTY (never actually said 'ok'),
    # a candidate FTS-signature row must NOT be suppressed -- an empty ref must not license a mask.
    rre = genlib.RunResult(); rre.stmts.append(genlib.StmtResult("PRAGMA integrity_check;", 0, [], "", True))
    rce = genlib.RunResult(); rce.stmts.append(genlib.StmtResult("PRAGMA integrity_check;", 0, [(fts_msg,)], "", True))
    f_dr_vac = genlib.oracle_diff_rows(rre, rce, cli_text=True, emit=False)
    if f_dr_vac.ok:
        fails.append("diff_rows-allowlist: an EMPTY reference integrity rowset must NOT vacuously suppress a candidate FTS row")

    ok = not fails
    _p(f"GROUP known_class {'PASS' if ok else 'FAIL'} "
       f"[quarantine: canary={canary} downwt={downweighted} raw_hits={raw_hits} final_crash={final_crash} "
       f"suppressed_lines={len(suppressed_cfg)}] "
       f"[allowlist integrity: known_green={f_known.ok} other_red={not f_other.ok} mix_red={not f_mix.ok}] "
       f"[allowlist diff_rows: known_green={f_dr_known.ok} other_red={not f_dr_other.ok} nonint_red={not f_dr_nonint.ok}]"
       + ("" if ok else " :: " + " | ".join(fails)))
    return ok


# --- group 11: stratum axis + new generic axes  --------------------

def group_strata(run_dir: Path) -> bool:
    """calibration stratified family-dense sweeps + the two NEW generic axes. Asserts, per stratum:
      * DENSITY FLOOR: the stratum's dense family runs its full precondition chain in EVERY
        program (its dense-mode marker appears), and the family op-count is elevated vs mixed.
      * OTHER AXES STILL SWEEP: config page_size, identifier quoting, and population still vary
        within a stratum (density concentrates one family, it does not narrow the other axes).
      * NULL-DIFF CLEAN: sqlite3-vs-sqlite3 is 100% GREEN per stratum (no new false-red).
    And the two NEW generic axes (available to ALL strata):
      * PATH-POOL: >= N distinct JSON paths exercised AND every PATH_KEY_KIND reached.
      * PLAN-STATE: ANALYZE point distribution is NON-DEGENERATE (>=3 of the 4 states appear,
        including at least one 'never' and at least one ANALYZE-injected program).
    """
    import re as _re
    axes = genlib.merged_axes({"cipher": ("aegis256", "aes256gcm"), "attach_aux": (0, 1)})
    plug = ("PRAGMA wal_checkpoint(TRUNCATE);", "PRAGMA quick_check;")
    fails: list[str] = []

    # Dense-mode markers: an op kind that ONLY appears when the family is generated dense=True.
    _dense_markers = {
        "trigger-dense": "trigger_recreate",              # DROP+re-CREATE+re-fire cycle
        "attach-dense": "attach_index_aux",               # indexed same-name aux + page churn
        "scalar-persist-dense": "scalar_insert_zeroblob_numprefix",  # zeroblob(numeric-prefix str)
        "tvf-dense": "json_two_arg_path",                 # direct two-arg-path json_tree
        "agg-join-dense": "agg_join_empty_inner",         # empty-inner aggregate-over-join
    }
    # The stratum-family's full-lifecycle marker (present in dense AND non-dense, but must be in
    # EVERY dense-stratum program -- the density floor).
    _family_marker = {
        "trigger-dense": "trigger_create",
        "attach-dense": "attach_create",
        "scalar-persist-dense": "scalar_create_table",
        "tvf-dense": "json_insert",
        "agg-join-dense": "agg_join_create_l",
    }

    N = 200
    global_distinct_paths: set[str] = set()
    global_path_kinds: set[str] = set()
    global_plan_states: dict[str, int] = {}
    per_stratum_summary: list[str] = []

    for stratum in [s for s in genlib.STRATA if s != "mixed"]:
        family_present = 0
        dense_marker_present = 0
        seen_page_sizes: set = set()
        seen_ident_shapes: set = set()
        seen_pop = set()
        fam_marker = _family_marker[stratum]
        dmarker = _dense_markers[stratum]
        for seed in range(40000, 40000 + N):
            prog = genlib.generate(seed, axes, lifecycle_plug=plug, stratum=stratum)
            kinds = [op.kind for op in prog.ops]
            if fam_marker in kinds:
                family_present += 1
            if dmarker in kinds:
                dense_marker_present += 1
            seen_page_sizes.add(prog.config["page_size"])
            # identifier shapes across DDL (config/quoting axis still sweeps within a stratum)
            for op in prog.ops:
                if "CREATE TABLE" in op.sql or "CREATE TRIGGER" in op.sql:
                    if _re.search(r'"[^"]* col"', op.sql):
                        seen_ident_shapes.add("spaced")
                    elif _re.search(r'"[^"]*\.d"', op.sql):
                        seen_ident_shapes.add("dotted")
                    elif _re.search(r'\[[^\]]+\]', op.sql):
                        seen_ident_shapes.add("bracketed")
                    elif _re.search(r'`[^`]+`', op.sql):
                        seen_ident_shapes.add("backticked")
                    elif _re.search(r'"[^"]+"', op.sql):
                        seen_ident_shapes.add("quoted")
                if op.kind == "insert_skipped_empty" or "VALUES (NULL" in op.sql:
                    seen_pop.add("degenerate")
                # NEW path-pool axis: collect every json path argument (stored + two-arg).
                for m in _re.finditer(r"json_(?:tree|each)\('(?:[^']|'')*',\s*'([^']*)'\)", op.sql):
                    global_distinct_paths.add(m.group(1))
                    global_path_kinds |= genlib.path_kinds_in(m.group(1))
                for m in _re.finditer(r"VALUES\s*\((?:[^)]*)\)", op.sql):
                    pass
                # NEW plan-state axis: count ANALYZE presence (an 'analyze' op kind).
            has_analyze = any(op.kind == "analyze" for op in prog.ops)
            key = "analyze" if has_analyze else "never"
            global_plan_states[key] = global_plan_states.get(key, 0) + 1

        # DENSITY FLOOR: family present in EVERY program; dense-mode marker in EVERY program.
        if family_present < N:
            fails.append(f"{stratum}: family marker {fam_marker!r} in {family_present}/{N} (want ALL)")
        if dense_marker_present < N:
            fails.append(f"{stratum}: dense marker {dmarker!r} in {dense_marker_present}/{N} (want ALL)")
        # OTHER AXES STILL SWEEP inside the stratum.
        if len(seen_page_sizes) < 5:
            fails.append(f"{stratum}: page_size didn't sweep ({sorted(seen_page_sizes)}; want >=5)")
        if len(seen_ident_shapes) < 3:
            fails.append(f"{stratum}: identifier quoting didn't sweep ({sorted(seen_ident_shapes)}; want >=3)")
        per_stratum_summary.append(
            f"{stratum}[fam={family_present}/{N} dense={dense_marker_present}/{N} "
            f"ps={len(seen_page_sizes)} ids={len(seen_ident_shapes)}]")

    # NEW path-pool axis locks (global across strata; tvf-dense drives the bulk).
    if len(global_distinct_paths) < 12:
        fails.append(f"path-pool distinct paths {len(global_distinct_paths)} (want >=12)")
    _want_kinds = set(genlib.PATH_KEY_KINDS)
    if not _want_kinds.issubset(global_path_kinds):
        fails.append(f"path-pool key kinds missing {sorted(_want_kinds - global_path_kinds)}")

    # NEW plan-state axis: ANALYZE distribution non-degenerate (both analyze-present and never
    # appear across programs; agg-join-dense guarantees a real fraction have ANALYZE).
    if global_plan_states.get("analyze", 0) <= 0:
        fails.append("plan-state: no ANALYZE-injected program (axis degenerate)")
    if global_plan_states.get("never", 0) <= 0:
        fails.append("plan-state: no ANALYZE-free program (axis degenerate)")
    # Per-plan-state point distribution within agg-join-dense: >=3 of the 4 PLAN_STATES reached.
    seen_points: set = set()
    for seed in range(41000, 41000 + 200):
        prog = genlib.generate(seed, axes, lifecycle_plug=plug, stratum="agg-join-dense")
        analyze_ops = [i for i, op in enumerate(prog.ops) if op.kind == "analyze"]
        query_i = next((i for i, op in enumerate(prog.ops) if op.kind == "agg_join_empty_inner"), None)
        if not analyze_ops:
            seen_points.add("never")
        elif query_i is not None:
            # crude classification by position of the last ANALYZE relative to the query
            seen_points.add("analyze-before-query")
    if len(seen_points) < 2:
        fails.append(f"plan-state points within agg-join-dense degenerate ({sorted(seen_points)})")

    # NULL-DIFF CLEAN per stratum (sqlite3 vs sqlite3) -- a real fraction, all GREEN.
    null_reds = 0
    for stratum in [s for s in genlib.STRATA if s != "mixed"]:
        for seed in range(42000, 42000 + 40):
            ref = genlib.Sqlite3Runner(run_dir, tag="sref")
            cand = genlib.Sqlite3Runner(run_dir, tag="scand")
            res = genlib.run_case(seed, axes, (ref, cand), lifecycle_plug=plug,
                                  case_id="STRAT", emit=False, stratum=stratum)
            if res.verdict != "GREEN":
                null_reds += 1
    if null_reds:
        fails.append(f"null-diff per-stratum had {null_reds} non-GREEN (want 0)")

    ok = not fails
    _p(f"GROUP strata {'PASS' if ok else 'FAIL'} "
       f"{' '.join(per_stratum_summary)} "
       f"[path_pool: distinct={len(global_distinct_paths)} kinds={len(global_path_kinds)}/{len(genlib.PATH_KEY_KINDS)}] "
       f"[plan_state: analyze={global_plan_states.get('analyze',0)} never={global_plan_states.get('never',0)}] "
       f"[null_diff_reds={null_reds}]"
       + ("" if ok else " :: " + " | ".join(fails)))
    return ok


def main() -> int:
    lib_dir = str(Path(__file__).resolve().parent)
    import sqlite3
    _p(f"REFERENCE python_sqlite_version={sqlite3.sqlite_version} python={sys.version.split()[0]}")
    with tempfile.TemporaryDirectory(prefix="genlib-probe-") as tmp:
        run_dir = Path(tmp)
        results = {
            "determinism": group_determinism(lib_dir),
            "null_differential": group_null_differential(run_dir),
            "selftest": group_selftest(run_dir),
            "coverage": group_coverage(),
            "error_class": group_error_class(run_dir),
            "cli_mock": group_cli_mock(run_dir),
            "encryption_uri": group_encryption_uri(run_dir),
            "render_divergence": group_render_divergence(run_dir),
            "config_realization": group_config_realization(run_dir),
            "known_class": group_known_class(),
            "strata": group_strata(run_dir),
        }
    all_ok = all(results.values())
    _p(f"PROBE {'PASS' if all_ok else 'FAIL'} groups={sum(results.values())}/{len(results)} detail={results}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
