#!/usr/bin/env python3
"""check.py -- the strict format compiler for the .workers/ v2 tree.

Enforces rules G1-G11 from CONTRACT.md over a `.workers/` tree, and derives
the dispatcher-v2 status row plus the stop-blockers (v0.1.5 six + v0.1.6
aim-debt + v0.1.8 anti-monoculture breadth floor) (--status) or
rewrites the generated block of candidates.md (--emit). Python 3.12 stdlib
only; no third-party YAML.

This file ships as lib/check.py and is copied to `.workers/check.py` at init.
It imports frontmatter from the lib/ next to the .workers root (the directory
containing this script), falling back to the script's own directory so it also
runs in-place during development.

    check.py [--root DIR] [--status] [--emit]

Default root is the directory containing the script (so it works as
.workers/check.py); --root overrides it for tests. Exit 0 clean, 2 on any
G-failure.
"""
from __future__ import annotations

import argparse
import ast
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
for _cand in (os.path.join(_SCRIPT_DIR, "lib"), _SCRIPT_DIR):
    if os.path.exists(os.path.join(_cand, "frontmatter.py")):
        if _cand not in sys.path:
            sys.path.insert(0, _cand)
        break
import frontmatter as fm  # noqa: E402

API_EXPLORER = "api-explorer"
CONTRACT_ABUSER = "contract-abuser"
BUILTIN_PERSONAS = (API_EXPLORER, CONTRACT_ABUSER)
RUNGS = ("L0", "L1", "L2", "L3", "L4")
MODALITIES = ("sync", "async", "threaded")
SOURCES = ("usage", "api-floor")
PARK_PREFIX = "park:"
AUDIT_TAG = "[audited"
DEFAULT_API_FLOOR_SHARE = 0.3
DEFAULT_EVENT_MIN_AMP = 10
DEFAULT_CLUSTER_BREADTH = 3
DEFAULT_CLUSTER_CAP = 3
EMIT_BEGIN = "<!-- emit:begin -->"
EMIT_END = "<!-- emit:end -->"


# --------------------------------------------------------------------------- #
# tree loading
# --------------------------------------------------------------------------- #
def _read(path: str) -> str | None:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def load_model(root: str):
    """Return (meta, error_or_None) for usage-model.md."""
    path = os.path.join(root, "usage-model.md")
    if not os.path.exists(path):
        return {}, "usage-model.md missing"
    try:
        meta, _ = fm.load(path)
        return meta, None
    except ValueError as e:
        return {}, str(e)


def load_dir(root: str, sub: str):
    """List of (relpath, meta_or_None, body_or_None, parse_error_or_None), sorted."""
    d = os.path.join(root, sub)
    out = []
    if not os.path.isdir(d):
        return out
    for name in sorted(os.listdir(d)):
        if not name.endswith(".md"):
            continue
        rel = f"{sub}/{name}"
        try:
            meta, body = fm.load(os.path.join(d, name))
            out.append((rel, meta, body, None))
        except ValueError as e:
            out.append((rel, None, None, str(e)))
    return out


def _present(v) -> bool:
    if v is None:
        return False
    if isinstance(v, (list, dict, str)) and len(v) == 0:
        return False
    return True


# --------------------------------------------------------------------------- #
# flows/flows_<target>.py -- parsed by ast, never imported
# --------------------------------------------------------------------------- #
def parse_flows_module(source: str):
    """Return (flows_dict, classes) or raise SyntaxError.

    flows_dict: {dict_key: class_name_or_None} from `FLOWS = {...}`.
    classes:    {class_name: key_string_or_None} for every ClassDef.
    """
    tree = ast.parse(source)
    classes: dict[str, str | None] = {}
    flows_dict: dict[str, str | None] = {}

    def record_flows(value):
        if isinstance(value, ast.Dict):
            for k, v in zip(value.keys, value.values):
                if isinstance(k, ast.Constant) and isinstance(k.value, str):
                    cname = v.id if isinstance(v, ast.Name) else None
                    flows_dict[k.value] = cname

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            key_val = None
            for stmt in node.body:
                targets = []
                if isinstance(stmt, ast.Assign):
                    targets = stmt.targets
                elif isinstance(stmt, ast.AnnAssign):
                    targets = [stmt.target]
                for t in targets:
                    if isinstance(t, ast.Name) and t.id == "key":
                        val = stmt.value
                        if isinstance(val, ast.Constant) and isinstance(val.value, str):
                            key_val = val.value
            classes[node.name] = key_val
        elif isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == "FLOWS" for t in node.targets):
                record_flows(node.value)
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == "FLOWS" and node.value:
                record_flows(node.value)
    return flows_dict, classes


