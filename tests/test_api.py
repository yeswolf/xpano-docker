from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from pano_xpano.adapters.replacement import SafeReplacer
from pano_xpano.adapters.scanner import FilesystemFolderCounter
from pano_xpano.adapters.store import SqliteStore
from pano_xpano.application.jobs import JobRunner
from pano_xpano.application.use_cases import (
    AddFolder,
    RemoveFolder,
    ReplaceGroup,
    ScanLibrary,
    StitchGroup,
    UndoReplacement,
)
from pano_xpano.config import DetectionSettings, Settings, SettingsManager
from pano_xpano.container import AppContainer
from pano_xpano.domain.models import JobStatus, Photo
from pano_xpano.web.app import create_app

from conftest import Clock, FakeDetector, FakeScanner, FakeStitcher, make_image


def _photo(path: Path, moment: datetime, key: str) -> Photo:
    return Photo(
        path=path,
        captured_at=moment,
        modified_at=moment,
        camera="Test",
        lens="35mm",
        focal_length=35.0,
        width=1200,
        height=800,
        size=path.stat().st_size,
        thumbnail_key=key,
    )


def _container(tmp_path: Path):
    library = tmp_path / "library"
    library.mkdir()
    moment = datetime(2024, 5, 1, 12, 0, 0)
    first_path = library / "2024" / "a.jpg"
    second_path = library / "2024" / "b.jpg"
    make_image(first_path, (1200, 800))
    make_image(second_path, (1200, 800))
    photos = [
        _photo(first_path, moment, "a" * 40),
        _photo(second_path, moment, "b" * 40),
    ]
    settings = Settings(
        library_root=library,
        data_dir=tmp_path / "data",
        xpano_bin="Xpano",
        host="127.0.0.1",
        port=3040,
        detector_version="test",
        output_ext=".jpg",
        stitch_timeout_s=30,
        use_xvfb=False,
        thumb_size=120,
        detection=DetectionSettings(),
    )
    manager = SettingsManager(settings)
    store = SqliteStore(settings.db_path)
    runner = JobRunner(store, inline=True)
    clock = Clock()
    container = AppContainer(
        settings_manager=manager,
        store=store,
        scan=ScanLibrary(
            FakeScanner(photos), FakeDetector(photos), store, lambda: manager.current, clock=clock
        ),
        stitch=StitchGroup(store, FakeStitcher(), lambda: manager.current, clock=clock),
        replace=ReplaceGroup(store, SafeReplacer(), lambda: manager.current, clock=clock),
        undo=UndoReplacement(store, SafeReplacer(), clock=clock),
        add_folder=AddFolder(
            store,
            lambda: manager.current,
            FilesystemFolderCounter(),
            clock=clock,
        ),
        remove_folder=RemoveFolder(store),
        runner=runner,
    )
    return container, photos


def test_scan_stitch_replace_and_undo(tmp_path: Path) -> None:
    container, photos = _container(tmp_path)
    client = TestClient(create_app(container))

    folder = client.post("/api/folders", json={"path": "2024"})
    assert folder.status_code == 200
    folder_id = folder.json()["id"]
    assert folder.json()["path"] == "2024"
    assert folder.json()["image_count"] == 2
    assert folder.json()["file_count"] == 2
    assert len(client.get("/api/folders").json()) == 1

    browse = client.get("/api/folders/browse", params={"path": "."})
    assert browse.status_code == 200
    assert any(entry["name"] == "2024" for entry in browse.json()["entries"])

    outside = client.post("/api/folders", json={"path": "../outside"})
    assert outside.status_code == 400

    pending = container.store.create_job(
        "scan", datetime.now(), {"folder_id": folder_id}
    )
    container.store.update_job(pending.id, status=JobStatus.RUNNING)
    active = client.get("/api/jobs", params={"active": True}).json()
    assert any(
        job["id"] == pending.id and job["context"]["folder_id"] == folder_id
        for job in active
    )
    container.store.update_job(pending.id, status=JobStatus.COMPLETED)

    scan = client.post(f"/api/folders/{folder_id}/scan")
    assert scan.status_code == 200
    scan_job = scan.json()
    assert scan_job["status"] == "completed"
    assert scan_job["result"]["photos"] == 2
    assert scan_job["result"]["groups"] == 1
    folder_after = client.get("/api/folders").json()[0]
    assert folder_after["photo_count"] == 2
    assert folder_after["image_count"] == 2
    assert folder_after["file_count"] == 2
    assert folder_after["last_scan_status"] == "completed"

    groups = client.get("/api/groups", params={"folder_id": folder_id}).json()
    assert len(groups) == 1
    assert groups[0]["folder_id"] == folder_id
    group_id = groups[0]["id"]
    assert client.get("/api/groups", params={"folder_id": "other"}).json() == []

    stitch = client.post(f"/api/groups/{group_id}/stitch")
    assert stitch.status_code == 200
    assert stitch.json()["status"] == "completed"
    page = client.get(f"/groups/{group_id}")
    assert page.status_code == 200
    assert 'id="image-dialog"' in page.text
    assert 'id="preview-full"' in page.text
    assert 'id="preview-error"' in page.text
    assert "app.js?v=" in page.text

    detail = client.get(f"/api/groups/{group_id}").json()
    assert detail["stitch"]["status"] == "completed"
    preview = client.get(f"/api/groups/{group_id}/preview")
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("image/")

    member = detail["members"][0]
    assert member["original"] == f"/api/photos/{photos[0].thumbnail_key}/original"
    original = client.get(member["original"])
    assert original.status_code == 200
    assert original.headers["content-type"].startswith("image/")
    assert original.content == Path(member["path"]).read_bytes()
    original_bytes = original.content
    assert client.get("/api/photos/not-a-key/original").status_code == 400
    assert client.get(f"/api/photos/{'f' * 40}/original").status_code == 404

    refused = client.post(
        f"/api/groups/{group_id}/replace", json={"confirm": False}
    )
    assert refused.status_code == 400
    assert photos[0].path.is_file()

    replaced = client.post(
        f"/api/groups/{group_id}/replace", json={"confirm": True}
    )
    assert replaced.status_code == 200
    assert replaced.json()["status"] == "completed"
    assert not photos[0].path.exists()
    assert not photos[1].path.exists()
    from_trash = client.get(member["original"])
    assert from_trash.status_code == 200
    assert from_trash.content == original_bytes
    panoramas = list((tmp_path / "library" / "2024").glob("PANO_*.jpg"))
    assert len(panoramas) == 1

    operations = client.get("/api/operations").json()
    assert len(operations) == 1
    assert operations[0]["status"] == "completed"

    undo = client.post(f"/api/operations/{operations[0]['id']}/undo")
    assert undo.status_code == 200
    assert undo.json()["status"] == "completed"
    assert photos[0].path.is_file()
    assert photos[1].path.is_file()
    assert not panoramas[0].exists()
    assert client.get(member["original"]).status_code == 200

    photos[0].path.unlink()
    assert client.get(member["original"]).status_code == 404

    removed = client.delete(f"/api/folders/{folder_id}")
    assert removed.status_code == 200
    assert client.get("/api/folders").json() == []
    assert client.get("/api/groups").json() == []
