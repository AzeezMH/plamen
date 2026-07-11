"""Tests for the generic mechanical SECOND-CHANNEL skill dispatch
(_seed_mechanical_flag) and its EVM cross-chain-message consumer
(_seed_cross_chain_msg_flag).

The mechanical second channel is a deterministic backup to the LLM recon's
own flag detection: a marker/import grep over production source flips a
skill's Required column, emits its flag into detected_patterns.md, and notes
it in recon_summary.md — all gated on the pre-pass marker (manifest
priority), so a skill still fires even when the LLM recon pass misses it.
"""
from __future__ import annotations

from pathlib import Path

import recon_prepass as rp


def _parse_required(scratch: Path) -> list[str]:
    """Lightweight local re-implementation of Required=YES row parsing so
    this test file has no dependency on plamen_prompt's L1-flavored parser
    (which skips ## Niche Agents sections — irrelevant here but avoids
    conflating two independent contracts)."""
    tr = scratch / "template_recommendations.md"
    if not tr.exists():
        return []
    required = []
    for line in tr.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        cols = [c.strip() for c in s.strip("|").split("|")]
        if len(cols) < 3:
            continue
        name = cols[0].strip("`").strip("*").strip()
        req = cols[2].strip("`").strip("*").strip().upper()
        if name and req == "YES":
            required.append(name)
    return required


EVM_TEMPLATE_RECOMMENDATIONS = """\
# Template Recommendations

[LLM TO ENRICH] Pre-pass stub. Every row below is `Required=NO` by default.

## BINDING MANIFEST

### EVM Skills

| Skill | Trigger | Required | Rationale |
|-------|---------|----------|-----------|
| `ORACLE_ANALYSIS` | ORACLE flag | NO | [LLM TO ENRICH] |
| `CROSS_CHAIN_MESSAGE_INTEGRITY` | CROSS_CHAIN_MSG flag | NO | [LLM TO ENRICH] |
"""


class TestSeedMechanicalFlagGeneric:
    """Direct tests of the shared 3-step helper, independent of any specific
    detector."""

    def test_flips_row_and_emits_flags(self, tmp_path: Path):
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        marker = rp._PREPASS_MARKER + "\n"
        (scratch / "template_recommendations.md").write_text(
            marker + EVM_TEMPLATE_RECOMMENDATIONS, encoding="utf-8"
        )
        (scratch / "recon_summary.md").write_text(
            marker + "# Recon Summary\n\n- **Language**: evm\n", encoding="utf-8"
        )

        rp._seed_mechanical_flag(
            scratch,
            rows_to_flip={"ORACLE_ANALYSIS": "Synthetic test trigger (mechanical). "},
            flags=["SYNTHETIC_FLAG"],
            detected_patterns_header="synthetic test",
            detected_patterns_body="Synthetic marker detected for test purposes.",
            summary_note="synthetic marker detected",
        )

        tr = (scratch / "template_recommendations.md").read_text(encoding="utf-8")
        assert "SYNTHETIC_FLAG" not in tr  # rationale text doesn't echo the flag
        assert "ORACLE_ANALYSIS" in _parse_required(scratch)
        # The untouched row must remain NO.
        assert "CROSS_CHAIN_MESSAGE_INTEGRITY" not in _parse_required(scratch)

        rs = (scratch / "recon_summary.md").read_text(encoding="utf-8")
        assert "SYNTHETIC_FLAG" in rs
        assert "synthetic marker detected" in rs

        dp = (scratch / "detected_patterns.md").read_text(encoding="utf-8")
        assert "SYNTHETIC_FLAG" in dp
        assert "Synthetic marker detected for test purposes." in dp

    def test_manifest_priority_skips_enriched_template_recommendations(
        self, tmp_path: Path
    ):
        """A template_recommendations.md that no longer carries the pre-pass
        marker (i.e. the LLM recon already enriched it) must be left
        untouched by the mechanical seeder."""
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        enriched = (
            "# Template Recommendations\n\n## BINDING MANIFEST\n\n### EVM Skills\n\n"
            "| Skill | Trigger | Required | Rationale |\n"
            "|-------|---------|----------|-----------|\n"
            "| `ORACLE_ANALYSIS` | ORACLE flag | NO | LLM decided not applicable |\n"
        )
        (scratch / "template_recommendations.md").write_text(enriched, encoding="utf-8")

        rp._seed_mechanical_flag(
            scratch,
            rows_to_flip={"ORACLE_ANALYSIS": "Should never be applied. "},
            flags=["SYNTHETIC_FLAG"],
            detected_patterns_header="synthetic test",
            detected_patterns_body="Synthetic marker detected for test purposes.",
            summary_note="synthetic marker detected",
        )

        tr = (scratch / "template_recommendations.md").read_text(encoding="utf-8")
        assert tr == enriched
        assert "ORACLE_ANALYSIS" not in _parse_required(scratch)

    def test_manifest_priority_skips_enriched_detected_patterns(self, tmp_path: Path):
        """A detected_patterns.md without the marker (LLM-enriched) must not
        be appended to; and since it already exists, no new stub is written
        either."""
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        marker = rp._PREPASS_MARKER + "\n"
        (scratch / "template_recommendations.md").write_text(
            marker + EVM_TEMPLATE_RECOMMENDATIONS, encoding="utf-8"
        )
        enriched_dp = "# Detected Patterns\n\nLLM found nothing relevant.\n"
        (scratch / "detected_patterns.md").write_text(enriched_dp, encoding="utf-8")

        rp._seed_mechanical_flag(
            scratch,
            rows_to_flip={"ORACLE_ANALYSIS": "Synthetic. "},
            flags=["SYNTHETIC_FLAG"],
            detected_patterns_header="synthetic test",
            detected_patterns_body="Synthetic marker detected for test purposes.",
            summary_note="synthetic marker detected",
        )

        dp = (scratch / "detected_patterns.md").read_text(encoding="utf-8")
        assert dp == enriched_dp
        # But the (still pre-pass-owned) template_recommendations.md row DID flip.
        assert "ORACLE_ANALYSIS" in _parse_required(scratch)