# --------------------------------------------------------------------------- #
# G8/G11 helper (shared with --status orphan counts)
# --------------------------------------------------------------------------- #
def check_covermap(entries, model_flow_keys, label):
    """Return (errors, orphan_count) for a covered-by/parked entry list
    (modules G8, surfaces G11). errors are detail strings."""
    errors = []
    orphans = 0
    for entry in entries or []:
        if not isinstance(entry, dict):
            errors.append(f"{label} entry is not a mapping: {entry!r}")
            orphans += 1
            continue
        name = entry.get("name", "?")
        cb = entry.get("covered-by")
        parked = entry.get("parked")
        if cb is None and parked is None:
            errors.append(f"{label} {name!r} has neither covered-by nor parked")
            orphans += 1
            continue
        if cb is not None:
            if isinstance(cb, list):
                for fk in cb:
                    if fk not in model_flow_keys:
                        errors.append(f"{label} {name!r} covered-by flow {fk!r} not in model")
                        orphans += 1
            elif cb in BUILTIN_PERSONAS:
                pass
            elif cb not in model_flow_keys:
                errors.append(f"{label} {name!r} covered-by flow {cb!r} not in model")
                orphans += 1
    return errors, orphans


def check_modules(modules, model_flow_keys):
    return check_covermap(modules, model_flow_keys, "module")


# --------------------------------------------------------------------------- #
# journal config (## config section: `key: value` lines)
# --------------------------------------------------------------------------- #
def journal_config(root: str) -> dict:
    text = _read(os.path.join(root, "journal.md"))
    if text is None:
        return {}
    cfg: dict = {}
    in_config = False
    for ln in text.splitlines():
        if ln.startswith("## "):
            in_config = ln.strip() == "## config"
            continue
        if not in_config:
            continue
        s = ln.strip().lstrip("- ").strip()
        if ":" in s:
            k, _, v = s.partition(":")
            cfg[k.strip()] = v.strip()
    return cfg


