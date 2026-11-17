from __future__ import annotations

import hashlib
from datetime import datetime
from pathlib import Path

from pano_xpano.config import DetectionSettings
from pano_xpano.domain.models import (
    DetectedGroup,
    FileMove,
    GroupStatus,
    PanoramaGroup,
    PairMatch,
    Photo,
    ReplacementPlan,
)

SIDECAR_SUFFIXES = (".xmp", ".json", ".yml", ".yaml", ".aae", ".dop")


def candidate_pairs(
    photos: list[Photo], settings: DetectionSettings
) -> list[tuple[Photo, Photo]]:
    ordered = sorted(photos, key=_order_key)
    pairs: list[tuple[Photo, Photo]] = []
    for left, right in zip(ordered, ordered[1:]):
        if left.path.parent != right.path.parent:
            continue
        if not _same_camera(left, right):
            continue
        if not _same_focal(left, right):
            continue
        if not _similar_aspect(left, right):
            continue
        if not _within_time_window(left, right, settings):
            continue
        pairs.append((left, right))
    return pairs


def _order_key(photo: Photo) -> tuple[datetime, str]:
    return (photo.captured_at or photo.modified_at, str(photo.path))


def _same_camera(left: Photo, right: Photo) -> bool:
    if left.camera and right.camera:
        return left.camera.casefold() == right.camera.casefold()
    return True


def _same_focal(left: Photo, right: Photo) -> bool:
    if not left.focal_length or not right.focal_length:
        return True
    larger = max(left.focal_length, right.focal_length)
    return abs(left.focal_length - right.focal_length) / larger <= 0.25


def _similar_aspect(left: Photo, right: Photo) -> bool:
    if left.aspect <= 0 or right.aspect <= 0:
        return True
    return abs(left.aspect - right.aspect) / max(left.aspect, right.aspect) <= 0.2


def _within_time_window(
    left: Photo, right: Photo, settings: DetectionSettings
) -> bool:
    if left.captured_at is not None and right.captured_at is not None:
        gap = abs((right.captured_at - left.captured_at).total_seconds())
        return gap <= settings.time_window_s
    gap = abs((right.modified_at - left.modified_at).total_seconds())
    return gap <= settings.no_exif_window_s


def build_groups(
    photos: list[Photo],
    matches: list[PairMatch],
    settings: DetectionSettings,
    detector_version: str,
) -> list[DetectedGroup]:
    if not matches:
        return []

    parent = {str(photo.path): str(photo.path) for photo in photos}

    def find(value: str) -> str:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: str, right: str) -> None:
        a, b = find(left), find(right)
        if a != b:
            parent[b] = a

    usable: list[PairMatch] = []
    for match in matches:
        translation = max(abs(match.dx_ratio), abs(match.dy_ratio))
        if match.inliers < settings.min_inliers:
            continue
        if translation < settings.min_translation_ratio:
            continue
        usable.append(match)
        union(str(match.left.path), str(match.right.path))

    components: dict[str, list[PairMatch]] = {}
    for match in usable:
        components.setdefault(find(str(match.left.path)), []).append(match)

    by_path = {str(photo.path): photo for photo in photos}
    groups: list[DetectedGroup] = []
    for component_matches in components.values():
        paths = {
            str(match.left.path) for match in component_matches
        } | {str(match.right.path) for match in component_matches}
        if len(paths) < 2:
            continue
        members = tuple(sorted((by_path[path] for path in paths), key=_order_key))
        drift = _cumulative_drift(component_matches)
        if drift < settings.drift_ratio:
            continue
        confidence = min(
            0.99,
            0.35
            + 0.55 * min(1.0, drift / max(settings.drift_ratio * 3, 0.001))
            + 0.10 * min(1.0, len(component_matches) / max(1, len(members) - 1)),
        )
        groups.append(DetectedGroup(members=members, confidence=round(confidence, 3)))
    return groups


