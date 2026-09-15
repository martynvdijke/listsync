## 1. Inventory the leak

- [ ] 1.1 List every `sqlite3.connect(DB_FILE)` site in `api_server.py` and classify each as query vs mutation
- [ ] 1.2 List every `execute`/`cursor` use not covered above
- [ ] 1.3 Confirm the two `normalize_list_id` definitions (`api_server.py:353`, `database.py:21`) and diff their behavior on representative inputs

## 2. Establish the boundary

- [ ] 2.1 Add a shared connection/transaction helper to `list_sync/database.py`
- [ ] 2.2 Add a guard test asserting non-DAL modules do not import `sqlite3` for the app DB

## 3. Canonicalize list identity

- [ ] 3.1 Delete `normalize_list_id` from `api_server.py` and import the canonical one from `list_sync/database.py`
- [ ] 3.2 Verify all callers use the canonical function and that URL-vs-id lookups resolve to the same row

## 4. Move inline SQL into named DAL functions

- [ ] 4.1 Migrate `/api/items/enriched` DB access (api_server.py ~3490)
- [ ] 4.2 Migrate `/api/processed` DB access (~4643)
- [ ] 4.3 Migrate `/api/requested` DB access (~4909)
- [ ] 4.4 Migrate `/api/lists` DB access (~3193, ~3355)
- [ ] 4.5 Migrate image cache DB access (~8665) and settings/history DB access (~1744, ~1800, ~7222)
- [ ] 4.6 Remove the now-unused `sqlite3` import from `api_server.py`

## 5. Verify and validate

- [ ] 5.1 Add DAL tests for every new function
- [ ] 5.2 Run `python tests/run_all.py` and fix failures
- [ ] 5.3 Run `openspec validate enforce-data-layer-boundary --strict`
