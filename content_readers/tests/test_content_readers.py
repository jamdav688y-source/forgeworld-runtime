"""Tests for FW-UNIVERSAL-CONTENT-READERS-001 (Microphase 02 of
FW-PERMANENT-OFFLINE-SUBSTRATE-001).

Stdlib `unittest` (same precedent as every other test file in this
program). All fixtures are synthetic and local; nothing here touches a
network, Gmail, Drive, or a real external artifact.

Import note: this file needs BOTH content_readers.interface and
artifact_handoff.interface loaded in the same process -- the only place
in this program that does. Both are now package-qualified imports
(FW-PYTHON-NAMESPACE-STABILIZATION-001), so they resolve to distinct
sys.modules keys ("content_readers.interface" vs "artifact_handoff.interface")
and can never shadow each other, regardless of import order.
"""
import hashlib
import io
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

CONTENT_READERS_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = CONTENT_READERS_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from content_readers import interface as ci  # noqa: E402
from content_readers import text_readers  # noqa: E402,F401 -- registers readers as an import side effect
from content_readers import html_reader  # noqa: E402,F401
from content_readers import image_metadata_reader  # noqa: E402,F401
from content_readers import archive_reader  # noqa: E402,F401

from artifact_handoff import interface as ah  # noqa: E402
from artifact_handoff import zip_unpack  # noqa: E402,F401
from artifact_handoff.local_file_provider import LocalFileAcquisitionProvider  # noqa: E402

AH_PROVIDER = LocalFileAcquisitionProvider()


def _png_bytes(width: int, height: int) -> bytes:
    """A minimal, valid PNG header (signature + IHDR chunk) with no real
    pixel data -- enough for image_metadata_reader to parse dimensions,
    nothing that could be decoded as an actual image."""
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr_data = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes([8, 2, 0, 0, 0])
    ihdr = (13).to_bytes(4, "big") + b"IHDR" + ihdr_data
    return sig + ihdr + b"\x00" * 16  # trailing padding; no real chunk CRCs needed for this reader


def _request(data: bytes, detected="text/plain", **overrides) -> ci.ContentReadRequest:
    defaults = dict(
        artifact_id="ART-testcontentread0000000001",
        data=data,
        detected_content_type=detected,
        source_sha256=hashlib.sha256(data).hexdigest(),
    )
    defaults.update(overrides)
    return ci.ContentReadRequest(**defaults)


class TestPlainText(unittest.TestCase):
    """A. UTF-8 text."""

    def test_utf8_text_is_read(self):
        result = ci.read_content(_request(b"hello world\nsecond line\n"))
        self.assertEqual(result.status, ci.READ_OK)
        self.assertEqual(result.reader_id, "plain_text_reader")
        self.assertEqual(result.text_content, "hello world\nsecond line\n")
        self.assertFalse(result.truncated)


class TestMarkdown(unittest.TestCase):
    """B. Markdown."""

    def test_markdown_headings_counted_structurally(self):
        data = b"# Title\n\nSome body text.\n## Sub\nmore text\n"
        result = ci.read_content(_request(data, filename="notes.md"))
        self.assertEqual(result.status, ci.READ_OK)
        self.assertEqual(result.reader_id, "markdown_reader")
        self.assertEqual(result.metadata["heading_count"], 2)


class TestJSON(unittest.TestCase):
    """C. valid JSON. D. malformed JSON fails honestly. K. extension/content
    mismatch remains surfaced."""

    def test_valid_json_is_parsed(self):
        data = b'{"a": 1, "b": [1, 2, 3]}'
        result = ci.read_content(_request(data, filename="data.json"))
        self.assertEqual(result.status, ci.READ_OK)
        self.assertEqual(result.reader_id, "json_reader")
        self.assertEqual(result.structured_content, {"a": 1, "b": [1, 2, 3]})
        self.assertEqual(result.metadata["key_count"], 2)

    def test_malformed_json_fails_honestly(self):
        data = b'{"a": 1,'  # truncated, invalid
        result = ci.read_content(_request(data, filename="broken.json"))
        self.assertEqual(result.status, ci.READ_MALFORMED)
        self.assertIsNone(result.structured_content)
        self.assertTrue(any("does not parse as valid JSON" in e for e in result.errors))

    def test_extension_content_mismatch_is_surfaced_by_reader(self):
        # Named .json, but the bytes are ordinary prose -- routing follows
        # the filename hint (as designed), and the JSON reader's own
        # honest failure is what surfaces the mismatch.
        data = b"This is just a note, not JSON at all."
        result = ci.read_content(_request(data, filename="fake.json"))
        self.assertEqual(result.status, ci.READ_MALFORMED)
        self.assertEqual(result.reader_id, "json_reader")
        self.assertTrue(any("routed to the JSON reader" in e for e in result.errors))


