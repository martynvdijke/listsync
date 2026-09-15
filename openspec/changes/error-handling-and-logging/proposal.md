## Why

`api_server.py` contains 136 `except Exception` handlers and 29 bare `except:` clauses; `list_sync/main.py` follows the same pattern. Bare and broad catches swallow failures silently, so errors surface as wrong data or a 200 with empty content instead of a clear failure. Meanwhile the codebase has a logging module (`list_sync/utils/logger.py`) yet calls `print()` 113 times in `api_server.py` and 43 times in `list_sync/main.py`. Failures have too many places to hide and operational output is unstructured.

## What Changes

- Eliminate bare `except:` clauses; catch the specific exceptions each site can actually raise.
- Require every broad `except Exception` to log with context and either re-raise or return an explicit error — no silent `pass`.
- Replace `print()` in application code with the module logger.
- Map unhandled errors to correct HTTP status codes at the API boundary rather than returning success with degraded data.
- Ensure startup failures fail loudly instead of continuing in a broken state.

## Capabilities

### New Capabilities
- `error-handling`: explicit, specific, logged error handling with correct HTTP error semantics and no silent failures.

### Modified Capabilities
<!-- openspec/specs/ is empty; no existing capabilities to modify. -->

## Impact

- `api_server.py`: 136 `except Exception` sites and 29 bare excepts reviewed; `print` calls replaced.
- `list_sync/main.py`: same treatment.
- `list_sync/utils/logger.py`: used consistently; may gain a small structured-context helper.
- Tests: error-path tests for representative handlers; startup failure test.
