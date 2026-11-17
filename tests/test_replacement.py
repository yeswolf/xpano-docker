from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from pano_xpano.adapters.replacement import SafeReplacer
from pano_xpano.application.ports import ReplacementError
from pano_xpano.domain.models import (
    DetectedGroup,
    OperationStatus,
    ReplacementOperation,
)
from pano_xpano.domain.policies import make_group, plan_replacement

from conftest import make_panorama, make_photo


def _setup(tmp_path: Path):
    library = tmp_path / "library"
    first = make_photo(library / "2024" / "a.jpg")
    second = make_photo(library / "2024" / "b.jpg")
    first.path.with_suffix(".xmp").write_text("sidecar", encoding="utf-8")
    panorama = tmp_path / "stitch" / "pano.jpg"
    make_panorama(panorama)
    group = make_group(
        DetectedGroup(members=(first, second), confidence=0.9),
        "test",
        "folder",
        datetime(2024, 5, 1),
    )
    plan = plan_replacement(
        group, panorama, library, tmp_path / "trash", "op1", ".jpg"
    )
    operation = ReplacementOperation(
        id=plan.operation_id,
        group_id=group.id,
        status=OperationStatus.RUNNING,
        source_paths=tuple(move.source for move in plan.moves),
        trash_paths=tuple(move.trash for move in plan.moves),
        trash_dir=plan.trash_dir,
        panorama_path=plan.target,
        error=None,
        created_at=datetime(2024, 5, 1),
        updated_at=datetime(2024, 5, 1),
    )
    return library, group, plan, operation


def test_execute_moves_sources_and_publishes_panorama(tmp_path: Path) -> None:
    library, group, plan, operation = _setup(tmp_path)
    SafeReplacer().execute(operation, plan)

    assert plan.target.is_file()
    assert not (library / "2024" / "a.jpg").exists()
    assert not (library / "2024" / "b.jpg").exists()
    assert not (library / "2024" / "a.xmp").exists()
    assert all(move.trash.is_file() for move in plan.moves)
    assert plan.temp.exists() is False


def test_undo_restores_sources_and_moves_panorama_out(tmp_path: Path) -> None:
    library, group, plan, operation = _setup(tmp_path)
    replacer = SafeReplacer()
    replacer.execute(operation, plan)
    replacer.undo(operation)

    assert (library / "2024" / "a.jpg").is_file()
    assert (library / "2024" / "b.jpg").is_file()
    assert (library / "2024" / "a.xmp").is_file()
    assert not plan.target.exists()
    assert list(plan.trash_dir.glob("panorama_*"))


def test_failed_move_rolls_back_earlier_sources(tmp_path: Path) -> None:
    library, group, plan, operation = _setup(tmp_path)
    missing = library / "2024" / "b.jpg"
    missing.unlink()
    with pytest.raises(ReplacementError):
        SafeReplacer().execute(operation, plan)

    assert (library / "2024" / "a.jpg").is_file()
    assert not plan.target.exists()
    assert not plan.temp.exists()
