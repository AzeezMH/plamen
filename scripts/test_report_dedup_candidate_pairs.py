"""Fix 4 + Fix 1 (item C): report-stage same-tier AND cross-tier candidate list.

``_compute_report_dedup_candidate_pairs`` reads report_index.md's Master Finding
Index and emits ``report_dedup_candidate_pairs.md`` listing:
  - every pair (ANY tier combination) whose FIRST Location range matches within
    ±3 lines on both endpoints on the same file (Fix 4, widened by Fix 1 to also
    fire same-tier), and
  - SAME-TIER pairs on the same file whose titles overlap (>= 0.50) or share a
    specific identifier, even when locations do not match (Fix 1 — the gap where
    same-tier merging depended on the LLM doing unaided exhaustive comparison).
It is a CANDIDATE HINT generator only — it NEVER merges anything (the
report_dedup_agent's same-root-cause + same-fix test + the Python zero-loss gate
remain the sole merge authority). These tests assert the ±3 tolerance is honored
(neither loosened nor tightened), cross-tier location behavior is UNCHANGED, the
flagship identical-location twin surfaces, same-tier pairs now surface via both
the location and the title/anchor signals, distinct-mechanism same-location pairs
surface as candidates only, and the helper mutates nothing but its own hint file.
"""
from pathlib import Path

from plamen_parsers import (
    _compute_report_dedup_candidate_pairs,
    _parse_report_index_master_rows,
    _report_index_first_location,
    _llm_norm,
)


_INDEX = """# Report Index

## Master Finding Index

| Report ID | Title | Severity | Location | Verification | Trust Adj. | Internal Hypothesis |
|-----------|-------|----------|----------|--------------|-----------|--------------------|
| H-01 | Public `withdraw` lacks access modifier | High | NativeVault.sol:286-304 | VERIFIED | - | HH-11 |
| M-06 | `withdraw` permissionless-path defect | Medium | NativeVault.sol:286-304 | VERIFIED | - | H-36 |
| M-22 | Public `withdraw`/`onRevert` refund-path interaction | Medium | NativeVault.sol:286-304,607-638 | CONTESTED | - | H-02 |
| H-04 | claimPayout non-EVM branch guard self-satisfies | High | NativeVault.sol:661-680; CrossChainRouter.sol:571-590 | VERIFIED | - | HH-02 |
| L-14 | claimPayout emits event fields after delete | Low | NativeVault.sol:661-679,674-678 | VERIFIED | - | HL-07 |
| M-10 | decompressAccounts OOB read | Medium | libraries/PayloadCodec.sol:19-56 | VERIFIED | - | HM-04 |
| L-26 | decompressAccounts contested facets | Low | PayloadCodec.sol:19-56 | CONTESTED | - | HM-01 |
| M-01 | Fee/accounting asymmetry in claimPayout | Medium | NativeVault.sol:661-680 | VERIFIED | - | H-21 |
| M-27 | claimPayout CEI ordering / reentrancy gap | Medium | NativeVault.sol:661-680 | VERIFIED | - | HH-05 |
| I-07 | MessageRouter general code-quality observation | Informational | MessageRouter.sol (file) | VERIFIED | - | H-116 |
| L-07 | Shared constant across gateways | Low | CrossChainRouter.sol:19 | VERIFIED | - | H-63 |
| H-05 | bytes20 truncation | High | CrossChainRouter.sol:291 | VERIFIED | - | HH-15 |

## Tier Assignments

### Critical+High Tier
- H-01
- H-04
- H-05

### Medium Tier
- M-06 at NativeVault.sol:286-304
"""


def _write_index(scratchpad: Path, text: str = _INDEX) -> None:
    (scratchpad / "report_index.md").write_text(text, encoding="utf-8")


