#!/usr/bin/env python3
"""turso_genfuzz -- Turso adapter for the genlib differential harness (calibration/102).

Wires genlib's product-agnostic core to tursodb:
  * reference runner  = stdlib sqlite3 (genlib.Sqlite3Runner)
  * candidate runner  = tursodb CLI (genlib.CliRunner) against the vendored binary
  * product axes      = encryption on/off (cipher opts swept) x page_size x journal
  * lifecycle plug    = checkpoint, ATTACH/DETACH aux db (Turso-exposed via SQL)

Imports are stdlib + genlib only, so this file can be copied verbatim into
turso-workload/.workers/workloads/ next to genlib.py for the guest run. It reads the
seed from the SAME env names as turso_workload_common (TURSO_WORKLOAD_SEED / WORKLOAD_SEED).

NOTE: the tursodb binary is linux-only, so on macOS the candidate runner cannot
actually execute; this module is import- and construction-safe there and is exercised
end-to-end only in the guest (calibration). The sqlite3-vs-sqlite3 path runs anywhere.
"""
import hashlib
import os
import secrets
import sys
from pathlib import Path

import genlib


# --- seed derivation, matching turso_workload_common's env contract ----------

def workload_seed_raw() -> str:
    return (
        os.environ.get("TURSO_WORKLOAD_SEED")
        or os.environ.get("WORKLOAD_SEED")
        or secrets.token_hex(16)
    )


# --- vendored tursodb binary path (same layout as existing workloads) --------

def _vendor_paths() -> tuple[Path, Path, Path]:
    # In the guest, this file lives at .workers/workloads/turso_genfuzz.py, so the
    # project root is two parents up (matches turso_workload_common.ROOT). TURSODB_PATH
    # overrides the binary (same env contract as turso_workload_common), which is how the
    # calibration host -- where parents[2] does NOT point at a turso project -- can still be
    # tested; the guest run leaves it unset and uses the vendored binary.
    root = Path(__file__).resolve().parents[2]
    raw = os.environ.get("TURSODB_PATH")
    binary = Path(raw) if raw else root / ".workers" / "vendor" / "bin" / "tursodb"
    if not binary.is_absolute():
        binary = root / binary
    loader = root / ".workers" / "vendor" / "lib" / "ld-linux-x86-64.so.2"
    loader_lib = root / ".workers" / "vendor" / "lib"
    return binary, loader, loader_lib


# --- Turso product axes (swept, never pinned) --------------------------------
# Encryption is a swept axis: 0/1. When on, a cipher is chosen from the CIPHERS
# sweep. The page_size x encryption product is what surfaces the abort target
# (WP-025 / turso #7610) WITHOUT the generator pinning any single combo.
TURSO_AXES: dict[str, tuple] = {
    "cipher": ("aegis256", "aes256gcm"),   # only meaningful when encryption=1
    "attach_aux": (0, 1),                  # whether an aux db is attached
}

# Turso lifecycle ops exposed via SQL -- fed to genlib as a lifecycle plug so the
# generator interleaves them like any other op.
TURSO_LIFECYCLE_PLUG: tuple[str, ...] = (
    "PRAGMA wal_checkpoint(TRUNCATE);",
    "PRAGMA quick_check;",
)

# Experimental flags the tursodb CLI needs for the surface we generate. FTS needs the
# index-method + custom-types flags (per turso_fts_index_maintenance_reopen); encryption
# needs --experimental-encryption. We union every flag the generated surface can touch so
# no family is silently rejected for a missing flag.
TURSO_BASE_ARGS: tuple[str, ...] = (
    "--experimental-attach",
    "--experimental-views",
    "--experimental-vacuum",
    "--experimental-generated-columns",
    "--experimental-without-rowid",
    "--experimental-encryption",
    "--experimental-index-method",
    "--experimental-custom-types",
)


def hexkey_for(seed: int) -> str:
    """A deterministic 64-hex-char (256-bit) key derived from the seed, so an encrypted
    run is reproducible from its seed alone (matches the corpus's 64-hex key length)."""
    return hashlib.sha256(f"genfuzz-hexkey:{seed}".encode()).hexdigest()


def build_runners(run_dir: Path, seed: int, encryption: int, cipher: str):
    """Construct (reference, candidate) runners. On macOS the candidate is constructed
    but not executed (linux binary); the guest run executes it for real. When encryption
    is swept on, the candidate opens the main db via the cipher URI with a seed-derived
    hexkey; the reference stays plaintext (encryption is candidate-side config)."""
    binary, loader, loader_lib = _vendor_paths()
    reference = genlib.Sqlite3Runner(run_dir, tag="sqlite3-ref")
    base_args = list(TURSO_BASE_ARGS)
    candidate = genlib.CliRunner(
        binary=binary,
        base_args=tuple(base_args),
        run_dir=run_dir,
        tag="tursodb",
        loader=loader if loader.exists() else None,
        loader_lib=loader_lib if loader_lib.exists() else None,
        encryption=encryption,
        cipher=cipher if encryption else "",
        hexkey=hexkey_for(seed) if encryption else "",
    )
    return reference, candidate


def run_dir_for(name: str) -> Path:
    base = Path(os.environ.get("TMPDIR", "/tmp")) / f"turso-genfuzz-{name}"
    return base


def main() -> int:
    raw = workload_seed_raw()
    seed = genlib.root_seed_from(raw)
    axes = genlib.merged_axes(TURSO_AXES)
    # Realize the encryption/cipher choice from the swept config so the candidate
    # runner opens the db with the matching cipher URI in the guest.
    config = genlib.choose_config(seed, axes)
    run_dir = run_dir_for(str(seed))

    print(
        f"turso_genfuzz seed_raw={raw!r} seed={seed} "
        f"page_size={config['page_size']} encryption={config['encryption']} "
        f"cipher={config['cipher']} journal_mode={config['journal_mode']} "
        f"attach_aux={config['attach_aux']} sqlite_version={_sqlite_version()}",
        flush=True,
    )

    reference, candidate = build_runners(run_dir, seed, config["encryption"], config["cipher"])
    result = genlib.run_case(
        seed=seed,
        axes=axes,
        runners=(reference, candidate),
        lifecycle_plug=TURSO_LIFECYCLE_PLUG,
        case_id="GENFUZZ",
    )
    # 0 GREEN / 1 RED / 3 VOID -- matches turso_workload_common exit conventions.
    return result.exit_code


def _sqlite_version() -> str:
    import sqlite3
    return sqlite3.sqlite_version


if __name__ == "__main__":
    sys.exit(main())
