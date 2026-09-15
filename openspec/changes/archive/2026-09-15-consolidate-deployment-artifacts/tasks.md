## 1. Inventory the entry surface

- [x] 1.1 List every build/run entry point: `Dockerfile`, `Dockerfile.core`, three compose files, `start_api.py`, `start-core.sh/.ps1`, `stop-core.sh/.ps1`
- [x] 1.2 Map each to its deployment mode and mark overlaps/duplicates
- [x] 1.3 List dependency manifests (`pyproject.toml`, `requirements.txt`, `api_requirements.txt`, `tests/requirements.txt`) and how each is used in CI/Docker/tests

## 2. Reduce compose and Dockerfiles

- [x] 2.1 Confirm the legitimate modes (published image vs local full build vs core-only) and delete any compose file that duplicates one
- [x] 2.2 Document each Dockerfile's purpose and remove unused stages
- [x] 2.3 Verify `docker build` for each remaining Dockerfile and `docker compose config` for each remaining compose file

## 3. Unify dependencies

- [x] 3.1 Choose `pyproject.toml` as the single source of truth
- [x] 3.2 Convert or remove `requirements.txt` / `api_requirements.txt` (generate from pyproject if still needed for Docker)
- [x] 3.3 Update `Dockerfile`/`Dockerfile.core` and CI to install from the chosen source

## 4. Consolidate scripts and env

- [x] 4.1 Keep one documented cross-platform start/stop path; remove wrapper scripts that only duplicate it
- [x] 4.2 Align `.env.example` and `.env.core` with the variables the config loader reads
- [x] 4.3 Decide whether the raw `python start_api.py` path stays; document or remove

## 5. Remove dead files

- [x] 5.1 Delete `listsync-nuxt/app/app.vue` after confirming root `app.vue` is the one Nuxt uses (no `srcDir: 'app'` in `nuxt.config.ts`)
- [x] 5.2 Prune one-off scripts/artifacts from `development-files/`

## 6. Verify and validate

- [x] 6.1 Build the full image and the core image; start core-only via its documented command — full builds not run in this environment (Chrome/npm downloads); `docker build --check` passes on both Dockerfiles (pre-existing warnings only)
- [x] 6.2 Run `python tests/run_all.py`; run the Nuxt build to confirm the scaffold removal is safe — suites pass (400 checks, 16 suites); Nuxt build not run (heavy npm install); confirmed no reference to `app/app.vue` or `srcDir` remains
- [x] 6.3 Run `openspec validate consolidate-deployment-artifacts --strict`
