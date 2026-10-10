"""Tests for LOCAL-INFERENCE-SEAM-001.

Stdlib `unittest`, not pytest: this sandbox has no pytest installed and
installing it is out of scope for this mission (see capabilities/tests
for the same precedent/rationale).

No test in this file makes a network call, downloads a model, starts a
service, or requires Ollama to be installed. `TestNoNetworkCalls` proves
the negative directly by making socket.create_connection raise if
anything under test tries to use it.
"""
import socket
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

LOCAL_INFERENCE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = LOCAL_INFERENCE_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from local_inference import interface  # noqa: E402
from local_inference import ollama_adapter  # noqa: E402


class FakeProvider:
    """An entirely in-memory provider: no subprocess, no filesystem, no
    network. Proves the interface is provider-neutral -- Ollama is not
    the only thing that can satisfy LocalInferenceProvider."""

    provider_id = "fake_local"

    def __init__(self, reachable=True, output_text="fake model output"):
        self.reachable = reachable
        self.output_text = output_text
        self.invoke_call_count = 0

    def reachability_check(self) -> dict:
        return {
            "reachable": self.reachable,
            "confidence": 1.0 if self.reachable else 0.0,
            "evidence": "fake provider forced reachable" if self.reachable else "fake provider forced unreachable",
            "evidence_level": None,
        }

    def invoke(self, request: interface.InferenceRequest) -> interface.InferenceResult:
        self.invoke_call_count += 1
        now = interface._now()
        return interface.InferenceResult(
            request_id=request.request_id,
            status=interface.STATUS_COMPLETED,
            provider=request.provider,
            model=request.model,
            locality=request.locality,
            output_text=self.output_text,
            error_detail=None,
            started_at=now,
            completed_at=now,
            duration_seconds=0.001,
        )


def _make_request(**overrides):
    defaults = dict(
        request_id="TEST-REQ-0001",
        provider="fake_local",
        model="test-model",
        prompt="say hello",
        timeout_seconds=5,
    )
    defaults.update(overrides)
    return interface.InferenceRequest(**defaults)


class TestStructuredRequestAndResult(unittest.TestCase):
    def test_request_has_explicit_provider_model_locality(self):
        req = _make_request()
        self.assertEqual(req.provider, "fake_local")
        self.assertEqual(req.model, "test-model")
        self.assertEqual(req.locality, interface.LOCALITY_LOCAL_ONLY)

    def test_result_rejects_unknown_status(self):
        with self.assertRaises(interface.LocalInferenceError):
            interface.InferenceResult(
                request_id="X", status="MADE_UP_STATUS", provider="fake_local",
                model="m", locality=interface.LOCALITY_LOCAL_ONLY, output_text=None,
                error_detail=None, started_at="t", completed_at="t", duration_seconds=0.0,
            )

    def test_completed_result_requires_output_text(self):
        with self.assertRaises(interface.LocalInferenceError):
            interface.InferenceResult(
                request_id="X", status=interface.STATUS_COMPLETED, provider="fake_local",
                model="m", locality=interface.LOCALITY_LOCAL_ONLY, output_text=None,
                error_detail=None, started_at="t", completed_at="t", duration_seconds=0.0,
            )


class TestModelOutputIsNotEvidence(unittest.TestCase):
    """model output is NOT evidence; invocation does NOT imply truth or
    promotion -- for both success and failure results."""

    def test_successful_result_still_not_evidence_or_truth_or_promoted(self):
        provider = FakeProvider(reachable=True)
        result = interface.run_inference(_make_request(), provider)
        self.assertEqual(result.status, interface.STATUS_COMPLETED)
        self.assertEqual(result.evidence_status, interface.NOT_EVIDENCE)
        self.assertEqual(result.interpretation_status, interface.UNVERIFIED_MODEL_OUTPUT)
        self.assertEqual(result.promotion_status, interface.NOT_PROMOTED)

    def test_failed_result_also_not_evidence_or_truth_or_promoted(self):
        provider = FakeProvider(reachable=False)
        result = interface.run_inference(_make_request(), provider)
        self.assertEqual(result.status, interface.STATUS_UNREACHABLE)
        self.assertEqual(result.evidence_status, interface.NOT_EVIDENCE)
        self.assertEqual(result.interpretation_status, interface.UNVERIFIED_MODEL_OUTPUT)
        self.assertEqual(result.promotion_status, interface.NOT_PROMOTED)


class TestUnreachableFailsHonestly(unittest.TestCase):
    def test_unreachable_provider_never_gets_invoked(self):
        provider = FakeProvider(reachable=False)
        result = interface.run_inference(_make_request(), provider)
        self.assertEqual(result.status, interface.STATUS_UNREACHABLE)
        self.assertEqual(provider.invoke_call_count, 0, "unreachable provider must never be invoked")
        self.assertIn("not reachable", result.error_detail)

    def test_invalid_request_never_reaches_reachability_or_invoke(self):
        provider = FakeProvider(reachable=True)
        bad_request = _make_request(prompt="")
        result = interface.run_inference(bad_request, provider)
        self.assertEqual(result.status, interface.STATUS_INVALID_REQUEST)
        self.assertEqual(provider.invoke_call_count, 0)

    def test_provider_id_mismatch_is_invalid_request(self):
        provider = FakeProvider(reachable=True)
        mismatched = _make_request(provider="not_fake_local")
        result = interface.run_inference(mismatched, provider)
        self.assertEqual(result.status, interface.STATUS_INVALID_REQUEST)
        self.assertEqual(provider.invoke_call_count, 0)


