from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DetectionSettings:
    time_window_s: int = 20
    no_exif_window_s: int = 5
    min_inliers: int = 18
    drift_ratio: float = 0.08
    min_translation_ratio: float = 0.015
    max_pairs: int = 12000

    def as_dict(self) -> dict[str, float | int]:
        return {
            "time_window_s": self.time_window_s,
            "no_exif_window_s": self.no_exif_window_s,
            "min_inliers": self.min_inliers,
            "drift_ratio": self.drift_ratio,
            "min_translation_ratio": self.min_translation_ratio,
            "max_pairs": self.max_pairs,
        }


@dataclass(frozen=True, slots=True)
class Settings:
    library_root: Path
    data_dir: Path
    xpano_bin: str
    host: str
    port: int
    detector_version: str
    output_ext: str
    stitch_timeout_s: int
    use_xvfb: bool
    thumb_size: int
    detection: DetectionSettings

    @property
    def db_path(self) -> Path:
        return self.data_dir / "state" / "pano-xpano.sqlite3"

    @property
    def thumbs_dir(self) -> Path:
        return self.data_dir / "thumbs"

    @property
    def stitch_dir(self) -> Path:
        return self.data_dir / "stitch"

    @property
    def trash_dir(self) -> Path:
        return self.data_dir / "trash"

    @property
    def settings_path(self) -> Path:
        return self.data_dir / "settings.json"

    def with_detection(self, detection: DetectionSettings) -> Settings:
        return replace(self, detection=detection)

    @classmethod
    def from_env(cls) -> Settings:
        data_dir = Path(os.environ.get("PANORAMA_DATA_DIR", "/data")).resolve()
        library_root = Path(
            os.environ.get("PANORAMA_LIBRARY_ROOT", "/library")
        ).resolve()
        detection = _load_detection(data_dir)
        return cls(
            library_root=library_root,
            data_dir=data_dir,
            xpano_bin=os.environ.get("PANORAMA_XPANO_BIN", "Xpano"),
            host=os.environ.get("PANORAMA_HOST", "0.0.0.0"),
            port=int(os.environ.get("PANORAMA_PORT", "3040")),
            detector_version=os.environ.get(
                "PANORAMA_DETECTOR_VERSION", "sift-v1"
            ),
            output_ext=os.environ.get("PANORAMA_OUTPUT_EXT", ".jpg"),
            stitch_timeout_s=int(
                os.environ.get("PANORAMA_STITCH_TIMEOUT", "600")
            ),
            use_xvfb=os.environ.get("PANORAMA_USE_XVFB", "0") == "1",
            thumb_size=int(os.environ.get("PANORAMA_THUMB_SIZE", "360")),
            detection=detection,
        )


def _load_detection(data_dir: Path) -> DetectionSettings:
    path = data_dir / "settings.json"
    defaults = DetectionSettings()
    if not path.is_file():
        return defaults
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return defaults
    values: dict[str, float | int] = {}
    for key in defaults.as_dict():
        if key in raw:
            values[key] = raw[key]
    try:
        return DetectionSettings(**values)  # type: ignore[arg-type]
    except TypeError:
        return defaults


class SettingsManager:
    """Reads and persists the editable detection settings."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def current(self) -> Settings:
        return self._settings

    def update_detection(self, values: dict[str, float | int]) -> Settings:
        allowed = self._settings.detection.as_dict()
        clean: dict[str, float | int] = {}
        for key, value in values.items():
            if key not in allowed:
                continue
            if key in {"time_window_s", "no_exif_window_s", "min_inliers", "max_pairs"}:
                clean[key] = max(1, int(value))
            else:
                clean[key] = max(0.0, float(value))
        detection = replace(self._settings.detection, **clean)
        self._settings = self._settings.with_detection(detection)
        self._settings.data_dir.mkdir(parents=True, exist_ok=True)
        self._settings.settings_path.write_text(
            json.dumps(detection.as_dict(), indent=2), encoding="utf-8"
        )
        return self._settings
