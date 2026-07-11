"""
Tests for ITEM B1 — Reported-vs-Held Asset Divergence at Dust Supply directive.

Verifies agents/skills/injectable/vault-accounting/SKILL.md contains a new
generic §2c directive covering the case where an intentionally-overridden
accounting getter (e.g. totalAssets()) can rise purely from elapsed
time/vesting with no deposit/withdraw/donation event, and that rise closes
while totalSupply is zero/dust — diluting (not just enriching) the
depositor. Also verifies the directive stays protocol-agnostic (Part 0:
no protocol/contest/token proper nouns), matching the no-overfit rule in
~/.plamen/rules/post-audit-improvement-protocol.md and
feedback_no_overfit.md.
"""
import re
from pathlib import Path

import pytest

SKILL_PATH = (
    Path(__file__).resolve().parent.parent
    / "agents"
    / "skills"
    / "injectable"
    / "vault-accounting"
    / "SKILL.md"
)

# Proper nouns that would constitute Part-0 overfitting if they appeared in
# the new §2c directive text (specific protocols / audit contests / past
# finding sources). NOT an exhaustive ban on the whole file -- pre-existing
# illustrative names elsewhere in the skill (e.g. an existing "X-style"
# example in an older section) are out of scope for this item; only the
# NEW §2c section text is checked.
BANNED_PROPER_NOUNS = [
    "pareto",
    "sherlock",
    "burve",
    "yearn",
    "synthetix",
    "aave",
    "compound",
    "curve",
    "balancer",
    "uniswap",
    "makerdao",
    "zetachain",
    "irys",
    "awesomex",
    "umia",
    "code4rena",
    "immunefi",
    "cantina",
]


def _read_skill_text() -> str:
    assert SKILL_PATH.exists(), f"SKILL.md not found at {SKILL_PATH}"
    return SKILL_PATH.read_text(encoding="utf-8")


def _extract_section_2c(text: str) -> str:
    """
    Extract the §2c section body: from the '2c' heading (### 2c. or ## 2c)
    up to (but not including) the next heading of level <= the 2c heading's
    level, or end of file. Raises AssertionError if no 2c heading is found
    (this is intentional -- the extraction must fail on the unmodified file
    so both tests fail before the directive is added).
    """
    heading_re = re.compile(
        r'^(#{2,4})\s*2c[.\s]', re.MULTILINE
    )
    match = heading_re.search(text)
    assert match is not None, (
        "No '2c' heading (## 2c / ### 2c.) found in vault-accounting SKILL.md "
        "-- the §2c directive has not been added yet."
    )
    level = len(match.group(1))
    start = match.start()

    # Find the next heading at the same or shallower level after this one.
    next_heading_re = re.compile(
        r'^(#{2,' + str(level) + r'})\s+\S', re.MULTILINE
    )
    tail_search = next_heading_re.search(text, match.end())
    end = tail_search.start() if tail_search else len(text)

    return text[start:end]


class TestDirectivePresent:
    """(a) The §2c directive exists with the required heading and key phrases."""

    def test_2c_heading_present(self):
        text = _read_skill_text()
        section = _extract_section_2c(text)
        assert "Reported-vs-Held Asset Divergence" in section
        assert "Dust Supply" in section

    def test_2c_covers_time_only_increase(self):
        text = _read_skill_text()
        section = _extract_section_2c(text)
        assert "elapsed time" in section.lower() or "purely from elapsed" in section.lower()
        # Must exclude the unvested/streaming/pending component explicitly.
        assert re.search(r'unvested|streaming|pending', section, re.IGNORECASE)

    def test_2c_covers_dust_supply_share_math(self):
        text = _read_skill_text()
        section = _extract_section_2c(text)
        assert "totalSupply" in section
        assert re.search(r'dust', section, re.IGNORECASE)
        # The share-computation formula with real constants for minimal deposit.
        assert "shares" in section.lower()
        assert re.search(r'reportedAssets\s*\(\s*\)', section)

    def test_2c_covers_depositor_loses_direction(self):
        text = _read_skill_text()
        section = _extract_section_2c(text)
        # Must frame this as a depositor-loses finding, not only attacker-profits.
        assert re.search(r'depositor[\s\-]*loses|dilut', section, re.IGNORECASE)
        assert "first-depositor" in section.lower() or "inflation" in section.lower()

    def test_2c_references_own_formula_not_external_donation(self):
        text = _read_skill_text()
        section = _extract_section_2c(text)
        assert re.search(r"protocol'?s\s+OWN\s+accounting\s+formula|own accounting formula", section, re.IGNORECASE)
        assert re.search(r'external donation', section, re.IGNORECASE)

    def test_2c_referenced_in_step_execution_checklist(self):
        text = _read_skill_text()
        checklist_match = re.search(
            r'## Step Execution Checklist(.*)', text, re.DOTALL
        )
        assert checklist_match is not None, "Step Execution Checklist section missing"
        checklist = checklist_match.group(1)
        assert re.search(r'2c\.?\s+Reported-vs-Held Asset Divergence', checklist), (
            "Step Execution Checklist has no row for the new 2c directive"
        )

    def test_2c_referenced_in_orchestrator_decomposition_guide(self):
        text = _read_skill_text()
        guide_match = re.search(
            r'## Orchestrator Decomposition Guide(.*?)\n## ', text, re.DOTALL
        )
        assert guide_match is not None, "Orchestrator Decomposition Guide section missing"
        guide = guide_match.group(1)
        assert re.search(r'2c', guide), (
            "Orchestrator Decomposition Guide has no row mapping the new 2c directive"
        )


class TestStaysGeneric:
    """(b) Part-0: the new §2c directive names no protocol/contest/token proper nouns."""

    def test_no_banned_proper_nouns_in_2c_section(self):
        text = _read_skill_text()
        section = _extract_section_2c(text)
        section_lower = section.lower()
        hits = [name for name in BANNED_PROPER_NOUNS if name in section_lower]
        assert not hits, (
            f"§2c directive contains banned protocol/contest/token proper noun(s): {hits}. "
            "Methodology must encode HOW to analyze, never WHAT to find in a specific protocol."
        )

    def test_erc4626_as_standard_name_is_not_banned(self):
        # Sanity check on the banned-noun policy itself: ERC4626 (a standard,
        # not a specific protocol) is explicitly allowed and must NOT be in
        # the banned list.
        assert "erc4626" not in [n.lower() for n in BANNED_PROPER_NOUNS]


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
