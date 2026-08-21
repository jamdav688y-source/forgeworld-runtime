"""Focused tests for capabilities/discover.py command verification.

These tests exist to prove one thing: a "command" capability check must
not be considered reachable merely because path resolution found *something*
on PATH. On Windows, an inert Microsoft Store execution alias satisfies
shutil.which() while doing nothing useful when actually launched -- these
tests pin down the fix for that, and guard against regressing the weaker
(path-only) behavior still used by capabilities that declare no "verify"
spec (git, ollama, claude), and Termux/Linux command probes generally.
"""
import os
import stat
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import discover  # noqa: E402


IS_WINDOWS = sys.platform == "win32"
# Derived from environment, not hardcoded to a specific account: any
# Windows user with the same per-user CPython install / Store alias
# layout satisfies these, and no username is embedded in this file.
_LOCALAPPDATA = Path(os.environ.get("LOCALAPPDATA", ""))
REAL_PYTHON_ON_THIS_MACHINE = _LOCALAPPDATA / "Programs" / "Python" / "Python312" / "python.exe"
STORE_ALIAS_ON_THIS_MACHINE = _LOCALAPPDATA / "Microsoft" / "WindowsApps" / "python3.exe"

PYTHON_VERIFY_SPEC = {
    "args": ["--version"],
    "timeout_seconds": 5,
    "expect_identity": r"Python \d+\.\d+\.\d+",
    "min_version": "3.8",
}


