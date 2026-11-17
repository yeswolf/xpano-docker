# Tasks

## 1. Project scaffold

- [x] 1.1 Create the Python package layout, `pyproject.toml`, and test setup.
- [x] 1.2 Add configuration, logging, and the SQLite schema/migrations.
- [x] 1.3 Add `.gitignore`, README, and the Docker/Compose files.

## 2. Domain and application

- [x] 2.1 Define domain entities and value objects for photos, groups, stitches,
  and replacement operations.
- [x] 2.2 Define the ports for library scanning, metadata, thumbnails, group
  detection, stitching, persistence, and file replacement.
- [x] 2.3 Implement the group detector and replacement planner as pure
  application/domain services.
- [x] 2.4 Add unit tests for detection policies, group IDs, naming, and
  replacement planning.

## 3. Adapters

- [x] 3.1 Implement the filesystem scanner, ExifTool metadata reader, and Pillow
  thumbnail writer with tests.
- [x] 3.2 Implement the OpenCV SIFT/RANSAC pair verifier with tests on synthetic
  images.
- [x] 3.3 Implement the Xpano CLI stitcher with a fake-binary test and a real
  smoke test.
- [x] 3.4 Implement the safe replacement transaction with trash, rollback, and
  undo, and test success and failure paths.
- [x] 3.5 Implement SQLite repositories for photos, groups, stitches, and
  operations.

## 4. Web interface

- [x] 4.1 Add the FastAPI application, dependency wiring, and job runner.
- [x] 4.2 Add folder management: schema, path validation, list/add/remove,
  folder browser, and folder-scoped photo and group sync.
- [x] 4.3 Add endpoints for folder scan, all-folder scan, groups by folder,
  thumbnails, stitch, replace, undo, operations, settings, active jobs, and job
  status.
- [x] 4.4 Build the folder manager, group list filtered by folder, group detail,
  operations, and settings pages.
- [x] 4.5 Persist the selected folder in the URL and local storage and resume
  active jobs on every page load.
- [x] 4.6 Add confirmation and error handling for replacement.
- [x] 4.7 Add API integration tests with a fake stitcher and folder-scoped scan
  tests.
- [x] 4.8 Serve original-resolution member files and open members and the
  stitched panorama in a real-size popup.
- [x] 4.9 Fall back to the trash copy for replaced originals and make the
  panorama preview image itself open the real-size popup.
- [x] 4.10 Version static asset URLs so a rebuilt container cannot serve stale
  JavaScript or CSS after an update.

## 5. Container and verification

- [x] 5.1 Build the Ubuntu 24.04 image with Xpano, ExifTool, OpenCV, and the app.
- [x] 5.2 Verify `Xpano --version` and a headless stitch inside the container.
- [ ] 5.3 Run the full test suite on the host and in the container.
- [ ] 5.4 Start the service against a small sample folder and exercise scan,
  stitch, and replacement through the API.
- [x] 5.5 Document mounting the PhotoPrism originals and the required
  `photoprism index --cleanup` step.
- [x] 5.6 Run OpenSpec validation and record the final status.
