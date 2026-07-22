# Changelog

## 0.9.2 — 2026-07-22

### Fixed
- Guided mod creation in the TUI ignored the dashboard's project path: the wizard modal and
  generate form operated on the process cwd, silently scaffolding into the wrong folder (or
  creating a new project there). Commands that work on "." now run with the dashboard project
  as their working directory. Regression tests cover both forms from a foreign cwd.
- Wizard modal title now carries the brand glyph.

## 0.9.1 — 2026-07-22

### Fixed
- Crash in the TUI status bar (`AttributeError: '_PrintCapture' object has no attribute
  'encoding'`): Textual replaces `sys.stdout` with a wrapper, so `_ascii_mode()` now tolerates
  streams without an encoding and treats them as unicode-capable.

## 0.9.0 — 2026-07-22

Deep UI refinement, round 3: a bold S4Chemist visual identity across all surfaces.

### Added
- ⚗ brand banner (`⚗ S4CHEMIST · Portable Sims 4 Mod Construction CLI vX.Y.Z`) on the help
  screen and as a splash panel when the arrow-key menu launches (with key hints); ASCII
  fallback glyphs on legacy consoles
- State-colored panel borders: fail/blocked = red, ok/verified = green, local = yellow,
  info = accent blue — outcomes are readable before you read a word
- Section glyph markers (`▸`) in help sections; TUI sidebar sections get `◆` labels, the
  status bar gets the brand glyph, and the TUI header shows a subtitle
- Receipt-style generate/wizard summaries (aligned Type/Name/Path rows)

## 0.8.1 — 2026-07-22

### Fixed
- Crash (`DuplicateIds`) when changing the mod type in the TUI wizard form: widget removal is
  async in Textual, so the rebuilt parameter Inputs must await `remove_children()` before
  mounting. Regression test switches types both ways.

## 0.8.0 — 2026-07-22

Deep UI refinement, round 2: typography and layout craftsmanship.

### Changed
- Hanging-indent wrapping for all panel bullets (validate issues, tune-ids lists, advice/next
  steps): wrapped continuations align under the text instead of spilling to the panel edge
- `validate` placeholder hint no longer prints the absolute project path
  (`tune-ids <project>` instead)
- Help KINDS list is now two aligned columns instead of a wrapped wall of text
- TUI identity: rounded/muted borders, focus rings on inputs, button variants (primary/
  success/warning), styled DataTable header, preview filename header + empty states for the
  preview and log panes, muted sidebar section labels

## 0.7.0 — 2026-07-22

Deep UI refinement: one Hermes design system across all three interfaces.

### Changed
- Shared `HERMES` palette (green/blue/yellow/red/muted hex tokens) now drives the rich theme,
  a registered Textual theme, and the questionary menu style — panels, menus, and the TUI
  finally look like one app
- Footer hints ("Run doctor / Run help…") only appear on help and error panels; normal command
  output is just the panel — dramatically less noise
- Result summaries: `build`/`package` show archive size + file count; artifact paths display
  relative to the project instead of absolute
- TUI status bar above the tabs: project name, current phase, and progress bar at a glance;
  pipeline rows are color-coded (DONE green / ACTIVE yellow / WAIT muted)

## 0.6.1 — 2026-07-22

Full feature audit (67 end-to-end checks across all commands, UI modes, and artifacts).

### Fixed
- `pipeline tune <phase> <path>` ignored the given path and always used the current directory
  (argv slicing skipped the path); regression test added
- Flaky TUI wizard-modal tests now wait for async mount instead of racing fixed pauses

## 0.6.0 — 2026-07-22

TUI deepening.

### Added
- Dashboard tabs: Pipeline / Files / Log. Files tab has a lazy-mounted directory tree with
  syntax-highlighted file preview (xml/python/yaml/markdown)
- Wizard modal form: mod type + required name + dynamic per-type parameter fields with inline
  validation; runs through the standard wizard pipeline
- Command palette (Ctrl+P) with fuzzy search over dashboard actions
- Pipeline phase detail panel (hint / next step / expected artifact) updates on row selection
- Log pane mirrors to a plain-text `history` list; auto-switches to the Log tab on new output