def _cfg_float(cfg, key, default):
    try:
        return float(cfg.get(key, default))
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- #
# the G-check
# --------------------------------------------------------------------------- #
def run_check(root: str):
    """Return (errors, n_scenarios, n_flows). errors: list of (gnum, relpath, detail)."""
    errors: list[tuple[int, str, str]] = []

    def err(n, path, detail):
        errors.append((n, path, detail))

    model, model_err = load_model(root)
    if model_err:
        err(9, "usage-model.md", model_err)

    personas = model.get("personas") or {}
    flows = model.get("flows") or {}
    events = model.get("events") or {}
    modules = model.get("modules") or []
    target = model.get("target")

    model_flow_keys = set(flows.keys())
    model_js_flows = {
        fk: fv[3:]
        for fk, fv in flows.items()
        if isinstance(fv, str) and fv.startswith("js:")
    }
    model_nonjs_flows = model_flow_keys - set(model_js_flows)

    scenarios = load_dir(root, "scenarios")
    findings = load_dir(root, "findings")

    # G9: parse failures
    for rel, meta, _body, perr in scenarios + findings:
        if perr is not None:
            err(9, rel, f"frontmatter failed to parse: {perr}")

    good_scen = [(rel, meta) for rel, meta, _b, perr in scenarios if perr is None]
    good_find = [(rel, meta) for rel, meta, _b, perr in findings if perr is None]

    # ---- G1: scenario flows / cast personas / event exist in the model ----
    for rel, meta in good_scen:
        for fk in meta.get("flows") or []:
            if fk not in model_flow_keys:
                err(1, rel, f"flow {fk!r} not in usage-model.md")
        for persona in (meta.get("cast") or {}).keys():
            if persona not in personas:
                err(1, rel, f"persona {persona!r} not in usage-model.md")
        event = meta.get("event")
        if isinstance(event, dict) and "key" in event:
            if event["key"] not in events:
                err(1, rel, f"event {event['key']!r} not in usage-model.md")

    # ---- G2: FLOWS registry <-> model flow bijection ----
    flows_rel = f"flows/flows_{target}.py" if target else "flows/flows_<target>.py"
    if not target:
        err(2, flows_rel, "usage-model.md has no target")
    else:
        flows_path = os.path.join(root, flows_rel)
        source = _read(flows_path)
        if source is None:
            err(2, flows_rel, "flow module missing")
        else:
            try:
                flows_dict, classes = parse_flows_module(source)
            except SyntaxError as e:
                err(2, flows_rel, f"syntax error: {e}")
                flows_dict, classes = {}, {}
            for dk, cname in flows_dict.items():
                if cname is None:
                    err(2, flows_rel, f"FLOWS[{dk!r}] value is not a class name")
                elif cname not in classes:
                    err(2, flows_rel, f"FLOWS[{dk!r}] references undefined class {cname}")
                else:
                    kv = classes[cname]
                    if kv is None:
                        err(2, flows_rel, f"class {cname} has no key attribute")
                    elif kv != dk:
                        err(2, flows_rel, f"FLOWS key {dk!r} != class {cname}.key {kv!r}")
            registry_keys = set(flows_dict.keys())
            for k in sorted(registry_keys - model_nonjs_flows):
                err(2, flows_rel, f"flow {k!r} in FLOWS but not in model")
            for k in sorted(model_nonjs_flows - registry_keys):
                err(2, flows_rel, f"model flow {k!r} missing from FLOWS registry")
        for fk, path in sorted(model_js_flows.items()):
            if not os.path.exists(os.path.join(root, path)):
                err(2, "usage-model.md", f"js driver path {path!r} for flow {fk!r} missing")

    # ---- G3: every flow has >=1 invariant; scenario invariants covered ----
    flow_invariants: dict[str, list] = {}
    for fk, fv in flows.items():
        if fk in model_js_flows:
            flow_invariants[fk] = []
            continue
        inv = fv.get("invariants") if isinstance(fv, dict) else None
        flow_invariants[fk] = list(inv) if inv else []
        if not flow_invariants[fk]:
            err(3, "usage-model.md", f"flow {fk!r} carries no invariants")
    for rel, meta in good_scen:
        covered: set = set()
        for fk in meta.get("flows") or []:
            covered.update(flow_invariants.get(fk, []))
        for inv in meta.get("invariants") or []:
            if inv not in covered:
                err(3, rel, f"invariant {inv!r} not provided by any of the scenario's flows")

    # ---- G4: ready|done requires cast, flows, depth, story, invariants,
    # ----     modality, source ----
    for rel, meta in good_scen:
        if meta.get("status") in ("ready", "done"):
            for field in ("cast", "flows", "depth", "story", "invariants",
                          "modality", "source"):
                if not _present(meta.get(field)):
                    err(4, rel, f"status {meta.get('status')} requires non-empty {field!r}")

    # ---- G5 (HARD): done + green requires non-null redproof ----
    for rel, meta in good_scen:
        if meta.get("status") == "done" and meta.get("result") == "green":
            if meta.get("redproof") in (None, "", "null"):
                err(5, rel, "status done + result green requires a non-null redproof")

    # ---- G6: persona citations; event amplification + citation ----
    for pname, pdata in personas.items():
        if pname in BUILTIN_PERSONAS:
            continue
        cit = pdata.get("citation") if isinstance(pdata, dict) else None
        if not _present(cit):
            err(6, "usage-model.md", f"persona {pname!r} weight has no citation")
    for ename, edata in events.items():
        if not isinstance(edata, dict) or not _present(edata.get("amplification")):
            err(6, "usage-model.md", f"event {ename!r} missing amplification")
        if not isinstance(edata, dict) or not _present(edata.get("citation")):
            err(6, "usage-model.md", f"event {ename!r} missing citation")

    # ---- G7: key uniqueness; findings reference existing scenario keys ----
    scen_keys: dict[str, str] = {}
    seen: dict[str, str] = {}
    for rel, meta in good_scen:
        key = meta.get("key")
        if key is not None:
            if key in seen:
                err(7, rel, f"duplicate key {key!r} (already in {seen[key]})")
            else:
                seen[key] = rel
            scen_keys[key] = rel
    for rel, meta in good_find:
        key = meta.get("key")
        if key is not None:
            if key in seen:
                err(7, rel, f"duplicate key {key!r} (already in {seen[key]})")
            else:
                seen[key] = rel
        sref = meta.get("scenario")
        if not _present(sref):
            err(7, rel, "finding has no scenario: frontmatter key")
        elif sref not in scen_keys:
            err(7, rel, f"finding scenario {sref!r} names no existing scenario key")

    # ---- G8: module floor ----
    for detail in check_modules(modules, model_flow_keys)[0]:
        err(8, "usage-model.md", detail)

    # ---- G10: sampling axes -- flow modalities declared; scenario
    # ----      modality/source values valid ----
    for fk, fv in flows.items():
        if fk in model_js_flows:
            continue
        mods = fv.get("modalities") if isinstance(fv, dict) else None
        if not isinstance(mods, dict) or not mods:
            err(10, "usage-model.md",
                f"flow {fk!r} declares no modalities: (each of {'/'.join(MODALITIES)} "
                f"must be 'plan' or 'park: <reason>')")
            continue
        for m in MODALITIES:
            v = mods.get(m)
            if v is None:
                err(10, "usage-model.md", f"flow {fk!r} modality {m!r} undeclared")
            elif v == "plan":
                pass
            elif isinstance(v, str) and v.startswith(PARK_PREFIX):
                if len(v[len(PARK_PREFIX):].strip()) < 4:
                    err(10, "usage-model.md",
                        f"flow {fk!r} modality {m!r} park has no reason")
            else:
                err(10, "usage-model.md",
                    f"flow {fk!r} modality {m!r} must be 'plan' or 'park: <reason>', "
                    f"got {v!r}")
        for m in mods:
            if m not in MODALITIES:
                err(10, "usage-model.md", f"flow {fk!r} unknown modality {m!r}")
    for rel, meta in good_scen:
        if meta.get("status") not in ("ready", "done"):
            continue
        mod = meta.get("modality")
        if mod is not None and mod not in MODALITIES:
            err(10, rel, f"modality {mod!r} not one of {MODALITIES}")
        src = meta.get("source")
        if src is not None and src not in SOURCES:
            err(10, rel, f"source {src!r} not one of {SOURCES}")

    # ---- G11: documented-surface census entries well-formed ----
    surfaces = model.get("surfaces") or []
    for detail in check_covermap(surfaces, model_flow_keys, "surface")[0]:
        err(11, "usage-model.md", detail)

    # ---- G9: journal.md exists with a ## config line ----
    journal_path = os.path.join(root, "journal.md")
    jtext = _read(journal_path)
    if jtext is None:
        err(9, "journal.md", "journal.md missing")
    elif not any(ln.startswith("## config") for ln in jtext.splitlines()):
        err(9, "journal.md", "journal.md has no '## config' section")

    return errors, len(scenarios), len(flows)


