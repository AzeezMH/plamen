"""Positive-harvest test for the broadened Soroban MULTI_STEP_OPS recon
trigger row (Plan: structured-toasting-parasol — trigger owner, layer 2).

The M2 identity axis (enumeration_gate.py, gate owner's lane) is
LANGUAGE-AGNOSTIC and lives entirely on agent-emitted tags/prose. The
per-language MULTI_STEP_OPS recon flag is the only place source-code
vocabulary legitimately lives (already per-ecosystem: separate EVM and
Soroban rows), and is a WEAK trigger only — it selects the
MULTI_STEP_OPERATION_SAFETY niche agent, it never gates the identity axis
itself.

This test proves the broadened Soroban row (behalf-of suffix shape family +
explicit on-behalf-of/for_owner/for_recipient names + Address-typed
operator/delegate params + SEP-41 delegated-action methods) still:
  1. fires on a generic behalf-of/SEP-41-shaped function that carries an
     Address-subject parameter distinct from the caller, and
  2. does NOT net-fire on a pure-internal helper with no Address-subject
     parameter, even when its name superficially matches the bare `_for_`
     suffix shape (the row's own applicability qualifier nets this out,
     mirroring how the LLM recon agent applies judgment on top of the raw
     grep hit).

Extracted directly from the shipped
`prompts/soroban/phase1-recon-prompt.md` row so this test breaks if the row
regresses, per the MEMORY.md "verify the running checkout" + "ID regex must
catalog all formats" rules — it does not maintain a parallel hardcoded copy.
"""

from __future__ import annotations

import re
from pathlib import Path

_RECON_PROMPT = (
    Path(__file__).resolve().parent.parent
    / "prompts"
    / "soroban"
    / "phase1-recon-prompt.md"
)


def _load_multi_step_ops_pattern() -> str:
    """Extract the MULTI_STEP_OPS grep pattern from the shipped recon prompt.

    The row is a markdown table cell: `<pattern>` (qualifier) | MULTI_STEP_OPS |
    Pipe characters inside the pattern are escaped as `\\|` purely for
    markdown table-cell safety (a bare `|` would break the table), not for
    regex-alternation escaping - real usage is plain `|` alternation, exactly
    like every other TASK 6 pattern row in this file (e.g. the BALANCE_DEPENDENT
    / SEMI_TRUSTED_ROLE rows above it).
    """
    text = _RECON_PROMPT.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("| MULTI_STEP_OPS |"):
            m = re.search(r"`([^`]+)`", stripped)
            assert m, f"MULTI_STEP_OPS row has no backtick-quoted pattern: {line!r}"
            raw = m.group(1)
            return raw.replace("\\|", "|")
    raise AssertionError(
        "MULTI_STEP_OPS row not found in prompts/soroban/phase1-recon-prompt.md "
        "(trigger regressed or row text changed)"
    )


_ADDRESS_PARAM_RE = re.compile(r":\s*Address\b")


def _sets_multi_step_ops(fn_signature: str, pattern: str) -> bool:
    """Model the recon agent's applied judgment for this row: a raw shape
    match on the extracted pattern AND an Address-subject parameter present
    (the row's own applicability qualifier: "excludes purely internal
    helpers with no Address-subject parameter"). A bare regex hit alone is
    not sufficient - this is a weak/coarse grep, the qualifier is what keeps
    it from over-firing on unrelated `_for_`-shaped internal helpers.
    """
    if not re.search(pattern, fn_signature):
        return False
    return bool(_ADDRESS_PARAM_RE.search(fn_signature))


# --- Fixtures: generic, freshly-authored, zero protocol-specific vocabulary -

_BEHALF_OF_SUFFIX_FAMILY = (
    "pub fn stake_for(env: Env, caller: Address, beneficiary: Address, amount: i128) {\n"
    "    caller.require_auth();\n"
    "}\n"
)

_BEHALF_OF_FOR_USER_SHAPE = (
    "pub fn claim_for_user(env: Env, caller: Address, user: Address) {\n"
    "    caller.require_auth();\n"
    "}\n"
)

_SEP41_DELEGATED_METHOD = (
    "pub fn transfer_from(env: Env, spender: Address, from: Address, to: Address, amount: i128) {\n"
    "    spender.require_auth();\n"
    "}\n"
)

_OPERATOR_ADDRESS_PARAM = (
    "pub fn set_operator(env: Env, owner: Address, operator: Address) {\n"
    "    owner.require_auth();\n"
    "}\n"
)

_ON_BEHALF_OF_NAME = (
    "pub fn withdraw_on_behalf_of(env: Env, caller: Address, owner: Address, amount: i128) {\n"
    "    caller.require_auth();\n"
    "}\n"
)