class TestCrossChainMsgDetector:
    """The EVM CROSS_CHAIN_MESSAGE_INTEGRITY mechanical second channel."""

    def _scratch_with_manifest(self, tmp_path: Path) -> Path:
        scratch = tmp_path / "scratch"
        scratch.mkdir()
        marker = rp._PREPASS_MARKER + "\n"
        (scratch / "template_recommendations.md").write_text(
            marker + EVM_TEMPLATE_RECOMMENDATIONS, encoding="utf-8"
        )
        (scratch / "recon_summary.md").write_text(
            marker + "# Recon Summary\n\n- **Language**: evm\n", encoding="utf-8"
        )
        return scratch

    def test_marker_present_detected(self, tmp_path: Path):
        proj = tmp_path / "proj"
        (proj / "src").mkdir(parents=True)
        (proj / "src" / "Bridge.sol").write_text(
            "pragma solidity ^0.8.20;\n\n"
            "contract Bridge {\n"
            "    function lzReceive(uint16 srcId, bytes calldata payload) external {\n"
            "        // handle inbound message\n"
            "    }\n"
            "}\n",
            encoding="utf-8",
        )
        assert rp._detect_cross_chain_msg_markers(proj) is True

        scratch = self._scratch_with_manifest(tmp_path)
        status = rp._seed_cross_chain_msg_flag(scratch, proj)
        assert status == "DETECTED:CROSS_CHAIN_MSG"

        assert "CROSS_CHAIN_MESSAGE_INTEGRITY" in _parse_required(scratch)
        # Unrelated row stays NO.
        assert "ORACLE_ANALYSIS" not in _parse_required(scratch)

        dp = (scratch / "detected_patterns.md").read_text(encoding="utf-8")
        assert "CROSS_CHAIN_MSG" in dp

        rs = (scratch / "recon_summary.md").read_text(encoding="utf-8")
        assert "CROSS_CHAIN_MSG" in rs

    def test_marker_absent_not_detected_no_false_fire(self, tmp_path: Path):
        proj = tmp_path / "proj"
        (proj / "src").mkdir(parents=True)
        (proj / "src" / "Vault.sol").write_text(
            "pragma solidity ^0.8.20;\n\n"
            "contract Vault {\n"
            "    function deposit(uint256 amount) external {}\n"
            "    function withdraw(uint256 amount) external {}\n"
            "}\n",
            encoding="utf-8",
        )
        assert rp._detect_cross_chain_msg_markers(proj) is False

        scratch = self._scratch_with_manifest(tmp_path)
        status = rp._seed_cross_chain_msg_flag(scratch, proj)
        assert status == "NOT_DETECTED"

        # Row must remain untouched (still NO / not in required list).
        assert "CROSS_CHAIN_MESSAGE_INTEGRITY" not in _parse_required(scratch)
        tr = (scratch / "template_recommendations.md").read_text(encoding="utf-8")
        assert "| `CROSS_CHAIN_MESSAGE_INTEGRITY` | CROSS_CHAIN_MSG flag | NO |" in tr

        # No detected_patterns.md should have been created (no-op on miss).
        assert not (scratch / "detected_patterns.md").exists()

    def test_marker_in_test_dir_excluded(self, tmp_path: Path):
        """Markers in test/mock source must not trip the detector — only
        production source is scanned."""
        proj = tmp_path / "proj"
        (proj / "test").mkdir(parents=True)
        (proj / "test" / "MockBridge.sol").write_text(
            "pragma solidity ^0.8.20;\n\n"
            "contract MockBridge {\n"
            "    function lzReceive(uint16, bytes calldata) external {}\n"
            "}\n",
            encoding="utf-8",
        )
        assert rp._detect_cross_chain_msg_markers(proj) is False

    def test_manifest_priority_already_enriched_left_untouched(self, tmp_path: Path):
        """If template_recommendations.md was already enriched by the LLM
        recon (no marker), the mechanical detector must not rewrite it, even
        though the marker scan itself still fires."""
        proj = tmp_path / "proj"
        (proj / "src").mkdir(parents=True)
        (proj / "src" / "Bridge.sol").write_text(
            "pragma solidity ^0.8.20;\n\n"
            "contract Bridge {\n"
            "    function ccipReceive(bytes calldata message) external {}\n"
            "}\n",
            encoding="utf-8",
        )

        scratch = tmp_path / "scratch"
        scratch.mkdir()
        enriched = (
            "# Template Recommendations\n\n## BINDING MANIFEST\n\n### EVM Skills\n\n"
            "| Skill | Trigger | Required | Rationale |\n"
            "|-------|---------|----------|-----------|\n"
            "| `CROSS_CHAIN_MESSAGE_INTEGRITY` | CROSS_CHAIN_MSG flag | NO | "
            "LLM reviewed, not applicable |\n"
        )
        (scratch / "template_recommendations.md").write_text(enriched, encoding="utf-8")

        status = rp._seed_cross_chain_msg_flag(scratch, proj)
        # Detection itself still fires (mechanism is independent of file state)...
        assert status == "DETECTED:CROSS_CHAIN_MSG"
        # ...but the enriched file on disk is untouched.
        tr = (scratch / "template_recommendations.md").read_text(encoding="utf-8")
        assert tr == enriched
        assert "CROSS_CHAIN_MESSAGE_INTEGRITY" not in _parse_required(scratch)
