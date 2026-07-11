"""Move (aptos/sui) PoC discovery — package-prefix generalization.

Root cause recap (see CLAUDE.md task): `spike_mechanical_poc._TEST_PATH_BY_LANG`
got the cargo (solana/soroban/l1_rust) crate-prefix generalization — an
optional repeated path-segment group prepended before the `tests?/` anchor so
a workspace-member-prefixed path keeps its full prefix — but the two Move keys
(aptos/sui) were left narrow: `((?:sources/)?tests?/[\\w.\\-/]+\\.move)`. A Move
package is its own `Move.toml` root with a sibling `sources/`+`tests/` pair; a
repo with multiple packages (Sui "local dependencies" / Aptos workspace
members) puts each package under its own directory, e.g.
`packages/foo/tests/bar.move`. The unanchored regex started matching AT
`tests/` and dropped the `packages/foo/` package-directory prefix — the same
truncation the cargo fix removed, only partially masked by the language-
agnostic bounded rglob fallback in `_resolve_test_path_for`.

This file covers, generically (no protocol names in assertions/logic):
  1. Multi-package Move path: package-directory prefix retained in full.
  2. Single-package Move path (bare `tests/...` and `sources/tests/...`):
     zero-repetition case still resolves exactly as before.
  3. EVM byte-identical (no cross-contamination from the Move-only change).

Run: pytest scripts/test_move_poc_discovery.py -q
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import spike_mechanical_poc as SP  # noqa: E402


def _verify_text(test_file_line: str) -> str:
    return (
        "# Verification: H-9\n"
        "- **Finding ID**: H-9\n"
        f"- **Test File**: {test_file_line}\n"
        "- **Verdict**: CONFIRMED\n"
        "- **Evidence Tag**: [POC-PASS]\n"
    )


def _write(tmp_path: Path, text: str, name: str = "verify_H-9.md") -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


class TestMovePackagePrefixCapture:
    def test_aptos_multipackage_prefix_retained(self, tmp_path):
        probe = SP.parse_verify_file(
            _write(tmp_path, _verify_text("packages/foo/tests/bar.move")),
            language="aptos",
        )
        assert probe.test_file_resolved == "packages/foo/tests/bar.move"

    def test_sui_multipackage_prefix_retained(self, tmp_path):
        probe = SP.parse_verify_file(
            _write(tmp_path, _verify_text("packages/foo/tests/bar.move")),
            language="sui",
        )
        assert probe.test_file_resolved == "packages/foo/tests/bar.move"

    def test_aptos_nested_package_dir_prefix_retained(self, tmp_path):
        """Multiple package-directory segments (not just one level)."""
        probe = SP.parse_verify_file(
            _write(tmp_path, _verify_text("contracts/vault-core/tests/poc_h09.move")),
            language="aptos",
        )
        assert probe.test_file_resolved == "contracts/vault-core/tests/poc_h09.move"

    def test_sui_bare_tests_unaffected(self, tmp_path):
        """Zero-repetition case: a bare tests/foo.move (no package dir) still
        resolves exactly as before the fix."""
        probe = SP.parse_verify_file(
            _write(tmp_path, _verify_text("tests/bar.move")), language="sui",
        )
        assert probe.test_file_resolved == "tests/bar.move"

    def test_aptos_bare_tests_unaffected(self, tmp_path):
        probe = SP.parse_verify_file(
            _write(tmp_path, _verify_text("tests/bar.move")), language="aptos",
        )
        assert probe.test_file_resolved == "tests/bar.move"

    def test_sui_sources_tests_single_package_unaffected(self, tmp_path):
        """The pre-existing `sources/tests/...` option (single package, no
        package-dir prefix) still resolves in full, unchanged."""
        probe = SP.parse_verify_file(
            _write(tmp_path, _verify_text("sources/tests/bar.move")),
            language="sui",
        )
        assert probe.test_file_resolved == "sources/tests/bar.move"

    def test_aptos_sources_tests_single_package_unaffected(self, tmp_path):
        probe = SP.parse_verify_file(
            _write(tmp_path, _verify_text("sources/tests/bar.move")),
            language="aptos",
        )
        assert probe.test_file_resolved == "sources/tests/bar.move"

    def test_aptos_package_dir_with_sources_tests_retained(self, tmp_path):
        """Multi-package PLUS the sources/tests/ option combined."""
        probe = SP.parse_verify_file(
            _write(tmp_path, _verify_text("packages/foo/sources/tests/bar.move")),
            language="aptos",
        )
        assert probe.test_file_resolved == "packages/foo/sources/tests/bar.move"

    def test_na_resolves_to_none(self, tmp_path):
        probe = SP.parse_verify_file(
            _write(tmp_path, _verify_text("N/A")), language="sui",
        )
        assert probe.test_file_resolved is None

    def test_evm_byte_identical_no_cross_contamination(self, tmp_path):
        """HARD INVARIANT: EVM extraction/regex is untouched by the Move-only
        package-prefix generalization."""
        probe = SP.parse_verify_file(
            _write(tmp_path, _verify_text("test/Foo.t.sol")), language="evm",
        )
        assert probe.test_file_resolved == "test/Foo.t.sol"
        assert SP._TEST_PATH_BY_LANG["evm"].pattern == r"((?:test|tests)/[\w.\-/]+\.t\.sol)"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
