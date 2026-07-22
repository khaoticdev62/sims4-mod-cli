# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

S4Chemist (package name `s4chemist`, CLI entry point `s4chemist_cli`) is a portable, single-file
Python CLI for scaffolding, validating, and packaging Sims 4 mod projects. The entire implementation
lives in one module: `s4chemist_cli.py` (~2300 lines). Runtime dependencies are `rich` (panels/tables), `questionary`+`prompt_toolkit` (menus/REPL),
and `textual` (the `tui` dashboard)
(for the terminal UI). Tests live in `tests/` (pytest).

## Commands

Run directly from source (no install needed):
```
python s4chemist_cli.py <command> [args]
python s4chemist_cli.py --help
python s4chemist_cli.py help <command>
```

Install locally as a package:
```
pip install -e .
s4chemist_cli <command> [args]
```

Build a portable Windows executable (requires `pip install -e ".[dev]"` for PyInstaller):
```
pyinstaller s4chemist_cli.spec
```

Tests live in `tests/` (pytest, configured in `pyproject.toml` alongside ruff/mypy settings and a
`dev` extra); run `python -m pytest` after changes. Also verify changes by exercising
the CLI directly against a scratch project (e.g. under `tmp/`, which is gitignored):
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
`main()` at the bottom of `s4chemist_cli.py` dispatches through the `COMMANDS` registry: a dict
of `Command` entries mapping each command name to a `_cmd_<name>(argv) -> int` handler. Bare
launch on a TTY opens `menu_shell()` (questionary arrow-key menu; `_menu_flow()` builds argv per
command) with a "Type a command..." option that drops into `interactive_shell()` (prompt_toolkit
REPL with history + completion); piped launches print help and exit. Each handler parses its own flags positionally,
calls the relevant function, prints a `_status_panel(...)` block, and returns an int exit code. Help
text is data-driven: `Command.args` feeds the ARGS section of `print_help()` subcommand help and
`Command.help_lines` feeds the main COMMANDS panel. When adding a new top-level command, add a
`_cmd_<name>` handler and a matching `Command` entry in `COMMANDS`.

### Mod-project shape
A "project" is any directory containing all of `PROJECT_FILES` (defined near `_existing_project`):
`src/xml_snippets`, `src/ts4script`, `src/package`, `dist`, `tmp`, `s4modconfig.yaml`, `mod_notes.txt`,
`.gitignore`. `init_project()` creates this skeleton; `_existing_project()` validates it before any
command (`new`, `validate`, `build`, `package`, `install`, `pipeline`, ...) operates on a path.

### Artifact generators (`new_*` factories)
Each supported mod kind (`career`, `trait`, `buff`, `interaction`, `event`, `achievement`,
`aspiration`, `whim`, `club`, `holiday`, `loot_action`, `testset`, `relationship`, `skill`, `motive`,
plus the base `xml_snippet` / `ts4script` / `package`) has a `new_<kind>(proj, name) -> Path` factory
that writes XML/README/manifest scaffolding into `src/...`. These are registered once in the
module-level `MOD_FACTORIES` dict (defined right after `new_motive`), which the `new`, `generate`,
and `wizard` commands all share.

`generate <type> <name> [--param key=value ...]` layers on top of `new`: it also applies STBL/tuning
placeholder rewrites via `_apply_params()` and `_rewrite_stbl_placeholders()`, and will create a
throwaway project under `tmp/generate-<name>-<timestamp>/` via `_find_or_create_temp_project()` if run
outside an existing project.

### Pipeline / slot-n-lock state machine
`PIPELINE_PHASES` (concept → requirements → proof → tuning → implementation → validation →
local_test → packaging → distribution) and `PIPELINE_META` describe a linear build pipeline tracked
per-project in a `.s4modstate` JSON file (`pipeline_state_path`, `load_pipeline_state`,
`save_pipeline_state`). Phases advance automatically when expected artifacts appear
(`_advance_pipeline_if_artifact`, called after `init`/`new`/`validate`/`build`/`package`) or manually
via `pipeline unlock/reset`. `pipeline status`/`pipeline next`/`pipeline tune <phase>` render progress
using the same `_status_panel` UI helpers as every other command.

### Validation, build, and install
- `validate_project_issues()` returns actionable issue strings (what/where/how-to-fix);
  `validate_project()` is an int wrapper kept for compatibility. Checks: XML declaration,
  kind-specific required tuning tags via `TUNING_TAG_RULES`, and (non-strict) at least one
  `.package`/`.package.template` when other src files exist. `--strict` additionally flags
  template config values (`ReplaceMe`/`YourName`), `0x00000000` tuning ids, and `Replace with ...`
  flavor text. Full rules: `docs/validation.md`.
- `wizard` is scriptable: when stdin/stdout is not a real terminal it skips prompts and uses preset
  defaults plus `--param k=v` overrides (name via `[name]` arg or `--param name=...`). Note: on
  Windows NUL//dev/null reports `isatty()` True, so interactivity requires both stdin and stdout
  to be TTYs.
- `_zip_project()` (shared by `build_project()` and `package_release()`) zips the whole project
  excluding `dist/`, `tmp/`, `.git*` — paths are normalized with `rel.as_posix()` because on
  Windows `str(rel)` uses backslashes and the exclusions silently failed (the archive even embedded
  a partial copy of itself). `_verify_archive()` runs post-build integrity checks (is_zipfile,
  `testzip()`, non-empty). `package_release()` is the release-named variant that also excludes
  `OWNERS-GUIDE.txt` (see `docs/packaging.md`).
- `install_to_mods()` copies the project into the Mods folder with priority `--to-dir` >
  `S4_MODS_DIR` env var > auto-detected `Documents/Electronic Arts/The Sims 4/Mods`, stripping
  `dist/`, `tmp/`, `.git`.
- `doctor_check()` / `ensure_game_python()` are environment probes (Python version, Sims 4 Documents
  folder, Mods folder, game's bundled Python) with no side effects.

### Output styling
The UI is built on `rich` (panels/tables) with `questionary`/`prompt_toolkit` for menus and the REPL, and `textual` for the
`tui` dashboard (pipeline table, command buttons, generate form, log pane). All commands render through shared
helpers — `_status_panel` (auto-sized closed panel; body items may be markup strings or Rich
renderables like `Table`), `_meta_block`, `_kv_block`, `_section` — styled by the `THEME`
tags (`ok`/`fail`/`verified`/`local`/`blocked`/`accent`/`head`/`hint`/`glyph`). Rules:
never inline raw ANSI (`\033[...]`); always escape user-derived strings with `_esc()` so they
can't corrupt markup. Color is auto-disabled when piped, with `NO_COLOR`, or `--no-color`;
`_ascii_mode()` (legacy console, non-UTF-8 stream, or `S4_ASCII=1`) switches box glyphs and the
`❯` prompt glyph to ASCII.

## Distribution

`s4chemist_cli.spec` (PyInstaller) builds a single portable `.exe` from `s4chemist_cli.py`
(bundling `rich`) with no extra data files — the CLI must remain self-contained (no runtime file
reads outside the target project directory). See `docs/packaging.md` for the
release zip layout and `docs/sims4-mod-types.md` for the mod-type reference shipped to end users.
