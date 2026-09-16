## ADDED Requirements

### Requirement: TypeScript contract generated from OpenAPI

Frontend API types SHALL be generated from the backend OpenAPI schema rather than written by hand.

#### Scenario: Types are generated

- **WHEN** the generation command runs against the backend schema
- **THEN** a TypeScript types artifact is produced covering the API paths and schemas

#### Scenario: Generated artifact is the source of truth

- **WHEN** a frontend module needs a response or request type
- **THEN** it imports the generated type instead of declaring a hand-written shape

### Requirement: Contract drift fails CI

CI SHALL fail when regenerating the types produces a diff against what is committed.

#### Scenario: Stale types fail the build

- **WHEN** the backend schema changes and the generated types are not regenerated
- **THEN** CI detects the diff and fails

#### Scenario: In-sync types pass

- **WHEN** the backend schema and the generated types agree
- **THEN** the drift check passes

### Requirement: Frontend uses the generated client

The frontend's API calls SHALL be routed through the generated/typed layer so response shapes are checked at build time.

#### Scenario: Typed call sites

- **WHEN** reading `useApiService()` and the stores
- **THEN** calls reference generated types and a response-shape mismatch is a type error

### Requirement: Streaming TODOs resolved

The frontend SHALL either consume the existing SSE/streaming endpoints or explicitly document why it does not, and the stale TODO comments SHALL be removed.

#### Scenario: SSE TODO removed or justified

- **WHEN** searching the frontend for `TODO: Enable when backend implements SSE endpoint`
- **THEN** the TODOs are gone, replaced by working streaming integration or an explicit, dated note explaining the blocker
