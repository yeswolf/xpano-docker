from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from pano_xpano.config import DetectionSettings
from pano_xpano.domain.models import GroupStatus, PairMatch
from pano_xpano.domain.policies import (
    build_groups,
    candidate_pairs,
    group_id,
    make_group,
    plan_replacement,
    unique_output_path,
)

from conftest import make_photo, make_panorama


def test_candidate_pairs_respect_time_and_camera(tmp_path: Path) -> None:
    first = make_photo(tmp_path / "a.jpg", datetime(2024, 5, 1, 12, 0, 0))
    second = make_photo(tmp_path / "b.jpg", datetime(2024, 5, 1, 12, 0, 5))
    far = make_photo(tmp_path / "c.jpg", datetime(2024, 5, 1, 12, 5, 0))
    other = make_photo(
        tmp_path / "d.jpg", datetime(2024, 5, 1, 12, 0, 6), camera="Other"
    )
    settings = DetectionSettings(time_window_s=20)
    pairs = candidate_pairs([first, second, far, other], settings)
    assert [(left.path.name, right.path.name) for left, right in pairs] == [
        ("a.jpg", "b.jpg")
    ]


def test_candidate_pairs_use_mtime_without_exif(tmp_path: Path) -> None:
    first = make_photo(tmp_path / "a.jpg", None)
    second = make_photo(tmp_path / "b.jpg", None)
    settings = DetectionSettings(no_exif_window_s=1)
    assert len(candidate_pairs([first, second], settings)) == 1


def test_build_groups_accepts_panning_sequence(tmp_path: Path) -> None:
    photos = [
        make_photo(tmp_path / f"{index}.jpg", datetime(2024, 5, 1, 12, 0, index))
        for index in range(3)
    ]
    matches = [
        PairMatch(photos[0], photos[1], 80, 0.35, 0.0),
        PairMatch(photos[1], photos[2], 75, 0.30, 0.01),
    ]
    groups = build_groups(photos, matches, DetectionSettings(), "test")
    assert len(groups) == 1
    assert [photo.path.name for photo in groups[0].members] == [
        "0.jpg",
        "1.jpg",
        "2.jpg",
    ]
    assert groups[0].confidence >= 0.8


def test_build_groups_rejects_burst(tmp_path: Path) -> None:
    photos = [
        make_photo(tmp_path / f"{index}.jpg", datetime(2024, 5, 1, 12, 0, index))
        for index in range(3)
    ]
    matches = [
        PairMatch(photos[0], photos[1], 100, 0.005, 0.0),
        PairMatch(photos[1], photos[2], 100, -0.004, 0.0),
    ]
    assert build_groups(photos, matches, DetectionSettings(), "test") == []


def test_group_id_is_stable_and_order_independent(tmp_path: Path) -> None:
    first = make_photo(tmp_path / "a.jpg")
    second = make_photo(tmp_path / "b.jpg")
    left = group_id((first, second), "v1")
    right = group_id((second, first), "v1")
    assert left == right
    assert group_id((first, second), "v2") != left


def test_unique_output_path_avoids_collision(tmp_path: Path) -> None:
    assert unique_output_path(tmp_path, "PANO_1", ".jpg").name == "PANO_1.jpg"
    (tmp_path / "PANO_1.jpg").write_bytes(b"")
    assert unique_output_path(tmp_path, "PANO_1", ".jpg").name == "PANO_1_2.jpg"


def test_replacement_plan_includes_sidecars_and_keeps_paths_inside_library(
    tmp_path: Path,
) -> None:
    library = tmp_path / "library"
    photo = make_photo(library / "2024" / "a.jpg")
    make_photo(library / "2024" / "b.jpg")
    photo.path.with_suffix(".xmp").write_text("sidecar")
    panorama = tmp_path / "stitch" / "pano.jpg"
    make_panorama(panorama)
    group = make_group(
        _detected(photo, make_photo(library / "2024" / "b.jpg")),
        "test",
        "folder",
        datetime(2024, 5, 1),
    )
    plan = plan_replacement(
        group,
        panorama,
        library,
        tmp_path / "trash",
        "op1",
        ".jpg",
    )
    assert plan.target.parent == photo.path.parent
    assert plan.target.name.startswith("PANO_")
    assert len(plan.moves) == 3
    assert plan.target not in {move.source for move in plan.moves}
    assert group.status == GroupStatus.CANDIDATE


def _detected(*photos):
    from pano_xpano.domain.models import DetectedGroup

    return DetectedGroup(members=tuple(photos), confidence=0.9)
