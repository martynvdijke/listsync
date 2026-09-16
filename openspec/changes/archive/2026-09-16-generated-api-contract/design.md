## Context

The backend is FastAPI (`app = FastAPI(...)` in `api_server.py`) and therefore already serves `/openapi.json`. The frontend is Nuxt 3 (`listsync-nuxt/`) and defines every call in `composables/useApiService.ts`, `composables/useApi.ts`, and the Pinia stores. No generated types exist anywhere under `listsync-nuxt/` (searched; none found). Two composables explicitly note a missing backend streaming endpoint that in fact exists: `useSyncMonitor.ts:149` and `useRealtime.ts:80`. That comment surviving alongside `/api/sync/status/live` and `/api/logs/stream` is the drift in miniature.

## Goals / Non-Goals

**Goals:**
- Backend schema is the contract; frontend types are derived, not guessed.
- Contract changes become visible (CI fails on drift).
- Remove stale streaming TODO comments.

**Non-Goals:**
- Rewriting the frontend API layer from scratch or adopting a different HTTP client.
- Changing backend endpoints or adding new ones.
- Redesigning the Pinia stores.

## Decisions

### D1: `openapi-typescript` for types; typed client optional

Generate plain TypeScript types from the schema and use them in the existing `useApiService()` wrappers. A full generated client (`openapi-fetch`) is a nicety, not required for drift detection.

*Rejected:* Hand-maintained types with a comment "keep in sync" — that is what exists now and it drifted.

### D2: Commit the generated types and drift-check in CI

Committing the artifact keeps builds hermetic and makes drift a visible diff. CI regenerates and fails if there is a diff. The alternative (generate only at build time) hides drift until a build breaks for a different reason.

### D3: Generation reads the schema without running the full server

Prefer producing the OpenAPI schema from the app object in a small script over requiring a live server, so CI does not need to boot the service and its dependencies.

### D4: Resolve the SSE TODOs as part of this change

Leaving known-stale TODOs in place while claiming a contract change would be inconsistent. Either wire the streaming endpoints or document a concrete blocker.

## Risks / Trade-offs

- [Generated types are verbose / noisy in diffs] → Commit them; the diff is the point. Split the generation commit from logic commits.
- [The schema is huge (90 endpoints) and typechecking slows down] → `vue-tsc` on the Nuxt app is already the right scope; measure and exclude node_modules.
- [Some endpoints have loose `Dict[str, Any]` response models] → Generated types will be weak there; improve Pydantic response models where it matters, tracked as follow-up rather than blocking.
- [Bootless schema generation misses the startup-registered routes] → Route registration happens at import; verify the generated path count matches the live server.

## Migration Plan

1. Add the generator and generation script (section 1).
2. Adopt types in `useApiService`/stores (section 2).
3. Resolve streaming TODOs (section 3).
4. Add the CI drift check (section 4).
Rollback: the generation script and CI check are independent of runtime behavior; reverting removes the check without affecting the app.

## Open Questions

- Where should the generated file live — `listsync-nuxt/types/api.ts` (committed) and is that acceptable to the team?
- Do we also want a typed runtime client (`openapi-fetch`) now, or only types?
- Are the existing `/api/sync/status/live` and `/api/logs/stream` endpoints sufficient for what `useSyncMonitor`/`useRealtime` need, or do they need shape changes?
