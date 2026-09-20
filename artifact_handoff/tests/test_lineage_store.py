"""Tests for FW-DURABLE-ARTIFACT-LINEAGE-001 (Microphase 01 of
FW-PERMANENT-OFFLINE-SUBSTRATE-001).

Stdlib `unittest` (same precedent as every other test file in this
program: no pytest installed, installing it is out of scope).

All fixtures are synthetic and local; nothing here touches a network,
Gmail, Drive, or a real external artifact.
"""
import io
import sys
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

ARTIFACT_HANDOFF_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = ARTIFACT_HANDOFF_DIR.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from artifact_handoff import interface  # noqa: E402
from artifact_handoff import zip_unpack  # noqa: E402 -- registers the zip adapter as an import side effect
from evidence_envelope import envelope  # noqa: E402
from artifact_handoff.lineage_store import LineageStore, LineageConflictError  # noqa: E402
from artifact_handoff.local_file_provider import LocalFileAcquisitionProvider  # noqa: E402

PROVIDER = LocalFileAcquisitionProvider()


def _reference(path: Path) -> interface.ArtifactReference:
    return interface.ArtifactReference(
        source_provider="local_file", source_reference=str(path), declared_filename=path.name,
    )


def _sample_manifest_dict(artifact_id="ART-sample0000000000000000000001", **overrides) -> dict:
    manifest = interface.Manifest(
        artifact_id=artifact_id, parent_artifact_id=None, source_provider="local_file",
        source_reference="/tmp/x.txt", filename="x.txt", declared_content_type="text/plain",
        detected_content_type="text/plain", size=4, sha256="0" * 64,
        acquisition_state=interface.ACQUISITION_ACQUIRED, extraction_state=interface.EXTRACTION_NOT_APPLICABLE,
        safety_disposition=interface.SAFETY_SAFE, selected_capability=None, provenance_lineage=(),
        content_type_mismatch=False, routing_note="test", safety_findings=(), error_detail=None,
        child_artifact_ids=(),
    )
    d = manifest.to_dict()
    d.update(overrides)
    return d


