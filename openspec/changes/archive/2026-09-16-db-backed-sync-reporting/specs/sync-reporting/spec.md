## ADDED Requirements

### Requirement: Single source of truth for sync reporting

All sync reporting and analytics SHALL be derived from structured database tables written during the sync run; reporting SHALL NOT derive per-item outcomes by parsing the sync log file.

#### Scenario: Failures endpoint reads the database

- **WHEN** `/api/failures` is requested
- **THEN** the response is produced from structured sync result rows and the response is identical in shape to the current log-parsed response

#### Scenario: Successful and processed endpoints agree

- **WHEN** `/api/successful` and `/api/processed` are requested for the same sync session
- **THEN** both read the same structured source and their status counts are mutually consistent

#### Scenario: Log file is not a reporting dependency

- **WHEN** the sync log file is truncated, rotated, or absent
- **THEN** `/api/failures`, `/api/successful`, `/api/processed`, `/api/sync-history`, and `/api/analytics/*` still return correct results from the database

### Requirement: Every reported outcome is persisted at sync time

The sync pipeline SHALL persist every fact required by the reporting surface before a sync session is marked complete; a reported status SHALL NOT exist only in the log text.

#### Scenario: Persist-then-report

- **WHEN** a media item finishes with a status of requested, already available, already requested, skipped, not found, or error
- **THEN** that status and its session/list association are written to the database in the same run

#### Scenario: No log-only fields remain in the reporting surface

- **WHEN** auditing each field returned by the reporting endpoints against the database schema
- **THEN** every field maps to a stored column or is explicitly removed from the API contract

### Requirement: One log-line reader retained for the live tail only

After this change the codebase SHALL contain at most one function that parses log text lines, and it SHALL be used only for the live log tail / SSE stream, not for historical reporting.

#### Scenario: Duplicate parsers are removed

- **WHEN** searching `api_server.py` and `list_sync/` for log-parsing entry points
- **THEN** only the single live-tail reader remains; `parse_log_for_sync_info`, `parse_docker_logs_for_activity`, `parse_failures_from_logs`, `parse_historic_items_from_logs`, `get_duplicates_from_current_sync`, `categorize_log_entry`, `extract_media_info`, `parse_log_line`, `parse_recent_activity_from_structured_log`, and `SyncLogParser` are gone

#### Scenario: Live tail still streams

- **WHEN** a client subscribes to the log stream
- **THEN** new log lines are still delivered in real time using the single retained reader

### Requirement: Analytics are computed from structured events

Analytics aggregations SHALL be computed over structured sync records rather than re-parsed log entries.

#### Scenario: Analytics endpoint uses structured data

- **WHEN** `/api/analytics/overview` and `/api/analytics/*` are requested for a time range
- **THEN** the aggregation queries structured records and returns the same metrics (media additions, source distribution, match rates) as before

#### Scenario: Historic data is not lost in migration

- **WHEN** the change is deployed over an existing installation whose history exists only in log files
- **THEN** either existing structured rows already cover that history, or a one-time backfill imports it before the parsers are removed

### Requirement: Removal is gated by regression evidence

The log parsers SHALL NOT be removed until DB-backed outputs have been verified equivalent to the log-parsed outputs they replace.

#### Scenario: Equivalence check before deletion

- **WHEN** DB-backed reporting is implemented
- **THEN** a comparison test runs both implementations over recorded representative inputs, asserts equivalent output, and only then are the parsers deleted
