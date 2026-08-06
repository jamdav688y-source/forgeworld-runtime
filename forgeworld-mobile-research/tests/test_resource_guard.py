import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from resource_guard import ResourceMetrics, ResourceState, evaluate, write_state_snapshot


def test_all_metrics_missing_is_green():
    decision = evaluate(ResourceMetrics())
    assert decision.state == ResourceState.GREEN
    assert decision.allow_optional_indexing is True


def test_normal_metrics_are_green():
    m = ResourceMetrics(free_storage_gb=10, free_memory_mb=2000, battery_percent=80, battery_charging=False, thermal_celsius=30)
    decision = evaluate(m)
    assert decision.state == ResourceState.GREEN


def test_low_battery_not_charging_is_yellow():
    m = ResourceMetrics(battery_percent=15, battery_charging=False)
    decision = evaluate(m)
    assert decision.state == ResourceState.YELLOW
    assert decision.allow_optional_indexing is False


def test_low_battery_while_charging_does_not_escalate():
    m = ResourceMetrics(battery_percent=15, battery_charging=True)
    decision = evaluate(m)
    assert decision.state == ResourceState.GREEN


def test_low_storage_is_orange():
    m = ResourceMetrics(free_storage_gb=0.5)
    decision = evaluate(m)
    assert decision.state == ResourceState.ORANGE
    assert decision.should_preserve_state is True
    assert decision.allow_media_processing is False


def test_critical_storage_is_red():
    m = ResourceMetrics(free_storage_gb=0.1)
    decision = evaluate(m)
    assert decision.state == ResourceState.RED
    assert decision.should_notify_operator is True


def test_high_thermal_is_orange_critical_thermal_is_red():
    orange = evaluate(ResourceMetrics(thermal_celsius=43))
    red = evaluate(ResourceMetrics(thermal_celsius=47))
    assert orange.state == ResourceState.ORANGE
    assert red.state == ResourceState.RED


def test_multiple_gaps_escalate_to_the_worst_one():
    m = ResourceMetrics(free_storage_gb=10, free_memory_mb=50, thermal_celsius=30)
    decision = evaluate(m)
    assert decision.state == ResourceState.RED  # critical memory wins over otherwise-fine storage
    assert len(decision.reasons) >= 1


def test_red_state_blocks_heavy_local_models_regardless_of_charging():
    m = ResourceMetrics(free_storage_gb=0.1, battery_charging=True)
    decision = evaluate(m)
    assert decision.state == ResourceState.RED
    assert decision.allow_heavy_local_models is False


def test_indexing_queue_depth_triggers_yellow():
    m = ResourceMetrics(pending_indexing_queue=100)
    decision = evaluate(m)
    assert decision.state == ResourceState.YELLOW


def test_reasons_are_never_empty(tmp_path):
    decision = evaluate(ResourceMetrics())
    assert decision.reasons  # always explains itself, even when everything's fine


def test_write_state_snapshot_writes_valid_json(tmp_path):
    m = ResourceMetrics(free_storage_gb=5)
    decision = evaluate(m)
    out = tmp_path / "resource_state.json"
    write_state_snapshot(m, decision, out)
    assert out.exists()
    import json
    data = json.loads(out.read_text())
    assert data["decision"]["state"] == "GREEN"