class TestPersistenceSurvivesRestart(unittest.TestCase):
    def test_new_store_instance_over_same_root_sees_prior_records(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "lineage"
            store_a = LineageStore(root)
            record = _sample_manifest_dict()
            store_a.record(record)

            store_b = LineageStore(root)  # simulates a fresh process re-opening the same root
            self.assertEqual(store_b.get(record["artifact_id"]), record)
            self.assertEqual(store_b.list_all(), [record])

    def test_handoff_lineage_store_persists_across_a_fresh_store_instance(self):
        with tempfile.TemporaryDirectory() as d:
            lineage_root = Path(d) / "lineage"
            fixture_path = Path(d) / "note.txt"
            fixture_path.write_bytes(b"durable artifact content")

            store_a = LineageStore(lineage_root)
            manifest = interface.handoff(_reference(fixture_path), PROVIDER, lineage_store=store_a)

            store_b = LineageStore(lineage_root)
            reloaded = store_b.get(manifest.artifact_id)
            self.assertIsNotNone(reloaded)
            self.assertEqual(reloaded["sha256"], manifest.sha256)
            self.assertEqual(reloaded["detected_content_type"], "text/plain")


class TestDuplicateIdentityIsDeterministic(unittest.TestCase):
    def test_identical_record_twice_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            store = LineageStore(Path(d))
            record = _sample_manifest_dict()
            first = store.record(record)
            second = store.record(dict(record))  # equal but distinct dict object
            self.assertEqual(first, second)
            self.assertEqual(len(store.list_all()), 1)

    def test_conflicting_record_same_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            store = LineageStore(Path(d))
            record = _sample_manifest_dict()
            store.record(record)
            conflicting = _sample_manifest_dict(sha256="1" * 64)
            with self.assertRaises(LineageConflictError):
                store.record(conflicting)
            # ledger must be unchanged by the rejected write
            self.assertEqual(len(store.list_all()), 1)
            self.assertEqual(store.get(record["artifact_id"])["sha256"], "0" * 64)


class TestLineageReconstruction(unittest.TestCase):
    def test_multi_level_tree_ancestors_and_descendants(self):
        inner = _zip_bytes({"leaf.txt": b"leaf"})
        outer = _zip_bytes({"inner.zip": inner})
        with tempfile.TemporaryDirectory() as d:
            lineage_root = Path(d) / "lineage"
            fixture = Path(d) / "outer.zip"
            fixture.write_bytes(outer)

            store = LineageStore(lineage_root)
            tree = interface.handoff_tree(
                _reference(fixture), PROVIDER, lineage_store=store, max_unpack_depth=2,
            )
            root = tree[0]
            inner_manifest = next(m for m in tree if m.filename == "inner.zip")
            leaf_manifest = next(m for m in tree if m.filename == "leaf.txt")

            reconstructed = store.reconstruct_lineage(leaf_manifest.artifact_id)
            self.assertIsNotNone(reconstructed)
            self.assertEqual(reconstructed["ancestor_ids"], [root.artifact_id, inner_manifest.artifact_id])
            self.assertEqual(reconstructed["descendants"], [])  # leaf has none

            root_reconstructed = store.reconstruct_lineage(root.artifact_id)
            descendant_ids = {r["artifact_id"] for r in root_reconstructed["descendants"]}
            self.assertEqual(descendant_ids, {inner_manifest.artifact_id, leaf_manifest.artifact_id})

    def test_unknown_artifact_id_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            store = LineageStore(Path(d))
            self.assertIsNone(store.reconstruct_lineage(interface.new_artifact_id()))


class TestCorruptionIsDetected(unittest.TestCase):
    def test_truncated_final_line_raises_ledger_integrity_error(self):
        with tempfile.TemporaryDirectory() as d:
            store = LineageStore(Path(d))
            store.record(_sample_manifest_dict())
            # Corrupt: strip the trailing newline evidence_envelope's own
            # tests already treat as a truncated/partial write.
            raw = store.ledger_path.read_bytes()
            store.ledger_path.write_bytes(raw.rstrip(b"\n"))

            with self.assertRaises(envelope.LedgerIntegrityError):
                store.list_all()

    def test_invalid_json_line_raises_ledger_integrity_error(self):
        with tempfile.TemporaryDirectory() as d:
            store = LineageStore(Path(d))
            store.record(_sample_manifest_dict())
            with open(store.ledger_path, "a") as f:
                f.write("{not valid json\n")

            with self.assertRaises(envelope.LedgerIntegrityError):
                store.list_all()

    def test_missing_artifact_id_field_raises_ledger_integrity_error(self):
        with tempfile.TemporaryDirectory() as d:
            store = LineageStore(Path(d))
            with open(store.ledger_path, "w") as f:
                f.write('{"not_artifact_id": "x"}\n')

            with self.assertRaises(envelope.LedgerIntegrityError):
                store.list_all()


class TestConcurrentWritesDoNotCorrupt(unittest.TestCase):
    def test_concurrent_threaded_writers_all_land(self):
        with tempfile.TemporaryDirectory() as d:
            store = LineageStore(Path(d))
            n = 20
            records = [
                _sample_manifest_dict(artifact_id=f"ART-concurrent{i:04d}", sha256=f"{i:064d}")
                for i in range(n)
            ]
            errors = []

            def worker(rec):
                try:
                    store.record(rec)
                except Exception as exc:  # noqa: BLE001 -- captured for the assertion below
                    errors.append(exc)

            threads = [threading.Thread(target=worker, args=(r,)) for r in records]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            self.assertEqual(errors, [])
            all_records = store.list_all()  # must not raise LedgerIntegrityError
            self.assertEqual(len(all_records), n)
            self.assertEqual({r["artifact_id"] for r in all_records}, {r["artifact_id"] for r in records})


class TestPersistenceCreatesNoEvidenceOrAuthorityPromotion(unittest.TestCase):
    def test_round_tripped_record_keeps_manifest_invariants_unchanged(self):
        with tempfile.TemporaryDirectory() as d:
            fixture = Path(d) / "note.txt"
            fixture.write_bytes(b"plain content")
            store = LineageStore(Path(d) / "lineage")

            manifest = interface.handoff(_reference(fixture), PROVIDER, lineage_store=store)
            reloaded = store.get(manifest.artifact_id)

            for field in (
                "trust_status", "execution_status", "validation_status",
                "evidence_status", "authority_status", "promotion_status",
            ):
                self.assertEqual(reloaded[field], getattr(manifest, field))
            self.assertEqual(reloaded["evidence_status"], interface.EVIDENCE_STATUS)
            self.assertEqual(reloaded["promotion_status"], interface.PROMOTION_STATUS)
            self.assertEqual(reloaded["authority_status"], interface.AUTHORITY_STATUS)

    def test_lineage_store_module_never_uses_envelope_store(self):
        # Parses the AST rather than grepping raw text: the module
        # docstring legitimately *discusses* EnvelopeStore in English (a
        # string literal, invisible to the AST's Name/Attribute/Import
        # nodes), but the actual code must never import, name, or call it.
        import ast

        source = (ARTIFACT_HANDOFF_DIR / "lineage_store.py").read_text()
        tree = ast.parse(source)
        forbidden_names = {"EnvelopeStore", "GOLD_VALIDATED", "record_promotion_authority"}
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in forbidden_names:
                found.add(node.id)
            elif isinstance(node, ast.Attribute) and node.attr in forbidden_names:
                found.add(node.attr)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    if alias.name in forbidden_names:
                        found.add(alias.name)
        self.assertEqual(found, set(), f"lineage_store.py code must not use {found}")


def _zip_bytes(entries: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return buf.getvalue()


if __name__ == "__main__":
    unittest.main()
