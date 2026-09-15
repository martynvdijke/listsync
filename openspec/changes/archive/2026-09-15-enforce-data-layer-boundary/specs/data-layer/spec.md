## ADDED Requirements

### Requirement: All application database access is mediated by the data layer

Modules outside `list_sync/database.py` SHALL NOT open connections to the application database or execute SQL against it; they SHALL call named functions in the data layer.

#### Scenario: No raw connections in the HTTP layer

- **WHEN** searching non-DAL application modules for `sqlite3.connect` against `DB_FILE`
- **THEN** no matches remain in `api_server.py` or other non-DAL modules

#### Scenario: No inline SQL in handlers

- **WHEN** reading route handlers
- **THEN** persistence is performed by calling DAL functions, not by building SQL inline

### Requirement: A single canonical list-id normalizer

The application SHALL have exactly one `normalize_list_id` implementation, in the data layer, and all callers SHALL use it.

#### Scenario: Duplicate normalizer removed

- **WHEN** searching the codebase for `def normalize_list_id`
- **THEN** exactly one definition exists (in `list_sync/database.py`) and `api_server.py` imports it

#### Scenario: Identifiers normalize consistently

- **WHEN** a list is looked up using either a bare id or a pasted URL
- **THEN** both forms resolve to the same stored row regardless of which module performs the lookup

### Requirement: Consistent connection and transaction handling

The data layer SHALL provide a shared connection/transaction helper so commit, rollback, and close behavior is applied uniformly.

#### Scenario: Failures roll back

- **WHEN** a DAL mutation raises partway through
- **THEN** the transaction is rolled back and the connection is closed, without leaving a partially written row

### Requirement: Behavior-preserving migration

Moving SQL into the data layer SHALL NOT change query results; each migrated query SHALL return the same data as before.

#### Scenario: Migrated query returns identical results

- **WHEN** a handler's inline SQL is replaced by a DAL function
- **THEN** tests over representative data show the same rows, ordering, and field values as before
