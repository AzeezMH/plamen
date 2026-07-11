#!/usr/bin/env python3
"""Plamen — Supply-Chain Pre-Exec Safety Gate (ITEM H2).

The driver runs the TARGET repo's *own* untrusted install/build/test/fuzz
commands (forge/npm/yarn/pnpm/cargo/...) with no vetting. This module is a
mechanical, hermetic, fail-closed gate called BEFORE any such subprocess so a
poisoned dependency lockfile cannot execute an install-time payload on the
auditor's machine.

Design
------
- **Hermetic**: the actual scanner invocation is isolated behind
  ``_call_offline_scanner`` so tests can monkeypatch it directly instead of
  needing a real network-connected scanner binary. No network calls are made
  by this module itself (``osv-scanner --offline`` / ``npm audit`` /
  ``cargo audit`` are all local-lockfile tools).
- **Fail-closed**: a CRITICAL/malicious signal (scanner hit, IoC denylist
  match, or the install-script/base64 heuristic) raises
  :class:`SupplyChainAbortError` — a TRUE circuit breaker. The caller MUST
  NOT swallow this specific exception before its own install/build/test
  subprocess: once raised, none of the later scans/subprocesses run.
- **The ONE legitimate hard stop for "can't verify"**: if a lockfile is
  present but no offline scanner binary exists on PATH, we cannot verify the
  target's dependencies are safe, so we fail closed rather than silently
  proceeding. Every OTHER inability (scanner call errors, no lockfile at
  all, heuristic found nothing) degrades to a logged warning/info — it does
  NOT abort.
- **Generic across ecosystems**: no protocol/project-specific names. The IoC
  denylist is append-only and ships empty; it is a defense-in-depth
  complement to the offline scanner, not the primary detector.

This module owns ``SupplyChainAbortError`` for both of its call sites
(``recon_prepass.py``'s EVM dependency-install path and
``mechanical_verify.py``'s pre-test-exec path). It is deliberately narrow —
NOT a general-purpose/reusable phase-abort helper.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

log = logging.getLogger("plamen.supply_chain_gate")

__all__ = [
    "SupplyChainAbortError",
    "gate_supply_chain",
    "denylist_has_not_shrunk",
    "DEFAULT_IOC_DENYLIST",
]


class SupplyChainAbortError(Exception):
    """Raised ONLY by :func:`gate_supply_chain` when a CRITICAL/malicious
    supply-chain signal is found in the TARGET repo's dependency lockfile(s),
    or when no offline scanner binary is available to verify them at all
    (fail-closed on inability-to-verify).

    Narrow to its 2 call sites — ``recon_prepass._prepare_evm_build`` and
    ``mechanical_verify.run_phase5b_mechanical_verify`` — this is NOT a
    reusable/general phase-abort mechanism; do not raise it elsewhere.
    """


# Append-only IoC denylist of known-malicious dependency name/version
# substrings. NEVER remove an entry — shrinking this list silently un-blocks
# a previously-known-bad dependency (see `denylist_has_not_shrunk`). New
# entries may be appended freely. Ships empty: this is a defense-in-depth
# complement to the offline scanner (Signal 3 below), not the primary
# detector, and per the no-overfit rule it must stay generic — no
# protocol/contest-specific data lives here.
DEFAULT_IOC_DENYLIST: frozenset[str] = frozenset()

_LOCKFILE_NAMES = (
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
    "Cargo.lock", "soldeer.lock",
)

# Offline/local dependency-vulnerability scanners, in preference order. None
# of these are hard dependencies — `_pick_scanner_binary` degrades to "none
# found" (the one fail-closed hard stop) rather than assuming any is present.
_SCANNER_BINARIES = ("osv-scanner", "npm", "cargo")

_INSTALL_SCRIPT_KEYS = ("preinstall", "install", "postinstall")

# Obfuscated-payload shape: an eval/Function-constructor call whose argument
# chain decodes base64 (atob(...) or Buffer.from(..., 'base64')). This is a
# generic obfuscation-chain shape, not a specific package signature.
_BASE64_EVAL_RE = re.compile(
    r"(eval\s*\(|new\s+Function\s*\()\s*[^)]*"
    r"(atob\(|Buffer\.from\([^,]+,\s*['\"]base64['\"]\))",
    re.IGNORECASE,
)

_CRITICAL_RE = re.compile(r"\b(CRITICAL|MALICIOUS)\b", re.IGNORECASE)


def denylist_has_not_shrunk(previous: Iterable[str], current: Iterable[str]) -> bool:
    """Return True iff every entry in `previous` is still present in
    `current`. The denylist is append-only by policy; this is the mechanical
    check that turns "denylist-shrink = corruption" into a testable
    invariant rather than a documentation-only convention."""
    return set(previous) <= set(current)


def _find_lockfiles(root: Path) -> List[Path]:
    found: List[Path] = []
    for name in _LOCKFILE_NAMES:
        try:
            p = root / name
            if p.is_file():
                found.append(p)
        except OSError:
            continue
    return found


def _pick_scanner_binary() -> Optional[str]:
    for b in _SCANNER_BINARIES:
        if shutil.which(b):
            return b
    return None


def _call_offline_scanner(binary: str, lockfile: Path) -> str:
    """Hermetic wrapper around the offline scanner subprocess call.

    Tests monkeypatch THIS function directly rather than relying on a real
    scanner binary being installed. Never raises — a failed/absent binary
    call degrades to an empty result (no CRITICAL match), NOT an abort; the
    fail-closed "can't verify" case is handled by the caller when NO scanner
    binary is on PATH at all (see `gate_supply_chain`)."""
    if binary == "osv-scanner":
        cmd = ["osv-scanner", "--offline", "--lockfile", str(lockfile)]
    elif binary == "npm":
        cmd = ["npm", "audit", "--json", "--prefix", str(lockfile.parent)]
    elif binary == "cargo":
        cmd = ["cargo", "audit", "--json"]
    else:  # pragma: no cover - defensive, _SCANNER_BINARIES is closed
        return ""
    try:
        proc = subprocess.run(
            cmd, cwd=str(lockfile.parent), capture_output=True, text=True,
            timeout=120, shell=False,
        )
        return (proc.stdout or "") + "\n" + (proc.stderr or "")
    except Exception as exc:
        log.warning("supply_chain_gate: scanner call failed (%s on %s): %s",
                    binary, lockfile, exc)
        return ""


def _denylist_hit(text: str, denylist: Iterable[str]) -> Optional[str]:
    for entry in denylist:
        if entry and entry in text:
            return entry
    return None


def _install_script_heuristic_hit(root: Path) -> Optional[str]:
    """Offline, no-network heuristic: flag pre/post/install script hooks
    combined with a base64+eval-style obfuscation chain in the TARGET repo's
    own manifest files. Best-effort — a miss here does not weaken the other
    signals; a hit fail-closed aborts."""
    for name in ("package.json", "package-lock.json"):
        p = root / name
        try:
            if not p.is_file():
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if _BASE64_EVAL_RE.search(text):
            return f"base64/eval obfuscation chain in {name}"
        has_install_hook = any(f'"{k}"' in text for k in _INSTALL_SCRIPT_KEYS)
        if has_install_hook and "base64" in text.lower() and (
            "eval(" in text or "Function(" in text
        ):
            return f"install-script hook + base64/eval in {name}"
    return None


def gate_supply_chain(root: Path, *, denylist: Optional[Sequence[str]] = None) -> None:
    """Fail-closed pre-exec safety gate.

    Call BEFORE any subprocess that installs/builds/tests dependencies
    resolved from the (untrusted) TARGET repo. This is a TRUE circuit
    breaker: on any fail-closed condition it raises immediately, before
    later signals are even checked, and the caller must let that exception
    prevent the guarded subprocess from running.

    Raises :class:`SupplyChainAbortError` when:
      - an append-only IoC denylist entry matches a found lockfile, OR
      - the install-script/base64 heuristic fires, OR
      - the offline scanner reports a CRITICAL/malicious finding, OR
      - lockfile(s) are present but NO offline scanner binary exists on
        PATH at all (fail-closed on inability-to-verify — the one
        legitimate "can't check" hard stop).

    Everything else (no lockfiles at all, a scanner call itself failing,
    heuristic finding nothing) degrades to a logged message and returns
    normally — never a silent no-op, always logged.

    Env override: ``PLAMEN_SKIP_SUPPLY_CHAIN_GATE=1`` disables the gate
    entirely (explicit opt-out for trusted/offline dev environments — never
    the default, and always logged when used).
    """
    if os.environ.get("PLAMEN_SKIP_SUPPLY_CHAIN_GATE") == "1":
        log.warning("supply_chain_gate: SKIPPED via PLAMEN_SKIP_SUPPLY_CHAIN_GATE=1 "
                     "for %s", root)
        return

    active_denylist = tuple(denylist) if denylist is not None else tuple(DEFAULT_IOC_DENYLIST)
    root = Path(root)
    lockfiles = _find_lockfiles(root)

    # --- Signal 1: append-only IoC denylist (no binary required) ----------
    for lf in lockfiles:
        try:
            text = lf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        hit = _denylist_hit(text, active_denylist)
        if hit:
            log.error("supply_chain_gate: denylisted IoC %r found in %s", hit, lf)
            raise SupplyChainAbortError(
                f"supply-chain gate: denylisted dependency IoC {hit!r} found in "
                f"{lf}. Aborting before install/build/test — fail-closed."
            )

    # --- Signal 2: install-script + base64/eval heuristic (no binary) -----
    heuristic_hit = _install_script_heuristic_hit(root)
    if heuristic_hit:
        log.error("supply_chain_gate: install-script heuristic fired (%s) in %s",
                   heuristic_hit, root)
        raise SupplyChainAbortError(
            f"supply-chain gate: suspicious install-script heuristic fired "
            f"({heuristic_hit}) under {root}. Aborting before "
            "install/build/test — fail-closed."
        )

    # --- Signal 3: offline dependency-vulnerability scanner ---------------
    if not lockfiles:
        log.info("supply_chain_gate: no lockfile found under %s — scanner step "
                  "skipped (nothing to verify)", root)
        return

    binary = _pick_scanner_binary()
    if binary is None:
        # The ONE legitimate hard stop: dependencies exist but cannot be
        # verified at all.
        log.error(
            "supply_chain_gate: %d lockfile(s) present under %s but no offline "
            "scanner binary is on PATH (tried %s) — cannot verify target "
            "dependencies. Fail-closed.",
            len(lockfiles), root, ", ".join(_SCANNER_BINARIES),
        )
        raise SupplyChainAbortError(
            "supply-chain gate: no offline scanner binary available "
            f"(tried {', '.join(_SCANNER_BINARIES)}) — cannot verify target "
            f"dependencies under {root} are safe to install/build/test. "
            "Fail-closed."
        )

    for lf in lockfiles:
        output = _call_offline_scanner(binary, lf)
        if _CRITICAL_RE.search(output):
            log.error("supply_chain_gate: %s reported a CRITICAL/malicious "
                       "finding for %s", binary, lf)
            raise SupplyChainAbortError(
                f"supply-chain gate: {binary} reported a CRITICAL/malicious "
                f"finding for {lf}. Aborting before install/build/test — "
                "fail-closed."
            )

    log.info("supply_chain_gate: clean (%d lockfile(s) scanned via %s under %s)",
              len(lockfiles), binary, root)
