"""Tests for Wave-2 L1 proof-harness items A1 (`go test -race` routing) and
A3 (l1_go/l1_rust fuzz_engines template registration) in mechanical_verify.py.

Covers:
  - A1: an l1_go finding whose verification_queue Bug Class names a
    race/concurrency defect gets `-race` injected into the rendered command
    AND a raised per-test timeout; a non-race l1_go row and an SC (evm) row
    do NOT, even when fed the identical race-class bug_class_map (adversarial
    SC-isolation check).
  - A1: `_load_race_bug_class_map` is gated to language == "l1_go" — returns
    `{}` immediately for every other language, including when the on-disk
    verification_queue.md contains race-class rows.
  - A3: the l1_go / l1_rust registry entries injected by
    `_ensure_l1_registry_entries` carry a `fuzz_engines[0].template_path`
    that resolves to a real file on disk (mirrors
    test_language_skill_registry_contracts.py's soroban template_path
    assertion).
  - SC isolation fixture: the on-disk SC registry (evm/solana/aptos/sui/
    soroban/daml) is byte-identical to the pre-change registry file, and the
    EVM command-building path is unaffected by the race machinery.

Run: `cd scripts && python -m pytest test_l1_race_fuzz_registry.py -v`
"""
from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


def _mv():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
    if "mechanical_verify" in sys.modules:
        del sys.modules["mechanical_verify"]
    return importlib.import_module("mechanical_verify")


def _plamen_home() -> Path:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
    if "plamen_types" in sys.modules:
        del sys.modules["plamen_types"]
    import plamen_types
    return plamen_types.plamen_home()


# ---------------------------------------------------------------------------
# A1: race Bug-Class keyword matching + flag injection helpers
# ---------------------------------------------------------------------------


def test_is_race_bug_class_positive_matches():
    mv = _mv()
    for bc in (
        "Data race", "RACE CONDITION", "concurrency bug",
        "goroutine leak", "Deadlock", "TOCTOU", "concurrent map write",
    ):
        assert mv._is_race_bug_class(bc), f"expected race match for {bc!r}"


def test_is_race_bug_class_negative_and_safe_defaults():
    mv = _mv()
    for bc in ("Access Control", "Missing Event", "Integer Overflow", "", None):
        assert not mv._is_race_bug_class(bc)  # type: ignore[arg-type]


def test_inject_go_race_flag_inserts_once_after_test_token():
    mv = _mv()
    argv = ["go", "test", "-run", "^Fn$", "-v", "./..."]
    out = mv._inject_go_race_flag(argv)
    assert out == ["go", "test", "-race", "-run", "^Fn$", "-v", "./..."]
    # Idempotent — calling twice does not duplicate the flag.
    out2 = mv._inject_go_race_flag(out)
    assert out2 == out


# ---------------------------------------------------------------------------
# A1: _load_race_bug_class_map — l1_go-only gate
# ---------------------------------------------------------------------------


_QUEUE_HEADER = (
    "# Verification Queue Manifest\n"
    "| Queue # | Finding ID | Expected Output File | Severity | Title | Bug Class | "
    "Preferred Tag | Location | Primary Artifact | PoC Class |\n"
    "|---------|------------|----------------------|----------|-------|-----------|"
    "---------------|----------|------------------|-----------|\n"
)


def _write_queue(sp: Path, rows: list[tuple[str, str, str]]):
    """rows: list of (finding_id, severity, bug_class)."""
    body = []
    for i, (fid, sev, bug_class) in enumerate(rows, start=1):
        body.append(
            f"| {i} | {fid} | verify_{fid}.md | {sev} | some title | {bug_class} | "
            f"CODE-TRACE | pkg/foo.go:10 | depth_state_trace_findings.md | structural |"
        )
    (sp / "verification_queue.md").write_text(
        _QUEUE_HEADER + "\n".join(body) + "\n", encoding="utf-8"
    )


def test_load_race_bug_class_map_l1_go_positive_harvest(tmp_path):
    """Positive-harvest: a real l1_go queue with a race row yields a NON-EMPTY
    map containing that finding's Bug Class string."""
    mv = _mv()
    _write_queue(tmp_path, [
        ("H-1", "High", "Data race on shared connection pool"),
        ("H-2", "Medium", "Missing input validation"),
    ])
    m = mv._load_race_bug_class_map(tmp_path, "l1_go")
    assert m, "expected a non-empty bug-class map for l1_go"
    assert "H-1" in m and mv._is_race_bug_class(m["H-1"])
    assert "H-2" in m and not mv._is_race_bug_class(m["H-2"])


def test_load_race_bug_class_map_gated_to_l1_go_only(tmp_path):
    """SC ISOLATION: identical race-class queue rows produce `{}` for every
    language other than l1_go — including l1_rust and every SC language."""
    mv = _mv()
    _write_queue(tmp_path, [("H-1", "High", "Data race on shared connection pool")])
    for lang in ("evm", "solana", "aptos", "sui", "soroban", "daml", "l1_rust", "", "go"):
        assert mv._load_race_bug_class_map(tmp_path, lang) == {}, (
            f"expected empty map for language={lang!r}"
        )


