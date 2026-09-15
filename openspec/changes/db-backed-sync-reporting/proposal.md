## Why

Every sync run already writes structured, indexed rows (`synced_items`, `item_lists`, `sync_history`, `sync_items` via `list_sync/database.py`), yet the reporting surface re-derives the same facts by parsing the emoji-laden `data/list_sync.log` with ~10 independent parsers and 93 regexes in `api_server.py`. The log file has become a de-facto database. Two sources of truth for one fact means endpoints disagree (`/api/requested` reads SQLite while `/api/successful` and `/api/failures` parse logs), and every log-format tweak risks silently breaking reporting.

## What Changes

- Make the database the single source of truth for per-item outcomes, sync history, and analytics inputs.
- Replace log-parsing report functions with query functions in `list_sync/database.py` (`parse_failures_from_logs`, `parse_historic_items_from_logs`, `get_duplicates_from_current_sync`, and the `SyncLogParser`-based history endpoints).
- Retire the duplicated log parsers and `SyncLogParser` once endpoints read from the DB; keep exactly one shared line reader for the *live tail* / SSE stream only.
- **BREAKING**: any fact not currently persisted (e.g. log-only fields) is either added as a column/table via migration or explicitly dropped from the reporting surface.

## Capabilities

### New Capabilities
- `sync-reporting`: structured, database-backed reporting of sync outcomes, failures, duplicates, history, and analytics; the text log is retained only as a human-readable and live-tail artifact.

### Modified Capabilities
<!-- openspec/specs/ is empty; no existing capabilities to modify. -->

## Impact

- `api_server.py`: `/api/failures`, `/api/processed`, `/api/successful`, `/api/duplicates` (inside `/api/stats/*`), `/api/recent-activity`, `/api/sync-history*`, `/api/analytics/*`; removal of `parse_log_for_sync_info`, `parse_docker_logs_for_activity`, `parse_failures_from_logs`, `parse_historic_items_from_logs`, `get_duplicates_from_current_sync`, `categorize_log_entry`, `extract_media_info`, `parse_log_line`, `parse_recent_activity_from_structured_log`, and `SyncLogParser`.
- `list_sync/database.py`: new query functions over existing `sync_items` / `sync_history` / `synced_items` tables.
- `list_sync/main.py`: ensure every reported outcome is persisted at sync time; no log-only facts.
- Tests: DB-backed reporting suites; regression fixtures for the log formats that are being retired.
