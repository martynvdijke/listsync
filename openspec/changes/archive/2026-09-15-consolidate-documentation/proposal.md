## Why

The repository ships two parallel documentation trees covering the same subjects: `docs/` (12 files, ~7,400 lines) and `docs/docsnew/` (9 files, ~9,700 lines). Both were updated by the same recent commits (`09c635a`, `82acd8f`, `3a19848`), and `docsnew` is referenced nowhere in the repo. A reader cannot tell which is canonical, and every documentation change becomes a "do I update both?" decision that will eventually be answered wrong. Duplicated docs always drift.

## What Changes

- Choose one canonical documentation tree and delete the other.
- Merge any content unique to the losing tree into the canonical set before deletion.
- Fix inbound references so nothing links to a removed path.
- Ensure a single docs index / README entry point.
- Reconcile the root `ReadMe.md` and any overlapping guides with the canonical tree.

## Capabilities

### New Capabilities
- `documentation`: one canonical, non-duplicated documentation set with a single entry point and working internal links.

### Modified Capabilities
<!-- openspec/specs/ is empty; no existing capabilities to modify. -->

## Impact

- `docs/` and `docs/docsnew/`: one is deleted, the other becomes canonical.
- Root `ReadMe.md` and `.github/` templates: references updated.
- No code behavior change.