def _cumulative_drift(matches: list[PairMatch]) -> float:
    dx = sum(match.dx_ratio for match in matches)
    dy = sum(match.dy_ratio for match in matches)
    return max(abs(dx), abs(dy))


def group_id(members: tuple[Photo, ...], detector_version: str) -> str:
    payload = "|".join(sorted(str(photo.path) for photo in members))
    digest = hashlib.sha256(f"{detector_version}|{payload}".encode("utf-8")).hexdigest()
    return digest[:16]


def make_group(
    detected: DetectedGroup,
    detector_version: str,
    folder_id: str,
    now: datetime,
) -> PanoramaGroup:
    return PanoramaGroup(
        id=group_id(detected.members, detector_version),
        folder_id=folder_id,
        detector_version=detector_version,
        members=detected.members,
        confidence=detected.confidence,
        status=GroupStatus.CANDIDATE,
        created_at=now,
        updated_at=now,
    )


def unique_output_path(directory: Path, stem: str, ext: str) -> Path:
    if not ext.startswith("."):
        ext = f".{ext}"
    candidate = directory / f"{stem}{ext}"
    index = 2
    while candidate.exists():
        candidate = directory / f"{stem}_{index}{ext}"
        index += 1
    return candidate


def panorama_stem(first: Photo, group_id_value: str) -> str:
    timestamp = first.captured_at or datetime.now()
    return f"PANO_{timestamp:%Y%m%d_%H%M%S}_{group_id_value[:8]}"


def plan_replacement(
    group: PanoramaGroup,
    panorama_path: Path,
    library_root: Path,
    trash_root: Path,
    operation_id: str,
    output_ext: str,
) -> ReplacementPlan:
    if not panorama_path.is_file():
        raise ValueError("stitched panorama does not exist")
    library_root = library_root.resolve()
    for photo in group.members:
        if not _inside(photo.path.resolve(), library_root):
            raise ValueError(f"photo is outside the library: {photo.path}")

    first = group.members[0]
    target_dir = first.path.parent
    target = unique_output_path(
        target_dir, panorama_stem(first, group.id), output_ext
    )
    trash_dir = trash_root / operation_id

    moves: list[FileMove] = []
    seen: set[Path] = set()
    for photo in group.members:
        for source in _sources_for(photo.path):
            resolved = source.resolve()
            if resolved in seen:
                continue
            if not _inside(resolved, library_root):
                raise ValueError(f"source is outside the library: {source}")
            relative = resolved.relative_to(library_root)
            moves.append(FileMove(source=resolved, trash=trash_dir / relative))
            seen.add(resolved)

    return ReplacementPlan(
        operation_id=operation_id,
        group_id=group.id,
        panorama_source=panorama_path,
        target=target,
        temp=target_dir / f".pano-xpano-{operation_id}.tmp",
        trash_dir=trash_dir,
        moves=tuple(moves),
    )


def _sources_for(photo_path: Path) -> list[Path]:
    sources = [photo_path]
    for suffix in SIDECAR_SUFFIXES:
        sidecar = photo_path.with_suffix(suffix)
        if sidecar.exists():
            sources.append(sidecar)
    return sources


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def normalize_folder_path(library_root: Path, raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        raise ValueError("folder path is empty")
    candidate = Path(text)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        if any(part == ".." for part in candidate.parts):
            raise ValueError("folder path must not contain '..'")
        resolved = (library_root / candidate).resolve()
    root = library_root.resolve()
    if not _inside(resolved, root):
        raise ValueError("folder path is outside the library root")
    relative = resolved.relative_to(root)
    return "." if str(relative) == "." else relative.as_posix()


def folder_absolute(library_root: Path, relative: str) -> Path:
    if relative in ("", "."):
        return library_root.resolve()
    return (library_root / relative).resolve()


def folder_id_for(relative: str) -> str:
    return hashlib.sha256(f"folder|{relative}".encode("utf-8")).hexdigest()[:16]
