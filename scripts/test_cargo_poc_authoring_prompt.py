"""Fixtures for the cargo (soroban/solana/l1_rust) PoC-authoring mandate.

Approved fix, Part B+C — additive documentation changes only:

- prompts/soroban/phase5-verification-prompt.md and
  prompts/solana/phase5-verification-prompt.md MUST mandate authoring the
  PoC as a NEW in-crate `src/poc_<id>.rs` file wired via
  `#[cfg(test)] mod poc_<id>;` into the target workspace member's `lib.rs`,
  FORBID inline-in-`lib.rs` authoring and a bare top-level `tests/*.rs` as
  the PRIMARY shape, and record `Test File:` / `Command:` accordingly.
  Soroban's command includes `--features testutils`; Solana's explicitly
  does not (carve-out, documented inline).

- rules/phase5-poc-execution.md MUST carry a concise cargo-generic ledger
  line: for `unit`/`property` rows in cargo languages (soroban / solana /
  l1_rust) the PoC must be placed in-crate under the member's `src/`, and
  `STRUCTURAL_NO_EXECUTABLE_HARM_ASSERTION` remains DISALLOWED for those
  rows when a build harness exists.

Part-0 (no codebase overfitting): none of the three edited pipeline files
may contain contest/protocol proper nouns. A representative crate-name
string (e.g. "principal-token") is used ONLY inside this test file's own
fixture data to sanity-check path-shape assertions -- never asserted to
exist in, or written into, the actual prompt/rule files.

Run: cd scripts && python -m pytest test_cargo_poc_authoring_prompt.py -q
"""
from __future__ import annotations

from pathlib import Path

import pytest

PLAMEN_HOME = Path(__file__).resolve().parent.parent

SOROBAN_PROMPT = PLAMEN_HOME / "prompts" / "soroban" / "phase5-verification-prompt.md"
SOLANA_PROMPT = PLAMEN_HOME / "prompts" / "solana" / "phase5-verification-prompt.md"
POC_EXECUTION_RULES = PLAMEN_HOME / "rules" / "phase5-poc-execution.md"

# Edited pipeline files under Part-0 no-overfit scrutiny (proper-noun scan).
EDITED_PIPELINE_FILES = [SOROBAN_PROMPT, SOLANA_PROMPT, POC_EXECUTION_RULES]

# Generic no-overfit blacklist: contest/protocol proper nouns that must never
# appear in pipeline methodology files. This list itself names no answer to
# any audit question -- it exists only to keep pipeline prose generic.
FORBIDDEN_PROPER_NOUNS = [
    "Spectra",
    "principal-token",
    "principal token",
    "Pendle",
]


def _read(path: Path) -> str:
    assert path.exists(), f"missing file: {path}"
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Part B: prompts/soroban + prompts/solana phase5-verification-prompt.md
# ---------------------------------------------------------------------------


class TestSorobanCargoPocAuthoringMandate:
    def test_in_crate_src_poc_file_mandate_present(self):
        text = _read(SOROBAN_PROMPT)
        assert "src/poc_" in text
        assert "#[cfg(test)] mod poc_" in text

    def test_test_file_and_command_shape_recorded(self):
        text = _read(SOROBAN_PROMPT)
        assert "Test File" in text
        assert "<crate>/src/poc_" in text
        assert "cargo test -p <crate>" in text

    def test_features_testutils_required_for_soroban(self):
        text = _read(SOROBAN_PROMPT)
        # The mandated command must include the testutils feature flag.
        assert "cargo test -p <crate> --features testutils" in text

    def test_inline_lib_rs_authoring_forbidden(self):
        text = _read(SOROBAN_PROMPT)
        assert "lib.rs" in text
        assert "excluded basename" in text
        assert "FORBIDDEN" in text

    def test_bare_top_level_tests_dir_forbidden_as_primary(self):
        text = _read(SOROBAN_PROMPT)
        assert "tests/*.rs" in text
        assert "PRIMARY" in text

    def test_generic_cdylib_rlib_reason_present_no_names(self):
        text = _read(SOROBAN_PROMPT)
        assert "cdylib" in text
        assert "rlib" in text
        # Reason must be generic (crate-type mechanics), not protocol-named.
        assert "E0463" in text


