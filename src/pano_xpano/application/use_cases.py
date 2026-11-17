from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

from pano_xpano.application.ports import (
    FolderCounter,
    GroupDetector,
    LibraryScanner,
    Progress,
    Replacer,
    ReplacementError,
    Stitcher,
    StitcherError,
    Store,
)
from pano_xpano.config import Settings
from pano_xpano.domain.models import (
    GroupStatus,
    OperationStatus,
    PanoramaGroup,
    ReplacementOperation,
    StitchRecord,
    StitchStatus,
    WatchedFolder,
)
from pano_xpano.domain.policies import (
    folder_absolute,
    folder_id_for,
    make_group,
    normalize_folder_path,
    plan_replacement,
    unique_output_path,
)

Clock = Callable[[], datetime]


def _noop_progress(_: float, __: str) -> None:
    return None


class AddFolder:
    def __init__(
        self,
        store: Store,
        settings: Callable[[], Settings],
        counter: FolderCounter,
        clock: Clock = datetime.now,
    ) -> None:
        self._store = store
        self._settings = settings
        self._counter = counter
        self._clock = clock

    def run(self, raw_path: str) -> dict:
        settings = self._settings()
        relative = normalize_folder_path(settings.library_root, raw_path)
        absolute = folder_absolute(settings.library_root, relative)
        if not absolute.is_dir():
            raise ValueError(f"folder does not exist: {relative}")
        existing = self._store.get_folder_by_path(relative)
        if existing is not None:
            return folder_payload(existing)
        image_count, file_count = self._counter.count(absolute)
        folder = WatchedFolder(
            id=folder_id_for(relative),
            path=relative,
            created_at=self._clock(),
            last_scan_at=None,
            last_scan_status="never",
            image_count=image_count,
            file_count=file_count,
        )
        self._store.add_folder(folder)
        return folder_payload(folder)


class RemoveFolder:
    def __init__(self, store: Store) -> None:
        self._store = store

    def run(self, folder_id: str) -> None:
        folder = self._store.get_folder(folder_id)
        if folder is None:
            raise ValueError(f"unknown folder: {folder_id}")
        for job in self._store.list_active_jobs():
            context = job.context or {}
            if context.get("folder_id") == folder_id:
                raise ValueError("folder is being scanned; wait for the job to finish")
        self._store.remove_folder(folder_id)


class ScanLibrary:
    def __init__(
        self,
        scanner: LibraryScanner,
        detector: GroupDetector,
        store: Store,
        settings: Callable[[], Settings],
        clock: Clock = datetime.now,
    ) -> None:
        self._scanner = scanner
        self._detector = detector
        self._store = store
        self._settings = settings
        self._clock = clock

    def run(
        self,
        folder_id: str | None = None,
        progress: Progress | None = None,
    ) -> dict:
        report = progress or _noop_progress
        settings = self._settings()
        if folder_id is not None:
            folder = self._store.get_folder(folder_id)
            if folder is None:
                raise ValueError(f"unknown folder: {folder_id}")
            result = self._scan_folder(folder, settings, report)
            report(1.0, "scan finished")
            return result

        folders = self._store.list_folders()
        if not folders:
            raise ValueError("no watched folders; add a folder first")
        results = []
        total_photos = 0
        total_groups = 0
        for index, folder in enumerate(folders):
            start = index / len(folders)
            span = 1 / len(folders)

            def folder_progress(
                value: float, message: str, start=start, span=span
            ) -> None:
                report(start + value * span, f"{folder.path}: {message}")

            result = self._scan_folder(folder, settings, folder_progress)
            results.append(result)
            total_photos += result["photos"]
            total_groups += result["groups"]
        report(1.0, "scan finished")
        return {
            "folders": len(folders),
            "photos": total_photos,
            "groups": total_groups,
            "results": results,
        }

    def _scan_folder(
        self, folder: WatchedFolder, settings: Settings, report: Progress
    ) -> dict:
        root = folder_absolute(settings.library_root, folder.path)
        report(0.02, "scanning files")
        try:
            scan = self._scanner.scan(root, settings.detection)
        except Exception:
            self._store.update_folder_scan(folder.id, self._clock(), "failed")
            raise
        report(0.35, f"indexed {len(scan.photos)} photos")

        def detector_progress(value: float, message: str) -> None:
            report(0.35 + value * 0.60, message)

        try:
            detected = self._detector.detect(
                scan.photos,
                settings.detection,
                settings.detector_version,
                detector_progress,
            )
        except Exception:
            self._store.update_folder_scan(folder.id, self._clock(), "failed")
            raise
        now = self._clock()
        groups = [
            make_group(group, settings.detector_version, folder.id, now)
            for group in detected
        ]
        self._store.replace_photos(folder.id, scan.photos)
        self._store.sync_candidate_groups(folder.id, groups)
        self._store.update_folder_counts(
            folder.id,
            len(scan.photos) + len(scan.skipped),
            scan.total_files,
        )
        self._store.update_folder_scan(folder.id, now, "completed")
        report(1.0, f"found {len(groups)} candidate groups")
        return {
            "folder_id": folder.id,
            "path": folder.path,
            "photos": len(scan.photos),
            "groups": len(groups),
            "skipped": [
                {"path": str(path), "reason": reason}
                for path, reason in scan.skipped
            ],
        }


