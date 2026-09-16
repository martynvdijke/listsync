## Why

The generated TypeScript contract exists and is drift-checked, but every backend route returns
`Dict[str, Any]` with no response model, so all 200 responses resolve to `unknown` in the generated
schema. That is exactly why the previous change had to leave the hand-written response interfaces in
place: the "generated artifact is the source of truth" requirement is only met for request bodies and
paths, not for responses. Publishing response models closes that gap without touching runtime
behavior.

## What Changes

- Declare Pydantic response models for the JSON endpoints the frontend consumes, attached through
  FastAPI's documentation-only `responses={200: {"model": ...}}` mapping so runtime serialization is
  unchanged.
- Regenerate `listsync-nuxt/types/api.ts` from the enriched schema.
- Replace the remaining hand-written response interfaces in `listsync-nuxt/types/index.ts` with
  aliases to the generated schemas, so `GeneratedOr` resolves to the generated branch.
- Keep the existing CI drift check and typecheck green.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `api-contract`: backend JSON responses gain published schemas, and the frontend response types
  derive from the generated contract instead of hand-written interfaces.

## Impact

- `list_sync/web/schemas.py` (new): response models.
- `list_sync/web/routers/*.py`: 200-response model declarations on the frontend-consumed handlers.
- `listsync-nuxt/types/api.ts` (regenerated), `listsync-nuxt/types/index.ts` (aliases).
- `listsync-nuxt/composables/useApiService.ts` and the `lists`/`users`/`collections` stores: consume
  the aliases.
- CI: the existing `openapi-contract` drift job must stay green.
- Backend runtime behavior: none. No endpoint is added, removed, or re-shaped.