# --------------------------------------------------------------------------- #
# --status
# --------------------------------------------------------------------------- #
def _candidate_backlog_rows(root: str) -> int:
    text = _read(os.path.join(root, "candidates.md"))
    if text is None:
        return 0
    idx = text.find(EMIT_END)
    tail = text[idx + len(EMIT_END):] if idx != -1 else text
    return sum(1 for ln in tail.splitlines() if ln.startswith("| "))


def _journal_has_trigger(root: str) -> bool:
    text = _read(os.path.join(root, "journal.md"))
    if text is None:
        return False
    return any(ln.strip().startswith("trigger: model-refresh") for ln in text.splitlines())


def stop_blockers(root: str, model: dict, smetas: list) -> list[str]:
    """The stop gates (v0.1.5 six + the v0.1.6 aim-debt gate + the v0.1.8
    anti-monoculture breadth floor). Row 1 (stop) cannot fire while any
    blocker holds; --status prints them so episodes aim at exactly what is
    open. All computed from done scenarios + the model — no memory, no
    judgment."""
    cfg = journal_config(root)
    flows = model.get("flows") or {}
    events = model.get("events") or {}
    modules = model.get("modules") or []
    surfaces = model.get("surfaces") or []
    model_flow_keys = set(flows.keys())
    js_flows = {
        fk for fk, fv in flows.items()
        if isinstance(fv, str) and fv.startswith("js:")
    }
    done = [m for m in smetas if m.get("status") == "done"]
    blockers: list[str] = []

    # (1) modality parity: every planned flow x modality has a done scenario
    for fk, fv in flows.items():
        if fk in js_flows or not isinstance(fv, dict):
            continue
        mods = fv.get("modalities")
        mods = mods if isinstance(mods, dict) else {"sync": "plan"}
        for m in MODALITIES:
            if mods.get(m) != "plan":
                continue
            hit = any(
                fk in (d.get("flows") or []) and (d.get("modality") or "sync") == m
                for d in done
            )
            if not hit:
                blockers.append(f"modality: flow {fk!r} {m} planned, no done scenario")

    # (2) documented-surface census: non-empty and zero orphans
    if not surfaces:
        blockers.append("census: usage-model.md has no surfaces: (documented-API census)")
    else:
        n_orph = check_covermap(surfaces, model_flow_keys, "surface")[1]
        if n_orph:
            blockers.append(f"census: {n_orph} surface orphan(s) (no covered-by/parked)")

    # (3) api-floor share is binding, not advisory
    share = _cfg_float(cfg, "api-floor-share", DEFAULT_API_FLOOR_SHARE)
    if done:
        af = sum(1 for d in done if d.get("source") == "api-floor")
        if af < share * len(done):
            blockers.append(
                f"api-floor: {af}/{len(done)} done scenarios (share {share} binding)")

    # (4) event coverage: modeled amplified events must be exercised
    min_amp = _cfg_float(cfg, "event-min-amp", DEFAULT_EVENT_MIN_AMP)
    for ename, edata in events.items():
        if not isinstance(edata, dict):
            continue
        if _present(edata.get("parked")):
            continue
        try:
            amp = float(edata.get("amplification") or 0)
        except (TypeError, ValueError):
            amp = 0
        if amp < min_amp:
            continue
        hit = any(
            isinstance(d.get("event"), dict) and d["event"].get("key") == ename
            for d in done
        )
        if not hit:
            blockers.append(f"event: {ename!r} (amp {amp:g}) has no done scenario")

    # (5) misuse floor: the contract-abuser persona must have fired
    if model_flow_keys:
        hit = any(CONTRACT_ABUSER in (d.get("cast") or {}) for d in done)
        if not hit:
            blockers.append(f"misuse: no done scenario casts {CONTRACT_ABUSER!r}")

    # (6) park audit: every park carries the strategy-critic audit tag
    def _park_audited(where, reason):
        if isinstance(reason, str) and AUDIT_TAG not in reason:
            blockers.append(f"park-audit: {where} park lacks '{AUDIT_TAG} eN]' tag")

    for entry in list(modules) + list(surfaces):
        if isinstance(entry, dict) and _present(entry.get("parked")):
            _park_audited(f"{entry.get('name', '?')!r}", entry.get("parked"))
    for fk, fv in flows.items():
        if isinstance(fv, dict) and isinstance(fv.get("modalities"), dict):
            for m, v in fv["modalities"].items():
                if isinstance(v, str) and v.startswith(PARK_PREFIX):
                    _park_audited(f"flow {fk!r} modality {m}", v)
    for ename, edata in events.items():
        if isinstance(edata, dict) and _present(edata.get("parked")):
            _park_audited(f"event {ename!r}", edata.get("parked"))

    # (7) aim-debt gate: a mapped surface whose covering flow carries a live
    #     oracle, and which has been baselined green but never attacked. An
    #     un-falsified promise is not coverage — the producer owes an attacking
    #     scenario (L1+) before spending budget on another baseline/green
    #     control. This ranks the next episode onto (mapped AND oracle-exists
    #     AND not-yet-aimed); the natural draw-down for an interaction surface
    #     is an L2. Computed from done scenarios + the model — no judgment.
    attack_rungs = tuple(r for r in RUNGS if r != "L0")
    mapped_oracle_flows: set = set()
    for entry in surfaces:
        if not isinstance(entry, dict) or _present(entry.get("parked")):
            continue
        cb = entry.get("covered-by")
        for fk in (cb if isinstance(cb, list) else [cb]):
            fv = flows.get(fk)
            if (isinstance(fk, str) and fk not in js_flows
                    and isinstance(fv, dict) and fv.get("invariants")):
                mapped_oracle_flows.add(fk)
    for fk in sorted(mapped_oracle_flows):
        baselined = any(
            fk in (d.get("flows") or []) and d.get("rung") == "L0" for d in done)
        attacked = any(
            fk in (d.get("flows") or []) and d.get("rung") in attack_rungs
            for d in done)
        if baselined and not attacked:
            blockers.append(
                f"aim-debt: flow {fk!r} baselined green, no attacking scenario "
                f"(L1+ owed before a new baseline)")

    # (8) anti-monoculture breadth floor before depth-collapse. A BRAKE that
    #     composes with the aim-debt gate (7): aim-debt owes the *first*
    #     attacker on each flow; this caps how far ONE flow may be deepened
    #     before breadth is spread. A "cluster" is a flow (subsystem); an
    #     "attacking" scenario is a done scenario at rung L1+ on that flow.
    #     Breadth-before-depth: no cluster may be DEEPENED (carry a 2nd+
    #     attacking scenario) until >=K distinct clusters each carry >=1
    #     attacker; and a per-cluster episode budget caps total attackers per
    #     cluster. K is bounded by the attackable universe (mapped, oracle'd
    #     flows) so a small repo is never blocked by an unreachable floor.
    #     Pure function of done scenarios + the flow lattice — no memory, no
    #     judgment, no attention/realness scoring (that deeper change is held).
    attack_counts: dict[str, int] = {}
    for d in done:
        if d.get("rung") in attack_rungs:
            for fk in (d.get("flows") or []):
                if isinstance(fk, str) and fk not in js_flows:
                    attack_counts[fk] = attack_counts.get(fk, 0) + 1
    breadth = sum(1 for n in attack_counts.values() if n >= 1)
    attackable = len(mapped_oracle_flows)
    k_floor = int(min(
        _cfg_float(cfg, "cluster-breadth-floor", DEFAULT_CLUSTER_BREADTH),
        attackable))
    cap = _cfg_float(cfg, "cluster-attack-cap", DEFAULT_CLUSTER_CAP)
    for fk in sorted(attack_counts):
        n = attack_counts[fk]
        if n >= 2 and breadth < k_floor:
            blockers.append(
                f"anti-monoculture: flow {fk!r} deepened ({n} attackers) but "
                f"only {breadth}/{k_floor} distinct clusters attacked "
                f"(spread breadth before depth)")
        if cap and n > cap:
            blockers.append(
                f"cluster-budget: flow {fk!r} has {n} attacking scenarios "
                f"(per-cluster cap {cap:g})")

    return blockers


