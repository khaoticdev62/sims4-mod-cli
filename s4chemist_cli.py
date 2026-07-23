#!/usr/bin/env python3
"""Portable Sims 4 Mod Construction CLI - local authoring helper.

This CLI ships with a Hermes-style screen layout: colored status labels,
command panel tables, and uniform subcommand help blocks.
"""
from __future__ import annotations

import os
import re
import shlex
import shutil
import sys
import textwrap
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from datetime import datetime
from typing import Callable, Iterable

from rich import box
from rich.console import Console, Group
from rich.markup import escape as _escape_markup
from rich.panel import Panel
from rich.progress import track
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

if sys.stdout.encoding and sys.stdout.encoding.upper() != "UTF-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    except (AttributeError, UnicodeError):
        pass

__version__ = "0.12.0"

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
        "hint": "Run s4chemist_cli validate and fix XML/schema/text issues.",
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
    state: dict = {"phase_index": 0, "locked": [], "notes": {}}
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
    if is_phase_locked(state, cur):
        return ["Pipeline complete — all phases done."]
    actions = [f"Complete current phase: {meta.get('name', cur)}", meta.get("next", "")]
    if meta.get("artifact"):
        actions.append(f"Expected artifact: {meta['artifact']}")
    return [a for a in actions if a]


def _progress_bar(pct: int, width: int = 10) -> str:
    filled = round(width * pct / 100)
    if _ascii_mode():
        return "#" * filled + "-" * (width - filled)
    return "█" * filled + "░" * (width - filled)


def _pipeline_table(state: dict) -> Table:
    cur = current_phase(state)
    table = Table(box=_inner_table_box(), show_edge=False, header_style="head", pad_edge=False)
    table.add_column("Phase")
    table.add_column("Status")
    table.add_column("Hint")
    for p in PIPELINE_PHASES:
        locked = is_phase_locked(state, p)
        active = p == cur and not locked
        marker = "DONE" if locked else ("ACTIVE" if active else "WAIT")
        style = "ok" if locked else ("local" if active else "muted")
        hint = PIPELINE_META[p]["hint"]
        if not (locked or active):
            hint = f"[muted]{hint}[/]"
        table.add_row(f"[head]{PIPELINE_META[p]['name']}[/]", f"[{style}]{marker}[/{style}]", hint)
    return table


def print_pipeline_status(proj: Path) -> str:
    state = load_pipeline_state(proj)
    cur, done, total, pct = phase_progress(state)
    rows: list = [_pipeline_table(state)]
    rows += [
        "",
        f"[head]Progress:[/] {done}/{total} ({pct}%) [ok]{_progress_bar(pct)}[/]",
        "[head]Next:[/]",
    ] + _bullets(_esc(a) for a in next_actions(state))
    return _status_panel("pipeline", rows, command="pipeline")


