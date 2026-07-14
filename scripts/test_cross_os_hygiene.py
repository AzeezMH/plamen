"""Mechanical cross-OS hygiene gate.

This replaces the recurring MANUAL "sweep the repo for Windows-breaking
patterns" audit with an always-on static test. The Windows-breaking bug this
was written after (and had already been fixed twice before this gate
existed): a `subprocess.run(..., text=True)` call with no explicit
`encoding=` kwarg. On Windows, Python's default text-mode decode falls back
to the console's active code page (commonly cp1252), not UTF-8 — so any
non-ASCII byte in a child process's stdout/stderr raises
`UnicodeDecodeError` there while working fine on Linux/macOS. The same class
of bug applies to `open()` / `Path.read_text()` / `Path.write_text()` calls
that omit `encoding=`.

Every `scripts/*.py` file (excluding `test_*.py` and `__pycache__`) is parsed
with `ast` and checked for four anti-patterns:

  1. `subprocess.run/Popen/check_output/check_call` called with `text=True`
     or `universal_newlines=True` but no `encoding=` kwarg. (A bytes-mode
     call — no `text=True` at all — is fine and not flagged.)
  2. `open(...)` / `Path.read_text(...)` / `Path.write_text(...)` in text
     mode with no `encoding=` kwarg. Binary modes (any mode string
     containing `"b"`) are exempt — there is no text decoding to break.
  3. An unguarded top-level `import pty|fcntl|termios` (Unix-only stdlib
     modules) or an unguarded `os.fork(` call. "Guarded" means nested
     inside a function/`try`/`if sys.platform ...`/`if os.name ...` block
     rather than sitting bare at module top level.
  4. A literal `"python3"` hardcoded as the executable in a subprocess
     command (should be `sys.executable`, a platform-aware lookup, or the
     bare `"python"` launcher — Windows installers do not ship
     `python3.exe` by default).

Calls whose relevant keyword arguments are only knowable at runtime (a
`**kwargs` splat, or a dynamically computed mode string) are treated as
*unknowable* and skipped rather than false-flagged — precision over recall
for this gate, since a static analyzer cannot see inside an opaque dict.

Violations are asserted to be empty, modulo the explicit ALLOWLIST below.
The allowlist exists so a reviewer can see, in one place, exactly which
(rule, file, line) combinations are waived and why — it is not a place to
quietly hide new violations; `test_allowlist_has_no_stale_entries` fails the
suite if an allowlisted line stops matching (so the entry must be removed
when the underlying code is fixed).
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import NamedTuple

SCRIPTS_DIR = Path(__file__).resolve().parent

_SUBPROCESS_CALL_NAMES = {"run", "Popen", "check_output", "check_call"}
_UNIX_ONLY_MODULES = {"pty", "fcntl", "termios"}

RULE_SUBPROCESS_TEXT = "subprocess-text-no-encoding"
RULE_OPEN_NO_ENCODING = "open-no-encoding"
RULE_UNGUARDED_UNIX_IMPORT = "unguarded-unix-only-import"
RULE_HARDCODED_PYTHON3 = "hardcoded-python3-interpreter"


class Violation(NamedTuple):
    rule: str
    file: str  # bare filename, e.g. "supply_chain_gate.py" (scripts/ is flat)
    line: int
    snippet: str


# ---------------------------------------------------------------------------
# ALLOWLIST
#
# Real, pre-existing, low-risk cases found when this gate was first written.
# Each is a genuine hit of the stated rule (NOT a detector false positive —
# those are handled by tightening the detector itself, not by allowlisting).
# They are called out here, and in the tool's report, rather than fixed
# in-place because fixing them touches files outside this gate's own scope.
# ---------------------------------------------------------------------------
# Empty by design: every violation the gate surfaced in the live tree was
# FIXED in-place (encoding= added to supply_chain_gate.py's scanner subprocess
# and the retry-counter read_text() calls in plamen_driver.py / plamen_validators.py)
# rather than suppressed. A non-empty allowlist should be a last resort for a
# genuinely-unfixable, intentional case — never a parking lot for real bugs.
ALLOWLIST: dict[tuple[str, str, int], str] = {}


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def _has_starstar_kwargs(call: ast.Call) -> bool:
    """True if the call splats an unknowable **kwargs dict."""
    return any(kw.arg is None for kw in call.keywords)


def _keyword(call: ast.Call, name: str) -> ast.expr | None:
    for kw in call.keywords:
        if kw.arg == name:
            return kw.value
    return None


def _is_true_constant(node: ast.expr | None) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _str_constant(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _subprocess_aliases(tree: ast.Module) -> tuple[set[str], dict[str, str]]:
    """Resolve local names bound to the subprocess module or its functions.

    Returns (module_aliases, bare_names): module_aliases covers
    `import subprocess [as x]`; bare_names maps a local name to the
    canonical subprocess function it refers to for
    `from subprocess import run [as x]`.
    """
    module_aliases: set[str] = set()
    bare_names: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "subprocess":
                    module_aliases.add(alias.asname or alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module == "subprocess":
                for alias in node.names:
                    if alias.name in _SUBPROCESS_CALL_NAMES:
                        bare_names[alias.asname or alias.name] = alias.name
    return module_aliases, bare_names


def _is_subprocess_call(
    call: ast.Call, module_aliases: set[str], bare_names: dict[str, str]
) -> bool:
    func = call.func
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return func.value.id in module_aliases and func.attr in _SUBPROCESS_CALL_NAMES
    if isinstance(func, ast.Name):
        return func.id in bare_names
    return False


def _build_parent_map(tree: ast.Module) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    return parents


def _is_platform_guarded(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    """True if `node` sits inside a try/except or a sys.platform/os.name if.

    Being merely nested inside a function is deliberately NOT treated as a
    guard: a function that unconditionally calls `os.fork()` still crashes
    the instant something on Windows calls that function. Only an actual
    `try/except` (which can catch the resulting AttributeError) or an
    `if sys.platform ...` / `if os.name ...` branch counts.
    """
    current = parents.get(node)
    while current is not None:
        if isinstance(current, ast.Try):
            return True
        if isinstance(current, ast.If):
            dumped = ast.dump(current.test)
            if "platform" in dumped or ("id='os'" in dumped and "attr='name'" in dumped):
                return True
        current = parents.get(current)
    return False


# ---------------------------------------------------------------------------
# Rule 1: subprocess text=True / universal_newlines=True without encoding=
# ---------------------------------------------------------------------------

def _find_subprocess_text_violations(tree: ast.Module) -> list[ast.Call]:
    module_aliases, bare_names = _subprocess_aliases(tree)
    hits: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not _is_subprocess_call(node, module_aliases, bare_names):
            continue
        if _has_starstar_kwargs(node):
            continue  # encoding= may be hiding inside the splat — unknowable
        text_kw = _keyword(node, "text")
        newlines_kw = _keyword(node, "universal_newlines")
        if not (_is_true_constant(text_kw) or _is_true_constant(newlines_kw)):
            continue
        if _keyword(node, "encoding") is not None:
            continue
        hits.append(node)
    return hits


# ---------------------------------------------------------------------------
# Rule 2: open()/read_text()/write_text() text mode without encoding=
# ---------------------------------------------------------------------------

def _find_open_mode_violations(tree: ast.Module) -> list[ast.Call]:
    hits: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func

        if isinstance(func, ast.Name) and func.id == "open":
            if _has_starstar_kwargs(node):
                continue
            mode_node: ast.expr | None = None
            if len(node.args) >= 2:
                mode_node = node.args[1]
            else:
                mode_kw = _keyword(node, "mode")
                if mode_kw is not None:
                    mode_node = mode_kw
            if mode_node is not None:
                mode_str = _str_constant(mode_node)
                if mode_str is None:
                    continue  # dynamic mode expression — unknowable, skip
                if "b" in mode_str:
                    continue  # binary mode — no text decode to break
            if _keyword(node, "encoding") is not None:
                continue
            hits.append(node)

        elif isinstance(func, ast.Attribute) and func.attr in ("read_text", "write_text"):
            if _has_starstar_kwargs(node):
                continue
            has_kw_encoding = _keyword(node, "encoding") is not None
            # write_text(data, encoding=None, ...) -> encoding is the 2nd
            # positional slot; read_text(encoding=None, ...) -> the 1st.
            min_positional_for_encoding = 2 if func.attr == "write_text" else 1
            if has_kw_encoding or len(node.args) >= min_positional_for_encoding:
                continue
            hits.append(node)

    return hits


# ---------------------------------------------------------------------------
# Rule 3: unguarded top-level Unix-only import, or unguarded os.fork()
# ---------------------------------------------------------------------------

def _find_unguarded_unix_import_violations(tree: ast.Module) -> list[ast.AST]:
    hits: list[ast.AST] = []
    # Top-level only: anything nested inside a function/if/try body is, by
    # definition, not a bare top-level import and does not appear directly
    # in tree.body.
    for node in tree.body:
        if isinstance(node, ast.Import):
            if any(alias.name in _UNIX_ONLY_MODULES for alias in node.names):
                hits.append(node)
        elif isinstance(node, ast.ImportFrom):
            if node.module in _UNIX_ONLY_MODULES:
                hits.append(node)

    parents = _build_parent_map(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "fork"
                and isinstance(func.value, ast.Name)
                and func.value.id == "os"
                and not _is_platform_guarded(node, parents)
            ):
                hits.append(node)

    return hits


# ---------------------------------------------------------------------------
# Rule 4: hardcoded "python3" interpreter in a subprocess command
# ---------------------------------------------------------------------------

def _find_hardcoded_python3_violations(tree: ast.Module) -> list[ast.Call]:
    module_aliases, bare_names = _subprocess_aliases(tree)
    hits: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not _is_subprocess_call(node, module_aliases, bare_names):
            continue
        if not node.args:
            continue
        cmd_arg = node.args[0]
        if isinstance(cmd_arg, (ast.List, ast.Tuple)) and cmd_arg.elts:
            first = cmd_arg.elts[0]
            if isinstance(first, ast.Constant) and first.value == "python3":
                hits.append(node)
        else:
            cmd_str = _str_constant(cmd_arg)
            if cmd_str is not None:
                first_token = cmd_str.strip().split(maxsplit=1)[:1]
                if first_token and first_token[0] == "python3":
                    hits.append(node)
    return hits


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def _iter_target_files() -> list[Path]:
    return sorted(
        p
        for p in SCRIPTS_DIR.glob("*.py")
        if not p.name.startswith("test_") and p.name != "__pycache__"
    )


def _snippet(source_lines: list[str], lineno: int, width: int = 100) -> str:
    if 1 <= lineno <= len(source_lines):
        text = source_lines[lineno - 1].strip()
    else:
        text = "<line unavailable>"
    return text if len(text) <= width else text[: width - 3] + "..."


def _scan_file(path: Path) -> list[Violation]:
    source = path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(source, filename=str(path))
    lines = source.splitlines()

    checks: list[tuple[str, list[ast.AST]]] = [
        (RULE_SUBPROCESS_TEXT, _find_subprocess_text_violations(tree)),
        (RULE_OPEN_NO_ENCODING, _find_open_mode_violations(tree)),
        (RULE_UNGUARDED_UNIX_IMPORT, _find_unguarded_unix_import_violations(tree)),
        (RULE_HARDCODED_PYTHON3, _find_hardcoded_python3_violations(tree)),
    ]

    violations: list[Violation] = []
    for rule, nodes in checks:
        for node in nodes:
            violations.append(
                Violation(
                    rule=rule,
                    file=path.name,
                    line=node.lineno,
                    snippet=_snippet(lines, node.lineno),
                )
            )
    return violations


def _scan_tree() -> list[Violation]:
    all_violations: list[Violation] = []
    for path in _iter_target_files():
        all_violations.extend(_scan_file(path))
    return all_violations


def _is_allowlisted(v: Violation) -> bool:
    return (v.rule, v.file, v.line) in ALLOWLIST


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------

def test_no_unallowlisted_cross_os_hygiene_violations() -> None:
    violations = _scan_tree()
    unallowlisted = [v for v in violations if not _is_allowlisted(v)]
    if unallowlisted:
        lines = [
            f"  [{v.rule}] {v.file}:{v.line}: {v.snippet}" for v in unallowlisted
        ]
        raise AssertionError(
            "Cross-OS hygiene gate found "
            f"{len(unallowlisted)} unallowlisted violation(s):\n"
            + "\n".join(lines)
            + "\n\nEither fix the offending code, or — if this is a genuinely "
            "intentional/low-risk case — add a justified entry to ALLOWLIST "
            "in scripts/test_cross_os_hygiene.py."
        )


def test_allowlist_has_no_stale_entries() -> None:
    """Every ALLOWLIST entry must still correspond to a real detected hit.

    Prevents the allowlist from silently rotting into a dead sink that no
    longer describes the tree — once a listed line is fixed, the entry must
    be deleted along with it.
    """
    violations = _scan_tree()
    live_keys = {(v.rule, v.file, v.line) for v in violations}
    stale = [key for key in ALLOWLIST if key not in live_keys]
    assert not stale, (
        "Stale ALLOWLIST entries no longer match any detected violation "
        f"(remove them): {stale}"
    )


# ---------------------------------------------------------------------------
# Self-tests: prove the detector actually fires on bad code and stays quiet
# on good code, so the gate above is trustworthy.
# ---------------------------------------------------------------------------

_BAD_SUBPROCESS_SNIPPET = """
import subprocess

