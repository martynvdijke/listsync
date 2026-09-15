## 1. Inventory

- [ ] 1.1 Enumerate all 29 bare `except:` sites in `api_server.py` (and any in `list_sync/`)
- [ ] 1.2 Enumerate the 136 `except Exception` sites and tag each: log-and-reraise, convert-to-error, or genuinely-safe-ignore
- [ ] 1.3 Inventory `print(` calls in application paths (`api_server.py`, `list_sync/main.py`)

## 2. Fix bare excepts

- [ ] 2.1 Replace each bare `except:` with the specific exception(s) it can raise
- [ ] 2.2 Where the intent was "ignore anything", make the narrow catch explicit and add a comment explaining why

## 3. Fix broad excepts

- [ ] 3.1 Add contextual logging to each `except Exception` that presently swallows
- [ ] 3.2 Remove silent `pass` bodies; re-raise or return an explicit error
- [ ] 3.3 Add error-path tests for representative handlers

## 4. Replace print with logging

- [ ] 4.1 Replace `print(` in `api_server.py` with `list_sync.utils.logger`
- [ ] 4.2 Replace `print(` in `list_sync/main.py`
- [ ] 4.3 Confirm startup and sync paths produce structured log output

## 5. Error semantics

- [ ] 5.1 Map unhandled handler failures to 5xx responses
- [ ] 5.2 Make startup fail loudly on required-resource initialization failure
- [ ] 5.3 Add a startup-failure test

## 6. Verify and validate

- [ ] 6.1 Run `python tests/run_all.py` and fix failures
- [ ] 6.2 Run `openspec validate error-handling-and-logging --strict`