class TestYAML(unittest.TestCase):
    """YAML is one of the ten initial format targets (PyYAML is already
    present in this environment); not in the lettered A-O matrix, but
    tested here so the format-support matrix reflects real coverage."""

    def test_valid_yaml_is_parsed_via_safe_load_only(self):
        data = b"a: 1\nb:\n  - x\n  - y\n"
        result = ci.read_content(_request(data, filename="config.yaml"))
        self.assertEqual(result.status, ci.READ_OK)
        self.assertEqual(result.reader_id, "yaml_reader")
        self.assertEqual(result.structured_content, {"a": 1, "b": ["x", "y"]})
        self.assertEqual(result.metadata["parser"], "yaml.safe_load")

    def test_malformed_yaml_fails_honestly(self):
        data = b"a: [1, 2\nb: {c: d\n"  # unbalanced flow collections
        result = ci.read_content(_request(data, filename="broken.yaml"))
        self.assertEqual(result.status, ci.READ_MALFORMED)
        self.assertTrue(any("does not parse as valid YAML" in e for e in result.errors))


class TestCSV(unittest.TestCase):
    """E. CSV."""

    def test_csv_rows_are_read(self):
        data = b"a,b,c\n1,2,3\n4,5,6\n"
        result = ci.read_content(_request(data, filename="table.csv"))
        self.assertEqual(result.status, ci.READ_OK)
        self.assertEqual(result.reader_id, "csv_reader")
        self.assertEqual(result.structured_content, [["a", "b", "c"], ["1", "2", "3"], ["4", "5", "6"]])
        self.assertEqual(result.metadata["row_count"], 3)


class TestHTML(unittest.TestCase):
    """F. HTML converted/read without executing embedded content."""

    def test_html_extracted_without_executing_script(self):
        data = (
            b"<html><head><title>Hi</title></head><body>"
            b"<p>Hello world</p>"
            b"<script>document.write('PWNED');alert(1)</script>"
            b"<a href='https://example.invalid/x'>link</a>"
            b"</body></html>"
        )
        result = ci.read_content(_request(data, filename="page.html"))
        self.assertEqual(result.status, ci.READ_OK)
        self.assertEqual(result.reader_id, "html_reader")
        self.assertEqual(result.structured_content["title"], "Hi")
        self.assertIn("Hello world", result.text_content)
        self.assertNotIn("PWNED", result.text_content)
        self.assertNotIn("document.write", result.text_content)
        self.assertEqual(result.structured_content["links"], ["https://example.invalid/x"])


class TestSourceCode(unittest.TestCase):
    """G. source code treated strictly as data."""

    def test_python_source_is_data_only_never_imported(self):
        data = b"import os\ndef f():\n    return os.system('echo pwned')\n"
        result = ci.read_content(_request(data, filename="mod.py"))
        self.assertEqual(result.status, ci.READ_OK)
        self.assertEqual(result.reader_id, "source_code_reader")
        self.assertEqual(result.metadata["language_hint"], "python")
        self.assertIn("os.system", result.text_content)  # present as literal text
        self.assertNotIn("mod", sys.modules)  # never imported as a module


class TestImageMetadata(unittest.TestCase):
    """H. image metadata without image execution/transformation."""

    def test_png_dimensions_parsed_without_decoding_pixels(self):
        data = _png_bytes(width=800, height=600)
        result = ci.read_content(_request(data, detected="image/png"))
        self.assertEqual(result.status, ci.READ_OK)
        self.assertEqual(result.reader_id, "image_metadata_reader")
        self.assertEqual(result.metadata["width"], 800)
        self.assertEqual(result.metadata["height"], 600)
        self.assertTrue(result.metadata["dimensions_parsed"])
        self.assertNotIn("pixels", result.metadata)
        self.assertNotIn("pixel_data", result.metadata)