class TestRoutingDirectionPreserved(unittest.TestCase):
    def test_local_inference_sits_between_composed_capability_and_synthesized_capability(self):
        chain = interface.ROUTING_CHAIN
        self.assertEqual(
            chain,
            (
                "deterministic", "retrieval", "existing_capability", "composed_capability",
                "local_inference", "synthesized_capability", "frontier_inference", "human_judgment",
            ),
        )
        self.assertEqual(interface.ROUTER_TIER, "local_inference")
        idx = chain.index("local_inference")
        self.assertEqual(chain[idx - 1], "composed_capability")
        self.assertEqual(chain[idx + 1], "synthesized_capability")


class TestOllamaAdapterReachability(unittest.TestCase):
    """Proves failure behavior without requiring Ollama to be installed:
    this sandbox genuinely has no `ollama` binary, so this is a real,
    honest, unmocked probe."""

    def test_reuses_registered_local_llm_check(self):
        check = ollama_adapter._find_registered_check()
        self.assertIsNotNone(check)
        self.assertEqual(check["type"], "command")
        self.assertEqual(check["value"], "ollama")

    def test_real_reachability_check_in_this_sandbox_is_honestly_unreachable(self):
        provider = ollama_adapter.OllamaProvider()
        reach = provider.reachability_check()
        self.assertFalse(reach["reachable"])
        self.assertEqual(reach["confidence"], 0.0)
        self.assertIn("ollama", reach["evidence"])

    def test_run_inference_reports_unreachable_without_installing_ollama(self):
        provider = ollama_adapter.OllamaProvider()
        request = _make_request(provider="ollama", model="llama3.1:8b")
        result = interface.run_inference(request, provider)
        self.assertEqual(result.status, interface.STATUS_UNREACHABLE)
        self.assertIsNone(result.output_text)


class _ForcedReachableOllamaProvider(ollama_adapter.OllamaProvider):
    """Test-only subclass: same invoke() logic as the real adapter, but
    with reachability forced True so invoke() can be exercised through
    run_inference() without a real ollama binary."""

    def reachability_check(self) -> dict:
        return {"reachable": True, "confidence": 1.0, "evidence": "forced for test", "evidence_level": None}


class TestOllamaAdapterInvoke(unittest.TestCase):
    """invoke() control flow, proven entirely with an injected fake
    run_fn -- no subprocess actually named 'ollama' is ever executed."""

    def test_successful_invocation(self):
        def fake_run(cmd, capture_output, text, timeout):
            self.assertEqual(cmd[0], "ollama")
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="hello from fake ollama", stderr="")

        provider = _ForcedReachableOllamaProvider(run_fn=fake_run)
        request = _make_request(provider="ollama", model="llama3.1:8b")
        result = interface.run_inference(request, provider)
        self.assertEqual(result.status, interface.STATUS_COMPLETED)
        self.assertEqual(result.output_text, "hello from fake ollama")
        self.assertEqual(result.evidence_status, interface.NOT_EVIDENCE)

    def test_timeout(self):
        def fake_run(cmd, capture_output, text, timeout):
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)

        provider = _ForcedReachableOllamaProvider(run_fn=fake_run)
        request = _make_request(provider="ollama", model="llama3.1:8b", timeout_seconds=1)
        result = interface.run_inference(request, provider)
        self.assertEqual(result.status, interface.STATUS_TIMEOUT)
        self.assertIsNone(result.output_text)

    def test_provider_error_on_nonzero_exit(self):
        def fake_run(cmd, capture_output, text, timeout):
            return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="model not found")

        provider = _ForcedReachableOllamaProvider(run_fn=fake_run)
        request = _make_request(provider="ollama", model="does-not-exist")
        result = interface.run_inference(request, provider)
        self.assertEqual(result.status, interface.STATUS_PROVIDER_ERROR)
        self.assertIn("model not found", result.error_detail)
        self.assertIsNone(result.output_text)

    def test_oserror_during_invoke_is_unreachable(self):
        def fake_run(cmd, capture_output, text, timeout):
            raise OSError("binary vanished between reachability check and invoke")

        provider = _ForcedReachableOllamaProvider(run_fn=fake_run)
        request = _make_request(provider="ollama", model="llama3.1:8b")
        result = interface.run_inference(request, provider)
        self.assertEqual(result.status, interface.STATUS_UNREACHABLE)


class TestNoNetworkCalls(unittest.TestCase):
    """Makes socket.create_connection raise if anything under test tries
    to use it -- a direct, positive proof rather than an assumption."""

    def test_fake_provider_path_never_touches_the_network(self):
        with mock.patch.object(socket, "create_connection", side_effect=AssertionError("network touched")):
            provider = FakeProvider(reachable=True)
            result = interface.run_inference(_make_request(), provider)
            self.assertEqual(result.status, interface.STATUS_COMPLETED)

    def test_ollama_adapter_path_never_touches_the_network(self):
        def fake_run(cmd, capture_output, text, timeout):
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="ok", stderr="")

        with mock.patch.object(socket, "create_connection", side_effect=AssertionError("network touched")):
            # Real reachability_check() (unmocked): local_llm's registry
            # check is type "command", which never opens a socket.
            provider = ollama_adapter.OllamaProvider(run_fn=fake_run)
            reach = provider.reachability_check()
            self.assertFalse(reach["reachable"])  # honest: ollama absent here

            forced = _ForcedReachableOllamaProvider(run_fn=fake_run)
            request = _make_request(provider="ollama", model="llama3.1:8b")
            result = interface.run_inference(request, forced)
            self.assertEqual(result.status, interface.STATUS_COMPLETED)


if __name__ == "__main__":
    unittest.main()
