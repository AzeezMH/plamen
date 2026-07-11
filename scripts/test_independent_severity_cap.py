"""Fixtures for M4 — blind-first independent severity, min-capped (anti-inflation).

The verifier assigns a severity INDEPENDENTLY from the code and evidence
alone, BEFORE reconciling with the pre-assigned/claimed severity from the
verification queue. `_apply_independent_severity_caps` mechanically caps
`final = min(independent, claimed)`:

  - Independent LOWER than claimed  -> cap recorded, Final = independent,
    stamped `INDEPENDENT-MIN(<claimed>)` in the report.
  - Independent EQUAL/HIGHER than claimed -> NO cap (never raises severity).
  - Verdict REFUTED (or other non-body verdicts) -> NO cap (N/A class; the
    finding isn't in the body at all).
  - Independent Severity missing or unparseable ("N/A", garbage) -> NO cap
    (recall-safe fallback to the claimed severity — never drops a finding).

This mirrors the `poc_demotions.md` mechanical-cap precedent
(`_apply_poc_fail_demotions` / `_poc_demotion_caps_for_validator` /
`_expected_report_index_severities`) end-to-end, including a
`_report_index_adjustment_reason_present("INDEPENDENT-MIN(High)")` coverage
test (mirrors the EXTERNAL-ASSUMPTION-CAP test in
test_fix1_fix3_status_and_external_assumption.py).

All fixtures are synthetic/generic (no protocol/token/contract/function names).

Run: pytest scripts/test_independent_severity_cap.py -v
"""
from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

import pytest

PLAMEN_HOME = Path(__file__).resolve().parent.parent


def _v():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
    if "plamen_validators" in sys.modules:
        del sys.modules["plamen_validators"]
    return importlib.import_module("plamen_validators")


def _scratch(tmp_path: Path) -> Path:
    sp = tmp_path / ".scratchpad"
    sp.mkdir()
    (sp / "config.json").write_text(json.dumps({}), encoding="utf-8")
    return sp


def _queue(sp: Path, rows: list[tuple[str, str, str]]) -> None:
    """rows: (finding_id, severity, poc_class)."""
    out = [
        "| Queue # | Finding ID | Severity | Title | PoC Class |",
        "|---------|------------|----------|-------|-----------|",
    ]
    for i, (fid, sev, pc) in enumerate(rows, start=1):
        out.append(f"| {i} | {fid} | {sev} | example finding | {pc} |")
    (sp / "verification_queue.md").write_text("\n".join(out) + "\n", encoding="utf-8")


def _verify(
    sp: Path,
    fid: str,
    *,
    verdict: str,
    independent: str | None,
    severity: str = "High",
    tag: str = "[CODE-TRACE]",
) -> None:
    """Write a verify_{fid}.md fixture. `independent=None` omits the field
    entirely (missing-field case)."""
    lines = [
        f"**Severity**: {severity}\n\n",
        f"**Verdict**: {verdict}\n\n",
        f"**Evidence Tag**: {tag}\n\n",
    ]
    if independent is not None:
        lines.append(f"**Independent Severity**: {independent}\n\n")
    lines.append(
        "### PoC Attempt\n"
        "- PoC Required: YES\n"
        "- Attempted: NO\n"
        "- PoC Not Attempted Because: N/A\n\n"
        "### Execution Result\n"
        "- Result: NOT_EXECUTED\n"
    )
    (sp / f"verify_{fid}.md").write_text("".join(lines), encoding="utf-8")


# ===========================================================================
# _apply_independent_severity_caps
# ===========================================================================

