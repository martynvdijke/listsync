## ADDED Requirements

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
