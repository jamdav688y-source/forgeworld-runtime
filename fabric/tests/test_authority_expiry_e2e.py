"""Tests for FW-AUTHORITY-EXPIRY-E2E-001.

Proves, end-to-end through process_remote_capability_request() itself
(not just authority_permits() in isolation, already covered by
fabric/tests/test_authority_expiry.py), that expired authority never
reaches capability execution. Stdlib unittest, same precedent as every
other test file in this program. No network, no phone, no external
service -- fabric.transports.InMemoryFabricTransport only.

Zero production code was changed for this mission: inspection of
process_remote_capability_request() (fabric/interface.py) showed exactly
one call to authority_permits(), strictly before the capability lookup
(CAPABILITIES.get()) and provider.invoke() -- there is no other path
through this function that reaches invoke(). These tests exist to prove
that structural fact holds under real request construction, using a spy
capability provider to make "zero execution" directly observable rather
than merely inferred from the returned status.
"""
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fabric import interface as fi
from fabric.transports import InMemoryFabricTransport

PC_ID = "PC-NODE-E2E"
PHONE_ID = "PHONE-NODE-E2E"

# Fixed, not wall-clock-relative on purpose: real UTC "now" will always be
# after PAST_EXPIRY and before FUTURE_EXPIRY for the foreseeable operating
# life of this test suite -- no clock injection is needed or attempted
# because process_remote_capability_request() exposes none (see the
# EXACT-BOUNDARY limitation recorded in the evidence receipt).
PAST_EXPIRY = "2020-01-01T00:00:00Z"
FUTURE_EXPIRY = "2099-01-01T00:00:00Z"
MALFORMED_EXPIRY = "not-a-timestamp"


class _SpyCapabilityProvider:
    """Records every invoke() call so a test can assert the executor was
    never reached -- the narrowest deterministic mechanism available,
    no external service, no network."""

    def __init__(self, capability_id):
        self.capability_id = capability_id
        self.invocation_count = 0

    def invoke(self, manifest_dict, payload):
        self.invocation_count += 1
        return (fi.CAP_COMPLETED, {"echo_len": len(payload)}, None)


def _authority(capability_ids, expires_at=None, actor=PHONE_ID):
    return fi.AuthorityContext(
        actor_id=actor, granted_capability_ids=tuple(capability_ids),
        granted_by="operator_default_policy", expires_at=expires_at,
    )


def _submit_and_request(transport, spy, cap_authority, payload=b"e2e expiry probe payload"):
    """Real transfer (unrelated authority, always sufficient) followed by
    a real capability request carrying the authority_context under test --
    isolates expiry behavior to exactly the gate this mission targets,
    matching submit_transfer()'s own contract of not checking authority
    itself (transfer != trust; authority is enforced only at capability-
    invocation time)."""
    env = fi.build_artifact_envelope(PHONE_ID, payload, declared_content_type="text/plain")
    correlation_id = fi._new_id("CORR")
    xfer_request = fi.TransferRequest(
        request_id=fi._new_id("XFERREQ"), envelope=env, source_node_id=PHONE_ID,
        destination_node_id=PC_ID, authority_context=_authority((spy.capability_id,)),
        correlation_id=correlation_id,
    )
    xfer_result = fi.submit_transfer(xfer_request, transport)
    assert xfer_result.transfer_state == fi.TRANSFER_COMPLETED, "test fixture transfer must succeed to isolate the capability-authority gate"
    cap_request = fi.RemoteCapabilityRequest(
        request_id=fi._new_id("CAPREQ"), source_node_id=PHONE_ID, destination_node_id=PC_ID,
        artifact_id=env.artifact_id, capability_id=spy.capability_id, authority_context=cap_authority,
        correlation_id=correlation_id, causation_id=xfer_result.transfer_id, timeout_seconds=5,
    )
    return fi.process_remote_capability_request(cap_request, transport)


