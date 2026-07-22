# AGENTS.md

Guidance for AI coding agents working in this repository. Assumes no prior knowledge of the project.

## Project overview

S4Chemist (package name `s4chemist`, CLI entry point `s4chemist_cli`) is a portable, single-file
Python CLI for scaffolding, validating, and packaging Sims 4 mod projects. The entire implementation
lives in one module: `s4chemist_cli.py` (~2300 lines). Runtime dependencies are `rich` (panels/tables), `questionary`+`prompt_toolkit` (menus/REPL),
and `textual` (the `tui` dashboard)
(for the terminal UI); Python >= 3.9 is required.

Key files:

- `s4chemist_cli.py` — the whole CLI (commands, generators, pipeline state machine, TUI helpers).
- `pyproject.toml` — packaging metadata, console script, and config for pytest / mypy / ruff.
- `s4chemist_cli.spec` — PyInstaller spec that builds a single portable `.exe` (no data files).
- `tests/` — pytest suite (`test_smoke.py`, `test_lifecycle.py`, `test_phases.py`, `conftest.py`
  fixtures).
- `tools/justfile` — task shortcuts: `just test`, `just lint`, `just typecheck`, `just package`.
- `docs/packaging.md`, `docs/sims4-mod-types.md`, `docs/validation.md` — release zip layout,
  mod-type reference, and validation rules.
- `.github/workflows/tests.yml` — CI: ruff + mypy + pytest on `windows-latest`, Python 3.11.
- `PLAN.md` — multi-phase improvement plan (Phases 0–1 are done; later phases are in progress).
- `CLAUDE.md` — architecture notes; may lag behind recent phases — trust the code.

## Build and test commands

Run directly from source (no install needed):

```
python s4chemist_cli.py <command> [args]
python s4chemist_cli.py --help
python s4chemist_cli.py help <command>
```

Install locally as a package:

```
pip install -e ".[dev]"   # installs pytest, ruff, mypy, pyinstaller
s4chemist_cli <command> [args]
```

Test / lint / typecheck (same steps CI runs; all must pass):

```
python -m pytest tests/ -v
ruff check s4chemist_cli.py tests
mypy s4chemist_cli.py
```

Build the portable Windows executable:

```
pyinstaller s4chemist_cli.spec   # output in dist/
```

Manual smoke loop against a scratch project (use `tmp/`, which is gitignored):

```
python s4chemist_cli.py init tmp/SmokeTest
python s4chemist_cli.py new tmp/SmokeTest career MyCareer
python s4chemist_cli.py validate tmp/SmokeTest
python s4chemist_cli.py build tmp/SmokeTest
python s4chemist_cli.py pipeline tmp/SmokeTest
python s4chemist_cli.py doctor
```

## Architecture

### Command dispatch
`main()` (near the bottom of `s4chemist_cli.py`) dispatches through the `COMMANDS` registry: a
dict of `Command` entries mapping each command name to a `_cmd_<name>(argv) -> int` handler. Bare
launch on a TTY opens `menu_shell()` (questionary arrow-key menu; `_menu_flow()` builds argv per
command) with a "Type a command..." option that drops into `interactive_shell()` (prompt_toolkit
REPL with history + completion); piped launches print help and exit. Each handler parses its own flags positionally,
calls the relevant function, prints a `_status_panel(...)` block, and returns an int exit code. Help
text is data-driven: `Command.args` feeds the ARGS section of subcommand help and `Command.help_lines`
feeds the main COMMANDS panel. When adding a new top-level command, add a `_cmd_<name>` handler and a
matching `Command` entry in `COMMANDS`.

### Mod-project shape
A "project" is any directory containing all of `PROJECT_FILES`: `src/xml_snippets`, `src/ts4script`,
`src/package`, `dist`, `tmp`, `s4modconfig.yaml`, `mod_notes.txt`, `.gitignore`. `init_project()`
creates this skeleton; `_existing_project()` validates it before any command operates on a path.

### Artifact generators (`new_*` factories)
Each supported mod kind (`career`, `trait`, `buff`, `interaction`, `event`, `achievement`,
`aspiration`, `whim`, `club`, `holiday`, `loot_action`, `testset`, `relationship`, `skill`, `motive`,
plus the base `xml_snippet` / `ts4script` / `package`) has a `new_<kind>(proj, name) -> Path`
factory that writes XML/README/manifest scaffolding into `src/...`. These factories are registered
once in the module-level `MOD_FACTORIES` dict (right after `new_motive`), shared by the `new`,
`generate`, and `wizard` commands.