# Pure-internal helper: name superficially matches the bare `_for_` suffix
# shape (a raw grep would hit "wait_for_ledger(") but there is NO
# Address-subject parameter - the row's applicability qualifier must net
# this out to NOT SET, so this is the load-bearing negative control.
_PURE_INTERNAL_NO_ADDRESS_SUBJECT = (
    "fn wait_for_ledger(env: Env, target_sequence: u32) -> bool {\n"
    "    env.ledger().sequence() >= target_sequence\n"
    "}\n"
)

# Pure-internal helper with no name-shape match at all either (double-blocked
# negative control).
_PURE_INTERNAL_NO_SHAPE_MATCH = (
    "fn compute_scaling_factor(base: i128, exponent: u32) -> i128 {\n"
    "    base.pow(exponent)\n"
    "}\n"
)


def test_multi_step_ops_pattern_extracted_from_shipped_row():
    pattern = _load_multi_step_ops_pattern()
    assert pattern, "extracted MULTI_STEP_OPS pattern must be non-empty"
    re.compile(pattern)  # must compile as a real regex


def test_behalf_of_suffix_family_sets_flag():
    pattern = _load_multi_step_ops_pattern()
    assert _sets_multi_step_ops(_BEHALF_OF_SUFFIX_FAMILY, pattern)


def test_behalf_of_for_user_shape_sets_flag():
    pattern = _load_multi_step_ops_pattern()
    assert _sets_multi_step_ops(_BEHALF_OF_FOR_USER_SHAPE, pattern)


def test_sep41_delegated_method_sets_flag():
    pattern = _load_multi_step_ops_pattern()
    assert _sets_multi_step_ops(_SEP41_DELEGATED_METHOD, pattern)


def test_operator_address_param_sets_flag():
    pattern = _load_multi_step_ops_pattern()
    assert _sets_multi_step_ops(_OPERATOR_ADDRESS_PARAM, pattern)


def test_on_behalf_of_name_sets_flag():
    pattern = _load_multi_step_ops_pattern()
    assert _sets_multi_step_ops(_ON_BEHALF_OF_NAME, pattern)


def test_pure_internal_helper_with_no_address_subject_does_not_set_flag():
    pattern = _load_multi_step_ops_pattern()
    assert not _sets_multi_step_ops(_PURE_INTERNAL_NO_ADDRESS_SUBJECT, pattern)


def test_pure_internal_helper_with_no_shape_match_does_not_set_flag():
    pattern = _load_multi_step_ops_pattern()
    assert not _sets_multi_step_ops(_PURE_INTERNAL_NO_SHAPE_MATCH, pattern)


def test_row_still_states_address_subject_applicability_qualifier():
    text = _RECON_PROMPT.read_text(encoding="utf-8")
    assert (
        "excludes purely internal helpers with no Address-subject parameter"
        in text
    ), "the row's applicability qualifier regressed or was reworded"


def test_evm_row_ported_to_suffix_family():
    # The EVM MULTI_STEP_OPS row was intentionally generalized (this session)
    # from brittle enumerated literals (depositFor|stakeFor|...) to a suffix-
    # family shape, mirroring the Soroban port, so a differently-named on-behalf
    # function (e.g. executeFor) no longer evades the authz-subject trigger.
    evm_prompt = (
        Path(__file__).resolve().parent.parent
        / "prompts"
        / "evm"
        / "phase1-recon-prompt.md"
    )
    text = evm_prompt.read_text(encoding="utf-8")
    assert "MULTI_STEP_OPS" in text, "EVM MULTI_STEP_OPS row must still exist"
    # suffix-family generalization present (the whole point of the port):
    assert r"\w+For\(" in text, (
        "EVM MULTI_STEP_OPS row should carry the generic suffix-family shape "
        r"(\w+For\() after the port, not only brittle enumerated literals"
    )


def test_part0_no_overfit_vocabulary_in_soroban_recon_prompt():
    # Word/underscore-bounded checks only - avoids false alarms on innocuous
    # substrings (e.g. bare "pt"/"yt"/"ibt" inside unrelated words).
    text = _RECON_PROMPT.read_text(encoding="utf-8")
    lowered = text.lower()
    banned_literal = (
        "spectra",
        "fee_reduction",
        "before_yt_transfer",
        "convert_to_ibt",
        "assertminbalance",
        "deploy_pt",
        "transfer_admin_role",
    )
    for token in banned_literal:
        assert token not in lowered, (
            f"overfit vocabulary leaked into soroban recon prompt: {token!r}"
        )
    for token in ("pt", "yt", "ibt"):
        assert not re.search(rf"\b{token}\b", lowered), (
            f"overfit vocabulary (standalone token) leaked into soroban "
            f"recon prompt: {token!r}"
        )


if __name__ == "__main__":
    import sys

    failures = 0
    tests = [
        v
        for k, v in sorted(globals().items())
        if k.startswith("test_") and callable(v)
    ]
    for t in tests:
        try:
            t()
            print(f"PASS: {t.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL: {t.__name__}: {e}")
    sys.exit(1 if failures else 0)
