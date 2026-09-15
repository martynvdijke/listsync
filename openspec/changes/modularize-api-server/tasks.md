## 1. Inventory and seam-finding

- [ ] 1.1 Extract the full route list (`grep '^@app\.' api_server.py`) and assign each of the 90 endpoints to a domain
- [ ] 1.2 Capture the current OpenAPI schema (`/openapi.json`) as the equivalence baseline
- [ ] 1.3 Identify non-HTTP logic blocks (log parsing ~201–1724, analytics ~5888–6478, sync runner ~4050/5475, image proxy ~8359–8693) and their domain modules

## 2. Establish the package skeleton

- [ ] 2.1 Create the application package with `create_app()`, router registration, CORS middleware, and startup hook
- [ ] 2.2 Add a compatibility shim so `api_server:app` still resolves
- [ ] 2.3 Add a route-inventory test comparing the app's schema to the baseline

## 3. Extract routers incrementally

- [ ] 3.1 Extract system/setup routes
- [ ] 3.2 Extract lists/items routes
- [ ] 3.3 Extract sync orchestration routes and move the subprocess runner into a service module
- [ ] 3.4 Extract collections routes
- [ ] 3.5 Extract images routes and move the image service into a module
- [ ] 3.6 Extract settings/notifications routes
- [ ] 3.7 Extract logs routes (live tail / SSE)
- [ ] 3.8 Extract analytics routes and move `process_*` aggregation into an analytics module
- [ ] 3.9 Extract sync-history routes

## 4. Verify and validate

- [ ] 4.1 Confirm no route decorators remain in the shim
- [ ] 4.2 Run `python tests/run_all.py` and fix failures
- [ ] 4.3 Diff the OpenAPI schema against the baseline and confirm equivalence
- [ ] 4.4 Run `openspec validate modularize-api-server --strict`
