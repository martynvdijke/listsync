## Context

`api_server.py` (8,693 lines) exposes reporting that is split across two data sources. `/api/requested` opens SQLite directly, while `/api/failures` (line 4495), `/api/processed` (4624), `/api/successful` (4794) and the `SyncLogParser`-based history endpoints parse `data/list_sync.log`. The parsers (`parse_failures_from_logs` at 721, `parse_historic_items_from_logs` at 887, `get_duplicates_from_current_sync` at 1086, plus `parse_log_line`, `categorize_log_entry`, `extract_media_info`, `parse_recent_activity_from_structured_log`) carry ~93 `re.*` calls between them, and `SyncLogParser` (line 7412) even keeps an `ITEM_PATTERNS_ALT` copy of every pattern "for different log formats" — direct evidence of format drift. The database already stores per-item status via `save_sync_result`/`add_item_to_sync` into `sync_items`, with indexes `idx_sync_items_sync_id` and `idx_sync_items_item_id`.

## Goals / Non-Goals

**Goals:**
- One source of truth for reporting/analytics; endpoints cannot disagree.
- Remove the log format as a load-bearing interface.
- Delete the duplicated parser surface.
- Preserve the API response shapes so the Nuxt frontend is unaffected.

**Non-Goals:**
- Changing sync behavior or provider scraping.
- Redesigning the database schema beyond what reporting needs.
- Removing the log file itself (it stays for debugging and live tail).
- Changing the frontend reporting UI.

## Decisions

### D1: Structured tables are the source of truth; the log is an artifact

Reporting reads `sync_items`/`synced_items`/`sync_history`; the log is written for humans and streamed for the live tail. This is the only way both `/api/successful` and `/api/requested` can be guaranteed consistent.

*Rejected:* Keeping log parsing but centralizing it into one "good" parser. It fixes duplication but not the fundamental brittleness — the format can still silently change and breaking reporting on a cosmetic log tweak remains possible.

### D2: Persist missing facts at sync time, not at report time

Where 1.3 finds a reported field that is log-only, the fix is to persist it when the outcome is determined in `list_sync/main.py`. Reporting must never re-derive.

### D3: Equivalence gate before deletion

A comparison test runs the old parser and the new query over recorded representative inputs. Parsers are deleted only after equivalence passes. This keeps the migration reversible and avoids "we deleted the parser and lost a field" regressions.

### D4: Exactly one live-tail reader

The live log stream/SSE genuinely needs to read new lines. That single reader is retained and isolated; it is not used to reconstruct history. This bounds the remaining log coupling to one deliberate place.

### D5: API response shapes unchanged

Endpoints keep their current JSON shape (frontend depends on it); only the data source changes. Any field that cannot be persisted is a conscious contract removal, recorded in 1.3.

## Risks / Trade-offs

- [Some historical facts exist only in old log files] → Backfill task 5.1 handles pre-existing installs; if impossible, document the boundary rather than silently returning empty history.
- [Persisting more fields slows sync slightly] → Writes are batched per session inside existing transactions; measure against current sync time.
- [Analytics query volume on SQLite] → Add indexes on the time/session columns used; the tables already index `sync_id` and `item_id`.
- [Response shape drift while rewriting handlers] → Snapshot current responses as fixtures before rewriting endpoints.
- [Deleting `SyncLogParser` breaks an unknown caller] → 1.1 enumerates all callers before any deletion.

## Migration Plan

1. Inventory fields (section 1) and add persistence (section 2).
2. Add query functions and switch endpoints behind the unchanged API shapes (sections 3–4).
3. Backfill old installs and pass the equivalence test (section 5).
4. Delete parsers, keep one tail reader, run the suite (section 6).
Rollback: parsers are removed only in the final section; reverting that commit restores them while the DB-backed path remains available.

## Open Questions

- Which report fields are truly log-only — does `1.3` surface any that should be dropped rather than persisted?
- Is a log-history backfill needed for the project's own deployments, or only for external users?
- Should analytics read live `sync_items` directly, or a periodic materialized rollup for performance?
