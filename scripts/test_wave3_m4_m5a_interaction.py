"""Wave-3 cross-integration tests — M4 (independent-severity min-cap) x M5a
(identifier-existence inventory gate) interacting on the SAME finding.

Both mechanisms are independently recall-safe (see test_independent_severity_cap.py
and test_identifier_gate.py). This file asks the harder question: what happens
when a SINGLE finding is touched by BOTH in the same pipeline run?

Scenario under test: a Medium+ finding that
  (a) cites a concrete identifier absent from the whole-project source index
      -> M5a Gate 3 fires but, because severity is Medium+, only FLAGS the
      finding (loc_reason gets an `[IDENTIFIER-UNVERIFIED ...]` note); it
      stays exactly where it was (never appendix-routed, never dropped), AND
  (b) has a verifier-assessed Independent Severity LOWER than its claimed
      severity -> M4 mechanically caps `final = min(independent, claimed)`
      and stamps `INDEPENDENT-MIN(<claimed>)` in the report.

Assertions:
  1. The finding keeps a SINGLE coherent disposition — it is not split into
     two rows, not double-counted, not silently overwritten by whichever
     mechanism runs second.
  2. It stays in the report BODY (Medium, real security consequence — never
     appendix per the material-harm floor).
  3. `_report_index_adjustment_reason_present` accepts a Trust Adj. cell that
     carries BOTH signals (the INDEPENDENT-MIN token from M4 and prose
     mentioning the M5a human-review flag) — regardless of token order — so
     the severity-provenance gate does not spuriously halt the run.
  4. Neither mechanism removes the finding from the active verification queue
     or the report index; the only artifact-level effect is a severity number
     and a reason string.

All fixtures are synthetic/generic (no protocol/token/contract/function names).

Run: pytest scripts/test_wave3_m4_m5a_interaction.py -v
"""
from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path


def _v():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    if "plamen_validators" in sys.modules:
        del sys.modules["plamen_validators"]
    return importlib.import_module("plamen_validators")


def _scratch(tmp_path: Path) -> Path:
    sp = tmp_path / ".scratchpad"
    sp.mkdir()
    (sp / "config.json").write_text(json.dumps({}), encoding="utf-8")
    return sp


def _mk_project(tmp_path: Path) -> Path:
    """A tiny project whose only real function is `knownFunc` — any other
    identifier a finding cites does not exist anywhere in scope."""
    root = tmp_path / "proj"
    (root / "core").mkdir(parents=True)
    (root / "core" / "Real.sol").write_text(
        "\n".join(
            f"contract Real {{ function knownFunc() public {{}} }} // line{i}"
            for i in range(1, 11)
        ),
        encoding="utf-8",
    )
    return root


def _inv_block(fid: str, title: str, loc: str, severity: str, src: str = "B1-1") -> str:
    return (
        f"## [{fid}] {title}\n\n"
        f"**Severity**: {severity}\n"
        f"**Location**: `{loc}`\n"
        f"**Source IDs**: {src}\n"
    )


def _write_inventory(sp: Path, *blocks: str) -> None:
    (sp / "findings_inventory.md").write_text(
        "# Findings Inventory\n\n" + "\n\n".join(blocks) + "\n", encoding="utf-8"
    )


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


def _write_master_index(sp: Path, *, report_id: str, severity: str, trust_adj: str, internal: str) -> None:
    (sp / "report_index.md").write_text(
        "# Report Index\n\n## Master Finding Index\n\n"
        "| Report ID | Title | Severity | Location | Verification | Trust Adj. | Internal Hypothesis |\n"
        "|-----------|-------|----------|----------|--------------|-----------|--------------------|\n"
        f"| {report_id} | example finding | {severity} | core/Real.sol:L5 | CONFIRMED | {trust_adj} | {internal} |\n",
        encoding="utf-8",
    )


# ===========================================================================
# 1. End-to-end: one finding, both mechanisms fire, single coherent body row
# ===========================================================================

