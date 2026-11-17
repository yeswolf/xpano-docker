# Design

## Overview

The service is a single Docker container with three layers:

1. **Domain**: `Photo`, `PanoramaGroup`, `StitchResult`, `ReplacementOperation`,
   and the policies that decide group membership and replacement order.
2. **Application**: use cases `ScanLibrary`, `DetectGroups`, `ListGroups`,
   `StitchGroup`, `ReplaceGroup`, `UndoReplacement`.
3. **Adapters**: filesystem library, ExifTool metadata reader, Pillow thumbnail
   writer, OpenCV group detector, Xpano CLI stitcher, SQLite repositories, and a
   FastAPI web interface.

Dependencies point inward. The domain has no FastAPI, OpenCV, SQLite, or Xpano
imports.

## Detection

The detector has two stages so that a large library does not require an
all-pairs comparison:

1. **Candidate sequences** from metadata. Images are sorted by capture time.
   Consecutive images are candidates when they are within 20 seconds, use the
   same camera model, have a similar focal length, and have a similar aspect
   ratio. Images without EXIF use a time window of 5 seconds and are allowed to
   match only by geometry.
2. **Geometric confirmation**. For each candidate pair, downscale both images to
   at most 900 px on the long side, detect SIFT features, apply a ratio test,
   estimate a homography with RANSAC, and require at least 18 inliers and a
   minimum translation. Build a graph of confirmed pairs and take connected
   components with at least two images.
3. **Panorama versus burst**. Sum the translation vectors along a component. A
   component is a panorama only when cumulative drift exceeds 8% of the image
   width or height; a burst that wobbles around zero is rejected. The confidence
   combines the fraction of confirmed edges and the cumulative drift.

The detector is a pure Python component behind a `GroupDetector` port. Settings
(time window, SIFT thresholds, drift threshold) are configuration values, not
hard-coded constants.

## Watched folders

The library root is a mount, not a scan target. The operator adds one or more
watched folders, each a path relative to the library root (`2024`,
`2024/05`, or `.` for the whole mount). The server resolves every path and
rejects anything outside the root, including `..` segments and symlinks that
escape the root. Adding a folder never touches files.

SQLite stores `folders(id, path, created_at, last_scan_at, last_scan_status)`.
A scan receives a folder ID, indexes only that subtree, and replaces only that
folder's rows. Groups carry a folder ID, so the interface can filter by folder
and two folders can be tested independently. Removing a folder removes its
indexed photos and candidate groups but leaves the files and the operation
audit untouched.

The folder browser endpoint lists subdirectories under the library root; the
interface also accepts a manually typed relative or absolute path.

## Persistence

SQLite stores:

- `folders`: ID, relative path, created time, last scan time and status.
- `photos`: path, folder ID, capture time, camera, lens, width, height, size,
  orientation, thumbnail key.
- `groups`: stable ID, folder ID, detector version, confidence, status, member
  JSON, first/last timestamp, created/updated.
- `stitches`: group ID, status, output path, width, height, error, timestamps.
- `operations`: group ID, status, source paths, trash paths, panorama path,
  created/updated, error.
- `jobs`: kind, status, progress, message, result, context JSON (folder or group
  ID), timestamps.

A group ID is a SHA-256 of the sorted member paths and the detector version, so a
rescan is idempotent. Folder-scoped scans delete only candidate groups whose
folder ID matches the scanned folder.

## Stitching

The `Stitcher` port receives a list of absolute paths and an output path. The
Xpano adapter runs:

```text
Xpano <path1> <path2> ... --output=<output.jpg>
```

It runs with no display, a 10-minute timeout, and a temporary work directory.
Only one stitch is allowed at a time; the job runner queues requests. The output
is copied to a persistent work directory before the temporary directory is
removed.

If Xpano needs a display in the tested image, the adapter wraps it with
`xvfb-run -a`; the CLI path is tested first without Xvfb.

## Replacement transaction

A replacement is an explicit two-phase operation:

