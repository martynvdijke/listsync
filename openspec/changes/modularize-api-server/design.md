## Context

`api_server.py` is a single 8,693-line module holding 90 route decorators. Distinct concerns are interleaved: log parsing (lines ~201–1724), analytics (5888–6478), sync subprocess orchestration (`_run_sync_in_subprocess` at 4050, `_run_collection_sync_in_subprocess` at 5475), image proxy/cache (8359–8693), settings, and SSE. Deferred `from list_sync... import` statements (~35 of them) inside handler bodies already signal that the module cannot cleanly import its dependencies at top level. There is no test seam: mounting the app pulls in the entire file.

## Goals / Non-Goals

**Goals:**
- One obvious place per concern; reviewers and tests can target a domain without loading everything.
- Thin handlers delegating to services.
- App factory for testability.
- Zero behavior change.

**Non-Goals:**
- Changing endpoints, response shapes, or business logic.
- Rewriting the database layer (separate change `enforce-data-layer-boundary`).
- Replacing log parsing with DB reporting (separate change `db-backed-sync-reporting`).
- Changing the frontend.

## Decisions

### D1: Routers grouped by domain, not by layer

Split by domain (sync, lists, images, analytics…) rather than by technical layer (all GETs here, all POSTs there). Domain split aligns with ownership and keeps related handlers together.

*Rejected:* A generic "routes.py + services.py" split — still two giant files, no seam improvement.

### D2: Non-HTTP logic moves into service modules

Log parsing, analytics aggregation, subprocess orchestration, and the image service become importable modules. Handlers become plumbing. This is what makes handlers testable and small.

### D3: App factory + compatibility shim

`create_app()` builds the app; `api_server.py` becomes `app = create_app()`. The deployed command `uvicorn api_server:app` is preserved, so `start_api.py` and Docker entrypoints do not change. The shim is intentional and documented, not accidental.

### D4: Extract one domain per commit, gated by a route-inventory test

The baseline OpenAPI schema is captured first; a test compares the live schema to it after each extraction. This makes a 90-route refactor safe to do incrementally.

## Risks / Trade-offs

- [A 90-route refactor silently drops or renames a route] → OpenAPI schema diff test (2.3/4.3) fails on any change.
- [Circular imports as logic moves out of the monolith] → Services depend on `list_sync.*`; routers depend on services; the app factory depends on routers. One direction only.
- [Large diff is hard to review] → Domain-by-domain extraction, each independently verifiable.
- [Temporary duplication while old and new paths coexist] → Keep the change unmerged until the shim holds no routes; do not ship a half-migrated state.
- [Startup hook ordering changes behavior] → Keep the single startup hook in the factory and verify startup tests pass.

## Migration Plan

1. Baseline the OpenAPI schema and inventory routes (section 1).
2. Build the factory and shim with one trivial router, verify startup and the inventory test (section 2).
3. Move domains one at a time, running the suite after each (section 3).
4. Confirm the shim is route-free and the schema is equivalent (section 4).
Rollback: each domain extraction is a separate commit; revert the offending commit without touching the others.

## Open Questions

- Package location: extend `list_sync/` (e.g. `list_sync/web/`) or a sibling `webapp/` package? `list_sync/` keeps one installable package per `pyproject.toml`.
- Should the log-parsing block move as-is, or wait for `db-backed-sync-reporting` to delete most of it first? Sequencing may remove ~1,700 lines this change would otherwise relocate.
- Do we want a per-domain `routes.py` + `service.py` convention, or flat modules?
