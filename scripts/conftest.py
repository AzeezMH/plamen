"""Shared pytest configuration for the Plamen scripts/ test suite.

Two responsibilities, both zero-risk to test *logic*:

1. ``sys.path`` net — put ``scripts/`` on ``sys.path`` so new test modules can
   ``import enumeration_gate`` etc. without repeating the
   ``sys.path.insert(0, ...)`` boilerplate that 190+ existing files hand-roll.
   Existing files keep their own insert (harmless); new ones need not.

2. Test-selection markers (registered in ../pyproject.toml) applied by FILENAME
   here — the single source of truth for which modules are `integration` / `slow`.
   Marking never removes a test: the full/nightly lane (`pytest` with no `-m`)
   still runs every one. It only lets a fast inner loop skip the heavy files:
       fast:        pytest -m "not integration" -n auto
       integration: pytest -m "integration"            (serial, env-guarded)
   The heavy set is measured, not guessed: real OS-subprocess files + files whose
   real ``time.sleep`` is >= ~1s (heartbeat/timing tests). Sub-second sleepers and
   fully-mocked tests stay in the default (fast) lane.
"""

import os
import sys
from pathlib import Path

import pytest

# (0) Hang-proof self-runs — make ANY `pytest` of this suite non-blocking without
# an exported env var. The driver's halt/purge prompts (wait_halt_choice /
# wait_critical_halt_choice / wait_purge_choice) exit on a non-TTY stdin, but an
# agent/pty shell reports isatty()==True, so integration tests (test_driver_smoke,
# test_halt_ux_e2e, test_signal_and_ratelimit) would block on a keypress there.
# setdefault: only fills it if the caller/CI hasn't chosen a value, so explicit
# overrides still win. Test-scoped — real audit runs never import conftest, so
# this cannot change production halt behavior. This is what lets the agent run
# the full suite unattended (the way it has for months) without it hanging.
os.environ.setdefault("PLAMEN_AUTO_HALT_CHOICE", "exit")

# (1) sys.path net — idempotent; scripts/ dir is this file's parent.
_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)


# (2) Filename-driven marker application. Stems only (no .py). Keep sorted.
# A file lands in _INTEGRATION_STEMS if it spawns a real OS subprocess / external
# tool, or does a real time.sleep >= ~1s. _SLOW_STEMS is the heavyweight subset
# (real driver phase-loop / mass real import subprocesses).
_INTEGRATION_STEMS = frozenset(
    {
        "test_cross_os_hygiene",
        "test_driver_smoke",
        "test_halt_ux_e2e",
        "test_l1_race_fuzz_registry",
        "test_mechanical_heartbeat",
        "test_opengrep",
        "test_p0_judge_table_parser",
        "test_phase_containment_regression",
        "test_pty_exec",
        "test_recon_hardened_subprocess",
        "test_recon_heartbeat",
        "test_signal_and_ratelimit",
        "test_structural_integrity",
        "test_windows_copy_fallback_install",
    }
)
_SLOW_STEMS = frozenset(
    {
        "test_driver_smoke",
        "test_structural_integrity",
    }
)


def pytest_collection_modifyitems(config, items):
    """Apply integration/slow markers by source filename (single source of truth)."""
    for item in items:
        stem = Path(str(item.fspath)).stem
        if stem in _INTEGRATION_STEMS:
            item.add_marker(pytest.mark.integration)
        if stem in _SLOW_STEMS:
            item.add_marker(pytest.mark.slow)


@pytest.fixture(autouse=True)
def fail_on_legacy_check_failures(request):
    """Make legacy check()/FAIL harnesses behave like pytest assertions."""
    module = getattr(request, "module", None)
    if module is None or not hasattr(module, "FAIL"):
        yield
        return

    before = getattr(module, "FAIL", 0)
    yield
    after = getattr(module, "FAIL", 0)
    if after <= before:
        return

    details = []
    for attr in ("FAILURES", "ERRORS"):
        entries = getattr(module, attr, None)
        if entries:
            details.extend(str(entry) for entry in entries[-(after - before):])
    detail_text = "\n".join(details) if details else f"{after - before} legacy check() failure(s)"
    pytest.fail(detail_text)
