from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image

from pano_xpano.application.ports import ScanResult, StitchOutput
from pano_xpano.config import DetectionSettings, Settings
from pano_xpano.domain.models import DetectedGroup, Photo


def make_photo(
    path: Path,
    captured_at: datetime | None = None,
    *,
    camera: str = "Camera",
    focal: float = 35.0,
    width: int = 1200,
    height: int = 800,
) -> Photo:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"photo")
    moment = captured_at or datetime(2024, 5, 1, 12, 0, 0)
    return Photo(
        path=path,
        captured_at=captured_at,
        modified_at=moment,
        camera=camera,
        lens="35mm",
        focal_length=focal,
        width=width,
        height=height,
        size=5,
        thumbnail_key="0" * 40,
    )


def make_image(path: Path, size: tuple[int, int] = (240, 160)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (40, 120, 180)).save(path, "JPEG")


def make_panorama(path: Path, size: tuple[int, int] = (600, 240)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (200, 180, 60)).save(path, "JPEG")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    library = tmp_path / "library"
    library.mkdir()
    return Settings(
        library_root=library,
        data_dir=tmp_path / "data",
        xpano_bin="Xpano",
        host="127.0.0.1",
        port=3040,
        detector_version="test-v1",
        output_ext=".jpg",
        stitch_timeout_s=30,
        use_xvfb=False,
        thumb_size=120,
        detection=DetectionSettings(),
    )


class FakeScanner:
    def __init__(self, photos: list[Photo]) -> None:
        self.photos = photos

    def scan(self, root: Path, settings: DetectionSettings) -> ScanResult:
        return ScanResult(
            photos=self.photos, skipped=[], total_files=len(self.photos)
        )


class FakeDetector:
    def __init__(self, photos: list[Photo]) -> None:
        self.photos = photos

    def detect(self, photos, settings, detector_version, progress=None) -> list[DetectedGroup]:
        if progress:
            progress(1.0, "fake detection")
        return [DetectedGroup(members=tuple(self.photos), confidence=0.9)]


class FakeStitcher:
    def stitch(self, paths, output, timeout_s, use_xvfb) -> StitchOutput:
        make_panorama(output)
        return StitchOutput(path=output, width=600, height=240)


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2024, 5, 1, 12, 0, 0)

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now