### Fixed
- DirectoryTree now mounts lazily (eager mount deadlocked worker callbacks)
- Wizard param form guards against the mount + Select.Changed double-fire race

## 0.5.0 — 2026-07-22

### Added
- `tui [path]` command: full Textual dashboard — live pipeline table (auto-refreshing),
  command buttons (validate/build/package/changelog/tune-ids/doctor) streaming output into a
  log pane, a generate form (mod type + name), project path input, `q`/`r` key bindings.
  Registered as a normal command, so it also appears in the menu, REPL completion, and help.

## 0.4.0 — 2026-07-22

UI level-up: menu navigation + live feedback (adds `questionary`/`prompt_toolkit` dependency,
bundled in the exe).

### Added
- Arrow-key main menu on bare TTY launch: pick any command, answer guided prompts for its
  arguments (paths, kinds, flags, --param), or choose "Type a command..." for the REPL.
  Esc/Ctrl+C backs out safely at every step.
- REPL upgrades: persistent history (`~/.s4chemist_history`) and command-name tab-completion
  via prompt_toolkit.
- Live feedback: progress bars while zipping (`build`/`package`) and tuning ids, spinner while
  `validate` scans (terminal only; piped output unchanged).

## 0.3.1 — 2026-07-22

### Added
- Interactive shell: launching with no arguments on a real terminal (e.g. double-clicking the
  exe) now opens a `❯ s4chemist_cli` prompt loop instead of printing help and exiting — the
  window stays open and commands can be entered directly. Type `exit`/`quit`, EOF, or Ctrl+C
  to leave. Piped/no-TTY launches still print help and exit.

## 0.3.0 — 2026-07-22

UI refinement: the terminal interface is rebuilt on `rich` (new runtime dependency for
source installs; the portable exe bundles it).

### Added
- Auto-sized, closed panels and real aligned tables (help, pipeline, wizard summary)
- Color-off support: `NO_COLOR` env var, `--no-color` flag, automatic plain output when piped
- Legacy-console fallback: ASCII borders/glyph on non-UTF-8 or legacy Windows consoles
  (plus hidden `S4_ASCII=1` override); VT processing on modern Windows via rich
- Wizard: rich prompts, required-field re-ask, summary table with create-files confirmation
- Pipeline status shows a progress bar

### Changed
- All inline ANSI replaced by a Rich `Theme` (ok/fail/verified/local/blocked/accent/head/hint/glyph)
- `Command` registry metadata is now structured (`usage`/`description`/`status`) and rendered
  as a table; supported kinds listed from `MOD_FACTORIES`
- `install` no longer double-prints; doctor/game-python rows are key-aligned

### Removed
- Dead `_header`/`_status_label` helpers and the pre-colored `PROMPT_GLYPH`

## 0.2.0 — 2026-07-22

Implementation of PLAN.md phases 0–5.

### Added
- pytest suite (25 tests) with CI workflow (ruff + mypy + pytest on windows-latest)
- `COMMANDS` registry with data-driven help metadata; `main()` dispatches via `_cmd_<name>` handlers
- `validate` now prints one actionable line per issue; `--strict` also flags template config
  values (`ReplaceMe`/`YourName`), `0x00000000` tuning ids, and placeholder flavor text
- `docs/validation.md` documenting all validation checks and tag-matching rules
- `wizard --param k=v` overrides and non-interactive mode (defaults + overrides when not a TTY)
- `install` honors `S4_MODS_DIR` (priority: `--to-dir` > env var > auto-detect)
- Post-build archive integrity checks (`_verify_archive`)

### Fixed
- Windows: `_zip_project` exclusions used backslash paths, so `dist/`/`tmp/` were never excluded
  and archives embedded partial copies of themselves
- `testset` factory wrote `testset_name`; validation and `tune-ids` expect `test_set_name`
- Removed dead duplicate `pipeline` dispatch block, dead `_STBL_REPLACEMENTS` dict, and
  duplicated factory maps (now single `MOD_FACTORIES`)
- `build --release` semantics made explicit (delegates to `package_release`)

## 0.1.1 — 2026-07-21

- Version bump; added USAGE.md.
