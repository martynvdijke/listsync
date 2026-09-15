## 1. Inventory

- [x] 1.1 Enumerate all 29 bare `except:` sites in `api_server.py` (and any in `list_sync/`)
- [x] 1.2 Enumerate the 136 `except Exception` sites and tag each: log-and-reraise, convert-to-error, or genuinely-safe-ignore
- [x] 1.3 Inventory `print(` calls in application paths (`api_server.py`, `list_sync/main.py`)

## 2. Fix bare excepts

- [x] 2.1 Replace each bare `except:` with the specific exception(s) it can raise
- [x] 2.2 Where the intent was "ignore anything", make the narrow catch explicit and add a comment explaining why

## 3. Fix broad excepts

- [x] 3.1 Add contextual logging to each `except Exception` that presently swallows
- [x] 3.2 Remove silent `pass` bodies; re-raise or return an explicit error
- [x] 3.3 Add error-path tests for representative handlers

## 4. Replace print with logging

- [x] 4.1 Replace `print(` in `api_server.py` with `list_sync.utils.logger`
- [x] 4.2 Replace `print(` in `list_sync/main.py`
- [x] 4.3 Confirm startup and sync paths produce structured log output

## 5. Error semantics

- [x] 5.1 Map unhandled handler failures to 5xx responses
- [x] 5.2 Make startup fail loudly on required-resource initialization failure
- [x] 5.3 Add a startup-failure test

## 6. Verify and validate

- [x] 6.1 Run `python tests/run_all.py` and fix failures
- [x] 6.2 Run `openspec validate error-handling-and-logging --strict`

## Implementation notes

- CLI presentation channel: `list_sync/ui/cli.py`, `list_sync/ui/display.py` and
  `list_sync/main.py` (130 `print()` calls) now write through
  `get_console_logger()` (`list_sync/utils/logger.py`), a message-only stdout
  logger. The diagnostic file logger intentionally blocks the console, so
  routing the CLI through it would have made the tool silent. Output is
  unchanged (ANSI colours preserved).
- `start_api.py` (launcher) also switched to the console logger; its narrow
  best-effort `psutil.NoSuchProcess/AccessDenied` catch now `continue`s with a
  comment instead of silently `pass`ing.
- Library diagnostics (`config.py`, providers, `api/seerr.py`,
  `utils/helpers.py`, `utils/log_rotation.py`) go through per-module
  `logging.getLogger(__name__)`.
- `api_server.py`: unhandled errors now hit a global `@app.exception_handler(Exception)`
  returning 500 (logged server-side); startup re-raises if `init_database()`
  fails; a guarded `logging.basicConfig` makes the new INFO/DEBUG records emit.
- Guarded by the new `tests/test_error_handling.py` (source scan for bare
  excepts / `print(`, 500 mapping, loud startup). Suite total: 404 checks / 17 suites.
