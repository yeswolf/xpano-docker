# Spec Delta

## Purpose

Replace the source files of a panorama group with the stitched panorama while
preserving the originals in a recoverable trash area and recording an auditable
operation.

## ADDED Requirements

### Requirement: Explicit confirmation
The system SHALL require an explicit confirmation for every replacement and
SHALL never replace files as an automatic consequence of stitching.

#### Scenario: Replacement requires confirmation
- **WHEN** the operator requests replacement without confirming
- **THEN** the system rejects the request and leaves the library unchanged

### Requirement: Safe replacement order
The system SHALL write the panorama to a temporary path, move every source photo
and its related sidecars into the operation trash, and only then publish the
panorama at its final path.

#### Scenario: Successful replacement
- **WHEN** a confirmed replacement runs and all moves succeed
- **THEN** the panorama exists in the library, the source files exist only in
  the operation trash, and the operation is marked completed

#### Scenario: Failure before publishing
- **WHEN** writing the panorama or moving a source file fails
- **THEN** the system moves already-trashed files back, removes partial output,
  and marks the operation failed

### Requirement: Recoverable originals
The system SHALL preserve all replaced originals and related sidecars in a trash
directory on persistent storage until the operator explicitly removes them.

#### Scenario: Operator undoes a replacement
- **WHEN** the operator requests undo for a completed replacement
- **THEN** the system moves the panorama out of the library and restores every
  original file and sidecar to its previous path

### Requirement: Collision-free output
The system SHALL choose a final panorama filename that does not overwrite an
existing file and SHALL report the chosen path.

#### Scenario: Name already exists
- **WHEN** the preferred panorama path is already occupied
- **THEN** the system adds a deterministic suffix instead of overwriting the
  existing file

### Requirement: Operation audit
The system SHALL persist each replacement with its group, source paths, trash
paths, panorama path, status, and timestamps, and SHALL expose the history in
the web interface.

#### Scenario: Operator reviews history
- **WHEN** the operator opens the operations view
- **THEN** the interface lists completed and failed replacements with enough
  information to locate the trash and undo a completed one
