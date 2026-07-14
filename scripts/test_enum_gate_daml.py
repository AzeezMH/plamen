"""DAML `_LANG` entry (M2 hot-set / axis-coverage matrix ONLY).

Scope of this port, per the applicability research: `_bake_daml_graph` /
`_finalize_source_graph` (recon_prepass.py) already emit the unified
`functions`/`var_refs` schema every M2 consumer (`compute_hot_function_set`,
`compute_axis_coverage_gaps`) reads, keyed by DAML choice name. Those
consumers, and their 6 axis detectors, are already language-agnostic (closed
depth-evidence tag vocabulary + generic English prose cues — no
`msg.sender`/`require_auth`/`&signer` tokens). The ONE genuine gap was that
`_LANG` had no `daml` entry at all, so `_value_effect_res("daml")` always
returned `[]` -> every DAML choice was permanently `value_effect=False`,
forcing the theft/identity axes to a provable N/A even for a value-moving
choice (create/archive/exercise) whose only state reference is a
uniquely-referenced field the recon-prepass var_refs filter (`1 < len(fns) <=
25`) drops.

This test file exercises the PARTIAL `daml` entry added to close that gap:
`fn_re` (choice-name join with the baked graph) + `effect` (value/authority
movement) ONLY. It deliberately has NO `array_param`/`str_param`/`mover`/
`id_param`/`asset_handle` -- the L-04/L-08/L-10 obligation-derivers stay a
no-op for DAML (need a `with`-block field-type grammar not parsed here; see
test_enum_gate_multilang.py::test_lang_applicability_matrix) and that no-op
must not throw and silently wipe out OTHER languages' already-collected
candidates in a mixed-ecosystem tree (regression-guards Part A below).

Vocabulary used throughout is DAML-generic only (template/choice/signatory/
controller/ensure/Party/ContractId) -- no protocol/template names, per the
no-overfit rule. All choice-grammar fixtures (new-style `with`/`controller`,
`nonconsuming`, `createAndExercise`) are hand-built; no real DAML repo exists
on this machine to validate against (see CLAUDE.md notes on this port).
"""
from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))


def _eg():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    return importlib.import_module("enumeration_gate")


def _proj(tmp_path: Path):
    root = tmp_path / "proj"
    sp = root / ".scratchpad"
    sp.mkdir(parents=True)
    (sp / "findings_inventory.md").write_text("# Inv\n", encoding="utf-8")
    return root, sp


def _daml(root: Path, rel: str, body: str):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


_TEMPLATE_BODY = """
template Asset
  with
    owner: Party
    newOwner: Party
    amount: Int
  where
    signatory owner
    ensure amount > 0

    choice Transfer : ContractId Asset
      with
        newOwner: Party
      controller owner
      do
        create this with owner = newOwner

    nonconsuming choice GetBalance : Int
      controller owner
      do
        pure amount

    choice Burn : ()
      controller owner
      do
        archive self
"""


# ── _LANG["daml"] structural shape ───────────────────────────────────────────

def test_lang_daml_entry_is_partial_by_design():
    eg = _eg()
    spec = eg._LANG["daml"]
    assert spec["suffix"] == (".daml",)
    assert "fn_re" in spec and "effect" in spec
    # Deliberately absent: the 3 obligation-derivers' with-block grammar keys.
    for k in ("array_param", "str_param", "mover", "id_param", "asset_handle",
              "loop", "uniq_guard", "stored_tpl", "lenguard_tpl"):
        assert k not in spec, k


def test_daml_suffix_is_supported_and_root_is_located(tmp_path: Path):
    eg = _eg()
    root, sp = _proj(tmp_path)
    assert ".daml" in eg._SUPPORTED_SUFFIXES
    _daml(root, "Asset.daml", _TEMPLATE_BODY)
    assert eg._locate_project_root(sp) == root


# ── _iter_functions: choice-name join with the baked graph ──────────────────

