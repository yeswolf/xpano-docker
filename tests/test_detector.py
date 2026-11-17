from __future__ import annotations

from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from pano_xpano.adapters.detector import OpenCvGroupDetector
from pano_xpano.config import DetectionSettings
from pano_xpano.domain.models import Photo


def _texture() -> np.ndarray:
    rng = np.random.default_rng(7)
    base = rng.integers(0, 256, (700, 1800, 3), dtype=np.uint8)
    base = cv2.GaussianBlur(base, (7, 7), 0)
    for index in range(80):
        x = int(rng.integers(0, 1750))
        y = int(rng.integers(0, 650))
        color = tuple(int(value) for value in rng.integers(0, 256, 3))
        cv2.rectangle(base, (x, y), (x + 40, y + 30), color, -1)
    return base


def test_detects_overlapping_pair(tmp_path: Path) -> None:
    base = _texture()
    left_path = tmp_path / "left.png"
    right_path = tmp_path / "right.png"
    Image.fromarray(base[:, :1200]).save(left_path)
    Image.fromarray(base[:, 600:1800]).save(right_path)

    moment = datetime(2024, 5, 1, 12, 0, 0)
    photos = [
        Photo(
            path=left_path,
            captured_at=moment,
            modified_at=moment,
            camera="Test",
            lens="35mm",
            focal_length=35.0,
            width=1200,
            height=700,
            size=left_path.stat().st_size,
            thumbnail_key="0" * 40,
        ),
        Photo(
            path=right_path,
            captured_at=moment,
            modified_at=moment,
            camera="Test",
            lens="35mm",
            focal_length=35.0,
            width=1200,
            height=700,
            size=right_path.stat().st_size,
            thumbnail_key="1" * 40,
        ),
    ]

    groups = OpenCvGroupDetector().detect(
        photos, DetectionSettings(), "test"
    )

    assert len(groups) == 1
    assert len(groups[0].members) == 2
    assert groups[0].confidence > 0.5