def test_independent_lower_than_claimed_caps(tmp_path):
    """Independent LOWER than claimed -> cap recorded, Final=independent."""
    V = _v()
    sp = _scratch(tmp_path)
    _queue(sp, [("F-01", "Critical", "unit")])
    _verify(sp, "F-01", verdict="CONFIRMED", independent="Medium", severity="Critical")
    result = V._apply_independent_severity_caps(sp, "thorough")
    assert len(result) == 1
    rec = result[0]
    assert rec["finding_id"] == "F-01"
    assert rec["claimed_severity"] == "Critical"
    assert rec["independent_severity"] == "Medium"
    assert rec["final_severity"] == "Medium"
    ledger = sp / "independent_severity_caps.md"
    assert ledger.exists()
    text = ledger.read_text(encoding="utf-8")
    assert "F-01" in text and "Critical" in text and "Medium" in text


def test_independent_equal_to_claimed_no_cap(tmp_path):
    """Independent EQUAL to claimed -> no cap."""
    V = _v()
    sp = _scratch(tmp_path)
    _queue(sp, [("F-02", "High", "unit")])
    _verify(sp, "F-02", verdict="CONFIRMED", independent="High", severity="High")
    result = V._apply_independent_severity_caps(sp, "thorough")
    assert result == []
    assert not (sp / "independent_severity_caps.md").exists()


def test_independent_higher_than_claimed_never_raises(tmp_path):
    """Independent HIGHER than claimed -> NO cap (never raises severity)."""
    V = _v()
    sp = _scratch(tmp_path)
    _queue(sp, [("F-03", "Low", "unit")])
    _verify(sp, "F-03", verdict="CONFIRMED", independent="Critical", severity="Low")
    result = V._apply_independent_severity_caps(sp, "thorough")
    assert result == []
    assert not (sp / "independent_severity_caps.md").exists()


def test_independent_na_no_cap(tmp_path):
    """Independent Severity = N/A -> no cap."""
    V = _v()
    sp = _scratch(tmp_path)
    _queue(sp, [("F-04", "High", "unit")])
    _verify(sp, "F-04", verdict="CONFIRMED", independent="N/A", severity="High")
    result = V._apply_independent_severity_caps(sp, "thorough")
    assert result == []


def test_refuted_verdict_no_cap(tmp_path):
    """REFUTED verdict -> no cap (N/A class), even if Independent Severity
    was somehow filled in."""
    V = _v()
    sp = _scratch(tmp_path)
    _queue(sp, [("F-05", "High", "unit")])
    _verify(sp, "F-05", verdict="REFUTED", independent="Low", severity="High")
    result = V._apply_independent_severity_caps(sp, "thorough")
    assert result == []
    assert not (sp / "independent_severity_caps.md").exists()


def test_missing_independent_field_no_cap(tmp_path):
    """Missing Independent Severity field entirely -> no cap (recall-safe
    fallback to claimed severity)."""
    V = _v()
    sp = _scratch(tmp_path)
    _queue(sp, [("F-06", "High", "unit")])
    _verify(sp, "F-06", verdict="CONFIRMED", independent=None, severity="High")
    result = V._apply_independent_severity_caps(sp, "thorough")
    assert result == []
    assert not (sp / "independent_severity_caps.md").exists()


def test_unparseable_independent_field_no_cap(tmp_path):
    """Garbage/unparseable Independent Severity -> no cap (recall-safe)."""
    V = _v()
    sp = _scratch(tmp_path)
    _queue(sp, [("F-07", "High", "unit")])
    _verify(sp, "F-07", verdict="CONFIRMED", independent="unclear, need more data", severity="High")
    result = V._apply_independent_severity_caps(sp, "thorough")
    assert result == []


def test_light_mode_skips(tmp_path):
    """Light mode -> no caps applied at all (mirrors poc_demotions light-mode
    skip)."""
    V = _v()
    sp = _scratch(tmp_path)
    _queue(sp, [("F-08", "Critical", "unit")])
    _verify(sp, "F-08", verdict="CONFIRMED", independent="Low", severity="Critical")
    result = V._apply_independent_severity_caps(sp, "light")
    assert result == []


