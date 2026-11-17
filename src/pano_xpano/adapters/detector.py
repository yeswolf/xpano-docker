from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from pano_xpano.application.ports import Progress
from pano_xpano.config import DetectionSettings
from pano_xpano.domain.models import DetectedGroup, PairMatch, Photo
from pano_xpano.domain.policies import build_groups, candidate_pairs

logger = logging.getLogger(__name__)

MAX_SIDE = 900


class OpenCvGroupDetector:
    def __init__(self, max_side: int = MAX_SIDE) -> None:
        self._max_side = max_side
        cv2.setNumThreads(1)

    def detect(
        self,
        photos: list[Photo],
        settings: DetectionSettings,
        detector_version: str,
        progress: Progress | None = None,
    ) -> list[DetectedGroup]:
        pairs = candidate_pairs(photos, settings)
        if len(pairs) > settings.max_pairs:
            logger.warning(
                "candidate pairs %s exceed max_pairs %s; truncating",
                len(pairs),
                settings.max_pairs,
            )
            pairs = pairs[: settings.max_pairs]
        total = len(pairs)
        if not total:
            return []

        sift = _make_detector()
        matches: list[PairMatch] = []
        for index, (left, right) in enumerate(pairs, start=1):
            match = _match_pair(left, right, sift, self._max_side)
            if match is not None and match.inliers >= settings.min_inliers:
                matches.append(match)
            if progress and (index % 20 == 0 or index == total):
                progress(
                    index / total,
                    f"matching {index}/{total}, {len(matches)} overlapping pairs",
                )
        return build_groups(photos, matches, settings, detector_version)


def _make_detector():
    try:
        return cv2.SIFT_create(nfeatures=2200, contrastThreshold=0.03, edgeThreshold=10)
    except (AttributeError, cv2.error):
        logger.warning("SIFT unavailable, falling back to ORB")
        return cv2.ORB_create(nfeatures=5000)


def _match_pair(
    left: Photo,
    right: Photo,
    detector,
    max_side: int,
) -> PairMatch | None:
    image_left = _load_gray(left.path, max_side)
    image_right = _load_gray(right.path, max_side)
    if image_left is None or image_right is None:
        return None
    keypoints_left, descriptors_left = detector.detectAndCompute(image_left, None)
    keypoints_right, descriptors_right = detector.detectAndCompute(image_right, None)
    if (
        descriptors_left is None
        or descriptors_right is None
        or len(keypoints_left) < 12
        or len(keypoints_right) < 12
    ):
        return None

    matcher = _make_matcher(descriptors_left, descriptors_right)
    try:
        candidates = matcher.knnMatch(descriptors_left, descriptors_right, k=2)
    except cv2.error:
        return None
    good = [
        first
        for pair in candidates
        if len(pair) == 2
        for first, second in [pair]
        if first.distance < 0.75 * second.distance
    ]
    if len(good) < 12:
        return None

    source = np.float32(
        [keypoints_left[match.queryIdx].pt for match in good]
    ).reshape(-1, 1, 2)
    target = np.float32(
        [keypoints_right[match.trainIdx].pt for match in good]
    ).reshape(-1, 1, 2)
    matrix, mask = cv2.findHomography(source, target, cv2.RANSAC, 5.0)
    if matrix is None or mask is None:
        return None
    inliers = int(mask.sum())
    if inliers < 8:
        return None

    height, width = image_left.shape[:2]
    center = np.float32([[[width / 2, height / 2]]])
    transformed = cv2.perspectiveTransform(center, matrix)[0][0]
    dx_ratio = float((transformed[0] - width / 2) / width)
    dy_ratio = float((transformed[1] - height / 2) / height)
    if abs(dx_ratio) > 2.0 or abs(dy_ratio) > 2.0:
        return None
    return PairMatch(
        left=left,
        right=right,
        inliers=inliers,
        dx_ratio=dx_ratio,
        dy_ratio=dy_ratio,
    )


def _make_matcher(descriptors_left: np.ndarray, descriptors_right: np.ndarray):
    if descriptors_left.dtype == np.uint8:
        return cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
    return cv2.BFMatcher(cv2.NORM_L2, crossCheck=False)


def _load_gray(path: Path, max_side: int) -> np.ndarray | None:
    try:
        buffer = np.fromfile(str(path), dtype=np.uint8)
    except OSError:
        return None
    if buffer.size == 0:
        return None
    image = cv2.imdecode(buffer, cv2.IMREAD_GRAYSCALE)
    if image is None:
        return None
    height, width = image.shape[:2]
    if max(height, width) <= max_side:
        return image
    scale = max_side / max(height, width)
    return cv2.resize(
        image,
        (max(1, int(width * scale)), max(1, int(height * scale))),
        interpolation=cv2.INTER_AREA,
    )
