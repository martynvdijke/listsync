## Context

Deployment surface today: `Dockerfile` (3 `FROM` stages, 17 KB) used by `docker-compose.local.yml`; `Dockerfile.core` (1 stage) used by `docker-compose.core.yml`; `docker-compose.yml` runs the published `ghcr.io/woahai321/list-sync:main` image. Dependency manifests: `pyproject.toml` (poetry, authoritative for the package), `requirements.txt` (10 lines), `api_requirements.txt` (25 lines), `tests/requirements.txt` (22 lines). Entry scripts: `start_api.py` (calls `uvicorn "api_server:app"`), `start-core.sh/.ps1`, `stop-core.sh/.ps1`. Env examples: `.env.example`, `.env.core`. `development-files/` holds ~20 one-off scripts and analysis files. Dead scaffold: `listsync-nuxt/app/app.vue` is tracked, is the only file under `app/`, and is shadowed by the real root `listsync-nuxt/app.vue` (no `srcDir` override in `nuxt.config.ts`).

## Goals / Non-Goals

**Goals:**
- One documented path per mode; no competing duplicates.
- One dependency source of truth.
- No dead files in the entry surface.

**Non-Goals:**
- Changing runtime behavior or the published image's content.
- Replacing Docker or Compose.
- Rewriting CI beyond install-command updates.

## Decisions

### D1: Keep full vs core as legitimate modes, document them; drop overlapping variants

Full (`Dockerfile`) and core (`Dockerfile.core`) are real product modes (web UI vs minimal footprint). The redundancy is in the wrapper scripts and, potentially, in compose variants that express the same mode. Keep one compose file per mode; delete any that merely restate another.

*Rejected:* Collapsing to a single Dockerfile — the core image exists specifically to avoid shipping the web UI.

### D2: `pyproject.toml` is the dependency source of truth

Runtime deps live in `pyproject.toml`. Requirement files, if the Docker build needs a flat list, are generated from it and clearly marked; otherwise removed. Four hand-maintained manifests will drift.

### D3: Compose is the portable start path; remove duplicative wrappers

`docker compose` works on all platforms. Shell/PowerShell wrappers that only set a compose file and print messages are removed unless they add behavior (e.g. env validation). If cross-platform convenience is still wanted, document the one-liner.

### D4: Delete the dead Nuxt scaffold

`app/app.vue` renders `<NuxtWelcome />` and nothing references it; root `app.vue` is the real shell. Removing it reduces the "which app.vue?" confusion. If a future Nuxt 4 migration wants `srcDir: 'app'`, that migration creates its own file.

### D5: Prune `development-files/` from the deployable surface

One-off analysis/prototype scripts are not part of the product. Remove them or move them out of the tracked repo surface; keep anything genuinely useful as a documented tool.

## Risks / Trade-offs

- [Removing a compose file someone relies on] → Document the canonical replacement in the same change; check README/GitHub templates for references first.
- [Docker build breaks when switching dependency install] → Build both images in CI after the change; keep the generated requirements if the build needs a flat file.
- [Windows users lose the `.ps1` convenience] → Document the `docker compose` command; wrappers that only wrap it are not worth maintaining in two languages.
- [Deleting the wrong `app.vue`] → Verify Nuxt's resolved `srcDir`/root before deletion (no `srcDir` in `nuxt.config.ts` ⇒ root `app.vue` is used) and run `nuxt build` in 6.2.
- [`.env.core` and `.env.example` diverge from the loader] → 4.2 cross-checks against `list_sync/config.py`.

## Migration Plan

1. Inventory and map (section 1).
2. Reduce compose/Dockerfiles (section 2).
3. Unify dependencies (section 3).
4. Consolidate scripts/env (section 4).
5. Remove dead files (section 5).
6. Build both images and validate (section 6).
Rollback: each reduction is a separate commit; restore a deleted file from git if a mode is found to be in use.

## Open Questions

- Are `requirements.txt` and `api_requirements.txt` used by the Docker build directly, or stale copies of `pyproject`? 1.3 answers this and decides generate-vs-delete.
- Does the published image build from `Dockerfile` (CI `docker-build.yml`)? Confirm before editing.
- Is `start_api.py` the supported non-Docker entry point, or is `list_sync.main`/`uvicorn` the documented one?
