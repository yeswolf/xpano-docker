from __future__ import annotations

import logging
import shutil
from pathlib import Path

from pano_xpano.application.ports import ReplacementError
from pano_xpano.domain.models import FileMove, ReplacementOperation, ReplacementPlan

logger = logging.getLogger(__name__)


class SafeReplacer:
    def execute(self, operation: ReplacementOperation, plan: ReplacementPlan) -> None:
        if plan.target == plan.panorama_source:
            raise ReplacementError("panorama target equals the stitch source")
        if plan.target.exists():
            raise ReplacementError(f"target already exists: {plan.target}")
        moved: list[FileMove] = []
        try:
            plan.trash_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(plan.panorama_source, plan.temp)
            if not plan.temp.is_file() or plan.temp.stat().st_size == 0:
                raise ReplacementError("failed to copy the stitched panorama")
            for move in plan.moves:
                if not move.source.is_file():
                    raise ReplacementError(f"source disappeared: {move.source}")
                if move.trash.exists():
                    raise ReplacementError(f"trash path already exists: {move.trash}")
                move.trash.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(move.source), str(move.trash))
                moved.append(move)
            plan.target.parent.mkdir(parents=True, exist_ok=True)
            plan.temp.replace(plan.target)
        except Exception as error:
            logger.exception("replacement failed, rolling back")
            self._rollback(moved, plan)
            if isinstance(error, ReplacementError):
                raise
            raise ReplacementError(str(error)) from error

    def undo(self, operation: ReplacementOperation) -> None:
        if operation.panorama_path is None:
            raise ReplacementError("operation has no panorama path")
        target = operation.panorama_path
        if not target.is_file():
            raise ReplacementError(f"panorama is missing: {target}")
        pairs = list(zip(operation.source_paths, operation.trash_paths))
        for source, trash in pairs:
            if not trash.is_file():
                raise ReplacementError(f"trash copy is missing: {trash}")
            if source.exists():
                raise ReplacementError(f"original path is occupied: {source}")

        restored: list[tuple[Path, Path]] = []
        try:
            for source, trash in pairs:
                source.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(trash), str(source))
                restored.append((source, trash))
        except Exception as error:
            logger.exception("undo failed while restoring, returning files to trash")
            for source, trash in reversed(restored):
                try:
                    if source.exists() and not trash.exists():
                        trash.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(source), str(trash))
                except OSError:
                    logger.exception("could not return %s to trash", source)
            raise ReplacementError(f"could not restore originals: {error}") from error

        panorama_trash = _unique_path(
            operation.trash_dir / f"panorama_{target.name}"
        )
        try:
            panorama_trash.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(target), str(panorama_trash))
        except OSError as error:
            raise ReplacementError(
                f"originals restored, but the panorama could not be moved: {error}"
            ) from error

    def _rollback(self, moved: list[FileMove], plan: ReplacementPlan) -> None:
        for move in reversed(moved):
            try:
                if move.trash.exists() and not move.source.exists():
                    move.source.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(move.trash), str(move.source))
            except OSError:
                logger.exception("rollback failed for %s", move.source)
        try:
            if plan.temp.exists():
                plan.temp.unlink()
        except OSError:
            logger.exception("could not remove temporary panorama %s", plan.temp)
        try:
            if plan.target.exists() and plan.temp.exists():
                plan.target.unlink()
        except OSError:
            logger.exception("could not remove partial target %s", plan.target)


def _unique_path(path: Path) -> Path:
    candidate = path
    index = 2
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        index += 1
    return candidate
