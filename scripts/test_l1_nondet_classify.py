"""Unit tests for Wave-2 item A2: the L1 twin of the mandatory-PoC force gate.

Targets:
  - classify_poc_testability(..., pipeline="l1")  — reroute race/non-determinism/
    Byzantine bug classes away from the zero-PoC `structural` bucket, so the
    mandatory-PoC/force gate engages for them (matching the L1 verification
    contract: `[CODE-TRACE]` alone caps High/Critical at CONTESTED for these
    classes; see prompts/l1/phase5-verification-prompt.md and
    docs/l1-mode/design.md Section 8.2).
  - _matches_l1_nondeterminism_class              — the pattern predicate
  - _read_pipeline_from_config                    — config.json auto-detection
  - _queue_rows_from_inventory_with_exclusions    — end-to-end queue building
    auto-detects pipeline from config.json and threads it into the classifier

HARD REQUIREMENT: the SC path (pipeline == "sc" / "" / absent) must be
byte-identical to pre-existing behavior. Every test below pairs an L1
assertion with a same-input SC control assertion.

Run: `python -m pytest test_l1_nondet_classify.py -q`
     or: `python test_l1_nondet_classify.py`
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

from plamen_parsers import (  # noqa: E402
    classify_poc_testability,
    _matches_l1_nondeterminism_class,
    _read_pipeline_from_config,
    _queue_rows_from_inventory_with_exclusions,
)

PASS, FAIL = 0, 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  PASS  {label}")
    else:
        FAIL += 1
        print(f"  FAIL  {label} :: {detail}")


def _mkscratch(files: dict[str, str]) -> Path:
    sp = Path(tempfile.mkdtemp(prefix="plamen_l1nondet_"))
    for name, body in files.items():
        (sp / name).write_text(body, encoding="utf-8")
    return sp


# --------------------------------------------------------------------------
# classify_poc_testability: default arg / backward compatibility
# --------------------------------------------------------------------------

def test_default_pipeline_arg_unchanged():
    """Calling with the original 4-arg signature (no pipeline) is untouched."""
    print("\n--- classify_poc_testability: default (no pipeline arg) ---")
    check(
        "race condition, no pipeline arg -> structural (unchanged)",
        classify_poc_testability("race condition", "", "Goroutine data race", "High")
        == "structural",
    )
    check(
        "non-determinism, no pipeline arg -> structural (unchanged)",
        classify_poc_testability("non-determinism", "", "Random seed usage", "High")
        == "structural",
    )
    check(
        "byzantine, no pipeline arg -> structural (unchanged)",
        classify_poc_testability("byzantine tolerance", "", "2/3 threshold", "Critical")
        == "structural",
    )


# --------------------------------------------------------------------------
# classify_poc_testability: pipeline="l1" reroute (positive-harvest)
# --------------------------------------------------------------------------

def test_l1_race_condition_reroutes_to_property():
    print("\n--- classify_poc_testability: l1 race condition reroute ---")
    l1_result = classify_poc_testability(
        "race condition", "CODE-TRACE", "Goroutine data race in validator set", "High",
        "l1",
    )
    sc_result = classify_poc_testability(
        "race condition", "CODE-TRACE", "Goroutine data race in validator set", "High",
        "sc",
    )
    check("l1: race condition -> property (mandatory PoC engages)", l1_result == "property")
    check("sc control: race condition -> structural (unchanged)", sc_result == "structural")


def test_l1_nondeterminism_reroutes_to_property():
    print("\n--- classify_poc_testability: l1 non-determinism reroute ---")
    l1_result = classify_poc_testability(
        "non-determinism", "CODE-TRACE", "Non-deterministic fee ordering", "Critical",
        "l1",
    )
    sc_result = classify_poc_testability(
        "non-determinism", "CODE-TRACE", "Non-deterministic fee ordering", "Critical",
        "sc",
    )
    check("l1: non-determinism -> property", l1_result == "property")
    check("sc control: non-determinism -> structural (unchanged)", sc_result == "structural")


def test_l1_byzantine_reroutes_to_property():
    print("\n--- classify_poc_testability: l1 byzantine reroute ---")
    l1_result = classify_poc_testability(
        "byzantine", "CODE-TRACE", "Byzantine fraction miscount at 1/3 threshold", "High",
        "l1",
    )
    sc_result = classify_poc_testability(
        "byzantine", "CODE-TRACE", "Byzantine fraction miscount at 1/3 threshold", "High",
        "sc",
    )
    check("l1: byzantine -> property", l1_result == "property")
    check("sc control: byzantine -> structural (unchanged)", sc_result == "structural")


def test_l1_absent_pipeline_defaults_to_sc_behavior():
    """pipeline='' (falsy, same as omitted) never engages the l1 reroute."""
    print("\n--- classify_poc_testability: pipeline='' behaves like sc ---")
    check(
        "empty pipeline string -> structural (no reroute)",
        classify_poc_testability("race condition", "", "Data race", "High", "")
        == "structural",
    )


def test_l1_genuinely_untestable_classes_remain_structural():
    """timing/crash-recovery/cross-client/toctou/eclipse/network-partition are
    legitimately structural per phase5-verification-prompt.md's
    `poc_class: structural` section ("timing, crash-recovery, or cross-client
    conditions that cannot be unit-tested") — the l1 reroute must NOT touch
    these, only the race/non-determinism/byzantine subset.
    """
    print("\n--- classify_poc_testability: l1 non-reroute classes stay structural ---")
    for bug_class, title in [
        ("toctou", "TOCTOU on config reload"),
        ("crash-recovery", "State loss on crash recovery"),
        ("timing", "Timing-dependent block acceptance"),
        ("cross-client", "Cross-client divergence in gas accounting"),
        ("eclipse", "Eclipse attack via peer table exhaustion"),
        ("network partition", "Split-brain under network partition"),
    ]:
        result = classify_poc_testability(bug_class, "CODE-TRACE", title, "High", "l1")
        check(f"l1: {bug_class!r} stays structural", result == "structural", result)


# --------------------------------------------------------------------------
# _matches_l1_nondeterminism_class: pattern predicate
# --------------------------------------------------------------------------

def test_matches_l1_nondeterminism_class_predicate():
    print("\n--- _matches_l1_nondeterminism_class ---")
    check("race condition matches", _matches_l1_nondeterminism_class("race condition", ""))
    check("data race matches", _matches_l1_nondeterminism_class("", "data race in cache"))
    check("non-determinism matches", _matches_l1_nondeterminism_class("non-determinism", ""))
    check("nondeterminism (no hyphen) matches", _matches_l1_nondeterminism_class("nondeterminism", ""))
    check("byzantine matches", _matches_l1_nondeterminism_class("byzantine consensus", ""))
    check("unrelated text does not match", not _matches_l1_nondeterminism_class("overflow", "fee calc"))
    check("timing does not match (genuinely structural)", not _matches_l1_nondeterminism_class("timing", ""))


# --------------------------------------------------------------------------
# _read_pipeline_from_config
# --------------------------------------------------------------------------

def test_read_pipeline_from_config():
    print("\n--- _read_pipeline_from_config ---")
    sp_l1 = _mkscratch({"config.json": json.dumps({"pipeline": "l1", "mode": "thorough"})})
    check("reads l1 from config.json", _read_pipeline_from_config(sp_l1) == "l1")

    sp_sc = _mkscratch({"config.json": json.dumps({"pipeline": "sc", "mode": "core"})})
    check("reads sc from config.json", _read_pipeline_from_config(sp_sc) == "sc")

    sp_missing = _mkscratch({})
    check("missing config.json -> ''", _read_pipeline_from_config(sp_missing) == "")

    sp_malformed = _mkscratch({"config.json": "{not valid json"})
    check("malformed config.json degrades to '' (try/except-safe)", _read_pipeline_from_config(sp_malformed) == "")

    sp_no_field = _mkscratch({"config.json": json.dumps({"mode": "core"})})
    check("config.json without pipeline field -> ''", _read_pipeline_from_config(sp_no_field) == "")


# --------------------------------------------------------------------------
# _queue_rows_from_inventory_with_exclusions: end-to-end, config-driven
# auto-detection (positive-harvest: the real classification lands on a
# synthetic finding, not merely "does not crash")
# --------------------------------------------------------------------------

def test_e2e_l1_scratchpad_reroutes_race_finding_to_property():
    print("\n--- e2e: l1 scratchpad auto-detects pipeline, reroutes race finding ---")
    sp = _mkscratch({
        "config.json": json.dumps({"pipeline": "l1", "mode": "thorough"}),
        "findings_inventory.md": (
            "## Finding [F-01]: Goroutine data race in block validator\n\n"
            "**Severity**: High\n"
            "**Location**: consensus/validator.go:120\n"
            "**Bug Class**: race condition\n"
            "**Preferred Tag**: [CODE-TRACE]\n"
            "**Description**: Two goroutines mutate validator state without a lock.\n\n"
        ),
    })
    rows, _excluded = _queue_rows_from_inventory_with_exclusions(sp)
    check("e2e l1: exactly 1 row harvested (positive, non-empty)", len(rows) == 1, len(rows))
    if rows:
        check(
            "e2e l1: F-01 poc class == property (mandatory PoC engages)",
            rows[0].get("poc class") == "property",
            rows[0].get("poc class"),
        )


def test_e2e_sc_scratchpad_control_unchanged():
    """Same finding, same file layout, but config.json declares pipeline=sc.
    The SC path MUST be byte-identical to pre-existing behavior: structural.
    """
    print("\n--- e2e: sc scratchpad control — unchanged (structural) ---")
    sp = _mkscratch({
        "config.json": json.dumps({"pipeline": "sc", "mode": "thorough"}),
        "findings_inventory.md": (
            "## Finding [F-01]: Goroutine data race in block validator\n\n"
            "**Severity**: High\n"
            "**Location**: consensus/validator.go:120\n"
            "**Bug Class**: race condition\n"
            "**Preferred Tag**: [CODE-TRACE]\n"
            "**Description**: Two goroutines mutate validator state without a lock.\n\n"
        ),
    })
    rows, _excluded = _queue_rows_from_inventory_with_exclusions(sp)
    check("e2e sc: exactly 1 row harvested (positive, non-empty)", len(rows) == 1, len(rows))
    if rows:
        check(
            "e2e sc control: F-01 poc class == structural (unchanged)",
            rows[0].get("poc class") == "structural",
            rows[0].get("poc class"),
        )


def test_e2e_no_config_json_defaults_to_prior_behavior():
    """No config.json at all (e.g. an older scratchpad or an ad-hoc test
    fixture) must degrade to the pre-existing structural classification —
    proves the SC/default path is genuinely unaffected by this change.
    """
    print("\n--- e2e: no config.json -> prior (structural) behavior ---")
    sp = _mkscratch({
        "findings_inventory.md": (
            "## Finding [F-02]: Non-deterministic ordering of reward split entries\n\n"
            "**Severity**: Critical\n"
            "**Location**: rewards/split.go:88\n"
            "**Bug Class**: non-determinism\n"
            "**Preferred Tag**: [CODE-TRACE]\n"
            "**Description**: Concurrent goroutines write reward entries in nondeterministic order.\n\n"
        ),
    })
    rows, _excluded = _queue_rows_from_inventory_with_exclusions(sp)
    check("e2e no-config: exactly 1 row harvested (positive, non-empty)", len(rows) == 1, len(rows))
    if rows:
        check(
            "e2e no-config: F-02 poc class == structural (prior default, unchanged)",
            rows[0].get("poc class") == "structural",
            rows[0].get("poc class"),
        )


def main() -> int:
    test_default_pipeline_arg_unchanged()
    test_l1_race_condition_reroutes_to_property()
    test_l1_nondeterminism_reroutes_to_property()
    test_l1_byzantine_reroutes_to_property()
    test_l1_absent_pipeline_defaults_to_sc_behavior()
    test_l1_genuinely_untestable_classes_remain_structural()
    test_matches_l1_nondeterminism_class_predicate()
    test_read_pipeline_from_config()
    test_e2e_l1_scratchpad_reroutes_race_finding_to_property()
    test_e2e_sc_scratchpad_control_unchanged()
    test_e2e_no_config_json_defaults_to_prior_behavior()

    print(f"\n{'=' * 60}")
    print(f"RESULTS: {PASS} passed, {FAIL} failed")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