class StitchGroup:
    def __init__(
        self,
        store: Store,
        stitcher: Stitcher,
        settings: Callable[[], Settings],
        clock: Clock = datetime.now,
    ) -> None:
        self._store = store
        self._stitcher = stitcher
        self._settings = settings
        self._clock = clock

    def run(self, group_id: str, progress: Progress | None = None) -> dict:
        report = progress or _noop_progress
        group = self._store.get_group(group_id)
        if group is None:
            raise ValueError(f"unknown group: {group_id}")
        settings = self._settings()
        output_dir = settings.stitch_dir / group.id
        output_dir.mkdir(parents=True, exist_ok=True)
        output = unique_output_path(
            output_dir,
            f"pano_{self._clock():%Y%m%d_%H%M%S}",
            settings.output_ext,
        )
        now = self._clock()
        running = StitchRecord(
            id=None,
            group_id=group.id,
            status=StitchStatus.RUNNING,
            output_path=output,
            width=None,
            height=None,
            error=None,
            created_at=now,
            updated_at=now,
        )
        self._store.add_stitch(running)
        report(0.05, "starting Xpano")
        try:
            result = self._stitcher.stitch(
                [photo.path for photo in group.members],
                output,
                settings.stitch_timeout_s,
                settings.use_xvfb,
            )
        except Exception as error:
            failed = StitchRecord(
                id=None,
                group_id=group.id,
                status=StitchStatus.FAILED,
                output_path=output,
                width=None,
                height=None,
                error=str(error),
                created_at=now,
                updated_at=self._clock(),
            )
            self._store.add_stitch(failed)
            self._store.update_group_status(group.id, GroupStatus.FAILED)
            raise
        completed = StitchRecord(
            id=None,
            group_id=group.id,
            status=StitchStatus.COMPLETED,
            output_path=result.path,
            width=result.width,
            height=result.height,
            error=None,
            created_at=now,
            updated_at=self._clock(),
        )
        self._store.add_stitch(completed)
        self._store.update_group_status(group.id, GroupStatus.STITCHED)
        report(1.0, "panorama ready")
        return {
            "group_id": group.id,
            "output": str(result.path),
            "width": result.width,
            "height": result.height,
        }


class ReplaceGroup:
    def __init__(
        self,
        store: Store,
        replacer: Replacer,
        settings: Callable[[], Settings],
        clock: Clock = datetime.now,
    ) -> None:
        self._store = store
        self._replacer = replacer
        self._settings = settings
        self._clock = clock

    def run(
        self, group_id: str, confirm: bool, progress: Progress | None = None
    ) -> dict:
        if not confirm:
            raise ValueError("replacement requires explicit confirmation")
        report = progress or _noop_progress
        group = self._store.get_group(group_id)
        if group is None:
            raise ValueError(f"unknown group: {group_id}")
        stitch = self._store.latest_stitch(group.id)
        if stitch is None or stitch.status != StitchStatus.COMPLETED:
            raise ReplacementError("group has no completed stitch")
        if stitch.output_path is None or not stitch.output_path.is_file():
            raise ReplacementError("stitched panorama is missing")

        settings = self._settings()
        operation_id = uuid.uuid4().hex
        plan = plan_replacement(
            group,
            stitch.output_path,
            settings.library_root,
            settings.trash_dir,
            operation_id,
            settings.output_ext,
        )
        now = self._clock()
        operation = ReplacementOperation(
            id=operation_id,
            group_id=group.id,
            status=OperationStatus.RUNNING,
            source_paths=tuple(move.source for move in plan.moves),
            trash_paths=tuple(move.trash for move in plan.moves),
            trash_dir=plan.trash_dir,
            panorama_path=plan.target,
            error=None,
            created_at=now,
            updated_at=now,
        )
        self._store.create_operation(operation)
        report(0.1, "writing panorama")
        try:
            self._replacer.execute(operation, plan)
        except Exception as error:
            failed = ReplacementOperation(
                id=operation.id,
                group_id=operation.group_id,
                status=OperationStatus.FAILED,
                source_paths=operation.source_paths,
                trash_paths=operation.trash_paths,
                trash_dir=operation.trash_dir,
                panorama_path=operation.panorama_path,
                error=str(error),
                created_at=operation.created_at,
                updated_at=self._clock(),
            )
            self._store.update_operation(failed)
            self._store.update_group_status(group.id, GroupStatus.FAILED)
            raise
        completed = ReplacementOperation(
            id=operation.id,
            group_id=operation.group_id,
            status=OperationStatus.COMPLETED,
            source_paths=operation.source_paths,
            trash_paths=operation.trash_paths,
            trash_dir=operation.trash_dir,
            panorama_path=operation.panorama_path,
            error=None,
            created_at=operation.created_at,
            updated_at=self._clock(),
        )
        self._store.update_operation(completed)
        self._store.update_group_status(group.id, GroupStatus.REPLACED)
        report(1.0, "group replaced")
        return {
            "operation_id": operation.id,
            "panorama": str(plan.target),
            "trashed": [str(move.source) for move in plan.moves],
        }


