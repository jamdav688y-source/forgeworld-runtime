"""Permanent regression tests for the test-only audit guard
(MISSION: FW-PHASE-1B-TCP-LOOPBACK-001).

Background: during FW-PHASE-1-HARDENING-001 a syntax error in a draft guard
was silently skipped by Python's sitecustomize mechanism, so a canary ran
unguarded. The guard now fails closed: these tests prove that a guard that
cannot install -- broken code, missing or invalid configuration -- stops the
child with exit code 97 before it can produce any side effect, and that an
installed tcp_loopback guard enforces the endpoint policy in a child process.

Every child here runs tests/harness/canary_child.py with an explicit,
self-contained guard environment, so these tests do not depend on the guard
of the process running them.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parent
REPO_ROOT = HARNESS_DIR.parent.parent
CANARY = HARNESS_DIR / "canary_child.py"
PROXY_STYLE_DENIED_PORT = "39293"


class _GuardChildTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.marker = self.root / "side_effect_marker"
        self.log = self.root / "child_guard.jsonl"
        self.registry = self.root / "endpoints.jsonl"

    def tearDown(self):
        self._tmp.cleanup()

    def guard_env(self, harness_dir=HARNESS_DIR, **overrides):
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": str(self.root),
            "TMPDIR": str(self.root),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": f"{harness_dir}:{REPO_ROOT}",
            "FW_GUARD": "1",
            "FW_GUARD_LOG": str(self.log),
            "FW_GUARD_WRITE_ROOTS": str(self.root),
            "FW_GUARD_NET": "tcp_loopback",
            "FW_GUARD_ENDPOINT_REGISTRY": str(self.registry),
            "FW_GUARD_DENY_PORTS": PROXY_STYLE_DENIED_PORT,
        }
        for key, value in overrides.items():
            if value is None:
                env.pop(key, None)
            else:
                env[key] = value
        return env

    def run_canary(self, scenario, env, *args):
        return subprocess.run([sys.executable, str(CANARY), scenario, *args],
                              env=env, capture_output=True, text=True, timeout=60)

    def assert_failed_closed(self, proc):
        self.assertEqual(proc.returncode, 97, proc.stdout + proc.stderr)
        self.assertIn("FW AUDIT GUARD INSTALL FAILED", proc.stderr)
        self.assertFalse(self.marker.exists(), "child produced a side effect before the guard failed")
        self.assertEqual(proc.stdout, "")


class TestGuardFailsClosed(_GuardChildTestCase):
    def test_g1_broken_guard_code_exits_97_before_any_side_effect(self):
        broken = self.root / "broken_harness"
        shutil.copytree(HARNESS_DIR, broken, ignore=shutil.ignore_patterns("__pycache__"))
        with open(broken / "audit_guard.py", "a", encoding="utf-8") as f:
            f.write("\nthis is not valid python(\n")
        self.assert_failed_closed(self.run_canary("marker", self.guard_env(harness_dir=broken), str(self.marker)))

    def test_g2_missing_required_configuration_exits_97(self):
        for missing in ("FW_GUARD_LOG", "FW_GUARD_WRITE_ROOTS", "FW_GUARD_NET", "FW_GUARD_ENDPOINT_REGISTRY"):
            with self.subTest(missing=missing):
                env = self.guard_env(**{missing: None})
                self.assert_failed_closed(self.run_canary("marker", env, str(self.marker)))

    def test_g3_invalid_network_mode_exits_97(self):
        env = self.guard_env(FW_GUARD_NET="anything_goes")
        self.assert_failed_closed(self.run_canary("marker", env, str(self.marker)))


class TestTcpLoopbackPolicyInChild(_GuardChildTestCase):
    def test_g4_child_enforces_endpoint_policy(self):
        outside = self.root.parent / f"fw_guard_outside_{os.getpid()}"
        proc = self.run_canary("tcp", self.guard_env(), str(outside))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout.strip().splitlines()[-1])
        expected_blocked = (
            "af_inet6", "af_unix", "dns_name", "bind_nonzero_port", "bind_wildcard",
            "connect_unregistered", "connect_denied_port", "connect_dead_creator",
            "connect_after_close", "subprocess_unapproved", "os_system", "write_outside",
            "layer_state_closed_record", "layer_creator_dead", "layer_kernel_not_listening",
        )
        for key in expected_blocked:
            self.assertEqual(result[key], "BLOCKED", key)
        self.assertEqual(result["connect_active_endpoint"], "ALLOWED")
        self.assertEqual(result["round_trip"], "OK")
        self.assertFalse(outside.exists())

    def test_g5_child_logs_installation_and_endpoint_lifecycle(self):
        proc = self.run_canary("tcp", self.guard_env(), str(self.root.parent / "unused"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        records = [json.loads(line) for line in self.log.read_text().splitlines()]
        installs = [r for r in records if "guard_installed" in r]
        self.assertEqual(len(installs), 1)
        self.assertEqual(installs[0]["net"], "tcp_loopback")
        child_pid = installs[0]["pid"]
        lifecycle = [json.loads(line) for line in self.registry.read_text().splitlines()
                     if json.loads(line).get("pid") == child_pid]
        # three live listeners (two layer probes + the approved endpoint), each
        # registered -> listening, with its own closed record on close; the
        # deliberately injected records are excluded by pid or by being extras
        self.assertEqual(sum(1 for e in lifecycle if e["event"] == "registered"), 3)
        self.assertEqual(sum(1 for e in lifecycle if e["event"] == "listening"), 3 + 1)  # + injected kernel probe
        allowed = [r for r in records if r.get("allowed") == "socket.connect"]
        self.assertEqual(len(allowed), 1)
        self.assertEqual(allowed[0]["creator"], child_pid)



class TestDenyListIsolated(_GuardChildTestCase):
    def test_g6_denied_port_is_refused_even_when_every_other_check_would_pass(self):
        # The policy never lets a process bind a specific port, so the deny
        # list cannot be reached through a real listener; exercise the
        # decision function directly (no hook is installed in this process).
        import importlib.util
        from unittest import mock
        spec = importlib.util.spec_from_file_location("fw_audit_guard_under_test", HARNESS_DIR / "audit_guard.py")
        guard_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(guard_module)
        self.registry.write_text(json.dumps({"event": "listening", "port": int(PROXY_STYLE_DENIED_PORT),
                                             "pid": os.getpid()}) + "\n")
        with mock.patch.dict(os.environ, self.guard_env(), clear=True):
            guard = guard_module._Guard()
        with mock.patch.object(guard, "kernel_listening", return_value=True), \
                mock.patch.object(guard, "alive", return_value=True):
            reason = guard.decide("socket.connect", (None, ("127.0.0.1", int(PROXY_STYLE_DENIED_PORT))))
            allowed_control = guard.decide("socket.connect", (None, ("127.0.0.1", int(PROXY_STYLE_DENIED_PORT) + 1)))
        self.assertIsNotNone(reason)
        self.assertIn("denied port", reason)
        self.assertIn("unregistered", allowed_control)  # a non-denied port falls through to the registry check


if __name__ == "__main__":
    unittest.main()
