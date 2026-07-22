# S4Chemist Implementation Plan

Goal: turn `s4chemist_cli.py` into a maintainable, testable, verifiable CLI without regressing current behavior.

---

## Current state

- Single-file Python CLI: `s4chemist_cli.py`
- No external dependencies
- No tests, no lint, no CI, no type checking
- Command parsing is manual and partially duplicated
- Duplicate base factories + stale path references in docs
- `build --release` flag is accepted but does not change packing behavior
- `wizard` is interactive-first
- Validation is string-presence based

---

## Phase 0 — Tooling foundation

Add minimal but real dev/test prerequisites so every change has an automated safety net.

1. Add `pyproject.toml` sections for:
   - test deps: `pytest`
   - lint: `ruff`
   - typecheck: `mypy`
   - optional format: `black`
2. Add `tests/conftest.py` and `tests/test_smoke.py`.
3. Add `.github/workflows/tests.yml` for PR checks.
4. Add `justfile` or `Makefile`:
   - `just test`
   - `just lint`
   - `just typecheck`
   - `just package`

---

## Phase 1 — Correctness before features

Fix the clear inconsistencies first.

1. Remove duplicate base factory definitions:
   - keep one definition of `new_xml_snippet`, `new_ts4script`, `new_package_mod`
2. Fix path drift in `docs/packaging.md` and `OWNERS-GUIDE.txt`.
3. Make `build --release` behavior explicit:
   - either implement release semantics, or remove the misleading flag behavior.

---

## Phase 2 — Command parsing cleanup

1. Introduce a small command registry.
2. Move help text to data-driven metadata.
3. Migrate `main()` dispatch while preserving existing `_status_panel` output format.

---

## Phase 3 — Validation improvements

1. Add stricter placeholder checks.
2. Add actionable validation output.
3. Add `docs/validation.md` describing exact checks and duplicates tagging rules.

---

## Phase 4 — Scriptability

1. Make `wizard` accept `--param` overrides.
2. Provide clear non-interactive fallback/errors.

---

## Phase 5 — Packaging and install hardening

1. Share zip-generation logic between `build_project()` and `package_release()`.
2. Support Sims 4 Mods path override via `S4_MODS_DIR`.
3. Add post-build archive integrity checks.

---

## Phase 6 — Verification loop

After each phase, run:
- `python s4chemist_cli.py --help`
- `python s4chemist_cli.py version`
- init/new/validate/build/package against a scratch project under `tmp/`
- update `CLAUDE.md` if architecture changes

---

## Claude Code start sequence

Recommended first actions:
1. Implement Phase 0 test scaffolding.
2. Fix Phase 1 duplicate definitions and stale doc paths.
3. Add regression smoke tests covering init/new/validate/build/package for all supported mod types.