1. **Prepare**: verify the group has a successful stitch, verify every source
   path is inside the configured library, choose a final name, copy the panorama
   to `<target>/.pano-xpano-<operation>.tmp`, and create the trash directory.
2. **Commit**: move every source photo and matching sidecar (`.xmp`, `.json`,
   `.yml`, `.aae`) to the trash preserving relative paths, then rename the
   temporary panorama to its final path. Write the operation manifest after each
   step.

On any failure, the service moves trashed files back in reverse order, removes
the temporary and published panorama, and marks the operation failed. The
operation row is the source of truth for undo.

The default target directory is the directory of the first member. The default
name is `PANO_<capture timestamp>_<group id prefix>.<ext>`. A suffix `_2`, `_3`
is added if the name exists.

Trash lives under `/data/trash/<operation id>/` by default. It is outside the
library, so PhotoPrism does not index it. Restoring moves files back to their
recorded paths.

## Web interface

FastAPI serves JSON under `/api` and a small server-rendered interface:

- `/`: watched-folder manager, add/browse controls, folder cards with scan
  status and counts, and group cards for the selected folder.
- `/groups/{id}`: member table, stitch preview, stitch and replace buttons,
  replacement history.
- `/operations`: replacement audit and undo.
- `/settings`: library root, time window, drift threshold, output extension.

The selected folder is kept in the URL query string and in local storage, so a
reload or navigation restores the same filter. Folder cards show the last scan
time, outcome, photo count, and group count.

The group page serves every indexed member file from
`/api/photos/{thumbnail_key}/original`; the key resolves through the photos
table, so only indexed paths are served. If the source file was moved by a
completed replacement, the endpoint falls back to the matching trash copy from
the operation record, so originals remain reviewable after replacement.
Activation of a member thumbnail, the panorama preview image, or the full-size
panorama action opens a dialog that renders the image at its natural size
inside a scrollable stage; a failed load shows an explicit unavailable message.
The stitched panorama uses the existing `/api/groups/{id}/preview` file, which
is already full resolution. When the latest stitch failed, the panorama panel
shows the stitcher error instead of hiding the panel. Static asset URLs carry a
version derived from the asset file timestamps, so a rebuilt container is not
masked by a stale browser cache.

Actions are asynchronous. The browser polls `/api/jobs/{id}` and refreshes the
affected view when a job reaches a terminal state. Every page also asks
`/api/jobs?active=true` on load and resumes the newest active job, so a scan or
stitch operation survives a reload or a section change. Replacement is accepted
only with `confirm=true` and a typed confirmation in the UI.

The service binds to a configured host and port (default `0.0.0.0:3040` inside
the container, published to a chosen LAN address). It is a single-user tool; no
authentication is implemented in the first version, and the README states that
it must not be exposed to the internet.

## Container

`ubuntu:24.04` base:

- Xpano from the `ppa:krupkat/code` package (or the pre-release AppImage if the
  PPA build is unavailable), plus `libgl1`, `libgomp1`, and Xvfb.
- ExifTool and LibRaw tools.
- Python 3.12 virtual environment with FastAPI, Uvicorn, Pillow,
  `opencv-python-headless`, NumPy, and Jinja2.
- Mounts: `/library` (photo root, read-write) and `/data` (SQLite, thumbnails,
  stitch work, trash).
- Health endpoint `/healthz`.

The image is built on the host; the application is not run on the host.

## Testing

- Unit tests for candidate sequencing, drift classification, group IDs, filename
  collision handling, and replacement planning.
- Adapter tests with temporary directories for scanning and replacement.
- API integration tests with FastAPI `TestClient` and a fake stitcher.
- A container smoke test that runs `Xpano --version` and stitches a small
  synthetic panorama pair.
- No test deletes files outside a pytest temporary directory.

## Out of scope

- RAW decoding beyond what Xpano/OpenCV supports; RAW files are excluded from
  stitching in the first version.
- Automatic replacement without review.
- Multi-user accounts and internet-facing authentication.
- Updating the PhotoPrism index; the operator runs `photoprism index --cleanup`
  after a replacement.
- HDR blending and focus stacking.
