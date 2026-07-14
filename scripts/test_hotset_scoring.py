"""M2 hot-set fidelity + Formula-2 scoring (scoped denoise + reweight).

Exercises the M2-isolated changes in `compute_hot_function_set` /
`_load_function_summary` (enumeration_gate.py):

  - builtin-method DENOISE of `fn_writes` (a math-util whose only write-signal is
    a generic language builtin symbol loses `writes`);
  - Formula-2 REWEIGHT (log-dampened fan-in + kept security terms + a mild flat
    entry-point bonus) — entry-point real-writers rank up, high-fan-in shared
    utils are dampened but NOT evicted, value-movers are never evicted, cap=40
    and deterministic order preserved, row schema byte-unchanged;
  - header-driven Callers column in `_load_function_summary` (correct across
    SCIP- and EVM-shaped summaries; clean fallback when no label is found).

All fixtures use synthetic, generic names only (writeFn/coldFn/mathUtil/entryFn/
valueMover/f0..fN). No protocol/token/function vocabulary appears anywhere — the
denylist is generic language builtins and the scoring is pure topology.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

# Row schema keys the M2 consumer (compute_axis_coverage_gaps) depends on.
# Byte-exact — the reweight must not add/rename/drop a key.
_ROW_KEYS = {"function", "loc", "callers", "writes", "elevate",
             "value_effect", "score", "lang"}


def _eg():
    return importlib.import_module("enumeration_gate")


def _proj(tmp_path: Path):
    root = tmp_path / "proj"
    sp = root / ".scratchpad"
    sp.mkdir(parents=True)
    (sp / "findings_inventory.md").write_text("# Inv\n", encoding="utf-8")
    return root, sp


def _sol(root: Path, rel: str, body: str):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("// SPDX-License-Identifier: MIT\npragma solidity ^0.8.20;\n" + body,
                 encoding="utf-8")


def _write_graph(sp: Path, var_refs: dict, functions: dict):
    (sp / "_mechanical_graph.json").write_text(
        json.dumps({"source": "slither", "var_refs": var_refs, "functions": functions}),
        encoding="utf-8")


# ── (a) builtin-method denoise: builtin-named write descriptors don't count ──

def test_builtin_write_descriptors_are_denoised(tmp_path):
    eg = _eg()
    root, sp = _proj(tmp_path)
    # Both `mul` (a builtin-method symbol) and `realWriter` are recorded as
    # referencing state `total`. Both have 2 callers so both are hot and appear.
    # After denoise, `mul` (and the `checked_add` prefix family) must NOT be a
    # writer; `realWriter` (a real, non-builtin symbol) must remain a writer.
    _write_graph(
        sp,
        var_refs={"C.total": {"bare": "total", "refs": [
            "mul (C.sol:L1)", "checked_add (C.sol:L2)", "realWriter (C.sol:L3)"]}},
        functions={
            "C.mul": {"bare": "mul", "loc": "C.sol:L1", "callers": ["p", "q"]},
            "C.checked_add": {"bare": "checked_add", "loc": "C.sol:L2", "callers": ["p", "q"]},
            "C.realWriter": {"bare": "realWriter", "loc": "C.sol:L3", "callers": ["p", "q"]},
        },
    )
    _sol(root, "C.sol", "contract C {}\n")
    hot = eg.compute_hot_function_set(sp)
    by = {h["function"]: h for h in hot}
    assert by["mul"]["writes"] is False            # builtin symbol denoised
    assert by["checked_add"]["writes"] is False    # denylisted prefix family
    assert by["realWriter"]["writes"] is True      # genuine state writer kept


def test_is_builtin_method_helper_generic_only(tmp_path):
    eg = _eg()
    assert eg._is_builtin_method("mul") is True
    assert eg._is_builtin_method("UNWRAP_OR") is True        # case-insensitive
    assert eg._is_builtin_method("saturating_sub") is True   # prefix family
    assert eg._is_builtin_method("as_u128") is True          # prefix family
    assert eg._is_builtin_method("realWriter") is False
    assert eg._is_builtin_method("") is False


# ── (b) entry-point fn with a real write ranks up ──

def test_entry_point_real_writer_ranks_up(tmp_path):
    eg = _eg()
    root, sp = _proj(tmp_path)
    # entryFn: 0 callers (<= ENTRY_THRESH) + a REAL non-builtin state write.
    # coldMidFn: 3 callers, no write/effect. The log-dampened fan-in of coldMidFn
    # (log2(4)=2.0) must fall BELOW entryFn's write + entry bonus (2.0 + 1.0).
    _write_graph(
        sp,
        var_refs={"C.state": {"bare": "state", "refs": ["entryFn (C.sol:L1)"]}},
        functions={
            "C.entryFn": {"bare": "entryFn", "loc": "C.sol:L1", "callers": []},
            "C.coldMidFn": {"bare": "coldMidFn", "loc": "C.sol:L9",
                            "callers": ["a", "b", "c"]},
        },
    )
    _sol(root, "C.sol", "contract C {}\n")
    hot = eg.compute_hot_function_set(sp)
    names = [h["function"] for h in hot]
    assert "entryFn" in names and "coldMidFn" in names
    assert names.index("entryFn") < names.index("coldMidFn")
    by = {h["function"]: h for h in hot}
    assert by["entryFn"]["writes"] is True


# ── (c)+(d)+(e)+(f) dampen-not-evict, value-movers retained, cap, order ──

def test_high_fanin_util_dampened_but_not_evicted_and_movers_retained(tmp_path):
    eg = _eg()
    root, sp = _proj(tmp_path)
    # A flood of 45 cold high-fan-in utils (8 callers each, no write/effect),
    # plus a high-fan-in shared util WITH a real write, plus three value-movers
    # (real write + value effect + entry). Under the OLD linear score the 8-caller
    # utils would dominate; under Formula-2 (log-dampened) they are dampened and
    # the value-movers survive the cap. Value-mover eviction is the explicit
    # failure mode this asserts against.
    functions = {}
    var_refs_refs = []
    for i in range(45):
        functions[f"C.f{i}"] = {"bare": f"f{i}", "loc": f"C.sol:L{100 + i}",
                                "callers": ["a"] * 8}
    # high-fan-in shared util that ALSO writes state -> must be dampened, not dropped
    functions["C.sharedUtil"] = {"bare": "sharedUtil", "loc": "C.sol:L10",
                                  "callers": ["a"] * 50}
    var_refs_refs.append("sharedUtil (C.sol:L10)")
    # value-movers: real write + (source) value effect + entry (0/1 callers)
    movers = {"valueMover": 0, "burnFn": 1, "redeemFn": 0}
    for m, ncall in movers.items():
        functions[f"C.{m}"] = {"bare": m, "loc": f"C.sol:L{len(m)}",
                               "callers": ["a"] * ncall}
        var_refs_refs.append(f"{m} (C.sol:L1)")
    _write_graph(sp, var_refs={"C.state": {"bare": "state", "refs": var_refs_refs}},
                 functions=functions)
    # source so the movers register a value effect (generic token move)
    _sol(root, "C.sol",
         "contract C {\n"
         "  function valueMover(address to, uint a) external { token.transfer(to, a); }\n"
         "  function burnFn(address to, uint a) external { token.transfer(to, a); }\n"
         "  function redeemFn(address to, uint a) external { token.transfer(to, a); }\n"
         "}\n")
    hot = eg.compute_hot_function_set(sp)
    names = [h["function"] for h in hot]
    # (e) cap preserved
    assert len(hot) == eg._MAX_HOT_FUNCTIONS == 40
    # (c) high-fan-in shared writer dampened but retained
    assert "sharedUtil" in names
    # (d) value-movers retained despite the 45-util flood evicting 8 entries
    for m in movers:
        assert m in names, f"value-mover {m} was evicted (failure mode)"
    # (g) row schema byte-unchanged
    for h in hot:
        assert set(h.keys()) == _ROW_KEYS
    # (f) deterministic order preserved across repeated calls
    assert [h["function"] for h in eg.compute_hot_function_set(sp)] == names
    # deterministic tie-break: equal-score cold utils are ordered by name asc
    util_names = [n for n in names if n.startswith("f") and n[1:].isdigit()]
    assert util_names == sorted(util_names, key=str.lower)


def test_row_schema_keys_exact(tmp_path):
    eg = _eg()
    root, sp = _proj(tmp_path)
    _write_graph(
        sp,
        var_refs={"C.total": {"bare": "total", "refs": ["writeFn (C.sol:L1)"]}},
        functions={"C.writeFn": {"bare": "writeFn", "loc": "C.sol:L1", "callers": ["a", "b"]}},
    )
    _sol(root, "C.sol", "contract C {\n  function writeFn(uint x) external { total += x; }\n}\n")
    hot = eg.compute_hot_function_set(sp)
    assert hot
    assert set(hot[0].keys()) == _ROW_KEYS


# ── (h) header-driven Callers column in _load_function_summary ──

def test_load_summary_header_driven_evm_shape(tmp_path):
    eg = _eg()
    _root, sp = _proj(tmp_path)
    # EVM-shaped summary: Callers is at index 3, NOT the SCIP index 4. The legacy
    # cells[4] would misread the Callees column (2); header-driven must read 7.
    (sp / "function_summary.md").write_text(
        "| Function | Contract | Visibility | Callers | Callees |\n"
        "|---|---|---|---|---|\n"
        "| `foo` | C | external | 7 | 2 |\n",
        encoding="utf-8")
    summ = eg._load_function_summary(sp)
    assert summ.get("foo", {}).get("callers") == 7


def test_load_summary_header_driven_scip_shape(tmp_path):
    eg = _eg()
    _root, sp = _proj(tmp_path)
    # SCIP-shaped summary: Callers at index 4 (label-resolved, still correct).
    (sp / "function_summary.md").write_text(
        "| Function | File | Line | Kind | Callers | Callees |\n"
        "|---|---|---|---|---|---|\n"
        "| `bar` | f.rs | 10 | function | 5 | 3 |\n",
        encoding="utf-8")
    summ = eg._load_function_summary(sp)
    assert summ.get("bar", {}).get("callers") == 5


def test_load_summary_hash_prefixed_header_reads_callers_not_callees(tmp_path):
    eg = _eg()
    _root, sp = _proj(tmp_path)
    # Some recon writers emit `#Callers` / `#Callees` (leading `#`). The bare
    # `== "callers"` compare misses this, falls back to legacy cells[4], and in
    # this schema cells[4] is `#Callees` (3) -- silently reading callee count as
    # caller count. The header-label match must strip the leading `#` and find
    # the REAL Callers column (7), not the Callees column (3).
    (sp / "function_summary.md").write_text(
        "| Function | Contract | Visibility | #Callers | #Callees |\n"
        "|---|---|---|---|---|\n"
        "| `qux` | C | external | 7 | 3 |\n",
        encoding="utf-8")
    summ = eg._load_function_summary(sp)
    assert summ.get("qux", {}).get("callers") == 7


def test_load_summary_plain_callers_header_still_works(tmp_path):
    eg = _eg()
    _root, sp = _proj(tmp_path)
    # Plain (non-hash-prefixed) `Callers` / `Callees` header must still resolve
    # correctly after the leading-`#` normalization is added.
    (sp / "function_summary.md").write_text(
        "| Function | Contract | Callers | Callees |\n"
        "|---|---|---|---|\n"
        "| `plain` | C | 9 | 1 |\n",
        encoding="utf-8")
    summ = eg._load_function_summary(sp)
    assert summ.get("plain", {}).get("callers") == 9


def test_load_summary_falls_back_to_index4_when_no_callers_label(tmp_path):
    eg = _eg()
    _root, sp = _proj(tmp_path)
    # Header present but no "Callers" label -> callers_idx stays None -> legacy
    # cells[4]-if-int fallback keeps SCIP-layout parsing working.
    (sp / "function_summary.md").write_text(
        "| Function | File | Line | Kind | Cnt | Callees |\n"
        "|---|---|---|---|---|---|\n"
        "| `baz` | f.rs | 10 | function | 6 | 3 |\n",
        encoding="utf-8")
    summ = eg._load_function_summary(sp)
    assert summ.get("baz", {}).get("callers") == 6