def run_it(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=5)
"""

_GOOD_SUBPROCESS_SNIPPET = """
import subprocess

def run_it(cmd):
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=5,
    )
"""

_SPLAT_SUBPROCESS_SNIPPET = """
import subprocess

def run_it(cmd, **kw):
    return subprocess.run(cmd, **kw)
"""

_BAD_OPEN_SNIPPET = """
def load(path):
    with open(path) as f:
        return f.read()
"""

_GOOD_OPEN_SNIPPET = """
def load(path):
    with open(path, encoding="utf-8") as f:
        return f.read()
"""

_BAD_READ_TEXT_SNIPPET = """
from pathlib import Path

def load(p: Path):
    return p.read_text()
"""

_GOOD_READ_TEXT_SNIPPET = """
from pathlib import Path

def load(p: Path):
    return p.read_text(encoding="utf-8")
"""

_BAD_BINARY_OPEN_IS_FINE_SNIPPET = """
def load(path):
    with open(path, "rb") as f:
        return f.read()
"""

_BAD_UNGUARDED_IMPORT_SNIPPET = """
import termios

def restore(fd):
    termios.tcsetattr(fd, 0, [])
"""

_GOOD_GUARDED_IMPORT_SNIPPET = """
import sys

def restore(fd):
    if sys.platform != "win32":
        import termios
        termios.tcsetattr(fd, 0, [])
