"""
Tests for ITEM B2 -- "Interned/Compacted Identity Coherence" directive.

Verifies agents/skills/injectable/l1/execution-client-hardening/SKILL.md
contains a new generic section 5b covering coupled-cache coherence /
index-recycling bugs in VM/execution clients: a compact numeric index/handle
assigned to a named entity, with OTHER structures caching data keyed by that
same index space, where a partial reset/compact/GC on one structure but not
its siblings lets a recycled index resolve to the wrong entity's data.

Also verifies agents/depth-state-trace.md section 8 (the single-cache
lifecycle set-cover "near miss") carries a one-line cross-link to the new
section 5b, and that both the new section and the cross-link stay
protocol-agnostic (Part 0: no VM/protocol/contest proper nouns -- "Move VM"
as a category name is explicitly allowed), matching the no-overfit rule in
~/.plamen/rules/post-audit-improvement-protocol.md and feedback_no_overfit.md.
"""
import re
from pathlib import Path

import pytest

SKILL_PATH = (
    Path(__file__).resolve().parent.parent
    / "agents"
    / "skills"
    / "injectable"
    / "l1"
    / "execution-client-hardening"
    / "SKILL.md"
)

DEPTH_STATE_TRACE_PATH = (
    Path(__file__).resolve().parent.parent / "agents" / "depth-state-trace.md"
)

# Proper nouns that would constitute Part-0 overfitting if they appeared in
# the new section text (specific VMs / protocols / audit contests / past
# finding sources). "move vm" is explicitly NOT banned -- it is a generic VM
# category name, not a specific protocol, and the item spec allows it.
BANNED_PROPER_NOUNS = [
    "aptos",
    "hexens",
    "aip-107",
    "sui",
    "solana",
    "sherlock",
    "code4rena",
    "immunefi",
    "cantina",
    "zetachain",
    "irys",
    "awesomex",
    "umia",
    "pareto",
    "diem",
    "libra",
    "starcoin",
]


def _read_text(path: Path) -> str:
    assert path.exists(), f"File not found at {path}"
    return path.read_text(encoding="utf-8")


def _extract_section_5b(text: str) -> str:
    """
    Extract the section 5b body: from the '5b' heading (## 5b. / ### 5b)
    up to (but not including) the next heading of level <= the 5b heading's
    level, or end of file. Raises AssertionError if no 5b heading is found
    (intentional -- extraction fails on the unmodified file so tests fail
    before the directive is added).
    """
    heading_re = re.compile(r'^(#{2,4})\s*5b[.\s]', re.MULTILINE)
    match = heading_re.search(text)
    assert match is not None, (
        "No '5b' heading (## 5b. / ### 5b) found in execution-client-hardening "
        "SKILL.md -- the section 5b directive has not been added yet."
    )
    level = len(match.group(1))
    start = match.start()

    next_heading_re = re.compile(r'^(#{2,' + str(level) + r'})\s+\S', re.MULTILINE)
    tail_search = next_heading_re.search(text, match.end())
    end = tail_search.start() if tail_search else len(text)

    return text[start:end]


def _extract_section_8(text: str) -> str:
    """Extract depth-state-trace.md's '### 8.' section body."""
    heading_re = re.compile(r'^(#{2,4})\s*8[.\s]', re.MULTILINE)
    match = heading_re.search(text)
    assert match is not None, (
        "No '8' heading (### 8. Cache Lifecycle Set-Cover) found in "
        "depth-state-trace.md -- expected pre-existing section is missing."
    )
    level = len(match.group(1))
    start = match.start()

    next_heading_re = re.compile(r'^(#{2,' + str(level) + r'})\s+\S', re.MULTILINE)
    tail_search = next_heading_re.search(text, match.end())
    end = tail_search.start() if tail_search else len(text)

    return text[start:end]