def test_medium_finding_flagged_and_capped_stays_single_coherent_body_finding(tmp_path):
    V = _v()
    root = _mk_project(tmp_path)
    sp = _scratch(tmp_path)

    fid = "H-77"
    # Claimed severity is High everywhere pre-verification (inventory + queue).
    _write_inventory(sp, _inv_block(
        fid, "Fund loss via `ghostFunc4()`", "core/Real.sol:L5", severity="High",
    ))
    _queue(sp, [(fid, "High", "unit")])

    # --- M5a: Gate 3 fires (ghostFunc4 absent everywhere), but severity is
    # High (Medium+) so it is FLAG-ONLY: loc_status stays OK, never appendix.
    recs = V._validate_inventory_evidence(sp, str(root), apply_safe_recovery=False)
    assert recs[fid]["location_status"] == "OK", (
        "Medium+ finding must stay OK (flag-only), never appendix-routed by M5a"
    )
    assert "IDENTIFIER-UNVERIFIED" in recs[fid]["location_reason"]
    assert "ghostFunc4" in recs[fid]["location_reason"]

    # --- M4: verifier's independent assessment (Medium) is LOWER than the
    # claimed severity (High) -> mechanical cap to Medium.
    _verify(sp, fid, verdict="CONFIRMED", independent="Medium", severity="High")
    cap_result = V._apply_independent_severity_caps(sp, "thorough")
    assert len(cap_result) == 1
    assert cap_result[0]["finding_id"] == fid
    assert cap_result[0]["final_severity"] == "Medium"

    # --- Neither gate removed the finding from the active queue.
    removed = V._filter_verification_queue_by_evidence(sp)
    assert fid not in removed, "M5a flag-only path must not remove a Medium+ finding from the queue"
    excluded_path = sp / "verification_queue_evidence_excluded.md"
    if excluded_path.exists():
        assert fid not in excluded_path.read_text(encoding="utf-8")

    # --- The driver-computed expected severity reflects ONLY the M4 cap
    # (M5a never touches severity for a Medium+ flag-only finding).
    expected = V._expected_report_index_severities(sp)
    assert expected.get(fid) == "Medium"

    # --- Build the report_index.md row a report-index agent would write:
    # final severity Medium, Trust Adj. carries the M4 token AND references
    # the M5a human-review flag (as a real writer might, since loc_reason
    # was available context). Both signals must coexist without collision.
    combined_trust_adj = f"INDEPENDENT-MIN(High); flagged by IDENTIFIER-UNVERIFIED human review (`ghostFunc4` unresolved)"
    _write_master_index(
        sp, report_id="M-01", severity="Medium", trust_adj=combined_trust_adj, internal=fid,
    )

    # --- The severity-provenance gate must NOT flag this row: the combined
    # Trust Adj. is recognized as a canonical reason (via the "independent"
    # alternative), so the silent-severity-change halt never fires.
    issues = V._validate_report_index_severity_provenance(sp)
    assert issues == [], f"combined M4+M5a Trust Adj. must be accepted, got: {issues}"

    # --- Single coherent disposition: exactly one row for this finding in
    # the audited report_index rows, at the capped severity, in the Medium
    # tier (body — a real security consequence, never appendix per the
    # material-harm floor).
    rows = V._report_index_rows_for_severity_audit(sp)
    matching = [r for r in rows if fid in r["internal"]]
    assert len(matching) == 1, "finding must not be split into multiple report rows"
    assert matching[0]["report_id"].startswith("M-"), "capped severity must land in the Medium body tier"
    assert matching[0]["severity"] == "Medium"


# ===========================================================================
# 2. Token-collision unit test — order independence, no erasure
# ===========================================================================

def test_independent_min_and_identifier_flag_tokens_coexist_either_order(tmp_path):
    V = _v()
    a = "INDEPENDENT-MIN(High); IDENTIFIER-UNVERIFIED human review flag"
    b = "IDENTIFIER-UNVERIFIED human review flag; INDEPENDENT-MIN(High)"
    assert V._report_index_adjustment_reason_present(a) is True
    assert V._report_index_adjustment_reason_present(b) is True
    # Each signal ALSO independently satisfies the gate (neither is required
    # to carry the other — this proves they don't need to "cooperate" to be
    # individually recognized, i.e. neither erases the other's meaning).
    assert V._report_index_adjustment_reason_present("INDEPENDENT-MIN(High)") is True
    assert V._report_index_adjustment_reason_present("IDENTIFIER-UNVERIFIED human review flag") is True


