"""Acceptance tests for FW-PYTHON-NAMESPACE-STABILIZATION-001.

Proves, in ONE Python interpreter, that artifact_handoff, content_readers,
and local_inference (each of which has its own interface.py) can be
imported and used together without any bare-module-name sys.modules
collision -- the defect Microphase 02 empirically exposed and worked
around locally with a now-removed shim (content_readers/_interface_singleton.py).

Stdlib `unittest` (same precedent as every other test file in this
program). This file lives at the repo root's tests/ directory, not
inside any one capability's own tests/, because it is specifically
testing cross-package composition, not any single package's behavior.
"""
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# 1-3: import all three in one process.
from artifact_handoff import interface as ah_interface
from artifact_handoff import zip_unpack  # noqa: F401 -- registers the zip adapter
from artifact_handoff.local_file_provider import LocalFileAcquisitionProvider
from content_readers import interface as cr_interface
from content_readers import text_readers  # noqa: F401 -- registers text/plain etc.
from local_inference import interface as li_interface


class TestAllThreeImportTogether(unittest.TestCase):
    """1-3: import artifact_handoff / content_readers / local_inference
    interface modules in one process."""

    def test_all_three_modules_imported_successfully(self):
        self.assertTrue(hasattr(ah_interface, "handoff"))
        self.assertTrue(hasattr(cr_interface, "read_content"))
        self.assertTrue(hasattr(li_interface, "run_inference"))


class TestIdentitiesResolveToCorrectModules(unittest.TestCase):
    """5. identities resolve to their correct defining modules.
    8. no bare "interface" module shadowing occurs."""

    def test_module_names_are_fully_qualified_and_distinct(self):
        self.assertEqual(ah_interface.__name__, "artifact_handoff.interface")
        self.assertEqual(cr_interface.__name__, "content_readers.interface")
        self.assertEqual(li_interface.__name__, "local_inference.interface")
        self.assertIsNot(ah_interface, cr_interface)
        self.assertIsNot(ah_interface, li_interface)
        self.assertIsNot(cr_interface, li_interface)

    def test_sys_modules_keys_are_fully_qualified(self):
        self.assertIs(sys.modules["artifact_handoff.interface"], ah_interface)
        self.assertIs(sys.modules["content_readers.interface"], cr_interface)
        self.assertIs(sys.modules["local_inference.interface"], li_interface)

    def test_bare_interface_name_is_never_populated(self):
        self.assertNotIn("interface", sys.modules)

    def test_each_module_has_its_own_distinguishing_contract_symbol(self):
        # A concrete proof that these are genuinely different files, not
        # the same module imported three times under different aliases:
        # each has a symbol the others structurally cannot have.
        self.assertTrue(hasattr(ah_interface, "Manifest"))
        self.assertFalse(hasattr(cr_interface, "Manifest"))
        self.assertFalse(hasattr(li_interface, "Manifest"))
        self.assertTrue(hasattr(cr_interface, "ContentReadResult"))
        self.assertFalse(hasattr(ah_interface, "ContentReadResult"))
        self.assertTrue(hasattr(li_interface, "InferenceResult"))
        self.assertFalse(hasattr(ah_interface, "InferenceResult"))


class TestRepeatedImportsAreDeterministic(unittest.TestCase):
    """7. repeated imports remain deterministic."""

    def test_reimporting_via_importlib_returns_the_same_object(self):
        import importlib
        self.assertIs(importlib.import_module("artifact_handoff.interface"), ah_interface)
        self.assertIs(importlib.import_module("content_readers.interface"), cr_interface)
        self.assertIs(importlib.import_module("local_inference.interface"), li_interface)


class TestInstantiateRepresentativeContractObjects(unittest.TestCase):
    """4. instantiate/use representative contract objects from all three.
    9-11. existing behavior for each package is unchanged: a live
    functional round trip, not just an import check."""

    def test_full_cross_package_round_trip(self):
        # artifact_handoff: acquire + classify a real local fixture.
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "note.txt"
            content = b"namespace stabilization proof content"
            path.write_bytes(content)
            reference = ah_interface.ArtifactReference(
                source_provider="local_file", source_reference=str(path), declared_filename=path.name,
            )
            manifest = ah_interface.handoff(reference, LocalFileAcquisitionProvider())

        self.assertEqual(manifest.acquisition_state, ah_interface.ACQUISITION_ACQUIRED)
        self.assertEqual(manifest.sha256, hashlib.sha256(content).hexdigest())

        # content_readers: read that same artifact's content, glued via
        # the manifest dict only (no import of artifact_handoff needed
        # inside content_readers itself).
        request = cr_interface.build_request_from_manifest(manifest.to_dict(), data=content)
        read_result = cr_interface.read_content(request)
        self.assertEqual(read_result.status, cr_interface.READ_OK)
        self.assertEqual(read_result.text_content, content.decode())
        self.assertEqual(read_result.provenance_reference, manifest.artifact_id)

        # local_inference: independent of the above, same process.
        class _FakeProvider:
            provider_id = "fake_local"

            def reachability_check(self):
                return {"reachable": True, "confidence": 1.0, "evidence": "forced for test", "evidence_level": None}

            def invoke(self, request):
                now = li_interface._now()
                return li_interface.InferenceResult(
                    request_id=request.request_id, status=li_interface.STATUS_COMPLETED,
                    provider=request.provider, model=request.model, locality=request.locality,
                    output_text="fake output", error_detail=None, started_at=now, completed_at=now,
                    duration_seconds=0.001,
                )

        inference_request = li_interface.InferenceRequest(
            request_id="NS-STAB-0001", provider="fake_local", model="test-model",
            prompt="say hello", timeout_seconds=5,
        )
        inference_result = li_interface.run_inference(inference_request, _FakeProvider())
        self.assertEqual(inference_result.status, li_interface.STATUS_COMPLETED)
        self.assertEqual(inference_result.evidence_status, li_interface.NOT_EVIDENCE)


class TestImportOrderDoesNotAlterResolution(unittest.TestCase):
    """6. import order does not alter resolution -- proven in a fresh
    subprocess (distinct interpreter, distinct sys.modules) that imports
    the three packages in the OPPOSITE order from this file's own
    module-level imports above."""

    def test_reverse_import_order_in_a_fresh_interpreter(self):
        script = f"""
import sys
sys.path.insert(0, {str(REPO_ROOT)!r})

# Opposite order: local_inference, then content_readers, then artifact_handoff.
from local_inference import interface as li
from content_readers import interface as cr
from artifact_handoff import interface as ah

assert li.__name__ == "local_inference.interface", li.__name__
assert cr.__name__ == "content_readers.interface", cr.__name__
assert ah.__name__ == "artifact_handoff.interface", ah.__name__
assert hasattr(ah, "Manifest") and not hasattr(cr, "Manifest") and not hasattr(li, "Manifest")
assert hasattr(cr, "ContentReadResult") and not hasattr(ah, "ContentReadResult")
assert hasattr(li, "InferenceResult") and not hasattr(ah, "InferenceResult")
assert "interface" not in sys.modules
print("REVERSE_ORDER_OK")
"""
        proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, msg=f"stdout={proc.stdout!r} stderr={proc.stderr!r}")
        self.assertIn("REVERSE_ORDER_OK", proc.stdout)


if __name__ == "__main__":
    unittest.main()
