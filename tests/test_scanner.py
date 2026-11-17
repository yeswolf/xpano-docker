from __future__ import annotations

from pathlib import Path

from pano_xpano.adapters.scanner import (
    FilesystemScanner,
    PillowMetadata,
    Thumbnailer,
)
from pano_xpano.config import DetectionSettings

from conftest import make_image


def test_scanner_indexes_supported_images(tmp_path: Path) -> None:
    library = tmp_path / "library"
    make_image(library / "2024" / "a.jpg", (240, 160))
    make_image(library / "2024" / "b.png", (320, 200))
    (library / "2024" / "notes.txt").write_text("ignore", encoding="utf-8")

    scanner = FilesystemScanner(
        metadata_reader=PillowMetadata(),
        thumbnailer=Thumbnailer(tmp_path / "thumbs", 100),
    )
    result = scanner.scan(library, DetectionSettings())

    assert len(result.photos) == 2
    assert result.skipped == []
    assert {photo.path.name for photo in result.photos} == {"a.jpg", "b.png"}
    for photo in result.photos:
        assert photo.width > 0 and photo.height > 0
        assert (tmp_path / "thumbs" / f"{photo.thumbnail_key}.jpg").is_file()