def test_iter_functions_yields_choice_names_multiple_grammars(tmp_path: Path):
    eg = _eg()
    root, sp = _proj(tmp_path)
    _daml(root, "Asset.daml", _TEMPLATE_BODY)
    fns = {name: (lang, body) for lang, _rel, name, _params, body, _line
           in eg._iter_functions(root)}
    # All 3 choice-grammar shapes parsed: consuming with `with`-block,
    # `nonconsuming`, and a bodiless-`with` choice.
    assert set(fns) == {"Transfer", "GetBalance", "Burn"}
    assert fns["Transfer"][0] == "daml"
    assert "create this with owner = newOwner" in fns["Transfer"][1]
    assert "archive self" in fns["Burn"][1]
    assert "pure amount" in fns["GetBalance"][1]


# ── compute_hot_function_set: value_effect detection ─────────────────────────

def test_hot_set_fallback_marks_value_moving_choices_only(tmp_path: Path):
    # No graph -> fallback to 'all external state-mutating functions' (source
    # value-effect parse). Transfer/Burn move value (create/archive); a pure
    # view-shaped choice with no create/archive/exercise must NOT appear.
    eg = _eg()
    root, sp = _proj(tmp_path)
    _daml(root, "Asset.daml", _TEMPLATE_BODY)
    hot = eg.compute_hot_function_set(sp)
    names = [h["function"] for h in hot]
    assert "Transfer" in names
    assert "Burn" in names
    assert "GetBalance" not in names   # `pure amount` has no value effect
    by = {h["function"]: h for h in hot}
    assert by["Transfer"]["value_effect"] is True
    assert by["Burn"]["value_effect"] is True
    assert all(h["lang"] == "daml" for h in hot)


def test_hot_set_primary_graph_path_ranks_daml_choice(tmp_path: Path):
    # PRIMARY path: a `_mechanical_graph.json` in the choice-keyed schema
    # `_bake_daml_graph` emits (functions/var_refs keyed by bare choice name).
    eg = _eg()
    root, sp = _proj(tmp_path)
    _daml(root, "Asset.daml", _TEMPLATE_BODY)
    graph = {
        "source": "daml",
        "var_refs": {"amount": {"bare": "amount", "refs": [
            "Transfer (Asset.daml:L10)", "GetBalance (Asset.daml:L18)"]}},
        "functions": {
            "Transfer": {"bare": "Transfer", "loc": "Asset.daml:L10", "callers": []},
            "Burn": {"bare": "Burn", "loc": "Asset.daml:L24", "callers": []},
        },
    }
    (sp / "_mechanical_graph.json").write_text(json.dumps(graph), encoding="utf-8")
    hot = eg.compute_hot_function_set(sp)
    names = [h["function"] for h in hot]
    assert "Transfer" in names   # writes (var_refs) + value_effect
    assert "Burn" in names       # value_effect (archive) makes it hot even w/ 0 callers
    by = {h["function"]: h for h in hot}
    assert by["Transfer"]["writes"] is True
    assert by["Burn"]["value_effect"] is True


# ── theft/identity axis N/A gate: the corner recall hole this closes ────────

def test_theft_axis_not_forced_na_for_value_moving_choice_with_unique_var_ref(tmp_path: Path):
    """The corner case from the applicability research: a choice whose ONLY
    state reference is a UNIQUELY-referenced field (referenced by exactly 1
    function) is dropped from `var_refs` by `_finalize_source_graph`'s
    `1 < len(fns) <= 25` filter, so `writes=False`. Before the `effect` fix,
    `value_effect` was ALSO always False for DAML -> theft/identity were
    incorrectly forced N/A even though the choice archives (moves/destroys)
    the contract's value. After the fix, `value_effect=True` closes this."""
    eg = _eg()
    root, sp = _proj(tmp_path)
    _daml(root, "Asset.daml",
          "template Asset\n"
          "  with\n"
          "    owner: Party\n"
          "  where\n"
          "    signatory owner\n"
          "    choice Redeem : ()\n"
          "      controller owner\n"
          "      do\n"
          "        archive self\n")
    # Graph has NO var_refs entry for Redeem at all (uniquely-referenced field
    # dropped by the recon-prepass filter) -- only the function entry, so
    # `writes` resolves False purely from the (empty) var_refs map.
    graph = {
        "source": "daml",
        "var_refs": {},
        "functions": {"Redeem": {"bare": "Redeem", "loc": "Asset.daml:L6",
                                  "callers": ["a", "b"]}},
    }
    (sp / "_mechanical_graph.json").write_text(json.dumps(graph), encoding="utf-8")
    eg.compute_axis_coverage_gaps(sp)
    matrix = json.loads((sp / "_hot_function_axes.json").read_text(encoding="utf-8"))
    row = next(r for r in matrix["matrix"] if r["function"] == "Redeem")
    assert row["cells"]["theft"] != "N/A"
    assert row["cells"]["identity"] != "N/A"