class _SpyCapabilityTestCase(unittest.TestCase):
    """Shared setup: register a uniquely-named spy capability, and
    guarantee its removal from the module-level fi.CAPABILITIES registry
    afterward so this file never leaks state into any other test file's
    view of the registry (e.g. test_fabric_contract.py's exact-keys
    assertion on advertised capability ids)."""

    def setUp(self):
        self.spy = _SpyCapabilityProvider("e2e_expiry_spy_" + fi.uuid.uuid4().hex[:8])
        fi.register_capability(self.spy)

    def tearDown(self):
        fi.CAPABILITIES.pop(self.spy.capability_id, None)


class TestExpiredAuthorityBlocksExecution(_SpyCapabilityTestCase):
    def test_expired_authority_is_denied_and_executor_never_invoked(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        authority = _authority((self.spy.capability_id,), expires_at=PAST_EXPIRY)
        result, receipt = _submit_and_request(transport, self.spy, authority)
        self.assertEqual(result.status, fi.CAP_UNAUTHORIZED)
        self.assertEqual(receipt.capability_status, fi.CAP_UNAUTHORIZED)
        self.assertEqual(self.spy.invocation_count, 0)


class TestFutureAuthorityPermitsExecution(_SpyCapabilityTestCase):
    def test_future_expiry_permits_execution_when_otherwise_authorized(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        authority = _authority((self.spy.capability_id,), expires_at=FUTURE_EXPIRY)
        result, receipt = _submit_and_request(transport, self.spy, authority)
        self.assertEqual(result.status, fi.CAP_COMPLETED)
        self.assertEqual(receipt.capability_status, fi.CAP_COMPLETED)
        self.assertEqual(self.spy.invocation_count, 1)


class TestNoneExpiryPreservesExistingExecution(_SpyCapabilityTestCase):
    def test_non_expiring_grant_still_executes(self):
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        authority = _authority((self.spy.capability_id,), expires_at=None)
        result, receipt = _submit_and_request(transport, self.spy, authority)
        self.assertEqual(result.status, fi.CAP_COMPLETED)
        self.assertEqual(self.spy.invocation_count, 1)


class TestMalformedExpiryBlocksExecution(_SpyCapabilityTestCase):
    def test_malformed_expiry_reaching_the_real_request_boundary_denies_and_never_executes(self):
        # AuthorityContext has no construction-time validation of
        # expires_at (documented limitation, FW-AUTHORITY-EXPIRY-
        # ENFORCEMENT-001's evidence receipt) -- a malformed value
        # legitimately can reach process_remote_capability_request()
        # exactly like this, through the real dataclass constructor, not
        # through an unrealistic bypass of the actual contract.
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        authority = _authority((self.spy.capability_id,), expires_at=MALFORMED_EXPIRY)
        result, receipt = _submit_and_request(transport, self.spy, authority)
        self.assertEqual(result.status, fi.CAP_UNAUTHORIZED)
        self.assertEqual(self.spy.invocation_count, 0)


class TestExistingAuthorityChecksUnweakened(_SpyCapabilityTestCase):
    def test_future_expiry_does_not_bypass_capability_allowlist(self):
        # A future (non-expired) grant for a DIFFERENT capability must
        # still be denied for this one -- expiry enforcement must not
        # weaken the pre-existing allowlist check.
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        authority = _authority(("some_other_capability",), expires_at=FUTURE_EXPIRY)
        result, receipt = _submit_and_request(transport, self.spy, authority)
        self.assertEqual(result.status, fi.CAP_UNAUTHORIZED)
        self.assertEqual(self.spy.invocation_count, 0)

    def test_expired_and_wrong_scope_together_still_denies_with_zero_execution(self):
        # Both violations present at once: still UNAUTHORIZED, still zero
        # execution -- expiry enforcement composes with, rather than
        # replaces, the existing allowlist check.
        transport = InMemoryFabricTransport(registered_nodes=(PC_ID,))
        authority = _authority(("some_other_capability",), expires_at=PAST_EXPIRY)
        result, receipt = _submit_and_request(transport, self.spy, authority)
        self.assertEqual(result.status, fi.CAP_UNAUTHORIZED)
        self.assertEqual(self.spy.invocation_count, 0)


if __name__ == "__main__":
    unittest.main()
