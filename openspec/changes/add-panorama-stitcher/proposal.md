# Proposal

## Why

The PhotoPrism library contains panorama sequences that are stored as separate
photos. PhotoPrism can group related files but cannot detect panorama sequences
or stitch them, and Xpano can do both only as a desktop application. The user
needs a self-hosted web tool that finds candidate panorama groups, stitches a
chosen group, and replaces the source photos with the resulting panorama without
losing the originals.

## What Changes

- Add a Docker-packaged web service built around the Xpano stitching engine.
- Manage a list of watched folders inside the mounted library; folders are added
  manually, browsed from the library root, and removed without touching files.
- Scan only the selected folder, not the whole library by default, and keep each
  folder's photos and groups separate so parts of the library can be tested
  incrementally.
- Persist scan and action progress in SQLite, resume the active job after a page
  reload or navigation, and show the last scan status and time per folder.
- Show detected groups with thumbnails and member details in a web interface,
  filtered by the selected folder.
- Stitch a selected group on demand and show the resulting panorama.
- Replace the group's source files with the panorama, moving originals and
  related sidecars into a recoverable trash directory behind an explicit
  confirmation.
- Keep an operation log and support undo of a replacement.
- Keep all existing photos untouched until the user confirms a replacement.

## Capabilities

### New Capabilities

- `panorama-groups`: discover, persist, and present candidate panorama groups
  from a photo library.
- `panorama-stitching`: turn a selected group into a panorama image and expose
  the result for review.
- `library-replacement`: replace a source group with its panorama safely, with
  trash, audit records, and undo.

### Modified Capabilities

None. This is a new project with no existing OpenSpec capabilities.

## Impact

- New project directory with a Python web application, SQLite state, and a
  Docker image.
- New runtime dependencies: Xpano, ExifTool, OpenCV, Pillow, FastAPI.
- The container mounts the photo library read-write for replacement; all
  destructive operations are explicit and recoverable through the trash.
- PhotoPrism is not modified by the tool; after a replacement the operator
  reindexes PhotoPrism with its cleanup option.
