## Why

`list_sync/database.py` is the data-access layer (2,094 lines, ~60 functions), but `api_server.py` bypasses it: 15 raw `sqlite3.connect(DB_FILE)` sites and 76 `execute`/`cursor` uses hand-write SQL inside HTTP handlers. Worse, `normalize_list_id` — the canonicalizer for list identity — is defined twice, once in `api_server.py:353` and once in `database.py:21`, with different docstrings. Two canonicalizers for one key is a latent silent-miss bug: a lookup can miss and fall back to defaults when the two definitions drift.

## What Changes

- Route all database access through named functions in `list_sync/database.py`; remove direct `sqlite3` usage from `api_server.py` and any other non-DAL module.
- Delete the duplicate `normalize_list_id` in `api_server.py` and import the canonical one.
- Convert inline handler SQL into named DAL functions (queries and mutations).
- Add one shared connection/transaction helper so connection handling (commit/rollback/close) is consistent.
- Preserve query semantics and results exactly.

## Capabilities

### New Capabilities
- `data-layer`: a single, enforced data-access boundary — all persistence goes through named functions in one module, with one canonical list-id normalization.

### Modified Capabilities
<!-- openspec/specs/ is empty; no existing capabilities to modify. -->

## Impact

- `api_server.py`: raw `sqlite3.connect` / `execute` sites replaced with DAL calls; duplicate `normalize_list_id` removed.
- `list_sync/database.py`: new query/mutation functions and a connection helper.
- Tests: DAL-level tests for the newly named functions; a guard test that no module outside the DAL imports `sqlite3` for the app DB.
