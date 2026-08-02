import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from alerts.engine import AlertEngine, InvalidTransitionError, UnknownAlertError
from alerts.models import (
    STATE_PRESENTED, STATE_ACKNOWLEDGED, STATE_ACTIONED, STATE_RESOLVED,
    STATE_DISMISSED, STATE_ESCALATED, CLASS_PASSIVE, CLASS_ACTIVE_WARNING, CLASS_BLOCKING,
)


@pytest.fixture()
def engine(tmp_path):
    return AlertEngine(tmp_path / "alerts", suppression_window_s=0.05)


def test_every_required_source_can_raise_an_alert(engine):
    from alerts.models import SOURCES
    for source in SOURCES:
        a = engine.detect(source, "progress", CLASS_PASSIVE, f"signal from {source}")
        assert a.source == source
        assert a.state == STATE_PRESENTED


def test_every_class_and_code_is_representable(engine):
    from alerts.models import CODES_BY_CLASS
    for alert_class, codes in CODES_BY_CLASS.items():
        for code in codes:
            a = engine.detect("validator", code, alert_class, f"{code} occurred", group_key=code)
            assert a.alert_class == alert_class
            assert a.code == code


def test_full_state_machine_detect_to_resolve(engine):
    a = engine.detect("renderer", "low_storage", CLASS_ACTIVE_WARNING, "disk getting low")
    assert a.state == STATE_PRESENTED
    a = engine.acknowledge(a.id, by="operator")
    assert a.state == STATE_ACKNOWLEDGED
    a = engine.action(a.id, note="cleared temp render cache")
    assert a.state == STATE_ACTIONED
    a = engine.resolve(a.id, evidence="disk_usage.free now 4.2GB, threshold was 1GB")
    assert a.state == STATE_RESOLVED
    assert a.resolution_evidence


def test_resolve_requires_evidence(engine):
    a = engine.detect("renderer", "low_storage", CLASS_ACTIVE_WARNING, "disk getting low")
    with pytest.raises(ValueError):
        engine.resolve(a.id, evidence="")


def test_dismiss_path(engine):
    a = engine.detect("renderer", "missing_optional_asset", CLASS_ACTIVE_WARNING, "no logo asset")
    a = engine.dismiss(a.id, by="operator", reason="logo asset intentionally omitted")
    assert a.state == STATE_DISMISSED


def test_escalate_path(engine):
    a = engine.detect("validator", "corrupt_frame", CLASS_BLOCKING, "frame 500 checksum mismatch")
    a = engine.escalate(a.id, reason="unresolved after 3 render attempts")
    assert a.state == STATE_ESCALATED
    # an escalated alert can still be acknowledged/resolved afterward
    a = engine.acknowledge(a.id, by="operator")
    a = engine.resolve(a.id, evidence="frame 500 regenerated, checksum verified")
    assert a.state == STATE_RESOLVED


def test_invalid_transition_raises(engine):
    a = engine.detect("renderer", "progress", CLASS_PASSIVE, "50%")
    with pytest.raises(InvalidTransitionError):
        engine.action(a.id, note="skip ahead illegally")


def test_unknown_alert_id_raises(engine):
    with pytest.raises(UnknownAlertError):
        engine.get("does-not-exist")


def test_deduplication_merges_identity_regardless_of_window(engine):
    a1 = engine.detect("storage_monitor", "low_storage", CLASS_ACTIVE_WARNING, "89% full")
    a2 = engine.detect("storage_monitor", "low_storage", CLASS_ACTIVE_WARNING, "90% full")
    assert a1.id == a2.id
    assert a2.occurrence_count == 2
    time.sleep(0.06)  # exceed the 0.05s suppression window used in this fixture
    a3 = engine.detect("storage_monitor", "low_storage", CLASS_ACTIVE_WARNING, "91% full")
    assert a3.id == a1.id  # still the same alert -- dedup identity never resets on its own
    assert a3.occurrence_count == 3


