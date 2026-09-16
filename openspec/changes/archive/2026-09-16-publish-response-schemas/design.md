## Context

`generated-api-contract` shipped a committed, drift-checked type artifact, but every route's 200
response is `{}` because handlers have no return annotation and return `Dict[str, Any]`. The prior
change explicitly deferred this ("Notes on scope": 2.2 scoped down because responses resolve to
`unknown`). The mechanism to fix it without behavior change is FastAPI's per-route `responses`
mapping, which contributes a schema to `components.schemas` and a `$ref` under the 200 content while
leaving runtime serialization untouched.

## Goals / Non-Goals

**Goals:**
- The frontend-consumed JSON endpoints publish concrete 200 schemas.
- The frontend response types derive from those schemas.
- Zero runtime change and a green drift check.

**Non-Goals:**
- Adding or reshaping endpoints.
- Modelling all 89 operations; non-JSON endpoints (streaming, image proxy, file downloads) and
  routes the frontend never calls stay as-is.
- Switching to `openapi-fetch` or rewriting the API layer.

## Decisions

### D1: `responses={200: {"model": ...}}`, not `response_model`

`response_model` would serialize/validate at runtime and risk changing output. The `responses`
mapping is documentation-only: it declares the schema for OpenAPI but FastAPI does not validate or
re-serialize the returned dict. Verified with a spike before this change.

### D2: One `list_sync/web/schemas.py` for the new models

Models are shared across routers (`collections`, `lists`, `system`, `sync`, `analytics`). A single
leaf module avoids cross-router imports and cycles. The existing analytics models stay in
`services/analytics.py`.

### D3: Model the frontend-consumed endpoints, not all 89

Coverage is scoped to the JSON endpoints the frontend actually calls through `useApiService()` (the
six stores plus their service methods). Modelling unused routes adds schema surface with no consumer
and no test value. Broader coverage is a follow-up.

### D4: Preserve exported type names, re-point them at generated schemas

`types/index.ts` is imported by many components. Redefining an interface as a type alias to the
generated component (`export type List = components['schemas']['ListSummary']`) keeps every importer
compiling while making the generated shape authoritative. Hand-written shapes are deleted only where
an alias replaces them.

## Risks / Trade-offs

- [Variable-shape 200s: live sync status has running/idle/error variants; Overseerr status has
  connected/disconnected] → Use optional fields in one model per route; OpenAPI has a single 200
  schema and the frontend already narrows on `is_running`/`isConnected`.
- [Nested generated names may not match hand-written names] → Inspect the generated artifact before
  writing aliases; alias by generated name.
- [Adding `responses` changes the schema and trips the drift check] → Regenerate and commit
  `types/api.ts` in the same change.

## Migration Plan

1. Define models and attach them to the handlers (section 1).
2. Regenerate and commit the artifact (section 2).
3. Adopt aliases in types and stores (section 3).
4. Verify tests, lint, typecheck, build, drift (section 4).

Rollback: removing the `responses` mappings and regenerating reverts to the current schema; the
frontend aliases are additive.
