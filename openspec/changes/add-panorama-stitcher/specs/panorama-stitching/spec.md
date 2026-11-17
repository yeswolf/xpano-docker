# Spec Delta

## Purpose

Turn a reviewed candidate group into a stitched panorama image without changing
the source library until the operator explicitly requests replacement.

## ADDED Requirements

### Requirement: On-demand stitching
The system SHALL stitch a selected group on explicit operator request using the
Xpano command-line engine and SHALL store the result outside the source library.

#### Scenario: Group stitches successfully
- **WHEN** the operator requests a panorama for a group with stitchable members
- **THEN** the system runs Xpano on exactly the group members and records the
  output path, width, and height

#### Scenario: Stitching fails
- **WHEN** Xpano exits with an error or produces no output
- **THEN** the system marks the attempt as failed, shows the engine error, and
  leaves every source file unchanged

### Requirement: Result preview
The system SHALL serve a preview of a successful stitch result from the web
interface before any replacement is allowed.

#### Scenario: Operator reviews the panorama
- **WHEN** a stitch succeeds
- **THEN** the group view shows the stitched image and its dimensions

### Requirement: Serialized stitching
The system SHALL run at most one stitch operation at a time and SHALL report
queued, running, completed, and failed states.

#### Scenario: Second request while stitching
- **WHEN** the operator requests a stitch while another stitch is running
- **THEN** the new request is queued and starts after the running one finishes
