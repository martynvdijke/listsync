## Why

`pyproject.toml` enables roughly 55 ruff rule families (including `S`, `BLE`, `TRY`, `PERF`, `RUF`), but the tool never fails anything: CI runs `ruff check --exit-zero .` (`.github/workflows/ci.yml:100`). The rule surface is decorative. On top of that the ruff version is inconsistent across the three places it is configured — poetry dev dependency `ruff = "^0.2.1"`, CI pins `ruff==0.6.7`, and pre-commit pins `rev: v0.6.7` — so even the enabled rules are evaluated differently depending on where you run them. The result is a large, unenforced, version-skewed quality gate.

## What Changes

- Pin exactly one ruff version used by the dev dependency, CI, and pre-commit.
- Make CI fail on ruff violations instead of `--exit-zero`.
- Establish a baseline of current violations, recorded explicitly (fixed, or captured as tracked per-file ignores / a ratchet), so the gate fails only on *new* debt.
- Enforce `ruff format --check` so formatting is not a diff-churn source.
- Keep the rule families enabled but make them real; do not silently shrink the rule set to hide findings.

## Capabilities

### New Capabilities
- `code-quality-gates`: a single pinned linter/formatter configuration that CI enforces, with current findings baselined explicitly and prevented from growing.

### Modified Capabilities
<!-- openspec/specs/ is empty; no existing capabilities to modify. -->

## Impact

- `pyproject.toml`: ruff version and configuration.
- `.github/workflows/ci.yml`: remove `--exit-zero`, add a format check.
- `.pre-commit-config.yaml`: align the pinned ruff revision.
- Codebase: an initial batch of violations to fix or baseline (size unknown until ruff runs; ruff is not installed in this environment).
