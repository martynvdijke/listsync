## 1. Inventory and seam-finding

- [x] 1.1 Extract the full route list (`grep '^@app\.' api_server.py`) and assign each of the 90 endpoints to a domain
- [x] 1.2 Capture the current OpenAPI schema (`/openapi.json`) as the equivalence baseline
- [x] 1.3 Identify non-HTTP logic blocks (log parsing ~201–1724, analytics ~5888–6478, sync runner ~4050/5475, image proxy ~8359–8693) and their domain modules

### 1.1 route inventory — 89 HTTP operations across 9 domains

analytics 21, system 24, lists 10, sync 5, collections 9, logs 8, settings 3,
sync-history 4, images 5. (The 90th `@app.` decorator in the original file was the
startup hook, which is not a route.) `tests/test_route_inventory.py` asserts the
per-router decorator count.

### 1.2 equivalence baseline

`tests/openapi_baseline.json` — 85 paths / 89 operations, dumped from
`api_server.app.openapi()` (indent=2, sort_keys=True).

## 2. Establish the package skeleton

- [x] 2.1 Create the application package with `create_app()`, router registration, CORS middleware, and startup hook
- [x] 2.2 Add a compatibility shim so `api_server:app` still resolves
- [x] 2.3 Add a route-inventory test comparing the app's schema to the baseline

Package is `list_sync/web/` (auto-included via the poetry `list_sync` package):
`app.py` holds the factory, CORS, startup hook, exception handler and
`SERVER_START_TIME`; `common.py` holds shared models/helpers; `routers/*` and
`services/*` hold the HTTP and non-HTTP layers. `create_app()` imports the routers
inside the factory and returns a configured app without binding a port.

`api_server.py` is a shim: it re-exports `app`, `create_app`, `startup_event`,
`unhandled_exception_handler`, `sniff_image_type`, `DB_FILE`, `init_database`, and
keeps the `uvicorn.run("api_server:app", …)` `__main__` block.

## 3. Extract routers incrementally

- [x] 3.1 Extract system/setup routes
- [x] 3.2 Extract lists/items routes
- [x] 3.3 Extract sync orchestration routes and move the subprocess runner into a service module
- [x] 3.4 Extract collections routes
- [x] 3.5 Extract images routes and move the image service into a module
- [x] 3.6 Extract settings/notifications routes
- [x] 3.7 Extract logs routes (live tail / SSE)
- [x] 3.8 Extract analytics routes and move `process_*` aggregation into an analytics module
- [x] 3.9 Extract sync-history routes

All nine routers live under `list_sync/web/routers/`; the moved non-HTTP logic
lives under `list_sync/web/services/` (`analytics`, `images`, `logs`,
`sync_runner`). The two deliberately duplicate handler names that distinguish
same-path methods (`cleanup_image_cache`, `get_recent_activity`) are preserved so
the generated operationIds stay stable.

## 4. Verify and validate

- [x] 4.1 Confirm no route decorators remain in the shim
- [x] 4.2 Run `python tests/run_all.py` and fix failures
- [x] 4.3 Diff the OpenAPI schema against the baseline and confirm equivalence
- [x] 4.4 Run `openspec validate modularize-api-server --strict`

### 4.1–4.4 verification (actual)

- `api_server.py` contains 0 `@app.`/`@router.` decorators (`tests/test_route_inventory.py`).
- `uvx ruff@0.6.7 check .` → All checks passed; `uvx ruff@0.6.7 format --check .` → 75 files already formatted.
- `python3 tests/run_all.py` → 632 checks passed across 20 suites (was 573 / 19; adds `test_route_inventory`).
- Schema diff: re-dumped the live schema and `diff` against `tests/openapi_baseline.json` → identical (85 paths / 89 operations).
- `openspec validate modularize-api-server --strict` → Change is valid.
