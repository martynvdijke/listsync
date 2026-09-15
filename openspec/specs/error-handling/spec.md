# error-handling Specification

## Purpose
TBD - created by archiving change error-handling-and-logging. Update Purpose after archive.
## Requirements
### Requirement: No bare exception handlers

The codebase SHALL NOT contain bare `except:` clauses; each handler SHALL catch the specific exception types the guarded code can raise.

#### Scenario: Bare excepts are gone

- **WHEN** searching application modules for `except:` with no exception type
- **THEN** no matches remain

#### Scenario: Missing catch is explicit

- **WHEN** a site previously used a bare except to catch anything
- **THEN** it either catches the specific expected exceptions or lets unexpected exceptions propagate

### Requirement: No silent failures

A broad `except Exception` MAY remain only where it logs with context and either re-raises or returns an explicit error result; it SHALL NOT `pass` silently.

#### Scenario: Broad catch logs and re-raises

- **WHEN** a broad catch handles an unexpected error
- **THEN** it emits a log record with enough context to diagnose the failure and does not discard the error silently

#### Scenario: No silent pass

- **WHEN** auditing `except` bodies
- **THEN** none consist solely of `pass` (or of nothing) without a logged, justified reason

### Requirement: Application logging uses the logger

Application code SHALL log through `list_sync/utils/logger.py`; `print()` SHALL NOT be used for operational or diagnostic output in application paths.

#### Scenario: No print in application code

- **WHEN** searching `api_server.py` and `list_sync/` for `print(`
- **THEN** no operational `print` calls remain (developer-only scripts excepted and out of application paths)

#### Scenario: Log records carry context

- **WHEN** an error is logged
- **THEN** the record includes the operation and relevant identifiers, not just the exception string

### Requirement: Correct HTTP error semantics

API handlers SHALL return an appropriate error status when an operation fails, rather than returning success with degraded or empty data.

#### Scenario: Failed operation returns an error status

- **WHEN** a handler's underlying operation fails unexpectedly
- **THEN** the response is a 5xx (or a specific 4xx for client errors), not a 200 with empty content

#### Scenario: Unexpected errors surface

- **WHEN** an unhandled exception escapes a handler
- **THEN** it is logged and the client receives an error response

### Requirement: Startup fails loudly

If the application cannot initialize a required resource, startup SHALL fail rather than continue in a broken state.

#### Scenario: Initialization failure stops startup

- **WHEN** a required resource (database, configuration) cannot be initialized
- **THEN** startup raises/logs an error and does not serve requests as if healthy