def compute_status(root: str):
    """Return (row, reason, blockers). Rows evaluated 1..6, first match wins."""
    model, _ = load_model(root)
    flows = model.get("flows") or {}
    modules = model.get("modules") or []
    model_flow_keys = set(flows.keys())

    smetas = [meta for _r, meta, _b, perr in load_dir(root, "scenarios") if perr is None]
    fmetas = [meta for _r, meta, _b, perr in load_dir(root, "findings") if perr is None]

    running = [m for m in smetas if m.get("status") == "running"]
    ready = [m for m in smetas if m.get("status") == "ready"]
    done = [m for m in smetas if m.get("status") == "done"]

    crystallized = {m.get("scenario") for m in fmetas}
    uncryst = [
        m for m in smetas
        if m.get("result") == "finding" and m.get("key") not in crystallized
    ]

    def flow_done(fk):
        return any(fk in (m.get("flows") or []) for m in done)

    _, orphans = check_modules(modules, model_flow_keys)
    all_flows_done = bool(model_flow_keys) and all(flow_done(fk) for fk in model_flow_keys)
    blockers = stop_blockers(root, model, smetas)

    # Row 1 (stop) is checked first, but only fires when its full condition holds
    # AND every v0.1.5 stop gate is clear.
    if (not ready and not running and not uncryst and all_flows_done
            and orphans == 0 and not blockers):
        return 1, "stop: flows done, findings clear, modules covered, gates clear", blockers
    if running:
        return 2, f"in-flight: scenario {running[0].get('key')!r} running", blockers
    if uncryst:
        return (3, f"crystallize: finding for scenario {uncryst[0].get('key')!r} not written",
                blockers)
    if _candidate_backlog_rows(root) < 5 or _journal_has_trigger(root):
        return 4, "model-refresh: candidate backlog thin or trigger set", blockers
    if ready:
        return 5, f"run: scenario {ready[0].get('key')!r} ready", blockers
    return 6, "emit: propose a new batch of candidates", blockers