def _parse_pairs(scratchpad: Path) -> set[frozenset[str]]:
    """Parse the emitted hint table into a set of {A,B} report-ID pairs."""
    out: set[frozenset[str]] = set()
    txt = (scratchpad / "report_dedup_candidate_pairs.md").read_text(
        encoding="utf-8"
    )
    import re
    for line in txt.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        a = re.match(r"([CHMLI]-\d+)", cells[0])
        b = re.match(r"([CHMLI]-\d+)", cells[1])
        if a and b:
            out.add(frozenset((a.group(1), b.group(1))))
    return out


# --------------------------------------------------------------------------
# First-location extraction
# --------------------------------------------------------------------------
def test_first_location_takes_first_site_only():
    base, lr = _report_index_first_location(
        "NativeVault.sol:530-537, :425-432; CrossChainRouter.sol swap"
    )
    assert base == "nativevault.sol"
    assert lr == (530, 537)


def test_first_location_single_line():
    base, lr = _report_index_first_location("CrossChainRouter.sol:291")
    assert base == "crosschainrouter.sol"
    assert lr == (291, 291)


def test_first_location_basename_strips_dir():
    base, lr = _report_index_first_location("libraries/PayloadCodec.sol:19-56")
    assert base == "payloadcodec.sol"
    assert lr == (19, 56)


def test_first_location_no_range_returns_none():
    base, lr = _report_index_first_location("MessageRouter.sol (file)")
    assert base == ""
    assert lr is None


# --------------------------------------------------------------------------
# Master Finding Index parsing (header-aware, section-bounded)
# --------------------------------------------------------------------------
def test_master_rows_ignore_tier_assignments():
    rows = _parse_report_index_master_rows(_llm_norm(_INDEX))
    ids = [r["report_id"] for r in rows]
    # Every Master Finding Index row parsed exactly once ...
    assert ids.count("M-06") == 1
    assert ids.count("H-01") == 1
    # ... and the Tier Assignments bullets are NOT parsed as findings.
    assert len(rows) == 12


# --------------------------------------------------------------------------
# Candidate-pair generation
# --------------------------------------------------------------------------
def test_flagship_identical_location_twin_surfaces(tmp_path: Path):
    _write_index(tmp_path)
    n = _compute_report_dedup_candidate_pairs(tmp_path)
    assert n > 0
    pairs = _parse_pairs(tmp_path)
    # The flagship: a High and a Medium at the exact same lines.
    assert frozenset(("H-01", "M-06")) in pairs


def test_cross_tier_location_pairs_still_present(tmp_path: Path):
    """Fix 1 scopes the NEW title/anchor signals to same-tier pairs only —
    cross-tier candidate generation stays location-range-only, UNCHANGED from
    before. This replaces the old (now-incorrect) 'same-tier never leaks'
    invariant: same-tier pairs are now an intentional, tested capability (see
    test_same_tier_pairs_now_surface_via_location below), not a leak."""
    _write_index(tmp_path)
    _compute_report_dedup_candidate_pairs(tmp_path)
    pairs = _parse_pairs(tmp_path)
    cross_tier_pairs = {p for p in pairs if len({rid[0] for rid in p}) == 2}
    assert frozenset(("H-01", "M-06")) in cross_tier_pairs
    assert frozenset(("M-10", "L-26")) in cross_tier_pairs


def test_same_tier_pairs_now_surface_via_location(tmp_path: Path):
    """Fix 1 (item C): M-06 and M-22 are BOTH Medium (same tier) at the same
    location (NativeVault.sol:286-304). Before Fix 1 this pair was silently
    dropped by the ``if fa["tier"] == fb["tier"]: continue`` skip, so the
    LLM proposer never saw it as a candidate. It must now surface as a
    candidate HINT (this helper still never decides the merge)."""
    _write_index(tmp_path)
    _compute_report_dedup_candidate_pairs(tmp_path)
    pairs = _parse_pairs(tmp_path)
    assert frozenset(("M-06", "M-22")) in pairs
    # M-01 and M-27 are also both Medium at the exact same NativeVault.sol
    # range (661-680) — a second same-tier regression check.
    assert frozenset(("M-01", "M-27")) in pairs
    # The helper still writes ONLY its hint file for this widened case too.
    assert (tmp_path / "report_index.md").read_text(encoding="utf-8") == _INDEX
    assert not (tmp_path / "report_dedup_mapping.md").exists()


