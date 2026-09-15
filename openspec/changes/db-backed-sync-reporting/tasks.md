## 1. Inventory the reporting surface and its data

- [ ] 1.1 Map every caller of `parse_failures_from_logs`, `parse_historic_items_from_logs`, `get_duplicates_from_current_sync`, `parse_docker_logs_for_activity`, `parse_recent_activity_from_structured_log`, and `SyncLogParser` to the endpoint(s) that serve them
- [ ] 1.2 List every field each endpoint returns and classify it as already-persisted vs log-only vs derived
- [ ] 1.3 For each log-only field decide: add a column/table, or drop from the API contract (record the decision)

## 2. Ensure the sync pipeline persists everything

- [ ] 2.1 Add any missing columns/tables in `list_sync/database.py` (`init_database`) with a forward migration
- [ ] 2.2 Emit the missing fields from `list_sync/main.py` at the point each item outcome is determined
- [ ] 2.3 Verify a full sync run populates all reporting fields before completion

## 3. Add DB-backed query functions

- [ ] 3.1 Add failure-query function over `sync_items`/`synced_items` replacing `parse_failures_from_logs`
- [ ] 3.2 Add processed/successful query functions replacing `parse_historic_items_from_logs`
- [ ] 3.3 Add duplicate detection query replacing `get_duplicates_from_current_sync`
- [ ] 3.4 Add sync-history queries replacing the `SyncLogParser` endpoints
- [ ] 3.5 Add analytics aggregation queries replacing `process_*` functions that consume `get_log_entries`

## 4. Switch endpoints to the DB

- [ ] 4.1 Rewrite `/api/failures` to use the failure query
- [ ] 4.2 Rewrite `/api/processed` and `/api/successful`
- [ ] 4.3 Rewrite `/api/sync-history`, `/api/sync-history/stats`, `/api/sync-history/{session_id}`
- [ ] 4.4 Rewrite `/api/analytics` and all `/api/analytics/*` handlers
- [ ] 4.5 Rewrite recent-activity to use structured records

## 5. Backfill and equivalence

- [ ] 5.1 Write a one-time backfill for installations whose history exists only in logs, if 1.3 shows persisted rows do not cover it
- [ ] 5.2 Add a comparison test asserting DB-backed output equals logged output on recorded fixtures

## 6. Retire parsers and validate

- [ ] 6.1 Delete the ten named parser functions and `SyncLogParser` from `api_server.py`
- [ ] 6.2 Keep exactly one live-tail reader and point the log stream/SSE at it
- [ ] 6.3 Run `python tests/run_all.py` and fix failures
- [ ] 6.4 Run `openspec validate db-backed-sync-reporting --strict`
