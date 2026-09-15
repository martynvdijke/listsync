## Context

`list_sync/database.py` already is a real data-access module: ~60 named functions over tables `lists`, `synced_items`, `item_lists`, `sync_history`, `sync_items`, `settings`, `overseerr_users`, `cached_images`, with indexes and migrations in `init_database()`. Yet `api_server.py` reaches past it with 15 raw `sqlite3.connect(DB_FILE)` calls and 76 `execute`/`cursor` uses, hand-writing SQL in handlers (e.g. `/api/requested` at 4909, `/api/processed` at 4643, `/api/items/enriched` at 3490). `normalize_list_id` exists in both files (`api_server.py:353`, `database.py:21`). The deferred `from list_sync.database import ...` statements inside handlers show the boundary is already partially recognized but not enforced.

## Goals / Non-Goals

**Goals:**
- One place that knows SQL; handlers ask the DAL.
- One canonical list-id normalizer.
- Consistent transaction handling.
- Identical query results.

**Non-Goals:**
- Adopting an ORM (the stdlib `sqlite3` + named functions is sufficient and already in use).
- Schema redesign or new tables (handled by `db-backed-sync-reporting` where needed).
- Changing endpoint contracts.

## Decisions

### D1: Named DAL functions, not a query builder or ORM

Each migrated query becomes a function like `get_enriched_items(...)`. Stdlib `sqlite3` stays; no new dependency. A query builder/ORM would be more machinery than the ~15 leaked call sites justify.

### D2: One canonical `normalize_list_id` in the data layer

Identity normalization is a data concern. The `api_server.py` copy is deleted and imported from the DAL. This removes the drift risk between the two definitions.

### D3: Shared connection/transaction helper

A small context manager centralizes connect/commit/rollback/close so every call site behaves the same on error. This addresses the current mix of `with sqlite3.connect(...)` and bare `connect()` + manual close.

### D4: Guard test over convention

A test asserts that modules outside the DAL do not import `sqlite3` for the app DB. Enforcement beats documentation; without it the boundary will leak again.

### D5: Migrate one endpoint at a time

Each migrated endpoint is a small, independently verifiable diff with a DAL test, rather than one sweeping rewrite.

## Risks / Trade-offs

- [A migrated query subtly changes filtering or ordering] → DAL tests assert row set, ordering, and field values against the previous behavior.
- [The guard test is too strict and blocks legitimate uses] → Scope it to the application DB path; allow explicit, reviewed exceptions.
- [Transaction helper changes autocommit behavior] → Match existing semantics per call site (many use `with sqlite3.connect` which commits on success); test rollback explicitly.
- [Two `normalize_list_id` implementations differ on an edge case] → Diff them on representative inputs (URL vs bare id, trailing slashes) before deleting either.

## Migration Plan

1. Inventory leaked sites and diff the normalizers (section 1).
2. Add the helper and the guard test (section 2).
3. Canonicalize identity (section 3).
4. Migrate call sites endpoint-by-endpoint (section 4).
5. Run the suite and validate (section 5).
Rollback: each endpoint migration is a separate commit; the guard test is added last to avoid blocking mid-migration.

## Open Questions

- Does `db-backed-sync-reporting` create the DAL functions this change would otherwise add? If so, land that change first and migrate only the remaining sites.
- Should the guard test be a lint rule (banned import) or a test? A lint rule can be bypassed less easily but needs ruff configuration.