class TestDirectivePresent:
    """(a) section 5b exists in the skill, and section 8 cross-links to it."""

    def test_5b_heading_present(self):
        text = _read_text(SKILL_PATH)
        section = _extract_section_5b(text)
        assert "Interned" in section or "Compacted" in section
        assert re.search(r'identity coherence', section, re.IGNORECASE)

    def test_5b_placed_after_section_5_before_section_6(self):
        text = _read_text(SKILL_PATH)
        sec5_match = re.search(r'^##\s*5\.\s', text, re.MULTILINE)
        sec5b_match = re.search(r'^##\s*5b[.\s]', text, re.MULTILINE)
        sec6_match = re.search(r'^##\s*6\.\s', text, re.MULTILINE)
        assert sec5_match and sec5b_match and sec6_match, (
            "Expected sections 5, 5b, and 6 headings all present"
        )
        assert sec5_match.start() < sec5b_match.start() < sec6_match.start(), (
            "Section 5b must be positioned after section 5 (Memory Safety) and "
            "before section 6 (Cross-Client Consistency)"
        )

    def test_5b_covers_index_handle_assignment(self):
        text = _read_text(SKILL_PATH)
        section = _extract_section_5b(text)
        assert re.search(r'index|handle', section, re.IGNORECASE)
        assert re.search(r'enumerate every structure', section, re.IGNORECASE)

    def test_5b_covers_atomic_multi_structure_invalidation(self):
        text = _read_text(SKILL_PATH)
        section = _extract_section_5b(text)
        assert re.search(r'reset|flush|compact|GC', section)
        assert re.search(r'same atomic step|atomically|SAME\s', section)

    def test_5b_covers_index_recycling_after_partial_reset(self):
        text = _read_text(SKILL_PATH)
        section = _extract_section_5b(text)
        assert re.search(r'restart|reused|recycl', section, re.IGNORECASE)
        assert re.search(r'partial reset', section, re.IGNORECASE)

    def test_5b_covers_derived_identity_via_recycled_index(self):
        text = _read_text(SKILL_PATH)
        section = _extract_section_5b(text)
        assert re.search(r'derived identity', section, re.IGNORECASE)
        assert re.search(
            r'storage|lookup key|resource type|permission|capability|scope',
            section,
            re.IGNORECASE,
        )

    def test_5b_distinguishes_from_single_cache_eviction(self):
        text = _read_text(SKILL_PATH)
        section = _extract_section_5b(text)
        # Must explicitly frame this as structurally distinct from ordinary
        # single-cache eviction (the near-miss in depth-state-trace.md sec 8).
        assert re.search(r'single\b.{0,20}\bcache', section, re.IGNORECASE | re.DOTALL)
        assert re.search(r'coupled', section, re.IGNORECASE)

    def test_5b_has_finding_tag(self):
        text = _read_text(SKILL_PATH)
        section = _extract_section_5b(text)
        assert "[IDENTITY-COHERENCE:" in section

    def test_section_8_crosslinks_to_5b(self):
        text = _read_text(DEPTH_STATE_TRACE_PATH)
        section = _extract_section_8(text)
        assert re.search(r'5b', section), (
            "depth-state-trace.md section 8 has no cross-link reference to "
            "the new execution-client-hardening section 5b"
        )
        assert re.search(
            r'execution-client-hardening[/\\]SKILL\.md', section
        ), (
            "depth-state-trace.md section 8 cross-link does not point at "
            "execution-client-hardening/SKILL.md"
        )


class TestStaysGeneric:
    """(b) Part-0: new content names no VM/protocol/contest proper nouns."""

    def test_no_banned_proper_nouns_in_5b_section(self):
        text = _read_text(SKILL_PATH)
        section = _extract_section_5b(text)
        section_lower = section.lower()
        hits = [name for name in BANNED_PROPER_NOUNS if name in section_lower]
        assert not hits, (
            f"Section 5b directive contains banned protocol/contest/token "
            f"proper noun(s): {hits}. Methodology must encode HOW to "
            "analyze, never WHAT to find in a specific protocol."
        )

    def test_move_vm_category_name_allowed_not_banned(self):
        # Sanity check on the banned-noun policy: "Move VM" is a generic VM
        # *category* name (explicitly allowed by the item spec), not a
        # specific protocol, and must not appear in the banned list.
        assert "move vm" not in [n.lower() for n in BANNED_PROPER_NOUNS]

    def test_no_banned_proper_nouns_in_crosslink(self):
        text = _read_text(DEPTH_STATE_TRACE_PATH)
        section = _extract_section_8(text)
        section_lower = section.lower()
        hits = [name for name in BANNED_PROPER_NOUNS if name in section_lower]
        assert not hits, (
            f"depth-state-trace.md section 8 cross-link contains banned "
            f"proper noun(s): {hits}."
        )


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