def test_multiple_findings_only_lower_ones_capped(tmp_path):
    """Mixed batch: only the finding whose independent assessment is lower
    gets a cap row; the others are untouched."""
    V = _v()
    sp = _scratch(tmp_path)
    _queue(sp, [
        ("F-09", "Critical", "unit"),
        ("F-10", "Medium", "unit"),
        ("F-11", "Low", "unit"),
    ])
    _verify(sp, "F-09", verdict="CONFIRMED", independent="High", severity="Critical")  # caps
    _verify(sp, "F-10", verdict="CONFIRMED", independent="Medium", severity="Medium")  # no cap
    _verify(sp, "F-11", verdict="CONFIRMED", independent="Critical", severity="Low")  # never raises
    result = V._apply_independent_severity_caps(sp, "thorough")
    capped_ids = {r["finding_id"] for r in result}
    assert capped_ids == {"F-09"}


# ===========================================================================
# _load_independent_severity_caps — read the ledger back
# ===========================================================================

def test_load_independent_severity_caps_round_trip(tmp_path):
    V = _v()
    sp = _scratch(tmp_path)
    _queue(sp, [("F-12", "Critical", "unit")])
    _verify(sp, "F-12", verdict="CONFIRMED", independent="Low", severity="Critical")
    V._apply_independent_severity_caps(sp, "thorough")
    caps = V._load_independent_severity_caps(sp)
    assert caps.get("F-12") == "Low"


def test_load_independent_severity_caps_missing_file(tmp_path):
    V = _v()
    sp = _scratch(tmp_path)
    assert V._load_independent_severity_caps(sp) == {}


# ===========================================================================
# _expected_report_index_severities integration — the cap actually lowers
# the driver-computed expected severity for report_index/severity_binding.md
# ===========================================================================

def test_expected_severity_reflects_independent_cap(tmp_path):
    V = _v()
    sp = _scratch(tmp_path)
    _queue(sp, [("F-13", "Critical", "unit")])
    _verify(sp, "F-13", verdict="CONFIRMED", independent="Medium", severity="Critical")
    V._apply_independent_severity_caps(sp, "thorough")
    expected = V._expected_report_index_severities(sp)
    assert expected.get("F-13") == "Medium"


def test_expected_severity_unaffected_when_no_cap(tmp_path):
    """No independent_severity_caps.md ledger written -> expected severity is
    unaffected (recall-safe no-op)."""
    V = _v()
    sp = _scratch(tmp_path)
    _queue(sp, [("F-14", "High", "unit")])
    _verify(sp, "F-14", verdict="CONFIRMED", independent="High", severity="High")
    # Deliberately do NOT call _apply_independent_severity_caps — simulates a
    # pre-M4 scratchpad with no ledger at all.
    expected = V._expected_report_index_severities(sp)
    assert expected.get("F-14") == "High"


# ===========================================================================
# _report_index_adjustment_reason_present — INDEPENDENT-MIN token accepted
# ===========================================================================

def test_provenance_allowlist_accepts_independent_min(tmp_path):
    V = _v()
    assert V._report_index_adjustment_reason_present("INDEPENDENT-MIN(High)") is True
    assert V._report_index_adjustment_reason_present("INDEPENDENT-MIN(Critical)") is True
    # no regression on empty/none
    assert V._report_index_adjustment_reason_present("") is False
    assert V._report_index_adjustment_reason_present("-") is False


# ===========================================================================
# Verifier prompt directive — mandatory Independent Severity field present
# ===========================================================================

@pytest.mark.parametrize("lang", ["evm", "solana", "aptos", "sui", "soroban", "daml"])
def test_verifier_prompt_has_independent_severity_directive(lang):
    path = PLAMEN_HOME / "prompts" / lang / "phase5-verification-prompt.md"
    assert path.exists(), f"missing {path}"
    text = path.read_text(encoding="utf-8")
    assert "INDEPENDENT SEVERITY ASSESSMENT" in text
    assert "MANDATORY" in text.split("INDEPENDENT SEVERITY ASSESSMENT", 1)[1][:200]
    # The mandatory output field itself:
    assert "**Independent Severity**:" in text
    # ignore-pre-assigned-severity directive:
    assert "ignore" in text.lower()
