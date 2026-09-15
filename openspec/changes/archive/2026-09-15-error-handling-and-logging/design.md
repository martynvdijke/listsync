## Context

`api_server.py` has 136 `except Exception` and 29 bare `except:` handlers; `list_sync/main.py` is similar. Examples of bare excepts: `api_server.py:307, 878, 1015, 1574, 2029, 2267, 2512, 2689`. Broad catches without logging are how a scrape failure becomes an empty list, or a DB error becomes a 200 with `[]`. Separately, `list_sync/utils/logger.py` exists and is used elsewhere, yet there are 113 `print()` calls in `api_server.py` and 43 in `list_sync/main.py`, so operational output is unstructured and inconsistent.

## Goals / Non-Goals

**Goals:**
- No silent failures: every unexpected error is logged with context.
- Specific catches over catch-all.
- Consistent structured logging instead of `print`.
- Correct HTTP status on failure.

**Non-Goals:**
- Introducing an external logging/observability stack — `list_sync/utils/logger.py` already exists.
- Rewriting every handler into a middleware-based error framework (a small helper is enough).
- Changing success-path behavior.

## Decisions

### D1: Specific exceptions, documented ignores

Bare `except:` catches everything including `KeyboardInterrupt` and `SystemExit`; each is replaced with the actual expected types. Where "ignore anything" is truly intended (e.g. best-effort cleanup), the narrow catch is kept explicit with a comment.

### D2: Broad catches must log and not swallow

An `except Exception` is allowed at boundaries (a handler, a top-level sync loop), but only if it logs with context and re-raises or returns an explicit error. A silent `pass` is the defect being removed.

### D3: Logger, not print

Application code uses `list_sync/utils/logger.py`. `print` stays only in developer scripts (`development-files/`), which are out of application paths.

### D4: HTTP boundary maps errors

Rather than each handler inventing a response, a small shared error handler (or explicit `HTTPException`) converts unexpected failures to 5xx with the details logged server-side. This is the API reflection of D2.

### D5: Startup fails loudly

Initialization currently can fail and let the app serve a degraded state. Required-resource failures should abort startup; this is the one place where "catch and continue" is most dangerous.

## Risks / Trade-offs

- [Narrowing a catch causes a previously-swallowed exception to propagate and crash a request] → That is the intended behavior; add error-path tests per migrated site and map to 5xx at the boundary.
- [Log volume increases] → Log once at the boundary, not at every level; keep per-site logs at warning/error with context.
- [Legit best-effort cleanup gets noisy] → Keep explicit, commented, non-logging narrow catches for those; do not blanket-ban.
- [Large diff across many sites] → Migrate by module/section (startup, sync runner, image proxy, analytics) and run the suite after each.

## Migration Plan

1. Inventory and tag (section 1).
2. Bare excepts first (section 2) — highest risk of hiding fatal conditions.
3. Broad excepts and logging (section 3).
4. `print` → logger (section 4).
5. Error semantics + startup (section 5).
Rollback: per-section commits; each is behavior-preserving except where a silent failure becomes loud, which is the point.

## Open Questions

- Should the API get a global exception handler (middleware) or per-handler `HTTPException`? Middleware is less repetitive; per-handler is more explicit.
- Do any of the 29 bare excepts hide a known-and-relied-upon fallback path (e.g. optional provider missing)? 1.2 must classify before editing.
- Is `list_sync/utils/logger.py` already the single configured logger, or are there ad-hoc `logging.basicConfig` calls to consolidate?
