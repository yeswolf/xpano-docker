from __future__ import annotations

import sqlite3
from pathlib import Path

from pano_xpano.adapters.store import SqliteStore


def test_old_database_is_migrated(tmp_path: Path) -> None:
    path = tmp_path / "state.sqlite3"
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE photos (
            path TEXT PRIMARY KEY,
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
        CREATE TABLE groups (
            id TEXT PRIMARY KEY,
            detector_version TEXT NOT NULL,
            members TEXT NOT NULL,
            confidence REAL NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE jobs (
            id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            status TEXT NOT NULL,
            progress REAL NOT NULL,
            message TEXT,
            result TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        INSERT INTO photos VALUES (
            '/library/old.jpg', NULL, '2024-05-01T12:00:00',
            'Camera', '35mm', 35.0, 1200, 800, 5, 'a'
        );
        """
    )
    connection.commit()
    connection.close()

    store = SqliteStore(path)
    photos = store.list_photos()
    assert [photo.path.name for photo in photos] == ["old.jpg"]
    assert store.list_folders() == []
    assert store.list_groups() == []
