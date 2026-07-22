# S4Chemist — User Guide

This guide is for players and modders who want to use S4Chemist-generated mods.

## Install S4Chemist CLI

### Windows zip
1. Download `S4Chemist-portable-*.zip` from the latest GitHub release.
2. Extract it anywhere, e.g. `C:\Tools\S4Chemist`.
3. Open that folder and double-click `s4chemist_cli.exe` — it opens an arrow-key menu.
   Pick a command, answer its prompts, or choose "Type a command..." for a prompt with
   history and tab-completion. Esc backs out; "Exit" quits.

If the window closes immediately, open Command Prompt in that folder and run:
- `python s4chemist_cli.py doctor`

### pip install
- `pip install s4chemist`

### Run from source
- `pip install rich` (only dependency), then `python s4chemist_cli.py --help`

## Verify install
- `s4chemist_cli version`
- `s4chemist_cli doctor`

If `doctor` says `MISSING Sims 4 Documents`, install The Sims 4 or create the folder:
- `C:\Users\<you>\Documents\Electronic Arts\The Sims 4\Mods`

## Install a mod into The Sims 4
1. Extract the mod zip.
2. Copy the mod folder into your Mods folder:
   - `C:\Users\<you>\Documents\Electronic Arts\The Sims 4\Mods\`
3. In-game:
   - Enable script mods in Game Options > Other.
   - Restart the game if prompted.

## Using the CLI
- `s4chemist_cli init <name>` — create a new mod project
- `s4chemist_cli new . <kind> <name>` — add a mod artifact
- `s4chemist_cli validate .` — check XML/packaging hygiene (add `--strict` to also flag
  placeholder tuning ids and template values; see `docs/validation.md`)
- `s4chemist_cli build .` — create `dist/*.zip`
- `s4chemist_cli install .` — copy to detected Mods folder (override with `--to-dir <dir>`
  or the `S4_MODS_DIR` environment variable)
- `s4chemist_cli tui .` — open the full dashboard (live pipeline table, one-click commands,
  generate form, log pane)

## Troubleshooting
- `doctor` shows `MISSING Mods Folder`: create `Documents\Electronic Arts\The Sims 4\Mods`
  or point `S4_MODS_DIR` at your real Mods folder
- `validate` shows issues: each line names the file and the fix; `docs/validation.md`
  lists every check
- Script mods not loading: confirm script mods are enabled in-game

## Support
See `OWNERS-GUIDE.txt` for authoring details and `docs/packaging.md` for release layout.