class TestArchiveInventoryDelegatesToArtifactHandoff(unittest.TestCase):
    """I. archive inventory delegates/reuses artifact_handoff."""

    def _zip_bytes(self, entries: dict) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            for name, content in entries.items():
                zf.writestr(name, content)
        return buf.getvalue()

    def test_inventory_matches_real_handoff_children_and_never_reparses_bytes(self):
        entries = {"a.txt": b"alpha", "b.txt": b"beta"}
        zip_data = self._zip_bytes(entries)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "bundle.zip"
            path.write_bytes(zip_data)
            reference = ah.ArtifactReference(source_provider="local_file", source_reference=str(path), declared_filename=path.name)
            tree = ah.handoff_tree(reference, AH_PROVIDER)

        root, children = tree[0], tree[1:]
        request = ci.build_request_from_manifest(
            root.to_dict(),
            data=b"THIS IS DELIBERATELY NOT VALID ZIP DATA",  # proves the reader ignores it
            child_manifest_dicts=tuple(c.to_dict() for c in children),
        )
        result = ci.read_content(request)
        self.assertEqual(result.status, ci.READ_OK)
        self.assertEqual(result.reader_id, "archive_inventory_reader")
        self.assertEqual(result.metadata["member_count"], 2)
        self.assertEqual({m["filename"] for m in result.structured_content}, {"a.txt", "b.txt"})
        self.assertEqual(
            {m["artifact_id"] for m in result.structured_content}, {c.artifact_id for c in children}
        )

    def test_no_child_manifests_is_honest_unsupported(self):
        request = ci.build_request_from_manifest(
            {"artifact_id": "ART-nozipchildren000000001", "detected_content_type": "application/zip", "sha256": "0" * 64},
            data=b"PK\x03\x04irrelevant",
        )
        result = ci.read_content(request)
        self.assertEqual(result.status, ci.READ_UNSUPPORTED)
        self.assertEqual(result.reader_id, "archive_inventory_reader")


class TestUnsupportedBinaryFailsHonestly(unittest.TestCase):
    """J. unsupported binary fails honestly."""

    def test_unclassifiable_binary_is_unsupported(self):
        data = bytes([0xDE, 0xAD, 0xBE, 0xEF, 0x00, 0x01] * 4)
        result = ci.read_content(_request(data, detected="application/octet-stream"))
        self.assertEqual(result.status, ci.READ_UNSUPPORTED)
        self.assertIn("application/octet-stream", result.errors[0])


class TestPDFUnsupported(unittest.TestCase):
    """PDF: no safe local parser is installed -> explicitly unsupported,
    dependency gap recorded, never attempted with an unsafe parser."""

    def test_pdf_signature_is_always_unsupported_even_if_it_decodes_as_text(self):
        # An all-ASCII synthetic PDF skeleton: would decode as valid UTF-8
        # (so artifact_handoff's own byte-sniffer would call it text/plain),
        # but the %PDF- signature must win regardless.
        data = b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n"
        self.assertEqual(ah.detect_content_type(data), "text/plain")  # confirms the trap this guards against
        result = ci.read_content(_request(data, detected="text/plain", filename="doc.pdf"))
        self.assertEqual(result.status, ci.READ_UNSUPPORTED)
        self.assertEqual(result.content_type, "application/pdf")
        self.assertIn("no safe local PDF parser", result.errors[0])


