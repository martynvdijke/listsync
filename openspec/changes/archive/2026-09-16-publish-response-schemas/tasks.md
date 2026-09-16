## 1. Publish response models

- [x] 1.1 Define Pydantic response models in `list_sync/web/schemas.py` for the JSON endpoints the frontend consumes
- [x] 1.2 Attach `responses={200: {"model": ...}}` to each of those route handlers
- [x] 1.3 Confirm runtime behavior is unchanged (test suite) and the 200 schemas are now concrete

### Notes (1.x)

- `list_sync/web/schemas.py` holds 30 models and a `response(model)` helper
  (`{200: {"model": model, "description": ...}}`). Models are documentation-only: no route sets
  `response_model`, so serialization is untouched.
- `responses=response(...)` attached to 22 handlers: lists 5, system 6, sync 5, collections 5,
  analytics 1 (`get_sync_stats`). Before: 5 component schemas, every 200 body `{}`. After: 35
  component schemas, the 22 routes' 200 content `$ref`s a named schema (all other routes untouched).
- Runtime equivalence: `python3 tests/run_all.py` → 634 checks across 20 suites, all ok; route
  inventory/OpenAPI path+operationId baseline test passes (`tests/test_route_inventory.py`).
- Variable-shape responses (live sync status, Overseerr status, cancel) use one model with optional
  fields, as designed.

## 2. Regenerate the contract

- [x] 2.1 Regenerate `listsync-nuxt/openapi.json` and `listsync-nuxt/types/api.ts`
- [x] 2.2 Inspect the generated component names for the new models
- [x] 2.3 Commit the regenerated artifact so the drift check stays green

### Notes (2.x)

- `npm run openapi` → 85 paths, 89 operations, 35 component schemas; openapi-typescript 7.13.0.
- Generated names match the models (`ListsResponse`, `SyncStatsResponse`, `LiveSyncStatusResponse`,
  `CollectionDetail`, `CollectionMovie`, …). Re-running `npm run openapi` produced a byte-identical
  `types/api.ts` (drift check green).

## 3. Adopt the generated types

- [x] 3.1 Replace the hand-written response interfaces in `types/index.ts` with aliases to the generated schemas
- [x] 3.2 Update `useApiService.ts` and the `lists`/`users`/`collections`/`sync` stores to use the aliases
- [x] 3.3 Contract typecheck passes and `typecheck:full` gains no new errors

### Notes (3.x)

- `types/index.ts` now aliases directly (`List = Schemas['ListSummary']`, `SyncStats =
  ApiStatsResponse`, `Collection = Schemas['CollectionDetail']`, `CollectionMovie =
  Schemas['CollectionMovie']`, …) and exposes an `Api*Response` alias per modelled route; the
  `GeneratedOr` fallback helper is gone. Hand-written interfaces remain only for schema-less routes
  (`CollectionSyncResponse`, sync-history, failures, items) and frontend-only shapes (forms, store
  state, UI).
- The `lists`/`users`/`collections`/`sync`/`system`/`stats` stores already consume the service's typed
  return values (`await api.getLists()` etc.) and import the app-facing aliases, so re-pointing the
  aliases adopted them without further store edits. `stores/stats.ts`'s `breakdown` getter fallback
  was corrected to the real shape (`newly_requested`/`already_requested`, not `requested`).
- `useApiService.ts`: 21 methods now declare `Promise<Api*Response>` return types.
- `npm run typecheck` (contract) passes. `typecheck:full` went from 162 pre-existing errors to 140
  (22 resolved, 0 new). The remaining errors are pre-existing (Naive-UI colour unions,
  `services/api.ts`/`useApi.ts` `$fetch` overloads, untyped store getters).

## 4. Verify

- [x] 4.1 `python3 tests/run_all.py` is green
- [x] 4.2 `uvx ruff@0.6.7 check .` and `format --check .` are green
- [x] 4.3 `npm run typecheck` passes and the frontend builds
- [x] 4.4 `npm run openapi` produces no diff (CI drift check green)
- [x] 4.5 `openspec validate publish-response-schemas --strict` passes

### Notes (4.x)

- `python3 tests/run_all.py` → 634 checks, 20 suites, all ok.
- `uvx ruff@0.6.7 check .` → All checks passed; `format --check .` → 77 files already formatted.
- `npm run typecheck` → clean; `npm run build` → successful Nitro/Nuxt production build.
- `npm run openapi` → no diff in `types/api.ts` after regeneration.
- `openspec validate publish-response-schemas --strict` → Change is valid.
