# Spec Delta

## Purpose

Discover candidate panorama groups in a photo library and present them for
human review before any stitching or file replacement happens.

## ADDED Requirements

### Requirement: Library scan
The system SHALL recursively scan a configured photo root and index supported
image files with their capture time, camera, dimensions, and filesystem path.

#### Scenario: Scan finds images
- **WHEN** the operator starts a scan of a directory containing JPEG files
- **THEN** the system reports the number of indexed images and makes them
  available for group detection

#### Scenario: Unsupported files are skipped
- **WHEN** the scan encounters a file with an unsupported extension or a file
  that cannot be decoded
- **THEN** the scan continues and records the file in a skipped-files report

### Requirement: Candidate group detection
The system SHALL form candidate panorama groups only from images that are
temporally adjacent and have verified geometric overlap, and SHALL assign each
group a confidence value.

#### Scenario: Panorama sweep becomes a group
- **WHEN** a sequence of overlapping photos was taken within the configured time
  window and pairwise matching finds sufficient inlier correspondences
- **THEN** the system creates one candidate group containing the overlapping
  sequence

#### Scenario: Burst of the same scene is not a panorama
- **WHEN** consecutive photos overlap but show no cumulative camera drift
- **THEN** the system does not create a panorama group for that sequence

### Requirement: Group review
The system SHALL expose every candidate group with its member thumbnails,
capture times, dimensions, confidence, and current status in the web interface.

#### Scenario: Operator inspects a group
- **WHEN** the operator opens a detected group
- **THEN** the interface lists every member photo and shows a thumbnail for each
  member

### Requirement: Full-size photo review
The system SHALL serve every indexed group member at its original resolution
and SHALL let the operator open any member or the stitched panorama at its real
pixel size in a popup on the group page.

#### Scenario: Open a member at real size
- **WHEN** the operator activates a member photo on the group page
- **THEN** the interface opens a popup that renders the original file at 100%
  scale and shows its dimensions

#### Scenario: Open the panorama at real size
- **WHEN** a completed stitch exists and the operator activates the panorama
  preview image or its full-size action
- **THEN** the interface opens the same popup with the full-resolution panorama

#### Scenario: Stitching failed
- **WHEN** the latest stitch for a group failed
- **THEN** the group page shows the stitching error in the panorama panel
  instead of an empty or missing preview

#### Scenario: Original was moved to the trash
- **WHEN** a source photo was moved to the trash by a replacement
- **THEN** the original-image endpoint serves the preserved trash copy at full
  resolution

#### Scenario: Original file is missing
- **WHEN** neither the indexed source file nor a completed operation's trash
  copy exists
- **THEN** the original-image endpoint reports that the file is missing instead
  of serving another file, and the popup shows an unavailable message

### Requirement: Idempotent rescan
The system SHALL keep group identifiers stable across repeated scans of an
unchanged library and SHALL NOT create duplicate groups for the same member set
and detector version.

#### Scenario: Rescanning an unchanged library
- **WHEN** the operator scans the same directory twice without changing files
- **THEN** the number of groups and their member sets remain unchanged

### Requirement: Watched folders
The system SHALL allow the operator to add, list, and remove folders inside the
configured library root and SHALL NOT index any folder that was not added
explicitly.

#### Scenario: Add a folder manually
- **WHEN** the operator submits a relative or absolute path inside the library
  root
- **THEN** the folder is persisted and appears in the folder list

#### Scenario: Reject a path outside the library
- **WHEN** the submitted path resolves outside the library root or contains a
  traversal segment
- **THEN** the system rejects it and does not index anything

### Requirement: Folder-scoped scan
The system SHALL scan a selected watched folder and SHALL replace only that
folder's photos and candidate groups, leaving other folders' indexed data
intact.

#### Scenario: Scan one folder while another is indexed
- **WHEN** folder A is scanned after folder B was indexed
- **THEN** folder B's photos and groups remain available unchanged

#### Scenario: Rescan a folder
- **WHEN** the operator rescans a folder
- **THEN** its photos and candidate groups are rebuilt without duplicates and
  the last scan time is updated

### Requirement: Persistent job state
The system SHALL persist scan, stitch, replacement, and undo jobs with their
context and status, and SHALL expose active jobs so the web interface can
resume progress after a reload or navigation.

#### Scenario: Reload during a scan
- **WHEN** the operator reloads the page while a scan is running
- **THEN** the interface reconnects to the running job and shows its current
  progress

#### Scenario: Navigate between sections
- **WHEN** the operator moves from Groups to Operations and back while a job is
  running
- **THEN** the active job remains visible and its result refreshes the affected
  view

### Requirement: Folder status
The system SHALL show each watched folder's photo count, group count, last scan
time, and last scan outcome.

#### Scenario: Folder card after a scan
- **WHEN** a scan completes for a folder
- **THEN** its card shows the updated counts, completion time, and status
