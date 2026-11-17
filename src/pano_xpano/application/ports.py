from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol

from pano_xpano.config import DetectionSettings
from pano_xpano.domain.models import (
    DetectedGroup,
    JobRecord,
    JobStatus,
    PanoramaGroup,
    Photo,
    ReplacementOperation,
    ReplacementPlan,
    StitchRecord,
    WatchedFolder,
)

Progress = Callable[[float, str], None]


class StitcherError(RuntimeError):
    pass


class ReplacementError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ScanResult:
    photos: list[Photo]
    skipped: list[tuple[Path, str]]
    total_files: int = 0


@dataclass(frozen=True, slots=True)
class StitchOutput:
    path: Path
    width: int
    height: int


class LibraryScanner(Protocol):
    def scan(self, root: Path, settings: DetectionSettings) -> ScanResult: ...


class FolderCounter(Protocol):
    def count(self, root: Path) -> tuple[int, int]: ...


class GroupDetector(Protocol):
    def detect(
        self,
        photos: list[Photo],
        settings: DetectionSettings,
        detector_version: str,
        progress: Progress | None = None,
    ) -> list[DetectedGroup]: ...


class Stitcher(Protocol):
    def stitch(
        self,
        paths: list[Path],
        output: Path,
        timeout_s: int,
        use_xvfb: bool,
    ) -> StitchOutput: ...


class Replacer(Protocol):
    def execute(
        self, operation: ReplacementOperation, plan: ReplacementPlan
    ) -> None: ...

    def undo(self, operation: ReplacementOperation) -> None: ...


class Store(Protocol):
    def add_folder(self, folder: WatchedFolder) -> None: ...

    def get_folder(self, folder_id: str) -> WatchedFolder | None: ...

    def get_folder_by_path(self, path: str) -> WatchedFolder | None: ...

    def list_folders(self) -> list[WatchedFolder]: ...

    def update_folder_scan(
        self, folder_id: str, when: datetime, status: str
    ) -> None: ...

    def update_folder_counts(
        self, folder_id: str, image_count: int, file_count: int
    ) -> None: ...

    def remove_folder(self, folder_id: str) -> None: ...

    def replace_photos(self, folder_id: str, photos: list[Photo]) -> None: ...

    def list_photos(self, folder_id: str | None = None) -> list[Photo]: ...

    def get_photo_by_thumbnail_key(self, key: str) -> Photo | None: ...

    def find_trash_copy(self, source: Path) -> Path | None: ...

    def sync_candidate_groups(
        self, folder_id: str, groups: list[PanoramaGroup]
    ) -> None: ...

    def list_groups(self, folder_id: str | None = None) -> list[PanoramaGroup]: ...

    def get_group(self, group_id: str) -> PanoramaGroup | None: ...

    def update_group_status(self, group_id: str, status: str) -> None: ...

    def add_stitch(self, record: StitchRecord) -> None: ...

    def latest_stitch(self, group_id: str) -> StitchRecord | None: ...

    def create_operation(self, operation: ReplacementOperation) -> None: ...

    def update_operation(self, operation: ReplacementOperation) -> None: ...

    def get_operation(self, operation_id: str) -> ReplacementOperation | None: ...

    def list_operations(self) -> list[ReplacementOperation]: ...

    def create_job(
        self, kind: str, now: datetime, context: dict | None = None
    ) -> JobRecord: ...

    def update_job(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        progress: float | None = None,
        message: str | None = None,
        result: dict | None = None,
        now: datetime | None = None,
    ) -> JobRecord | None: ...

    def get_job(self, job_id: str) -> JobRecord | None: ...

    def list_jobs(self, limit: int = 20) -> list[JobRecord]: ...

    def list_active_jobs(self) -> list[JobRecord]: ...

    def get_setting(self, key: str) -> str | None: ...

    def set_setting(self, key: str, value: str) -> None: ...