def test_same_tier_title_and_anchor_signal_zero_location_overlap(tmp_path: Path):
    """POSITIVE CONTROL (item C, mandate b): two SAME-TIER findings describing
    the same bug via a shared code identifier in the title, at locations that
    do NOT overlap (far outside the +/-3 tolerance) and whose titles share no
    generic wording besides that identifier. Fix 1's title/shared-identifier
    signal must still surface them as a candidate — the location-range signal
    alone would miss this pair entirely."""
    idx = """# Report Index

## Master Finding Index

| Report ID | Title | Severity | Location | Verification | Trust Adj. | Internal Hypothesis |
|-----------|-------|----------|----------|--------------|-----------|--------------------|
| M-30 | `_settleEpochRewards` skips users who claimed mid-epoch | Medium | RewardVault.sol:100-110 | VERIFIED | - | X-30 |
| M-31 | Reward accounting drifts because `_settleEpochRewards` under-counts | Medium | RewardVault.sol:400-410 | VERIFIED | - | X-31 |
| M-32 | Unrelated fee rounding error | Medium | RewardVault.sol:700-710 | VERIFIED | - | X-32 |
"""
    _write_index(tmp_path, idx)
    n = _compute_report_dedup_candidate_pairs(tmp_path)
    assert n > 0
    pairs = _parse_pairs(tmp_path)
    assert frozenset(("M-30", "M-31")) in pairs
    # M-32 shares neither location nor title/identifier wording with either —
    # must NOT be pulled in as a false candidate.
    assert frozenset(("M-30", "M-32")) not in pairs
    assert frozenset(("M-31", "M-32")) not in pairs


def test_cross_tier_far_apart_titles_do_not_pair(tmp_path: Path):
    """Cross-tier pairs do NOT get the title/anchor fallback (unchanged
    behavior) — only same-tier pairs do. Two cross-tier findings at
    non-overlapping locations that happen to share a title identifier must
    NOT be paired, since that would be a behavior change to the cross-tier
    path the task explicitly requires stay unchanged."""
    idx = """# Report Index

## Master Finding Index

| Report ID | Title | Severity | Location | Verification | Trust Adj. | Internal Hypothesis |
|-----------|-------|----------|----------|--------------|-----------|--------------------|
| H-08 | `_settleEpochRewards` skips users who claimed mid-epoch | High | RewardVault.sol:100-110 | VERIFIED | - | X-8 |
| M-33 | Reward accounting drifts because `_settleEpochRewards` under-counts | Medium | RewardVault.sol:400-410 | VERIFIED | - | X-33 |
"""
    _write_index(tmp_path, idx)
    _compute_report_dedup_candidate_pairs(tmp_path)
    pairs = _parse_pairs(tmp_path)
    assert frozenset(("H-08", "M-33")) not in pairs


def test_distinct_mechanism_same_location_is_candidate_not_merged(tmp_path: Path):
    """H-01 and M-22 sit at the same lines but are different mechanisms.

    The helper surfaces the pair as a CANDIDATE — it must NOT decide the merge.
    Merge authority stays with the LLM proposer + zero-loss gate.
    """
    _write_index(tmp_path)
    _compute_report_dedup_candidate_pairs(tmp_path)
    pairs = _parse_pairs(tmp_path)
    assert frozenset(("H-01", "M-22")) in pairs
    # The helper writes ONLY its hint file — it never mutates report_index.md
    # (the source of truth) and never produces a merge-decisions/mapping file.
    assert (tmp_path / "report_index.md").read_text(encoding="utf-8") == _INDEX
    assert not (tmp_path / "report_dedup_mapping.md").exists()
    assert not (tmp_path / "AUDIT_REPORT.md").exists()


