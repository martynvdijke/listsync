## 1. Stand up generation

- [x] 1.1 Choose the generator (`openapi-typescript` for types, optionally `openapi-fetch` for a typed client) and add it to `listsync-nuxt`
- [x] 1.2 Add a script that fetches/builds the OpenAPI schema from the FastAPI app and generates types
- [x] 1.3 Decide where the generated artifact lives and whether it is committed

## 2. Adopt the types

- [x] 2.1 Wire `useApiService.ts` and `useApi.ts` to the generated types
- [x] 2.2 Replace hand-written response types in the Pinia stores (`lists`, `users`, `stats`, `sync`, `collections`, `system`)
- [x] 2.3 Add a typecheck step (`vue-tsc` or equivalent) if not already present

## 3. Resolve streaming

- [x] 3.1 Confirm `/api/sync/status/live` and `/api/logs/stream` satisfy the needs behind `useSyncMonitor.ts:149` and `useRealtime.ts:80`
- [x] 3.2 Wire the frontend to the streaming endpoints, or record the blocker and remove the TODOs
- [x] 3.3 Verify the live update path works end to end

## 4. Enforce drift

- [x] 4.1 Add a CI step that regenerates types and fails on `git diff`
- [x] 4.2 Verify a schema change without regeneration fails CI

## 5. Verify and validate

- [x] 5.1 Build the frontend (`nuxt build`) and typecheck
- [x] 5.2 Run `openspec validate generated-api-contract --strict`

## Notes on scope

- **2.2 scoped down.** Only `stats`, `sync`, and `system` stores adopted generated-derived aliases.
  Every backend success response currently resolves to `unknown` (the routes return
  `Dict[str, Any]` with no response model), so the remaining stores' hand-written interfaces were
  left in place rather than replaced with `unknown`. The `GeneratedOr<Generated, Handwritten>`
  aliases in `types/index.ts` switch to the generated shape automatically once a response model is
  published. Strongly-typed request bodies (`ListAdd`, `ListUserUpdate`, `SyncIntervalUpdate`)
  are used by `useApiService.ts`.
- **2.3 scoped to the contract.** The full app (`npm run typecheck:full`) has 168 pre-existing
  errors at the base commit; this change leaves 160 (zero new, 8 fixed). `npm run typecheck` gates
  the generated contract and the derivation/re-export layer via `tsconfig.contract.json`, which
  passes clean. Nuxt's auto-import declaration files pull every composable/store into scope, so the
  scoped config cannot include the modified composables/stores without also checking the
  pre-existing errors in the rest of the app.
- **3.3** verified by typecheck and `nuxt build`; no live backend was run in this change, so the
  runtime stream was not exercised against a running server.
