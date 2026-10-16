"""Tests for MISSION: FW-PHASE-1-HARDENING-001 -- production entry points
are governed-only and carry no test hooks.

Entirely in-process: multiprocessing.connection.Listener is replaced by a
fake that records whether it was ever constructed and serves scripted
messages, so no socket is ever created by this file.
"""
import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fabric import interface as fi  # noqa: E402
from fabric.loopback import pc_node_server as loopback_server  # noqa: E402
from fabric.tcp import pc_node_server as tcp_server  # noqa: E402

LOOPBACK_SOURCE = REPO_ROOT / "fabric" / "loopback" / "pc_node_server.py"
TCP_SOURCE = REPO_ROOT / "fabric" / "tcp" / "pc_node_server.py"
STRONG_KEY = b"k" * fi.MIN_AUTHKEY_BYTES


class _FakeConnection:
    """Serves scripted wire messages and records every reply."""

    def __init__(self, messages):
        self._incoming = [json.dumps({"kind": k, "payload": p}).encode() for k, p in messages]
        self.sent = []
        self.maxlengths = []

    def poll(self, timeout):
        return bool(self._incoming)

    def recv_bytes(self, maxlength=None):
        self.maxlengths.append(maxlength)
        if not self._incoming:
            raise EOFError
        return self._incoming.pop(0)

    def send_bytes(self, data):
        self.sent.append(json.loads(data))

    def close(self):
        pass


class _FakeListener:
    def __init__(self, conn, *args, **kwargs):
        self._conn = conn
        self.address = ("fake", 0)

    def accept(self):
        return self._conn

    def close(self):
        pass


def _forbidden_listener(*args, **kwargs):
    raise AssertionError("a listener was constructed before configuration was validated")


def _option_strings(source: Path) -> dict:
    """{'--option': required_bool} for every parser.add_argument in source."""
    options = {}
    for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "add_argument" and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                required = any(k.arg == "required" and getattr(k.value, "value", False) for k in node.keywords)
                options[first.value] = required
    return options


