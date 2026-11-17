from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path


class GroupStatus(StrEnum):
    CANDIDATE = "candidate"
    STITCHED = "stitched"
    REPLACED = "replaced"
    FAILED = "failed"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class StitchStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class OperationStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    UNDONE = "undone"


@dataclass(frozen=True, slots=True)
class Photo:
    path: Path
    captured_at: datetime | None
    modified_at: datetime
    camera: str | None
    lens: str | None
    focal_length: float | None
    width: int
    height: int
    size: int
    thumbnail_key: str

    @property
    def aspect(self) -> float:
        if self.height <= 0:
            return 0.0
        return self.width / self.height


@dataclass(frozen=True, slots=True)
class PairMatch:
    left: Photo
    right: Photo
    inliers: int
    dx_ratio: float
    dy_ratio: float


@dataclass(frozen=True, slots=True)
class DetectedGroup:
    members: tuple[Photo, ...]
    confidence: float


@dataclass(frozen=True, slots=True)
class WatchedFolder:
    id: str
    path: str
    created_at: datetime
    last_scan_at: datetime | None
    last_scan_status: str | None
    photo_count: int = 0
    group_count: int = 0
    image_count: int = 0
    file_count: int = 0


@dataclass(frozen=True, slots=True)
class PanoramaGroup:
    id: str
    folder_id: str
    detector_version: str
    members: tuple[Photo, ...]
    confidence: float
    status: GroupStatus
    created_at: datetime
    updated_at: datetime

    @property
    def first(self) -> Photo:
        return self.members[0]

    @property
    def last(self) -> Photo:
        return self.members[-1]


@dataclass(frozen=True, slots=True)
class StitchRecord:
    id: int | None
    group_id: str
    status: StitchStatus
    output_path: Path | None
    width: int | None
    height: int | None
    error: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class FileMove:
    source: Path
    trash: Path


@dataclass(frozen=True, slots=True)
class ReplacementPlan:
    operation_id: str
    group_id: str
    panorama_source: Path
    target: Path
    temp: Path
    trash_dir: Path
    moves: tuple[FileMove, ...]


@dataclass(frozen=True, slots=True)
class ReplacementOperation:
    id: str
    group_id: str
    status: OperationStatus
    source_paths: tuple[Path, ...]
    trash_paths: tuple[Path, ...]
    trash_dir: Path
    panorama_path: Path | None
    error: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class JobRecord:
    id: str
    kind: str
    status: JobStatus
    progress: float
    message: str | None
    result: dict | None
    context: dict | None
    created_at: datetime
    updated_at: datetime
