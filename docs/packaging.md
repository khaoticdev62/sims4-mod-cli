# Packaging & Distribution

This release layout is designed for zip distribution and Mods-folder installs from a checked-out repo.

DISTRIBUTION FILES
- `s4chemist_cli.py` at your repo root
- `OWNERS-GUIDE.txt`
- `docs/sims4-mod-types.md`

CLI TOOL RELEASE ZIP CONTENTS
(the portable distribution archive for S4Chemist itself, e.g. the PyInstaller build)
- s4chemist_cli.py
- OWNERS-GUIDE.txt
- docs/sims4-mod-types.md

CREATE CLI TOOL RELEASE ZIP
1. Open terminal at the repo root
2. Run: pyinstaller s4chemist_cli.spec
3. Zip the dist/ output, or hand-assemble the files listed above.

MOD PROJECT BUILD/PACKAGE OUTPUT
`build`/`package` zip up a mod *project* directory (created via `init`), not the
S4Chemist repo. They always exclude `dist/`, `tmp/`, and `.git*`. `package`
(and `build --release`, which is equivalent) additionally excludes
`OWNERS-GUIDE.txt` if a copy happens to be present inside the project.

INSTALL FOR USERS
1. Python 3.10 or later
2. Extract release zip
3. Run: python s4chemist_cli.py --help

MODS INSTALL
- python "$SK" install <project>
- This copies project files to Documents\Electronic Arts\The Sims 4\Mods\<project>
- dist/ and tmp/ are removed before copy

VERSIONING
- Use s4modconfig.yaml mod_name and version fields
- Build stamps use YYYYMMDD-HHMMSS
