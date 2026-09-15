## ADDED Requirements

### Requirement: One pinned linter version everywhere

The ruff version used by the project SHALL be identical across the dev dependency declaration, CI, and pre-commit.

#### Scenario: Versions match

- **WHEN** comparing the ruff version in `pyproject.toml`, `.github/workflows/ci.yml`, and `.pre-commit-config.yaml`
- **THEN** all three specify the same pinned version, and CI fails if they diverge

### Requirement: CI fails on lint violations

The lint step SHALL fail the build when ruff reports a violation that is not part of the recorded baseline.

#### Scenario: New violation fails CI

- **WHEN** a commit introduces a ruff violation outside the baseline
- **THEN** the CI lint job exits non-zero and the build is red

#### Scenario: No blanket exit-zero

- **WHEN** inspecting the CI lint step
- **THEN** it does not pass `--exit-zero`, and the job result reflects ruff's exit code

### Requirement: Existing violations are baselined explicitly

Current violations SHALL be either fixed or captured as an explicit, visible baseline; they SHALL NOT be hidden by disabling rule families.

#### Scenario: Baseline is visible

- **WHEN** ruff is run on the repository after this change
- **THEN** the remaining findings are enumerated in configuration (e.g. per-file ignores with tracking) rather than suppressed by removing rules from `select`

#### Scenario: Baseline cannot grow

- **WHEN** the number of ignored violations is compared over time
- **THEN** it is non-increasing; new ignores require an explicit, reviewable change

### Requirement: Formatting is enforced

Code formatting SHALL be checked in CI so formatting is not a source of review noise.

#### Scenario: Format check runs

- **WHEN** CI runs
- **THEN** `ruff format --check` runs and fails the build if files are unformatted

### Requirement: The rule set stays honest

Enabled rule families SHALL NOT be silently removed to make the gate pass; any reduction SHALL be a reviewed, documented decision.

#### Scenario: Rule removal is intentional

- **WHEN** a rule family is removed from `select`
- **THEN** the change documents why, so the gate shrinks knowingly rather than accidentally
