from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from pano_xpano.domain.models import (
    GroupStatus,
    JobRecord,
    JobStatus,
    OperationStatus,
    PanoramaGroup,
    Photo,
    ReplacementOperation,
    StitchRecord,
    StitchStatus,
    WatchedFolder,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS folders (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    last_scan_at TEXT,
    last_scan_status TEXT,
    image_count INTEGER NOT NULL DEFAULT 0,
    file_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS photos (
    path TEXT PRIMARY KEY,
    folder_id TEXT NOT NULL DEFAULT '',
    captured_at TEXT,
    modified_at TEXT NOT NULL,
    camera TEXT,
    lens TEXT,
    focal_length REAL,
    width INTEGER NOT NULL,
    height INTEGER NOT NULL,
    size INTEGER NOT NULL,
    thumbnail_key TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS groups (
    id TEXT PRIMARY KEY,
    folder_id TEXT NOT NULL DEFAULT '',
    detector_version TEXT NOT NULL,
    members TEXT NOT NULL,
    confidence REAL NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS stitches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id TEXT NOT NULL,
    status TEXT NOT NULL,
    output_path TEXT,
    width INTEGER,
    height INTEGER,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS operations (
    id TEXT PRIMARY KEY,
    group_id TEXT NOT NULL,
    status TEXT NOT NULL,
    source_paths TEXT NOT NULL,
    trash_paths TEXT NOT NULL,
    trash_dir TEXT NOT NULL,
    panorama_path TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    progress REAL NOT NULL,
    message TEXT,
    result TEXT,
    context TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
"""


class SqliteStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            _ensure_column(connection, "photos", "folder_id", "TEXT NOT NULL DEFAULT ''")
            _ensure_column(connection, "groups", "folder_id", "TEXT NOT NULL DEFAULT ''")
            _ensure_column(connection, "jobs", "context", "TEXT")
            _ensure_column(connection, "folders", "image_count", "INTEGER NOT NULL DEFAULT 0")
            _ensure_column(connection, "folders", "file_count", "INTEGER NOT NULL DEFAULT 0")
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_photos_folder ON photos(folder_id)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_photos_thumb ON photos(thumbnail_key)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_groups_folder ON groups(folder_id)"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    # Folders ---------------------------------------------------------------

    def add_folder(self, folder: WatchedFolder) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO folders
                (id, path, created_at, last_scan_at, last_scan_status,
                 image_count, file_count)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    folder.id,
                    folder.path,
                    _dt(folder.created_at),
                    _dt(folder.last_scan_at),
                    folder.last_scan_status,
                    folder.image_count,
                    folder.file_count,
                ),
            )

    def get_folder(self, folder_id: str) -> WatchedFolder | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM folders WHERE id = ?", (folder_id,)
            ).fetchone()
            if row is None:
                return None
            return self._folder_with_counts(connection, row)

    def get_folder_by_path(self, path: str) -> WatchedFolder | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM folders WHERE path = ?", (path,)
            ).fetchone()
            if row is None:
                return None
            return self._folder_with_counts(connection, row)

    def list_folders(self) -> list[WatchedFolder]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM folders ORDER BY path"
            ).fetchall()
            return [self._folder_with_counts(connection, row) for row in rows]

    def _folder_with_counts(
        self, connection: sqlite3.Connection, row: sqlite3.Row
    ) -> WatchedFolder:
        photo_count = connection.execute(
            "SELECT count(*) FROM photos WHERE folder_id = ?", (row["id"],)
        ).fetchone()[0]
        group_count = connection.execute(
            "SELECT count(*) FROM groups WHERE folder_id = ?", (row["id"],)
        ).fetchone()[0]
        return WatchedFolder(
            id=row["id"],
            path=row["path"],
            created_at=_parse(row["created_at"]),
            last_scan_at=_maybe_parse(row["last_scan_at"]),
            last_scan_status=row["last_scan_status"],
            photo_count=photo_count,
            group_count=group_count,
            image_count=row["image_count"],
            file_count=row["file_count"],
        )

    def update_folder_scan(
        self, folder_id: str, when: datetime, status: str
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE folders
                SET last_scan_at = ?, last_scan_status = ?
                WHERE id = ?
                """,
                (_dt(when), status, folder_id),
            )

    def update_folder_counts(
        self, folder_id: str, image_count: int, file_count: int
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE folders
                SET image_count = ?, file_count = ?
                WHERE id = ?
                """,
                (image_count, file_count, folder_id),
            )

    def remove_folder(self, folder_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM photos WHERE folder_id = ?", (folder_id,))
            connection.execute("DELETE FROM groups WHERE folder_id = ?", (folder_id,))
            connection.execute("DELETE FROM folders WHERE id = ?", (folder_id,))

    # Photos -----------------------------------------------------------------

    def replace_photos(self, folder_id: str, photos: list[Photo]) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM photos WHERE folder_id = ?", (folder_id,)
            )
            connection.executemany(
                """
                INSERT INTO photos
                (path, folder_id, captured_at, modified_at, camera, lens,
                 focal_length, width, height, size, thumbnail_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        str(photo.path),
                        folder_id,
                        _dt(photo.captured_at),
                        _dt(photo.modified_at),
                        photo.camera,
                        photo.lens,
                        photo.focal_length,
                        photo.width,
                        photo.height,
                        photo.size,
                        photo.thumbnail_key,
                    )
                    for photo in photos
                ],
            )

    def list_photos(self, folder_id: str | None = None) -> list[Photo]:
        with self._connect() as connection:
            if folder_id is None:
                rows = connection.execute("SELECT * FROM photos").fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM photos WHERE folder_id = ?", (folder_id,)
                ).fetchall()
        return [_photo_from_row(row) for row in rows]

    def get_photo_by_thumbnail_key(self, key: str) -> Photo | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM photos WHERE thumbnail_key = ? LIMIT 1", (key,)
            ).fetchone()
        return _photo_from_row(row) if row else None

    def find_trash_copy(self, source: Path) -> Path | None:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT source_paths, trash_paths FROM operations
                WHERE status = ?
                ORDER BY created_at DESC
                """,
                (str(OperationStatus.COMPLETED),),
            ).fetchall()
        for row in rows:
            sources = json.loads(row["source_paths"])
            trashes = json.loads(row["trash_paths"])
            for original, trashed in zip(sources, trashes):
                if original != str(source):
                    continue
                candidate = Path(trashed)
                if candidate.is_file():
                    return candidate
        return None

    # Groups -----------------------------------------------------------------

    def sync_candidate_groups(
        self, folder_id: str, groups: list[PanoramaGroup]
    ) -> None:
        ids = {group.id for group in groups}
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT id FROM groups WHERE status = ? AND folder_id = ?",
                (GroupStatus.CANDIDATE, folder_id),
            ).fetchall()
            stale = [row["id"] for row in existing if row["id"] not in ids]
            if stale:
                connection.executemany(
                    "DELETE FROM groups WHERE id = ?", [(value,) for value in stale]
                )
            for group in groups:
                connection.execute(
                    """
                    INSERT INTO groups
                    (id, folder_id, detector_version, members, confidence, status,
                     created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        folder_id=excluded.folder_id,
                        detector_version=excluded.detector_version,
                        members=excluded.members,
                        confidence=excluded.confidence,
                        updated_at=excluded.updated_at
                    """,
                    (
                        group.id,
                        group.folder_id,
                        group.detector_version,
                        json.dumps([str(photo.path) for photo in group.members]),
                        group.confidence,
                        group.status,
                        _dt(group.created_at),
                        _dt(group.updated_at),
                    ),
                )

    def list_groups(self, folder_id: str | None = None) -> list[PanoramaGroup]:
        with self._connect() as connection:
            if folder_id is None:
                rows = connection.execute(
                    "SELECT * FROM groups ORDER BY updated_at DESC"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM groups WHERE folder_id = ? ORDER BY updated_at DESC",
                    (folder_id,),
                ).fetchall()
        groups = [self._group_from_row(row) for row in rows]
        return [group for group in groups if group.members]

    def get_group(self, group_id: str) -> PanoramaGroup | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM groups WHERE id = ?", (group_id,)
            ).fetchone()
        if row is None:
            return None
        return self._group_from_row(row)

    def update_group_status(self, group_id: str, status: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE groups SET status = ?, updated_at = ? WHERE id = ?",
                (str(status), _dt(datetime.now()), group_id),
            )

    def _group_from_row(self, row: sqlite3.Row) -> PanoramaGroup:
        paths = json.loads(row["members"])
        photos: list[Photo] = []
        if paths:
            with self._connect() as connection:
                placeholders = ",".join("?" for _ in paths)
                found = connection.execute(
                    f"SELECT * FROM photos WHERE path IN ({placeholders})", paths
                ).fetchall()
            by_path = {found_row["path"]: _photo_from_row(found_row) for found_row in found}
            photos = [by_path[path] for path in paths if path in by_path]
        return PanoramaGroup(
            id=row["id"],
            folder_id=row["folder_id"],
            detector_version=row["detector_version"],
            members=tuple(photos),
            confidence=row["confidence"],
            status=GroupStatus(row["status"]),
            created_at=_parse(row["created_at"]),
            updated_at=_parse(row["updated_at"]),
        )

    # Stitches ---------------------------------------------------------------

    def add_stitch(self, record: StitchRecord) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO stitches
                (group_id, status, output_path, width, height, error,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.group_id,
                    str(record.status),
                    str(record.output_path) if record.output_path else None,
                    record.width,
                    record.height,
                    record.error,
                    _dt(record.created_at),
                    _dt(record.updated_at),
                ),
            )

    def latest_stitch(self, group_id: str) -> StitchRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM stitches WHERE group_id = ? ORDER BY id DESC LIMIT 1",
                (group_id,),
            ).fetchone()
        return _stitch_from_row(row) if row else None

    # Operations -------------------------------------------------------------

    def create_operation(self, operation: ReplacementOperation) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO operations
                (id, group_id, status, source_paths, trash_paths, trash_dir,
                 panorama_path, error, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                _operation_values(operation),
            )

    def update_operation(self, operation: ReplacementOperation) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE operations SET
                    status = ?, source_paths = ?, trash_paths = ?,
                    trash_dir = ?, panorama_path = ?, error = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    str(operation.status),
                    json.dumps([str(path) for path in operation.source_paths]),
                    json.dumps([str(path) for path in operation.trash_paths]),
                    str(operation.trash_dir),
                    str(operation.panorama_path)
                    if operation.panorama_path
                    else None,
                    operation.error,
                    _dt(operation.updated_at),
                    operation.id,
                ),
            )

    def get_operation(self, operation_id: str) -> ReplacementOperation | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM operations WHERE id = ?", (operation_id,)
            ).fetchone()
        return _operation_from_row(row) if row else None

    def list_operations(self) -> list[ReplacementOperation]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM operations ORDER BY created_at DESC"
            ).fetchall()
        return [_operation_from_row(row) for row in rows]

    # Jobs -------------------------------------------------------------------

    def create_job(
        self, kind: str, now: datetime, context: dict | None = None
    ) -> JobRecord:
        job_id = uuid.uuid4().hex
        record = JobRecord(
            id=job_id,
            kind=kind,
            status=JobStatus.QUEUED,
            progress=0.0,
            message=None,
            result=None,
            context=context,
            created_at=now,
            updated_at=now,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs
                (id, kind, status, progress, message, result, context,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.kind,
                    str(record.status),
                    record.progress,
                    record.message,
                    None,
                    json.dumps(context) if context else None,
                    _dt(now),
                    _dt(now),
                ),
            )
        return record

    def update_job(
        self,
        job_id: str,
        *,
        status: JobStatus | None = None,
        progress: float | None = None,
        message: str | None = None,
        result: dict | None = None,
        now: datetime | None = None,
    ) -> JobRecord | None:
        fields = ["updated_at = ?"]
        values: list[object] = [_dt(now or datetime.now())]
        if status is not None:
            fields.append("status = ?")
            values.append(str(status))
        if progress is not None:
            fields.append("progress = ?")
            values.append(max(0.0, min(1.0, progress)))
        if message is not None:
            fields.append("message = ?")
            values.append(message)
        if result is not None:
            fields.append("result = ?")
            values.append(json.dumps(result))
        values.append(job_id)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE jobs SET {', '.join(fields)} WHERE id = ?", values
            )
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (job_id,)
            ).fetchone()
        return _job_from_row(row) if row else None

    def list_jobs(self, limit: int = 20) -> list[JobRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_job_from_row(row) for row in rows]

    def list_active_jobs(self) -> list[JobRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM jobs
                WHERE status IN (?, ?)
                ORDER BY created_at DESC
                """,
                (str(JobStatus.QUEUED), str(JobStatus.RUNNING)),
            ).fetchall()
        return [_job_from_row(row) for row in rows]

    def fail_unfinished_jobs(self, reason: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET status = ?, message = ?, updated_at = ?
                WHERE status IN (?, ?)
                """,
                (
                    str(JobStatus.FAILED),
                    reason,
                    _dt(datetime.now()),
                    str(JobStatus.QUEUED),
                    str(JobStatus.RUNNING),
                ),
            )

    # Settings ---------------------------------------------------------------

    def get_setting(self, key: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, value),
            )


def _ensure_column(
    connection: sqlite3.Connection, table: str, column: str, definition: str
) -> None:
    existing = {
        row[1] for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }
    if column not in existing:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _photo_from_row(row: sqlite3.Row) -> Photo:
    return Photo(
        path=Path(row["path"]),
        captured_at=_maybe_parse(row["captured_at"]),
        modified_at=_parse(row["modified_at"]),
        camera=row["camera"],
        lens=row["lens"],
        focal_length=row["focal_length"],
        width=row["width"],
        height=row["height"],
        size=row["size"],
        thumbnail_key=row["thumbnail_key"],
    )


def _stitch_from_row(row: sqlite3.Row) -> StitchRecord:
    return StitchRecord(
        id=row["id"],
        group_id=row["group_id"],
        status=StitchStatus(row["status"]),
        output_path=Path(row["output_path"]) if row["output_path"] else None,
        width=row["width"],
        height=row["height"],
        error=row["error"],
        created_at=_parse(row["created_at"]),
        updated_at=_parse(row["updated_at"]),
    )


def _operation_values(operation: ReplacementOperation) -> tuple:
    return (
        operation.id,
        operation.group_id,
        str(operation.status),
        json.dumps([str(path) for path in operation.source_paths]),
        json.dumps([str(path) for path in operation.trash_paths]),
        str(operation.trash_dir),
        str(operation.panorama_path) if operation.panorama_path else None,
        operation.error,
        _dt(operation.created_at),
        _dt(operation.updated_at),
    )


def _operation_from_row(row: sqlite3.Row) -> ReplacementOperation:
    return ReplacementOperation(
        id=row["id"],
        group_id=row["group_id"],
        status=OperationStatus(row["status"]),
        source_paths=tuple(Path(path) for path in json.loads(row["source_paths"])),
        trash_paths=tuple(Path(path) for path in json.loads(row["trash_paths"])),
        trash_dir=Path(row["trash_dir"]),
        panorama_path=Path(row["panorama_path"]) if row["panorama_path"] else None,
        error=row["error"],
        created_at=_parse(row["created_at"]),
        updated_at=_parse(row["updated_at"]),
    )


def _job_from_row(row: sqlite3.Row) -> JobRecord:
    return JobRecord(
        id=row["id"],
        kind=row["kind"],
        status=JobStatus(row["status"]),
        progress=row["progress"],
        message=row["message"],
        result=json.loads(row["result"]) if row["result"] else None,
        context=json.loads(row["context"]) if row["context"] else None,
        created_at=_parse(row["created_at"]),
        updated_at=_parse(row["updated_at"]),
    )


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _maybe_parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None
