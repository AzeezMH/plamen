"""Wave-4 M3: yield-gated ADDITIVE breadth waves.

Tests the pure planning substrate (`_breadth_wave_plan` and friends) plus the
default/off-path byte-identity contract of the live-wiring wrapper
(`_run_breadth_worker_pool_pty`). Live PTY execution of extra waves
(`_breadth_run_wave_extension`) is intentionally NOT exercised here — it is
best-effort glue around already-tested primitives (`_run_single_breadth_worker_pty`,
`_NonBlockingWorkerPool`) and requires a real subprocess; the decision logic
it depends on (`_breadth_wave_decide`) is fully covered below.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import plamen_driver as D  # noqa: E402


BASELINE_JOBS = [
    {"agent_id": "B1", "focus_area": "token_flow", "output": "analysis_token_flow.md"},
    {"agent_id": "B2", "focus_area": "access_control", "output": "analysis_access_control.md"},
]


def _thorough_config(**overrides) -> dict:
    cfg = {
        "breadth_wave_gating_enabled": True,
        "mode": "thorough",
        "pipeline": "sc",
    }
    cfg.update(overrides)
    return cfg


def _finding_block(finding_id: str, severity: str) -> str:
    return (
        f"## Finding [{finding_id}]: Example issue\n\n"
        f"**Severity**: {severity}\n"
        "**Location**: `Foo.sol:L10`\n"
        "**Description**: synthetic fixture finding.\n\n"
    )


def _write_analysis(sp: Path, name: str, findings: list[tuple[str, str]]) -> None:
    body = "".join(_finding_block(fid, sev) for fid, sev in findings)
    if not body:
        body = "## No Findings\n\nNothing found.\n"
    (sp / name).write_text(
        f"<!-- PLAMEN_ARTIFACT: {name} -->\n<!-- PLAMEN_STATUS: COMPLETE -->\n\n{body}",
        encoding="utf-8",
    )


def _write_baseline(sp: Path, n_findings: int) -> None:
    """Spread `n_findings` above-Info findings across the 2 baseline outputs."""
    per_job = [[], []]
    for i in range(n_findings):
        per_job[i % 2].append((f"B{i}-1", "High"))
    for job, findings in zip(BASELINE_JOBS, per_job):
        _write_analysis(sp, job["output"], findings)


def _write_wave(sp: Path, wave_number: int, n_findings: int) -> None:
    """Spread `n_findings` above-Info findings across a wave's 2 outputs."""
    per_job = [[], []]
    for i in range(n_findings):
        per_job[i % 2].append((f"W{wave_number}-{i}-1", "High"))
    for i, findings in zip((1, 2), per_job):
        _write_analysis(sp, f"analysis_wave{wave_number}_{i}.md", findings)


# ---------------------------------------------------------------------------
# _breadth_wave_count_above_info — mechanical parser
# ---------------------------------------------------------------------------

def test_count_above_info_excludes_informational(tmp_path: Path):
    sp = tmp_path
    _write_analysis(sp, "analysis_a.md", [
        ("A-1", "Critical"), ("A-2", "High"), ("A-3", "Medium"),
        ("A-4", "Low"), ("A-5", "Informational"),
    ])
    # Critical/High/Medium/Low all count as "above Info"; only Info excluded.
    assert D._breadth_wave_count_above_info(sp, ["analysis_a.md"]) == 4


def test_count_above_info_missing_file_is_zero(tmp_path: Path):
    assert D._breadth_wave_count_above_info(tmp_path, ["does_not_exist.md"]) == 0


def test_count_above_info_no_findings_section_is_zero(tmp_path: Path):
    sp = tmp_path
    _write_analysis(sp, "analysis_a.md", [])
    assert D._breadth_wave_count_above_info(sp, ["analysis_a.md"]) == 0


# ---------------------------------------------------------------------------
# _breadth_wave_should_spawn_next — decision core
# ---------------------------------------------------------------------------

def test_should_spawn_first_wave_when_productive():
    should, _reason = D._breadth_wave_should_spawn_next(
        prior_yields=[], this_wave_yield=3, waves_spawned_so_far=0,
    )
    assert should is True


def test_should_not_spawn_when_zero_yield():
    should, _reason = D._breadth_wave_should_spawn_next(
        prior_yields=[], this_wave_yield=0, waves_spawned_so_far=0,
    )
    assert should is False


def test_should_spawn_when_yield_meets_running_median():
    # prior=[3], this=5 (>= median 3) -> continue
    should, _reason = D._breadth_wave_should_spawn_next(
        prior_yields=[3], this_wave_yield=5, waves_spawned_so_far=1,
    )
    assert should is True


def test_should_not_spawn_when_yield_below_running_median():
    # prior=[5], this=1 (< median 5) -> stop
    should, _reason = D._breadth_wave_should_spawn_next(
        prior_yields=[5], this_wave_yield=1, waves_spawned_so_far=1,
    )
    assert should is False


