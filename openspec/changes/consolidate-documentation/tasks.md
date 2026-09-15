## 1. Choose the canonical tree

- [x] 1.1 Compare `docs/` (12 files, ~7.4k lines) and `docs/docsnew/` (9 files, ~9.7k lines) file-by-file and determine which is more complete and current
- [x] 1.2 Confirm no tooling, CI, or README references the tree being dropped (`docsnew` is currently referenced nowhere)
- [x] 1.3 Record the decision and rationale (see design D1) — DECISION: canonical *path* is `docs/`; canonical *content* is `docs/docsnew/` for all 9 overlapping subjects (fuller/newer: api-reference 1112 vs 668 lines, architecture 1311 vs 407, configuration 958 vs 530, contributing 1437 vs 674, installation 1078 vs 647, legal-disclaimer 559 vs 232, README 263 vs 197, troubleshooting 1569 vs 1016, user-guide 757 vs 598). Keeping the `docs/` path means existing inbound links (ReadMe.md → `/docs/*.md`) keep working; only `docs/api.md` needed a link update.

## 2. Merge unique content

- [x] 2.1 Diff each subject pair (api vs api-reference, architecture, configuration, troubleshooting, user-guide, installation, contributing, legal-disclaimer, README)
- [x] 2.2 Identify sections present only in the losing tree
- [x] 2.3 Merge those sections into the canonical tree, or record a deliberate drop with reason
  - Unique-to-`docs/` files preserved untouched: `advanced-usage.md`, `how-it-works.md`, `roadmap.md`.
  - `docs/api-reference.md` (old) was a *different subject* (provider API interface, Seerr client, DB schema, extension points, monitoring) with no counterpart in docsnew → renamed to `docs/developer-reference.md`.
  - Unique REST sections from old `docs/api.md` merged verbatim into canonical `docs/api-reference.md` under "📎 Additional Endpoints": Log Categories, Log Statistics, Sync Interval from Environment, Get Seerr Configuration, Timezone & Localization, Data Endpoints, Response Formats.
  - Deliberate drop: old `docs/api.md` "Usage Examples" (Python/JS/curl) — already covered by the canonical page's "Integration Examples"; not duplicated.

## 3. Remove the duplicate

- [x] 3.1 Delete the losing tree
- [x] 3.2 Update all references in `ReadMe.md`, `.github/`, and any code comments pointing at removed paths
- [x] 3.3 Add/adjust the docs index so the entry point is unambiguous

## 4. Verify and validate

- [x] 4.1 Link-check the canonical tree for dangling internal references
- [x] 4.2 Confirm `docsnew` no longer appears anywhere in the repo
- [x] 4.3 Run `openspec validate consolidate-documentation --strict`