class _FakeCompleted:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _make_fake_tool(directory: Path, output: str, exit_code: int = 0, sleep_seconds: float = 0.0, name: str = "fake_tool"):
    """Write a tiny OS-native script that prints `output` and exits `exit_code`.

    Uses .bat on Windows and a shebang'd, chmod +x shell script on
    everything else (Termux/Linux/macOS), so the same test logic exercises
    a real, directly-executed command on every platform.
    """
    directory.mkdir(parents=True, exist_ok=True)
    if IS_WINDOWS:
        script = directory / f"{name}.bat"
        lines = ["@echo off"]
        if sleep_seconds:
            # "timeout" requires a console and fails instantly under
            # redirected stdio (as subprocess.run uses); "ping" is the
            # standard portable no-console sleep trick on Windows.
            lines.append(f"ping -n {max(2, int(sleep_seconds) + 1)} 127.0.0.1 >nul")
        for line in output.splitlines():
            lines.append(f"echo {line}")
        lines.append(f"exit /b {exit_code}")
        script.write_text("\r\n".join(lines) + "\r\n")
        return script

    script = directory / name
    lines = ["#!/bin/sh"]
    if sleep_seconds:
        lines.append(f"sleep {sleep_seconds}")
    for line in output.splitlines():
        lines.append(f"echo '{line}'")
    lines.append(f"exit {exit_code}")
    script.write_text("\n".join(lines) + "\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return script


# 1. Existing executable with correct identity is verified.
def test_correct_identity_and_version_is_verified(tmp_path):
    tool = _make_fake_tool(tmp_path, "Python 9.9.9", exit_code=0)
    confidence, level, evidence = discover._probe_resolved(str(tool), PYTHON_VERIFY_SPEC)
    assert level == "VERSION_VERIFIED"
    assert confidence == 1.0
    assert "9, 9, 9" in evidence or "(9, 9, 9)" in evidence


# 2. Path exists but launch fails -> not reachable.
def test_launch_failure_is_unreachable(tmp_path):
    broken = tmp_path / "broken_tool"
    broken.write_text("this is not a real executable\n")
    # Deliberately NOT marked executable / not a valid binary format.
    confidence, level, evidence = discover._probe_resolved(str(broken), PYTHON_VERIFY_SPEC)
    assert level in {"UNREACHABLE", "TIMEOUT"}
    assert confidence == 0.0


# 3. Launch succeeds but identity is wrong -> not the requested capability.
def test_wrong_identity_is_mismatch(tmp_path):
    tool = _make_fake_tool(tmp_path, "NotPython 1.0", exit_code=0)
    confidence, level, evidence = discover._probe_resolved(str(tool), PYTHON_VERIFY_SPEC)
    assert level == "IDENTITY_MISMATCH"
    assert confidence == 0.0


# 4. Probe times out -> not reachable.
def test_timeout_is_not_reachable(tmp_path):
    tool = _make_fake_tool(tmp_path, "Python 9.9.9", exit_code=0, sleep_seconds=2)
    spec = dict(PYTHON_VERIFY_SPEC, timeout_seconds=0.3)
    confidence, level, evidence = discover._probe_resolved(str(tool), spec)
    assert level == "TIMEOUT"
    assert confidence == 0.0


# 5. Output may appear on stdout or stderr.
def test_identity_on_stderr_is_still_recognized(tmp_path):
    tool = _make_fake_tool(tmp_path, "Python 9.9.9", exit_code=0)
    # Route the fake tool's own stdout into evidence by checking a variant
    # that writes to stderr via the shell/batch redirection primitive.
    if IS_WINDOWS:
        tool.write_text("@echo off\r\necho Python 9.9.9 1>&2\r\nexit /b 0\r\n")
    else:
        tool.write_text("#!/bin/sh\necho 'Python 9.9.9' >&2\nexit 0\n")
        tool.chmod(tool.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    confidence, level, evidence = discover._probe_resolved(str(tool), PYTHON_VERIFY_SPEC)
    assert level == "VERSION_VERIFIED"
    assert confidence == 1.0


# 6. Version below declared minimum -> not version-verified.
def test_version_below_minimum_is_not_version_verified(tmp_path):
    tool = _make_fake_tool(tmp_path, "Python 2.7.18", exit_code=0)
    confidence, level, evidence = discover._probe_resolved(str(tool), PYTHON_VERIFY_SPEC)
    assert level != "VERSION_VERIFIED"
    assert level == "IDENTITY_VERIFIED"  # identity matched; version gate failed
    assert confidence == 0.0


# 7. Paths containing spaces work.
def test_path_with_spaces_is_handled(tmp_path):
    spaced_dir = tmp_path / "dir with space in it"
    tool = _make_fake_tool(spaced_dir, "Python 9.9.9", exit_code=0)
    assert " " in str(tool)
    confidence, level, evidence = discover._probe_resolved(str(tool), PYTHON_VERIFY_SPEC)
    assert level == "VERSION_VERIFIED"
    assert confidence == 1.0


# 8. Probe arguments are passed as an argument list, never through shell interpolation.
def test_arguments_passed_as_list_not_shell_string(monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _FakeCompleted(returncode=0, stdout="Python 9.9.9", stderr="")

    monkeypatch.setattr(discover.subprocess, "run", fake_run)
    dangerous_arg = "print('Python 9.9.9'); this ; is & not | a `shell` $(command)"
    confidence, level, evidence = discover._probe_resolved(
        "/fake/path/python", {"args": ["-c", dangerous_arg], "expect_identity": r"Python \d+\.\d+\.\d+"}
    )
    assert isinstance(captured["cmd"], list)
    assert captured["cmd"][0] == "/fake/path/python"
    assert captured["cmd"][-1] == dangerous_arg  # passed intact as one argument, not parsed/split
    assert captured["kwargs"].get("shell") is not True
    assert level == "IDENTITY_VERIFIED"


# 9. Termux/Linux behavior remains compatible through procedural fixtures.
def test_procedural_fixture_matches_platform_native_command_style(tmp_path):
    # Exercises the same shebang/chmod(+x) execution style Termux/Linux
    # command probes use (git, ollama, claude), via the OS-native fixture
    # helper rather than a Python-specific "-c" invocation.
    tool = _make_fake_tool(tmp_path, "Python 9.9.9", exit_code=0, name="git_like_tool")
    confidence, level, evidence = discover._probe_resolved(str(tool), PYTHON_VERIFY_SPEC)
    assert level == "VERSION_VERIFIED"
    assert confidence == 1.0


# 10. Actual Windows Store Python alias is no longer reported as verified Python.
@pytest.mark.skipif(
    not (IS_WINDOWS and STORE_ALIAS_ON_THIS_MACHINE.exists()),
    reason="Windows Store python3 alias not present on this machine/platform",
)
def test_real_windows_store_alias_is_rejected():
    confidence, level, evidence = discover._probe_resolved(
        str(STORE_ALIAS_ON_THIS_MACHINE), PYTHON_VERIFY_SPEC
    )
    assert confidence == 0.0
    assert level == "UNREACHABLE"


# 11. Actual installed CPython 3.12.10 is reported with correct identity and version.
@pytest.mark.skipif(
    not (IS_WINDOWS and REAL_PYTHON_ON_THIS_MACHINE.exists()),
    reason="Real per-user CPython install not present on this machine/platform",
)
def test_real_installed_cpython_is_verified():
    confidence, level, evidence = discover._probe_resolved(
        str(REAL_PYTHON_ON_THIS_MACHINE), PYTHON_VERIFY_SPEC
    )
    assert confidence == 1.0
    assert level == "VERSION_VERIFIED"
    assert "3, 12, 10" in evidence or "(3, 12, 10)" in evidence


# --- Wrapper-level regression coverage: _verify_command() and probe_one()/probe_all() ---

def test_command_not_found_on_path_is_unreachable():
    confidence, level, evidence = discover._verify_command(
        "definitely_not_a_real_command_xyz123", None
    )
    assert confidence == 0.0
    assert level == "UNREACHABLE"
    assert "not found on PATH" in evidence


def test_command_without_verify_spec_preserves_old_path_found_behavior(monkeypatch):
    # Capabilities that declare no "verify" (git, ollama, claude) must keep
    # their original, weaker path-only semantics unchanged.
    monkeypatch.setattr(discover.shutil, "which", lambda value: "/usr/bin/git")
    confidence, level, evidence = discover._verify_command("git", None)
    assert confidence == 1.0
    assert level == "PATH_FOUND"
    assert "path-only check" in evidence


def test_probe_one_command_returns_level_others_do_not():
    confidence, evidence, level = discover.probe_one({"type": "self"})
    assert level is None  # non-command modes must remain unchanged

    confidence, evidence, level = discover.probe_one(
        {"type": "command", "value": "definitely_not_a_real_command_xyz123"}
    )
    assert level == "UNREACHABLE"


def test_probe_all_only_adds_evidence_level_for_command_checks():
    results = discover.probe_all()
    assert "evidence_level" in results["python"]
    assert "evidence_level" in results["git"]
    assert "evidence_level" not in results["desktop_runtime"]  # self
    assert "evidence_level" not in results["chatgpt"]  # env
    assert "evidence_level" not in results["github"]  # network
    assert "evidence_level" not in results["zapier"]  # manual
    # Router-consumed keys must still be present and typed as before.
    for cap_id, entry in results.items():
        assert isinstance(entry["reachability_confidence"], float)
        assert isinstance(entry["evidence"], str)