# ===========================================================================
# 3. M4 caps never touch location/queue-membership state
# ===========================================================================

def test_independent_severity_cap_never_removes_finding_from_queue(tmp_path):
    """M4 is a pure severity transform: applying it must not change queue
    membership, row count, or any location/identifier gate state."""
    V = _v()
    sp = _scratch(tmp_path)
    fid = "H-88"
    _queue(sp, [(fid, "Critical", "unit")])
    _verify(sp, fid, verdict="CONFIRMED", independent="Low", severity="Critical")

    before = V.parse_verification_queue_rows(sp)
    V._apply_independent_severity_caps(sp, "thorough")
    after = V.parse_verification_queue_rows(sp)

    before_ids = {(r.get("finding id") or "").strip() for r in before}
    after_ids = {(r.get("finding id") or "").strip() for r in after}
    assert before_ids == after_ids == {fid}, "M4 must not add/remove queue rows"


# ===========================================================================
# 4. Both gates never fully drop a finding — appendix-at-worst
# ===========================================================================

def test_low_severity_identifier_unverified_is_appendix_not_deleted_even_with_cap_ledger(tmp_path):
    """Edge case: a Low finding is appendix-routed by M5a (Gate 3 hard path)
    while an (unrelated) independent_severity_caps.md ledger also exists in
    the same run. Confirm the M5a appendix routing still produces a ledger
    entry (not a silent delete) and `_expected_report_index_severities` does
    not crash or lose the OTHER (unrelated) finding's cap."""
    V = _v()
    root = _mk_project(tmp_path)
    sp = _scratch(tmp_path)

    low_fid = "L-09"
    capped_fid = "H-99"
    _write_inventory(
        sp,
        _inv_block(low_fid, "Dead code via `ghostFunc5()`", "core/Real.sol:L5", severity="Low"),
        _inv_block(capped_fid, "Fund loss via `knownFunc()`", "core/Real.sol:L5", severity="High"),
    )
    recs = V._validate_inventory_evidence(sp, str(root), apply_safe_recovery=False)
    assert recs[low_fid]["location_status"] == "IDENTIFIER_UNVERIFIED"
    assert recs[capped_fid]["location_status"] == "OK"

    _queue(sp, [(low_fid, "Low", "unit"), (capped_fid, "High", "unit")])
    _verify(sp, low_fid, verdict="CONFIRMED", independent=None, severity="Low")
    _verify(sp, capped_fid, verdict="CONFIRMED", independent="Medium", severity="High")
    V._apply_independent_severity_caps(sp, "thorough")

    removed = V._filter_verification_queue_by_evidence(sp)
    assert low_fid in removed, "Low IDENTIFIER_UNVERIFIED is appendix-routed (ledger, not deleted)"
    assert capped_fid not in removed, "Medium+/capped finding must remain active"

    excluded_path = sp / "verification_queue_evidence_excluded.md"
    assert excluded_path.exists(), "appendix routing must leave a traceable ledger, never a silent drop"
    excluded_text = excluded_path.read_text(encoding="utf-8")
    assert low_fid in excluded_text

    expected = V._expected_report_index_severities(sp)
    assert expected.get(capped_fid) == "Medium", "unrelated M4 cap must survive the M5a appendix routing"
    # The appendix-routed Low finding no longer appears in the ACTIVE queue's
    # expected-severity map (it left active verification), but it is NOT
    # silently deleted from the run: its original severity is preserved
    # verbatim in the appendix ledger row (data survives, just relocated).
    assert low_fid not in expected, (
        "appendix-routed finding is not part of the active severity map "
        "(it is not silently re-injected with a fabricated severity either)"
    )
    assert f"| {low_fid} | Low |" in excluded_text, (
        "original severity must be preserved verbatim in the appendix ledger, not dropped"
    )


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
