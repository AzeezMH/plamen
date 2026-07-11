"""Codex usage-cap errors are NATURAL LANGUAGE, not structured tokens, and MUST
be classified as a rate-limit (auto-wait + preserve state via
checkpoint.rate_limited_at), NOT a generic phase failure that burns the retry
budget and HALTS.

Fixture = the verbatim message from a live SC Thorough Codex halt
(account out of credits, reset 5:46 PM). Before the fix the regex looked only
for structured tokens (usage_limit_reached / 429 / "type":"usage_limit") and
missed this, so the run halted instead of auto-waiting.
"""
from pathlib import Path

import plamen_driver as d
from plamen_mechanical import estimate_rate_limit_wait_seconds

_REAL_USAGE_LIMIT = (
    '{"type":"thread.started","thread_id":"019e92ed-5538-74f3-80ee-5a79649d3c7a"}\n'
    '{"type":"turn.started"}\n'
    '{"type":"error","message":"You\'ve hit your usage limit. Visit '
    'https://chatgpt.com/codex/settings/usage to purchase more credits or try '
    'again at 5:46 PM."}\n'
    '{"type":"turn.failed","error":{"message":"You\'ve hit your usage limit. '
    'Visit https://chatgpt.com/codex/settings/usage to purchase more credits or '
    'try again at 5:46 PM."}}\n'
)


def test_real_codex_usage_limit_is_rate_limited(tmp_path: Path):
    log = tmp_path / "_stdio_recon.attempt2.log"
    log.write_text(_REAL_USAGE_LIMIT, encoding="utf-8")
    assert d._CODEX_RATE_LIMIT_RE.search(_REAL_USAGE_LIMIT), (
        "regex must match the verbatim Codex usage-cap message"
    )
    # rc=1 (turn.failed) AND rc=0 (Codex can graceful-stop with the error
    # in-stream) both classify as rate-limited -> auto-wait, never a failure.
    assert d._detect_codex_rate_limit(log, returncode=1) is True
    assert d._detect_codex_rate_limit(log, returncode=0) is True


def test_codex_credit_phrase_variants_match():
    for msg in (
        "You've hit your usage limit.",
        "You have reached your rate limit, try again later.",
        "Please purchase more credits to continue.",
        "see https://chatgpt.com/codex/settings/usage",
    ):
        assert d._CODEX_RATE_LIMIT_RE.search(msg), f"should match: {msg!r}"


def test_codex_normal_output_not_rate_limited(tmp_path: Path):
    log = tmp_path / "_stdio_recon.attempt1.log"
    log.write_text(
        '{"type":"item.completed","item":{"type":"agent_message",'
        '"text":"Using the plamen skill; writing recon artifacts."}}\n',
        encoding="utf-8",
    )
    assert d._detect_codex_rate_limit(log, returncode=0) is False


def test_codex_auth_error_not_misclassified_as_rate_limit(tmp_path: Path):
    # Auth errors need re-auth, not backoff — the new usage-cap patterns must
    # NOT swallow a 401 into the rate-limit path.
    log = tmp_path / "_stdio_recon.attempt1.log"
    log.write_text(
        '{"type":"error","message":"401 unauthorized: invalid_api_key"}\n',
        encoding="utf-8",
    )
    assert d._detect_codex_rate_limit(log, returncode=1) is False


# --- Codex daily-cap reset-window parsing (estimate_rate_limit_wait_seconds) ---
# The verbatim Spectra-run breadth halt: a Codex usage cap whose reset is phrased
# as an ABSOLUTE date+time ("try again at <Mon> <day>, <year> <HH>:<MM> <am/pm>").
# Before the fix the estimator returned None -> caller spun a useless 5-min wait +
# burned a retry that re-hit the same cap.
_SPECTRA_USAGE_LIMIT = (
    '{"type":"turn.started"}\n'
    '{"type":"error","message":"You\'ve hit your usage limit. Upgrade to Pro '
    '(https://chatgpt.com/explore/pro), visit '
    'https://chatgpt.com/codex/settings/usage to purchase more credits or try '
    'again at Jul 11th, 2026 2:46 AM."}\n'
    '{"type":"turn.failed","error":{"message":"You\'ve hit your usage limit. '
    'Upgrade to Pro (https://chatgpt.com/explore/pro), visit '
    'https://chatgpt.com/codex/settings/usage to purchase more credits or try '
    'again at Jul 11th, 2026 2:46 AM."}}\n'
)