def test_suppression_window_avoids_resurfacing_handled_alert_on_rapid_repeat(engine):
    a = engine.detect("storage_monitor", "low_storage", CLASS_ACTIVE_WARNING, "89% full")
    engine.acknowledge(a.id, by="operator")
    # a rapid repeat while it's being handled should NOT yank it back to PRESENTED
    a2 = engine.detect("storage_monitor", "low_storage", CLASS_ACTIVE_WARNING, "89% full again")
    assert a2.state == STATE_ACKNOWLEDGED
    # but if it keeps recurring past the suppression window, it resurfaces
    time.sleep(0.06)
    a3 = engine.detect("storage_monitor", "low_storage", CLASS_ACTIVE_WARNING, "still low")
    assert a3.state == STATE_PRESENTED


def test_root_cause_grouping(engine):
    engine.detect("renderer", "corrupt_frame", CLASS_BLOCKING, "frame 10", group_key="scene1_render_pass")
    engine.detect("renderer", "missing_frame", CLASS_BLOCKING, "frame 11", group_key="scene1_render_pass")
    engine.detect("validator", "invalid_duration", CLASS_BLOCKING, "unrelated", group_key="other")
    grouped = engine.alerts_by_group("scene1_render_pass")
    assert len(grouped) == 2


def test_severity_ranking_blocking_first(engine):
    engine.detect("renderer", "progress", CLASS_PASSIVE, "10%")
    engine.detect("storage_monitor", "low_storage", CLASS_ACTIVE_WARNING, "low")
    engine.detect("validator", "corrupt_frame", CLASS_BLOCKING, "bad frame")
    active = engine.active_alerts()
    assert active[0].alert_class == CLASS_BLOCKING


def test_blocking_alert_prevents_publish_until_resolved(engine):
    assert engine.can_proceed_to_publish() is True
    a = engine.detect("validator", "unsafe_publication_attempt", CLASS_BLOCKING, "duration mismatch detected")
    assert engine.can_proceed_to_publish() is False
    engine.acknowledge(a.id, by="operator")
    engine.resolve(a.id, evidence="re-encoded with corrected duration, ffprobe confirms 90.000s")
    assert engine.can_proceed_to_publish() is True


def test_dismissed_blocking_alert_also_unblocks(engine):
    a = engine.detect("validator", "private_data_detected", CLASS_BLOCKING, "false positive on synthetic content")
    assert engine.can_proceed_to_publish() is False
    engine.dismiss(a.id, by="operator", reason="confirmed false positive -- content is fully synthetic, no PII")
    assert engine.can_proceed_to_publish() is True


def test_restart_persistence(tmp_path):
    persist_dir = tmp_path / "alerts"
    engine1 = AlertEngine(persist_dir)
    a = engine1.detect("launcher", "device_validation_required", CLASS_ACTIVE_WARNING, "no Windows env to validate on")
    engine1.acknowledge(a.id, by="operator")

    # simulate process restart: brand-new engine instance, same directory
    engine2 = AlertEngine(persist_dir)
    reloaded = engine2.get(a.id)
    assert reloaded.state == STATE_ACKNOWLEDGED
    assert reloaded.message == a.message


def test_alerts_jsonl_and_current_state_json_are_written(tmp_path):
    persist_dir = tmp_path / "alerts"
    engine = AlertEngine(persist_dir)
    engine.detect("renderer", "render_complete", CLASS_PASSIVE, "done")
    assert (persist_dir / "alerts.jsonl").exists()
    assert (persist_dir / "current_state.json").exists()
    import json
    state = json.loads((persist_dir / "current_state.json").read_text())
    assert state["total_alerts"] == 1
    assert "can_proceed_to_publish" in state


def test_engine_has_no_publish_or_self_authorization_methods():
    # Structural guardrail check: these capabilities must not exist on the
    # engine at all, not just be unused.
    forbidden = ["publish", "delete_evidence", "overwrite_release", "get_credentials", "authorize_self"]
    for name in forbidden:
        assert not hasattr(AlertEngine, name)