`generate <type> <name> [--param key=value ...]` layers on top of `new`: it applies STBL/tuning
placeholder rewrites via `_apply_params()` / `_rewrite_stbl_placeholders()`, and creates a throwaway
project under `tmp/generate-<name>-<timestamp>/` if run outside an existing project.

### Pipeline / slot-n-lock state machine
`PIPELINE_PHASES` (concept → requirements → proof → tuning → implementation → validation →
local_test → packaging → distribution) and `PIPELINE_META` describe a linear build pipeline tracked
per project in a `.s4modstate` JSON file. Phases advance automatically when expected artifacts
appear (`_advance_pipeline_if_artifact`, called after `init`/`new`/`validate`/`build`/`package`) or
manually via `pipeline unlock/reset`.

### Validation, build, and install
- `validate_project_issues()` returns actionable issue strings; `validate_project()` is an int
  wrapper. Checks: XML declaration, kind-specific required tuning tags via `TUNING_TAG_RULES`, and
  (non-strict) at least one `.package` / `.package.template` when other src files exist. `--strict`
  also flags template config values, `0x00000000` ids, and `Replace with ...` flavor text. Full
  rules: `docs/validation.md`.
- `wizard` is scriptable: non-interactive (requires both stdin and stdout to be TTYs — on Windows
  NUL reports `isatty()` True) it uses preset defaults plus `--param k=v` overrides.
- `_zip_project()` is shared by `build_project()` and `package_release()`; exclusions use
  `rel.as_posix()` (Windows backslashes previously defeated the `dist/`/`tmp/` filters), and
  `_verify_archive()` runs post-build integrity checks. `build --release` / `package_release()`
  produce release-named archives (see `docs/packaging.md`).
- `install_to_mods()` copies the project into the Mods folder with priority `--to-dir` >
  `S4_MODS_DIR` env var > detected `Documents/Electronic Arts/The Sims 4/Mods`, stripping `dist/`,
  `tmp/`, `.git`.
- `doctor_check()` / `ensure_game_python()` are environment probes with no side effects.

### Output styling
The UI is built on `rich` (panels/tables) with `questionary`/`prompt_toolkit` for menus and the REPL, and `textual` for the
`tui` dashboard (pipeline table, command buttons, generate form, log pane). All commands render through shared
helpers — `_status_panel` (auto-sized closed panel; body items may be markup strings or Rich
renderables like `Table`), `_meta_block`, `_kv_block`, `_section` — styled by the `THEME`
tags. Rules: never inline raw ANSI; always escape user-derived strings with `_esc()`.
Color is auto-disabled when piped, with `NO_COLOR`, or `--no-color`; `_ascii_mode()` (legacy
console, non-UTF-8 stream, or `S4_ASCII=1`) switches box glyphs and the `❯` prompt to ASCII.

## Code style guidelines

- Single-file module: keep everything in `s4chemist_cli.py`; do not split into packages without a
  deliberate refactor.
- One runtime dependency: `rich` (terminal UI). No other third-party packages; the PyInstaller
  build bundles both, so the CLI must stay self-contained (no runtime file reads outside the
  target project directory).
- Ruff: line-length 120, target py311 (see `pyproject.toml`); mypy checks only `s4chemist_cli.py`.
- Match existing idioms: `pathlib.Path` everywhere, typed function signatures, `_`-prefixed
  private helpers, ANSI panel helpers for all user-facing output.

## Testing instructions

- Tests live in `tests/` and run via `python -m pytest tests/ -v` (config in `pyproject.toml`).
- `tests/conftest.py` provides `tmp_project` (a minimal valid mod project under pytest's
  `tmp_path`), `repo_root`, and `cli_runner(args, cwd)`, which invokes the CLI in a subprocess
  (`python s4chemist_cli.py ...`) and returns `(stdout, stderr, returncode)`.
- Write tests as black-box subprocess assertions on stdout / exit codes / produced files, following
  `test_smoke.py` and `test_lifecycle.py`.
- CI (`.github/workflows/tests.yml`) runs ruff, mypy, and pytest on every push/PR — keep all green.

## Security considerations

- The CLI writes files under user-supplied project paths and under `tmp/`; never introduce network
  access, credential handling, or writes outside the target project directory (except the explicit
  `install` command's Mods-folder copy).
- Keep the tool dependency-free; if a capability seems to require a new dependency, surface that to
  the user instead of silently adding one.
- `tmp/`, `build/`, `dist/`, and `release/` are generated artifacts — do not commit changes there.
