## Context

`docs/` holds `advanced-usage.md`, `api.md`, `api-reference.md`, `architecture.md`, `configuration.md`, `contributing.md`, `how-it-works.md`, `installation.md`, `legal-disclaimer.md`, `README.md`, `roadmap.md`, `troubleshooting.md`, `user-guide.md`. `docs/docsnew/` holds `api-reference.md`, `architecture.md`, `configuration.md`, `contributing.md`, `installation.md`, `legal-disclaimer.md`, `README.md`, `troubleshooting.md`, `user-guide.md`. Nine subjects overlap exactly. Git history shows both updated by the same commits, so they are being co-maintained — the worst of both worlds. `docsnew` is referenced nowhere, so nothing even points readers to it.

## Goals / Non-Goals

**Goals:**
- One canonical tree, no duplicated subjects.
- Preserve unique content.
- Working links and one entry point.

**Non-Goals:**
- Rewriting documentation for accuracy/quality (separate effort).
- Changing code or configuration.
- Building a docs site generator (none is configured today).

## Decisions

### D1: Prefer the fuller/newer tree, decided by content comparison

`docs/docsnew/` is the larger set (~9.7k vs ~7.4k lines) and has a "new" name, but that is not sufficient evidence — 1.1 compares content. The default assumption is that `docsnew` is the intended successor; the decision is confirmed by diffing before deletion. Either way, exactly one survives.

*Rejected:* Keeping both and adding a "canonical" banner — duplication continues and readers still cannot tell.

### D2: Merge before delete

Deleting first and re-adding lost content later is how documentation disappears. 2.2/2.3 enumerate unique sections and merge them before removal.

### D3: No docs generator

There is no Docusaurus/VitePress/MkDocs config in the repo. Adding one is out of scope; consolidation is a file/link exercise.

## Risks / Trade-offs

- [The canonical tree is missing content the dropped one had] → 2.3 requires explicit enumeration and merge-or-record before deletion.
- [Links from the README or GitHub templates break] → 3.2/4.1 update and link-check.
- [Losing `how-it-works.md` / `roadmap.md` / `advanced-usage.md` which exist only in `docs/`] → These are unique to `docs/` and must be migrated into the canonical tree, not dropped, unless deliberately retired.
- [Git history confusion after a big docs move] → Do the merge and the delete as separate commits with clear messages.

## Migration Plan

1. Compare and choose (section 1).
2. Merge unique sections (section 2).
3. Delete the loser and fix references (section 3).
4. Link-check and validate (section 4).
Rollback: deletion is a single commit on top of the merge; reverting restores the dropped tree while the merged canonical tree remains.

## Open Questions

- Which tree is genuinely canonical — does `docsnew` contain everything in `docs/`, including `how-it-works.md`, `roadmap.md`, and `advanced-usage.md` which have no counterpart?
- Should the root `ReadMe.md` (788 lines) itself be slimmed and point into the docs tree, or remain the standalone overview?
- Is any external party (wiki, website) linking to `docs/` paths that must keep working?
