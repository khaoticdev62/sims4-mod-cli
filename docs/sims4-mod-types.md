# Sims 4 Mod Types & Autoscripting Guide

This CLI supports three main authoring modes:
- `new` — add one artifact to an existing project
- `generate` — autoscript a full scaffold, with optional `--param key=value` tuning
- `wizard` — guided creation with brain advice, dependencies, and next steps
- `changelog` — create or append a project changelog entry

Supported mod types:
- xml_snippet
- ts4script
- package
- career
- trait
- buff
- interaction
- event
- achievement
- aspiration
- whim
- club
- holiday
- loot_action
- testset
- relationship
- skill
- motive

## Common commands
- `python s4mod_cli.py --help`
- `python s4mod_cli.py help <cmd>`
- `python s4mod_cli.py init <name>`
- `python s4mod_cli.py new <where> <kind> <name>`
- `python s4mod_cli.py generate <type> <name> [--param key=value]`
- `python s4mod_cli.py wizard <type> [name]`
- `python s4mod_cli.py changelog [path]`
- `python s4mod_cli.py validate [path]`
- `python s4mod_cli.py build [path]`
- `python s4mod_cli.py package [path]`
- `python s4mod_cli.py pipeline [path]`
- `python s4mod_cli.py pipeline tune <phase> [path]`
- `python s4mod_cli.py doctor`
- `python s4mod_cli.py version`

## Parameter workflow
Use `--param` to inject labels, descriptions, commands, or tuning notes:
- `label` / `title` → display names
- `description` → body/flavor text
- `command` → ts4script command name
- `tuning` → multiline tuning notes for XML snippets
- `note.<key>` → save pipeline notes into `.s4modstate`

## Wizard workflow
- `wizard career NightShift` prompts for label, description, pay, level_title
- It prints Brain Advice, Dependencies, and Next Steps
- If no project exists in the current directory, it initializes one automatically

## Brains behaviors
- Compatibility advice for each mod type
- Dependency hints: XML Injector, testsets, script runtime, tdesc tools
- Next-step guidance after generation

## Packaging
- Use `.package` or `.package.template` files under `src/package` for CC/packaged mods.
- `build` zips the project for Mods install.
- `package` creates a release zip excluding dist/tmp/.git.
- `install` copies to your detected Sims 4 `Mods` folder.

Examples:
- `python s4mod_cli.py wizard career NightShift`
- `python s4mod_cli.py generate trait RoadDog --param description="started on the road"`
- `python s4mod_cli.py validate .`
- `python s4mod_cli.py build .`
- `python s4mod_cli.py pipeline tune tuning .`
