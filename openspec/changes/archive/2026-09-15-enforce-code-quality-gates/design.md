## Context

`pyproject.toml` `[tool.ruff.lint]` selects a broad rule set (`E,F,W,I,N,UP,YTT,S,BLE,...RUF`) and ignores a specific list. A large ignore list is already present (`PLR0913`, `PLR0915`, `C901`, `PLR0912`, etc.), which is normal for a legacy codebase — but the gate never runs enforcingly. CI (`ci.yml:100`) uses `--exit-zero` and the summary step (`:105`) counts findings with `--exit-zero` too, so the job is always green. Version skew: `pyproject.toml:30` `ruff = "^0.2.1"`, `ci.yml:92` `ruff==0.6.7`, `.pre-commit-config.yaml` `rev: v0.6.7`. Different ruff versions have different rule behavior, so "enabled" does not mean the same thing in each place.

## Goals / Non-Goals

**Goals:**
- One version, enforced consistently.
- New violations fail the build; existing ones are visible and frozen.
- Formatting enforced.
- Rule set honest.

**Non-Goals:**
- Fixing all existing violations in this change (that is a separate, potentially large effort).
- Enabling type checking (`mypy`/`pyright`) — not currently configured.
- Changing runtime behavior.

## Decisions

### D1: Pick one ruff version and pin it in all three places

The dev dependency, CI, and pre-commit pin the same exact version. Version skew means "which rules apply" depends on where you run it, which defeats the purpose.

*Rejected:* Leaving versions floating — rule behavior changes on upgrade and the gate becomes non-deterministic.

### D2: Baseline via per-file ignores, not rule removal

Deferred findings are captured as explicit per-file ignores (ideally referencing a tracked list) so the count is visible and monotonically non-increasing. Removing rule families from `select` hides the debt and is disallowed without documentation.

*Rejected:* Turn off `BLE`, `S`, `TRY` etc. to get green — that is the current failure mode in disguise.

### D3: Fix mechanical findings first

`--fix` and `format` handle a large share with no judgment. Land the formatting pass as its own commit to avoid burying real changes in whitespace.

### D4: Fail closed

CI fails on violations unless baselined. A temporary period with the full baseline is acceptable; a permanently non-failing gate is not.

## Risks / Trade-offs

- [Baseline is huge and the first enforcing run is unmanageable] → Land 3.1–3.2 first (auto-fix + format), then baseline only the remainder; grow enforcement per-rule if needed.
- [Formatting pass creates a giant diff that hides logic changes] → Separate commit, no logic changes in it, called out in the PR.
- [Pre-commit and CI disagree because a dev skipped pre-commit] → CI is authoritative; pre-commit is convenience. Same pinned version.
- [Ignoring findings per-file hides real bugs] → Track the baseline count; require it to shrink. The ignore list is a debt ledger, not a graveyard.

## Migration Plan

1. Measure findings (section 1).
2. Unify versions (section 2) — safe, independent.
3. Auto-fix + format (section 3) — separate commits.
4. Baseline the rest (section 4).
5. Flip CI to fail-closed (section 5).
Rollback: revert the CI flip to restore `--exit-zero`; the baseline and formatting commits are benign on their own.

## Open Questions

- What is the actual size of the findings pile? Ruff is not installed here; 1.1 answers this and may change the strategy (small pile → fix it all; large pile → ratchet).
- Do we want to adopt `ruff format` at all, or only `ruff check`? Formatting is currently unmanaged.
- Should the ratchet be a CI script that compares a stored count, or just per-file ignores?
