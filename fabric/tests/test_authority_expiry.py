"""Tests for FW-AUTHORITY-EXPIRY-ENFORCEMENT-001.

Narrowly scoped, additive: proves authority_permits() enforces
AuthorityContext.expires_at without touching fabric/tests/test_fabric_contract.py.
Stdlib unittest only, same precedent as every other test file in this
program. No network, no phone, no external service.
"""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fabric import interface as fi

ACTOR_ID = "PHONE-NODE-FIELD"
FIXED_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
FIXED_NOW_STR = FIXED_NOW.strftime(fi._TIMESTAMP_FORMAT)


def _context(expires_at=None, capability_ids=("content_read",)):
    return fi.AuthorityContext(
        actor_id=ACTOR_ID,
        granted_capability_ids=tuple(capability_ids),
        granted_by="operator_default_policy",
        expires_at=expires_at,
    )


class TestExpiredAuthorityIsRejected(unittest.TestCase):
    def test_expires_at_in_the_past_denies(self):
        past = (FIXED_NOW - timedelta(seconds=1)).strftime(fi._TIMESTAMP_FORMAT)
        context = _context(expires_at=past)
        self.assertFalse(fi.authority_permits(context, "content_read", evaluation_time=FIXED_NOW))

    def test_expires_at_far_in_the_past_denies(self):
        past = (FIXED_NOW - timedelta(days=365)).strftime(fi._TIMESTAMP_FORMAT)
        context = _context(expires_at=past)
        self.assertFalse(fi.authority_permits(context, "content_read", evaluation_time=FIXED_NOW))


class TestFutureAuthorityIsAccepted(unittest.TestCase):
    def test_expires_at_in_the_future_permits(self):
        future = (FIXED_NOW + timedelta(seconds=1)).strftime(fi._TIMESTAMP_FORMAT)
        context = _context(expires_at=future)
        self.assertTrue(fi.authority_permits(context, "content_read", evaluation_time=FIXED_NOW))

    def test_future_expiry_still_respects_capability_allowlist(self):
        future = (FIXED_NOW + timedelta(seconds=1)).strftime(fi._TIMESTAMP_FORMAT)
        context = _context(expires_at=future, capability_ids=("echo_mock",))
        self.assertFalse(fi.authority_permits(context, "content_read", evaluation_time=FIXED_NOW))


class TestNonExpiringGrantPreservesExistingBehavior(unittest.TestCase):
    def test_expires_at_none_permits_granted_capability(self):
        context = _context(expires_at=None)
        self.assertTrue(fi.authority_permits(context, "content_read", evaluation_time=FIXED_NOW))

    def test_expires_at_none_still_denies_ungranted_capability(self):
        context = _context(expires_at=None)
        self.assertFalse(fi.authority_permits(context, "arbitrary_shell_execution", evaluation_time=FIXED_NOW))

    def test_expires_at_none_permits_with_real_wall_clock(self):
        context = _context(expires_at=None)
        self.assertTrue(fi.authority_permits(context, "content_read"))


class TestExactBoundaryIsRejected(unittest.TestCase):
    def test_evaluation_time_equal_to_expires_at_denies(self):
        context = _context(expires_at=FIXED_NOW_STR)
        self.assertFalse(fi.authority_permits(context, "content_read", evaluation_time=FIXED_NOW))

    def test_evaluation_time_one_microsecond_before_expiry_permits(self):
        just_before = FIXED_NOW - timedelta(microseconds=1)
        context = _context(expires_at=FIXED_NOW_STR)
        self.assertTrue(fi.authority_permits(context, "content_read", evaluation_time=just_before))


class TestMalformedExpiryFailsClosed(unittest.TestCase):
    def test_non_timestamp_string_denies(self):
        context = _context(expires_at="not-a-timestamp")
        self.assertFalse(fi.authority_permits(context, "content_read", evaluation_time=FIXED_NOW))

    def test_empty_string_denies(self):
        context = _context(expires_at="")
        self.assertFalse(fi.authority_permits(context, "content_read", evaluation_time=FIXED_NOW))

    def test_wrong_format_denies(self):
        context = _context(expires_at="2026-01-01")
        self.assertFalse(fi.authority_permits(context, "content_read", evaluation_time=FIXED_NOW))

    def test_naive_evaluation_time_raises_instead_of_silently_resolving(self):
        context = _context(expires_at=FIXED_NOW_STR)
        naive_now = datetime(2026, 1, 1, 11, 0, 0)
        with self.assertRaises(fi.FabricError):
            fi.authority_permits(context, "content_read", evaluation_time=naive_now)


class TestExistingAuthorityBehaviorUnchanged(unittest.TestCase):
    def test_capability_not_in_granted_scope_is_still_unauthorized(self):
        context = _context(expires_at=None, capability_ids=("content_read",))
        self.assertFalse(fi.authority_permits(context, "arbitrary_shell_execution"))

    def test_empty_grant_authorizes_nothing_regardless_of_expiry(self):
        future = (FIXED_NOW + timedelta(days=1)).strftime(fi._TIMESTAMP_FORMAT)
        context = _context(expires_at=future, capability_ids=())
        self.assertFalse(fi.authority_permits(context, "content_read", evaluation_time=FIXED_NOW))

    def test_expired_broad_grant_still_does_not_authorize_unlisted_capability(self):
        past = (FIXED_NOW - timedelta(seconds=1)).strftime(fi._TIMESTAMP_FORMAT)
        context = _context(expires_at=past, capability_ids=("content_read", "echo_mock"))
        self.assertFalse(fi.authority_permits(context, "arbitrary_shell_execution", evaluation_time=FIXED_NOW))


if __name__ == "__main__":
    unittest.main()
