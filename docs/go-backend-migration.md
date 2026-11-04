# Go backend migration

ListSync currently ships one container with three processes: the FastAPI API,
the Nuxt/Nitro frontend, and the Python sync loop, plus Xvfb/Selenium for IMDb.
The Go migration is about reducing runtime complexity and eventually producing
one small binary, not about changing the product.

## Why a phased migration

A big-bang rewrite would put the working sync pipeline at risk. The two largest
risks are:

1. **IMDb scraping.** The Python provider uses SeleniumBase UC mode to get past
   IMDb's AWS WAF challenge. Go browser libraries do not provide the same
   stealth behaviour, so IMDb stays on Python until a replacement is proven.
2. **Response-shape drift.** The Nuxt dashboard consumes many exact JSON shapes.
   Porting endpoints without parity tests would break pages silently.

The Go service therefore starts read-only, beside Python, with a fallback proxy.

## Current slice

`backend/` contains a runnable Go API with:

- `GET /healthz`
- `GET /api/system/health`
- `GET /api/system/database/test`
- `GET /api/setup/status`
- `GET /api/lists`
- `GET /api/lists/debug`
- `GET /api/lists/{type}/{id}/items`
- optional `LISTS_SYNC_LEGACY_API_URL` proxy for every other `/api/**` route

It reads the existing SQLite schema directly. The Python service still owns
schema creation and migrations.

The list-items handler parses `r.URL.EscapedPath()` instead of `r.URL.Path`.
The frontend URL-encodes full list URLs (`%2F`); using the decoded path would
split one list ID into several route segments.

## Phases

### Phase 1 — read-only API slice

Status: implemented in `backend/`.

- Lists, list items, health, setup state.
- Bearer-token parity with the Python API.
- CORS opt-in.
- Legacy reverse proxy for everything not yet ported.
- Unit tests for config, store, routing, auth, CORS, encoded list URLs, and
  fallback proxying.

### Phase 2 — reporting reads

Port sync history, session details, raw logs, stats, activity, failures,
successful, requested, and analytics endpoints. Add golden-response tests that
run the same requests against Python and Go and compare the JSON shape.

### Phase 3 — writes and sync control

Port list add/delete/user assignment, sync interval, settings, setup writes, and
sync trigger/cancel. This is where the Go service stops being read-only and
needs write transactions and process-signalling parity.

### Phase 4 — providers

Port providers in this order:

1. HTTP/JSON providers: TMDB, TVDB, Trakt, MDBList, StevenLu, AniList, Simkl,
   Letterboxd where it is plain HTTP.
2. Collections.
3. IMDb last, and only with a tested browser strategy. Keep the Python scraper
   as a sidecar if necessary.

The provider interface should be defined in Go before porting, with a fixture
test per provider.

### Phase 5 — frontend cutover

- Run Go on `4222` and Python on `4223` with
  `LISTS_SYNC_LEGACY_API_URL=http://127.0.0.1:4223`.
- Point the Nuxt proxy at Go.
- Remove fallback routes as they are ported.
- Keep the same `/api/**` paths so the frontend does not change.

### Phase 6 — packaging

- Build Nuxt as a static SPA.
- Move the Nitro API proxy and OIDC routes to Go, or keep Nitro only for auth
  until the Go auth layer exists.
- Embed the static assets with `go:embed`.
- Serve API and frontend from one Go process.
- Keep a small Python/Selenium sidecar only if IMDb parity requires it.

## Effort estimate

For one experienced Go developer, backend parity plus an embedded static
frontend is roughly **10–16 weeks**. The estimate assumes the existing Nuxt UI
is kept. A full Go UI rewrite adds another 3–5 months and is not recommended.

A cheaper intermediate, if the goal is only fewer runtimes, is to keep Python
and generate a static Nuxt build served by FastAPI. That removes Node but does
not require rewriting the backend.

## Running the current slice

```bash
cd backend
go test ./...
go run ./cmd/listsync
```

See `backend/README.md` for environment variables and the legacy-proxy setup.
