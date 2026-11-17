from __future__ import annotations

import os
from pathlib import Path

from pano_xpano.domain.policies import folder_absolute, normalize_folder_path

SKIP_NAMES = {
    "@eaDir",
    "#recycle",
    "System Volume Information",
    "__MACOSX",
    "$RECYCLE.BIN",
}


def browse_folders(library_root: Path, raw_path: str) -> dict:
    relative = normalize_folder_path(library_root, raw_path)
    current = folder_absolute(library_root, relative)
    if not current.is_dir():
        raise ValueError(f"folder does not exist: {relative}")

    entries: list[dict] = []
    try:
        with os.scandir(current) as scan:
            for entry in scan:
                if entry.name.startswith(".") or entry.name in SKIP_NAMES:
                    continue
                try:
                    if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                        continue
                except OSError:
                    continue
                child_path = (
                    entry.name
                    if relative == "."
                    else f"{relative}/{entry.name}"
                )
                entries.append({"name": entry.name, "path": child_path})
    except OSError as error:
        raise ValueError(f"cannot read folder: {error}") from error

    entries.sort(key=lambda item: item["name"].casefold())
    if relative == ".":
        parent = None
    else:
        parent = Path(relative).parent.as_posix()
        if parent == ".":
            parent = "."
    return {"path": relative, "parent": parent, "entries": entries}
