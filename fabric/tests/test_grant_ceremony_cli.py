"""Tests for the operator grant commands added to
fabric/tcp/pc_pairing_ceremony.py (MISSION: FW-PHASE-0-IMPLEMENT-001).

Calls main(argv) in-process -- no subprocess, no listener.
"""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fabric import interface as fi  # noqa: E402
from fabric.tcp import pc_pairing_ceremony as ceremony  # noqa: E402


class _CeremonyTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.dirs = {name: root / name for name in ("keys", "pairing", "peers", "grants")}
        self.key_store = fi.LocalKeyStore(self.dirs["keys"])
        self.pairing_store = fi.PairingStore(self.dirs["pairing"])
        self.peer_store = fi.PeerIdentityStore(self.dirs["peers"])

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        base = [
            "--key-store-dir", str(self.dirs["keys"]), "--pairing-store-dir", str(self.dirs["pairing"]),
            "--peer-store-dir", str(self.dirs["peers"]), "--grant-store-dir", str(self.dirs["grants"]),
        ]
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = ceremony.main(base + list(argv))
        return rc, out.getvalue(), err.getvalue()

    def _active_bound_pair(self, confirm=True, bind=True):
        offer = self.pairing_store.create_offer("PC-NODE-CLI", "PHONE-NODE-CLI", self.key_store)
        if confirm:
            self.pairing_store.confirm(offer["relationship_id"], offer["sas"])
        peer_id = self.peer_store.register_peer()
        if bind:
            self.peer_store.bind_relationship(peer_id, offer["relationship_id"])
        return offer, peer_id

    def _issue(self, offer, peer_id, *extra):
        return self._run(
            "issue-grant", "--peer-id", peer_id, "--relationship-id", offer["relationship_id"],
            "--capability", "physical_ping", "--ttl-seconds", "600", "--issued-by", "operator", *extra,
        )


class TestGrantCommands(_CeremonyTestCase):
    def test_g1_issue_list_revoke_round_trip(self):
        offer, peer_id = self._active_bound_pair()
        rc, out, _ = self._issue(offer, peer_id)
        self.assertEqual(rc, 0)
        grant_id = out.split("grant_id=")[1].split()[0]

        rc, out, _ = self._run("list-grants", "--peer-id", peer_id, "--relationship-id", offer["relationship_id"])
        self.assertEqual(rc, 0)
        self.assertIn(f"grant_id={grant_id} event=ISSUED", out)

        rc, out, _ = self._run("revoke-grant", "--grant-id", grant_id, "--reason", "done")
        self.assertEqual(rc, 0)
        self.assertEqual(fi.LocalGrantStore(self.dirs["grants"]).status_of(grant_id)["event"], fi.GRANT_EVENT_REVOKED)

    def test_g2_issuance_refused_for_unconfirmed_revoked_or_unbound(self):
        unconfirmed, peer_a = self._active_bound_pair(confirm=False)
        unbound, peer_b = self._active_bound_pair(bind=False)
        revoked_peer_offer, peer_c = self._active_bound_pair()
        self.peer_store.revoke_peer(peer_c, reason="test")
        for offer, peer_id, label in ((unconfirmed, peer_a, "not ACTIVE"), (unbound, peer_b, "not bound"),
                                      (revoked_peer_offer, peer_c, "not ACTIVE")):
            with self.subTest(label=label):
                rc, _, err = self._issue(offer, peer_id)
                self.assertEqual(rc, 1)
                self.assertIn(label, err)
        self.assertFalse((self.dirs["grants"] / "capability_grants.jsonl").exists())

    def test_g3_output_and_ledger_contain_no_secret_material(self):
        offer, peer_id = self._active_bound_pair()
        secret_hex = self.key_store.resolve_key(offer["key_id"]).hex()
        _, issue_out, _ = self._issue(offer, peer_id)
        _, list_out, _ = self._run("list-grants", "--peer-id", peer_id, "--relationship-id", offer["relationship_id"])
        ledger = (self.dirs["grants"] / "capability_grants.jsonl").read_text(encoding="utf-8")
        for text in (issue_out, list_out, ledger):
            self.assertNotIn(secret_hex, text)

    def test_g4_issue_grant_requires_an_explicit_expiry(self):
        offer, peer_id = self._active_bound_pair()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self._run("issue-grant", "--peer-id", peer_id, "--relationship-id", offer["relationship_id"],
                      "--capability", "physical_ping", "--issued-by", "operator")
        rc, _, err = self._run("issue-grant", "--peer-id", peer_id, "--relationship-id", offer["relationship_id"],
                               "--capability", "physical_ping", "--ttl-seconds", "0", "--issued-by", "operator")
        self.assertEqual(rc, 1)
        self.assertIn("positive", err)


if __name__ == "__main__":
    unittest.main()
