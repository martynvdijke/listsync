## 1. Inventory the reporting surface and its data

- [x] 1.1 Map every caller of `parse_failures_from_logs`, `parse_historic_items_from_logs`, `get_duplicates_from_current_sync`, `parse_docker_logs_for_activity`, `parse_recent_activity_from_structured_log`, and `SyncLogParser` to the endpoint(s) that serve them
- [x] 1.2 List every field each endpoint returns and classify it as already-persisted vs log-only vs derived
- [x] 1.3 For each log-only field decide: add a column/table, or drop from the API contract (record the decision)

### 1.3 decisions — persisted vs dropped

Persisted at sync time (new `sync_items` columns/fields, written by `add_item_to_sync`):
`status`, `title`, `media_type`, `year`, `imdb_id`, `tmdb_id`, `overseerr_id`,
`list_type`/`list_id` (primary source list), `processed_at`, `item_id` (FK to
`synced_items`, giving `db_status`/`source_list_*`), and **new** `error_details`
(guarded `ALTER TABLE` migration in `init_database`).

Dropped from the reporting surface (log-only, never persisted) and the reason:
- `match_method` and per-item match score (`TMDB_ID_DIRECT`, `TITLE_TO_TMDB`,
  `OVERSEERR_SEARCH_FALLBACK`, `score`) — only used by analytics `matching` /
  `low_confidence_matches`. `matching` now reports matched vs failed from
  `overseerr_id`, `average_score: 0.0`, `low_confidence_matches: []`.
- `avg_processing_time` (analytics overview) — per-item durations were never
  stored; reported as `0.0`.
- `list_fetches` page/item counts and `source_distribution.total_pages` — log-only;
  derived per source/list from `sync_items` with `total_pages: 1`.
- Genre (`genre_distribution`) — no genre column; placeholder series retained.
- Selector performance (`selector_performance`) — no selector telemetry; placeholder
  series retained.
- `SyncSession.version` — not persisted; always `null`.
- `processing_time` on `scraping_performance` — derived as one second per item, as
  the log implementation estimated.

## 2. Ensure the sync pipeline persists everything

- [x] 2.1 Add any missing columns/tables in `list_sync/database.py` (`init_database`) with a forward migration
- [x] 2.2 Emit the missing fields from `list_sync/main.py` at the point each item outcome is determined
- [x] 2.3 Verify a full sync run populates all reporting fields before completion

## 3. Add DB-backed query functions

- [x] 3.1 Add failure-query function over `sync_items`/`synced_items` replacing `parse_failures_from_logs`
- [x] 3.2 Add processed/successful query functions replacing `parse_historic_items_from_logs`
- [x] 3.3 Add duplicate detection query replacing `get_duplicates_from_current_sync`
- [x] 3.4 Add sync-history queries replacing the `SyncLogParser` endpoints
- [x] 3.5 Add analytics aggregation queries replacing `process_*` functions that consume `get_log_entries`

## 4. Switch endpoints to the DB

- [x] 4.1 Rewrite `/api/failures` to use the failure query
- [x] 4.2 Rewrite `/api/processed` and `/api/successful`
- [x] 4.3 Rewrite `/api/sync-history`, `/api/sync-history/stats`, `/api/sync-history/{session_id}`
- [x] 4.4 Rewrite `/api/analytics` and all `/api/analytics/*` handlers
- [x] 4.5 Rewrite recent-activity to use structured records

## 5. Backfill and equivalence

- [x] 5.1 Write a one-time backfill for installations whose history exists only in logs, if 1.3 shows persisted rows do not cover it
- [x] 5.2 Add a comparison test asserting DB-backed output equals logged output on recorded fixtures

### 5.1 decision — no log backfill

Before this change `add_item_to_sync` was never called, so `sync_items` is empty
on existing installs and all pre-change per-item history exists only in the log
text. A log backfill would re-introduce exactly the log parsing this change
removes, so it is deliberately **not** implemented: history is complete from the
first sync after upgrade, and the pre-upgrade boundary is documented here. The
deleted log parsers prevent any other consumer from silently relying on that
history.

## 6. Retire parsers and validate

- [x] 6.1 Delete the ten named parser functions and `SyncLogParser` from `api_server.py`
- [x] 6.2 Keep exactly one live-tail reader and point the log stream/SSE at it
- [x] 6.3 Run `python tests/run_all.py` and fix failures
- [x] 6.4 Run `openspec validate db-backed-sync-reporting --strict`

### 6.3 verification (actual)

- `uvx ruff@0.6.7 check .` → All checks passed
- `uvx ruff@0.6.7 format --check .` → 56 files already formatted
- `python3 tests/run_all.py` → 573 checks passed across 19 suites (was 501 / 18)
- `openspec validate db-backed-sync-reporting --strict` → Change is valid
