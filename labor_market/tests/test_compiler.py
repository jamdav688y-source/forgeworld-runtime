"""Tests for the Labor-Market Capability Compiler.

Covers: the compliance boundary (only permitted source_types are accepted),
posting ingestion idempotency/conflict handling, and the deterministic
extract -> classify pipeline against a small, explicit registry/reachability/
history fixture so classification tests never depend on this machine's
actual installed tools.
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import compiler  # noqa: E402


FIXTURE_REGISTRY = [
    {
        "id": "claude_code",
        "tags": ["code_generation", "debugging", "git_operations"],
        "check": {"type": "command", "value": "claude"},
    },
    {
        "id": "zapier",
        "tags": ["workflow_automation"],
        "check": {"type": "manual"},
    },
    {
        "id": "chatgpt",
        "tags": ["research"],
        "check": {"type": "env", "value": "OPENAI_API_KEY"},
    },
    {
        "id": "ollama",
        "tags": ["offline_inference"],
        "check": {"type": "command", "value": "ollama"},
    },
]

FIXTURE_REACHABILITY = {
    "claude_code": {"reachability_confidence": 1.0},
    "zapier": {"reachability_confidence": 0.5},
    "chatgpt": {"reachability_confidence": 0.0},
    "ollama": {"reachability_confidence": 0.0},
}

FIXTURE_HISTORY = [
    {"capability_id": "claude_code", "mission_class": "code_generation", "success_score": 1.0},
]

SAMPLE_POSTING_TEXT = """\
- Implement Microsoft 365 Copilot for enterprise clients.
- Write code and debug Python automation scripts using Git for version control.
- Support enterprise AI deployment across business units.
- Approve final deployment decisions for production rollouts.
- Use Zapier to automate recurring workflow automation tasks.
- Answer ad-hoc research questions from stakeholders.
- Wrangle the flux capacitor during onsite visits.
"""


@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    postings_dir = tmp_path / "postings"
    reports_dir = tmp_path / "reports"
    monkeypatch.setattr(compiler, "POSTINGS_DIR", postings_dir)
    monkeypatch.setattr(compiler, "REPORTS_DIR", reports_dir)
    return postings_dir, reports_dir


# ---------------------------------------------------------------------------
# compliance boundary
# ---------------------------------------------------------------------------

def test_rejects_unsupported_source_type(isolated_dirs):
    with pytest.raises(compiler.UnsupportedSourceError):
        compiler.ingest_posting("P1", "some text", "linkedin_scrape", "https://linkedin.com/jobs/1")


def test_rejects_automated_scrape_label_even_if_plausible(isolated_dirs):
    with pytest.raises(compiler.UnsupportedSourceError):
        compiler.ingest_posting("P1", "some text", "automated_crawl", "https://example.com/careers")


@pytest.mark.parametrize("source_type", compiler.ALLOWED_SOURCE_TYPES)
def test_accepts_every_permitted_source_type(isolated_dirs, source_type):
    record = compiler.ingest_posting(f"P-{source_type}", "some text", source_type, "ref")
    assert record["source_type"] == source_type


# ---------------------------------------------------------------------------
# ingestion identity / conflict handling
# ---------------------------------------------------------------------------

def test_ingest_is_idempotent_for_identical_content(isolated_dirs):
    first = compiler.ingest_posting("P1", "identical text", "manual_paste", "ref")
    second = compiler.ingest_posting("P1", "identical text", "manual_paste", "ref")
    assert first == second


def test_ingest_conflicts_on_different_content_same_id(isolated_dirs):
    compiler.ingest_posting("P1", "version A", "manual_paste", "ref")
    with pytest.raises(compiler.PostingConflictError):
        compiler.ingest_posting("P1", "version B", "manual_paste", "ref")


def test_ingest_rejects_empty_text(isolated_dirs):
    with pytest.raises(compiler.LaborMarketError):
        compiler.ingest_posting("P1", "   ", "manual_paste", "ref")


def test_invalid_posting_id_rejected(isolated_dirs):
    with pytest.raises(compiler.InvalidPostingIdError):
        compiler.ingest_posting("../etc/passwd", "text", "manual_paste", "ref")


def test_compile_report_requires_prior_ingestion(isolated_dirs):
    with pytest.raises(compiler.PostingNotFoundError):
        compiler.load_posting("never-ingested")


# ---------------------------------------------------------------------------
# extraction (pure)
# ---------------------------------------------------------------------------

def test_extraction_does_not_false_positive_on_substrings():
    taxonomy = [{"phrase": "test", "tag": "testing", "label": "x"}]
    specs = compiler.extract_capability_specs("We ship the latest greatest build.", taxonomy)
    # "test" must not match inside "latest"/"greatest" -- word-boundary only.
    assert all(spec["kind"] != "capability_claim" for spec in specs)


def test_unmapped_claim_is_not_silently_dropped():
    taxonomy = [{"phrase": "git", "tag": "git_operations", "label": "x"}]
    specs = compiler.extract_capability_specs("- Wrangle the flux capacitor.\n", taxonomy)
    assert len(specs) == 1
    assert specs[0]["kind"] == "unmapped"


def test_judgment_and_capability_claim_can_coexist_on_one_line():
    taxonomy = [{"phrase": "deployment", "tag": "deployment", "label": "x"}]
    specs = compiler.extract_capability_specs("Approve final deployment decisions.", taxonomy)
    kinds = {spec["kind"] for spec in specs}
    assert "operator_judgment" in kinds
    assert "capability_claim" in kinds


# ---------------------------------------------------------------------------
# classification against an explicit, hermetic fixture
# ---------------------------------------------------------------------------

def test_classify_proven_requires_reachability_and_history():
    state, _ = compiler.classify_tag(
        "code_generation", FIXTURE_REGISTRY, FIXTURE_REACHABILITY, FIXTURE_HISTORY
    )
    assert state == compiler.PROVEN


def test_classify_available_unproven_when_reachable_but_no_history():
    state, _ = compiler.classify_tag(
        "git_operations", FIXTURE_REGISTRY, FIXTURE_REACHABILITY, FIXTURE_HISTORY
    )
    assert state == compiler.AVAILABLE_UNPROVEN


def test_classify_connector_required_for_manual_check():
    state, _ = compiler.classify_tag(
        "workflow_automation", FIXTURE_REGISTRY, FIXTURE_REACHABILITY, FIXTURE_HISTORY
    )
    assert state == compiler.CONNECTOR_REQUIRED


def test_classify_platform_blocked_for_unreachable_env_check():
    state, _ = compiler.classify_tag(
        "research", FIXTURE_REGISTRY, FIXTURE_REACHABILITY, FIXTURE_HISTORY
    )
    assert state == compiler.PLATFORM_BLOCKED


def test_classify_partial_for_unreachable_command_check():
    state, _ = compiler.classify_tag(
        "offline_inference", FIXTURE_REGISTRY, FIXTURE_REACHABILITY, FIXTURE_HISTORY
    )
    assert state == compiler.PARTIAL


def test_classify_missing_when_no_capability_declares_tag():
    state, _ = compiler.classify_tag(
        "enterprise_copilot_deployment", FIXTURE_REGISTRY, FIXTURE_REACHABILITY, FIXTURE_HISTORY
    )
    assert state == compiler.MISSING


# ---------------------------------------------------------------------------
# end-to-end report compilation against the fixture registry
# ---------------------------------------------------------------------------

def test_compile_report_end_to_end(isolated_dirs, monkeypatch):
    monkeypatch.setattr(compiler.discover, "load_registry", lambda: FIXTURE_REGISTRY)
    monkeypatch.setattr(compiler.discover, "probe_all", lambda: FIXTURE_REACHABILITY)
    monkeypatch.setattr(compiler, "load_history", lambda: FIXTURE_HISTORY)

    compiler.ingest_posting("KROGER-001", SAMPLE_POSTING_TEXT, "manual_paste", "pasted by user")
    report = compiler.compile_report("KROGER-001")

    states = {spec["state"] for spec in report["capability_specs"]}
    assert compiler.MISSING in states  # Copilot/enterprise AI claims
    assert compiler.OPERATOR_REQUIRED in states  # "approve final ... decisions"
    assert compiler.PROVEN in states or compiler.AVAILABLE_UNPROVEN in states  # code_generation / git
    assert compiler.CONNECTOR_REQUIRED in states  # Zapier workflow automation
    assert compiler.UNMAPPED in states  # flux capacitor line

    on_disk = json.loads((compiler._report_path("KROGER-001")).read_text())
    assert on_disk == report


def test_report_is_idempotent_across_recompiles(isolated_dirs, monkeypatch):
    monkeypatch.setattr(compiler.discover, "load_registry", lambda: FIXTURE_REGISTRY)
    monkeypatch.setattr(compiler.discover, "probe_all", lambda: FIXTURE_REACHABILITY)
    monkeypatch.setattr(compiler, "load_history", lambda: FIXTURE_HISTORY)

    compiler.ingest_posting("KROGER-001", SAMPLE_POSTING_TEXT, "manual_paste", "pasted by user")
    first = compiler.compile_report("KROGER-001")
    second = compiler.compile_report("KROGER-001")
    assert first["capability_specs"] == second["capability_specs"]
    assert first["summary"] == second["summary"]
