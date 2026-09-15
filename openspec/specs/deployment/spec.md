# deployment Specification

## Purpose
TBD - created by archiving change consolidate-deployment-artifacts. Update Purpose after archive.
## Requirements
### Requirement: One canonical path per deployment mode

Each supported deployment mode SHALL have exactly one documented canonical command and configuration.

#### Scenario: Modes are enumerated

- **WHEN** reading the deployment documentation
- **THEN** each mode (full web UI, core-only, published image) has one documented build/run path

#### Scenario: Redundant variants removed

- **WHEN** inspecting compose files and start scripts
- **THEN** no two files express the same mode in competing ways

### Requirement: Single dependency manifest

Python dependencies SHALL have one source of truth; any other manifest is generated from it or removed.

#### Scenario: Manifest agrees with itself

- **WHEN** comparing the runtime dependencies across `pyproject.toml` and any remaining requirements file
- **THEN** they do not contradict, and the generated/derived file's origin is documented

#### Scenario: Reproducible install

- **WHEN** a fresh environment installs dependencies using the documented command
- **THEN** installation succeeds from the single source of truth

### Requirement: No dead entry points or scaffolds

The repository SHALL NOT contain dead entry-point files or unused framework scaffolds.

#### Scenario: Dead Nuxt scaffold removed

- **WHEN** inspecting `listsync-nuxt/app/`
- **THEN** the unused `app/app.vue` scaffold (shadowed by the root `app.vue`) is gone, or the directory is actually used as configured in `nuxt.config.ts`

#### Scenario: No duplicate start/stop wrappers

- **WHEN** inspecting start/stop scripts
- **THEN** there is one documented portable path, and platform-specific wrappers that merely duplicate it are removed unless they add real behavior

### Requirement: Environment examples are aligned

There SHALL be one reference environment file per deployment mode, and it SHALL reflect the variables the application actually reads.

#### Scenario: Env files match the code

- **WHEN** comparing `.env.example` (and the core variant) against the configuration loader
- **THEN** documented variables match what the app reads, with no stale entries

### Requirement: Development scratch is not shipped

One-off development scripts and analysis artifacts SHALL NOT remain in the application's tracked entry surface.

#### Scenario: Scratch is pruned or relocated

- **WHEN** inspecting `development-files/`
- **THEN** one-off scripts are removed or clearly isolated from the deployable surface