def test_theft_axis_is_na_for_non_value_moving_choice(tmp_path: Path):
    # Contrast case: a choice that neither writes state nor moves value
    # (pure ensure-style getter) IS a provable theft N/A.
    eg = _eg()
    root, sp = _proj(tmp_path)
    _daml(root, "Asset.daml",
          "template Asset\n"
          "  with\n"
          "    owner: Party\n"
          "    amount: Int\n"
          "  where\n"
          "    signatory owner\n"
          "    nonconsuming choice GetBalance : Int\n"
          "      controller owner\n"
          "      do\n"
          "        pure amount\n")
    graph = {
        "source": "daml",
        "var_refs": {},
        "functions": {"GetBalance": {"bare": "GetBalance", "loc": "Asset.daml:L7",
                                      "callers": ["a", "b"]}},
    }
    (sp / "_mechanical_graph.json").write_text(json.dumps(graph), encoding="utf-8")
    eg.compute_axis_coverage_gaps(sp)
    matrix = json.loads((sp / "_hot_function_axes.json").read_text(encoding="utf-8"))
    row = next(r for r in matrix["matrix"] if r["function"] == "GetBalance")
    assert row["cells"]["theft"] == "N/A"


# ── Part A regression guard: L-08/L-10 must not crash + wipe other langs ────

def test_array_uniqueness_survives_mixed_daml_tree(tmp_path: Path):
    """Before the `.get()` guard, a DAML function reaching
    `spec["array_param"]` (a key DAML's entry lacks) raised KeyError inside
    the per-language loop, caught by the deriver's OUTER try/except, wiping
    out every candidate already collected for OTHER languages in the same
    tree (dict iteration order runs sol/rust/move/go BEFORE daml). This test
    fails without the Part-A `.get()` guard and passes with it."""
    eg = _eg()
    root, sp = _proj(tmp_path)
    _daml(root, "Asset.daml", _TEMPLATE_BODY)
    (root / "lib.rs").write_text(
        "pub fn start_liquidation(assets: Vec<Address>) {\n"
        "    for a in assets.iter() {\n"
        "        token.transfer(&a, share);\n"
        "    }\n}\n", encoding="utf-8")
    out = eg.compute_array_uniqueness_candidates(sp)
    assert any("start_liquidation" in c["title"] and "assets" in c["title"]
               for c in out), out


def test_unbounded_input_survives_mixed_daml_tree(tmp_path: Path):
    eg = _eg()
    root, sp = _proj(tmp_path)
    _daml(root, "Asset.daml", _TEMPLATE_BODY)
    (root / "lib.rs").write_text(
        "pub fn upload(env: Env, name: String) {\n"
        "    env.storage().instance().set(&KEY, &name);\n}\n", encoding="utf-8")
    out = eg.compute_unbounded_input_candidates(sp)
    assert any("upload" in c["title"] and "name" in c["title"] for c in out), out


def test_critical_asset_mover_daml_skipped_no_crash(tmp_path: Path):
    # L-04 has no mover/id_param for DAML (already `.get()`-guarded prior to
    # this change) -- confirm it stays a clean no-op alongside a DAML file
    # without raising, and doesn't spuriously fire.
    eg = _eg()
    root, sp = _proj(tmp_path)
    _daml(root, "Asset.daml", _TEMPLATE_BODY)
    assert eg.compute_critical_asset_mover_candidates(sp) == []


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
