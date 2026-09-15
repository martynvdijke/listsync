## Why

There are too many ways to build, configure, and run the same system: two Dockerfiles (`Dockerfile` 3 stages, `Dockerfile.core` 1), three compose files (`docker-compose.yml` image-based, `docker-compose.local.yml` builds `Dockerfile`, `docker-compose.core.yml` builds `Dockerfile.core`), four Python dependency manifests (`pyproject.toml`, `requirements.txt`, `api_requirements.txt`, `tests/requirements.txt`), cross-platform start/stop scripts (`start-core.sh/.ps1`, `stop-core.sh/.ps1`, `start_api.py`), two env examples (`.env.example`, `.env.core`), and a 20-script `development-files/` directory. Add a dead tracked Nuxt scaffold (`listsync-nuxt/app/app.vue` — the only file in `app/`, shadowed by the real root `app.vue`) and the entry surface is confusing enough that contributors guess.

## What Changes

- Define one documented canonical path per deployment mode (core-only vs full/local vs published image).
- Reduce the compose files to the minimum that expresses those modes, and make each Dockerfile's purpose explicit.
- Establish a single source of truth for Python dependencies; the others become generated or removed.
- Keep one cross-platform start/stop path (compose is the portable one) and remove duplicated shell/PowerShell wrappers.
- Remove the dead Nuxt scaffold and prune one-off scripts from `development-files/`.
- Align `.env.example` / `.env.core` so there is one reference env file per mode.

## Capabilities

### New Capabilities
- `deployment`: a minimal, documented set of build, configuration, and run entry points — one canonical path per mode and one dependency manifest.

### Modified Capabilities
<!-- openspec/specs/ is empty; no existing capabilities to modify. -->

## Impact

- `Dockerfile`, `Dockerfile.core`, `docker-compose*.yml`, `start-core.sh/.ps1`, `stop-core.sh/.ps1`, `start_api.py`, `requirements.txt`, `api_requirements.txt`, `.env.example`, `.env.core`.
- `development-files/` (prune).
- `listsync-nuxt/app/app.vue` (delete dead scaffold).
- `Dockerfile` build must still produce the published image; `docker-compose.core.yml` and `docker-compose.local.yml` must still work.
