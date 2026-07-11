"""Unit tests for the force-by-default PoC gate prompt/rules edits (Part B).

Verifies that the closed-taxonomy skip-justification directive was added to:
  - rules/phase5-poc-execution.md (source of truth, + TTL-testable-via-Ledger note)
  - prompts/soroban/phase5-verification-prompt.md
  - prompts/evm/phase5-verification-prompt.md
  - prompts/daml/phase5-verification-prompt.md (+ passTime/allocateParty
    in-memory-ledger-is-not-an-excuse reinforcement note)

And that no protocol/contest proper nouns were introduced by the edits.

Run: `cd scripts && python -m pytest test_poc_force_gate_prompt.py -q`
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

RULES_FILE = REPO_ROOT / "rules" / "phase5-poc-execution.md"

PROMPT_FILES = {
    "soroban": REPO_ROOT / "prompts" / "soroban" / "phase5-verification-prompt.md",
    "evm": REPO_ROOT / "prompts" / "evm" / "phase5-verification-prompt.md",
    "solana": REPO_ROOT / "prompts" / "solana" / "phase5-verification-prompt.md",
    "aptos": REPO_ROOT / "prompts" / "aptos" / "phase5-verification-prompt.md",
    "sui": REPO_ROOT / "prompts" / "sui" / "phase5-verification-prompt.md",
    "daml": REPO_ROOT / "prompts" / "daml" / "phase5-verification-prompt.md",
}

# The closed taxonomy of code-grounded skip blockers introduced by this change.
CLOSED_TAXONOMY_TOKENS = (
    "FULLY_TRUSTED_DESIGN",
    "DEPLOY_OR_TX_ORDERING",
    "EXTERNAL_DEP_NO_FORK",
    "LIVE_ARTIFACT_REQUIRED",
    "SPEC_DOCS_NO_STATE_DELTA",
)

# Generic representative content only (Part-0 compliance) -- used to prove
# the test fixtures / assertions below don't smuggle in protocol/contest
# proper nouns of their own.
GENERIC_MARKERS = (
    "HARVESTER",
    "TTL",
    "UPGRADE authority",
    "initialize race",
)

# A conservative denylist of proper nouns that must never appear inside the
# specific blocks this change added. This is not a general Part-0 scanner --
# just a guard against regressions in the newly-authored prose.
FORBIDDEN_PROPER_NOUNS = (
    "Uniswap",
    "Compound",
    "Aave",
    "MakerDAO",
    "Curve",
    "Balancer",
    "Sushiswap",
    "Chainlink",
    "OpenZeppelin",
)


def _read(path: Path) -> str:
    assert path.exists(), f"missing file: {path}"
    return path.read_text(encoding="utf-8")


def _extract_force_gate_block(text: str) -> str:
    """Return the 'Force-by-Default Skip Justification' section only."""
    marker = "Force-by-Default Skip Justification"
    idx = text.find(marker)
    assert idx != -1, "Force-by-Default Skip Justification section not found"
    # Grab up to the next top-level (## ) or sub-level (### ) heading after
    # the marker's own heading line, or end of file.
    after_heading = text[idx:]
    lines = after_heading.splitlines()
    block_lines = [lines[0]]
    for line in lines[1:]:
        if line.startswith("## ") or line.startswith("### "):
            break
        block_lines.append(line)
    return "\n".join(block_lines)


# ---------------------------------------------------------------------------
# rules/phase5-poc-execution.md
# ---------------------------------------------------------------------------

def test_rules_file_exists():
    assert RULES_FILE.exists()


def test_rules_file_has_closed_taxonomy_skip_requirement():
    text = _read(RULES_FILE)
    block = _extract_force_gate_block(text)
    for token in CLOSED_TAXONOMY_TOKENS:
        assert token in block, f"missing closed-taxonomy token: {token}"
    # REFUTED verdict escape hatch must be present too.
    assert "REFUTED" in block


def test_rules_file_has_structural_not_valid_for_concrete_harm_line():
    text = _read(RULES_FILE)
    block = _extract_force_gate_block(text)
    assert "STRUCTURAL_NO_EXECUTABLE_HARM_ASSERTION" in block
    assert "NOT a valid skip" in block or "not a valid skip" in block.lower()
    assert "Material Harm" in block or "material harm" in block.lower()


def test_rules_file_has_code_trace_not_poc_fail_line():
    text = _read(RULES_FILE)
    block = _extract_force_gate_block(text)
    assert "[CODE-TRACE]" in block
    assert "[POC-FAIL]" in block
    # Must explicitly say a cannot-assert-harm outcome is CODE-TRACE, not POC-FAIL.
    assert re.search(r"records\s*`?\[CODE-TRACE\]`?[^.]*NOT\s*`?\[POC-FAIL\]`?", block), (
        "expected an explicit '...records [CODE-TRACE] ... NOT [POC-FAIL]' statement"
    )


def test_rules_file_has_ttl_testable_via_ledger_line():
    text = _read(RULES_FILE)
    assert "get_ttl()" in text
    assert "with_mut" in text
    assert "sequence_number" in text
    # The "Env::default cannot model eviction" excuse must be explicitly
    # invalidated somewhere near the TTL guidance.
    idx = text.find("get_ttl()")
    window = text[max(0, idx - 800): idx + 800]
    assert "Env::default" in window
    assert "NOT a valid" in window or "not a valid" in window.lower()


# ---------------------------------------------------------------------------
# Language prompt files carry the same skip-taxonomy directive
# (mandated for soroban + evm; also applied to solana/aptos/sui for parity)
# ---------------------------------------------------------------------------

def test_soroban_and_evm_prompts_carry_skip_taxonomy_directive():
    for lang in ("soroban", "evm"):
        text = _read(PROMPT_FILES[lang])
        block = _extract_force_gate_block(text)
        for token in CLOSED_TAXONOMY_TOKENS:
            assert token in block, f"{lang}: missing closed-taxonomy token {token}"
        assert "[CODE-TRACE]" in block
        assert "[POC-FAIL]" in block
        assert "STRUCTURAL_NO_EXECUTABLE_HARM_ASSERTION" in block


def test_daml_prompt_carries_skip_taxonomy_directive():
    text = _read(PROMPT_FILES["daml"])
    block = _extract_force_gate_block(text)
    for token in CLOSED_TAXONOMY_TOKENS:
        assert token in block, f"daml: missing closed-taxonomy token {token}"
    assert "[CODE-TRACE]" in block
    assert "[POC-FAIL]" in block
    assert "STRUCTURAL_NO_EXECUTABLE_HARM_ASSERTION" in block
    # DAML-correct vocabulary, not Solidity/cargo terms.
    assert "daml test" in block
    assert "Script" in block
    for forbidden_term in ("forge", "cargo", "hardhat", "anchor", "solc"):
        assert forbidden_term not in block.lower(), (
            f"daml force-gate block leaked non-DAML toolchain term: {forbidden_term!r}"
        )


def test_all_six_language_prompts_carry_directive():
    for lang, path in PROMPT_FILES.items():
        text = _read(path)
        block = _extract_force_gate_block(text)
        for token in CLOSED_TAXONOMY_TOKENS:
            assert token in block, f"{lang}: missing closed-taxonomy token {token}"


def test_soroban_prompt_carries_ttl_reinforcement():
    text = _read(PROMPT_FILES["soroban"])
    assert "get_ttl()" in text
    assert "with_mut" in text
    assert "sequence_number" in text


def test_daml_prompt_carries_in_memory_ledger_reinforcement():
    text = _read(PROMPT_FILES["daml"])
    assert "passTime" in text
    assert "allocateParty" in text
    idx = text.find("passTime")
    window = text[max(0, idx - 800): idx + 800]
    assert "EXTERNAL_DEP_NO_FORK" in window
    assert "LIVE_ARTIFACT_REQUIRED" in window
    assert "not, by itself, a valid" in window or "NOT a valid" in window


# ---------------------------------------------------------------------------
# Part 0 — no protocol/contest proper nouns introduced in the edited blocks
# ---------------------------------------------------------------------------

def test_no_forbidden_proper_nouns_in_force_gate_blocks():
    all_files = [RULES_FILE] + list(PROMPT_FILES.values())
    for path in all_files:
        text = _read(path)
        block = _extract_force_gate_block(text)
        for noun in FORBIDDEN_PROPER_NOUNS:
            assert noun not in block, f"{path.name}: forbidden proper noun {noun!r} found in force-gate block"


def test_no_forbidden_proper_nouns_in_ttl_reinforcement():
    for path in (RULES_FILE, PROMPT_FILES["soroban"]):
        text = _read(path)
        idx = text.find("get_ttl()")
        assert idx != -1
        window = text[max(0, idx - 800): idx + 800]
        for noun in FORBIDDEN_PROPER_NOUNS:
            assert noun not in window, f"{path.name}: forbidden proper noun {noun!r} found near TTL reinforcement"


def test_no_forbidden_proper_nouns_in_daml_reinforcement():
    text = _read(PROMPT_FILES["daml"])
    idx = text.find("passTime")
    assert idx != -1
    window = text[max(0, idx - 800): idx + 800]
    for noun in FORBIDDEN_PROPER_NOUNS:
        assert noun not in window, f"daml prompt: forbidden proper noun {noun!r} found near passTime reinforcement"


if __name__ == "__main__":
    import sys

    failures = 0
    tests = [
        test_rules_file_exists,
        test_rules_file_has_closed_taxonomy_skip_requirement,
        test_rules_file_has_structural_not_valid_for_concrete_harm_line,
        test_rules_file_has_code_trace_not_poc_fail_line,
        test_rules_file_has_ttl_testable_via_ledger_line,
        test_soroban_and_evm_prompts_carry_skip_taxonomy_directive,
        test_daml_prompt_carries_skip_taxonomy_directive,
        test_all_six_language_prompts_carry_directive,
        test_soroban_prompt_carries_ttl_reinforcement,
        test_daml_prompt_carries_in_memory_ledger_reinforcement,
        test_no_forbidden_proper_nouns_in_force_gate_blocks,
        test_no_forbidden_proper_nouns_in_ttl_reinforcement,
        test_no_forbidden_proper_nouns_in_daml_reinforcement,
    ]
    for t in tests:
        try:
            t()
            print(f"  PASS  {t.__name__}")
        except AssertionError as exc:
            failures += 1
            print(f"  FAIL  {t.__name__} :: {exc}")
    print(f"\n{'RESULTS'}: {len(tests) - failures} passed, {failures} failed")
    sys.exit(1 if failures else 0)
