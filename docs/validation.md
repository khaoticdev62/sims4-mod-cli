# Validation rules

`s4chemist_cli validate [path] [--strict]` checks a project and prints one actionable line per
issue (what is wrong, where, and how to fix it). The exit code equals the number of issues, so
`0` means clean.

## Non-strict checks (always on)

| Check | Trigger | Fix |
|-------|---------|-----|
| Unreadable XML | a `*.xml` file cannot be read | fix permissions/encoding |
| XML declaration | a `*.xml` file does not start with `<?xml` | add `<?xml version='1.0' encoding='utf-8'?>` as the first line |
| Required tuning tags | a file matching a kind in `TUNING_TAG_RULES` is missing one of its required `<T n="...">` / `<U n="...">` tags | add the missing tag (one issue per missing tag) |
| Package artifact | no `*.package` / `*.package.template` exists and there are also no XML/Python sources | `new <proj> package <name>` or author one in Sims4Studio |

The package check is skipped when `src/package/` exists and the project has XML or Python sources
(a package is expected to be produced later from those sources).

## Strict-only checks (`--strict`)

| Check | Trigger | Fix |
|-------|---------|-----|
| Missing config | `s4modconfig.yaml` absent | `s4chemist_cli init <name>` |
| Template mod name | config contains `ReplaceMe` | set a real `mod_name:` |
| Template creator | config contains `YourName` | set a real `creator:` |
| Placeholder tuning id | XML contains `0x00000000` | run `s4chemist_cli tune-ids <proj>` to assign real ids |
| Placeholder flavor text | XML contains `Replace with ...` | write real display/description text |

## Tag matching and duplicate tagging rules

A file is matched against every kind in `TUNING_TAG_RULES` (career, trait, buff, interaction,
event, achievement, aspiration, whim, club, holiday, loot_action, testset, relationship, skill,
motive). A file "belongs" to a kind when its filename:

- ends with `_<kind>.xml` (canonical scaffold naming, e.g. `MyTrait_trait.xml`), or
- contains `_<kind>.` anywhere, or
- is exactly `<kind>.xml`.

Matching is **not exclusive**: if a filename matches several kinds, each kind contributes its own
missing-tag issues (duplicates are intentional — rename the file so it matches exactly one kind).
A tag counts as present when either `<T n="tag">` or `<U n="tag">` appears in the file.

Files that fail the XML-declaration check are not tag-checked (the parse stops at the first
structural problem for that file).