def test_load_race_bug_class_map_degrades_on_missing_queue(tmp_path):
    """HALTLESS: no verification_queue.md at all -> {} not an exception."""
    mv = _mv()
    assert mv._load_race_bug_class_map(tmp_path, "l1_go") == {}


def test_load_race_bug_class_map_degrades_on_parser_import_failure(tmp_path, monkeypatch):
    """HALTLESS: if plamen_parsers can't be imported/used, degrade to {} rather
    than raising and killing the whole mechanical-verify phase."""
    mv = _mv()
    _write_queue(tmp_path, [("H-1", "High", "Data race on shared connection pool")])

    def _boom():
        raise RuntimeError("simulated import failure")

    monkeypatch.setattr(mv, "_parsers_module", _boom)
    assert mv._load_race_bug_class_map(tmp_path, "l1_go") == {}


# ---------------------------------------------------------------------------
# A1: _run_test_for_finding — race routing end-to-end (subprocess mocked)
# ---------------------------------------------------------------------------


class _FakeCompletedProcess:
    def __init__(self, returncode=0, stdout="PASS\nok", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _stub_probe(monkeypatch, mv, *, test_function="TestFoo", finding_id="H-1"):
    """Force parse_verify_file + path resolution so the run reaches the
    subprocess.run call without needing a real toolchain or a real test file
    on disk."""
    probe = SimpleNamespace(
        finding_id=finding_id,
        test_file_resolved="pkg/foo_test.go",
        test_function=test_function,
        test_command="",
        package=None,
        test_target=None,
        features=[],
    )
    fake_spike = SimpleNamespace(parse_verify_file=lambda *a, **k: probe)
    monkeypatch.setattr(mv, "_spike_module", lambda: fake_spike)
    monkeypatch.setattr(mv.shutil, "which", lambda b: b)  # binary "available"
    monkeypatch.setattr(
        mv, "_resolve_test_path_for", lambda *a, **k: Path("pkg/foo_test.go")
    )
    return probe


def test_race_class_l1_go_row_gets_race_flag_and_raised_timeout(tmp_path, monkeypatch):
    mv = _mv()
    _stub_probe(monkeypatch, mv, test_function="TestRaceFinding", finding_id="H-1")

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["timeout"] = kwargs.get("timeout")
        captured["env"] = kwargs.get("env")
        return _FakeCompletedProcess()

    monkeypatch.setattr(mv.subprocess, "run", fake_run)
    registry = mv._load_registry()
    bug_class_map = {"H-1": "Data race on shared connection pool"}

    result = mv._run_test_for_finding(
        tmp_path / "verify_H-1.md", tmp_path, "l1_go", registry,
        per_test_timeout_s=100, project_root=tmp_path,
        bug_class_map=bug_class_map,
    )

    assert "-race" in captured["cmd"], f"expected -race in {captured['cmd']}"
    assert captured["timeout"] == 100 * mv._RACE_TIMEOUT_MULTIPLIER
    assert captured["env"] is not None and captured["env"].get("CGO_ENABLED") == "1"
    assert result.race_mode is True
    assert result.status == "PASS"


def test_non_race_l1_go_row_unaffected(tmp_path, monkeypatch):
    mv = _mv()
    _stub_probe(monkeypatch, mv, test_function="TestPlainFinding", finding_id="H-2")

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["timeout"] = kwargs.get("timeout")
        captured["env"] = kwargs.get("env")
        return _FakeCompletedProcess()

    monkeypatch.setattr(mv.subprocess, "run", fake_run)
    registry = mv._load_registry()
    # Same map object, but H-2's bug class is not a race class.
    bug_class_map = {
        "H-1": "Data race on shared connection pool",
        "H-2": "Missing input validation",
    }

    result = mv._run_test_for_finding(
        tmp_path / "verify_H-2.md", tmp_path, "l1_go", registry,
        per_test_timeout_s=100, project_root=tmp_path,
        bug_class_map=bug_class_map,
    )

    assert "-race" not in captured["cmd"]
    assert captured["timeout"] == 100
    assert captured["env"] is None
    assert result.race_mode is False


def test_sc_evm_row_unaffected_by_race_bug_class_map(tmp_path, monkeypatch):
    """SC ISOLATION (adversarial): even when handed a race-class bug_class_map
    for an EVM finding, the EVM path must behave exactly as it does with no
    map at all -- no -race flag exists in Solidity/forge, and the EVM branch
    doesn't even consult bug_class_map."""
    mv = _mv()
    probe = SimpleNamespace(
        finding_id="H-1",
        test_file_resolved="test/Foo.t.sol",
        test_function="test_h1",
        test_command="forge test --match-test test_h1",
        package=None,
        test_target=None,
        features=[],
    )
    fake_spike = SimpleNamespace(parse_verify_file=lambda *a, **k: probe)
    monkeypatch.setattr(mv, "_spike_module", lambda: fake_spike)
    monkeypatch.setattr(mv.shutil, "which", lambda b: b)
    monkeypatch.setattr(
        mv, "_resolve_test_path_for", lambda *a, **k: Path("test/Foo.t.sol")
    )
    monkeypatch.setattr(
        mv, "_evm_forge_filter", lambda probe, rel: ["--match-test", "test_h1"]
    )
    monkeypatch.setattr(mv, "_resolve_foundry_profile", lambda *a, **k: None)

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["timeout"] = kwargs.get("timeout")
        return _FakeCompletedProcess()

    monkeypatch.setattr(mv.subprocess, "run", fake_run)
    registry = mv._load_registry()
    bug_class_map = {"H-1": "Data race on shared connection pool"}

    result = mv._run_test_for_finding(
        tmp_path / "verify_H-1.md", tmp_path, "evm", registry,
        per_test_timeout_s=42, project_root=tmp_path,
        bug_class_map=bug_class_map,
    )

    assert "-race" not in captured["cmd"]
    assert captured["timeout"] == 42
    assert result.race_mode is False


# ---------------------------------------------------------------------------
# A3: l1_go / l1_rust fuzz_engines template registration
# ---------------------------------------------------------------------------


def test_l1_go_fuzz_engine_template_path_resolves_to_real_file():
    mv = _mv()
    root = _plamen_home()
    reg = {"version": 2, "languages": {}}
    mv._ensure_l1_registry_entries(reg)
    engines = reg["languages"]["l1_go"]["fuzz_engines"]
    assert engines, "l1_go fuzz_engines must be non-empty (positive harvest)"
    template_path = engines[0]["template_path"]
    assert (root / template_path).exists(), template_path
    text = (root / template_path).read_text(encoding="utf-8")
    assert "func Fuzz" in text  # real Go native-fuzz skeleton, not a stub


def test_l1_rust_fuzz_engine_template_path_resolves_to_real_file():
    mv = _mv()
    root = _plamen_home()
    reg = {"version": 2, "languages": {}}
    mv._ensure_l1_registry_entries(reg)
    engines = reg["languages"]["l1_rust"]["fuzz_engines"]
    assert engines, "l1_rust fuzz_engines must be non-empty (positive harvest)"
    template_path = engines[0]["template_path"]
    assert (root / template_path).exists(), template_path
    text = (root / template_path).read_text(encoding="utf-8")
    assert "fuzz_target!" in text  # real libfuzzer-sys skeleton, not a stub
    # A proptest fallback engine must also be registered (mirrors soroban's
    # cargo_fuzz + proptest pair) even though it has no template_path.
    assert any(e.get("name") == "proptest" for e in engines)


def test_fuzz_engine_command_uses_test_function_token():
    """The registered fuzz commands must use the SAME {test_function} token
    the l1_go/l1_rust test_command already substitutes, not an unwired
    ad-hoc token."""
    mv = _mv()
    reg = {"version": 2, "languages": {}}
    mv._ensure_l1_registry_entries(reg)
    go_cmd = reg["languages"]["l1_go"]["fuzz_engines"][0]["command"]
    rust_cmd = reg["languages"]["l1_rust"]["fuzz_engines"][0]["command"]
    assert "{test_function}" in go_cmd
    assert "-fuzz" in go_cmd
    assert "{test_function}" in rust_cmd
    assert "fuzz run" in rust_cmd


def test_fuzz_engine_registration_is_idempotent():
    mv = _mv()
    reg = {"version": 2, "languages": {}}
    mv._ensure_l1_registry_entries(reg)
    mv._ensure_l1_registry_entries(reg)
    assert len(reg["languages"]["l1_go"]["fuzz_engines"]) == 1
    assert len(reg["languages"]["l1_rust"]["fuzz_engines"]) == 2


# ---------------------------------------------------------------------------
# SC ISOLATION fixture: on-disk SC registry untouched
# ---------------------------------------------------------------------------


def test_sc_registry_file_unaffected_by_l1_overlay():
    """The on-disk language-toolchain-registry.json (SC languages only) must
    still validate exactly as test_language_skill_registry_contracts.py
    expects -- l1_go/l1_rust are a RUNTIME overlay, never written to disk."""
    root = _plamen_home()
    registry = json.loads(
        (root / "rules" / "language-toolchain-registry.json").read_text(
            encoding="utf-8"
        )
    )
    expected = {"evm", "solana", "aptos", "sui", "soroban", "daml"}
    assert set(registry["languages"]) == expected
    assert "l1_go" not in registry["languages"]
    assert "l1_rust" not in registry["languages"]
    # Existing soroban/sui contract untouched.
    assert registry["languages"]["sui"]["fuzz_engines"][0]["template"] == "#[random_test]"
    soroban_template = registry["languages"]["soroban"]["fuzz_engines"][0]["template_path"]
    assert (root / soroban_template).exists()


def test_evm_command_building_unaffected_by_race_helpers():
    """The EVM `_format_test_command` path is untouched: it never sees
    `-race` or the l1_go race gate."""
    mv = _mv()
    cmd = mv._format_test_command(
        "forge test --match-test test_{id} -vvv", "test_h1", None, language="evm"
    )
    assert "-race" not in cmd
    assert cmd == ["forge", "test", "--match-test", "test_h1", "-vvv"]