class UndoReplacement:
    def __init__(
        self,
        store: Store,
        replacer: Replacer,
        clock: Clock = datetime.now,
    ) -> None:
        self._store = store
        self._replacer = replacer
        self._clock = clock

    def run(self, operation_id: str, progress: Progress | None = None) -> dict:
        report = progress or _noop_progress
        operation = self._store.get_operation(operation_id)
        if operation is None:
            raise ValueError(f"unknown operation: {operation_id}")
        if operation.status != OperationStatus.COMPLETED:
            raise ReplacementError("only a completed replacement can be undone")
        report(0.1, "restoring originals")
        self._replacer.undo(operation)
        undone = ReplacementOperation(
            id=operation.id,
            group_id=operation.group_id,
            status=OperationStatus.UNDONE,
            source_paths=operation.source_paths,
            trash_paths=operation.trash_paths,
            trash_dir=operation.trash_dir,
            panorama_path=operation.panorama_path,
            error=None,
            created_at=operation.created_at,
            updated_at=self._clock(),
        )
        self._store.update_operation(undone)
        self._store.update_group_status(operation.group_id, GroupStatus.STITCHED)
        report(1.0, "originals restored")
        return {"operation_id": operation.id, "status": "undone"}


def folder_payload(folder: WatchedFolder) -> dict:
    return {
        "id": folder.id,
        "path": folder.path,
        "created_at": folder.created_at.isoformat(),
        "last_scan_at": folder.last_scan_at.isoformat() if folder.last_scan_at else None,
        "last_scan_status": folder.last_scan_status or "never",
        "photo_count": folder.photo_count,
        "group_count": folder.group_count,
        "image_count": folder.image_count,
        "file_count": folder.file_count,
    }


def group_payload(
    group: PanoramaGroup, stitch: StitchRecord | None
) -> dict:
    return {
        "id": group.id,
        "folder_id": group.folder_id,
        "status": group.status,
        "confidence": group.confidence,
        "detector_version": group.detector_version,
        "created_at": group.created_at.isoformat(),
        "updated_at": group.updated_at.isoformat(),
        "members": [photo_payload(photo) for photo in group.members],
        "stitch": stitch_payload(stitch) if stitch else None,
    }


def photo_payload(photo) -> dict:
    return {
        "path": str(photo.path),
        "name": photo.path.name,
        "captured_at": photo.captured_at.isoformat() if photo.captured_at else None,
        "camera": photo.camera,
        "lens": photo.lens,
        "focal_length": photo.focal_length,
        "width": photo.width,
        "height": photo.height,
        "size": photo.size,
        "thumbnail": f"/api/thumbnails/{photo.thumbnail_key}",
        "original": f"/api/photos/{photo.thumbnail_key}/original",
    }


def stitch_payload(stitch: StitchRecord) -> dict:
    return {
        "status": stitch.status,
        "output": str(stitch.output_path) if stitch.output_path else None,
        "width": stitch.width,
        "height": stitch.height,
        "error": stitch.error,
        "created_at": stitch.created_at.isoformat(),
    }


def operation_payload(operation: ReplacementOperation) -> dict:
    return {
        "id": operation.id,
        "group_id": operation.group_id,
        "status": operation.status,
        "panorama": str(operation.panorama_path) if operation.panorama_path else None,
        "sources": [str(path) for path in operation.source_paths],
        "trash": [str(path) for path in operation.trash_paths],
        "trash_dir": str(operation.trash_dir),
        "error": operation.error,
        "created_at": operation.created_at.isoformat(),
        "updated_at": operation.updated_at.isoformat(),
    }
