from __future__ import annotations

import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from pano_xpano.adapters.folders import browse_folders
from pano_xpano.application.use_cases import (
    folder_payload,
    group_payload,
    operation_payload,
)
from pano_xpano.config import Settings
from pano_xpano.container import AppContainer, build_container
from pano_xpano.domain.models import JobRecord

PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"
THUMB_KEY = re.compile(r"^[0-9a-f]{40}$")


def _static_version() -> str:
    stamps = [
        path.stat().st_mtime_ns
        for path in (STATIC_DIR / "app.css", STATIC_DIR / "app.js")
        if path.is_file()
    ]
    return str(max(stamps)) if stamps else "0"


class ReplaceRequest(BaseModel):
    confirm: bool = False


class ScanRequest(BaseModel):
    folder_id: str | None = None


class FolderRequest(BaseModel):
    path: str


class DetectionUpdate(BaseModel):
    time_window_s: int | None = None
    no_exif_window_s: int | None = None
    min_inliers: int | None = None
    drift_ratio: float | None = None
    min_translation_ratio: float | None = None
    max_pairs: int | None = None


def create_app(
    container: AppContainer | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    if container is None:
        container = build_container(settings or Settings.from_env())
    app = FastAPI(title="pano-xpano", version="0.1.0")
    app.state.container = container
    templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))
    templates.env.globals["static_version"] = _static_version()
    app.mount(
        "/static",
        StaticFiles(directory=str(STATIC_DIR)),
        name="static",
    )

    @app.on_event("shutdown")
    def shutdown() -> None:
        container.runner.shutdown()

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok", "library": str(container.settings.library_root)}

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "index.html",
            {"library": str(container.settings.library_root)},
        )

    @app.get("/groups/{group_id}", response_class=HTMLResponse)
    def group_page(request: Request, group_id: str) -> HTMLResponse:
        group = container.store.get_group(group_id)
        if group is None:
            raise HTTPException(status_code=404, detail="group not found")
        return templates.TemplateResponse(
            request,
            "group.html",
            {
                "group_id": group_id,
                "library": str(container.settings.library_root),
            },
        )

    @app.get("/operations", response_class=HTMLResponse)
    def operations_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "operations.html",
            {"library": str(container.settings.library_root)},
        )

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request,
            "settings.html",
            {
                "settings": container.settings,
                "library": str(container.settings.library_root),
            },
        )

    # Folders ---------------------------------------------------------------

    @app.get("/api/folders")
    def folders() -> list[dict]:
        return [
            folder_payload(folder) for folder in container.store.list_folders()
        ]

    @app.post("/api/folders")
    def add_folder(request: FolderRequest) -> dict:
        try:
            return container.add_folder.run(request.path)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.delete("/api/folders/{folder_id}")
    def remove_folder(folder_id: str) -> dict:
        try:
            container.remove_folder.run(folder_id)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"status": "removed", "id": folder_id}

    @app.get("/api/folders/browse")
    def browse(path: str = ".") -> dict:
        try:
            return browse_folders(container.settings.library_root, path)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.post("/api/folders/{folder_id}/scan")
    def scan_folder(folder_id: str) -> dict:
        folder = container.store.get_folder(folder_id)
        if folder is None:
            raise HTTPException(status_code=404, detail="folder not found")
        job = container.runner.submit(
            "scan",
            lambda progress: container.scan.run(folder_id, progress),
            {"folder_id": folder_id},
        )
        return _job_payload(job)

    @app.post("/api/scan")
    def scan(request: ScanRequest | None = None) -> dict:
        folder_id = request.folder_id if request else None
        if folder_id is not None and container.store.get_folder(folder_id) is None:
            raise HTTPException(status_code=404, detail="folder not found")
        context = {"folder_id": folder_id} if folder_id else {"all_folders": True}
        job = container.runner.submit(
            "scan",
            lambda progress: container.scan.run(folder_id, progress),
            context,
        )
        return _job_payload(job)

    # Groups ----------------------------------------------------------------

    @app.get("/api/groups")
    def groups(folder_id: str | None = Query(default=None)) -> list[dict]:
        payload: list[dict] = []
        for group in container.store.list_groups(folder_id):
            stitch = container.store.latest_stitch(group.id)
            payload.append(group_payload(group, stitch))
        return payload

    @app.get("/api/groups/{group_id}")
    def group_detail(group_id: str) -> dict:
        group = container.store.get_group(group_id)
        if group is None:
            raise HTTPException(status_code=404, detail="group not found")
        stitch = container.store.latest_stitch(group.id)
        data = group_payload(group, stitch)
        data["operations"] = [
            operation_payload(operation)
            for operation in container.store.list_operations()
            if operation.group_id == group.id
        ]
        return data

    @app.post("/api/groups/{group_id}/stitch")
    def stitch_group(group_id: str) -> dict:
        if container.store.get_group(group_id) is None:
            raise HTTPException(status_code=404, detail="group not found")
        job = container.runner.submit(
            "stitch",
            lambda progress: container.stitch.run(group_id, progress),
            {"group_id": group_id},
        )
        return _job_payload(job)

    @app.post("/api/groups/{group_id}/replace")
    def replace_group(group_id: str, request: ReplaceRequest) -> dict:
        if not request.confirm:
            raise HTTPException(
                status_code=400,
                detail="replacement requires explicit confirmation",
            )
        if container.store.get_group(group_id) is None:
            raise HTTPException(status_code=404, detail="group not found")
        job = container.runner.submit(
            "replace",
            lambda progress: container.replace.run(group_id, True, progress),
            {"group_id": group_id},
        )
        return _job_payload(job)

    @app.get("/api/groups/{group_id}/preview")
    def preview(group_id: str) -> FileResponse:
        stitch = container.store.latest_stitch(group_id)
        if stitch is None or stitch.output_path is None:
            raise HTTPException(status_code=404, detail="no panorama")
        if not stitch.output_path.is_file():
            raise HTTPException(status_code=404, detail="panorama file missing")
        return FileResponse(stitch.output_path)

    # Operations ------------------------------------------------------------

    @app.get("/api/operations")
    def operations() -> list[dict]:
        return [
            operation_payload(operation)
            for operation in container.store.list_operations()
        ]

    @app.post("/api/operations/{operation_id}/undo")
    def undo(operation_id: str) -> dict:
        if container.store.get_operation(operation_id) is None:
            raise HTTPException(status_code=404, detail="operation not found")
        job = container.runner.submit(
            "undo",
            lambda progress: container.undo.run(operation_id, progress),
            {"operation_id": operation_id},
        )
        return _job_payload(job)

    # Jobs ------------------------------------------------------------------

    @app.get("/api/jobs/{job_id}")
    def job(job_id: str) -> dict:
        record = container.store.get_job(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="job not found")
        return _job_payload(record)

    @app.get("/api/jobs")
    def jobs(
        active: bool = Query(default=False), limit: int = Query(default=20, ge=1, le=100)
    ) -> list[dict]:
        records = (
            container.store.list_active_jobs()
            if active
            else container.store.list_jobs(limit)
        )
        return [_job_payload(record) for record in records]

    # Settings --------------------------------------------------------------

    @app.get("/api/settings")
    def get_settings() -> dict:
        current = container.settings
        return {
            "library_root": str(current.library_root),
            "data_dir": str(current.data_dir),
            "output_ext": current.output_ext,
            "detector_version": current.detector_version,
            "detection": current.detection.as_dict(),
        }

    @app.put("/api/settings")
    def update_settings(request: DetectionUpdate) -> dict:
        values = {
            key: value
            for key, value in request.model_dump().items()
            if value is not None
        }
        current = container.settings_manager.update_detection(values)
        return {
            "detection": current.detection.as_dict(),
        }

    @app.get("/api/thumbnails/{key}")
    def thumbnail(key: str) -> FileResponse:
        if not THUMB_KEY.fullmatch(key):
            raise HTTPException(status_code=400, detail="invalid thumbnail key")
        path = container.settings.thumbs_dir / f"{key}.jpg"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="thumbnail not found")
        return FileResponse(path)

    @app.get("/api/photos/{key}/original")
    def photo_original(key: str) -> FileResponse:
        if not THUMB_KEY.fullmatch(key):
            raise HTTPException(status_code=400, detail="invalid photo key")
        photo = container.store.get_photo_by_thumbnail_key(key)
        if photo is None:
            raise HTTPException(status_code=404, detail="photo not found")
        if photo.path.is_file():
            return FileResponse(photo.path)
        trashed = container.store.find_trash_copy(photo.path)
        if trashed is not None:
            return FileResponse(trashed)
        raise HTTPException(status_code=404, detail="photo file missing")

    return app


def _job_payload(record: JobRecord) -> dict:
    return {
        "id": record.id,
        "kind": record.kind,
        "status": record.status,
        "progress": record.progress,
        "message": record.message,
        "result": record.result,
        "context": record.context,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
    }
