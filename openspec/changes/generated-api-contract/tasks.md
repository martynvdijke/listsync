## 1. Stand up generation

- [ ] 1.1 Choose the generator (`openapi-typescript` for types, optionally `openapi-fetch` for a typed client) and add it to `listsync-nuxt`
- [ ] 1.2 Add a script that fetches/builds the OpenAPI schema from the FastAPI app and generates types
- [ ] 1.3 Decide where the generated artifact lives and whether it is committed

## 2. Adopt the types

- [ ] 2.1 Wire `useApiService.ts` and `useApi.ts` to the generated types
- [ ] 2.2 Replace hand-written response types in the Pinia stores (`lists`, `users`, `stats`, `sync`, `collections`, `system`)
- [ ] 2.3 Add a typecheck step (`vue-tsc` or equivalent) if not already present

## 3. Resolve streaming

- [ ] 3.1 Confirm `/api/sync/status/live` and `/api/logs/stream` satisfy the needs behind `useSyncMonitor.ts:149` and `useRealtime.ts:80`
- [ ] 3.2 Wire the frontend to the streaming endpoints, or record the blocker and remove the TODOs
- [ ] 3.3 Verify the live update path works end to end

## 4. Enforce drift

- [ ] 4.1 Add a CI step that regenerates types and fails on `git diff`
- [ ] 4.2 Verify a schema change without regeneration fails CI

## 5. Verify and validate

- [ ] 5.1 Build the frontend (`nuxt build`) and typecheck
- [ ] 5.2 Run `openspec validate generated-api-contract --strict`