def test_hard_cap_blocks_regardless_of_yield():
    should, reason = D._breadth_wave_should_spawn_next(
        prior_yields=[1, 9], this_wave_yield=99, waves_spawned_so_far=2,
        max_extra_waves=2,
    )
    assert should is False
    assert "cap" in reason


# ---------------------------------------------------------------------------
# _breadth_wave_plan — top-level planner (the main M3 deliverable)
# ---------------------------------------------------------------------------

def test_wave_feature_off_returns_baseline_unchanged_default_identical(tmp_path: Path):
    sp = tmp_path
    _write_baseline(sp, 5)  # even a highly productive baseline...
    result = D._breadth_wave_plan(sp, {}, BASELINE_JOBS)
    # ...must not add anything when the feature flag is absent (default OFF).
    assert result is BASELINE_JOBS
    assert result == BASELINE_JOBS


def test_wave_feature_off_when_flag_set_but_not_thorough(tmp_path: Path):
    sp = tmp_path
    _write_baseline(sp, 5)
    cfg = _thorough_config(mode="core")
    result = D._breadth_wave_plan(sp, cfg, BASELINE_JOBS)
    assert result == BASELINE_JOBS
    assert len(result) == len(BASELINE_JOBS)


def test_wave_feature_off_for_l1_pipeline(tmp_path: Path):
    sp = tmp_path
    _write_baseline(sp, 5)
    cfg = _thorough_config(pipeline="l1")
    result = D._breadth_wave_plan(sp, cfg, BASELINE_JOBS)
    assert result == BASELINE_JOBS


def test_wave0_always_full_baseline_roster_is_the_floor(tmp_path: Path):
    """Baseline (wave 0) is present in full regardless of feature state or
    yield — it is never gated, shrunk, or reordered."""
    sp = tmp_path
    # Zero yield baseline: even so, the returned plan still contains every
    # baseline job at the head, in order.
    _write_baseline(sp, 0)
    cfg = _thorough_config()
    result = D._breadth_wave_plan(sp, cfg, BASELINE_JOBS)
    assert result[: len(BASELINE_JOBS)] == BASELINE_JOBS


def test_zero_yield_baseline_spawns_no_wave(tmp_path: Path):
    sp = tmp_path
    _write_baseline(sp, 0)
    cfg = _thorough_config()
    result = D._breadth_wave_plan(sp, cfg, BASELINE_JOBS)
    assert result == BASELINE_JOBS


def test_productive_baseline_spawns_wave1(tmp_path: Path):
    sp = tmp_path
    _write_baseline(sp, 4)
    cfg = _thorough_config()
    result = D._breadth_wave_plan(sp, cfg, BASELINE_JOBS)
    assert len(result) == len(BASELINE_JOBS) + 2
    outputs = [j["output"] for j in result]
    assert "analysis_wave1_1.md" in outputs
    assert "analysis_wave1_2.md" in outputs


def test_high_yield_wave1_spawns_wave2(tmp_path: Path):
    sp = tmp_path
    _write_baseline(sp, 3)       # baseline yield = 3
    _write_wave(sp, 1, 5)        # wave1 yield = 5 >= median([3]) -> spawn wave2
    cfg = _thorough_config()
    result = D._breadth_wave_plan(sp, cfg, BASELINE_JOBS)
    outputs = [j["output"] for j in result]
    assert "analysis_wave1_1.md" in outputs and "analysis_wave1_2.md" in outputs
    assert "analysis_wave2_1.md" in outputs and "analysis_wave2_2.md" in outputs
    assert len(result) == len(BASELINE_JOBS) + 4


def test_low_yield_wave1_stops_no_wave2(tmp_path: Path):
    sp = tmp_path
    _write_baseline(sp, 5)       # baseline yield = 5
    _write_wave(sp, 1, 1)        # wave1 yield = 1 < median([5]) -> stop
    cfg = _thorough_config()
    result = D._breadth_wave_plan(sp, cfg, BASELINE_JOBS)
    outputs = [j["output"] for j in result]
    assert "analysis_wave1_1.md" in outputs
    assert "analysis_wave2_1.md" not in outputs
    assert len(result) == len(BASELINE_JOBS) + 2


def test_hard_wave_cap_respected(tmp_path: Path):
    sp = tmp_path
    _write_baseline(sp, 3)
    _write_wave(sp, 1, 5)   # productive
    _write_wave(sp, 2, 8)   # even more productive -- should NOT spawn wave3
    cfg = _thorough_config()
    result = D._breadth_wave_plan(sp, cfg, BASELINE_JOBS, max_extra_waves=2)
    outputs = [j["output"] for j in result]
    assert "analysis_wave2_1.md" in outputs
    assert "analysis_wave3_1.md" not in outputs
    # baseline (2) + wave1 (2) + wave2 (2), never more.
    assert len(result) == len(BASELINE_JOBS) + 4


