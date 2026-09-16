# api-server-structure Specification

## Purpose
TBD - created by archiving change modularize-api-server. Update Purpose after archive.
## Requirements
### Requirement: Domain-based router organization

The API SHALL be organized into FastAPI routers grouped by domain, and no single module SHALL contain the majority of the application's route handlers.

#### Scenario: Routes are grouped by domain

- **WHEN** inspecting the application package
- **THEN** route handlers are separated into routers such as system/setup, lists/items, sync, collections, images, settings, logs, analytics, and sync-history

#### Scenario: No monolith module remains

- **WHEN** counting route decorators per module
- **THEN** no single module contains all 90 endpoints; handlers are distributed across domain modules

### Requirement: Single application factory

The application SHALL be constructed by a single factory (`create_app()`) that registers routers, middleware, and startup hooks, so the app can be instantiated in tests without importing a fully configured global.

#### Scenario: App can be built in a test

- **WHEN** a test imports and calls `create_app()`
- **THEN** a configured FastAPI instance is returned and routes are registered, without starting background sync or binding a port

### Requirement: Thin HTTP handlers

HTTP handlers SHALL validate input, call a domain/service function, and shape the response; they SHALL NOT contain large inline algorithms (log parsing, analytics aggregation, subprocess orchestration).

#### Scenario: Handler delegates logic

- **WHEN** reading any route handler
- **THEN** its non-trivial logic lives in a service or query module, and the handler body is primarily request/response plumbing

### Requirement: Stable entrypoint compatibility

The existing deployment entrypoint SHALL continue to work: `uvicorn api_server:app` MUST resolve to the application.

#### Scenario: Existing start command still works

- **WHEN** the service starts via the current `start_api.py` / `uvicorn api_server:app` command
- **THEN** the application starts unchanged

### Requirement: No observable API behavior change

The refactor SHALL NOT change HTTP behavior; the OpenAPI surface (paths, methods, response schemas) before and after SHALL be equivalent.

#### Scenario: Route inventory is unchanged

- **WHEN** the OpenAPI schema is captured before and after the refactor
- **THEN** the set of paths and methods is identical and every existing test suite passes

