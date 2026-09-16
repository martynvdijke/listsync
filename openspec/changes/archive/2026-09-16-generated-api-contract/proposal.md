## Why

FastAPI generates an OpenAPI schema for the 90 endpoints for free, but the Nuxt frontend hand-writes every call through `useApiService()` with no generated types. There is no mechanical link between the contract the backend publishes and the shapes the frontend assumes, so drift is inevitable. It is already visible: `composables/useSyncMonitor.ts:149` and `composables/useRealtime.ts:80` both carry `// TODO: Enable when backend implements SSE endpoint`, yet the backend already exposes `/api/sync/status/live` and `/api/logs/stream`.

## What Changes

- Generate TypeScript types (and optionally a typed client) from the FastAPI OpenAPI schema.
- Have the frontend consume the generated types instead of hand-written response shapes.
- Add a CI check that fails when the committed/generated types are stale relative to the backend schema.
- Resolve the two SSE TODOs by wiring the frontend to the existing streaming endpoints (or, if they are genuinely unsuitable, record why and delete the TODOs).

## Capabilities

### New Capabilities
- `api-contract`: a generated, drift-checked TypeScript contract derived from the backend's OpenAPI schema, used by the frontend.

### Modified Capabilities
<!-- openspec/specs/ is empty; no existing capabilities to modify. -->

## Impact

- `listsync-nuxt/composables/useApiService.ts` and stores: consume generated types.
- New generated types file and a generation script (e.g. `openapi-typescript`).
- CI: a drift check comparing regenerated types to what is committed.
- `composables/useSyncMonitor.ts`, `composables/useRealtime.ts`: SSE TODOs resolved.
- Backend: no behavior change; the OpenAPI schema is already produced.
