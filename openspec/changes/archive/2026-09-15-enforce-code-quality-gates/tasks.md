## 1. Measure the pile

- [x] 1.1 Install the target ruff version and run `ruff check . --statistics` to size findings per rule
- [x] 1.2 Run `ruff format --check .` to size formatting drift
- [x] 1.3 Classify findings into "fix now" (cheap, mechanical) vs "baseline" (needs design work)

## 2. Unify the version

- [x] 2.1 Pin one ruff version in `pyproject.toml` dev dependencies
- [x] 2.2 Set the same version in `.github/workflows/ci.yml`
- [x] 2.3 Set the same `rev` in `.pre-commit-config.yaml`
- [x] 2.4 Decide and document the single target version (currently `^0.2.1`/`0.6.7`/`v0.6.7` disagree)

## 3. Fix cheap findings

- [x] 3.1 Apply `ruff check --fix` for auto-fixable rules
- [x] 3.2 Apply `ruff format` and commit the formatting pass on its own
- [x] 3.3 Manually fix the remaining high-value, low-risk findings (unused imports, dead code, undefined names)

## 4. Baseline the rest

- [x] 4.1 Add per-file ignores for the findings deferred to later, with a comment or tracked list
- [x] 4.2 Confirm no rule family was silently dropped from `select`

## 5. Make the gate real

- [x] 5.1 Remove `--exit-zero` from `.github/workflows/ci.yml`
- [x] 5.2 Add a `ruff format --check` step
- [x] 5.3 Verify a deliberately introduced violation fails CI, then revert it
- [x] 5.4 Run `openspec validate enforce-code-quality-gates --strict`