# --------------------------------------------------------------------------- #
# --emit
# --------------------------------------------------------------------------- #
_SKELETON = (
    "# Candidates\n\n"
    f"{EMIT_BEGIN}\n{EMIT_END}\n\n"
    "## Backlog\n\n"
    "| key | rung | status | note |\n"
    "| --- | --- | --- | --- |\n"
)


def _emit_body(root: str) -> str:
    model, _ = load_model(root)
    flows = sorted((model.get("flows") or {}).keys())
    smetas = [meta for _r, meta, _b, perr in load_dir(root, "scenarios") if perr is None]

    status_order = ("planned", "ready", "running", "done")
    result_order = ("null", "green", "finding", "void", "blocked")
    status_counts = {k: 0 for k in status_order}
    result_counts = {k: 0 for k in result_order}
    for m in smetas:
        st = m.get("status")
        if st in status_counts:
            status_counts[st] += 1
        res = m.get("result")
        rk = "null" if res is None else res
        if rk in result_counts:
            result_counts[rk] += 1

    lines = ["## Snapshot (generated -- do not edit inside the emit markers)", ""]
    lines.append("status: " + " ".join(f"{k}={status_counts[k]}" for k in status_order))
    lines.append("result: " + " ".join(f"{k}={result_counts[k]}" for k in result_order))
    lines.append("")
    lines.append("| flow \\ rung | " + " | ".join(RUNGS) + " |")
    lines.append("| --- | " + " | ".join("---" for _ in RUNGS) + " |")
    for fk in flows:
        cells = []
        for rung in RUNGS:
            n = sum(
                1 for m in smetas
                if fk in (m.get("flows") or []) and m.get("rung") == rung
            )
            cells.append(str(n))
        lines.append(f"| {fk} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def run_emit(root: str) -> None:
    path = os.path.join(root, "candidates.md")
    text = _read(path)
    if text is None or EMIT_BEGIN not in text or EMIT_END not in text:
        text = _SKELETON
    bi = text.find(EMIT_BEGIN)
    ei = text.find(EMIT_END)
    body = _emit_body(root)
    new_text = text[: bi + len(EMIT_BEGIN)] + "\n" + body + "\n" + text[ei:]
    with open(path, "w", encoding="utf-8") as f:
        f.write(new_text)


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="strict format compiler for the .workers/ v2 tree")
    ap.add_argument("--root", default=_SCRIPT_DIR)
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--emit", action="store_true")
    args = ap.parse_args(argv)
    root = args.root

    if args.emit:
        run_emit(root)
    if args.status:
        row, reason, blockers = compute_status(root)
        print(f"STATUS row={row} {reason}")
        if blockers:
            shown = blockers[:10]
            print(f"STOP-BLOCKERS ({len(blockers)}):")
            for b in shown:
                print(f"  - {b}")
            if len(blockers) > len(shown):
                print(f"  ... and {len(blockers) - len(shown)} more")
        else:
            print("STOP-BLOCKERS (0): none")
    if args.emit or args.status:
        return 0

    errors, n_scen, n_flows = run_check(root)
    for n, path, detail in sorted(errors):
        print(f"G{n} FAIL {path}: {detail}")
    if errors:
        print(f"CHECK FAIL {len(errors)} errors")
        return 2
    print(f"CHECK OK ({n_scen} scenarios, {n_flows} flows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
