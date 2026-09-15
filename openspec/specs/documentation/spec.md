# documentation Specification

## Purpose
TBD - created by archiving change consolidate-documentation. Update Purpose after archive.
## Requirements
### Requirement: Exactly one canonical documentation tree

The repository SHALL contain a single documentation tree for product documentation; no two trees SHALL cover the same subjects.

#### Scenario: Duplicate tree removed

- **WHEN** listing top-level documentation directories
- **THEN** only one canonical docs tree exists (either `docs/` or `docs/docsnew/`), not both

#### Scenario: No topic is documented twice

- **WHEN** searching the canonical tree for a subject (architecture, configuration, troubleshooting, user guide, API reference, installation)
- **THEN** each subject has exactly one authoritative page

### Requirement: No content is lost in consolidation

Before deleting the losing tree, any content unique to it SHALL be merged into the canonical tree.

#### Scenario: Unique content preserved

- **WHEN** diffing the losing tree against the canonical tree during consolidation
- **THEN** every unique section is either merged into the canonical set or explicitly and deliberately dropped with a recorded reason

### Requirement: Internal links resolve

Documentation SHALL NOT link to removed paths; internal links and the root README SHALL resolve within the canonical tree.

#### Scenario: No dangling references

- **WHEN** scanning markdown links across the repo for the removed docs path
- **THEN** no links point to it

#### Scenario: Entry point is unambiguous

- **WHEN** a reader opens the documentation entry point
- **THEN** it links into the canonical tree and indicates where that tree lives

### Requirement: A single documentation entry point

The project SHALL expose one obvious documentation entry point (root README or a docs index) that does not present conflicting sources.

#### Scenario: README points to canonical docs

- **WHEN** reading the root `ReadMe.md`
- **THEN** its documentation links resolve to the canonical tree