def test_cross_file_same_lines_not_paired(tmp_path: Path):
    """M-10 (PayloadCodec 19-56) must NOT pair with H-05 (CrossChain 291).

    Same lines only counts on the SAME file. M-10/L-26 (both PayloadCodec
    19-56, cross-tier) MUST pair despite one carrying a `libraries/` prefix.
    """
    _write_index(tmp_path)
    _compute_report_dedup_candidate_pairs(tmp_path)
    pairs = _parse_pairs(tmp_path)
    assert frozenset(("M-10", "L-26")) in pairs
    assert frozenset(("M-10", "H-05")) not in pairs


def test_tolerance_boundary_pm3(tmp_path: Path):
    """±3 both endpoints qualifies; ±4 on either endpoint does not."""
    idx = """# Report Index

## Master Finding Index

| Report ID | Title | Severity | Location | Verification | Trust Adj. | Internal Hypothesis |
|-----------|-------|----------|----------|--------------|-----------|--------------------|
| H-01 | anchor | High | A.sol:100-120 | VERIFIED | - | X-1 |
| M-01 | within +3 both | Medium | A.sol:103-123 | VERIFIED | - | X-2 |
| M-02 | start +4 (out) | Medium | A.sol:104-120 | VERIFIED | - | X-3 |
| M-03 | end +4 (out) | Medium | A.sol:100-124 | VERIFIED | - | X-4 |
| M-04 | exact | Medium | A.sol:100-120 | VERIFIED | - | X-5 |
"""
    _write_index(tmp_path, idx)
    _compute_report_dedup_candidate_pairs(tmp_path)
    pairs = _parse_pairs(tmp_path)
    assert frozenset(("H-01", "M-01")) in pairs   # +3/+3 → in
    assert frozenset(("H-01", "M-04")) in pairs   # exact → in
    assert frozenset(("H-01", "M-02")) not in pairs  # +4 start → out
    assert frozenset(("H-01", "M-03")) not in pairs  # +4 end → out


def test_no_index_returns_zero_no_file(tmp_path: Path):
    n = _compute_report_dedup_candidate_pairs(tmp_path)
    assert n == 0
    assert not (tmp_path / "report_dedup_candidate_pairs.md").exists()


def test_no_candidates_writes_empty_marker(tmp_path: Path):
    idx = """# Report Index

## Master Finding Index

| Report ID | Title | Severity | Location | Verification | Trust Adj. | Internal Hypothesis |
|-----------|-------|----------|----------|--------------|-----------|--------------------|
| H-01 | lone high | High | A.sol:10-20 | VERIFIED | - | X-1 |
| M-01 | far medium | Medium | A.sol:500-520 | VERIFIED | - | X-2 |
"""
    _write_index(tmp_path, idx)
    n = _compute_report_dedup_candidate_pairs(tmp_path)
    assert n == 0
    body = (tmp_path / "report_dedup_candidate_pairs.md").read_text(
        encoding="utf-8"
    )
    assert "No same-tier or cross-tier candidate pairs" in body


def test_cap_never_exceeded(tmp_path: Path):
    from plamen_parsers import _REPORT_DEDUP_CANDIDATE_CAP
    # Build a pathological index: many cross-tier findings at the same lines.
    lines = [
        "# Report Index", "", "## Master Finding Index", "",
        "| Report ID | Title | Severity | Location | Verification | Trust Adj. | Internal Hypothesis |",
        "|--|--|--|--|--|--|--|",
    ]
    # Alternate H/M tiers so every pair is cross-tier, all at A.sol:10-20.
    for i in range(1, 40):
        tier = "H" if i % 2 else "M"
        lines.append(f"| {tier}-{i:02d} | f{i} | X | A.sol:10-20 | VERIFIED | - | X-{i} |")
    _write_index(tmp_path, "\n".join(lines) + "\n")
    n = _compute_report_dedup_candidate_pairs(tmp_path)
    assert n <= _REPORT_DEDUP_CANDIDATE_CAP
