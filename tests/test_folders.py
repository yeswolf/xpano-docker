from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from pano_xpano.adapters.folders import browse_folders
from pano_xpano.adapters.store import SqliteStore
from pano_xpano.domain.models import DetectedGroup, JobStatus, WatchedFolder
from pano_xpano.domain.policies import (
    folder_absolute,
    folder_id_for,
    make_group,
    normalize_folder_path,
)

from conftest import make_photo


def test_normalize_folder_path_accepts_relative_and_absolute(tmp_path: Path) -> None:
    root = tmp_path / "library"
    (root / "2024" / "05").mkdir(parents=True)
    assert normalize_folder_path(root, "2024") == "2024"
    assert normalize_folder_path(root, "2024/05") == "2024/05"
    assert normalize_folder_path(root, str(root / "2024")) == "2024"
    assert normalize_folder_path(root, ".") == "."


def test_normalize_folder_path_rejects_escape(tmp_path: Path) -> None:
    root = tmp_path / "library"
    root.mkdir()
    (tmp_path / "outside").mkdir()
    with pytest.raises(ValueError):
        normalize_folder_path(root, "../outside")
    with pytest.raises(ValueError):
        normalize_folder_path(root, str(tmp_path / "outside"))


def test_browse_skips_hidden_folders(tmp_path: Path) -> None:
    root = tmp_path / "library"
    (root / "2024").mkdir(parents=True)
    (root / ".hidden").mkdir()
    (root / "2024" / "05").mkdir()
    result = browse_folders(root, ".")
    assert [entry["name"] for entry in result["entries"]] == ["2024"]
    assert browse_folders(root, "2024")["entries"][0]["path"] == "2024/05"


def test_store_scopes_folders(tmp_path: Path) -> None:
    root = tmp_path / "library"
    (root / "a").mkdir(parents=True)
    (root / "b").mkdir()
    store = SqliteStore(tmp_path / "state.sqlite3")
    now = datetime(2024, 5, 1)
    folder_a = WatchedFolder(
        id=folder_id_for("a"), path="a", created_at=now, last_scan_at=None,
        last_scan_status=None,
    )
    folder_b = WatchedFolder(
        id=folder_id_for("b"), path="b", created_at=now, last_scan_at=None,
        last_scan_status=None,
    )
    store.add_folder(folder_a)
    store.add_folder(folder_b)

    photo_a = make_photo(root / "a" / "one.jpg", now)
    photo_b = make_photo(root / "b" / "two.jpg", now)
    group_a = make_group(
        DetectedGroup(members=(photo_a, make_photo(root / "a" / "one2.jpg", now)), confidence=0.9),
        "test",
        folder_a.id,
        now,
    )
    group_b = make_group(
        DetectedGroup(members=(photo_b, make_photo(root / "b" / "two2.jpg", now)), confidence=0.9),
        "test",
        folder_b.id,
        now,
    )

    store.replace_photos(folder_a.id, [photo_a])
    store.replace_photos(folder_b.id, [photo_b])
    store.sync_candidate_groups(folder_a.id, [group_a])
    store.sync_candidate_groups(folder_b.id, [group_b])
    store.update_folder_scan(folder_a.id, now, "completed")

    assert [photo.path.name for photo in store.list_photos(folder_a.id)] == ["one.jpg"]
    assert [group.id for group in store.list_groups(folder_a.id)] == [group_a.id]
    assert [group.id for group in store.list_groups(folder_b.id)] == [group_b.id]
    folders = {folder.path: folder for folder in store.list_folders()}
    assert folders["a"].photo_count == 1
    assert folders["a"].group_count == 1
    assert folders["a"].last_scan_status == "completed"

    store.remove_folder(folder_a.id)
    assert store.get_folder(folder_a.id) is None
    assert store.list_photos(folder_a.id) == []
    assert [group.id for group in store.list_groups(folder_b.id)] == [group_b.id]
    assert folder_absolute(root, "a") == (root / "a").resolve()


def test_unfinished_jobs_are_failed_after_restart(tmp_path: Path) -> None:
    store = SqliteStore(tmp_path / "state.sqlite3")
    now = datetime(2024, 5, 1)
    job = store.create_job("scan", now, {"folder_id": "f"})
    store.update_job(job.id, status=JobStatus.RUNNING)
    assert len(store.list_active_jobs()) == 1
    store.fail_unfinished_jobs("interrupted by service restart")
    assert store.list_active_jobs() == []
    failed = store.get_job(job.id)
    assert failed is not None
    assert failed.status == JobStatus.FAILED
    assert "interrupted" in (failed.message or "")
