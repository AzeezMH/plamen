"""C Fix 2 — report_dedup coverage receipt.

The driver pre-computes candidate pairs (C Fix 1) into
``report_dedup_candidate_pairs.md``; the phase6d agent must then explicitly
DISPOSE every candidate (MERGE or Kept-Separate). ``_report_dedup_coverage_gaps``
surfaces any candidate pair the agent silently skipped — VISIBILITY ONLY (it
never merges, drops, or reorders anything). These tests pin that parser + gap
detector and the prompt receipt rule.
"""
from pathlib import Path

import plamen_mechanical as M

_CAND_HINT = """# Report Dedup Candidate Pairs

12 candidate pair(s): findings on the SAME file ...

| Survivor (higher sev) | Absorbed candidate | Tier | File | Loc A | Loc B | Signal |
|-----------------------|--------------------|------|------|-------|-------|--------|
| M-01: permissionless setFee drains fees | M-06: setFee has no owner gate | same-tier | Vault.sol | L10-20 | L12-22 | location (±2/±2 lines) |
| H-02: reentrancy in withdraw | M-09: withdraw missing nonReentrant | cross-tier | Vault.sol | L40-55 | L41-56 | location (±1/±1 lines) |
"""


def _write_hint(sp: Path) -> None:
    (sp / "report_dedup_candidate_pairs.md").write_text(_CAND_HINT, encoding="utf-8")


def test_parse_candidate_pairs(tmp_path: Path):
    _write_hint(tmp_path)
    pairs = M._report_dedup_candidate_pairs_from_hint(tmp_path)
    assert ("M-01", "M-06") in pairs
    assert ("H-02", "M-09") in pairs
    assert len(pairs) == 2


def test_no_candidate_file_is_no_gaps(tmp_path: Path):
    assert M._report_dedup_coverage_gaps(tmp_path) == []


def test_all_candidates_disposed_no_gap(tmp_path: Path):
    _write_hint(tmp_path)
    # Both pairs disposed: one merged, one kept-separate.
    (tmp_path / "report_dedup_agent_decisions.md").write_text(
        "# Report Consolidation Decisions\n\n"
        "## MERGE Decisions\n"
        "| Survivor | Absorbed | Same Root Cause | Reason |\n"
        "|----------|----------|-----------------|--------|\n"
        "| M-01 | M-06 | YES | same missing owner gate on setFee |\n\n"
        "## Quality Observation Reclassifications\n"
        "| Report ID | Class | Reason |\n"
        "|-----------|-------|--------|\n\n"
        "## Reviewed — Kept Separate\n"
        "| Report ID(s) | Reason kept separate |\n"
        "|--------------|----------------------|\n"
        "| H-02, M-09 | reentrancy vs a defense-in-depth modifier request — different fix |\n",
        encoding="utf-8",
    )
    assert M._report_dedup_coverage_gaps(tmp_path) == []


def test_undisposed_candidate_is_a_gap(tmp_path: Path):
    _write_hint(tmp_path)
    # Only the first pair is disposed; H-02~M-09 is silently skipped.
    (tmp_path / "report_dedup_agent_decisions.md").write_text(
        "# Report Consolidation Decisions\n\n"
        "## MERGE Decisions\n"
        "| Survivor | Absorbed | Same Root Cause | Reason |\n"
        "|----------|----------|-----------------|--------|\n"
        "| M-01 | M-06 | YES | same missing owner gate |\n\n"
        "## Reviewed — Kept Separate\n"
        "| Report ID(s) | Reason kept separate |\n"
        "|--------------|----------------------|\n",
        encoding="utf-8",
    )
    gaps = M._report_dedup_coverage_gaps(tmp_path)
    assert gaps == [("H-02", "M-09")]


def test_missing_decisions_file_all_candidates_are_gaps(tmp_path: Path):
    _write_hint(tmp_path)
    gaps = M._report_dedup_coverage_gaps(tmp_path)
    assert set(gaps) == {("M-01", "M-06"), ("H-02", "M-09")}


def test_phase6d_prompt_has_coverage_receipt_rule():
    import plamen_driver as d
    p = d.plamen_home() / "prompts" / "shared" / "v2" / "phase6d-report-dedup-agent.md"
    text = p.read_text(encoding="utf-8")
    assert "Coverage receipt (MANDATORY)" in text
    assert "MUST receive an EXPLICIT disposition" in text
    # The receipt forces a decision, never a merge (recall-safe wording present).
    assert "never forces a merge" in text


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
