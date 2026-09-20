"""Tests for FW-ARTIFACT-HANDOFF-SEAM-001.

Stdlib `unittest`, not pytest (same precedent/rationale as
capabilities/tests and local_inference/tests: no pytest installed in
this sandbox, installing it is out of scope).

ALL fixtures are synthetic and local (built in-memory / in a TemporaryDirectory
by this file). Nothing here touches Gmail, Drive, any network service, or
any real external artifact. route_to_capability() uses discover.load_registry()
+ discover.probe_all() (read-only, no writes) and mission_router.
score_capability() (a pure function) -- never mission_router.route(), so
no test here writes to the live router/decisions.jsonl or
capabilities/state.json.
"""
import hashlib
import io
import stat
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ARTIFACT_HANDOFF_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = ARTIFACT_HANDOFF_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from artifact_handoff import interface  # noqa: E402
from artifact_handoff import zip_unpack  # noqa: E402 -- import registers the zip adapter as a side effect
from artifact_handoff.local_file_provider import LocalFileAcquisitionProvider  # noqa: E402

PROVIDER = LocalFileAcquisitionProvider()


def _write_fixture(tmpdir: str, name: str, data: bytes) -> Path:
    path = Path(tmpdir) / name
    path.write_bytes(data)
    return path


def _zip_bytes(entries: dict, symlink_entries: dict = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
        for name, target in (symlink_entries or {}).items():
            zi = zipfile.ZipInfo(name)
            zi.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(zi, target)
    return buf.getvalue()


def _reference(path: Path, declared_content_type=None) -> interface.ArtifactReference:
    return interface.ArtifactReference(
        source_provider="local_file",
        source_reference=str(path),
        declared_filename=path.name,
        declared_content_type=declared_content_type,
    )


class TestOrdinaryFileHandoff(unittest.TestCase):
    """1. ordinary file handoff. 4. SHA-256 recording."""

    def test_plain_text_file(self):
        with tempfile.TemporaryDirectory() as d:
            content = b"hello forgeworld, this is an ordinary file\n"
            path = _write_fixture(d, "notes.txt", content)
            manifest = interface.handoff(_reference(path), PROVIDER)

            self.assertEqual(manifest.acquisition_state, interface.ACQUISITION_ACQUIRED)
            self.assertEqual(manifest.extraction_state, interface.EXTRACTION_NOT_APPLICABLE)
            self.assertEqual(manifest.safety_disposition, interface.SAFETY_SAFE)
            self.assertEqual(manifest.detected_content_type, "text/plain")
            self.assertEqual(manifest.size, len(content))
            self.assertEqual(manifest.sha256, hashlib.sha256(content).hexdigest())
            self.assertEqual(manifest.parent_artifact_id, None)
            self.assertEqual(manifest.provenance_lineage, ())
            self.assertEqual(manifest.child_artifact_ids, ())


class TestSafeMultiFileZip(unittest.TestCase):
    """2. safe multi-file ZIP. 3. parent/child provenance."""

    def test_safe_zip_produces_children_with_correct_provenance(self):
        entries = {"a.txt": b"alpha", "b.txt": b"beta", "sub/c.txt": b"gamma"}
        data = _zip_bytes(entries)
        with tempfile.TemporaryDirectory() as d:
            path = _write_fixture(d, "bundle.zip", data)
            tree = interface.handoff_tree(_reference(path), PROVIDER)

        root = tree[0]
        children = tree[1:]
        self.assertEqual(root.extraction_state, interface.EXTRACTION_EXTRACTED)
        self.assertEqual(root.safety_disposition, interface.SAFETY_SAFE)
        self.assertEqual(len(children), 3)
        self.assertEqual(set(root.child_artifact_ids), {c.artifact_id for c in children})

        for child in children:
            self.assertEqual(child.parent_artifact_id, root.artifact_id)
            self.assertEqual(child.provenance_lineage, (root.artifact_id,))
            self.assertEqual(child.acquisition_state, interface.ACQUISITION_ACQUIRED)
            self.assertEqual(child.source_provider, root.source_provider)
            self.assertTrue(child.source_reference.startswith(root.source_reference + "!"))

        child_names = {c.filename for c in children}
        self.assertEqual(child_names, set(entries.keys()))

    def test_sha256_recorded_for_root_and_children(self):
        entries = {"only.txt": b"exact content for hashing"}
        data = _zip_bytes(entries)
        with tempfile.TemporaryDirectory() as d:
            path = _write_fixture(d, "one.zip", data)
            tree = interface.handoff_tree(_reference(path), PROVIDER)

        root, child = tree[0], tree[1]
        self.assertEqual(root.sha256, hashlib.sha256(data).hexdigest())
        self.assertEqual(child.sha256, hashlib.sha256(b"exact content for hashing").hexdigest())


class TestUnsupportedTypeHonestFailure(unittest.TestCase):
    """5. unsupported-type honest failure."""

    def test_unclassifiable_binary_gets_no_capability_and_says_why(self):
        # Bytes matching no known magic signature and not valid UTF-8 text.
        content = bytes([0xDE, 0xAD, 0xBE, 0xEF, 0x00, 0x01, 0x02, 0xFF] * 4)
        with tempfile.TemporaryDirectory() as d:
            path = _write_fixture(d, "blob.bin", content)
            manifest = interface.handoff(_reference(path), PROVIDER)

        self.assertEqual(manifest.detected_content_type, "application/octet-stream")
        self.assertEqual(manifest.extraction_state, interface.EXTRACTION_NOT_APPLICABLE)
        self.assertIsNone(manifest.selected_capability)
        self.assertIn("no capability-tag mapping", manifest.routing_note)


class TestArchiveDefenses(unittest.TestCase):
    """6. traversal rejection. 7. unsafe-link rejection. 8. expansion-limit
    rejection. Fail-closed: safe members in the same archive are not
    extracted either."""

    def test_path_traversal_rejected(self):
        data = _zip_bytes({"../../etc/passwd": b"pwned", "safe.txt": b"fine"})
        with tempfile.TemporaryDirectory() as d:
            path = _write_fixture(d, "evil.zip", data)
            manifest = interface.handoff(_reference(path), PROVIDER)

        self.assertEqual(manifest.extraction_state, interface.EXTRACTION_REJECTED)
        self.assertEqual(manifest.safety_disposition, interface.SAFETY_UNSAFE)
        self.assertTrue(any("PATH_TRAVERSAL" in f for f in manifest.safety_findings))
        self.assertEqual(manifest.child_artifact_ids, ())  # fail-closed: safe.txt not extracted either

    def test_absolute_path_rejected(self):
        data = _zip_bytes({"/etc/passwd": b"pwned"})
        with tempfile.TemporaryDirectory() as d:
            path = _write_fixture(d, "abs.zip", data)
            manifest = interface.handoff(_reference(path), PROVIDER)

        self.assertEqual(manifest.extraction_state, interface.EXTRACTION_REJECTED)
        self.assertTrue(any("ABSOLUTE_PATH" in f for f in manifest.safety_findings))

    def test_unsafe_symlink_rejected(self):
        data = _zip_bytes({"safe.txt": b"fine"}, symlink_entries={"link": "/etc/passwd"})
        with tempfile.TemporaryDirectory() as d:
            path = _write_fixture(d, "link.zip", data)
            manifest = interface.handoff(_reference(path), PROVIDER)

        self.assertEqual(manifest.extraction_state, interface.EXTRACTION_REJECTED)
        self.assertTrue(any("UNSAFE_LINK" in f for f in manifest.safety_findings))

    def test_expansion_bomb_rejected_via_member_size_limit(self):
        data = _zip_bytes({"big.txt": b"x" * 1000})
        tiny_limits = zip_unpack.UnpackLimits(max_member_uncompressed_bytes=10)
        with tempfile.TemporaryDirectory() as d:
            path = _write_fixture(d, "bomb.zip", data)
            manifest = interface.handoff(_reference(path), PROVIDER, unpack_limits=tiny_limits)

        self.assertEqual(manifest.extraction_state, interface.EXTRACTION_REJECTED)
        self.assertTrue(any("EXPANSION_BOMB" in f for f in manifest.safety_findings))

    def test_excessive_nesting_rejected(self):
        deep_name = "/".join(["d"] * 20) + "/leaf.txt"
        data = _zip_bytes({deep_name: b"deep"})
        with tempfile.TemporaryDirectory() as d:
            path = _write_fixture(d, "deep.zip", data)
            manifest = interface.handoff(_reference(path), PROVIDER)

        self.assertEqual(manifest.extraction_state, interface.EXTRACTION_REJECTED)
        self.assertTrue(any("EXCESSIVE_NESTING" in f for f in manifest.safety_findings))

    def test_malformed_archive_fails_honestly(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_fixture(d, "corrupt.zip", b"PK\x03\x04not actually a valid zip stream")
            manifest = interface.handoff(_reference(path), PROVIDER)

        self.assertEqual(manifest.detected_content_type, "application/zip")
        self.assertEqual(manifest.extraction_state, interface.EXTRACTION_FAILED)
        self.assertTrue(any("MALFORMED_ARCHIVE" in f for f in manifest.safety_findings))

    def test_unsupported_archive_extension_is_surfaced_not_crashed(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_fixture(d, "data.rar", b"not a zip, not anything this seam parses")
            manifest = interface.handoff(_reference(path), PROVIDER)

        self.assertEqual(manifest.extraction_state, interface.EXTRACTION_NOT_APPLICABLE)
        self.assertEqual(manifest.safety_disposition, interface.SAFETY_UNSUPPORTED)
        self.assertTrue(any("UNSUPPORTED_ARCHIVE_FORMAT" in f for f in manifest.safety_findings))


class TestExtensionContentMismatch(unittest.TestCase):
    """9. extension/content mismatch surfaced (not silently trusted, and
    not treated as fatal)."""

    def test_txt_content_in_a_dot_zip_file_is_flagged(self):
        content = b"this is plain text, not a zip archive"
        with tempfile.TemporaryDirectory() as d:
            path = _write_fixture(d, "definitely_a_zip.zip", content)
            manifest = interface.handoff(_reference(path), PROVIDER)

        self.assertEqual(manifest.declared_content_type, "application/zip")
        self.assertEqual(manifest.detected_content_type, "text/plain")
        self.assertTrue(manifest.content_type_mismatch)
        self.assertEqual(manifest.extraction_state, interface.EXTRACTION_NOT_APPLICABLE)  # never treated as a zip


class TestExtractedContentNeverExecuted(unittest.TestCase):
    """10. extracted content never executed."""

    def test_python_looking_member_is_only_ever_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            marker = Path(d) / "PWNED_MARKER"
            malicious_source = (
                f"import pathlib\n"
                f"pathlib.Path({str(marker)!r}).write_text('PWNED')\n"
            ).encode()
            data = _zip_bytes({"setup.py": malicious_source})
            zpath = _write_fixture(d, "payload.zip", data)

            tree = interface.handoff_tree(_reference(zpath), PROVIDER)

            self.assertFalse(marker.exists(), "extracted member must never be executed")

        child = tree[1]
        self.assertEqual(child.filename, "setup.py")
        self.assertEqual(child.detected_content_type, "text/plain")
        self.assertEqual(child.sha256, hashlib.sha256(malicious_source).hexdigest())


class TestDownstreamRoutingPreservesProvenance(unittest.TestCase):
    """11. downstream routing preserves provenance."""

    PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32  # valid magic, synthetic body

    def _forced_reachable(self):
        return {"forgeworld_mobile_research": {"reachability_confidence": 1.0, "evidence": "forced for test"}}

    def test_root_level_image_routes_to_mobile_research_capability(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_fixture(d, "photo.png", self.PNG_BYTES)
            manifest = interface.handoff(_reference(path), PROVIDER, reachability_state=self._forced_reachable())

        self.assertEqual(manifest.detected_content_type, "image/png")
        self.assertEqual(manifest.selected_capability, "forgeworld_mobile_research")
        self.assertEqual(manifest.provenance_lineage, ())

    def test_nested_image_in_zip_routes_and_keeps_child_provenance(self):
        data = _zip_bytes({"photo.png": self.PNG_BYTES})
        with tempfile.TemporaryDirectory() as d:
            path = _write_fixture(d, "album.zip", data)
            tree = interface.handoff_tree(_reference(path), PROVIDER, reachability_state=self._forced_reachable())

        root, child = tree[0], tree[1]
        self.assertEqual(child.detected_content_type, "image/png")
        self.assertEqual(child.selected_capability, "forgeworld_mobile_research")
        self.assertEqual(child.parent_artifact_id, root.artifact_id)
        self.assertEqual(child.provenance_lineage, (root.artifact_id,))

    def test_without_forced_reachability_routing_is_honestly_none(self):
        # In this sandbox tesseract is genuinely absent, so without forcing
        # reachability, forgeworld_mobile_research is honestly unreachable
        # and routing must not pretend otherwise.
        with tempfile.TemporaryDirectory() as d:
            path = _write_fixture(d, "photo.png", self.PNG_BYTES)
            manifest = interface.handoff(_reference(path), PROVIDER)  # no reachability_state override

        self.assertEqual(manifest.detected_content_type, "image/png")
        self.assertIsNone(manifest.selected_capability)
        self.assertIn("no reachable capability", manifest.routing_note)


class TestNoAuthorityOrEvidencePromotion(unittest.TestCase):
    """12. no authority/evidence promotion -- structurally, for both
    success and failure manifests, and unconstructable any other way."""

    def _assert_fixed_invariants(self, manifest: interface.Manifest):
        self.assertEqual(manifest.trust_status, interface.TRUST_STATUS)
        self.assertEqual(manifest.execution_status, interface.EXECUTION_STATUS)
        self.assertEqual(manifest.validation_status, interface.VALIDATION_STATUS)
        self.assertEqual(manifest.evidence_status, interface.EVIDENCE_STATUS)
        self.assertEqual(manifest.authority_status, interface.AUTHORITY_STATUS)
        self.assertEqual(manifest.promotion_status, interface.PROMOTION_STATUS)

    def test_successful_manifest_carries_fixed_invariants(self):
        with tempfile.TemporaryDirectory() as d:
            path = _write_fixture(d, "ok.txt", b"fine")
            manifest = interface.handoff(_reference(path), PROVIDER)
        self._assert_fixed_invariants(manifest)

    def test_rejected_archive_manifest_carries_fixed_invariants(self):
        data = _zip_bytes({"/abs.txt": b"pwned"})
        with tempfile.TemporaryDirectory() as d:
            path = _write_fixture(d, "bad.zip", data)
            manifest = interface.handoff(_reference(path), PROVIDER)
        self._assert_fixed_invariants(manifest)

    def test_unreachable_source_manifest_carries_fixed_invariants(self):
        reference = interface.ArtifactReference(
            source_provider="local_file", source_reference="/nonexistent/path/ghost.txt"
        )
        manifest = interface.handoff(reference, PROVIDER)
        self.assertEqual(manifest.acquisition_state, interface.ACQUISITION_UNREACHABLE)
        self._assert_fixed_invariants(manifest)

    def test_invariant_properties_cannot_be_overridden_via_constructor(self):
        with self.assertRaises(TypeError):
            interface.Manifest(
                artifact_id="ART-x", parent_artifact_id=None, source_provider="local_file",
                source_reference="x", filename="x", declared_content_type="text/plain",
                detected_content_type="text/plain", size=0, sha256="0" * 64,
                acquisition_state=interface.ACQUISITION_ACQUIRED,
                extraction_state=interface.EXTRACTION_NOT_APPLICABLE,
                safety_disposition=interface.SAFETY_SAFE, selected_capability=None,
                provenance_lineage=(), content_type_mismatch=False, routing_note="",
                safety_findings=(), error_detail=None, child_artifact_ids=(),
                evidence_status="EVIDENCE",  # not a real constructor field
            )


class TestNoNetworkOrExternalAccess(unittest.TestCase):
    """Confirms routing never invokes mission_router.route() (which would
    write router/decisions.jsonl) and never calls discover.write_state()
    (which would write capabilities/state.json) -- both live operational
    files this seam must not touch."""

    def test_route_to_capability_never_calls_router_route_or_write_state(self):
        import unittest.mock as mock
        from router import mission_router  # noqa: E402
        from capabilities import discover  # noqa: E402

        with mock.patch.object(mission_router, "route", side_effect=AssertionError("must not call route()")), \
             mock.patch.object(discover, "write_state", side_effect=AssertionError("must not call write_state()")):
            with tempfile.TemporaryDirectory() as d:
                path = _write_fixture(d, "photo.png", TestDownstreamRoutingPreservesProvenance.PNG_BYTES)
                manifest = interface.handoff(_reference(path), PROVIDER)
        self.assertEqual(manifest.detected_content_type, "image/png")


if __name__ == "__main__":
    unittest.main()
