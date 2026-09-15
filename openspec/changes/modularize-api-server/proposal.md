## Why

`api_server.py` is 8,693 lines / 357 KB with 90 route decorators. It mixes the HTTP layer with ~1,700 lines of log parsing, ~600 lines of analytics aggregation, sync subprocess orchestration, image proxying/caching, settings management, and SSE. Every change to any one concern edits the same file, reviewers cannot see the relevant surface, and there is no seam to unit-test a handler without importing the world.

## What Changes

- Introduce an application package with one FastAPI app factory (`create_app()`) and per-domain routers.
- Extract HTTP handlers into routers by domain: system/setup, lists/items, sync orchestration, collections, images, settings/notifications, logs, analytics, sync-history.
- Move non-HTTP logic out of handlers into dedicated modules (reporting, sync-runner, image service, analytics).
- Reduce `api_server.py` to a thin compatibility entrypoint exposing `app` so the existing `uvicorn api_server:app` command keeps working.
- No HTTP behavior change: paths, methods, and response shapes stay identical.

## Capabilities

### New Capabilities
- `api-server-structure`: a modular FastAPI application — a single app factory, domain routers, thin handlers, and a non-HTTP logic layer — with a stable compatibility entrypoint.

### Modified Capabilities
<!-- openspec/specs/ is empty; no existing capabilities to modify. -->

## Impact

- `api_server.py`: shrinks from one module to an entrypoint shim.
- New modules for routers and services (proposed package: `list_sync/web/` or a top-level `webapp/`).
- `start_api.py`: unchanged externally (`uvicorn api_server:app` still resolves).
- Tests: a route-inventory test asserts the OpenAPI surface is unchanged; extraction is done domain-by-domain.