class TestSolanaCargoPocAuthoringMandate:
    def test_in_crate_src_poc_file_mandate_present(self):
        text = _read(SOLANA_PROMPT)
        assert "src/poc_" in text
        assert "#[cfg(test)] mod poc_" in text

    def test_test_file_and_command_shape_recorded(self):
        text = _read(SOLANA_PROMPT)
        assert "Test File" in text
        assert "<crate>/src/poc_" in text
        assert "cargo test -p <crate>" in text

    def test_inline_lib_rs_authoring_forbidden(self):
        text = _read(SOLANA_PROMPT)
        assert "lib.rs" in text
        assert "excluded basename" in text
        assert "FORBIDDEN" in text

    def test_bare_top_level_tests_dir_forbidden_as_primary(self):
        text = _read(SOLANA_PROMPT)
        assert "tests/*.rs" in text
        assert "PRIMARY" in text

    def test_testutils_carve_out_documented(self):
        text = _read(SOLANA_PROMPT)
        # The carve-out reasoning must be documented explicitly, and must
        # explicitly say the flag is not required/does not exist on Solana.
        assert "carve-out" in text.lower()
        assert "MUST NOT include `--features testutils`" in text
        assert "does not exist on Solana" in text

    def test_solana_mandated_command_line_omits_testutils_flag(self):
        text = _read(SOLANA_PROMPT)
        mandate_section = text.split("### PoC File Placement")[1].split(
            "### PoC Attempt Ledger"
        )[0]
        command_line = next(
            line for line in mandate_section.splitlines() if line.strip().startswith("- **Command**:")
        )
        assert "testutils" not in command_line


# ---------------------------------------------------------------------------
# Part C: rules/phase5-poc-execution.md
# ---------------------------------------------------------------------------


class TestPocExecutionRulesCargoLine:
    def test_cargo_languages_named_generically(self):
        text = _read(POC_EXECUTION_RULES)
        assert "soroban / solana / l1_rust" in text or "soroban/solana/l1_rust" in text

    def test_in_crate_src_placement_mandated(self):
        text = _read(POC_EXECUTION_RULES)
        assert "in-crate" in text
        assert "src/" in text

    def test_structural_skip_disallowed_for_unit_property(self):
        text = _read(POC_EXECUTION_RULES)
        assert "STRUCTURAL_NO_EXECUTABLE_HARM_ASSERTION" in text
        assert "DISALLOWED" in text

    def test_existing_structural_carve_out_for_non_unit_property_untouched(self):
        # The pre-existing single allowed-reasons list entry (structural/
        # integration only) must remain unchanged by this additive edit.
        text = _read(POC_EXECUTION_RULES)
        assert (
            "`STRUCTURAL_NO_EXECUTABLE_HARM_ASSERTION` (structural/integration only)"
            in text
        )


# ---------------------------------------------------------------------------
# Part-0: no codebase overfitting -- proper-noun scan of edited pipeline files
# ---------------------------------------------------------------------------


class TestNoOverfitProperNounScan:
    @pytest.mark.parametrize("path", EDITED_PIPELINE_FILES, ids=lambda p: p.name)
    def test_no_forbidden_proper_nouns_in_pipeline_file(self, path: Path):
        text = _read(path)
        lowered = text.lower()
        for noun in FORBIDDEN_PROPER_NOUNS:
            assert noun.lower() not in lowered, (
                f"forbidden proper noun {noun!r} found in pipeline file {path} -- "
                "methodology must stay generic (no protocol/contest names)"
            )

    def test_representative_crate_name_is_local_fixture_only(self):
        # Sanity check that this test module's own fixture usage of a
        # representative crate-name string never touches the real pipeline
        # files -- it is purely a local path-shape example.
        representative = "principal-token"
        example_path = f"{representative}/src/poc_H-12.rs"
        assert example_path.startswith(representative)
        for path in EDITED_PIPELINE_FILES:
            assert representative not in _read(path)