def test_absolute_date_reset_window_is_parsed(tmp_path: Path):
    # Time-robust: build the same Codex "try again at <Mon> <day>, <year> <time>"
    # shape as the verbatim Spectra halt, but with a date ~2 days out computed
    # from now, so the test never expires as real time passes the fixture date.
    from datetime import datetime, timedelta

    target = datetime.now().astimezone() + timedelta(days=2)
    mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][target.month - 1]
    hour12 = ((target.hour - 1) % 12) + 1
    ampm = "AM" if target.hour < 12 else "PM"
    stamp = f"{mon} {target.day}, {target.year} {hour12}:{target.minute:02d} {ampm}"
    log = tmp_path / "_stdio_breadth.log"
    log.write_text(
        '{"type":"error","message":"You\'ve hit your usage limit. try again at '
        + stamp + '."}\n',
        encoding="utf-8",
    )
    secs = estimate_rate_limit_wait_seconds(log)
    # A concrete far-future window must be returned (not None -> not the 5-min
    # default), and it must exceed the resume threshold so the caller preserves
    # state for resume instead of spin-waiting.
    assert secs is not None, "absolute 'try again at <date> <time>' must parse"
    assert secs > d._RATE_LIMIT_RESUME_THRESHOLD_S, secs
    assert secs <= 3 * 24 * 3600, secs


def test_verbatim_spectra_message_parses_or_defaults(tmp_path: Path):
    # The exact Spectra fixture. Once real time passes Jul 11 2026 the absolute
    # date is in the past, so parsing returns None (cap already reset) — both
    # outcomes are correct, so assert only that it never raises and, when it
    # does parse, the window is a far-future daily-cap window.
    log = tmp_path / "_stdio_breadth.log"
    log.write_text(_SPECTRA_USAGE_LIMIT, encoding="utf-8")
    secs = estimate_rate_limit_wait_seconds(log)
    assert secs is None or secs > d._RATE_LIMIT_RESUME_THRESHOLD_S, secs


def test_time_only_reset_window_is_parsed(tmp_path: Path):
    # The docstring's own example form ("try again at 5:46 PM") — time only, no
    # date. Must parse to a positive window < 24h (next occurrence of that time).
    log = tmp_path / "_stdio_recon.log"
    log.write_text(
        '{"type":"error","message":"You\'ve hit your usage limit. '
        'try again at 5:46 PM."}\n',
        encoding="utf-8",
    )
    secs = estimate_rate_limit_wait_seconds(log)
    assert secs is not None and 0 < secs <= 24 * 3600, secs


def test_resets_form_still_parses(tmp_path: Path):
    # Regression: the pre-existing "resets HH:MM am/pm" form must still work.
    log = tmp_path / "_stdio_recon.log"
    log.write_text("rate limited; resets 5:46 PM\n", encoding="utf-8")
    secs = estimate_rate_limit_wait_seconds(log)
    assert secs is not None and 0 < secs <= 24 * 3600, secs


def test_retry_after_delta_still_wins(tmp_path: Path):
    # Regression: an explicit minutes-scale retry-after (Anthropic shape) still
    # parses to its small window and stays UNDER the resume threshold.
    log = tmp_path / "_stdio_breadth.log"
    log.write_text("HTTP 429; retry-after: 45 seconds\n", encoding="utf-8")
    secs = estimate_rate_limit_wait_seconds(log)
    assert secs == 45
    assert secs <= d._RATE_LIMIT_RESUME_THRESHOLD_S


def test_no_window_returns_none(tmp_path: Path):
    log = tmp_path / "_stdio_breadth.log"
    log.write_text('{"type":"item.completed"}\n', encoding="utf-8")
    assert estimate_rate_limit_wait_seconds(log) is None


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
