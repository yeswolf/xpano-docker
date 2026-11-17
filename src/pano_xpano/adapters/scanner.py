from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps

from pano_xpano.application.ports import ScanResult
from pano_xpano.config import DetectionSettings
from pano_xpano.domain.models import Photo

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
    ".bmp",
}
SKIP_DIR_NAMES = {
    "@eaDir",
    "#recycle",
    "System Volume Information",
    "__MACOSX",
}
EXIF_FIELDS = [
    "SourceFile",
    "DateTimeOriginal",
    "CreateDate",
    "Model",
    "LensModel",
    "FocalLength",
    "ImageWidth",
    "ImageHeight",
    "ExifImageWidth",
    "ExifImageHeight",
    "Orientation",
    "FileModifyDate",
]


@dataclass(frozen=True, slots=True)
class Metadata:
    captured_at: datetime | None = None
    modified_at: datetime | None = None
    camera: str | None = None
    lens: str | None = None
    focal_length: float | None = None
    width: int | None = None
    height: int | None = None


class ExifToolReader:
    def __init__(self, binary: str = "exiftool", batch_size: int = 100) -> None:
        self._binary = binary
        self._batch_size = batch_size

    def read_many(self, paths: list[Path]) -> dict[Path, Metadata]:
        result: dict[Path, Metadata] = {}
        for start in range(0, len(paths), self._batch_size):
            batch = paths[start : start + self._batch_size]
            result.update(self._read_batch(batch))
        return result

    def _read_batch(self, paths: list[Path]) -> dict[Path, Metadata]:
        command = [
            self._binary,
            "-json",
            "-q",
            "-q",
            "-n",
            *[f"-{field}" for field in EXIF_FIELDS],
            *[str(path) for path in paths],
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            logger.warning("exiftool failed: %s", error)
            return {}
        if completed.returncode != 0 and not completed.stdout.strip():
            logger.warning("exiftool exited with %s", completed.returncode)
            return {}
        try:
            rows = json.loads(completed.stdout or "[]")
        except ValueError:
            logger.warning("exiftool returned invalid JSON")
            return {}
        output: dict[Path, Metadata] = {}
        for row in rows:
            source = row.get("SourceFile")
            if not source:
                continue
            path = Path(source)
            output[path] = Metadata(
                captured_at=_parse_datetime(
                    row.get("DateTimeOriginal") or row.get("CreateDate")
                ),
                modified_at=_parse_datetime(row.get("FileModifyDate")),
                camera=row.get("Model"),
                lens=row.get("LensModel"),
                focal_length=_as_float(row.get("FocalLength")),
                width=_as_int(row.get("ImageWidth") or row.get("ExifImageWidth")),
                height=_as_int(row.get("ImageHeight") or row.get("ExifImageHeight")),
            )
        return output


class PillowMetadata:
    """Fallback metadata reader used when ExifTool is unavailable."""

    def read_many(self, paths: list[Path]) -> dict[Path, Metadata]:
        output: dict[Path, Metadata] = {}
        for path in paths:
            try:
                with Image.open(path) as image:
                    exif = image.getexif()
                    output[path] = Metadata(
                        captured_at=_parse_datetime(
                            exif.get(36867) or exif.get(306)
                        ),
                        modified_at=datetime.fromtimestamp(path.stat().st_mtime),
                        camera=exif.get(272),
                        lens=exif.get(42036),
                        focal_length=_as_float(exif.get(37386)),
                        width=image.width,
                        height=image.height,
                    )
            except OSError:
                output[path] = Metadata(
                    modified_at=datetime.fromtimestamp(path.stat().st_mtime)
                )
        return output


class Thumbnailer:
    def __init__(self, directory: Path, size: int = 360) -> None:
        self._directory = directory
        self._size = size

    def create(self, path: Path, key: str) -> bool:
        target = self._directory / f"{key}.jpg"
        if target.is_file():
            return True
        try:
            with Image.open(path) as image:
                image = ImageOps.exif_transpose(image)
                if image.mode not in ("RGB", "L"):
                    image = image.convert("RGB")
                image.thumbnail((self._size, self._size), Image.Resampling.LANCZOS)
                target.parent.mkdir(parents=True, exist_ok=True)
                image.save(target, "JPEG", quality=82, optimize=True)
            return True
        except (OSError, ValueError, Image.DecompressionBombError) as error:
            logger.warning("thumbnail failed for %s: %s", path, error)
            return False


class FilesystemScanner:
    def __init__(
        self,
        metadata_reader: ExifToolReader | PillowMetadata | None = None,
        thumbnailer: Thumbnailer | None = None,
    ) -> None:
        self._metadata_reader = metadata_reader or ExifToolReader()
        self._thumbnailer = thumbnailer

    def set_thumbnailer(self, thumbnailer: Thumbnailer) -> None:
        self._thumbnailer = thumbnailer

    def scan(self, root: Path, settings: DetectionSettings) -> ScanResult:
        if self._thumbnailer is None:
            raise RuntimeError("thumbnailer is not configured")
        root = root.resolve()
        all_files = list(_iter_files(root))
        paths = [
            path
            for path in all_files
            if path.suffix.lower() in SUPPORTED_EXTENSIONS
        ]
        metadata = self._metadata_reader.read_many(paths)
        if not metadata and paths:
            metadata = PillowMetadata().read_many(paths)
        photos: list[Photo] = []
        skipped: list[tuple[Path, str]] = []
        for path in paths:
            try:
                stat = path.stat()
            except OSError as error:
                skipped.append((path, str(error)))
                continue
            meta = metadata.get(path) or metadata.get(path.resolve()) or Metadata()
            width = meta.width or 0
            height = meta.height or 0
            if width <= 0 or height <= 0:
                try:
                    with Image.open(path) as image:
                        width, height = image.size
                except (OSError, ValueError) as error:
                    skipped.append((path, f"cannot read image: {error}"))
                    continue
            key = hashlib.sha1(str(path).encode("utf-8")).hexdigest()
            if not self._thumbnailer.create(path, key):
                skipped.append((path, "thumbnail generation failed"))
                continue
            photos.append(
                Photo(
                    path=path,
                    captured_at=meta.captured_at,
                    modified_at=meta.modified_at
                    or datetime.fromtimestamp(stat.st_mtime),
                    camera=meta.camera,
                    lens=meta.lens,
                    focal_length=meta.focal_length,
                    width=width,
                    height=height,
                    size=stat.st_size,
                    thumbnail_key=key,
                )
            )
        return ScanResult(
            photos=photos, skipped=skipped, total_files=len(all_files)
        )


class FilesystemFolderCounter:
    def count(self, root: Path) -> tuple[int, int]:
        root = root.resolve()
        total = 0
        images = 0
        for path in _iter_files(root):
            total += 1
            if path.suffix.lower() in SUPPORTED_EXTENSIONS:
                images += 1
        return images, total


def _iter_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIR_NAMES or part.startswith(".") for part in path.parts):
            continue
        yield path


def _iter_images(root: Path):
    for path in _iter_files(root):
        if path.suffix.lower() in SUPPORTED_EXTENSIONS:
            yield path


def _parse_datetime(value) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    formats = (
        "%Y:%m:%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y:%m:%d %H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y:%m:%d %H:%M:%S.%f%z",
    )
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=None)
        except ValueError:
            continue
    return None


def _as_float(value) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None
