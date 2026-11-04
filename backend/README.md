# ListSync Go backend

This directory is the first slice of the phased Python-to-Go backend migration.
It is intentionally a **side-by-side service**, not a replacement yet.

The Go process reads the existing SQLite database and serves the read endpoints
the dashboard needs first. Anything it does not implement can be forwarded to
the existing FastAPI process, which lets the frontend switch over without a
big-bang rewrite.

## What works now

| Endpoint | Status |
|---|---|
| `GET /healthz` | Go liveness |
| `GET /api/system/health` | Database + latest-sync health |
| `GET /api/system/database/test` | SQLite connectivity |
| `GET /api/setup/status` | Setup state from `setup_status` / `app_settings` |
| `GET /api/lists` | Lists with display names and Seerr user names |
| `GET /api/lists/debug` | Raw list debug view |
| `GET /api/lists/{type}/{id}/items` | Items for one list, including poster URLs |
| everything else under `/api/**` | Optional proxy to the Python API |

The list-items route accepts full list URLs encoded as one path segment, the
same way the Nuxt client sends them (`%2F`). It parses the raw escaped path so a
URL never gets split into multiple route segments.

## Run locally

```bash
cd backend
go run ./cmd/listsync
```

Defaults:

- bind: `127.0.0.1:4222`
- database: `data/list_sync.db`
- Python fallback: disabled

Point it at a copy of the real database first:

```bash
LISTS_SYNC_DB=/config/listsync/list_sync.db \
LISTS_SYNC_PORT=4399 \
go run ./cmd/listsync
```

Run it beside the Python API with fallback enabled:

```bash
# Python API on 4223, Go API on 4222
LISTS_SYNC_DB=/config/listsync/list_sync.db \
LISTS_SYNC_LEGACY_API_URL=http://127.0.0.1:4223 \
go run ./cmd/listsync
```

The Nuxt proxy already targets `127.0.0.1:4222`, so this is the shape of a
gradual cutover: point the frontend at Go, let Go serve the migrated endpoints,
and forward the rest to Python.

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `LISTS_SYNC_HOST` | `127.0.0.1` | Bind address |
| `LISTS_SYNC_PORT` | `4222` | Bind port |
| `LISTS_SYNC_DB` | `data/list_sync.db` | Existing SQLite database |
| `LISTS_SYNC_ENV_FILE` | `.env` | Used by `/api/setup/status` |
| `LISTS_SYNC_API_TOKEN` | unset | Optional bearer token, same rule as Python |
| `CORS_ALLOWED_ORIGINS` | unset | Comma-separated opt-in browser origins |
| `LISTS_SYNC_LEGACY_API_URL` | unset | FastAPI base URL for unimplemented routes |

`/api/system/health` stays public so container health checks keep working when
a token is configured.

## Test

```bash
cd backend
go test ./...
```

The store tests build a temporary SQLite database and exercise the same tables
the Python service owns. The API tests use a fake store and a fake legacy
server, so they do not need the real 29 MB database.

## Build the image

```bash
docker build -t listsync-go:dev backend
```

The image is a static, CGO-free Go binary on distroless. It is not wired into
the main `Dockerfile` or `docker-compose.yml` yet; that happens after the
remaining API surface is ported.

## Migration plan

1. **Read-only API slice** (this change): lists, list items, health, setup state.
2. **Sync history and analytics reads**: port the reporting queries and add
   parity tests against the Python response shapes.
3. **Writes and sync control**: list add/delete/user assignment, interval,
   settings, and sync trigger/cancel.
4. **Providers**: port HTTP/JSON providers first. Keep IMDb on Python/Selenium
   until a Go browser path survives IMDb's AWS WAF reliably.
5. **Frontend cutover**: switch the Nuxt proxy to the Go service, leave the
   Python API behind the fallback URL, then remove routes one by one.
6. **Package**: embed the static Nuxt build in the Go binary or serve it from
   the same process, and retire the Node runtime.

## Deliberate limitations

- No schema creation or migrations. The Python service still owns the schema.
- No write endpoints yet.
- No sync worker yet.
- No IMDb scraping in Go. That is the highest-risk part and stays in Python for
  now.
- The legacy proxy is a migration tool, not a long-term architecture.