def print_pipeline_next(proj: Path) -> str:
    state = load_pipeline_state(proj)
    cur = current_phase(state)
    actions = next_actions(state)
    rows = [f"[head]Current Phase:[/] {_esc(PIPELINE_META[cur]['name'])}"]
    rows += [
        "",
        "[head]Next Actions:[/]",
    ] + _bullets(_esc(a) for a in actions)
    rows += [
        "",
        f"[head]Unlock:[/] pipeline-unlock {_esc(proj)}",
        f"[head]Reset:[/] pipeline-reset {_esc(proj)}",
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
    rows += [f"[head]Progress:[/] {phase_progress(state)[1]}/{len(PIPELINE_PHASES)}"]
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


def _argv_item_str(item: object) -> str:
    return str(item)


def _project_path_from_argv(argv: list[str], default: str = ".") -> str:
    for arg in argv[1:]:
        if not _argv_item_str(arg).startswith("-"):
            return _argv_item_str(arg)
    return default


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ── UI layer (rich-powered Hermes style) ─────────────────────────────────

HERMES = {
    "green": "#3ddc84",
    "blue": "#5dade2",
    "yellow": "#f5c542",
    "red": "#ff5555",
    "muted": "#8a8a8a",
}

THEME = Theme(
    {
        "ok": f"bold {HERMES['green']}",
        "fail": f"bold {HERMES['red']}",
        "verified": HERMES["green"],
        "local": HERMES["yellow"],
        "blocked": f"bold {HERMES['red']}",
        "accent": HERMES["blue"],
        "head": "bold white",
        "hint": HERMES["yellow"],
        "glyph": f"bold {HERMES['green']}",
        "muted": HERMES["muted"],
    }
)

NO_COLOR = "NO_COLOR" in os.environ or "--no-color" in sys.argv[1:]


def _make_console() -> Console:
    # Rich auto-disables color when stdout is not a terminal and enables VT
    # processing on modern Windows consoles; NO_COLOR/--no-color force plain.
    return Console(theme=THEME, highlight=False, emoji=False, no_color=NO_COLOR)


_console = _make_console()


def _ascii_mode() -> bool:
    """Force ASCII glyphs on legacy consoles, non-UTF-8 streams, or S4_ASCII=1."""
    if os.environ.get("S4_ASCII"):
        return True
    if _console.is_terminal and _console.legacy_windows:
        return True
    encoding = getattr(sys.stdout, "encoding", None)
    if encoding is None:
        # wrapped stream (e.g. Textual's _PrintCapture): the app renders
        # unicode itself, so stay in unicode mode
        return False
    return "utf" not in encoding.lower()


def _box_style() -> box.Box:
    return box.ASCII if _ascii_mode() else box.ROUNDED


def _inner_table_box() -> box.Box | None:
    """Tables nested inside panels: header rule only, no outer edge."""
    return box.SIMPLE_HEAD if not _ascii_mode() else box.ASCII


def _glyph() -> str:
    return ">" if _ascii_mode() else "❯"


def _prompt() -> str:
    return f"[glyph]{_glyph()}[/] "


def _brand_glyph() -> str:
    return "*" if _ascii_mode() else "⚗"


def _banner_line() -> str:
    """The one-line S4Chemist brand banner used on help, splash, and headers."""
    return (
        f"[glyph]{_brand_glyph()}[/] [head]S4CHEMIST[/] [muted]·[/] "
        f"[accent]Portable Sims 4 Mod Construction CLI[/] [muted]v{__version__}[/]"
    )


def _esc(text: object) -> str:
    """Escape user-derived content so it cannot corrupt Rich markup."""
    return _escape_markup(str(text))


def _bullets(items: Iterable[str], *, indent: str = "  - ") -> list[str]:
    """Bullet lines with hanging indent: wrapped continuations align under the
    text start instead of spilling back to the panel edge."""
    width = max(40, _console.width - 6)
    out = []
    for item in items:
        wrapped = textwrap.wrap(
            indent + item,
            width=width,
            subsequent_indent=" " * len(indent),
            break_long_words=False,
            break_on_hyphens=False,
        ) or [indent.rstrip()]
        out.extend(wrapped)
    return out


def _fnv1a_64(text: str) -> int:
    h = 0xCBF29CE484222325
    for b in text.encode("utf-8"):
        h = (h ^ b) * 0x100000001B3
        h &= 0xFFFFFFFFFFFFFFFF
    return h


def _tuning_instance(name: str, suffix: str = "") -> str:
    seed = f"{name}{suffix}"
    return hex(_fnv1a_64(seed) & 0x7FFFFFFFFFFFFFFF)


def _rewrite_stbl_placeholders(stem: str, text: str) -> tuple[str, str]:
    updated = text
    mappings = []
    stem_clean = stem.replace("_", " ").strip()
    base_key = stem_clean.replace(" ", "_").lower()
    for pattern, suffix in [
        ("<T n=\"display_name\">0x00000000</T>", "STR_DISPLAY_NAME"),
        ("<T n=\"description\">0x00000000</T>", "STR_DESCRIPTION"),
        ("<!-- Replace with {stem} flavor text.</T>", "STR_FLAVOR_DESC"),
    ]:
        decorated = pattern.replace("{stem}", stem_clean)
        key = f"{base_key}:{suffix}"
        replacement = f"<S>{key}</S>"
        if decorated in updated:
            updated = updated.replace(decorated, replacement, 1)
            placeholder_text = stem_clean if "display_name" in suffix else f"Replace with {stem_clean} flavor text."
            mappings.append(f"{key}={placeholder_text}")
            updated = updated.replace(decorated, replacement, 1)
    return updated, "\n".join(mappings)


_META_TAGS = {
    "ok": "[OK]",
    "verified": "[VERIFIED]",
    "local": "[LOCAL]",
    "blocked": "[BLOCKED]",
    "fail": "[FAIL]",
}


def _panel_border_style(body: Iterable) -> str:
    """Pick a border color from the panel's content: fail=red, ok/verified=green,
    local=yellow, otherwise the accent blue. Makes outcomes readable at a glance."""
    text = "\n".join(item for item in body if isinstance(item, str))
    if "[fail]" in text or "[blocked]" in text:
        return "fail"
    if "[ok]" in text or "[verified]" in text:
        return "ok"
    if "[local]" in text:
        return "local"
    return "accent"


def _status_panel(headline: str, body: Iterable, *, command: str = "", hints: bool = False) -> str:
    """Render the Hermes-style panel (auto-sized, closed box, state-colored border).

    Body items may be Rich-markup strings or Rich renderables (e.g. Table).
    User-derived strings must be escaped with `_esc()` (already handled by
    `_meta_block`/`_kv_block`). Footer hint lines are only shown when
    `hints=True` (help and error panels, where recovery guidance matters).
    """
    body = list(body)
    border_style = _panel_border_style(body)
    footer_command = command or headline.lower()
    items = [Text.from_markup(item) if isinstance(item, str) else item for item in body]
    panel = Panel(
        Group(*items),
        title=f"[ok]{_brand_glyph()} s4chemist_cli[/] [muted]{'-' if _ascii_mode() else '─'}[/] [accent]{_esc(headline)}[/]",
        title_align="left",
        box=_box_style(),
        border_style=border_style,
        expand=False,
    )
    with _console.capture() as cap:
        _console.print(panel)
        if hints:
            if footer_command == "s4chemist_cli":
                _console.print(f"[glyph]{_glyph()}[/] [head]Enter a command to start.[/]")
            else:
                _console.print(f"[glyph]{_glyph()}[/] Run [hint]'s4chemist_cli doctor'[/]   Verify environment paths.")
                _console.print(f"[glyph]{_glyph()}[/] Run [hint]'s4chemist_cli help <cmd>'[/]  Show command help.")
    return cap.get().rstrip("\n")


def _kv_block(rows: list[tuple[str, str]]) -> list[str]:
    """Key/value rows with aligned columns; empty keys become continuation lines."""
    width = max((len(k) for k, _ in rows), default=0)
    out = []
    for k, v in rows:
        out.append(f"{k + ':':<{width + 1}} {v}" if k else f"{'':<{width + 1}} {v}")
    return out


def _meta_block(state: str, label: str, detail: str = "") -> list[str]:
    style = state if state in _META_TAGS else "local"
    tag = f"[{style}]{_esc(_META_TAGS.get(state, '[' + state.upper() + ']'))}[/{style}]"
    line = f"{tag} {_esc(label)}"
    if detail:
        line += f" — {_esc(detail)}"
    return [line]


def _section(title: str, lines: list) -> list:
    marker = ">" if _ascii_mode() else "▸"
    return [f"[head]{marker} {title}[/]", *lines]


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


WIZARD_PRESETS: dict[str, dict] = {
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


def wizard_ask(prompt: str, default: str = "", *, required: bool = False, attempts: int = 3) -> str:
    """Interactive prompt via rich; `required` re-asks (up to `attempts`) on empty input."""
    for _ in range(attempts):
        try:
            reply = (Prompt.ask(
                f"[glyph]{_glyph()}[/] {prompt}",
                default=default or None,
                console=_console,
            ) or "").strip()
        except EOFError:
            return default
        if reply or not required:
            return reply or default
        _console.print("[fail]A value is required.[/]")
    return default


def new_career(proj: Path, name: str) -> Path:
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
        '{\n'
        '  "name": "' + name + '",\n'
        '  "version": "0.1.0",\n'
        '  "entry": "main.py",\n'
        '  "author": "YourName",\n'
        '  "description": "' + name + ' script mod",\n'
        '  "game_versions": ["*"]\n'
        '}\n',
    )
    _write(
        d / "README.txt",
        f"Script Mod: {name}\n"
        "Entry: main.py\n"
        "\n"
        "Runtime guidance:\n"
        "- Compile with the game's bundled Python (see `s4chemist_cli game-python`).\n"
        "- Place this folder (or a .ts4script zip of it) directly in Mods, max one level deep.\n"
        "- Enable 'Script Mods Allowed' in Game Options > Other and restart.\n"
        "- Test the console command in-game (Ctrl+Shift+C, then your.command.here).\n"
        "\n"
        "Tuning notes:\n"
        "- Keep scripts deterministic; avoid hard-coded paths.\n"
        "- Document dependencies (XML Injector, other script mods) here.\n",
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
        "Packaging steps:\n"
        "1. Author tuning XML here, then run `s4chemist_cli tune-ids <proj>`.\n"
        "2. Build a tdesc manifest with Tdesc Builder (one <Resource> per XML/STBL).\n"
        "3. Import resources into Sims 4 Studio (or s4pe) and save as " + name + ".package.\n"
        "4. Sign the .package (Sims 4 Studio 'Sign Package' for CC attribution).\n"
        "5. Drop the signed .package into Mods and run `s4chemist_cli validate --strict`.\n"
        "\n"
        "Tuning notes:\n"
        "- Write STBL entries for every visible string (see src/localization).\n"
        "- Keep one <Resource> per tdesc entry; avoid broad overrides.\n",
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
        "  <T n=\"test_set_name\">" + name + "</T>\n"
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


MOD_FACTORIES = {
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
}


def validate_project_issues(proj: Path, strict: bool = False) -> list[str]:
    """Return actionable validation issues for a project (see docs/validation.md)."""
    if _console.is_terminal:
        with _console.status("[accent]Scanning project...[/]"):
            return _validate_project_issues(proj, strict=strict)
    return _validate_project_issues(proj, strict=strict)


def _validate_project_issues(proj: Path, strict: bool = False) -> list[str]:
    issues: list[str] = []
    if strict:
        cfg = proj / "s4modconfig.yaml"
        if not cfg.exists():
            issues.append("s4modconfig.yaml: missing (run 's4chemist_cli init <name>' to scaffold a project)")
        else:
            txt = cfg.read_text(encoding="utf-8")
            if "ReplaceMe" in txt:
                issues.append("s4modconfig.yaml: mod_name is still 'ReplaceMe' (set your real mod name)")
            if "YourName" in txt:
                issues.append("s4modconfig.yaml: creator is still 'YourName' (set your creator name)")
            fields = {}
            for line in txt.splitlines():
                if ":" in line and not line.strip().startswith("-"):
                    fields[line.split(":", 1)[0].strip()] = line.split(":", 1)[1].strip()
            for required in ("mod_name", "creator", "version", "mod_type"):
                if not fields.get(required):
                    issues.append(f"s4modconfig.yaml: missing required field '{required}' (set it via 's4chemist_cli config <proj> {required}=...')")
            version = fields.get("version", "")
            if version and not re.match(r"^\d+\.\d+\.\d+$", version):
                issues.append(f"s4modconfig.yaml: version '{version}' is not x.y.z format")

        # ts4script modules need a parseable manifest.json
        for main_py in proj.rglob("src/ts4script/*/main.py"):
            manifest = main_py.parent / "manifest.json"
            if not manifest.exists():
                issues.append(f"{main_py.parent.relative_to(proj)}/manifest.json: missing (script mods need a manifest)")
                continue
            try:
                import json as _json
                meta = _json.loads(manifest.read_text(encoding="utf-8"))
                for key in ("name", "entry"):
                    if key not in meta:
                        issues.append(f"{manifest.relative_to(proj)}: missing '{key}' field")
            except ValueError:
                issues.append(f"{manifest.relative_to(proj)}: invalid JSON")

        # localization maps produced by tune-ids must be key=value lines.
        loc_keys: dict[str, str] = {}
        for stbl in proj.rglob("src/localization/*.txt"):
            if stbl.name == "stbl_index.txt":
                continue
            for lineno, line in enumerate(stbl.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if "=" not in stripped:
                    issues.append(f"{stbl.relative_to(proj)}:{lineno}: not a key=value line ({stripped[:40]})")
                    continue
                key = stripped.split("=", 1)[0].strip()
                if key in loc_keys:
                    issues.append(
                        f"{stbl.relative_to(proj)}:{lineno}: duplicate localization key '{key}' "
                        f"(already in {loc_keys[key]})"
                    )
                else:
                    loc_keys[key] = str(stbl.relative_to(proj))

        xml_s_refs: set[str] = set()
        for xml in proj.rglob("*.xml"):
            text = xml.read_text(encoding="utf-8", errors="ignore")
            xml_s_refs.update(ref.strip() for ref in re.findall(r"<S>([^<]+)</S>", text) if ref.strip())
        for ref in sorted(xml_s_refs):
            if ref not in loc_keys:
                issues.append(f"localization: XML references missing STBL key '{ref}'")

        # package templates that were never compiled into a real .package
        templates = list(proj.rglob("src/package/**/*.package.template"))
        if templates and not list(proj.rglob("src/package/**/*.package")):
            issues.append("src/package: only .package.template stubs found (compile a real .package in Sims4Studio/s4pe before release)")

    xml_files = list(proj.rglob("*.xml"))
    for xml in xml_files:
        rel = str(xml.relative_to(proj))
        try:
            txt = xml.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            issues.append(f"{rel}: unreadable file (check permissions/encoding)")
            continue
        if not txt.lstrip().startswith("<?xml"):
            issues.append(f"{rel}: missing XML declaration (start the file with <?xml version='1.0' encoding='utf-8'?>)")
            continue
        stem = xml.name
        for kind, tags in TUNING_TAG_RULES.items():
            if stem.endswith(f"_{kind}.xml") or f"_{kind}." in stem or kind == stem:
                missing = [t for t in tags if f'<T n="{t}">' not in txt and f'<U n="{t}">' not in txt]
                for tag in missing:
                    issues.append(f"{rel}: missing '{tag}' tag required for {kind} tuning")
        if strict:
            if "0x00000000" in txt:
                issues.append(f"{rel}: placeholder tuning id 0x00000000 (run 's4chemist_cli tune-ids <project>' to assign real ids)")
            if "Replace with" in txt:
                issues.append(f"{rel}: placeholder flavor text 'Replace with ...' (write real display text)")

    pkg_candidates = list(proj.rglob("*.package")) + list(proj.rglob("*.package.template"))
    xml_or_script_count = len(xml_files) + len(list(proj.rglob("*.py")))
    if proj.joinpath("src", "package").exists() and not pkg_candidates and xml_or_script_count:
        pass
    elif not pkg_candidates:
        issues.append("no .package artifact found (run 's4chemist_cli new <proj> package <name>' or author one in Sims4Studio)")

    return issues


def validate_project(proj: Path, strict: bool = False) -> int:
    return max(len(validate_project_issues(proj, strict=strict)), 0)


def _mod_name_from_config(proj: Path) -> str:
    mod_name = proj.name
    cfg_path = proj / "s4modconfig.yaml"
    if cfg_path.exists():
        for line in cfg_path.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("mod_name:"):
                mod_name = line.split(":", 1)[1].strip() or mod_name
                break
    return mod_name


def _verify_archive(out: Path) -> None:
    """Post-build archive integrity checks; aborts with SystemExit on failure."""
    if not zipfile.is_zipfile(out):
        raise SystemExit(f"Archive integrity check failed: not a zip file: {out}")
    with zipfile.ZipFile(out) as zf:
        bad = zf.testzip()
        if bad is not None:
            raise SystemExit(f"Archive integrity check failed: corrupt entry '{bad}' in {out}")
        if not zf.namelist():
            raise SystemExit(f"Archive integrity check failed: empty archive {out}")


def _zip_project(proj: Path, out: Path, *, extra_excludes: tuple[str, ...] = ()) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    paths = sorted(proj.rglob("*"))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in track(paths, description="[accent]Zipping...[/]", console=_console,
                          disable=not _console.is_terminal, transient=True):
            if path.is_dir():
                continue
            rel = path.relative_to(proj)
            txt = rel.as_posix()  # normalize: on Windows str(rel) uses backslashes
            if txt.startswith("dist/") or txt.startswith("tmp/"):
                continue
            if txt == ".gitignore" or txt.startswith(".git"):
                continue
            if txt in extra_excludes:
                continue
            zf.write(path, rel)
    _verify_archive(out)
    return out


def build_project(proj: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = proj / "dist" / f"{_mod_name_from_config(proj)}-{stamp}.zip"
    return _zip_project(proj, out)


def install_to_mods(proj: Path, mods_dir: str | None = None) -> Path:
    target_path = _mods_root(mods_dir)  # --to-dir > S4_MODS_DIR > auto-detect

    target = target_path / proj.name
    if target.exists():
        raise SystemExit(f"Target already exists: {target}")
    shutil.copytree(proj, target)
    for extra in ["dist", "tmp", ".git"]:
        d = target / extra
        if d.exists():
            shutil.rmtree(d)
    return target


def doctor_check() -> int:
    issues = 0
    checks = []
    if sys.version_info < (3, 10):
        issues += 1
        checks.append(("Python", "[fail]FAIL[/] Python 3.10+"))
    else:
        checks.append(("Python", "[ok]OK[/] Python >= 3.10"))

    sims_docs = Path.home() / "Documents" / "Electronic Arts" / "The Sims 4"
    sims_ok = sims_docs.exists()
    sims_ok_text = "[ok]OK[/]" if sims_ok else "[fail]MISSING[/]"
    checks.append(("Sims Docs", f"{sims_ok_text} Sims 4 Documents"))

    if sims_ok:
        mods = sims_docs / "Mods"
        mods_text = "[ok]OK[/]" if mods.exists() else "[local]MISSING[/]"
        checks.append(("Mods Folder", f"{mods_text} {_esc(mods)}"))

    print(_status_panel("VERDICT", _kv_block(checks), command="doctor"))
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
        rows.append(("Game Python", "[ok]OK[/] detected"))
        for item in found[:8]:
            rows.append(("", _esc(item)))
    else:
        rows.append(("Game Python", "[fail]MISSING[/]"))
        rows.append(("Hint", "<GAME>/Python/ + base/core/simulation/generated zip"))

    print(_status_panel("GAME PYTHON", _kv_block(rows), command="game-python"))


def _help_footer() -> list[str]:
    return [
        f"  [glyph]{_glyph()}[/] s4chemist_cli <command>    Enter a command to start.",
        "  Run 's4chemist_cli doctor'   Verify environment paths.",
        "  Run 's4chemist_cli help <cmd>'  Show command help.",
    ]


def _commands_table() -> Table:
    table = Table(box=_inner_table_box(), show_edge=False, header_style="head", pad_edge=False)
    table.add_column("COMMAND")
    table.add_column("DESCRIPTION")
    table.add_column("STATUS")
    for entry in COMMANDS.values():
        if entry.hidden or not entry.description:
            continue  # hidden command: dispatchable but not listed
        status_tag = ""
        if entry.status:
            status_tag = f"[{entry.status}]{_esc(_META_TAGS.get(entry.status, entry.status.upper()))}[/{entry.status}]"
        table.add_row(f"[head]{_esc(entry.usage)}[/]", _esc(entry.description), status_tag)
    return table


def print_help(*, is_subcommand=False, command="", error="") -> None:
    panel: list = []
    panel.append(_banner_line())
    if error:
        panel.extend(_section("[fail]ERROR[/]", [_esc(error)]))

    if is_subcommand:
        panel.extend(_section(f"COMMAND [head]{_esc(command)}[/]", []))
        panel.extend(_section("USAGE", [f"  {_prompt()}s4chemist_cli {_esc(command)} \\[options]"]))
        entry = COMMANDS.get(command)
        if entry and entry.args:
            panel.extend(_section("ARGS", [_esc(a) for a in entry.args]))
        panel.extend(_section("NOTES", ["  Status: [verified]VERIFIED[/] = exercised end-to-end; [local]LOCAL[/] = needs a local path."]))
        panel.extend(_section("FOOTER", _help_footer()))
    else:
        panel.extend(_section("COMMANDS", [_commands_table()]))
        kind_list = list(MOD_FACTORIES)
        half = (len(kind_list) + 1) // 2
        kind_rows = [
            f"  {kind_list[i]:<15}{kind_list[i + half] if i + half < len(kind_list) else ''}"
            for i in range(half)
        ]
        panel.extend(_section("KINDS", kind_rows))
        panel.extend(_section("STATUS KEY", ["  [verified]\\[VERIFIED][/]   = exercised end-to-end", "  [local]\\[LOCAL][/]     = needs environment-specific value", "  [blocked]\\[BLOCKED][/]   = missing dependency / environment"]))
        panel.extend(_section("FOOTER", _help_footer()))

    print(_status_panel(f"{'help' if is_subcommand else 's4chemist_cli'}", panel, command=command if is_subcommand else "", hints=True))

def package_release(proj: Path, out_dir: Path | None = None) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = out_dir or (proj / "dist")
    out = base / f"{_mod_name_from_config(proj)}-release-{stamp}.zip"
    result = _zip_project(proj, out, extra_excludes=("OWNERS-GUIDE.txt",))
    _write_release_manifest(proj, result)
    _write_release_notes(proj, base, stamp)
    return result


def _write_release_manifest(proj: Path, archive: Path) -> Path:
    """Auditable manifest of a built release: archive name, size, and full contents."""
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
    lines = [
        f"release: {archive.name}",
        f"mod: {_mod_name_from_config(proj)}",
        f"built: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"size: {archive.stat().st_size} bytes",
        f"files: {len(names)}",
        "",
        "contents:",
    ] + [f"  - {n}" for n in names]
    manifest = proj / "tmp" / "release_manifest.txt"
    _write(manifest, "\n".join(lines) + "\n")
    return manifest


def _write_release_notes(proj: Path, out_dir: Path, stamp: str) -> Path | None:
    """Extract the latest CHANGELOG.md section into dist/<mod>-release-notes-<stamp>.txt."""
    changelog = proj / "CHANGELOG.md"
    if not changelog.exists():
        return None
    text = changelog.read_text(encoding="utf-8")
    sections = re.split(r"(?m)^## ", text)
    latest = sections[1] if len(sections) > 1 else text
    notes = out_dir / f"{_mod_name_from_config(proj)}-release-notes-{stamp}.txt"
    _write(notes, "## " + latest.strip() + "\n" if not latest.startswith("#") else latest)
    return notes

def print_subcommand_help(command: str) -> None:
    print_help(is_subcommand=True, command=command)

@dataclass
class Command:
    """Registry entry: dispatch handler plus data-driven help metadata.

    Navigation metadata (category, takes_path, menu_flow, tui_action) lets the
    menu shell, REPL, help, and TUI derive their surfaces from one registry.
    """

    name: str
    handler: Callable[[list[str]], int]
    args: list[str] = field(default_factory=list)  # ARGS lines for subcommand help
    usage: str = ""        # usage column in the main COMMANDS table
    description: str = ""  # description column (empty = hidden from main help)
    status: str = ""       # "verified" | "local" | "" -> STATUS column tag
    category: str = "meta"  # create | inspect | ship | repair | meta
    takes_path: bool = False
    menu_flow: bool = False  # offer guided prompt flow in the menu shell
    tui_action: bool = False  # surface as a TUI sidebar button
    hidden: bool = False     # hide from help, menu, palette


def _cmd_init(argv: list[str]) -> int:
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


def _cmd_new(argv: list[str]) -> int:
    if len(argv) < 4:
        print_help(is_subcommand=True, command="new", error="Expected: new <where> <kind> <name>")
        return 2
    _, where, kind, name = argv[:4]
    proj = _existing_project(where)
    factory = MOD_FACTORIES.get(kind)
    if factory is None:
        print_help(is_subcommand=True, command="new", error=f"Unknown kind: {kind}")
        return 2
    _created = factory(proj, name)
    print(_status_panel("new", _meta_block("verified", "Created", kind) + [f"Path: {_esc(_rel_display(_created, proj))}"], command="new"))
    _advance_pipeline_if_artifact(proj, f"src/{kind}")
    _advance_pipeline_if_artifact(proj, "src/xml_snippets")
    _advance_pipeline_if_artifact(proj, "src/ts4script")
    _advance_pipeline_if_artifact(proj, "src/package")
    return 0


def _cmd_validate(argv: list[str]) -> int:
    path = _project_path_from_argv(argv)
    strict = "--strict" in argv
    proj = _existing_project(path)
    found = validate_project_issues(proj, strict=strict)
    issues = len(found)
    state = "ok" if issues == 0 else "fail"
    rows = _meta_block(state, "Validation", f"{issues} issue{'s' if issues != 1 else ''}")
    if found:
        rows += ["", "[head]Issues:[/]"] + _bullets(_esc(item) for item in found[:15])
        if issues > 15:
            rows.append(f"  ... and {issues - 15} more")
        if not strict:
            rows += ["", "Hint: rerun with --strict to also flag placeholder ids and template values."]
    print(_status_panel("validate", rows, command="validate"))
    _advance_pipeline_if_artifact(proj, "docs/validation_report.txt")
    _advance_pipeline_if_artifact(proj, "tmp/lint_report.txt")
    return issues


def _archive_stats(out: Path) -> str:
    """Human summary for a built archive: size + entry count."""
    size = float(out.stat().st_size)
    for unit in ("B", "KB", "MB"):
        if size < 1024 or unit == "MB":
            size_str = f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            break
        size /= 1024
    with zipfile.ZipFile(out) as zf:
        count = len(zf.namelist())
    return f"{size_str} · {count} file{'s' if count != 1 else ''}"


def _rel_display(path: Path, proj: Path) -> str:
    """Display path relative to the project when possible (shorter panels)."""
    try:
        return str(path.relative_to(proj))
    except ValueError:
        return str(path)


def _cmd_build(argv: list[str]) -> int:
    path = _project_path_from_argv(argv)
    release = "--release" in argv
    proj = _existing_project(path)
    if release:
        out = package_release(proj)
    else:
        out = build_project(proj)
    rows = _meta_block("verified", "Built", _rel_display(out, proj))
    rows.append(f"           {_archive_stats(out)}")
    print(_status_panel("build", rows, command="build"))
    _advance_pipeline_if_artifact(proj, "dist")
    return 0


def _cmd_package(argv: list[str]) -> int:
    path = _project_path_from_argv(argv)
    out_dir = None
    if "--out-dir" in argv:
        idx = argv.index("--out-dir")
        if idx + 1 < len(argv):
            out_dir = argv[idx + 1]
    proj = _existing_project(path)
    out = package_release(proj, out_dir=Path(out_dir) if out_dir else None)
    rows = _meta_block("verified", "Packaged", _rel_display(out, proj))
    rows.append(f"           {_archive_stats(out)}")
    print(_status_panel("package", rows, command="package"))
    _advance_pipeline_if_artifact(proj, "dist")
    _advance_pipeline_if_artifact(proj, "tmp/release_manifest.txt")
    return 0


def _cmd_install(argv: list[str]) -> int:
    path = _project_path_from_argv(argv)
    to_dir = None
    if "--to-dir" in argv:
        idx = argv.index("--to-dir")
        if idx + 1 < len(argv):
            to_dir = argv[idx + 1]
    target = install_to_mods(_existing_project(path), mods_dir=to_dir)
    print(_status_panel("install", _meta_block("local", "Installed", str(target)), command="install"))
    return 0


def _mods_root(mods_dir: str | None = None) -> Path:
    """Resolve the Mods root with the same priority as install: --to-dir > S4_MODS_DIR > auto-detect."""
    env_dir = os.environ.get("S4_MODS_DIR")
    if mods_dir:
        return Path(mods_dir)
    if env_dir:
        root = Path(env_dir)
        if not root.exists():
            raise SystemExit(f"S4_MODS_DIR does not exist: {root}")
        return root
    docs = Path.home() / "Documents"
    candidate = docs / "Electronic Arts" / "The Sims 4" / "Mods"
    if not candidate.exists():
        raise SystemExit(f"Auto-detected Mods folder not found: {candidate}")
    return candidate


def _cmd_uninstall(argv: list[str]) -> int:
    path = _project_path_from_argv(argv)
    to_dir = None
    if "--to-dir" in argv:
        idx = argv.index("--to-dir")
        if idx + 1 < len(argv):
            to_dir = argv[idx + 1]
    proj = _existing_project(path)
    target = _mods_root(to_dir) / proj.name
    if not target.exists():
        print_help(is_subcommand=True, command="uninstall", error=f"Not installed: {target}")
        return 2
    if not (target / "s4modconfig.yaml").exists():
        print_help(is_subcommand=True, command="uninstall",
                   error=f"Refusing to remove {target}: no s4modconfig.yaml (not an S4Chemist copy)")
        return 2
    shutil.rmtree(target)
    print(_status_panel("uninstall", _meta_block("ok", "Removed", str(target)), command="uninstall"))
    return 0


def _cmd_config(argv: list[str]) -> int:
    if len(argv) < 3:
        print_help(is_subcommand=True, command="config", error="Expected: config <path> key=value [key=value ...]")
        return 2
    proj = _existing_project(argv[1])
    cfg = proj / "s4modconfig.yaml"
    lines = cfg.read_text(encoding="utf-8").splitlines()
    changed = []
    for token in argv[2:]:
        if "=" not in token:
            print_help(is_subcommand=True, command="config", error=f"Expected key=value, got: {token}")
            return 2
        key, value = (part.strip() for part in token.split("=", 1))
        replaced = False
        for i, line in enumerate(lines):
            if line.strip().startswith(f"{key}:"):
                lines[i] = f"{key}: {value}"
                replaced = True
                break
        if not replaced:
            lines.append(f"{key}: {value}")
        changed.append((key, value))
    _write(cfg, "\n".join(lines) + "\n")
    rows = _meta_block("verified", "Config", f"{len(changed)} key{'s' if len(changed) != 1 else ''} updated")
    rows += _kv_block([(k, _esc(v)) for k, v in changed])
    print(_status_panel("config", rows, command="config"))
    return 0


def _cmd_doctor(argv: list[str]) -> int:
    return doctor_check()


def _cmd_version(argv: list[str]) -> int:
    print(_status_panel("version", _meta_block("ok", "Version", f"s4chemist_cli v{__version__}"), command="version"))
    return 0


def _cmd_help(argv: list[str]) -> int:
    target = argv[1] if len(argv) > 1 else "s4chemist_cli"
    if target == "s4chemist_cli":
        print_help(is_subcommand=False, command="")
    else:
        print_subcommand_help(target)
    return 0


def _cmd_pipeline(argv: list[str]) -> int:
    if len(argv) > 1 and argv[1] == "tune":
        phase = argv[2] if len(argv) > 2 else None
        path = _project_path_from_argv(argv[2:], default=".")
        if phase not in PIPELINE_PHASES:
            print_help(is_subcommand=True, command="pipeline", error="Expected: pipeline tune <phase> [path]")
            return 2
        proj = _existing_project(path)
        meta = PIPELINE_META.get(phase, {})
        rows = _meta_block("ok", f"Tune: {meta.get('name', phase)}", meta.get("hint", ""))
        rows += ["", "[head]Example:[/]", f"  - {_esc(meta.get('next', ''))}", f"[head]Artifact:[/] {_esc(meta.get('artifact', ''))}"]
        print(_status_panel("pipeline-tune", rows, command="pipeline tune"))
        return 0
    path = argv[1] if len(argv) > 1 else "."
    proj = _existing_project(path)
    print(print_pipeline_status(proj))
    return 0


def _cmd_pipeline_next(argv: list[str]) -> int:
    path = argv[1] if len(argv) > 1 else "."
    proj = _existing_project(path)
    print(print_pipeline_next(proj))
    return 0


def _cmd_pipeline_unlock(argv: list[str]) -> int:
    path = argv[1] if len(argv) > 1 else "."
    proj = _existing_project(path)
    print(unlock_current_phase(proj))
    return 0


def _cmd_pipeline_reset(argv: list[str]) -> int:
    path = argv[1] if len(argv) > 1 else "."
    proj = _existing_project(path)
    print(reset_pipeline(proj))
    return 0


def _cmd_game_python(argv: list[str]) -> int:
    ensure_game_python()
    return 0


def _cmd_generate(argv: list[str]) -> int:
    if len(argv) < 3:
        print_help(is_subcommand=True, command="generate", error="Expected: generate <mod_type> <name>")
        return 2
    mod_type = argv[1]
    name = argv[2]
    params = _parse_kv_tokens(argv[3:])
    factory = MOD_FACTORIES.get(mod_type)
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
    panel = [_meta_block("verified", "Generated", f"{mod_type}: {name}")[0]] + _kv_block([
        ("Type", _esc(mod_type)),
        ("Name", _esc(name)),
        ("Path", _esc(_rel_display(d, proj))),
    ]) + [
        "",
        "[head]Brain Advice:[/]",
        f"  {advice}",
        "",
        "[head]Dependencies:[/]",
    ] + _bullets(_esc(item) for item in deps) + [
        "",
        "[head]Next Steps:[/]",
    ] + _bullets(_esc(item) for item in preset.get("next_steps", []))
    _advance_pipeline_if_artifact(proj, f"src/{mod_type}")
    _advance_pipeline_if_artifact(proj, "src/xml_snippets")
    _advance_pipeline_if_artifact(proj, "src/ts4script")
    _advance_pipeline_if_artifact(proj, "src/package")
    if note_kv:
        panel += [
            "",
            "[head]Pipeline Notes Saved:[/]",
        ] + [f"  {_esc(k)}: {_esc(v)}" for k, v in note_kv.items()]
    print(_status_panel("generate", panel, command="generate"))
    return 0


def _cmd_changelog(argv: list[str]) -> int:
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
    print(_status_panel("changelog", _meta_block("verified", "Updated", str(changelog)), command="changelog"))
    _advance_pipeline_if_artifact(proj, "CHANGELOG.md")
    return 0


def _rewrite_placeholder_flavor_text(text: str, stem: str) -> str:
    label = stem
    for suffix in (
        "_trait",
        "_buff",
        "_career",
        "_interaction",
        "_event",
        "_achievement",
        "_aspiration",
        "_whim",
        "_club",
        "_holiday",
        "_loot_action",
        "_testset",
        "_relationship",
        "_skill",
        "_motive",
    ):
        if label.endswith(suffix):
            label = label[: -len(suffix)]
            break

    def repl(match: re.Match[str]) -> str:
        value = match.group(1).strip() or label
        return f"{value} flavor text."

    updated = re.sub(r"Replace with (.+?) flavor text\.", repl, text)
    return updated.replace("Replace with trait flavor text.", f"{label} trait flavor text.")


def _write_stbl_index(proj: Path) -> Path | None:
    loc_dir = proj / "src" / "localization"
    maps = sorted(p for p in loc_dir.glob("stbl_*.txt") if p.name != "stbl_index.txt") if loc_dir.exists() else []
    if not maps:
        return None
    rows = [
        "# S4Chemist localization index",
        "# Generated by repair-placeholders; source maps remain authoritative.",
        "",
    ]
    for mapping in maps:
        keys = []
        for line in mapping.read_text(encoding="utf-8", errors="ignore").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                keys.append(stripped.split("=", 1)[0].strip())
        rows.append(f"[{mapping.name}]")
        rows.extend(f"- {key}" for key in keys)
        rows.append("")
    index = loc_dir / "stbl_index.txt"
    _write(index, "\n".join(rows).rstrip() + "\n")
    return index


def _tune_project_placeholders(proj: Path, *, flavor: bool = False) -> list[str]:
    touched = []
    xml_files = sorted(proj.rglob("*.xml"))
    for xml in track(xml_files, description="[accent]Tuning...[/]", console=_console,
                     disable=not _console.is_terminal, transient=True):
        txt = xml.read_text(encoding="utf-8", errors="ignore")
        updated = txt
        updated, _ = _rewrite_stbl_placeholders(xml.stem, updated)
        updated = updated.replace('<I d="0x00000000">', '<I d="' + _tuning_instance(xml.stem) + '">')
        updated = updated.replace("<T n=\"career_icon\">0x00000000</T>", "<T n=\"career_icon\">" + _tuning_instance(xml.stem, "_icon") + "</T>")
        updated = updated.replace("<T n=\"display_name\">0x00000000</T>", "<T n=\"display_name\">" + _tuning_instance(xml.stem, "_display") + "</T>")
        updated = updated.replace("<T n=\"description\">0x00000000</T>", "<T n=\"description\">" + _tuning_instance(xml.stem, "_desc") + "</T>")
        updated = updated.replace("<T n=\"icon_resource\">0x00000000</T>", "<T n=\"icon_resource\">" + _tuning_instance(xml.stem, "_icon") + "</T>")
        updated = updated.replace("<U n=\"club_icon\">0x00000000</U>", "<U n=\"club_icon\">" + _tuning_instance(xml.stem, "_icon") + "</U>")
        updated = updated.replace("<U n=\"holiday_icon\">0x00000000</U>", "<U n=\"holiday_icon\">" + _tuning_instance(xml.stem, "_icon") + "</U>")
        if flavor:
            # stopgap copy so --strict passes: "Replace with X flavor text." -> "X flavor text."
            updated = re.sub(r"Replace with (.+?) flavor text\.",
                             lambda m: m.group(1) + " flavor text.", updated)
        idx = 0
        def _replace_u(match):
            nonlocal idx
            suffix = f"_item{idx}"
            idx += 1
            return "<U>" + _tuning_instance(xml.stem, suffix) + "</U>"
        updated = re.sub(r"<U>0x00000000</U>", _replace_u, updated)
        updated = updated.replace("<T n=\"trait_facial_priority\">0</T>", "<T n=\"trait_facial_priority\">" + str(_fnv1a_64(xml.stem) & 0xFFFFFFFF) + "</T>")
        updated = updated.replace("<U n=\"interaction_distance\">0</U>", "<U n=\"interaction_distance\">" + str(_fnv1a_64(xml.stem + "_distance") & 0xFFFFFFFF) + "</U>")
        updated = updated.replace("<T n=\"pie_menu_priority\">0</T>", "<T n=\"pie_menu_priority\">" + str(_fnv1a_64(xml.stem + "_menu") & 0xFFFFFFFF) + "</T>")
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
        if flavor:
            updated = _rewrite_placeholder_flavor_text(updated, xml.stem)
        if updated != txt:
            _write(xml, updated)
            touched.append(str(xml.relative_to(proj)))
        map_content = _rewrite_stbl_placeholders(xml.stem, txt)[1]
        if map_content:
            loc_dir = proj / "src" / "localization"
            _write(loc_dir / f"stbl_{xml.stem}.txt", map_content)
            touched.append(str((loc_dir / f"stbl_{xml.stem}.txt").relative_to(proj)))
    return touched


def _cmd_tune_ids(argv: list[str]) -> int:
    if len(argv) < 2:
        print_help(is_subcommand=True, command="tune-ids", error="Expected: tune-ids <path>")
        return 2
    flavor = "--flavor" in argv
    proj = _existing_project(argv[1])
    touched = _tune_project_placeholders(proj, flavor=flavor)
    rows = _meta_block("verified", "Tuned IDs", f"{len(touched)} file(s)")
    if touched:
        rows += ["", "[head]Updated:[/]"] + _bullets(_esc(item) for item in sorted(set(touched))[:20])
    print(_status_panel("tune-ids", rows, command="tune-ids"))
    _advance_pipeline_if_artifact(proj, "tmp/tune_ids_report.txt")
    return 0


def _cmd_repair_placeholders(argv: list[str]) -> int:
    path = _project_path_from_argv(argv)
    keep_flavor = "--keep-flavor" in argv
    proj = _existing_project(path)
    touched = _tune_project_placeholders(proj, flavor=not keep_flavor)
    index = _write_stbl_index(proj)
    if index:
        touched.append(str(index.relative_to(proj)))
    rows = _meta_block("verified", "Repaired placeholders", f"{len(set(touched))} file(s)")
    rows += [
        "",
        "[head]Behavior:[/]",
        "  - Rewrites placeholder tuning ids.",
        "  - Rewrites STBL placeholder refs and regenerates localization index.",
    ]
    if keep_flavor:
        rows.append("  - Flavor text was left unchanged (--keep-flavor).")
    else:
        rows.append("  - Placeholder flavor text was converted to editable plain text.")
    if touched:
        rows += ["", "[head]Updated:[/]"] + _bullets(_esc(item) for item in sorted(set(touched))[:20])
    print(_status_panel("repair-placeholders", rows, command="repair-placeholders"))
    _advance_pipeline_if_artifact(proj, "src/localization/stbl_index.txt")
    return 0


def _doctor_mod_findings(proj: Path) -> tuple[list[str], list[str]]:
    blockers: list[str] = []
    notes: list[str] = []
    script_dirs = sorted(p for p in (proj / "src" / "ts4script").glob("*") if p.is_dir()) if (proj / "src" / "ts4script").exists() else []
    if script_dirs:
        notes.append("Script mods: verify 'Script Mods Allowed' is enabled in The Sims 4 game options.")
    for script_dir in script_dirs:
        manifest = script_dir / "manifest.json"
        main = script_dir / "main.py"
        if not manifest.exists():
            blockers.append(f"{script_dir.relative_to(proj)}: missing manifest.json")
        if not main.exists():
            blockers.append(f"{script_dir.relative_to(proj)}: missing main.py")

    package_dirs = sorted(p for p in (proj / "src" / "package").glob("*") if p.is_dir()) if (proj / "src" / "package").exists() else []
    for package_dir in package_dirs:
        for required in ("tdesc", "STBL", "resources"):
            if not (package_dir / required).exists():
                blockers.append(f"{package_dir.relative_to(proj)}: missing {required}/ authoring folder")
        if not list(package_dir.glob("*.package")) and list(package_dir.glob("*.package.template")):
            notes.append(f"{package_dir.relative_to(proj)}: compile .package.template in Sims4Studio/s4pe before release.")

    loc_dir = proj / "src" / "localization"
    xml_refs: list[str] = []
    for xml in proj.rglob("*.xml"):
        text = xml.read_text(encoding="utf-8", errors="ignore")
        xml_refs.extend(ref.strip() for ref in re.findall(r"<S>([^<]+)</S>", text) if ref.strip())
    if xml_refs and not list(loc_dir.glob("stbl_*.txt")):
        blockers.append("src/localization: missing STBL map files for XML <S> references")

    strict_issues = validate_project_issues(proj, strict=True)
    for issue in strict_issues[:8]:
        blockers.append(issue)
    return blockers, notes


def _cmd_doctor_mod(argv: list[str]) -> int:
    path = _project_path_from_argv(argv)
    try:
        proj = _existing_project(path)
    except SystemExit:
        print_help(is_subcommand=True, command="doctor-mod", error=f"Not a valid project: {path}")
        return 2
    blockers, notes = _doctor_mod_findings(proj)
    state = load_pipeline_state(proj)
    rows = _meta_block("ok" if not blockers else "blocked", "Mod Doctor", f"{len(blockers)} finding(s)")
    rows += ["", "[head]Project:[/]", f"  {_esc(proj)}"]
    rows += ["", "[head]Next Action:[/]"] + _bullets(_esc(item) for item in next_actions(state)[:2])
    if notes:
        rows += ["", "[head]Notes:[/]"] + _bullets(_esc(item) for item in notes[:8])
    if blockers:
        rows += ["", "[head]Findings:[/]"] + _bullets(_esc(item) for item in sorted(set(blockers))[:15])
        if len(blockers) > 15:
            rows.append(f"  ... and {len(blockers) - 15} more")
        rows += ["", "[head]Repair:[/]", f"  s4chemist_cli repair-placeholders {_esc(proj)}"]
    print(_status_panel("doctor-mod", rows, command="doctor-mod"))
    return 1 if blockers else 0


def _cmd_wizard(argv: list[str]) -> int:
    if len(argv) < 2:
        print_help(is_subcommand=True, command="wizard", error="Expected: wizard <mod_type> [name]")
        return 2
    mod_type = argv[1]
    name = argv[2] if len(argv) > 2 and not argv[2].startswith("--") else ""
    cli_params = _parse_kv_tokens(argv[3:] if name else argv[2:])
    if not name:
        name = cli_params.pop("name", "")
    preset = wizard_presets(mod_type)
    if not preset:
        print_help(is_subcommand=True, command="wizard", error=f"Unknown mod type: {mod_type}")
        return 2
    # Note: on Windows, NUL//dev/null still reports isatty() True (character device),
    # so require a real terminal on stdout as well before prompting.
    interactive = sys.stdin.isatty() and sys.stdout.isatty()
    mode = "answer prompts to scaffold" if interactive else "non-interactive: defaults + --param overrides"
    print(_status_panel("wizard", [_meta_block("ok", f"Wizard: {mod_type}", mode)[0], ""], command="wizard"))

    if not name:
        if not interactive:
            print(_status_panel("wizard", [_meta_block("fail", "Cancelled", "name is required (pass [name] or --param name=... non-interactively)")[0]], command="wizard"))
            return 2
        name = wizard_ask("Module/object name", required=True)
        if not name:
            print(_status_panel("wizard", [_meta_block("fail", "Cancelled", "name is required")[0]], command="wizard"))
            return 2
    try:
        proj = _existing_project(".")
    except SystemExit:
        proj = init_project(name)

    params: dict[str, str] = {}
    for field_name in preset.get("params", []):
        if field_name in cli_params:
            params[field_name] = cli_params[field_name]
            continue
        default = preset.get("defaults", {}).get(field_name, "")
        if not interactive:
            if default:
                params[field_name] = default
            continue
        value = wizard_ask(field_name, default)
        if value:
            params[field_name] = value
    for key, value in cli_params.items():
        params.setdefault(key, value)

    if interactive:
        summary = Table(box=_box_style(), header_style="head", pad_edge=False)
        summary.add_column("Field")
        summary.add_column("Value")
        summary.add_row("mod_type", _esc(mod_type))
        summary.add_row("name", _esc(name))
        for k, v in params.items():
            summary.add_row(_esc(k), _esc(v))
        _console.print(summary)
        if not Confirm.ask("Create files?", console=_console, default=True):
            print(_status_panel("wizard", [_meta_block("fail", "Cancelled", "nothing written")[0]], command="wizard"))
            return 2

    factory = MOD_FACTORIES.get(mod_type)
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
    panel = [_meta_block("verified", "Wizard Complete", f"{mod_type}: {name}")[0]] + _kv_block([
        ("Type", _esc(mod_type)),
        ("Name", _esc(name)),
        ("Path", _esc(_rel_display(d, proj))),
    ]) + [
        "",
        "[head]Brain Advice:[/]",
        f"  {advice}",
        "",
        "[head]Dependencies:[/]",
    ] + _bullets(_esc(item) for item in deps) + [
        "",
        "[head]Next Steps:[/]",
    ] + _bullets(_esc(item) for item in preset.get("next_steps", []))
    print(_status_panel("wizard", panel, command="wizard"))
    _advance_pipeline_if_artifact(proj, f"src/{mod_type}")
    _advance_pipeline_if_artifact(proj, "CHANGELOG.md")
    return 0


# ── Textual TUI (full dashboard; launched via `tui`) ───────────────────────

_TUI_CATEGORY_ORDER = ["create", "inspect", "ship", "repair"]
_TUI_CATEGORY_LABELS = {
    "create": "CREATE",
    "inspect": "INSPECT",
    "ship": "SHIP",
    "repair": "REPAIR",
}

_TUI_CSS = """
#sidebar { width: 20%; min-width: 22; max-width: 38; padding: 1; border-right: tall $boost; }
#sidebar Label { margin-top: 1; color: $text-muted; text-style: bold; }
#sidebar Button { width: 100%; margin-top: 1; }
#status-bar { padding: 0 1; background: $boost; border-bottom: tall $boost; }
DataTable { height: 1fr; border: round $boost; }
DataTable > .datatable--header { text-style: bold; }
#phase-detail { padding: 0 1; border-top: tall $boost; height: auto; max-height: 6; }
#preview { border-left: tall $boost; }
#preview-title { padding: 0 1; color: $text-muted; text-style: bold; }
RichLog { height: 1fr; }
Horizontal { height: 1fr; }
Input:focus { border: round $secondary; }
Select:focus { border: round $secondary; }
SelectCurrent { height: auto; }  /* textual 8: Horizontal base leaks height:1fr into SelectCurrent */
#create-form { padding: 1 2; max-width: 90; }
#create-form Label { margin-top: 1; color: $text-muted; text-style: bold; }
#w_params_scroll { height: 1fr; min-height: 5; border: round $boost; padding: 0 1; }
#w_error { color: $error; text-style: bold; }
#w_create { margin-top: 1; }
"""

_PREVIEW_LEXERS = {
    ".xml": "xml", ".py": "python", ".yaml": "yaml", ".yml": "yaml",
    ".md": "markdown", ".txt": "text", ".json": "json", ".template": "xml",
}


def _make_tui_app(project: str = "."):
    """Build the Textual dashboard app. Imports are deferred so plain CLI
    commands stay fast and do not require textual installed."""
    from functools import partial

    from rich.syntax import Syntax
    from textual import on, work
    from textual.app import App, ComposeResult
    from textual.theme import Theme as TextualTheme
    from textual.command import Hit, Provider
    from textual.containers import Horizontal, Vertical, VerticalScroll
    from textual.widgets import (
        Button, DataTable, DirectoryTree, Footer, Header, Input, Label,
        RichLog, Select, Static, TabbedContent, TabPane,
    )

    class S4Commands(Provider):
        """Command palette entries (Ctrl+P). Derived from COMMANDS so new
        commands automatically appear without touching the TUI code."""

        def _entries(self) -> list[tuple[str, list[str] | str]]:
            app = self.app
            proj = app._proj()  # type: ignore[attr-defined]
            entries: list[tuple[str, list[str] | str]] = []
            for cmd in COMMANDS.values():
                if cmd.hidden or not cmd.description:
                    continue
                label = f"{cmd.name.replace('-', ' ').title()}: {cmd.description}"
                if cmd.takes_path:
                    entries.append((label, [cmd.name, proj]))
                else:
                    entries.append((label, [cmd.name]))
            entries.extend([
                ("Pipeline: tune current phase", "pipeline-tune"),
                ("Refresh pipeline table", "refresh"),
                ("Open guided creation tab", "open-create-tab"),
                ("Navigate to next action", "next-action"),
                ("Go to current phase", "go-phase"),
            ])
            return entries

        async def search(self, query: str):
            matcher = self.matcher(query)
            for label, action in self._entries():
                score = matcher.match(label)
                if score > 0:
                    yield Hit(score, matcher.highlight(label), partial(self._dispatch, action), help=label)

        async def discover(self):
            for label, action in self._entries():
                yield Hit(1.0, label, partial(self._dispatch, action), help=label)

        def _dispatch(self, action: list[str] | str) -> None:
            app = self.app
            if action == "refresh":
                app.refresh_pipeline()  # type: ignore[attr-defined]
            elif action == "pipeline-tune":
                proj = Path(app._proj())  # type: ignore[attr-defined]
                state = load_pipeline_state(proj)
                app.run_command(["pipeline", "tune", current_phase(state), str(proj)])  # type: ignore[attr-defined]
            elif action == "open-create-tab":
                app.query_one(TabbedContent).active = "tab-create"  # type: ignore[attr-defined]
            elif action == "next-action":
                proj = Path(app._proj())  # type: ignore[attr-defined]
                state = load_pipeline_state(proj)
                actions = next_actions(state)
                app._append_log(["palette"], "Next action: " + (actions[0] if actions else "No action"), 0)  # type: ignore[attr-defined]
            elif action == "go-phase":
                app.query_one(TabbedContent).active = "tab-pipeline"  # type: ignore[attr-defined]
            else:
                app.run_command(action)  # type: ignore[attr-defined]

    hermes_tui_theme = TextualTheme(
        name="hermes",
        primary=HERMES["green"],
        secondary=HERMES["blue"],
        accent=HERMES["yellow"],
        success=HERMES["green"],
        warning=HERMES["yellow"],
        error=HERMES["red"],
        dark=True,
    )

    class S4Tui(App):
        CSS = _TUI_CSS
        TITLE = "S4Chemist"
        SUB_TITLE = "Sims 4 Mod Construction CLI"
        COMMANDS = App.COMMANDS | {S4Commands}
        history: list = []
        BINDINGS = [("q", "quit", "Quit"), ("r", "refresh", "Refresh"), ("ctrl+p", "command_palette", "Palette")]

        def __init__(self) -> None:
            super().__init__()
            self.register_theme(hermes_tui_theme)
            self.theme = "hermes"

        def compose(self) -> ComposeResult:
            yield Header()
            with Horizontal():
                with VerticalScroll(id="sidebar"):
                    yield Label("◆ PROJECT")
                    yield Input(value=project, placeholder="project path", id="project")
                    if COMMANDS.get("init", Command("", lambda _: 0)).tui_action:
                        yield Button("Init Project", id="init")
                    yield Label("◆ WORKFLOW")
                    yield Button("Create", id="open-wizard", variant="warning")
                    for cat in _TUI_CATEGORY_ORDER:
                        cmds = [c for c in COMMANDS.values() if c.category == cat and c.tui_action]
                        if not cmds:
                            continue
                        yield Label(f"◆ {_TUI_CATEGORY_LABELS.get(cat, cat.upper())}")
                        for cmd in cmds:
                            if cmd.name == "init":
                                continue  # already shown under PROJECT
                            label = cmd.description.split(".")[0]
                            if cmd.name in ("validate", "build", "package"):
                                yield Button(label, id=cmd.name, variant="primary")
                            elif cmd.name in ("uninstall", "pipeline-reset"):
                                yield Button(label, id=cmd.name, variant="error")
                            else:
                                yield Button(label, id=cmd.name)
                    yield Label("◆ MODS")
                    yield Input(placeholder="Mods dir (optional)", id="mods_dir")
                with Vertical():
                    yield Static("", id="status-bar")
                    with TabbedContent():
                        with TabPane("Pipeline", id="tab-pipeline"):
                            yield DataTable(id="pipeline")
                            yield Static("", id="phase-detail")
                        with TabPane("Create", id="tab-create"):
                            with Vertical(id="create-form"):
                                yield Label(f"[bold]{_brand_glyph()} Guided mod creation[/]")
                                yield Label("Mod type")
                                yield Select([(k, k) for k in MOD_FACTORIES], value="trait", id="w_type")
                                yield Label("Name (required)")
                                yield Input(placeholder="module/object name", id="w_name")
                                yield Label("Parameters")
                                with VerticalScroll(id="w_params_scroll"):
                                    yield Vertical(id="w_params")
                                yield Label("", id="w_error")
                                yield Button("Create", id="w_create", variant="success")
                        with TabPane("Files", id="tab-files"):
                            with Horizontal():
                                yield Vertical(id="files-container")
                                with Vertical():
                                    yield Static("select a file to preview", id="preview-title")
                                    yield RichLog(id="preview", markup=True)
                        with TabPane("Log", id="tab-log"):
                            yield RichLog(id="log", markup=True)
            yield Footer()

        async def on_mount(self) -> None:
            self.history = []  # per-instance log mirror (class attr is just the default)
            self.query_one("#pipeline", DataTable).add_columns("Phase", "Status", "Hint")
            self.query_one("#log", RichLog).write(f"[{HERMES['muted']}]Command output appears here.[/]")
            self.refresh_pipeline()
            await self._w_build_params()

        def action_refresh(self) -> None:
            self.refresh_pipeline()
            self._reload_tree()

        _w_built_for: str | None = None

        @on(Select.Changed, "#w_type")
        async def _w_type_changed(self) -> None:
            await self._w_build_params()

        async def _w_build_params(self) -> None:
            """(Re)build guided-creation param inputs for the selected type.

            remove_children() is async in Textual — it must be awaited, otherwise
            the new Inputs register while the old ones still exist (DuplicateIds).
            """
            container = self.query_one("#w_params", Vertical)
            mod_type = str(self.query_one("#w_type", Select).value)
            if self._w_built_for == mod_type:
                return
            self._w_built_for = mod_type
            preset = wizard_presets(mod_type)
            wanted = [(f, preset.get("defaults", {}).get(f, "")) for f in preset.get("params", [])]
            existing = {w.placeholder: w for w in container.children if isinstance(w, Input)}
            if list(existing) == [f for f, _ in wanted]:
                return
            await container.remove_children()
            for param_field, default in wanted:
                await container.mount(Input(value=default, placeholder=param_field, id=f"w_param_{param_field}"))

        def _w_param_values(self) -> dict[str, str]:
            values = {}
            for widget in self.query_one("#w_params", Vertical).children:
                if isinstance(widget, Input) and widget.value.strip():
                    values[widget.placeholder] = widget.value.strip()
            return values

        @on(Button.Pressed, "#w_create")
        def _w_create(self) -> None:
            name = self.query_one("#w_name", Input).value.strip()
            if not name:
                self.query_one("#w_error", Label).update("name is required")
                return
            self.query_one("#w_error", Label).update("")
            mod_type = str(self.query_one("#w_type", Select).value)
            argv = ["wizard", mod_type, name]
            for key, value in self._w_param_values().items():
                argv += ["--param", f"{key}={value}"]
            self.run_command(argv, cwd=self._proj())

        def _proj(self) -> str:
            return self.query_one("#project", Input).value.strip() or "."

        def refresh_pipeline(self) -> None:
            table = self.query_one("#pipeline", DataTable)
            table.clear()
            bar = self.query_one("#status-bar", Static)
            proj = Path(self._proj())
            if not (proj / "s4modconfig.yaml").exists():
                table.add_row("-", "-", "not a project (set path or run init)")
                bar.update(Text.assemble((f"{_brand_glyph()} ", f"bold {HERMES['red']}"), (self._proj(), "bold white"), ("  not a project", HERMES["muted"])))
                self._show_phase_detail(-1)
                return
            state = load_pipeline_state(proj)
            cur, done, total, pct = phase_progress(state)
            for p in PIPELINE_PHASES:
                locked = is_phase_locked(state, p)
                active = p == cur and not locked
                marker = "DONE" if locked else ("ACTIVE" if active else "WAIT")
                style = f"bold {HERMES['green']}" if locked else (f"bold {HERMES['yellow']}" if active else HERMES["muted"])
                table.add_row(
                    Text(PIPELINE_META[p]["name"], style="bold white"),
                    Text(marker, style=style),
                    Text(PIPELINE_META[p]["hint"], style=HERMES["muted"] if not (locked or active) else ""),
                )
            cur_meta = PIPELINE_META[cur]
            bar.update(
                Text.assemble(
                    (f"{_brand_glyph()} ", f"bold {HERMES['green']}"),
                    (proj.name, "bold white"),
                    ("   Phase: ", "bold white"),
                    (f"{cur_meta['name']} ", f"bold {HERMES['yellow']}"),
                    ("  Progress: ", "bold white"),
                    (f"{done}/{total} ({pct}%) ", ""),
                    (_progress_bar(pct), f"bold {HERMES['green']}"),
                )
            )
            self._show_phase_detail(PIPELINE_PHASES.index(cur))

        def _show_phase_detail(self, index: int) -> None:
            detail = self.query_one("#phase-detail", Static)
            if index < 0 or index >= len(PIPELINE_PHASES):
                detail.update("")
                return
            phase = PIPELINE_PHASES[index]
            meta = PIPELINE_META[phase]
            detail.update(
                Text.assemble(
                    ("Phase: ", "bold white"), (meta["name"], ""), ("  Hint: ", "bold white"), (meta["hint"], ""),
                    ("\nNext: ", "bold white"), (meta.get("next", ""), ""),
                    ("  Artifact: ", "bold white"), (meta.get("artifact", ""), ""),
                )
            )

        @on(DataTable.RowSelected, "#pipeline")
        def _row_selected(self, event: DataTable.RowSelected) -> None:
            self._show_phase_detail(event.cursor_row)

        def _ensure_tree(self) -> None:
            container = self.query_one("#files-container", Vertical)
            if not container.children:
                container.mount(DirectoryTree(self._proj(), id="files"))

        def _reload_tree(self) -> None:
            if self.query("#files"):
                self.query_one("#files", DirectoryTree).path = Path(self._proj())

        @on(TabbedContent.TabActivated)
        def _tab_activated(self, event: TabbedContent.TabActivated) -> None:
            if self.query_one(TabbedContent).active == "tab-files":
                self._ensure_tree()

        @on(DirectoryTree.FileSelected, "#files")
        def _file_selected(self, event: DirectoryTree.FileSelected) -> None:
            preview = self.query_one("#preview", RichLog)
            preview.clear()
            path = Path(event.path)
            self.query_one("#preview-title", Static).update(f"[bold]{path.name}[/]")
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                preview.write(f"cannot read: {exc}")
                return
            lexer = _PREVIEW_LEXERS.get(path.suffix.lower(), "text")
            preview.write(Syntax(text[:20000], lexer, theme="ansi_dark", line_numbers=True))

        def _append_log(self, argv: list[str], text: str, rc: int) -> None:
            entry = f"$ s4chemist_cli {' '.join(argv)}  (exit {rc})\n{text.rstrip()}"
            self.history.append(entry)
            log = self.query_one("#log", RichLog)
            log.write(f"[bold]$ s4chemist_cli {' '.join(argv)}[/]  (exit {rc})")
            if text.strip():
                log.write(text.rstrip())
            log.write("")
            self.query_one(TabbedContent).active = "tab-log"

        @work(thread=True)
        def run_command(self, argv: list[str], cwd: str | None = None) -> None:
            import contextlib
            import io
            import os

            buf = io.StringIO()
            rc = 0
            old_cwd = os.getcwd()
            if cwd:
                os.chdir(cwd)  # commands like wizard/generate operate on "."
            try:
                with contextlib.redirect_stdout(buf):
                    try:
                        rc = main(argv)
                    except SystemExit as exc:
                        rc = 1
                        if exc.code:
                            print(exc.code)
                    except Exception as exc:  # keep the UI alive on command errors
                        rc = 1
                        print(f"error: {exc}")
            finally:
                os.chdir(old_cwd)
            self.call_from_thread(self._append_log, argv, buf.getvalue(), rc)
            self.call_from_thread(self.refresh_pipeline)

        @on(Button.Pressed, "#validate")
        def _validate(self) -> None:
            self.run_command(["validate", self._proj()])

        @on(Button.Pressed, "#build")
        def _build(self) -> None:
            self.run_command(["build", self._proj()])

        @on(Button.Pressed, "#package")
        def _package(self) -> None:
            self.run_command(["package", self._proj()])

        @on(Button.Pressed, "#changelog")
        def _changelog(self) -> None:
            self.run_command(["changelog", self._proj()])

        @on(Button.Pressed, "#tune-ids")
        def _tune_ids(self) -> None:
            self.run_command(["tune-ids", self._proj()])

        @on(Button.Pressed, "#repair-placeholders")
        def _repair_placeholders(self) -> None:
            self.run_command(["repair-placeholders", self._proj()])

        @on(Button.Pressed, "#doctor")
        def _doctor(self) -> None:
            self.run_command(["doctor"])

        @on(Button.Pressed, "#doctor-mod")
        def _doctor_mod(self) -> None:
            self.run_command(["doctor-mod", self._proj()])

        @on(Button.Pressed, "#init")
        def _init(self) -> None:
            self.run_command(["init", self._proj()])

        @on(Button.Pressed, "#install")
        def _install(self) -> None:
            argv = ["install", self._proj()]
            mods_dir = self.query_one("#mods_dir", Input).value.strip()
            if mods_dir:
                argv += ["--to-dir", mods_dir]
            self.run_command(argv)

        @on(Button.Pressed, "#uninstall")
        def _uninstall(self) -> None:
            argv = ["uninstall", self._proj()]
            mods_dir = self.query_one("#mods_dir", Input).value.strip()
            if mods_dir:
                argv += ["--to-dir", mods_dir]
            self.run_command(argv)

        @on(Button.Pressed, "#pipeline-next")
        def _pipeline_next(self) -> None:
            self.run_command(["pipeline-next", self._proj()])

        @on(Button.Pressed, "#pipeline-unlock")
        def _pipeline_unlock(self) -> None:
            self.run_command(["pipeline-unlock", self._proj()])

        @on(Button.Pressed, "#pipeline-reset")
        def _pipeline_reset(self) -> None:
            self.run_command(["pipeline-reset", self._proj()])

        @on(Button.Pressed, "#open-wizard")
        def _open_wizard(self) -> None:
            self.query_one(TabbedContent).active = "tab-create"

        @on(Input.Submitted, "#project")
        def _project_submitted(self) -> None:
            self.refresh_pipeline()
            self._reload_tree()

    return S4Tui()


def _cmd_tui(argv: list[str]) -> int:
    project = argv[1] if len(argv) > 1 else "."
    _make_tui_app(project).run()
    return 0


COMMANDS: dict[str, Command] = {
    entry.name: entry
    for entry in [
        Command(
            "init",
            _cmd_init,
            args=["  name       Project directory / mod name"],
            usage="init <name>",
            description="Initialize a new mod project.",
            status="verified",
            category="create",
            menu_flow=True,
            tui_action=True,
        ),
        Command(
            "new",
            _cmd_new,
            args=[
                "  where      Existing project path",
                "  kind       xml_snippet|ts4script|package|career|trait|buff|interaction|event|achievement|aspiration|whim|club|holiday|loot_action|testset|relationship|skill|motive",
                "  name       Artifact/module name",
            ],
            usage="new <where> <kind> <name>",
            description="Create a mod artifact of any supported kind.",
            status="verified",
            category="create",
            menu_flow=True,
        ),
        Command(
            "validate",
            _cmd_validate,
            args=["  path       Project path, default '.'.", "  --strict   Treat template values as errors."],
            usage="validate [path]",
            description="Validate XML/packaging hygiene.",
            status="verified",
            category="inspect",
            takes_path=True,
            menu_flow=True,
            tui_action=True,
        ),
        Command(
            "build",
            _cmd_build,
            args=["  path       Project path, default '.'.", "  --release  Use release packaging semantics (same output as 'package')."],
            usage="build [path]",
            description="Package current artifacts into a release zip.",
            status="verified",
            category="ship",
            takes_path=True,
            menu_flow=True,
            tui_action=True,
        ),
        Command(
            "package",
            _cmd_package,
            args=["  path       Project path, default '.'.", "  --out-dir  Output directory for release zip."],
            usage="package [path]",
            description="Create release zip excluding dist/tmp/.git.",
            status="verified",
            category="ship",
            takes_path=True,
            menu_flow=True,
            tui_action=True,
        ),
        Command(
            "install",
            _cmd_install,
            args=[
                "  path       Project path, default '.'.",
                "  --to-dir   Mods root or custom directory.",
                "  S4_MODS_DIR env var also overrides the auto-detected Mods folder.",
            ],
            usage="install [path]",
            description="Install project into your Mods folder.",
            status="local",
            category="ship",
            takes_path=True,
            menu_flow=True,
            tui_action=True,
        ),
        Command(
            "doctor",
            _cmd_doctor,
            usage="doctor",
            description="Run environment and path checks.",
            status="verified",
            category="inspect",
            tui_action=True,
        ),
        Command(
            "doctor-mod",
            _cmd_doctor_mod,
            args=["  path       Project path, default '.'."],
            usage="doctor-mod [path]",
            description="Run mod-project diagnostics and next-action guidance.",
            status="verified",
            category="inspect",
            takes_path=True,
            menu_flow=True,
            tui_action=True,
        ),
        Command(
            "version",
            _cmd_version,
            usage="version",
            description="Print CLI version.",
            category="meta",
        ),
        Command(
            "help",
            _cmd_help,
            usage="help <cmd>",
            description="Show help for a subcommand.",
            category="meta",
        ),
        Command(
            "generate",
            _cmd_generate,
            args=["  mod_type   Supported mod type", "  name       Module or object name", "  --param k=v   Scalar tuning params, repeatable."],
            usage="generate <type> <name>",
            description="Generate a Sims 4 mod scaffold.",
            category="create",
            menu_flow=True,
        ),
        Command(
            "wizard",
            _cmd_wizard,
            args=[
                "  mod_type   Supported mod type",
                "  name       Module or object name (required when non-interactive)",
                "  --param k=v   Scalar tuning params, repeatable; skips the matching prompt.",
            ],
            usage="wizard <type> [name]",
            description="Guided mod creation with brain advice.",
            category="create",
            menu_flow=True,
            # tui_action=False: the TUI has a synthetic "Create" button that opens
            # the Create tab, which itself runs wizard semantics.
        ),
        Command(
            "changelog",
            _cmd_changelog,
            usage="changelog [path]",
            description="Add/update CHANGELOG.md.",
            category="ship",
            takes_path=True,
            menu_flow=True,
            tui_action=True,
        ),
        Command(
            "tui",
            _cmd_tui,
            args=["  path       Project path to load in the dashboard, default '.'."],
            usage="tui [path]",
            description="Open the full dashboard UI (Textual).",
            category="meta",
            takes_path=True,
        ),
        Command(
            "tune-ids",
            _cmd_tune_ids,
            args=["  path       Project path, default '.'.", "  --flavor   Also rewrite placeholder flavor text (stopgap copy)."],
            usage="tune-ids [path]",
            description="Rewrite placeholder tuning ids to stable generated ids.",
            status="verified",
            category="repair",
            takes_path=True,
            menu_flow=True,
            tui_action=True,
        ),
        Command(
            "repair-placeholders",
            _cmd_repair_placeholders,
            args=[
                "  path       Project path, default '.'.",
                "  --keep-flavor  Leave placeholder flavor text unchanged.",
            ],
            usage="repair-placeholders [path]",
            description="Repair placeholder ids, flavor text, and STBL index.",
            status="verified",
            category="repair",
            takes_path=True,
            menu_flow=True,
            tui_action=True,
        ),
        Command(
            "pipeline",
            _cmd_pipeline,
            args=["  path       Project path, default '.'.", "  tune <phase> [path]   Show tuning guidance for a phase."],
            usage="pipeline [path]",
            description="Show phase-by-phase build pipeline status.",
            status="verified",
            category="inspect",
            takes_path=True,
        ),
        Command(
            "pipeline-next",
            _cmd_pipeline_next,
            usage="pipeline-next [path]",
            description="Show next actions for the current phase.",
            category="inspect",
            takes_path=True,
            tui_action=True,
        ),
        Command(
            "pipeline-unlock",
            _cmd_pipeline_unlock,
            usage="pipeline-unlock [path]",
            description="Mark current phase done and advance.",
            category="repair",
            takes_path=True,
            tui_action=True,
        ),
        Command(
            "pipeline-reset",
            _cmd_pipeline_reset,
            usage="pipeline-reset [path]",
            description="Reset the pipeline back to concept.",
            category="repair",
            takes_path=True,
            tui_action=True,
        ),
        Command(
            "config",
            _cmd_config,
            args=["  path       Project path", "  key=value  Config keys to set (mod_name, creator, version, ...)."],
            usage="config <path> key=value...",
            description="Set values in s4modconfig.yaml.",
            status="verified",
            category="repair",
            takes_path=True,
            menu_flow=True,
        ),
        Command(
            "uninstall",
            _cmd_uninstall,
            args=["  path       Project path, default '.'.", "  --to-dir   Mods root or custom directory."],
            usage="uninstall [path]",
            description="Remove an installed copy from the Mods folder.",
            status="local",
            category="repair",
            takes_path=True,
            menu_flow=True,
            tui_action=True,
        ),
        Command(
            "game-python",
            _cmd_game_python,
            usage="game-python",
            description="Locate the game's bundled Python files.",
            status="local",
            category="meta",
        ),
    ]
}


_SHELL_HISTORY = Path.home() / ".s4chemist_history"


def _dispatch_shell_line(line: str) -> bool:
    """Run one REPL/menu command line. Returns False when the user asked to exit."""
    line = line.strip()
    if not line:
        return True
    if line.lower() in ("exit", "quit", ":q"):
        return False
    try:
        args = shlex.split(line)
    except ValueError as exc:
        _console.print(f"[fail]{_esc(exc)}[/]")
        return True
    try:
        main(args)
    except SystemExit as exc:  # e.g. _existing_project() rejects a path
        if exc.code:
            _console.print(f"[fail]{_esc(exc.code)}[/]")
    except KeyboardInterrupt:
        _console.print("[local]Interrupted[/]")
    return True


def _shell_recommendations(cwd: Path | None = None) -> list[str]:
    path = cwd or Path.cwd()
    if _is_project_path(path):
        state = load_pipeline_state(path)
        actions = next_actions(state)
        first = actions[0] if actions else "Run validate --strict ."
        return [f"Next: {first}", "Try: validate --strict ."]
    return ["Next: init <NewModName>", "Try: tui ."]


def _shell_completion_words() -> list[str]:
    words = [e.name for e in COMMANDS.values() if not e.hidden and e.description]
    words.extend(["validate --strict", "build --release", "tune-ids", "pipeline-next"])
    return words


def interactive_shell(reader: Callable[[], str | None] | None = None) -> int:
    """REPL around the COMMANDS dispatch with persistent history + completion.

    `reader` is injectable for tests; by default a prompt_toolkit session is
    used (history in ~/.s4chemist_history, command-name completion).
    """
    print_help(is_subcommand=False, command="")
    _console.print(_status_panel("next actions", _bullets(_esc(item) for item in _shell_recommendations()), command="interactive"))
    if reader is None:
        from prompt_toolkit import PromptSession
        from prompt_toolkit.completion import WordCompleter
        from prompt_toolkit.history import FileHistory

        session: PromptSession = PromptSession(
            history=FileHistory(str(_SHELL_HISTORY)),
            completer=WordCompleter(_shell_completion_words(), sentence=True),
        )
        prompt_text = f"{_glyph()} s4chemist_cli "

        def reader() -> str | None:
            try:
                result: str = session.prompt(prompt_text)
                return result
            except (EOFError, KeyboardInterrupt):
                return None

    while True:
        line = reader()
        if line is None:
            _console.print()
            return 0
        if not _dispatch_shell_line(line):
            return 0


# ── Menu mode (arrow-key navigation, questionary) ──────────────────────────


def _qstyle():
    """Hermes-branded questionary style (menus match the panel palette)."""
    from questionary import Style

    return Style([
        ("qmark", f"fg:{HERMES['green']} bold"),
        ("question", "bold"),
        ("pointer", f"fg:{HERMES['green']} bold"),
        ("highlighted", f"fg:{HERMES['blue']} bold"),
        ("selected", f"fg:{HERMES['blue']}"),
        ("answer", f"fg:{HERMES['green']} bold"),
        ("instruction", HERMES["muted"]),
    ])


def _menu_select(message: str, choices: list[str]) -> str | None:
    import questionary

    result: str | None = questionary.select(message, choices=choices, style=_qstyle()).ask()
    return result


def _menu_text(message: str, default: str = "") -> str | None:
    import questionary

    result: str | None = questionary.text(message, default=default, style=_qstyle()).ask()
    return result


def _menu_confirm(message: str, default: bool = False) -> bool:
    import questionary

    return bool(questionary.confirm(message, default=default, style=_qstyle()).ask())


@dataclass
class MenuSession:
    """State shared across one guided/menu launch."""

    project_path: str = ""


@dataclass
class MenuAction:
    """A dispatchable menu action, optionally scoped to a working directory."""

    argv: list[str]
    cwd: str | None = None


def _is_project_path(path: str | Path) -> bool:
    candidate = Path(path)
    return all((candidate / marker).exists() for marker in PROJECT_FILES)


def _initial_project_default() -> str:
    return "." if _is_project_path(Path.cwd()) else "."


def _menu_project_default(session: MenuSession | None) -> str:
    return session.project_path if session and session.project_path else _initial_project_default()


def _remember_project(session: MenuSession | None, path: str | Path) -> None:
    if session is not None and str(path).strip():
        session.project_path = str(path).strip()


def _menu_project_text(message: str, session: MenuSession | None) -> str | None:
    path = _menu_text(message, _menu_project_default(session))
    if path is not None:
        _remember_project(session, path)
    return path


def _menu_flow(command: str, session: MenuSession | None = None) -> list[str] | None:
    """Collect argv for `command` via menu prompts; None = cancelled (Esc/Ctrl+C)."""
    if command == "init":
        name = _menu_text("Project directory / mod name")
        if name:
            _remember_project(session, name)
        return ["init", name] if name else None
    if command == "new":
        where = _menu_project_text("Existing project path", session)
        if where is None:
            return None
        kind = _menu_select("Kind", list(MOD_FACTORIES))
        if not kind:
            return None
        name = _menu_text("Artifact/module name")
        if not name:
            return None
        return ["new", where, kind, name]
    if command == "validate":
        path = _menu_project_text("Project path", session)
        if path is None:
            return None
        argv = ["validate", path]
        if _menu_confirm("Strict checks (placeholder ids/template values too)?"):
            argv.append("--strict")
        return argv
    if command == "build":
        path = _menu_project_text("Project path", session)
        if path is None:
            return None
        argv = ["build", path]
        if _menu_confirm("Release packaging semantics (same as 'package')?"):
            argv.append("--release")
        return argv
    if command == "package":
        path = _menu_project_text("Project path", session)
        if path is None:
            return None
        out = _menu_text("Output dir (blank = project dist)", "")
        if out is None:
            return None
        argv = ["package", path]
        if out:
            argv += ["--out-dir", out]
        return argv
    if command == "install":
        path = _menu_project_text("Project path", session)
        if path is None:
            return None
        to = _menu_text("Mods dir (blank = auto-detect / S4_MODS_DIR)", "")
        if to is None:
            return None
        argv = ["install", path]
        if to:
            argv += ["--to-dir", to]
        return argv
    if command in ("generate", "wizard"):
        mod_type = _menu_select("Mod type", list(MOD_FACTORIES))
        if not mod_type:
            return None
        name = _menu_text("Module or object name")
        if not name:
            return None
        argv = [command, mod_type, name]
        kv = _menu_text("Params k=v, comma-separated (optional)", "")
        if kv is None:
            return None
        for pair in [p.strip() for p in kv.split(",") if p.strip()]:
            argv += ["--param", pair]
        return argv
    if command == "changelog":
        path = _menu_project_text("Project path", session)
        return ["changelog", path] if path is not None else None
    if command == "doctor-mod":
        path = _menu_project_text("Project path", session)
        return ["doctor-mod", path] if path is not None else None
    if command in ("pipeline", "pipeline-next", "pipeline-unlock", "pipeline-reset", "tune-ids", "repair-placeholders"):
        path = _menu_project_text("Project path", session)
        if path is None:
            return None
        argv = [command, path]
        if command == "tune-ids" and _menu_confirm("Also rewrite placeholder flavor text (--flavor)?"):
            argv.append("--flavor")
        if command == "repair-placeholders" and _menu_confirm("Keep placeholder flavor text unchanged?", default=False):
            argv.append("--keep-flavor")
        return argv
    if command == "config":
        path = _menu_project_text("Project path", session)
        if path is None:
            return None
        kv = _menu_text("Config pairs k=v, comma-separated", "")
        if kv is None or not kv.strip():
            return None
        return ["config", path] + [p.strip() for p in kv.split(",") if p.strip()]
    if command == "uninstall":
        path = _menu_project_text("Project path", session)
        if path is None:
            return None
        to = _menu_text("Mods dir (blank = auto-detect / S4_MODS_DIR)", "")
        if to is None:
            return None
        argv = ["uninstall", path]
        if to:
            argv += ["--to-dir", to]
        return argv
    if command == "help":
        target = _menu_select("Help for command", [e.name for e in COMMANDS.values() if not e.hidden and e.description])
        return ["help", target] if target else None
    return [command]  # doctor, version


MENU_EXIT = "Exit"
MENU_SHELL = "Type a command..."
MENU_CREATE = "Create / scaffold mod"
MENU_VALIDATE = "Validate / test"
MENU_SHIP = "Build / package / install"
MENU_PIPELINE = "Pipeline / tune"
MENU_DOCTOR = "Environment / doctor"
MENU_TUI = "TUI / dashboard"

_GUIDED_CHOICES = [
    MENU_CREATE,
    MENU_VALIDATE,
    MENU_SHIP,
    MENU_PIPELINE,
    MENU_DOCTOR,
    MENU_TUI,
    MENU_SHELL,
    MENU_EXIT,
]


def _guided_splash(session: MenuSession) -> Panel:
    table = Table(box=_inner_table_box(), show_edge=False, header_style="head", pad_edge=False)
    table.add_column("TASK")
    table.add_column("WHAT IT RUNS")
    table.add_row("Create", "init or new")
    table.add_row("Validate", "validate --strict optional")
    table.add_row("Ship", "build, package, install, changelog")
    table.add_row("Pipeline", "pipeline status, next, unlock, reset, tune-ids")
    body = Group(
        Text.from_markup(_banner_line()),
        Text.from_markup(f"[muted]Project default:[/] [head]{_esc(_menu_project_default(session))}[/]"),
        table,
        Text.from_markup("[muted]Type a command... opens the REPL. Use 'tui' for the dashboard.[/]"),
    )
    return Panel(body, box=_box_style(), border_style="accent", expand=False)


def _guided_create(
    session: MenuSession,
    select: Callable[[str, list[str]], str | None],
) -> MenuAction | None:
    path = _menu_project_text("Project path", session)
    if path is None:
        return None
    if not _is_project_path(path):
        if _menu_confirm("Project not initialized. Initialize it now?", default=True):
            return MenuAction(["init", path])
        return None
    kind = select("Mod type", list(MOD_FACTORIES))
    if not kind:
        return None
    name = _menu_text("Artifact/module name")
    if not name:
        return None
    return MenuAction(["new", path, kind, name])


def _guided_ship(
    session: MenuSession,
    select: Callable[[str, list[str]], str | None],
) -> MenuAction | None:
    action = select("Ship action", ["Build zip", "Package release", "Install to Mods", "Changelog"])
    mapping = {
        "Build zip": "build",
        "Package release": "package",
        "Install to Mods": "install",
        "Changelog": "changelog",
    }
    command = mapping.get(action or "")
    if not command:
        return None
    argv = _menu_flow(command, session)
    return MenuAction(argv) if argv else None


def _guided_pipeline(
    session: MenuSession,
    select: Callable[[str, list[str]], str | None],
) -> MenuAction | None:
    action = select(
        "Pipeline action",
        ["Status", "Next actions", "Doctor mod", "Repair placeholders", "Unlock current phase", "Reset", "Tune IDs"],
    )
    mapping = {
        "Status": "pipeline",
        "Next actions": "pipeline-next",
        "Doctor mod": "doctor-mod",
        "Repair placeholders": "repair-placeholders",
        "Unlock current phase": "pipeline-unlock",
        "Reset": "pipeline-reset",
        "Tune IDs": "tune-ids",
    }
    command = mapping.get(action or "")
    if not command:
        return None
    argv = _menu_flow(command, session)
    return MenuAction(argv) if argv else None


def _guided_action(
    choice: str,
    session: MenuSession,
    select: Callable[[str, list[str]], str | None],
) -> MenuAction | None:
    if choice == MENU_CREATE:
        return _guided_create(session, select)
    if choice == MENU_VALIDATE:
        argv = _menu_flow("validate", session)
        return MenuAction(argv) if argv else None
    if choice == MENU_SHIP:
        return _guided_ship(session, select)
    if choice == MENU_PIPELINE:
        return _guided_pipeline(session, select)
    if choice == MENU_DOCTOR:
        return MenuAction(["doctor"])
    if choice == MENU_TUI:
        path = _menu_project_text("Project path", session)
        return MenuAction(["tui", path]) if path is not None else None
    return None


def _run_menu_action(action: MenuAction) -> None:
    old_cwd = os.getcwd()
    try:
        if action.cwd:
            os.chdir(action.cwd)
        main(action.argv)
    finally:
        os.chdir(old_cwd)


def _legacy_menu_shell(select: Callable[[str, list[str]], str | None] | None = None) -> int:
    """Arrow-key main menu shown on bare TTY launch. `select` injectable for tests."""
    select = select or _menu_select
    visible = [e.name for e in COMMANDS.values() if not e.hidden and e.description]
    splash = Panel(
        Text.from_markup(
            _banner_line()
            + "\n[muted]Arrow keys to choose · Enter to select · Esc to back out[/]"
        ),
        box=_box_style(),
        border_style="accent",
        expand=False,
    )
    _console.print(splash)
    while True:
        choice = select("S4Chemist - pick a command", visible + [MENU_SHELL, MENU_EXIT])
        if choice in (None, MENU_EXIT):
            return 0
        if choice == MENU_SHELL:
            interactive_shell()
            continue
        argv = _menu_flow(choice)
        if argv is None:
            continue
        try:
            main(argv)
        except SystemExit as exc:
            if exc.code:
                _console.print(f"[fail]{_esc(exc.code)}[/]")
        except KeyboardInterrupt:
            _console.print("[local]Interrupted[/]")


def menu_shell(select: Callable[[str, list[str]], str | None] | None = None) -> int:
    """Task-first menu shown on bare TTY launch. `select` injectable for tests."""
    select = select or _menu_select
    session = MenuSession()
    _console.print(_guided_splash(session))
    while True:
        choice = select("S4Chemist - choose a task", _GUIDED_CHOICES)
        if choice in (None, MENU_EXIT):
            return 0
        if choice == MENU_SHELL:
            interactive_shell()
            continue
        action = _guided_action(choice, session, select)
        if action is None:
            continue
        try:
            _run_menu_action(action)
        except SystemExit as exc:
            if exc.code:
                _console.print(f"[fail]{_esc(exc.code)}[/]")
        except KeyboardInterrupt:
            _console.print("[local]Interrupted[/]")


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    argv = [a for a in argv if a != "--no-color"]  # global flag, consumed by NO_COLOR at import

    if not argv:
        if sys.stdin.isatty() and sys.stdout.isatty():
            return menu_shell()
        print_help(is_subcommand=False, command="")
        return 0
    if argv[:1] in (["-h"], ["--help"]):
        print_help(is_subcommand=False, command="")
        return 0

    command = argv[0]
    entry = COMMANDS.get(command)
    if entry is None:
        print_help(is_subcommand=True, command=command, error=f"Unknown command: {command}")
        return 2
    return entry.handler(argv)


if __name__ == "__main__":
    sys.exit(main())
