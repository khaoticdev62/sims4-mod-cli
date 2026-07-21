#!/usr/bin/env python3
"""Portable Sims 4 Mod Construction CLI - local authoring helper.

This CLI ships with a Hermes-style screen layout: colored status labels,
command panel tables, and uniform subcommand help blocks.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path
from datetime import datetime
from typing import Iterable

if sys.stdout.encoding and sys.stdout.encoding.upper() != "UTF-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, UnicodeError):
        pass

PIPELINE_PHASES = [
    "concept",
    "requirements",
    "proof",
    "tuning",
    "implementation",
    "validation",
    "local_test",
    "packaging",
    "distribution",
]

PIPELINE_META = {
    "concept": {
        "name": "Concept",
        "hint": "Define the mod idea, player impact, and success criteria.",
        "next": "Write 3-6 bullet requirements.",
        "artifact": "mod_notes.txt",
    },
    "requirements": {
        "name": "Requirements",
        "hint": "Lock the feature list, inputs, outputs, and edge cases.",
        "next": "Create a tiny proof/placeholder scaffold.",
        "artifact": "docs/requirements.md",
    },
    "proof": {
        "name": "Proof",
        "hint": "Prove the smallest possible behavior end-to-end.",
        "next": "Tune values and replace placeholders.",
        "artifact": "tmp/proof_checklist.txt",
    },
    "tuning": {
        "name": "Tuning",
        "hint": "Adjust loot thresholds, decay rates, pay curves, and text.",
        "next": "Implement the locked behavior in XML/script.",
        "artifact": "src/**/README.txt",
    },
    "implementation": {
        "name": "Implementation",
        "hint": "Replace placeholders with real behavior and code paths.",
        "next": "Run validation and fix issues.",
        "artifact": "src/**",
    },
    "validation": {
        "name": "Validation",
        "hint": "Run s4mod_cli validate and fix XML/schema/text issues.",
        "next": "Load in-game and test locally.",
        "artifact": "dist/*.zip",
    },
    "local_test": {
        "name": "Local Test",
        "hint": "Playtest locally, capture receipts/stress/fatigue behavior.",
        "next": "Package release and log changelog.",
        "artifact": "tmp/playtest_notes.txt",
    },
    "packaging": {
        "name": "Packaging",
        "hint": "Create release zip and verify contents/install path.",
        "next": "Publish or deliver to testers.",
        "artifact": "dist/*-release-*.zip",
    },
    "distribution": {
        "name": "Distribution",
        "hint": "Deliver release notes, install path, and support notes.",
        "next": "Pipeline complete.",
        "artifact": "CHANGELOG.md",
    },
}


def pipeline_state_path(proj: Path) -> Path:
    return proj / ".s4modstate"


def load_pipeline_state(proj: Path) -> dict:
    path = pipeline_state_path(proj)
    state = {"phase_index": 0, "locked": [], "notes": {}}
    if not path.exists():
        return state
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("phase_index="):
            try:
                state["phase_index"] = int(line.split("=", 1)[1])
            except ValueError:
                pass
        elif line.startswith("locked="):
            state["locked"] = [p.strip() for p in line.split("=", 1)[1].split(",") if p.strip()]
        elif line.startswith("note."):
            k, v = line.split("=", 1)
            state["notes"][k.replace("note.", "", 1)] = v
    return state


def save_pipeline_state(proj: Path, state: dict) -> None:
    path = pipeline_state_path(proj)
    lines = [
        "# s4mod state: editable only via pipeline commands",
        f"phase_index={state.get('phase_index', 0)}",
        f"locked={','.join(state.get('locked', []))}",
    ]
    for k, v in state.get("notes", {}).items():
        lines.append(f"note.{k}={v}")
    _write(path, "\n".join(lines) + "\n")


def current_phase(state: dict) -> str:
    idx = max(0, min(int(state.get("phase_index", 0)), len(PIPELINE_PHASES) - 1))
    return PIPELINE_PHASES[idx]


def is_phase_locked(state: dict, phase: str) -> bool:
    return phase in [p for p in state.get("locked", []) if p in PIPELINE_PHASES]


def lock_phase(state: dict, phase: str) -> None:
    if phase not in state.get("locked", []):
        state.setdefault("locked", []).append(phase)
    try:
        idx = PIPELINE_PHASES.index(phase)
    except ValueError:
        return
    state["phase_index"] = min(idx + 1, len(PIPELINE_PHASES) - 1)


def phase_progress(state: dict) -> tuple[str, int, int, int]:
    total = len(PIPELINE_PHASES)
    current = PIPELINE_PHASES[max(0, min(int(state.get("phase_index", 0)), total - 1))]
    locked_count = len([p for p in PIPELINE_PHASES if p in state.get("locked", [])])
    completed = locked_count
    pct = int((completed / total) * 100) if total else 0
    return current, completed, total, pct


def next_actions(state: dict) -> list[str]:
    cur = current_phase(state)
    meta = PIPELINE_META.get(cur, {})
    actions = [f"Complete current phase: {meta.get('name', cur)}", meta.get("next", "")]
    if meta.get("artifact"):
        actions.append(f"Expected artifact: {meta['artifact']}")
    return [a for a in actions if a]


def print_pipeline_status(proj: Path) -> str:
    state = load_pipeline_state(proj)
    cur, done, total, pct = phase_progress(state)
    rows = [f"{'Phase':20} {'Status':10} {'Hint'}"]
    rows.append("─" * 60)
    for p in PIPELINE_PHASES:
        locked = is_phase_locked(state, p)
        active = p == cur and not locked
        marker = "DONE" if locked else ("ACTIVE" if active else "WAIT")
        color = C_GREEN if locked else C_YELLOW if active else C_RESET
        label = PIPELINE_META[p]["name"]
        hint = PIPELINE_META[p]["hint"]
        rows.append(f"{C_BOLD_WHITE}{label:20}{C_RESET} {color}{marker:10}{C_RESET} {hint}")
    rows += [
        "",
        f"{C_BOLD_WHITE}Progress:{C_RESET} {done}/{total} ({pct}%)",
        f"{C_BOLD_WHITE}Next:{C_RESET}",
    ] + [f"  - {a}" for a in next_actions(state)]
    return _status_panel("pipeline", rows, command="pipeline")


def print_pipeline_next(proj: Path) -> str:
    state = load_pipeline_state(proj)
    cur = current_phase(state)
    actions = next_actions(state)
    rows = [f"{C_BOLD_WHITE}Current Phase:{C_RESET} {PIPELINE_META[cur]['name']}"]
    rows += [
        "",
        f"{C_BOLD_WHITE}Next Actions:{C_RESET}",
    ] + [f"  - {a}" for a in actions]
    rows += [
        "",
        f"{C_BOLD_WHITE}Unlock:{C_RESET} pipeline unlock .",
        f"{C_BOLD_WHITE}Reset:{C_RESET} pipeline reset .",
    ]
    return _status_panel("pipeline-next", rows, command="pipeline-next")


def unlock_current_phase(proj: Path) -> str:
    state = load_pipeline_state(proj)
    cur = current_phase(state)
    if is_phase_locked(state, cur):
        out = _meta_block("blocked", "Blocked", f"{cur} already locked")[0]
        return _status_panel("pipeline-unlock", [out], command="pipeline-unlock")
    lock_phase(state, cur)
    save_pipeline_state(proj, state)
    nxt = current_phase(state)
    if nxt == cur and is_phase_locked(state, cur):
        msg = "Pipeline complete"
    else:
        msg = f"{PIPELINE_META[cur]['name']} -> {PIPELINE_META[nxt]['name']}"
    rows = _meta_block("verified", "Unlocked", msg)
    rows += [f"{C_BOLD_WHITE}Progress:{C_RESET} {phase_progress(state)[1]}/{len(PIPELINE_PHASES)}"]
    return _status_panel("pipeline-unlock", rows, command="pipeline-unlock")


def reset_pipeline(proj: Path) -> str:
    state = {"phase_index": 0, "locked": [], "notes": {}}
    save_pipeline_state(proj, state)
    rows = _meta_block("ok", "Reset", "Pipeline reset to concept phase")
    return _status_panel("pipeline-reset", rows, command="pipeline-reset")


def _advance_pipeline_if_artifact(proj: Path, artifact_rel: str) -> None:
    state = load_pipeline_state(proj)
    cur = current_phase(state)
    if is_phase_locked(state, cur):
        return
    if (proj / artifact_rel).exists():
        lock_phase(state, cur)
        save_pipeline_state(proj, state)


ROOT = Path(__file__).resolve().parent


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _header(text: str) -> str:
    return f"\033[1;37m{text}\033[0m"


PROMPT_GLYPH = "\033[1;32m❯\033[0m"


def _prompt() -> str:
    return f"{PROMPT_GLYPH} "


C_RESET = "\033[0m"
C_BOLD_WHITE = "\033[1;37m"
C_GREEN = "\033[1;32m"
C_RED = "\033[1;31m"
C_YELLOW = "\033[1;33m"
C_BLUE = "\033[1;34m"


def _fnv1a_64(text: str) -> int:
    h = 0xCBF29CE484222325
    for b in text.encode("utf-8"):
        h = (h ^ b) * 0x100000001B3
        h &= 0xFFFFFFFFFFFFFFFF
    return h


def _tuning_instance(name: str, suffix: str = "") -> str:
    seed = f"{name}{suffix}"
    return hex(_fnv1a_64(seed) & 0x7FFFFFFFFFFFFFFF)


def _status_label(ok: bool, text: str) -> str:
    return f"{C_GREEN}[OK]{C_RESET} {text}" if ok else f"{C_RED}[FAIL]{C_RESET} {text}"


def _status_panel(headline: str, body: Iterable[str], *, command: str = "") -> str:
    color = C_GREEN if "OK" in headline else C_RED if "FAIL" in headline or "ERROR" in headline else C_YELLOW
    headline_text = headline.replace("accessibility_verdict: true", "VERDICT").replace("game-python", "GAME PYTHON")
    headline_display = f"{C_BLUE}{headline_text}{C_RESET}"
    rule = "─" * 20
    footer_command = command or headline_text.lower()
    lines = [
        f"{C_BOLD_WHITE}┌── {C_GREEN}s4mod_cli {C_BOLD_WHITE}── {headline_display} {C_BOLD_WHITE}{rule}┐{C_RESET}"
    ]
    for line in body:
        lines.append(f"{C_BOLD_WHITE}│{C_RESET} {line}")
    lines.append(f"{C_BOLD_WHITE}└{'─' * 58}┘{C_RESET}")
    lines.append(f"{C_YELLOW}{PROMPT_GLYPH}{C_RESET} {C_BOLD_WHITE}s4mod_cli {footer_command} ...{C_RESET}")
    if footer_command != "s4mod_cli":
        lines.append(f"{C_YELLOW}{PROMPT_GLYPH}{C_RESET} {C_BOLD_WHITE}Run 's4mod_cli doctor'   Verify environment paths.{C_RESET}")
        lines.append(f"{C_YELLOW}{PROMPT_GLYPH}{C_RESET} {C_BOLD_WHITE}Run 's4mod_cli help <cmd>'  Show command help.{C_RESET}")
    else:
        lines.append(f"{C_YELLOW}{PROMPT_GLYPH}{C_RESET} {C_BOLD_WHITE}Enter a command to start.{C_RESET}")
    return "\n".join(lines)


def _kv_block(rows: list[tuple[str, str]]) -> list[str]:
    return [f"{k}: {v}" for k, v in rows]


def _meta_block(state: str, label: str, detail: str = "") -> list[str]:
    mapping = {
        "ok": f"{C_GREEN}[OK]{C_RESET}",
        "verified": f"{C_GREEN}[VERIFIED]{C_RESET}",
        "local": f"{C_YELLOW}[LOCAL]{C_RESET}",
        "blocked": f"{C_RED}[BLOCKED]{C_RESET}",
        "fail": f"{C_RED}[FAIL]{C_RESET}",
    }
    tag = mapping.get(state, f"{C_YELLOW}[{state.upper()}]{C_RESET}")
    return [f"{tag} {label}{' — ' + detail if detail else ''}"]


def _section(title: str, lines: list[str]) -> list[str]:
    out = [f"\033[1;37m{title}\033[0m"]
    if lines:
        for line in lines:
            out.append(line)
    return out


def init_project(name: str) -> Path:
    proj = Path(name).resolve()
    if proj.exists():
        raise SystemExit(f"Refusing to overwrite existing path: {proj}")

    (proj / "src" / "xml_snippets").mkdir(parents=True)
    (proj / "src" / "ts4script").mkdir(parents=True)
    (proj / "src" / "package").mkdir(parents=True)
    (proj / "dist").mkdir(parents=True)
    (proj / "tmp").mkdir(parents=True)
    (proj / ".gitignore").write_text("dist/\ntmp/\n", encoding="utf-8")
    _write(
        proj / "s4modconfig.yaml",
        "mod_name: ReplaceMe\ncreator: YourName\nversion: 0.1.0\nmod_type: xml_snippet\nxml_injector_required: false\ngame_versions:\n  - '*'\n",
    )
    _write(proj / "mod_notes.txt", "# Development notes\n")
    return proj


PROJECT_FILES = [
    "src/xml_snippets",
    "src/ts4script",
    "src/package",
    "dist",
    "tmp",
    "s4modconfig.yaml",
    "mod_notes.txt",
    ".gitignore",
]


def _existing_project(p: str | Path) -> Path:
    proj = Path(p).resolve()
    missing = [f for f in PROJECT_FILES if not (proj / f).exists()]
    if missing:
        raise SystemExit(f"Not a valid project: {proj}\nMissing: {missing}")
    return proj


def new_xml_snippet(proj: Path, name: str) -> Path:
    d = proj / "src" / "xml_snippets" / name
    _write(
        d / f"{name}.xml",
        "<?xml version='1.0' encoding='utf-8'?>\n"
        f"<!-- {name} snippet -->\n<Snippets>\n  <!-- Replace this body with an XML Injector snippet or tuning fragment -->\n</Snippets>\n",
    )
    _write(d / "README.txt", f"XML Snippet: {name}\nEnable via XML Injector snippet slot when required.\n")
    return d


def new_ts4script(proj: Path, name: str) -> Path:
    d = proj / "src" / "ts4script" / name
    _write(
        d / "main.py",
        "import sims4.commands\nimport services\n\n\n@sims4.commands.Command('your.command.here', command_type=sims4.commands.CommandType.Live)\ndef your_command(_connection=None):\n    output = sims4.commands.output(_connection)\n    output('Hello from mod script!')\n",
    )
    _write(
        d / "manifest.json",
        '{\n  "name": "' + name + '",\n  "version": "0.1.0",\n  "entry": "main.py"\n}\n',
    )
    return d


def new_package_mod(proj: Path, name: str) -> Path:
    d = proj / "src" / "package" / name
    _write(
        d / f"{name}.package.template",
        "Package binaries require Sims 4 Studio/s4pe + Tdesc Builder + EA resource tools to author and sign.\nSee current packaging docs for MODS_PACKAGE/EXTRA resource structure and tdesc files.\n",
    )
    _write(d / "README.txt", f"Package Tuning: {name}\nPurpose: behavioral tuning/custom-content base project.\n")
    return d


def _parse_kv_tokens(argv: list[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--param":
            if i + 1 < len(argv) and "=" in argv[i + 1]:
                k, v = argv[i + 1].split("=", 1)
                params[k] = v
                i += 2
                continue
        elif arg.startswith("--param="):
            _, kv = arg.split("--param=", 1)
            if "=" in kv:
                k, v = kv.split("=", 1)
                params[k] = v
        i += 1
    return params


def _find_or_create_temp_project(name: str | Path) -> Path:
    project_name = Path(name).name or "unnamed"
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    cwd_candidate = Path.cwd() / f"generate-{project_name}-{stamp}"
    fallback = ROOT / "tmp" / f"generate-{project_name}-{stamp}"
    if (Path.cwd() / ".gitignore").exists() or (Path.cwd() / "s4modconfig.yaml").exists():
        temp_root = cwd_candidate
    else:
        temp_root = fallback
    if temp_root.exists():
        i = 1
        while temp_root.with_name(f"{temp_root.name}-{i}").exists():
            i += 1
        temp_root = temp_root.with_name(f"{temp_root.name}-{i}")
    return init_project(str(temp_root))


def _apply_params(proj: Path, mod_type: str, name: str, params: dict[str, str]) -> None:
    if not params:
        return

    if mod_type == "xml_snippet":
        xml_path = proj / "src" / "xml_snippets" / name / f"{name}.xml"
        if xml_path.exists():
            txt = xml_path.read_text(encoding="utf-8")
            label = params.get("label") or params.get("title") or name
            desc = params.get("description")
            old = f"<!-- {name} snippet -->"
            new_cmt = f"<!-- {label}"
            if desc:
                new_cmt += f": {desc}"
            new_cmt += " -->"
            txt = txt.replace(old, new_cmt, 1)
            _write(xml_path, txt)

        readme = proj / "src" / "xml_snippets" / name / "README.txt"
        if readme.exists():
            lines = [f"Label: {params.get('label', name)}"]
            if "description" in params:
                lines.append(f"Description: {params['description']}")
            if "tuning" in params:
                lines.extend(params["tuning"].splitlines())
            _write(readme, "\n".join(lines) + "\n\n" + readme.read_text(encoding="utf-8"))

    elif mod_type == "ts4script":
        main = proj / "src" / "ts4script" / name / "main.py"
        if main.exists():
            txt = main.read_text(encoding="utf-8")
            if "label" in params:
                txt = txt.replace("your.command.here", params["label"].lower().replace(" ", "."))
            elif "command" in params:
                txt = txt.replace("your.command.here", params["command"].lower().replace(" ", "."))
            if "description" in params:
                txt = txt.replace("Hello from mod script!", params["description"])
            _write(main, txt)

        readme = proj / "src" / "ts4script" / name / "README.txt"
        if not readme.exists():
            _write(readme, f"{name}\n{'=' * len(name)}\n\n")
        if readme.exists():
            block = [name, "=" * len(name), ""]
            for k, v in params.items():
                block.append(f"{k}: {v}")
            block.append("")
            _write(readme, "\n".join(block) + "\n" + readme.read_text(encoding="utf-8"))

    elif mod_type == "package":
        pkg = proj / "src" / "package" / name
        readme = pkg / "README.txt"
        if readme.exists():
            lines = [name, "=" * len(name), ""]
            for k, v in params.items():
                lines.append(f"{k}: {v}")
            lines.append("")
            _write(readme, "\n".join(lines) + "\n" + readme.read_text(encoding="utf-8"))
    elif mod_type == "career":
        base = proj / "src" / "xml_snippets" / f"{name}_career"
        readme = base / "README.txt"
        if readme.exists():
            header = []
            if "label" in params:
                header.append(f"Label: {params['label']}")
            if "description" in params:
                header.append(f"Description: {params['description']}")
            if "pay" in params:
                header.append(f"Pay: {params['pay']}")
            if "level_title" in params:
                header.append(f"Level Title: {params['level_title']}")
            if header:
                _write(readme, "\n".join(header) + "\n\n" + readme.read_text(encoding="utf-8"))

        # Update XML skeleton with meaningful career stubs when possible.
        xml_path = base / f"{name}_career.xml"
        if xml_path.exists():
            txt = xml_path.read_text(encoding="utf-8")
            label = params.get("label") or name
            txt = txt.replace(f"<T n=\"career_name\">{name}</T>", f"<T n=\"career_name\">{label}</T>")
            txt = txt.replace("<T n=\"career_track\">Adult</T>", "<T n=\"career_track\">Adult</T>\n  <T n=\"career_icon\">0x00000000</T>\n  <U n=\"entry_level\">1</U>")
            txt = txt.replace("<U n=\"simoleon_pay\">500</U>", f"<U n=\"simoleon_pay\">{params.get('pay','500')}</U>")
            txt = txt.replace("<T n=\"level_title\">Level 1</T>", f"<T n=\"level_title\">{params.get('level_title','Level 1')}</T>")
            _write(xml_path, txt)

    elif mod_type == "trait":
        base = proj / "src" / "xml_snippets" / f"{name}_trait"
        readme = base / "README.txt"
        if readme.exists():
            header = []
            if "label" in params:
                header.append(f"Label: {params['label']}")
            if "description" in params:
                header.append(f"Description: {params['description']}")
            if header:
                _write(readme, "\n".join(header) + "\n\n" + readme.read_text(encoding="utf-8"))

        xml_path = base / f"{name}_trait.xml"
        if xml_path.exists():
            txt = xml_path.read_text(encoding="utf-8")
            label = params.get("label") or name
            txt = txt.replace(f"<T n=\"trait_name\">{name}</T>", f"<T n=\"trait_name\">{label}</T>")
            txt = txt.replace("Replace with trait flavor text.", params.get("description", "Replace with trait flavor text."))
            traits_trait_remove = 'sims4.traits.trait_Trait'
            if traits_trait_remove:
                xml_path.write_text(xml_path.read_text(encoding="utf-8").replace("trait_flavor_placeholder", label), encoding="utf-8")
            _write(xml_path, txt)

    elif mod_type == "buff":
        base = proj / "src" / "xml_snippets" / f"{name}_buff"
        readme = base / "README.txt"
        if readme.exists():
            header = []
            if "label" in params:
                header.append(f"Label: {params['label']}")
            if "description" in params:
                header.append(f"Description: {params['description']}")
            if "mood_type" in params:
                header.append(f"Mood Type: {params['mood_type']}")
            if "animation_style" in params:
                header.append(f"Animation: {params['animation_style']}")
            if header:
                _write(readme, "\n".join(header) + "\n\n" + readme.read_text(encoding="utf-8"))

        xml_path = base / f"{name}_buff.xml"
        if xml_path.exists():
            txt = xml_path.read_text(encoding="utf-8")
            label = params.get("label") or name
            txt = txt.replace(f"<T n=\"buff_name\">{name}</T>", f"<T n=\"buff_name\">{label}</T>")
            txt = txt.replace("Replace with buff flavor text.", params.get("description", "Replace with buff flavor text."))
            txt = txt.replace("<T n=\"mood_type\">Neutral</T>", f"<T n=\"mood_type\">{params.get('mood_type','Neutral')}</T>")
            txt = txt.replace("<T n=\"animation_style\">None</T>", f"<T n=\"animation_style\">{params.get('animation_style','None')}</T>")
            _write(xml_path, txt)

    elif mod_type == "interaction":
        base = proj / "src" / "xml_snippets" / f"{name}_interaction"
        readme = base / "README.txt"
        if readme.exists():
            header = []
            if "label" in params:
                header.append(f"Label: {params['label']}")
            if "description" in params:
                header.append(f"Description: {params['description']}")
            if "pie_menu_priority" in params:
                header.append(f"Menu Priority: {params['pie_menu_priority']}")
            if "available_tests" in params:
                header.append(f"Tests: {params['available_tests']}")
            if header:
                _write(readme, "\n".join(header) + "\n\n" + readme.read_text(encoding="utf-8"))

        xml_path = base / f"{name}_interaction.xml"
        if xml_path.exists():
            txt = xml_path.read_text(encoding="utf-8")
            label = params.get("label") or name
            txt = txt.replace("<T n=\"interaction_name\">" + name + "</T>", f"<T n=\"interaction_name\">{label}</T>")
            txt = txt.replace("<T n=\"pie_menu_priority\">0</T>", f"<T n=\"pie_menu_priority\">{params.get('pie_menu_priority','0')}</T>")
            _write(xml_path, txt)

    elif mod_type == "event":
        base = proj / "src" / "xml_snippets" / f"{name}_event"
        readme = base / "README.txt"
        if readme.exists():
            header = []
            if "label" in params:
                header.append(f"Label: {params['label']}")
            if "description" in params:
                header.append(f"Description: {params['description']}")
            if "event_type" in params:
                header.append(f"Type: {params['event_type']}")
            if "duration" in params:
                header.append(f"Duration: {params['duration']}")
            if header:
                _write(readme, "\n".join(header) + "\n\n" + readme.read_text(encoding="utf-8"))

        xml_path = base / f"{name}_event.xml"
        if xml_path.exists():
            txt = xml_path.read_text(encoding="utf-8")
            label = params.get("label") or name
            txt = txt.replace(f"<T n=\"event_name\">{name}</T>", f"<T n=\"event_name\">{label}</T>")
            txt = txt.replace("<T n=\"event_type\">Social</T>", f"<T n=\"event_type\">{params.get('event_type','Social')}</T>")
            txt = txt.replace("<U n=\"duration\">120</U>", f"<U n=\"duration\">{params.get('duration','120')}</U>")
            _write(xml_path, txt)

    elif mod_type == "achievement":
        base = proj / "src" / "xml_snippets" / f"{name}_achievement"
        readme = base / "README.txt"
        if readme.exists():
            header = []
            if "label" in params:
                header.append(f"Label: {params['label']}")
            if "description" in params:
                header.append(f"Description: {params['description']}")
            if "hidden" in params:
                header.append(f"Hidden: {params['hidden']}")
            if header:
                _write(readme, "\n".join(header) + "\n\n" + readme.read_text(encoding="utf-8"))

        xml_path = base / f"{name}_achievement.xml"
        if xml_path.exists():
            txt = xml_path.read_text(encoding="utf-8")
            label = params.get("label") or name
            txt = txt.replace(f"<T n=\"event_name\">{name}</T>", f"<T n=\"achievement_name\">{label}</T>")
            hidden = "True" if params.get("hidden","False").lower() == "true" else "False"
            if "<T n=\"hidden\">" not in txt:
                txt = txt.replace("</I>", f"  <T n=\"hidden\">{hidden}</T>\n</I>")
            _write(xml_path, txt)

    elif mod_type == "aspiration":
        base = proj / "src" / "xml_snippets" / f"{name}_aspiration"
        readme = base / "README.txt"
        if readme.exists():
            header = []
            if "label" in params:
                header.append(f"Label: {params['label']}")
            if "description" in params:
                header.append(f"Description: {params['description']}")
            if header:
                _write(readme, "\n".join(header) + "\n\n" + readme.read_text(encoding="utf-8"))

    elif mod_type == "whim":
        base = proj / "src" / "xml_snippets" / f"{name}_whim"
        readme = base / "README.txt"
        if readme.exists():
            header = []
            if "label" in params:
                header.append(f"Label: {params['label']}")
            if "description" in params:
                header.append(f"Description: {params['description']}")
            if header:
                _write(readme, "\n".join(header) + "\n\n" + readme.read_text(encoding="utf-8"))

    elif mod_type == "club":
        base = proj / "src" / "xml_snippets" / f"{name}_club"
        readme = base / "README.txt"
        if readme.exists():
            header = []
            if "label" in params:
                header.append(f"Label: {params['label']}")
            if "description" in params:
                header.append(f"Description: {params['description']}")
            if header:
                _write(readme, "\n".join(header) + "\n\n" + readme.read_text(encoding="utf-8"))

    elif mod_type == "holiday":
        base = proj / "src" / "xml_snippets" / f"{name}_holiday"
        readme = base / "README.txt"
        if readme.exists():
            header = []
            if "label" in params:
                header.append(f"Label: {params['label']}")
            if "description" in params:
                header.append(f"Description: {params['description']}")
            if header:
                _write(readme, "\n".join(header) + "\n\n" + readme.read_text(encoding="utf-8"))

    elif mod_type == "loot_action":
        base = proj / "src" / "xml_snippets" / f"{name}_loot_action"
        readme = base / "README.txt"
        if readme.exists():
            header = []
            if "label" in params:
                header.append(f"Label: {params['label']}")
            if "description" in params:
                header.append(f"Description: {params['description']}")
            if header:
                _write(readme, "\n".join(header) + "\n\n" + readme.read_text(encoding="utf-8"))

    elif mod_type == "testset":
        base = proj / "src" / "xml_snippets" / f"{name}_testset"
        readme = base / "README.txt"
        if readme.exists():
            header = []
            if "label" in params:
                header.append(f"Label: {params['label']}")
            if "description" in params:
                header.append(f"Description: {params['description']}")
            if header:
                _write(readme, "\n".join(header) + "\n\n" + readme.read_text(encoding="utf-8"))

    elif mod_type == "relationship":
        base = proj / "src" / "xml_snippets" / f"{name}_relationship"
        readme = base / "README.txt"
        if readme.exists():
            header = []
            if "label" in params:
                header.append(f"Label: {params['label']}")
            if "description" in params:
                header.append(f"Description: {params['description']}")
            if "relationship_value" in params:
                header.append(f"Value: {params['relationship_value']}")
            if header:
                _write(readme, "\n".join(header) + "\n\n" + readme.read_text(encoding="utf-8"))

        xml_path = base / f"{name}_relationship.xml"
        if xml_path.exists():
            txt = xml_path.read_text(encoding="utf-8")
            txt = txt.replace("<U n=\"relationship_value\">0</U>", f"<U n=\"relationship_value\">{params.get('relationship_value','0')}</U>")
            _write(xml_path, txt)

    elif mod_type == "skill":
        base = proj / "src" / "xml_snippets" / f"{name}_skill"
        readme = base / "README.txt"
        if readme.exists():
            header = []
            if "label" in params:
                header.append(f"Label: {params['label']}")
            if "description" in params:
                header.append(f"Description: {params['description']}")
            if "skill_level" in params:
                header.append(f"Skill Level: {params['skill_level']}")
            if header:
                _write(readme, "\n".join(header) + "\n\n" + readme.read_text(encoding="utf-8"))

        xml_path = base / f"{name}_skill.xml"
        if xml_path.exists():
            txt = xml_path.read_text(encoding="utf-8")
            txt = txt.replace("<U n=\"skill_level\">1</U>", f"<U n=\"skill_level\">{params.get('skill_level','1')}</U>")
            _write(xml_path, txt)

    elif mod_type == "motive":
        base = proj / "src" / "xml_snippets" / f"{name}_motive"
        readme = base / "README.txt"
        if readme.exists():
            header = []
            if "label" in params:
                header.append(f"Label: {params['label']}")
            if "description" in params:
                header.append(f"Description: {params['description']}")
            if "decay_rate" in params:
                header.append(f"Decay Rate: {params['decay_rate']}")
            if "threshold" in params:
                header.append(f"Threshold: {params['threshold']}")
            if header:
                _write(readme, "\n".join(header) + "\n\n" + readme.read_text(encoding="utf-8"))

        xml_path = base / f"{name}_motive.xml"
        if xml_path.exists():
            txt = xml_path.read_text(encoding="utf-8")
            txt = txt.replace("<U n=\"decay_rate\">1</U>", f"<U n=\"decay_rate\">{params.get('decay_rate','1')}</U>")
            txt = txt.replace("<U n=\"threshold\">100</U>", f"<U n=\"threshold\">{params.get('threshold','100')}</U>")
            _write(xml_path, txt)


WIZARD_PRESETS = {
    "career": {
        "params": ["label", "description", "pay", "level_title"],
        "defaults": {"pay": "500", "level_title": "Level 1"},
        "requires": ["xml_injector"],
        "notes": "Use XML Injector snippet; prefer testsets for autonomy. Add test references before packaging.",
        "next_steps": ["Write XML injector snippet", "Add testset references", "Test directory ownership"],
    },
    "trait": {
        "params": ["label", "description"],
        "requires": ["xml_injector"],
        "notes": "Traits are XML-first. Use script only if you need runtime state.",
        "next_steps": ["Add buff references", "Document skill links"],
    },
    "buff": {
        "params": ["label", "description", "mood_type", "animation_style"],
        "defaults": {"mood_type": "Neutral", "animation_style": "None"},
        "requires": ["xml_injector"],
        "notes": "Buff mood and animation should match gameplay tone.",
        "next_steps": ["Verify animation style", "Add loot where needed"],
    },
    "interaction": {
        "params": ["label", "description", "pie_menu_priority", "available_tests"],
        "defaults": {"pie_menu_priority": "0"},
        "requires": ["xml_injector", "testset_or_script"],
        "notes": "Use tags for broad object selection, not exact names.",
        "next_steps": ["Create testset if needed", "Check affordance conflicts"],
    },
    "event": {
        "params": ["label", "description", "event_type", "duration"],
        "defaults": {"event_type": "Social", "duration": "120"},
        "requires": ["xml_injector"],
        "notes": "Events should have bounded duration and minimal stakeable list.",
        "next_steps": ["Create event loot", "Check UI icon resource"],
    },
    "achievement": {
        "params": ["label", "description", "hidden"],
        "defaults": {"hidden": "False"},
        "requires": ["xml_injector_or_script"],
        "notes": "Use hidden=True for surprise achievements.",
        "next_steps": ["Write prerequisites", "Add display_name STBL key if needed"],
    },
    "xml_snippet": {
        "params": ["label", "description", "tuning"],
        "requires": ["xml_injector"],
        "notes": "Snippets should be surgical; avoid broad overrides.",
        "next_steps": ["Validate XML with Sims 4 Studio", "Document tuning reference"],
    },
    "ts4script": {
        "params": ["label", "command", "description"],
        "requires": ["script_mod_runtime"],
        "notes": "Keep scripts deterministic. Avoid hard-coded paths. Use cache events.",
        "next_steps": ["Add unit tests", "Document lastException handling"],
    },
    "package": {
        "params": ["label", "description"],
        "requires": ["sims4studio_or_s4pe"],
        "notes": "Packaging needs tdesc files, STBL, and signable resources.",
        "next_steps": ["Build tdesc manifest", "Author STBL entries"],
    },
    "aspiration": {
        "params": ["label", "description"],
        "requires": ["xml_injector"],
        "notes": "Use milestones for progression and STBL for display text.",
        "next_steps": ["Define milestone steps", "Add reward loot"],
    },
    "whim": {
        "params": ["label", "description"],
        "requires": ["xml_injector"],
        "notes": "Keep whims short-lived and tied to related buffs.",
        "next_steps": ["Check buff bias", "Verify duration"],
    },
    "club": {
        "params": ["label", "description"],
        "requires": ["xml_injector"],
        "notes": "Balance club rules and member preferences carefully.",
        "next_steps": ["Test gathering behavior", "Review member filters"],
    },
    "holiday": {
        "params": ["label", "description"],
        "requires": ["xml_injector"],
        "notes": "Limit traditions/decorations per holiday to avoid heavy neighborhoods.",
        "next_steps": ["Author tradition loot", "Verify decoration count"],
    },
    "loot_action": {
        "params": ["label", "description"],
        "requires": ["xml_injector"],
        "notes": "Group related state changes; keep chains short.",
        "next_steps": ["Test loot ordering", "Avoid long dependency chains"],
    },
    "testset": {
        "params": ["label", "description"],
        "requires": ["xml_injector"],
        "notes": "Use for affordance gating and interaction tests.",
        "next_steps": ["Verify cached tests", "Document filter rules"],
    },
    "relationship": {
        "params": ["label", "description", "relationship_value"],
        "defaults": {"relationship_value": "0"},
        "requires": ["xml_injector"],
        "notes": "Use relationship_value for baselines, related_traits for sentiment hooks.",
        "next_steps": ["Test sentiment transitions", "Review trait links"],
    },
    "skill": {
        "params": ["label", "description", "skill_level"],
        "defaults": {"skill_level": "1"},
        "requires": ["xml_injector"],
        "notes": "Use skill_effects for unlocks; keep progression smooth.",
        "next_steps": ["Test unlock order", "Balance curve"],
    },
    "motive": {
        "params": ["label", "description", "decay_rate", "threshold"],
        "defaults": {"decay_rate": "1", "threshold": "100"},
        "requires": ["xml_injector"],
        "notes": "Use decay_rate for pacing, motive_buffs for state transitions.",
        "next_steps": ["Check motive balance", "Verify buff triggers"],
    },
}

COMPATIBILITY_RULES = {
    "career": "Avoid broad overrides; use XML Injector snippets for level payloads. Add testset if autonomy changes.",
    "trait": "Prefer XML-only traits. Use script only when adding persistent state. Document related skills/loot.",
    "buff": "Keep mood/alarm behavior simple. Use loot for state transitions. Validate animation names.",
    "interaction": "Prefer tags over exact object names. Use testsets instead of full overrides when possible.",
    "event": "Limit duration and stakeables. Verify loot outcome order and test conditions.",
    "achievement": "Use hidden=False sparingly. Add prerequisites carefully; test backward compatibility after patches.",
    "xml_snippet": "Keep snippets narrow. Document referenced tuning files and instances.",
    "ts4script": "Document dependencies in README. Avoid modifying mutable slots without invalidation.",
    "package": "Use meaningful package names and versioning. Add changelog for packaged resources.",
    "aspiration": "Keep milestone steps small and testable.",
    "whim": "Use whims contextually; avoid broad whim spam.",
    "club": "Limit rules and preferences per club.",
    "holiday": "Keep traditions light; avoid heavy decoration counts.",
    "loot_action": "Keep loot chains short and deterministic.",
    "testset": "Prefer cached tests; avoid expensive runtime checks.",
    "relationship": "Prefer slow relationship drift over large jumps.",
    "skill": "Balance progression curves and unlock order.",
    "motive": "Use decay_rate/threshold carefully; buffs should feel responsive.",
}


def wizard_presets(mod_type: str) -> dict:
    return WIZARD_PRESETS.get(mod_type, {"params": ["label", "description"], "requires": [], "notes": "No preset available.", "next_steps": ["Validate output", "Run build"]})


def compatibility_advice(mod_type: str) -> str:
    return COMPATIBILITY_RULES.get(mod_type, "Validate tuning and avoid broad overrides. Use XML Injector when possible.")


def dependency_notes(mod_type: str) -> list[str]:
    preset = wizard_presets(mod_type)
    requires = preset.get("requires", [])
    items = []
    if "xml_injector" in requires:
        items.append("Requires XML Injector for safe snippet injection.")
    if "testset_or_script" in requires:
        items.append("Needs a testset script or cached test class for clean behavior.")
    if "script_mod_runtime" in requires:
        items.append("Script mod must be compiled and placed in Mods for runtime.")
    if "sims4studio_or_s4pe" in requires:
        items.append("Package authoring needs Sims4Studio/s4pe and tdesc tools.")
    if "xml_injector_or_script" in requires:
        items.append("Can use XML Injector or script fallback; pick one approach.")
    if not items:
        items.append("No hard dependency declared for this scaffold.")
    return items


TUNING_TAG_RULES = {
    "career": ["career_name", "entry_level", "career_levels", "career_icon"],
    "trait": ["trait_name", "trait_description"],
    "buff": ["buff_name", "buff_description", "mood_type", "mood_weight", "animation_style"],
    "interaction": ["interaction_name", "pie_menu_priority", "interaction_distance"],
    "event": ["event_name", "event_type", "duration"],
    "achievement": ["achievement_name", "hidden"],
    "aspiration": ["aspiration_name"],
    "whim": ["whim_name", "whim_description", "priority", "duration"],
    "club": ["club_name", "club_icon"],
    "holiday": ["holiday_name", "holiday_icon"],
    "loot_action": ["loot_action_name"],
    "testset": ["test_set_name"],
    "relationship": ["relationship_name", "relationship_value"],
    "skill": ["skill_name", "skill_level"],
    "motive": ["motive_name", "decay_rate", "threshold"],
}


def wizard_ask(prompt: str, default: str = "") -> str:
    try:
        prompt_text = f"{PROMPT_GLYPH} {prompt}"
        if default:
            prompt_text += f" [{default}]"
        print(prompt_text, end=": ", flush=True)
        reply = sys.stdin.readline().strip()
    except EOFError:
        return default
    return reply or default


def new_career(proj: Path, name: str) -> Path:
    label = name
    d = proj / "src" / "xml_snippets" / f"{name}_career"
    _write(
        d / f"{name}_career.xml",
        "<?xml version='1.0' encoding='utf-8'?>\n"
        f"<!-- {name} career snippet -->\n"
        "<I d=\"0x00000000\">\n"
        "  <T n=\"career_name\">" + name + "</T>\n"
        "  <T n=\"career_icon\">0x00000000</T>\n"
        "  <U n=\"entry_level\">1</U>\n"
        "  <T n=\"career_track\">Adult</T>\n"
        "  <T n=\"career_levels\">\n"
        "    <L n=\"career_levels\">\n"
        "      <U>\n"
        "        <T n=\"level_title\">Level 1</T>\n"
        "        <U n=\"simoleon_pay\">500</U>\n"
        "        <U n=\"performance_goal\">1000</U>\n"
        "      </U>\n"
        "    </L>\n"
        "  </T>\n"
        "</I>\n",
    )
    _write(
        d / "README.txt",
        f"Career Snippet: {name}\n"
        "Enable via XML Injector snippet slot when required.\n"
        "\n"
        "Tuning notes:\n"
        "- Use career_levels for level progression.\n"
        "- Add testset references if changing autonomy.\n",
    )
    return d


def new_trait(proj: Path, name: str) -> Path:
    d = proj / "src" / "xml_snippets" / f"{name}_trait"
    _write(
        d / f"{name}_trait.xml",
        "<?xml version='1.0' encoding='utf-8'?>\n"
        f"<!-- {name} trait snippet -->\n"
        "<I d=\"0x00000000\">\n"
        "  <T n=\"trait_name\">" + name + "</T>\n"
        "  <T n=\"trait_description\">Replace with trait flavor text.</T>\n"
        "  <U n=\"trait_facial_priority\">0</U>\n"
        "  <L n=\"related_skills\">\n"
        "    <U>0x00000000</U>\n"
        "  </L>\n"
        "  <L n=\"related_buffs\">\n"
        "    <U>0x00000000</U>\n"
        "  </L>\n"
        "</I>\n",
    )
    _write(
        d / "README.txt",
        f"Trait Snippet: {name}\n"
        "Enable via XML Injector snippet slot when required.\n"
        "\n"
        "Tuning notes:\n"
        "- Use related_buffs for mood associations.\n"
        "- Use related_skills only if tied to skill gain.\n",
    )
    return d


def new_buff(proj: Path, name: str) -> Path:
    d = proj / "src" / "xml_snippets" / f"{name}_buff"
    _write(
        d / f"{name}_buff.xml",
        "<?xml version='1.0' encoding='utf-8'?>\n"
        f"<!-- {name} buff snippet -->\n"
        "<I d=\"0x00000000\">\n"
        "  <T n=\"buff_name\">" + name + "</T>\n"
        "  <T n=\"buff_description\">Replace with buff flavor text.</T>\n"
        "  <T n=\"mood_type\">Neutral</T>\n"
        "  <U n=\"mood_weight\">1</U>\n"
        "  <T n=\"animation_style\">None</T>\n"
        "  <L n=\"buff_commodities\">\n"
        "    <U>0x00000000</U>\n"
        "  </L>\n"
        "</I>\n",
    )
    _write(
        d / "README.txt",
        f"Buff Snippet: {name}\n"
        "Enable via XML Injector snippet slot when required.\n"
        "\n"
        "Tuning notes:\n"
        "- Use buff_commodities for motive effects.\n"
        "- Keep animation_style lightweight.\n",
    )
    return d


def new_interaction(proj: Path, name: str) -> Path:
    d = proj / "src" / "xml_snippets" / f"{name}_interaction"
    _write(
        d / f"{name}_interaction.xml",
        "<?xml version='1.0' encoding='utf-8'?>\n"
        f"<!-- {name} interaction snippet -->\n"
        "<I d=\"0x00000000\">\n"
        "  <T n=\"interaction_name\">" + name + "</T>\n"
        "  <T n=\"display_name\">0x00000000</T>\n"
        "  <T n=\"pie_menu_priority\">0</T>\n"
        "  <U n=\"interaction_distance\">0</U>\n"
        "  <L n=\"available_tests\">\n"
        "    <V t=\"user_facing\">\n"
        "      <U n=\"user_facing\" n=\"test_specific_filter\" s=\"7484554514949210645,16764977504022179238\"/>\n"
        "    </V>\n"
        "  </L>\n"
        "  <L n=\"super_affordances\">\n"
        "    <V t=\"super_affordance\"/>\n"
        "  </L>\n"
        "</I>\n",
    )
    _write(
        d / "README.txt",
        f"Interaction Snippet: {name}\n"
        "Enable via XML Injector snippet slot when required.\n"
        "\n"
        "Tuning notes:\n"
        "- Prefer tags over exact object names.\n"
        "- Add super_affordances for fallback behavior.\n",
    )
    return d


def new_event(proj: Path, name: str) -> Path:
    d = proj / "src" / "xml_snippets" / f"{name}_event"
    _write(
        d / f"{name}_event.xml",
        "<?xml version='1.0' encoding='utf-8'?>\n"
        f"<!-- {name} event snippet -->\n"
        "<I d=\"0x00000000\">\n"
        "  <T n=\"event_name\">" + name + "</T>\n"
        "  <T n=\"event_type\">Social</T>\n"
        "  <U n=\"duration\">120</U>\n"
        "  <T n=\"icon_resource\">0x00000000</T>\n"
        "  <L n=\"stakeables\">\n"
        "    <V t=\"stakeable_list\"/>\n"
        "  </L>\n"
        "  <L n=\"actions\">\n"
        "    <V t=\"action\"/>\n"
        "  </L>\n"
        "</I>\n",
    )
    _write(
        d / "README.txt",
        f"Event Snippet: {name}\n"
        "Enable via XML Injector snippet slot when required.\n"
        "\n"
        "Tuning notes:\n"
        "- Use actions list for loot-style outcomes.\n"
        "- Keep stakeables small to avoid spam.\n",
    )
    return d


def new_achievement(proj: Path, name: str) -> Path:
    d = proj / "src" / "xml_snippets" / f"{name}_achievement"
    _write(
        d / f"{name}_achievement.xml",
        "<?xml version='1.0' encoding='utf-8'?>\n"
        f"<!-- {name} achievement snippet -->\n"
        "<I d=\"0x00000000\">\n"
        "  <T n=\"achievement_name\">" + name + "</T>\n"
        "  <T n=\"display_name\">0x00000000</T>\n"
        "  <T n=\"description\">0x00000000</T>\n"
        "  <U n=\"hidden\">0</U>\n"
        "  <L n=\"prerequisites\">\n"
        "    <U>0x00000000</U>\n"
        "  </L>\n"
        "</I>\n",
    )
    _write(
        d / "README.txt",
        f"Achievement Snippet: {name}\n"
        "Enable via XML Injector snippet slot when required.\n"
        "\n"
        "Tuning notes:\n"
        "- Use prerequisites for unlock chains.\n"
        "- Use display_name/description STBL keys.\n",
    )
    return d


def new_xml_snippet(proj: Path, name: str) -> Path:
    d = proj / "src" / "xml_snippets" / name
    _write(
        d / f"{name}.xml",
        "<?xml version='1.0' encoding='utf-8'?>\n"
        f"<!-- {name} snippet -->\n"
        "<Snippets>\n"
        "  <!-- Replace this body with an XML Injector snippet or tuning fragment -->\n"
        "  <I d=\"0x00000000\">\n"
        "    <T n=\"label\">" + name + "</T>\n"
        "  </I>\n"
        "</Snippets>\n",
    )
    _write(
        d / "README.txt",
        f"XML Snippet: {name}\n"
        "Enable via XML Injector snippet slot when required.\n"
        "\n"
        "Tuning notes:\n"
        "- Keep snippets narrow.\n"
        "- Document referenced tuning files/instances.\n",
    )
    return d


def new_ts4script(proj: Path, name: str) -> Path:
    d = proj / "src" / "ts4script" / name
    _write(
        d / "main.py",
        "import sims4.commands\nimport services\n\n\n@sims4.commands.Command('your.command.here', command_type=sims4.commands.CommandType.Live)\ndef your_command(_connection=None):\n    output = sims4.commands.output(_connection)\n    output('Hello from mod script!')\n",
    )
    _write(
        d / "manifest.json",
        '{\n  "name": "' + name + '",\n  "version": "0.1.0",\n  "entry": "main.py"\n}\n',
    )
    _write(
        d / "README.txt",
        f"Script Mod: {name}\n"
        "Entry: main.py\n"
        "\n"
        "Tuning notes:\n"
        "- Keep scripts deterministic.\n"
        "- Avoid hard-coded paths.\n"
        "- Document dependencies here.\n",
    )
    return d


def new_package_mod(proj: Path, name: str) -> Path:
    d = proj / "src" / "package" / name
    _write(
        d / f"{name}.package.template",
        "Package binaries require Sims 4 Studio/s4pe + Tdesc Builder + EA resource tools to author and sign.\nSee current packaging docs for MODS_PACKAGE/EXTRA resource structure and tdesc files.\n",
    )
    _write(
        d / "README.txt",
        f"Package Tuning: {name}\n"
        "Purpose: behavioral tuning/custom-content base project.\n"
        "\n"
        "Tuning notes:\n"
        "- Build tdesc manifest before export.\n"
        "- Write STBL entries for visible strings.\n",
    )
    return d


def new_aspiration(proj: Path, name: str) -> Path:
    d = proj / "src" / "xml_snippets" / f"{name}_aspiration"
    _write(
        d / f"{name}_aspiration.xml",
        "<?xml version='1.0' encoding='utf-8'?>\n"
        f"<!-- {name} aspiration snippet -->\n"
        "<I d=\"0x00000000\">\n"
        "  <T n=\"aspiration_name\">" + name + "</T>\n"
        "  <T n=\"description\">0x00000000</T>\n"
        "  <U n=\"hidden\">0</U>\n"
        "  <L n=\"milestones\">\n"
        "    <V t=\"aspiration_milestone\"/>\n"
        "  </L>\n"
        "</I>\n",
    )
    _write(
        d / "README.txt",
        f"Aspiration Snippet: {name}\n"
        "Enable via XML Injector snippet slot when required.\n"
        "\n"
        "Tuning notes:\n"
        "- Use milestones for step progression.\n"
        "- Use description STBL key for visible text.\n",
    )
    return d


def new_whim(proj: Path, name: str) -> Path:
    d = proj / "src" / "xml_snippets" / f"{name}_whim"
    _write(
        d / f"{name}_whim.xml",
        "<?xml version='1.0' encoding='utf-8'?>\n"
        f"<!-- {name} whim snippet -->\n"
        "<I d=\"0x00000000\">\n"
        "  <T n=\"whim_name\">" + name + "</T>\n"
        "  <T n=\"whim_description\">Replace with whim flavor text.</T>\n"
        "  <U n=\"priority\">1</U>\n"
        "  <U n=\"duration\">120</U>\n"
        "  <L n=\"related_buffs\">\n"
        "    <U>0x00000000</U>\n"
        "  </L>\n"
        "</I>\n",
    )
    _write(
        d / "README.txt",
        f"Whim Snippet: {name}\n"
        "Enable via XML Injector snippet slot when required.\n"
        "\n"
        "Tuning notes:\n"
        "- Use related_buffs to bias whim selection.\n"
        "- Keep duration short to avoid spam.\n",
    )
    return d


def new_club(proj: Path, name: str) -> Path:
    d = proj / "src" / "xml_snippets" / f"{name}_club"
    _write(
        d / f"{name}_club.xml",
        "<?xml version='1.0' encoding='utf-8'?>\n"
        f"<!-- {name} club snippet -->\n"
        "<I d=\"0x00000000\">\n"
        "  <T n=\"club_name\">" + name + "</T>\n"
        "  <U n=\"club_icon\">0x00000000</U>\n"
        "  <L n=\"club_rules\">\n"
        "    <V t=\"club_rule\"/>\n"
        "  </L>\n"
        "  <L n=\"member_preferences\">\n"
        "    <V t=\"club_member_preference\"/>\n"
        "  </L>\n"
        "</I>\n",
    )
    _write(
        d / "README.txt",
        f"Club Snippet: {name}\n"
        "Enable via XML Injector snippet slot when required.\n"
        "\n"
        "Tuning notes:\n"
        "- Use club_rules for gathering behavior.\n"
        "- Balance member_preferences carefully.\n",
    )
    return d


def new_holiday(proj: Path, name: str) -> Path:
    d = proj / "src" / "xml_snippets" / f"{name}_holiday"
    _write(
        d / f"{name}_holiday.xml",
        "<?xml version='1.0' encoding='utf-8'?>\n"
        f"<!-- {name} holiday snippet -->\n"
        "<I d=\"0x00000000\">\n"
        "  <T n=\"holiday_name\">" + name + "</T>\n"
        "  <U n=\"holiday_icon\">0x00000000</U>\n"
        "  <L n=\"traditions\">\n"
        "    <V t=\"holiday_tradition\"/>\n"
        "  </L>\n"
        "  <L n=\"decorations\">\n"
        "    <V t=\"holiday_decoration\"/>\n"
        "  </L>\n"
        "</I>\n",
    )
    _write(
        d / "README.txt",
        f"Holiday Snippet: {name}\n"
        "Enable via XML Injector snippet slot when required.\n"
        "\n"
        "Tuning notes:\n"
        "- Use traditions for rituals and rewards.\n"
        "- Use decorations for neighborhood visuals.\n",
    )
    return d


def new_loot_action(proj: Path, name: str) -> Path:
    d = proj / "src" / "xml_snippets" / f"{name}_loot_action"
    _write(
        d / f"{name}_loot_action.xml",
        "<?xml version='1.0' encoding='utf-8'?>\n"
        f"<!-- {name} loot action snippet -->\n"
        "<I d=\"0x00000000\">\n"
        "  <T n=\"loot_action_name\">" + name + "</T>\n"
        "  <L n=\"actions\">\n"
        "    <V t=\"loot_action\"/>\n"
        "  </L>\n"
        "</I>\n",
    )
    _write(
        d / "README.txt",
        f"Loot Action Snippet: {name}\n"
        "Enable via XML Injector snippet slot when required.\n"
        "\n"
        "Tuning notes:\n"
        "- Keep loot chains short.\n"
        "- Group related state changes in one loot action.\n",
    )
    return d


def new_testset(proj: Path, name: str) -> Path:
    d = proj / "src" / "xml_snippets" / f"{name}_testset"
    _write(
        d / f"{name}_testset.xml",
        "<?xml version='1.0' encoding='utf-8'?>\n"
        f"<!-- {name} testset snippet -->\n"
        "<I d=\"0x00000000\">\n"
        "  <T n=\"testset_name\">" + name + "</T>\n"
        "  <L n=\"tests\">\n"
        "    <V t=\"test\"/>\n"
        "  </L>\n"
        "</I>\n",
    )
    _write(
        d / "README.txt",
        f"Testset Snippet: {name}\n"
        "Enable via XML Injector snippet slot when required.\n"
        "\n"
        "Tuning notes:\n"
        "- Use tests for affordance gating.\n"
        "- Keep tests deterministic and cheap.\n",
    )
    return d


def new_relationship(proj: Path, name: str) -> Path:
    d = proj / "src" / "xml_snippets" / f"{name}_relationship"
    _write(
        d / f"{name}_relationship.xml",
        "<?xml version='1.0' encoding='utf-8'?>\n"
        f"<!-- {name} relationship snippet -->\n"
        "<I d=\"0x00000000\">\n"
        "  <T n=\"relationship_name\">" + name + "</T>\n"
        "  <U n=\"relationship_value\">0</U>\n"
        "  <L n=\"related_traits\">\n"
        "    <U>0x00000000</U>\n"
        "  </L>\n"
        "</I>\n",
    )
    _write(
        d / "README.txt",
        f"Relationship Snippet: {name}\n"
        "Enable via XML Injector snippet slot when required.\n"
        "\n"
        "Tuning notes:\n"
        "- Use relationship_value for baseline.\n"
        "- Use related_traits for sentiment/perk hooks.\n",
    )
    return d


def new_skill(proj: Path, name: str) -> Path:
    d = proj / "src" / "xml_snippets" / f"{name}_skill"
    _write(
        d / f"{name}_skill.xml",
        "<?xml version='1.0' encoding='utf-8'?>\n"
        f"<!-- {name} skill snippet -->\n"
        "<I d=\"0x00000000\">\n"
        "  <T n=\"skill_name\">" + name + "</T>\n"
        "  <U n=\"skill_level\">1</U>\n"
        "  <L n=\"skill_effects\">\n"
        "    <V t=\"skill_effect\"/>\n"
        "  </L>\n"
        "</I>\n",
    )
    _write(
        d / "README.txt",
        f"Skill Snippet: {name}\n"
        "Enable via XML Injector snippet slot when required.\n"
        "\n"
        "Tuning notes:\n"
        "- Use skill_effects for unlocks.\n"
        "- Keep progression curve smooth.\n",
    )
    return d


def new_motive(proj: Path, name: str) -> Path:
    d = proj / "src" / "xml_snippets" / f"{name}_motive"
    _write(
        d / f"{name}_motive.xml",
        "<?xml version='1.0' encoding='utf-8'?>\n"
        f"<!-- {name} motive snippet -->\n"
        "<I d=\"0x00000000\">\n"
        "  <T n=\"motive_name\">" + name + "</T>\n"
        "  <U n=\"decay_rate\">1</U>\n"
        "  <U n=\"threshold\">100</U>\n"
        "  <L n=\"motive_buffs\">\n"
        "    <U>0x00000000</U>\n"
        "  </L>\n"
        "</I>\n",
    )
    _write(
        d / "README.txt",
        f"Motive Snippet: {name}\n"
        "Enable via XML Injector snippet slot when required.\n"
        "\n"
        "Tuning notes:\n"
        "- Use decay_rate for pacing.\n"
        "- Use motive_buffs for state transitions.\n",
    )
    return d


def validate_project(proj: Path, strict: bool = False) -> int:
    issues = 0
    if strict:
        cfg = proj / "s4modconfig.yaml"
        if not cfg.exists():
            issues += 1
        else:
            txt = cfg.read_text(encoding="utf-8")
            if "ReplaceMe" in txt:
                issues += 1

    for xml in proj.rglob("*.xml"):
        try:
            txt = xml.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            issues += 1
            continue
        if not txt.lstrip().startswith("<?xml"):
            issues += 1
            continue
        stem = xml.name
        for kind, tags in TUNING_TAG_RULES.items():
            if stem.endswith(f"_{kind}.xml") or f"_{kind}." in stem or kind == stem:
                missing = [t for t in tags if f'<T n="{t}">' not in txt and f'<U n="{t}">' not in txt]
                if missing:
                    issues += len(missing)

    pkg_candidates = list(proj.rglob("*.package")) + list(proj.rglob("*.package.template"))
    xml_or_script_count = len(list(proj.rglob("*.xml"))) + len(list(proj.rglob("*.py")))
    if proj.joinpath("src", "package").exists() and not pkg_candidates and xml_or_script_count:
        pass
    elif not pkg_candidates:
        issues += 1

    return max(issues, 0)


def build_project(proj: Path, release: bool = False) -> Path:
    cfg_path = proj / "s4modconfig.yaml"
    mod_name = "mod"
    if cfg_path.exists():
        for line in cfg_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("mod_name:"):
                mod_name = line.split(":", 1)[1].strip() or mod_name
                break

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = proj / "dist" / f"{mod_name}-{stamp}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(proj.rglob("*")):
            if path.is_dir():
                continue
            rel = path.relative_to(proj)
            txt = str(rel)
            if txt.startswith("dist/") or txt.startswith("tmp/"):
                continue
            if txt == ".gitignore" or txt.startswith(".git"):
                continue
            zf.write(path, rel)
    return out


def install_to_mods(proj: Path, mods_dir: str | None = None) -> Path:
    target_path = None
    if mods_dir:
        target_path = Path(mods_dir)
    else:
        docs = Path.home() / "Documents"
        mods_candidate = docs / "Electronic Arts" / "The Sims 4" / "Mods"
        if not mods_candidate.exists():
            raise SystemExit(f"Auto-detected Mods folder not found: {mods_candidate}")
        target_path = mods_candidate

    target = target_path / proj.name
    if target.exists():
        raise SystemExit(f"Target already exists: {target}")
    shutil.copytree(proj, target)
    for extra in ["dist", "tmp", ".git"]:
        d = target / extra
        if d.exists():
            shutil.rmtree(d)
    print(f"Installed project copy into: {target}")
    return target


def doctor_check() -> int:
    issues = 0
    checks = []
    if sys.version_info < (3, 10):
        issues += 1
        checks.append(("Python", "\033[1;31mFAIL\033[0m Python 3.10+"))
    else:
        checks.append(("Python", "\033[1;32mOK\033[0m Python >= 3.10"))

    sims_docs = Path.home() / "Documents" / "Electronic Arts" / "The Sims 4"
    sims_ok = sims_docs.exists()
    sims_ok_text = "\033[1;32mOK\033[0m" if sims_ok else "\033[1;31mMISSING\033[0m"
    checks.append(("Sims Docs", f"{sims_ok_text} Sims 4 Documents"))

    if sims_ok:
        mods = sims_docs / "Mods"
        mods_text = "\033[1;32mOK\033[0m" if mods.exists() else "\033[1;33mMISSING\033[0m"
        checks.append(("Mods Folder", f"{mods_text} {mods}"))

    print(_status_panel("accessibility_verdict: true", _kv_block(checks), command="doctor"))
    return issues


def ensure_game_python() -> None:
    paths = [
        Path.home() / "Documents" / "Electronic Arts" / "The Sims 4" / "Python",
        Path("C:/Program Files/Electronic Arts/The Sims 4/Python"),
        Path("C:/Program Files (x86)/Electronic Arts/The Sims 4/Python"),
    ]
    found = []
    for p in paths:
        if p.exists():
            for f in sorted(p.rglob("*"))[:50]:
                found.append(str(f))
            break

    rows = []
    if found:
        rows.append(("Game Python", "\033[1;32mOK\033[0m detected"))
        for item in found[:8]:
            rows.append(("", item))
    else:
        rows.append(("Game Python", "\033[1;31mMISSING\033[0m"))
        rows.append(("Hint", "<GAME>/Python/ + base/core/simulation/generated zip"))

    print(_status_panel("game-python", _kv_block(rows), command="game-python"))


def print_help(*, is_subcommand=False, command="", error="") -> None:
    panel = []
    panel.extend(_section("PORTABLE SIMS 4 MOD CONSTRUCTION CLI", []))
    if error:
        panel.extend(_section(f"\033[1;31mERROR\033[0m", [error]))

    if is_subcommand:
        panel.extend(_section(f"COMMAND \033[1;37m{command}\033[0m", []))
        panel.extend(_section("USAGE", [f"  {_prompt()}s4mod_cli {command} [options]"]))
        if command == "init":
            panel.extend(_section("ARGS", ["  name       Project directory / mod name"]))
        elif command == "new":
            panel.extend(_section("ARGS", ["  where      Existing project path", "  kind       xml_snippet|ts4script|package|career|trait|buff|interaction|event|achievement|aspiration|whim|club|holiday|loot_action|testset|relationship|skill|motive", "  name       Artifact/module name"]))
        elif command == "validate":
            panel.extend(_section("ARGS", ["  path       Project path, default '.'.", "  --strict   Treat template values as errors."]))
        elif command == "build":
            panel.extend(_section("ARGS", ["  path       Project path, default '.'.", "  --release  Release packaging semantics."]))
        elif command == "package":
            panel.extend(_section("ARGS", ["  path       Project path, default '.'.", "  --out-dir  Output directory for release zip."]))
        elif command == "install":
            panel.extend(_section("ARGS", ["  path       Project path, default '.'.", "  --to-dir   Mods root or custom directory."]))
        elif command == "generate":
            panel.extend(_section("ARGS", ["  mod_type   Supported mod type", "  name       Module or object name", "  --param k=v   Scalar tuning params, repeatable."]))
        panel.extend(_section("NOTES", ["  Status: \033[1;32mVERIFIED\033[0m = exercised end-to-end; \033[1;33mLOCAL PATH REQUIRED\033[0m = needs environment-specific value."]))
        panel.extend(_section("FOOTER", ["  \033[1;32m❯\033[0m s4mod_cli <command>    Enter a command to start.", "  Run 's4mod_cli doctor'   Verify environment paths.", "  Run 's4mod_cli help <cmd>'  Show command help."]))
    else:
        panel.extend(
            _section(
                "COMMANDS",
                [
                    "  \033[1;37mCOMMAND\033[0m          \033[1;37mDESCRIPTION / STATUS\033[0m",
                    "  \033[1;37m-------\033[0m          \033[1;37m-------------------\033[0m",
                    "  init <name>           Initialize a new mod project.                            \033[1;32m[VERIFIED]\033[0m",
                    "  new <where> <kind>    Create xml_snippet, ts4script, package, career, trait, buff, interaction, event, or achievement artifact.      \033[1;32m[VERIFIED]\033[0m",
                    "                       <kind>: xml_snippet | ts4script | package | career | trait | buff | interaction | event | achievement | aspiration | whim | club | holiday | loot_action | testset | relationship | skill | motive",
                    "  validate [path]       Validate XML/packaging hygiene.                         \033[1;32m[VERIFIED]\033[0m",
                    "  build [path]          Package current artifacts into a release zip.           \033[1;32m[VERIFIED]\033[0m",
                    "  package [path]        Create release zip excluding dist/tmp/.git.                \033[1;32m[VERIFIED]\033[0m",
                    "  install [path]        Install project into your Mods folder.                  \033[1;33m[LOCAL]\033[0m",
                    "  doctor                Run environment and path checks.                        \033[1;32m[VERIFIED]\033[0m",
                    "  version               Print CLI version.",
                    "  help <cmd>            Show help for a subcommand.",
                    "  generate <type> <name> Generate a Sims 4 mod scaffold.",
                    "  wizard <type> [name]     Guided mod creation with brain advice.",
                    "  changelog [path]         Add/update CHANGELOG.md.",
                ],
            )
        )
        panel.extend(_section("STATUS KEY", ["  \033[1;32m[VERIFIED]\033[0m   = exercised end-to-end", "  \033[1;33m[LOCAL]\033[0m     = needs environment-specific value", "  \033[1;31m[BLOCKED]\033[0m   = missing dependency / environment"]))
        panel.extend(_section("FOOTER", ["  \033[1;32m❯\033[0m s4mod_cli <command>    Enter a command to start.", "  Run 's4mod_cli doctor'   Verify environment paths.", "  Run 's4mod_cli help <cmd>'  Show command help."]))

    print(_status_panel(f"{'help' if is_subcommand else 's4mod_cli'}", panel, command=command if is_subcommand else ""))

def package_release(proj: Path, out_dir: Path | None = None) -> Path:
    cfg_path = proj / "s4modconfig.yaml"
    mod_name = proj.name
    if cfg_path.exists():
        for line in cfg_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("mod_name:"):
                mod_name = line.split(":", 1)[1].strip() or mod_name
                break

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = out_dir or (proj / "dist")
    base.mkdir(parents=True, exist_ok=True)
    out = base / f"{mod_name}-release-{stamp}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(proj.rglob("*")):
            if path.is_dir():
                continue
            rel = path.relative_to(proj)
            txt = str(rel)
            if txt.startswith("dist/") or txt.startswith("tmp/"):
                continue
            if txt == ".gitignore" or txt.startswith(".git"):
                continue
            if txt == "OWNERS-GUIDE.txt":
                continue
            zf.write(path, rel)
    return out

def print_subcommand_help(command: str) -> None:
    print_help(is_subcommand=True, command=command)

def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if not argv or argv[:1] in (["-h"], ["--help"]):
        print_help(is_subcommand=False, command="")
        return 0

    command = argv[0]

    if command == "help":
        target = argv[1] if len(argv) > 1 else "s4mod_cli"
        if target == "s4mod_cli":
            print_help(is_subcommand=False, command="")
        else:
            print_subcommand_help(target)
        return 0

    if command == "init":
        if not argv[1:]:
            print_help(is_subcommand=True, command="init", error="Missing <name> argument.")
            return 2
        proj = init_project(argv[1])
        print(
            _status_panel(
                "init",
                _meta_block("verified", "Ready", argv[1])
                + [f"Files: {', '.join(PROJECT_FILES)}"],
                command="init",
            )
        )
        _advance_pipeline_if_artifact(proj, "s4modconfig.yaml")
        _advance_pipeline_if_artifact(proj, "mod_notes.txt")
        return 0

    if command == "new":
        if len(argv) < 4:
            print_help(is_subcommand=True, command="new", error="Expected: new <where> <kind> <name>")
            return 2
        _, where, kind, name = argv[:4]
        proj = _existing_project(where)
        factory = {
            "xml_snippet": new_xml_snippet,
            "ts4script": new_ts4script,
            "package": new_package_mod,
            "career": new_career,
            "trait": new_trait,
            "buff": new_buff,
            "interaction": new_interaction,
            "event": new_event,
            "achievement": new_achievement,
            "aspiration": new_aspiration,
            "whim": new_whim,
            "club": new_club,
            "holiday": new_holiday,
            "loot_action": new_loot_action,
            "testset": new_testset,
            "relationship": new_relationship,
            "skill": new_skill,
            "motive": new_motive,
        }.get(kind)
        if factory is None:
            print_help(is_subcommand=True, command="new", error=f"Unknown kind: {kind}")
            return 2
        print(_status_panel("new", _meta_block("verified", "Created", kind) + [f"Path: {factory(proj, name)}"], command="new"))
        _advance_pipeline_if_artifact(proj, f"src/{kind}")
        _advance_pipeline_if_artifact(proj, "src/xml_snippets")
        _advance_pipeline_if_artifact(proj, "src/ts4script")
        _advance_pipeline_if_artifact(proj, "src/package")
        return 0

    if command == "validate":
        path = argv[1] if len(argv) > 1 else "."
        strict = "--strict" in argv
        proj = _existing_project(path)
        issues = validate_project(proj, strict=strict)
        state = "ok" if issues == 0 else "fail"
        print(_status_panel("validate", _meta_block(state, "Validation", f"{issues} issue{'s' if issues != 1 else ''}"), command="validate"))
        _advance_pipeline_if_artifact(proj, "docs/validation_report.txt")
        _advance_pipeline_if_artifact(proj, "tmp/lint_report.txt")
        return issues

    if command == "build":
        path = argv[1] if len(argv) > 1 else "."
        release = "--release" in argv
        proj = _existing_project(path)
        out = build_project(proj, release=release)
        print(_status_panel("build", _meta_block("verified", "Built", str(out)), command="build"))
        _advance_pipeline_if_artifact(proj, "dist")
        return 0

    if command == "package":
        path = argv[1] if len(argv) > 1 else "."
        out_dir = None
        if "--out-dir" in argv:
            idx = argv.index("--out-dir")
            if idx + 1 < len(argv):
                out_dir = argv[idx + 1]
        proj = _existing_project(path)
        out = package_release(proj, out_dir=Path(out_dir) if out_dir else None)
        print(_status_panel("package", _meta_block("verified", "Packaged", str(out)), command="package"))
        _advance_pipeline_if_artifact(proj, "dist")
        _advance_pipeline_if_artifact(proj, "tmp/release_manifest.txt")
        return 0

    if command == "install":
        path = argv[1] if len(argv) > 1 else "."
        to_dir = None
        if "--to-dir" in argv:
            idx = argv.index("--to-dir")
            if idx + 1 < len(argv):
                to_dir = argv[idx + 1]
        target = install_to_mods(_existing_project(path), mods_dir=to_dir)
        print(_status_panel("install", _meta_block("local", "Installed", str(target)), command="install"))
        return 0

    if command == "doctor":
        return doctor_check()

    if command == "version":
        print(_status_panel("version", _meta_block("ok", "Version", "s4mod_cli v0.1.0-dev"), command="version"))
        return 0

    if command == "pipeline":
        if len(argv) > 1 and argv[1] == "tune":
            phase = argv[2] if len(argv) > 2 else None
            path = argv[3] if len(argv) > 3 and argv[2] else argv[2] if len(argv) > 2 else "."
            if phase not in PIPELINE_PHASES:
                print_help(is_subcommand=True, command="pipeline", error="Expected: pipeline tune <phase> [path]")
                return 2
            proj = _existing_project(path)
            meta = PIPELINE_META.get(phase, {})
            rows = _meta_block("ok", f"Tune: {meta.get('name', phase)}", meta.get("hint", ""))
            rows += ["", f"{C_BOLD_WHITE}Example:{C_RESET}", f"  - {meta.get('next', '')}", f"{C_BOLD_WHITE}Artifact:{C_RESET} {meta.get('artifact', '')}"]
            print(_status_panel("pipeline-tune", rows, command="pipeline tune"))
            return 0
        path = argv[1] if len(argv) > 1 else "."
        proj = _existing_project(path)
        print(print_pipeline_status(proj))
        return 0

    if command == "pipeline-next":
        path = argv[1] if len(argv) > 1 else "."
        proj = _existing_project(path)
        print(print_pipeline_next(proj))
        return 0

    if command == "pipeline-unlock":
        path = argv[1] if len(argv) > 1 else "."
        proj = _existing_project(path)
        print(unlock_current_phase(proj))
        return 0

    if command == "pipeline-reset":
        path = argv[1] if len(argv) > 1 else "."
        proj = _existing_project(path)
        print(reset_pipeline(proj))
        return 0

    if command == "game-python":
        ensure_game_python()
        return 0

    if command == "generate":
        if len(argv) < 3:
            print_help(is_subcommand=True, command="generate", error="Expected: generate <mod_type> <name>")
            return 2
        mod_type = argv[1]
        name = argv[2]
        params = _parse_kv_tokens(argv[3:])
        factory = {
            "xml_snippet": new_xml_snippet,
            "ts4script": new_ts4script,
            "package": new_package_mod,
            "career": new_career,
            "trait": new_trait,
            "buff": new_buff,
            "interaction": new_interaction,
            "event": new_event,
            "achievement": new_achievement,
            "aspiration": new_aspiration,
            "whim": new_whim,
            "club": new_club,
            "holiday": new_holiday,
            "loot_action": new_loot_action,
            "testset": new_testset,
            "relationship": new_relationship,
            "skill": new_skill,
            "motive": new_motive,
        }.get(mod_type)
        if factory is None:
            print_help(is_subcommand=True, command="generate", error=f"Unknown mod type: {mod_type}")
            return 2

        try:
            proj = _existing_project(".")
        except SystemExit:
            proj = _find_or_create_temp_project(name)

        d = factory(proj, name)
        _apply_params(proj, mod_type, name, params)
        preset = wizard_presets(mod_type)
        advice = compatibility_advice(mod_type)
        deps = dependency_notes(mod_type)
        note_kv = {k.replace("note.", "", 1): v for k, v in params.items() if k.startswith("note.")}
        if note_kv:
            state = load_pipeline_state(proj)
            state.setdefault("notes", {}).update(note_kv)
            save_pipeline_state(proj, state)
        panel = [
            _meta_block("verified", "Generated", f"{mod_type}: {name}")[0],
            f"Path: {d}",
            "",
            f"{C_BOLD_WHITE}Brain Advice:{C_RESET}",
            f"  {advice}",
            "",
            f"{C_BOLD_WHITE}Dependencies:{C_RESET}",
        ] + [f"  - {item}" for item in deps] + [
            "",
            f"{C_BOLD_WHITE}Next Steps:{C_RESET}",
        ] + [f"  - {item}" for item in preset.get("next_steps", [])]
        _advance_pipeline_if_artifact(proj, f"src/{mod_type}")
        _advance_pipeline_if_artifact(proj, "src/xml_snippets")
        _advance_pipeline_if_artifact(proj, "src/ts4script")
        _advance_pipeline_if_artifact(proj, "src/package")
        if note_kv:
            panel += [
                "",
                f"{C_BOLD_WHITE}Pipeline Notes Saved:{C_RESET}",
            ] + [f"  {k}: {v}" for k, v in note_kv.items()]
        print(_status_panel("generate", panel, command="generate"))
        return 0

    if command == "changelog":
        path = argv[1] if len(argv) > 1 else "."
        try:
            proj = _existing_project(path)
        except SystemExit:
            print_help(is_subcommand=True, command="changelog", error=f"Not a valid project: {path}")
            return 2
        changelog = proj / "CHANGELOG.md"
        today = datetime.now().strftime("%Y-%m-%d")
        content = f"# Changelog\n\n## {today}\n- Initial scaffold.\n"
        if changelog.exists():
            content = changelog.read_text(encoding="utf-8") + "\n" + content
        _write(changelog, content)
        print(_status_panel("changelog", _meta_block("verified", "Created", str(changelog)), command="changelog"))
        _advance_pipeline_if_artifact(proj, "CHANGELOG.md")
        return 0

    if command == "tune-ids":
        if len(argv) < 2:
            print_help(is_subcommand=True, command="tune-ids", error="Expected: tune-ids <path>")
            return 2
        proj = _existing_project(argv[1])
        touched = []
        for xml in sorted(proj.rglob("*.xml")):
            txt = xml.read_text(encoding="utf-8", errors="ignore")
            updated = txt
            updated = updated.replace('<I d="0x00000000">', '<I d="' + _tuning_instance(xml.stem) + '">')
            updated = updated.replace("<I d=\"0x00000000\">", "<I d=\"" + _tuning_instance(xml.stem) + "\">")
            updated = updated.replace("<T n=\"career_icon\">0x00000000</T>", "<T n=\"career_icon\">" + _tuning_instance(xml.stem, "_icon") + "</T>")
            updated = updated.replace("<T n=\"display_name\">0x00000000</T>", "<T n=\"display_name\">" + _tuning_instance(xml.stem, "_display") + "</T>")
            updated = updated.replace("<T n=\"description\">0x00000000</T>", "<T n=\"description\">" + _tuning_instance(xml.stem, "_desc") + "</T>")
            updated = updated.replace("<T n=\"icon_resource\">0x00000000</T>", "<T n=\"icon_resource\">" + _tuning_instance(xml.stem, "_icon") + "</T>")
            updated = updated.replace("<U n=\"club_icon\">0x00000000</U>", "<U n=\"club_icon\">" + _tuning_instance(xml.stem, "_icon") + "</U>")
            updated = updated.replace("<U n=\"holiday_icon\">0x00000000</U>", "<U n=\"holiday_icon\">" + _tuning_instance(xml.stem, "_icon") + "</U>")
            idx = 0
            def _replace_u(match):
                nonlocal idx
                suffix = f"_item{idx}"
                idx += 1
                return "<U>" + _tuning_instance(xml.stem, suffix) + "</U>"
            updated = re.sub(r"<U>0x00000000</U>", _replace_u, updated)
            updated = updated.replace("<T n=\"trait_facial_priority\">0</T>", "<T n=\"trait_facial_priority\">" + str(_fnv1a_64(xml.stem) & 0xFFFFFFFF) + "</T>")
            updated = updated.replace("<U n=\"mood_weight\">1</U>", "<U n=\"mood_weight\">1</U>")
            updated = updated.replace("<T n=\"animation_style\">None</T>", "<T n=\"animation_style\">None</T>")
            updated = updated.replace("<U n=\"interaction_distance\">0</U>", "<U n=\"interaction_distance\">" + str(_fnv1a_64(xml.stem + "_distance") & 0xFFFFFFFF) + "</U>")
            updated = updated.replace("<T n=\"pie_menu_priority\">0</T>", "<T n=\"pie_menu_priority\">" + str(_fnv1a_64(xml.stem + "_menu") & 0xFFFFFFFF) + "</T>")
            updated = updated.replace("<T n=\"event_name\">" + xml.stem + "</T>", "<T n=\"event_name\">" + xml.stem + "</T>")
            updated = updated.replace("<U n=\"duration\">120</U>", "<U n=\"duration\">120</U>")
            updated = updated.replace("<U n=\"hidden\">0</U>", "<U n=\"hidden\">0</U>")
            updated = updated.replace("<U n=\"entry_level\">1</U>", "<U n=\"entry_level\">1</U>")
            updated = updated.replace("<T n=\"career_track\">Adult</T>", "<T n=\"career_track\">Adult</T>")
            updated = updated.replace("<U n=\"simoleon_pay\">500</U>", "<U n=\"simoleon_pay\">500</U>")
            updated = updated.replace("<U n=\"performance_goal\">1000</U>", "<U n=\"performance_goal\">1000</U>")
            updated = updated.replace("<T n=\"level_title\">Level 1</T>", "<T n=\"level_title\">Level 1</T>")
            updated = updated.replace("<T n=\"display_name\">" + xml.stem + "</T>", "<T n=\"display_name\">" + xml.stem + "</T>")
            updated = updated.replace("<T n=\"description\">Replace with " + xml.stem + " flavor text.</T>", "<T n=\"description\">Replace with " + xml.stem + " flavor text.</T>")
            updated = updated.replace("<!-- " + xml.stem + " trait snippet -->", "<!-- " + xml.stem + " trait snippet -->")
            updated = updated.replace("<!-- " + xml.stem + " buff snippet -->", "<!-- " + xml.stem + " buff snippet -->")
            updated = updated.replace("<!-- " + xml.stem + " interaction snippet -->", "<!-- " + xml.stem + " interaction snippet -->")
            updated = updated.replace("<!-- " + xml.stem + " event snippet -->", "<!-- " + xml.stem + " event snippet -->")
            updated = updated.replace("<!-- " + xml.stem + " achievement snippet -->", "<!-- " + xml.stem + " achievement snippet -->")
            updated = updated.replace("<!-- " + xml.stem + " aspiration snippet -->", "<!-- " + xml.stem + " aspiration snippet -->")
            updated = updated.replace("<!-- " + xml.stem + " whim snippet -->", "<!-- " + xml.stem + " whim snippet -->")
            updated = updated.replace("<!-- " + xml.stem + " club snippet -->", "<!-- " + xml.stem + " club snippet -->")
            updated = updated.replace("<!-- " + xml.stem + " holiday snippet -->", "<!-- " + xml.stem + " holiday snippet -->")
            updated = updated.replace("<!-- " + xml.stem + " loot action snippet -->", "<!-- " + xml.stem + " loot action snippet -->")
            updated = updated.replace("<!-- " + xml.stem + " testset snippet -->", "<!-- " + xml.stem + " testset snippet -->")
            updated = updated.replace("<!-- " + xml.stem + " relationship snippet -->", "<!-- " + xml.stem + " relationship snippet -->")
            updated = updated.replace("<!-- " + xml.stem + " skill snippet -->", "<!-- " + xml.stem + " skill snippet -->")
            updated = updated.replace("<!-- " + xml.stem + " motive snippet -->", "<!-- " + xml.stem + " motive snippet -->")
            updated = updated.replace("<!-- " + xml.stem + " snippet -->", "<!-- " + xml.stem + " snippet -->")
            if xml.stem.endswith("_aspiration"):
                updated = re.sub(r"(<T n=\"aspiration_name\">)(.+)(</T>)", lambda m: m.group(1) + xml.stem.replace("_aspiration", "") + m.group(3), updated)
            if xml.stem.endswith("_whim"):
                updated = re.sub(r"(<T n=\"whim_name\">)(.+)(</T>)", lambda m: m.group(1) + xml.stem.replace("_whim", "") + m.group(3), updated)
                updated = re.sub(r"(<T n=\"whim_description\">)(.+)(</T>)", lambda m: m.group(1) + "Replace with " + xml.stem.replace("_whim", "") + " flavor text." + m.group(3), updated)
            if xml.stem.endswith("_club"):
                updated = re.sub(r"(<T n=\"club_name\">)(.+)(</T>)", lambda m: m.group(1) + xml.stem.replace("_club", "") + m.group(3), updated)
            if xml.stem.endswith("_holiday"):
                updated = re.sub(r"(<T n=\"holiday_name\">)(.+)(</T>)", lambda m: m.group(1) + xml.stem.replace("_holiday", "") + m.group(3), updated)
            if xml.stem.endswith("_loot_action"):
                updated = re.sub(r"(<T n=\"loot_action_name\">)(.+)(</T>)", lambda m: m.group(1) + xml.stem.replace("_loot_action", "") + m.group(3), updated)
            if xml.stem.endswith("_testset"):
                updated = re.sub(r"(<T n=\"test_set_name\">)(.+)(</T>)", lambda m: m.group(1) + xml.stem.replace("_testset", "") + m.group(3), updated)
            if xml.stem.endswith("_relationship"):
                updated = re.sub(r"(<T n=\"relationship_name\">)(.+)(</T>)", lambda m: m.group(1) + xml.stem.replace("_relationship", "") + m.group(3), updated)
            if xml.stem.endswith("_skill"):
                updated = re.sub(r"(<T n=\"skill_name\">)(.+)(</T>)", lambda m: m.group(1) + xml.stem.replace("_skill", "") + m.group(3), updated)
            if xml.stem.endswith("_motive"):
                updated = re.sub(r"(<T n=\"motive_name\">)(.+)(</T>)", lambda m: m.group(1) + xml.stem.replace("_motive", "") + m.group(3), updated)
            updated = updated.replace("<T n=\"event_name\">" + xml.stem + "</T>", "<T n=\"event_name\">" + xml.stem + "</T>")
            updated = updated.replace("<T n=\"achievement_name\">" + xml.stem.replace("_achievement", "") + "</T>", "<T n=\"achievement_name\">" + xml.stem.replace("_achievement", "") + "</T>")
            if updated != txt:
                _write(xml, updated)
                touched.append(str(xml.relative_to(proj)))
        rows = _meta_block("verified", "Tuned IDs", f"{len(touched)} file(s)")
        if touched:
            rows += ["", "Updated:"] + [f"  - {item}" for item in sorted(set(touched))[:20]]
        print(_status_panel("tune-ids", rows, command="tune-ids"))
        _advance_pipeline_if_artifact(proj, "tmp/tune_ids_report.txt")
        return 0

    if command == "wizard":
        if len(argv) < 2:
            print_help(is_subcommand=True, command="wizard", error="Expected: wizard <mod_type> [name]")
            return 2
        mod_type = argv[1]
        name = argv[2] if len(argv) > 2 else ""
        preset = wizard_presets(mod_type)
        if not preset:
            print_help(is_subcommand=True, command="wizard", error=f"Unknown mod type: {mod_type}")
            return 2
        print(_status_panel("wizard", [_meta_block("ok", f"Wizard: {mod_type}", "answer prompts to scaffold")[0], ""], command="wizard"))

        if not name:
            name = wizard_ask("Module/object name", "")
            if not name:
                print(_status_panel("wizard", [_meta_block("fail", "Cancelled", "name is required")[0]], command="wizard"))
                return 2
        try:
            proj = _existing_project(".")
        except SystemExit:
            proj = init_project(name)

        params: dict[str, str] = {}
        for field in preset.get("params", []):
            default = preset.get("defaults", {}).get(field, "")
            value = wizard_ask(field, default)
            if value:
                params[field] = value

        factory = {
            "xml_snippet": new_xml_snippet,
            "ts4script": new_ts4script,
            "package": new_package_mod,
            "career": new_career,
            "trait": new_trait,
            "buff": new_buff,
            "interaction": new_interaction,
            "event": new_event,
            "achievement": new_achievement,
            "aspiration": new_aspiration,
            "whim": new_whim,
            "club": new_club,
            "holiday": new_holiday,
            "loot_action": new_loot_action,
            "testset": new_testset,
            "relationship": new_relationship,
            "skill": new_skill,
            "motive": new_motive,
        }.get(mod_type)
        if factory is None:
            print(_status_panel("wizard", [_meta_block("fail", "Unknown mod type", mod_type)[0]], command="wizard"))
            return 2

        d = factory(proj, name)
        _apply_params(proj, mod_type, name, params)
        changelog = proj / "CHANGELOG.md"
        if not changelog.exists():
            today = datetime.now().strftime("%Y-%m-%d")
            _write(changelog, f"# Changelog\n\n## {today}\n- Wizard scaffolded {mod_type}: {name}.\n")

        advice = compatibility_advice(mod_type)
        deps = dependency_notes(mod_type)
        panel = [
            _meta_block("verified", "Wizard Complete", f"{mod_type}: {name}")[0],
            f"Path: {d}",
            "",
            f"{C_BOLD_WHITE}Brain Advice:{C_RESET}",
            f"  {advice}",
            "",
            f"{C_BOLD_WHITE}Dependencies:{C_RESET}",
        ] + [f"  - {item}" for item in deps] + [
            "",
            f"{C_BOLD_WHITE}Next Steps:{C_RESET}",
        ] + [f"  - {item}" for item in preset.get("next_steps", [])]
        print(_status_panel("wizard", panel, command="wizard"))
        _advance_pipeline_if_artifact(proj, f"src/{mod_type}")
        _advance_pipeline_if_artifact(proj, "CHANGELOG.md")
        return 0

    if command == "pipeline":
        if len(argv) > 1 and argv[1] == "tune":
            phase = argv[2] if len(argv) > 2 else None
            path = argv[3] if len(argv) > 3 and argv[2] else argv[2] if len(argv) > 2 else "."
            if phase not in PIPELINE_PHASES:
                print_help(is_subcommand=True, command="pipeline", error="Expected: pipeline tune <phase> [path]")
                return 2
            proj = _existing_project(path)
            meta = PIPELINE_META.get(phase, {})
            rows = _meta_block("ok", f"Tune: {meta.get('name', phase)}", meta.get("hint", ""))
            rows += ["", f"{C_BOLD_WHITE}Example:{C_RESET}", f"  - {meta.get('next', '')}", f"{C_BOLD_WHITE}Artifact:{C_RESET} {meta.get('artifact', '')}"]
            print(_status_panel("pipeline-tune", rows, command="pipeline tune"))
            return 0
        path = argv[1] if len(argv) > 1 else "."
        proj = _existing_project(path)
        print(print_pipeline_status(proj))
        return 0

    print_help(is_subcommand=True, command=command, error=f"Unknown command: {command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
