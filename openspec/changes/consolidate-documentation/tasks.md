## 1. Choose the canonical tree

- [ ] 1.1 Compare `docs/` (12 files, ~7.4k lines) and `docs/docsnew/` (9 files, ~9.7k lines) file-by-file and determine which is more complete and current
- [ ] 1.2 Confirm no tooling, CI, or README references the tree being dropped (`docsnew` is currently referenced nowhere)
- [ ] 1.3 Record the decision and rationale (see design D1)

## 2. Merge unique content

- [ ] 2.1 Diff each subject pair (api vs api-reference, architecture, configuration, troubleshooting, user-guide, installation, contributing, legal-disclaimer, README)
- [ ] 2.2 Identify sections present only in the losing tree
- [ ] 2.3 Merge those sections into the canonical tree, or record a deliberate drop with reason

## 3. Remove the duplicate

- [ ] 3.1 Delete the losing tree
- [ ] 3.2 Update all references in `ReadMe.md`, `.github/`, and any code comments pointing at removed paths
- [ ] 3.3 Add/adjust the docs index so the entry point is unambiguous

## 4. Verify and validate

- [ ] 4.1 Link-check the canonical tree for dangling internal references
- [ ] 4.2 Confirm `docsnew` no longer appears anywhere in the repo
- [ ] 4.3 Run `openspec validate consolidate-documentation --strict`
