import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import device_profile


def test_detect_termux_is_false_in_this_container(monkeypatch):
    monkeypatch.delenv("TERMUX_VERSION", raising=False)
    monkeypatch.delenv("PREFIX", raising=False)
    in_termux, evidence = device_profile.detect_termux()
    assert in_termux is False
    assert "TERMUX_VERSION" in evidence


def test_detect_termux_is_true_with_termux_markers(monkeypatch):
    monkeypatch.setenv("TERMUX_VERSION", "0.118.0")
    in_termux, _ = device_profile.detect_termux()
    assert in_termux is True


def test_detect_termux_via_prefix_path(monkeypatch):
    monkeypatch.delenv("TERMUX_VERSION", raising=False)
    monkeypatch.setenv("PREFIX", "/data/data/com.termux/files/usr")
    in_termux, _ = device_profile.detect_termux()
    assert in_termux is True


def test_build_profile_never_fabricates_android_facts_outside_termux(tmp_path, monkeypatch):
    monkeypatch.delenv("TERMUX_VERSION", raising=False)
    monkeypatch.delenv("PREFIX", raising=False)
    profile = device_profile.build_profile(tmp_path)
    assert profile["platform_class"] == "NOT_ANDROID"
    assert profile["android"]["not_available_reason"]
    assert "manufacturer" not in profile["android"]
    assert profile["battery"]["available"] is False
    assert profile["device_classification"] == "UNKNOWN"


def test_build_profile_reports_real_measurable_facts_about_this_container(tmp_path, monkeypatch):
    monkeypatch.delenv("TERMUX_VERSION", raising=False)
    monkeypatch.delenv("PREFIX", raising=False)
    profile = device_profile.build_profile(tmp_path)
    # these ARE real, honestly reported about the environment actually running --
    # not Android facts, but not fabricated either
    assert profile["cpu"]["logical_cores"] and profile["cpu"]["logical_cores"] > 0
    assert profile["storage"]["total_gb"] is not None
    assert profile["os"]["system"] in ("Linux", "Darwin", "Windows")


def test_classify_device_returns_unknown_without_ram_or_storage_data():
    profile = {
        "platform_class": "TERMUX_ANDROID",
        "memory": {"total_mb": None},
        "storage": {"available_gb": None},
        "battery": {"available": False},
    }
    assert device_profile.classify_device(profile) == "UNKNOWN"


def test_classify_device_storage_constrained():
    profile = {
        "platform_class": "TERMUX_ANDROID",
        "memory": {"total_mb": 6000},
        "storage": {"available_gb": 2.0},
        "battery": {"available": False},
    }
    assert device_profile.classify_device(profile) == "STORAGE_CONSTRAINED"


def test_classify_device_memory_constrained():
    profile = {
        "platform_class": "TERMUX_ANDROID",
        "memory": {"total_mb": 2048},
        "storage": {"available_gb": 20.0},
        "battery": {"available": False},
    }
    assert device_profile.classify_device(profile) == "MEMORY_CONSTRAINED"


def test_classify_device_thermally_constrained_takes_priority():
    profile = {
        "platform_class": "TERMUX_ANDROID",
        "memory": {"total_mb": 8192},
        "storage": {"available_gb": 30.0},
        "battery": {"available": True, "temperature": 45.0},
    }
    assert device_profile.classify_device(profile) == "THERMALLY_CONSTRAINED"


def test_classify_device_performance_tier():
    profile = {
        "platform_class": "TERMUX_ANDROID",
        "memory": {"total_mb": 12000},
        "storage": {"available_gb": 50.0},
        "battery": {"available": False},
    }
    assert device_profile.classify_device(profile) == "PERFORMANCE"


def test_read_cpu_info_does_not_mistake_processor_index_for_model_name():
    info = device_profile.read_cpu_info()
    # On real x86 hardware /proc/cpuinfo lists "processor : 0" before
    # "model name" -- a naive parser can grab "0" as the model. Guard
    # against that regression directly.
    assert info["model_name"] != "0"
