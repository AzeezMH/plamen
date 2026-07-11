"""M2 (recall): permissionless-setter detector. An external/public function
that writes contract state with no recognizable access gate (modifier or
body guard) is a candidate missing-access-control finding. Mechanical
Solidity parse, no SCIP dependency. Favors precision — any recognizable gate
excludes the function, to avoid an admin-setter false-positive flood."""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path


def _rp():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    return importlib.import_module("recon_prepass")


def test_flags_ungated_state_writing_setter(tmp_path: Path):
    rp = _rp()
    (tmp_path / "Foo.sol").write_text(
        "contract Foo {\n"
        " uint256 public fee;\n"
        " function setFee(uint x) external {\n"
        "  fee = x;\n"
        " }\n"
        "}\n", encoding="utf-8")
    fs = rp.compute_permissionless_setter_findings(str(tmp_path))
    assert len(fs) == 1
    assert fs[0]["id"] == "PSET-1"
    assert "setFee" in fs[0]["title"]
    assert fs[0]["severity"] == "Low"
    assert "L4" in fs[0]["location"] or ":L" in fs[0]["location"]


def test_modifier_gated_setter_not_flagged(tmp_path: Path):
    rp = _rp()
    (tmp_path / "Foo.sol").write_text(
        "contract Foo {\n"
        " uint256 public fee;\n"
        " function setFee(uint x) external onlyOwner {\n"
        "  fee = x;\n"
        " }\n"
        "}\n", encoding="utf-8")
    assert rp.compute_permissionless_setter_findings(str(tmp_path)) == []


def test_body_guard_setter_not_flagged(tmp_path: Path):
    rp = _rp()
    (tmp_path / "Foo.sol").write_text(
        "contract Foo {\n"
        " uint256 public fee;\n"
        " address public owner;\n"
        " function setFee(uint x) external {\n"
        "  require(msg.sender == owner);\n"
        "  fee = x;\n"
        " }\n"
        "}\n", encoding="utf-8")
    assert rp.compute_permissionless_setter_findings(str(tmp_path)) == []


def test_view_getter_not_flagged(tmp_path: Path):
    rp = _rp()
    (tmp_path / "Foo.sol").write_text(
        "contract Foo {\n"
        " uint256 public fee;\n"
        " function getFee() public view returns (uint256) {\n"
        "  return fee;\n"
        " }\n"
        "}\n", encoding="utf-8")
    assert rp.compute_permissionless_setter_findings(str(tmp_path)) == []


def test_whennotpaused_alone_is_not_access_and_still_flags(tmp_path: Path):
    # whenNotPaused is a liveness gate, not an access gate — must NOT suppress
    # the finding on its own.
    rp = _rp()
    (tmp_path / "Foo.sol").write_text(
        "contract Foo {\n"
        " uint256 public fee;\n"
        " function setFee(uint x) external whenNotPaused {\n"
        "  fee = x;\n"
        " }\n"
        "}\n", encoding="utf-8")
    fs = rp.compute_permissionless_setter_findings(str(tmp_path))
    assert len(fs) == 1


def test_constructor_and_initializer_not_flagged(tmp_path: Path):
    rp = _rp()
    (tmp_path / "Foo.sol").write_text(
        "contract Foo {\n"
        " uint256 public fee;\n"
        " constructor(uint x) {\n"
        "  fee = x;\n"
        " }\n"
        " function initialize(uint x) external {\n"
        "  fee = x;\n"
        " }\n"
        "}\n", encoding="utf-8")
    assert rp.compute_permissionless_setter_findings(str(tmp_path)) == []


def test_no_state_write_not_flagged(tmp_path: Path):
    rp = _rp()
    (tmp_path / "Foo.sol").write_text(
        "contract Foo {\n"
        " uint256 public fee;\n"
        " function noop(uint x) external {\n"
        "  uint local = x;\n"
        "  local = local + 1;\n"
        " }\n"
        "}\n", encoding="utf-8")
    assert rp.compute_permissionless_setter_findings(str(tmp_path)) == []


def test_writer_emits_promotable_niche_file(tmp_path: Path):
    rp = _rp()
    sp = tmp_path / ".scratchpad"; sp.mkdir()
    proj = tmp_path / "proj"; proj.mkdir()
    (proj / "Foo.sol").write_text(
        "contract Foo {\n"
        " uint256 public fee;\n"
        " function setFee(uint x) external {\n"
        "  fee = x;\n"
        " }\n"
        "}\n", encoding="utf-8")
    rp._write_permissionless_setter_findings(sp, proj)
    out = (sp / "niche_permissionless_setters_findings.md").read_text(encoding="utf-8")
    assert "### Finding [PSET-1]:" in out
    assert "**Severity**:" in out and "**Location**:" in out and "**Description**:" in out
    m = importlib.import_module("plamen_mechanical")
    assert m._NICHE_FINDING_HEADING_RE.search("### Finding [PSET-1]: x")


def test_writer_empty_tree_never_raises(tmp_path: Path):
    rp = _rp()
    sp = tmp_path / ".scratchpad"; sp.mkdir()
    proj = tmp_path / "proj"; proj.mkdir()
    result = rp._write_permissionless_setter_findings(sp, proj)
    assert result == "NONE"
    out = (sp / "niche_permissionless_setters_findings.md").read_text(encoding="utf-8")
    assert "None" in out or "no" in out.lower()


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