class _GovernedDirs(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.dirs = {name: str(root / name) for name in ("keys", "pairing", "peers", "grants", "lineage")}
        self._capabilities = dict(fi.CAPABILITIES)

    def tearDown(self):
        fi.CAPABILITIES.clear()
        fi.CAPABILITIES.update(self._capabilities)
        self._tmp.cleanup()

    def governed_kwargs(self, **overrides):
        kwargs = dict(key_store_dir=self.dirs["keys"], pairing_store_dir=self.dirs["pairing"],
                      peer_store_dir=self.dirs["peers"], grant_store_dir=self.dirs["grants"])
        kwargs.update(overrides)
        return kwargs


class TestNoTestHooksInProductionServers(unittest.TestCase):
    def test_production_server_sources_contain_no_test_hooks(self):
        for source in (LOOPBACK_SOURCE, TCP_SOURCE):
            code = source.read_text(encoding="utf-8")
            with self.subTest(source=source.name):
                for forbidden in ('"TEST_HOOK"', "os._exit", "_AlwaysIncompleteTestCapability",
                                  "broken_incomplete_capability_for_testing", "time.sleep"):
                    self.assertNotIn(forbidden, code)

    def test_production_servers_have_no_legacy_integrity_key_option_and_require_all_stores(self):
        for source in (LOOPBACK_SOURCE, TCP_SOURCE):
            options = _option_strings(source)
            with self.subTest(source=source.name):
                self.assertNotIn("--integrity-key", options)
                for store in ("--key-store-dir", "--pairing-store-dir", "--peer-store-dir", "--grant-store-dir"):
                    self.assertTrue(options.get(store), f"{store} must be a required option")

    def test_only_test_code_enables_ungoverned_or_hooked_run_server(self):
        offenders = []
        for path in REPO_ROOT.rglob("*.py"):
            rel = path.relative_to(REPO_ROOT)
            if "tests" in rel.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if "_allow_ungoverned=True" in text or "_test_handlers=" in text and "def run_server" not in text:
                offenders.append(str(rel))
        self.assertEqual(offenders, [])


class TestGovernedStartupRefusal(_GovernedDirs):
    def _loopback_argv(self, omit=None, authkey=STRONG_KEY, extra=()):
        argv = ["--address", "/nonexistent/fwp1.sock", "--family", "AF_UNIX", "--authkey", authkey.hex(),
                "--node-id", "PC-NODE-HARDENING", "--lineage-dir", self.dirs["lineage"]]
        for opt, key in (("--key-store-dir", "keys"), ("--pairing-store-dir", "pairing"),
                         ("--peer-store-dir", "peers"), ("--grant-store-dir", "grants")):
            if opt != omit:
                argv += [opt, self.dirs[key]]
        return argv + list(extra)

    def _tcp_argv(self, omit=None, authkey=STRONG_KEY, extra=()):
        argv = ["--host", "127.0.0.1", "--port", "1", "--authkey", authkey.hex(), "--lineage-dir", self.dirs["lineage"]]
        for opt, key in (("--key-store-dir", "keys"), ("--pairing-store-dir", "pairing"),
                         ("--peer-store-dir", "peers"), ("--grant-store-dir", "grants")):
            if opt != omit:
                argv += [opt, self.dirs[key]]
        return argv + list(extra)

    def _assert_main_refuses(self, module, argv):
        with mock.patch.object(module.connection, "Listener", side_effect=_forbidden_listener), \
                mock.patch("sys.stderr"), self.assertRaises(SystemExit) as exit_info:
            module.main(argv)
        self.assertEqual(exit_info.exception.code, 2)

    def test_main_refuses_any_missing_store(self):
        for module, argv_for in ((loopback_server, self._loopback_argv), (tcp_server, self._tcp_argv)):
            for store in ("--key-store-dir", "--pairing-store-dir", "--peer-store-dir", "--grant-store-dir"):
                with self.subTest(server=module.__name__, missing=store):
                    self._assert_main_refuses(module, argv_for(omit=store))

    def test_main_refuses_a_short_authkey(self):
        short = b"k" * (fi.MIN_AUTHKEY_BYTES - 1)
        for module, argv_for in ((loopback_server, self._loopback_argv), (tcp_server, self._tcp_argv)):
            with self.subTest(server=module.__name__):
                self._assert_main_refuses(module, argv_for(authkey=short))

    def test_main_rejects_the_legacy_integrity_key_option(self):
        for module, argv_for in ((loopback_server, self._loopback_argv), (tcp_server, self._tcp_argv)):
            with self.subTest(server=module.__name__):
                self._assert_main_refuses(module, argv_for(extra=["--integrity-key", "00" * 32]))

    def test_run_server_refuses_ungoverned_configurations_before_listening(self):
        cases = {
            "no stores": dict(),
            "no grant store": self.governed_kwargs(grant_store_dir=None),
            "no peer store": self.governed_kwargs(peer_store_dir=None),
            "legacy integrity key": self.governed_kwargs(integrity_key=b"i" * 32),
        }
        for label, kwargs in cases.items():
            with self.subTest(server="loopback", case=label), \
                    mock.patch.object(loopback_server.connection, "Listener", side_effect=_forbidden_listener), \
                    self.assertRaises(fi.FabricError):
                loopback_server.run_server("/nonexistent/fwp1.sock", "AF_UNIX", STRONG_KEY, "PC-NODE-H",
                                           self.dirs["lineage"], **kwargs)
            with self.subTest(server="tcp", case=label), \
                    mock.patch.object(tcp_server.connection, "Listener", side_effect=_forbidden_listener), \
                    self.assertRaises(fi.FabricError):
                tcp_server.run_server("127.0.0.1", 1, STRONG_KEY, "PC-NODE-H", self.dirs["lineage"], **kwargs)

    def test_run_server_refuses_a_short_authkey_even_when_governed(self):
        with mock.patch.object(loopback_server.connection, "Listener", side_effect=_forbidden_listener), \
                self.assertRaises(fi.FabricError):
            loopback_server.run_server("/nonexistent/fwp1.sock", "AF_UNIX", b"short", "PC-NODE-H",
                                       self.dirs["lineage"], **self.governed_kwargs())


class TestGovernedLoopbackServing(_GovernedDirs):
    def _serve(self, messages, **overrides):
        conn = _FakeConnection(messages + [("SHUTDOWN", {})])
        with mock.patch.object(loopback_server.connection, "Listener",
                               side_effect=lambda *a, **k: _FakeListener(conn)), mock.patch("sys.stdout"):
            loopback_server.run_server("/nonexistent/fwp1.sock", "AF_UNIX", STRONG_KEY, "PC-NODE-H",
                                       self.dirs["lineage"], **self.governed_kwargs(**overrides))
        return conn

    def test_test_hook_is_an_unrecognized_message_in_production(self):
        conn = self._serve([("TEST_HOOK", {"action": "die"}), ("TEST_HOOK", {"action": "sleep_ms", "ms": 5})])
        kinds = [m["kind"] for m in conn.sent]
        self.assertEqual(kinds, ["PROTOCOL_ERROR", "PROTOCOL_ERROR"])
        self.assertIn("TEST_HOOK", conn.sent[0]["payload"]["reason"])

    def test_capability_allowlist_and_message_bound_are_enforced(self):
        conn = self._serve([])
        self.assertEqual(set(fi.CAPABILITIES), {"content_read"})
        self.assertNotIn("broken_incomplete_capability_for_testing", fi.CAPABILITIES)
        self.assertTrue(conn.maxlengths)
        self.assertTrue(all(m == loopback_server.DEFAULT_MAX_MESSAGE_BYTES for m in conn.maxlengths))


if __name__ == "__main__":
    unittest.main()