class TestSizeAndOutputLimits(unittest.TestCase):
    """L. size/output limit produces explicit truncation/failure."""

    def test_output_char_limit_truncates_explicitly(self):
        data = ("x" * 500).encode()
        limits = ci.ReadLimits(max_output_chars=100)
        result = ci.read_content(_request(data, limits=limits))
        self.assertEqual(result.status, ci.READ_OK)
        self.assertTrue(result.truncated)
        self.assertIsNotNone(result.truncation_detail)
        self.assertEqual(len(result.text_content), 100)

    def test_input_byte_limit_fails_explicitly(self):
        data = b"x" * 50
        limits = ci.ReadLimits(max_input_bytes=10)
        result = ci.read_content(_request(data, limits=limits))
        self.assertEqual(result.status, ci.READ_FAILED)
        self.assertTrue(result.truncated)
        self.assertIn("exceeds max_input_bytes", result.errors[0])

    def test_csv_row_limit_truncates_explicitly(self):
        data = "\n".join(f"{i},{i}" for i in range(20)).encode()
        limits = ci.ReadLimits(max_csv_rows=5)
        result = ci.read_content(_request(data, filename="big.csv", limits=limits))
        self.assertEqual(result.status, ci.READ_OK)
        self.assertTrue(result.truncated)
        self.assertEqual(result.metadata["row_count"], 5)


class TestProvenanceSurvivesReading(unittest.TestCase):
    """M. provenance/artifact identity survives reading."""

    def test_provenance_reference_and_digest_preserved(self):
        data = b"provenance check content"
        digest = hashlib.sha256(data).hexdigest()
        result = ci.read_content(_request(data, source_sha256=digest, artifact_id="ART-provcheck00000000001"))
        self.assertEqual(result.artifact_id, "ART-provcheck00000000001")
        self.assertEqual(result.provenance_reference, "ART-provcheck00000000001")
        self.assertEqual(result.source_sha256, digest)


class TestNoEvidenceAuthorityOrPromotionMutation(unittest.TestCase):
    """N. no evidence/authority/promotion mutation."""

    def _assert_fixed(self, result: ci.ContentReadResult):
        self.assertEqual(result.interpretation_status, ci.INTERPRETATION_STATUS)
        self.assertEqual(result.verification_status, ci.VERIFICATION_STATUS)
        self.assertEqual(result.trust_status, ci.TRUST_STATUS)
        self.assertEqual(result.truth_status, ci.TRUTH_STATUS)
        self.assertEqual(result.evidence_status, ci.EVIDENCE_STATUS)
        self.assertEqual(result.authority_status, ci.AUTHORITY_STATUS)
        self.assertEqual(result.promotion_status, ci.PROMOTION_STATUS)

    def test_successful_read_carries_fixed_invariants(self):
        self._assert_fixed(ci.read_content(_request(b"fine content")))

    def test_malformed_read_carries_fixed_invariants(self):
        self._assert_fixed(ci.read_content(_request(b'{"a":', filename="x.json")))

    def test_unsupported_read_carries_fixed_invariants(self):
        self._assert_fixed(ci.read_content(_request(b"\x00\x01\x02", detected="application/octet-stream")))

    def test_invariant_properties_cannot_be_overridden_via_constructor(self):
        with self.assertRaises(TypeError):
            ci.ContentReadResult(
                artifact_id="ART-x", reader_id="x", reader_version="1", content_type="text/plain",
                status=ci.READ_OK, structured_content=None, text_content="x", metadata={},
                provenance_reference="ART-x", warnings=(), errors=(), truncated=False,
                evidence_status="EVIDENCE",  # not a real constructor field
            )


class TestDeterministicRepeatedRead(unittest.TestCase):
    """O. deterministic repeated read where source is unchanged."""

    def test_two_reads_of_identical_request_agree_except_timestamp(self):
        request = _request(b'{"a": 1, "b": [true, false, null]}', filename="stable.json")
        first = ci.read_content(request).to_dict()
        second = ci.read_content(request).to_dict()
        first.pop("generated_at")
        second.pop("generated_at")
        self.assertEqual(first, second)


class TestConcurrentReadsAreIndependent(unittest.TestCase):
    """Bonus robustness check: concurrent reads through the shared READERS
    registry don't interfere with each other (the registry is populated
    once at import time and only ever read from during read_content())."""

    def test_many_concurrent_reads_all_succeed_correctly(self):
        results = []
        errors = []

        def worker(i):
            try:
                data = f'{{"n": {i}}}'.encode()
                r = ci.read_content(_request(data, artifact_id=f"ART-concurrentread{i:04d}", filename="n.json"))
                results.append((i, r))
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 20)
        for i, r in results:
            self.assertEqual(r.status, ci.READ_OK)
            self.assertEqual(r.structured_content, {"n": i})


if __name__ == "__main__":
    unittest.main()