"""

_BAD_UNGUARDED_FORK_SNIPPET = """
import os

def spawn_child():
    pid = os.fork()
    return pid
"""

_GOOD_GUARDED_FORK_SNIPPET = """
import os
import sys

def spawn_child():
    if sys.platform != "win32":
        pid = os.fork()
        return pid
    return None
"""

_BAD_HARDCODED_PYTHON3_SNIPPET = """
import subprocess

def run_driver(script):
    return subprocess.run(["python3", script])
"""

_GOOD_SYS_EXECUTABLE_SNIPPET = """
import subprocess
import sys

def run_driver(script):
    return subprocess.run([sys.executable, script])
"""


def _rule_hits(source: str, finder) -> list[ast.AST]:
    return finder(ast.parse(source))


def test_detector_fires_on_bad_subprocess_text_snippet() -> None:
    assert _rule_hits(_BAD_SUBPROCESS_SNIPPET, _find_subprocess_text_violations)


def test_detector_passes_on_good_subprocess_text_snippet() -> None:
    assert not _rule_hits(_GOOD_SUBPROCESS_SNIPPET, _find_subprocess_text_violations)


def test_detector_skips_unknowable_kwargs_splat() -> None:
    assert not _rule_hits(_SPLAT_SUBPROCESS_SNIPPET, _find_subprocess_text_violations)


def test_detector_fires_on_bad_open_snippet() -> None:
    assert _rule_hits(_BAD_OPEN_SNIPPET, _find_open_mode_violations)


def test_detector_passes_on_good_open_snippet() -> None:
    assert not _rule_hits(_GOOD_OPEN_SNIPPET, _find_open_mode_violations)


def test_detector_fires_on_bad_read_text_snippet() -> None:
    assert _rule_hits(_BAD_READ_TEXT_SNIPPET, _find_open_mode_violations)


def test_detector_passes_on_good_read_text_snippet() -> None:
    assert not _rule_hits(_GOOD_READ_TEXT_SNIPPET, _find_open_mode_violations)


def test_detector_ignores_binary_mode_open() -> None:
    assert not _rule_hits(_BAD_BINARY_OPEN_IS_FINE_SNIPPET, _find_open_mode_violations)


def test_detector_fires_on_unguarded_unix_import() -> None:
    assert _rule_hits(
        _BAD_UNGUARDED_IMPORT_SNIPPET, _find_unguarded_unix_import_violations
    )


def test_detector_passes_on_guarded_unix_import() -> None:
    assert not _rule_hits(
        _GOOD_GUARDED_IMPORT_SNIPPET, _find_unguarded_unix_import_violations
    )


def test_detector_fires_on_unguarded_fork_even_inside_a_function() -> None:
    # Regression guard: nesting inside a function must NOT be treated as a
    # platform guard by itself, or this rule would never fire in practice.
    assert _rule_hits(
        _BAD_UNGUARDED_FORK_SNIPPET, _find_unguarded_unix_import_violations
    )


def test_detector_passes_on_platform_guarded_fork() -> None:
    assert not _rule_hits(
        _GOOD_GUARDED_FORK_SNIPPET, _find_unguarded_unix_import_violations
    )


def test_detector_fires_on_hardcoded_python3() -> None:
    assert _rule_hits(
        _BAD_HARDCODED_PYTHON3_SNIPPET, _find_hardcoded_python3_violations
    )


def test_detector_passes_on_sys_executable() -> None:
    assert not _rule_hits(
        _GOOD_SYS_EXECUTABLE_SNIPPET, _find_hardcoded_python3_violations
    )


def test_target_file_discovery_excludes_tests_and_pycache() -> None:
    files = _iter_target_files()
    assert files, "expected at least one non-test scripts/*.py file"
    assert all(not p.name.startswith("test_") for p in files)
    assert all(p.name != "__pycache__" for p in files)
    assert Path(__file__).resolve() not in files
