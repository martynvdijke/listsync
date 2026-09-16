# api-contract Specification

## Purpose
TBD - created by archiving change generated-api-contract. Update Purpose after archive.
## Requirements
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

### Requirement: JSON responses publish a schema

Backend routes that return JSON to the frontend SHALL declare a Pydantic response model in their
OpenAPI `responses` mapping, so the generated contract exposes a concrete 200 schema. Declaring the
model SHALL NOT change runtime serialization.

#### Scenario: Modelled response is no longer empty

- **WHEN** the OpenAPI schema is exported
- **THEN** each modelled route's 200 response content references a named component schema instead of
  an empty schema

#### Scenario: Runtime output is unchanged

- **WHEN** the existing backend test suite runs after the models are declared
- **THEN** every check passes and the returned response bodies are unchanged

### Requirement: Frontend response types derive from generated schemas

Once a route publishes a response model, the frontend type for that response SHALL derive from the
generated contract; the hand-written interface SHALL be replaced by an alias to the generated shape.

#### Scenario: Store consumes the generated type

- **WHEN** reading the store or composable for a modelled endpoint
- **THEN** its response type resolves to the generated schema rather than the hand-written fallback

#### Scenario: Contract drift stays caught

- **WHEN** types are regenerated from the updated schema and committed
- **THEN** the CI drift check passes and a later schema change without regeneration still fails it

