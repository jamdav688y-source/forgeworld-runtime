import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from mission_handoff import (
    create_mission_package, validate_mission_package, save_mission_package,
    list_mission_packages, load_mission_package, REQUIRED_FIELDS,
)


def test_create_mission_package_has_every_required_field():
    pkg = create_mission_package("test outcome", required_capabilities=["git"])
    for field in REQUIRED_FIELDS:
        assert field in pkg


def test_mobile_available_capability_is_bucketed_correctly():
    pkg = create_mission_package("test", required_capabilities=["git", "python"])
    assert "git" in pkg["mobile_available"]
    assert "python" in pkg["mobile_available"]
    assert pkg["windows_required"] == []
    assert pkg["operator_required"] == []


def test_platform_blocked_capability_routes_to_windows_required():
    pkg = create_mission_package("test", required_capabilities=["windows_shell_execution"])
    assert "windows_shell_execution" in pkg["windows_required"]


def test_unknown_capability_id_routes_to_operator_required_not_dropped():
    pkg = create_mission_package("test", required_capabilities=["totally_made_up_capability"])
    assert "totally_made_up_capability" in pkg["operator_required"]


def test_manual_check_capability_routes_to_operator_required():
    pkg = create_mission_package("test", required_capabilities=["camera_capture"])
    assert "camera_capture" in pkg["operator_required"]


def test_invalid_priority_raises():
    with pytest.raises(ValueError):
        create_mission_package("test", priority="whenever")


def test_validate_mission_package_catches_missing_fields():
    errors = validate_mission_package({"mission_id": "x"})
    assert len(errors) > 5


def test_validate_mission_package_passes_for_real_package():
    pkg = create_mission_package("test", required_capabilities=["git"])
    assert validate_mission_package(pkg) == []


def test_save_and_load_round_trip(tmp_path):
    pkg = create_mission_package("test outcome", required_capabilities=["git"], priority="urgent")
    path = save_mission_package(pkg, tmp_path)
    assert path.exists()
    loaded = load_mission_package(tmp_path, pkg["mission_id"])
    assert loaded["requested_outcome"] == "test outcome"
    assert loaded["priority"] == "urgent"


def test_save_invalid_package_raises_and_does_not_write(tmp_path):
    with pytest.raises(ValueError):
        save_mission_package({"mission_id": "bad"}, tmp_path)
    assert list(tmp_path.glob("*.json")) == [] if tmp_path.exists() else True


def test_list_mission_packages_returns_all_saved(tmp_path):
    for outcome in ["a", "b", "c"]:
        pkg = create_mission_package(outcome, required_capabilities=["git"])
        save_mission_package(pkg, tmp_path)
    packages = list_mission_packages(tmp_path)
    assert len(packages) == 3


def test_list_mission_packages_on_empty_dir_returns_empty_list(tmp_path):
    assert list_mission_packages(tmp_path / "does_not_exist") == []


def test_load_missing_mission_returns_none(tmp_path):
    assert load_mission_package(tmp_path, "MH-does-not-exist") is None


def test_mission_ids_are_unique_across_calls():
    ids = {create_mission_package(f"outcome {i}")["mission_id"] for i in range(5)}
    assert len(ids) == 5


def test_windows_never_reconstructs_request_from_conversation_history():
    # The whole point of the contract: everything needed to act is in the
    # package itself. Spot-check that the fields a Windows-side consumer
    # would need are present and non-empty when there's real content.
    pkg = create_mission_package(
        "Render Cinema master", source_records=[{"id": "r1"}],
        required_capabilities=["git"], constraints=["no destructive ops"],
        evidence=[{"note": "reviewed on mobile"}],
    )
    assert pkg["source_records"]
    assert pkg["constraints"]
    assert pkg["evidence"]
    assert pkg["requested_outcome"]
