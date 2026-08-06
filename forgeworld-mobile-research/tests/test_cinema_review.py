import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from cinema_review import (
    discover_cinema_artifacts, read_validation_summary, create_review,
    validate_review, save_review, list_reviews, review_queue_summary,
    APPROVAL_STATES, REVIEW_TYPES,
)


def test_discover_cinema_artifacts_finds_the_real_release():
    # This repo actually contains a built Cinema Player release
    # (cinema/cinema_player_90s/RELEASES/) -- confirm real discovery, not
    # a mock, finds real files.
    artifacts = discover_cinema_artifacts()
    assert len(artifacts) > 0
    kinds = {a["kind"] for a in artifacts}
    assert "master_video" in kinds


def test_discovered_artifact_paths_actually_exist_on_disk():
    artifacts = discover_cinema_artifacts()
    repo_root = Path(__file__).resolve().parent.parent.parent
    for a in artifacts[:5]:
        assert (repo_root / a["path"]).exists()


def test_read_validation_summary_returns_real_data():
    summary = read_validation_summary("FW-CINEMA-PLAYER-90S-V1")
    assert summary is not None
    assert "overall_pass" in summary


def test_read_validation_summary_returns_none_for_unknown_version():
    assert read_validation_summary("NOT-A-REAL-VERSION") is None


def test_create_review_rejects_invalid_review_type():
    with pytest.raises(ValueError):
        create_review("a.mp4", "v1", "device", "not_a_real_type")


def test_create_review_rejects_invalid_approval_state():
    with pytest.raises(ValueError):
        create_review("a.mp4", "v1", "device", "full_playback", approval_state="maybe")


def test_create_review_defaults_to_pending():
    review = create_review("a.mp4", "v1", "device", "full_playback")
    assert review["approval_state"] == "pending"
    assert review["observations"] == []
    assert review["defects"] == []


def test_validate_review_catches_missing_fields():
    assert len(validate_review({})) >= 8


def test_save_and_list_reviews_round_trip(tmp_path):
    r1 = create_review("a.mp4", "v1", "device", "full_playback", approval_state="approved")
    r2 = create_review("b.jpg", "v1", "device", "contact_sheet", approval_state="rejected", defects=["banding"])
    save_review(r1, tmp_path)
    save_review(r2, tmp_path)
    reviews = list_reviews(tmp_path)
    assert len(reviews) == 2


def test_save_invalid_review_raises(tmp_path):
    with pytest.raises(ValueError):
        save_review({"artifact": "x"}, tmp_path)


def test_review_queue_summary_counts_by_state(tmp_path):
    save_review(create_review("a.mp4", "v1", "d", "full_playback", approval_state="approved"), tmp_path)
    save_review(create_review("b.mp4", "v1", "d", "full_playback", approval_state="approved"), tmp_path)
    save_review(create_review("c.mp4", "v1", "d", "full_playback", approval_state="pending"), tmp_path)
    summary = review_queue_summary(tmp_path)
    assert summary["approved"] == 2
    assert summary["pending"] == 1
    assert summary["total"] == 3


def test_review_queue_summary_on_empty_dir(tmp_path):
    summary = review_queue_summary(tmp_path / "does_not_exist")
    assert summary["total"] == 0


def test_defects_recorded_do_not_modify_original_artifact():
    # Original source video/image files must never be touched by a review.
    artifacts_before = discover_cinema_artifacts()
    create_review("a.mp4", "v1", "device", "full_playback", defects=["frame 500 glitch"])
    artifacts_after = discover_cinema_artifacts()
    assert artifacts_before == artifacts_after