def test_never_returns_fewer_jobs_than_baseline(tmp_path: Path):
    scenarios = [
        ({}, 0),
        (_thorough_config(), 0),
        (_thorough_config(), 5),
        (_thorough_config(mode="light"), 5),
        (_thorough_config(pipeline="l1"), 5),
    ]
    for cfg, n in scenarios:
        sp = tmp_path / f"case_{n}_{cfg.get('mode')}_{cfg.get('pipeline')}_{cfg.get('breadth_wave_gating_enabled')}"
        sp.mkdir(parents=True, exist_ok=True)
        _write_baseline(sp, n)
        result = D._breadth_wave_plan(sp, cfg, BASELINE_JOBS)
        assert len(result) >= len(BASELINE_JOBS)
        assert result[: len(BASELINE_JOBS)] == BASELINE_JOBS


def test_empty_baseline_jobs_returns_empty(tmp_path: Path):
    cfg = _thorough_config()
    result = D._breadth_wave_plan(tmp_path, cfg, [])
    assert result == []


def test_plan_is_idempotent_across_repeated_calls(tmp_path: Path):
    """Replanning against the same disk state must not double-append."""
    sp = tmp_path
    _write_baseline(sp, 3)
    _write_wave(sp, 1, 5)
    cfg = _thorough_config()
    result1 = D._breadth_wave_plan(sp, cfg, BASELINE_JOBS)
    result2 = D._breadth_wave_plan(sp, cfg, BASELINE_JOBS)
    assert result1 == result2


# ---------------------------------------------------------------------------
# Live-wiring wrapper — default path must be byte-identical to the core
# ---------------------------------------------------------------------------

def test_wrapper_default_path_is_pure_passthrough_to_core(tmp_path: Path, monkeypatch):
    """When wave gating is disabled, `_run_breadth_worker_pool_pty` must not
    do anything beyond forwarding the core function's return code -- no wave
    decision, no extra I/O, no extra worker spawn attempts."""
    calls = {"core": 0, "extension": 0}

    def fake_core(**kwargs):
        calls["core"] += 1
        return 0

    def fake_extension(**kwargs):
        calls["extension"] += 1

    monkeypatch.setattr(D, "_run_breadth_worker_pool_pty_core", fake_core)
    monkeypatch.setattr(D, "_breadth_run_wave_extension", fake_extension)

    rc = D._run_breadth_worker_pool_pty(
        scratchpad=tmp_path,
        project_root=str(tmp_path),
        config={},
        phase=D.Phase(
            name="breadth", section_markers=["Phase 3"],
            expected_artifacts=["analysis_*.md"], base_timeout_s=60,
            min_artifact_bytes=200,
        ),
        base_cmd=["claude"],
        env={},
        timeout=60.0,
        quiescence_s=8.0,
        attempt=1,
    )
    assert rc == 0
    assert calls["core"] == 1
    assert calls["extension"] == 0


def test_wrapper_skips_extension_when_core_fails(tmp_path: Path, monkeypatch):
    calls = {"extension": 0}

    def fake_core(**kwargs):
        return -2

    def fake_extension(**kwargs):
        calls["extension"] += 1

    monkeypatch.setattr(D, "_run_breadth_worker_pool_pty_core", fake_core)
    monkeypatch.setattr(D, "_breadth_run_wave_extension", fake_extension)

    rc = D._run_breadth_worker_pool_pty(
        scratchpad=tmp_path,
        project_root=str(tmp_path),
        config=_thorough_config(),
        phase=D.Phase(
            name="breadth", section_markers=["Phase 3"],
            expected_artifacts=["analysis_*.md"], base_timeout_s=60,
            min_artifact_bytes=200,
        ),
        base_cmd=["claude"],
        env={},
        timeout=60.0,
        quiescence_s=8.0,
        attempt=1,
    )
    assert rc == -2
    assert calls["extension"] == 0


def test_wrapper_runs_extension_only_when_enabled_and_core_succeeds(tmp_path: Path, monkeypatch):
    calls = {"extension": 0}

    def fake_core(**kwargs):
        return 0

    def fake_extension(**kwargs):
        calls["extension"] += 1

    monkeypatch.setattr(D, "_run_breadth_worker_pool_pty_core", fake_core)
    monkeypatch.setattr(D, "_breadth_run_wave_extension", fake_extension)
    monkeypatch.setattr(D, "_breadth_worker_jobs", lambda *a, **k: BASELINE_JOBS)

    rc = D._run_breadth_worker_pool_pty(
        scratchpad=tmp_path,
        project_root=str(tmp_path),
        config=_thorough_config(),
        phase=D.Phase(
            name="breadth", section_markers=["Phase 3"],
            expected_artifacts=["analysis_*.md"], base_timeout_s=60,
            min_artifact_bytes=200,
        ),
        base_cmd=["claude"],
        env={},
        timeout=60.0,
        quiescence_s=8.0,
        attempt=1,
    )
    assert rc == 0
    assert calls["extension"] == 1
