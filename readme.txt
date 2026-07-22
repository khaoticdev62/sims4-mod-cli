Portable Sims 4 Mod Construction CLI — Hermes-Style Layout

Files:
- s4chemist_cli.py : portable Hermes-style CLI (requires `rich` for source runs)

Common commands:
- python s4chemist_cli.py            (arrow-key menu in a terminal; "Type a command..." for the shell)
- python s4chemist_cli.py --help
- python s4chemist_cli.py help <cmd>
- python s4chemist_cli.py init <name>
- python s4chemist_cli.py new <where> <kind> <name>
- python s4chemist_cli.py generate <type> <name> [--param key=value]
- python s4chemist_cli.py wizard <type> [name] [--param key=value]
- python s4chemist_cli.py validate [path] [--strict]
- python s4chemist_cli.py build [path] [--release]
- python s4chemist_cli.py package [path] [--out-dir <dir>]
- python s4chemist_cli.py changelog [path]
- python s4chemist_cli.py pipeline [path]
- python s4chemist_cli.py pipeline tune <phase> [path]
- python s4chemist_cli.py pipeline unlock/status/next/reset [path]
- python s4chemist_cli.py install [path] [--to-dir <dir>]   (or set S4_MODS_DIR)
- python s4chemist_cli.py doctor
- python s4chemist_cli.py tui [path]   (full dashboard UI)
- python s4chemist_cli.py version

Notes:
- validate --strict also flags template config values (ReplaceMe/YourName),
  0x00000000 tuning ids, and placeholder flavor text. See docs/validation.md.
- wizard runs non-interactively when input/output is not a terminal: it uses
  preset defaults plus any --param key=value overrides (name required).
