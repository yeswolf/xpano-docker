from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from pano_xpano.adapters.detector import OpenCvGroupDetector
from pano_xpano.adapters.replacement import SafeReplacer
from pano_xpano.adapters.scanner import (
    ExifToolReader,
    FilesystemFolderCounter,
    FilesystemScanner,
    Thumbnailer,
)
from pano_xpano.adapters.stitcher import XpanoStitcher
from pano_xpano.adapters.store import SqliteStore
from pano_xpano.application.jobs import JobRunner
from pano_xpano.application.use_cases import (
    AddFolder,
    RemoveFolder,
    ReplaceGroup,
    ScanLibrary,
    StitchGroup,
    UndoReplacement,
)
from pano_xpano.config import Settings, SettingsManager
from pano_xpano.domain.policies import folder_absolute

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AppContainer:
    settings_manager: SettingsManager
    store: SqliteStore
    scan: ScanLibrary
    stitch: StitchGroup
    replace: ReplaceGroup
    undo: UndoReplacement
    add_folder: AddFolder
    remove_folder: RemoveFolder
    runner: JobRunner

    @property
    def settings(self) -> Settings:
        return self.settings_manager.current


def build_container(settings: Settings) -> AppContainer:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.thumbs_dir.mkdir(parents=True, exist_ok=True)
    settings.stitch_dir.mkdir(parents=True, exist_ok=True)
    settings.trash_dir.mkdir(parents=True, exist_ok=True)
    manager = SettingsManager(settings)
    store = SqliteStore(settings.db_path)
    store.fail_unfinished_jobs("interrupted by service restart")
    counter = FilesystemFolderCounter()
    for folder in store.list_folders():
        if folder.image_count or folder.file_count:
            continue
        try:
            images, files = counter.count(
                folder_absolute(settings.library_root, folder.path)
            )
            store.update_folder_counts(folder.id, images, files)
        except Exception:
            logger.exception("could not count folder %s", folder.path)
    scanner = FilesystemScanner(
        metadata_reader=ExifToolReader(),
        thumbnailer=Thumbnailer(settings.thumbs_dir, settings.thumb_size),
    )
    detector = OpenCvGroupDetector()
    stitcher = XpanoStitcher(settings.xpano_bin)
    replacer = SafeReplacer()
    runner = JobRunner(store, max_workers=1)
    clock = datetime.now
    return AppContainer(
        settings_manager=manager,
        store=store,
        scan=ScanLibrary(
            scanner, detector, store, lambda: manager.current, clock=clock
        ),
        stitch=StitchGroup(store, stitcher, lambda: manager.current, clock=clock),
        replace=ReplaceGroup(store, replacer, lambda: manager.current, clock=clock),
        undo=UndoReplacement(store, replacer, clock=clock),
        add_folder=AddFolder(
            store,
            lambda: manager.current,
            FilesystemFolderCounter(),
            clock=clock,
        ),
        remove_folder=RemoveFolder(store),
        runner=runner,
    )
