"""Headless Textual TUI tests using app.run_test()."""
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_cli():
    import importlib

    sys.path.insert(0, str(REPO_ROOT))
    import s4chemist_cli as cli
    importlib.reload(cli)
    return cli


def _run(coro):
    return asyncio.run(coro)


def test_tui_status_bar_shows_phase_and_progress(tmp_project):
    cli = _load_cli()
    from textual.widgets import Static

    async def go():
        app = cli._make_tui_app(str(tmp_project))
        async with app.run_test(size=(120, 40)):
            bar = app.query_one("#status-bar", Static)
            text = str(bar.content)
            assert "Phase:" in text
            assert "Progress:" in text
            assert "Concept" in text

    _run(go())


def test_tui_pipeline_statuses_are_colored(tmp_project):
    cli = _load_cli()
    from rich.text import Text
    from textual.widgets import DataTable

    async def go():
        app = cli._make_tui_app(str(tmp_project))
        async with app.run_test(size=(120, 40)):
            table = app.query_one("#pipeline", DataTable)
            cell = table.get_row_at(0)[1]  # Status column, first row (ACTIVE concept)
            assert isinstance(cell, Text)
            assert cell.style and cell.plain == "ACTIVE"

    _run(go())


def test_tui_app_loads_with_pipeline_table(tmp_project):
    cli = _load_cli()
    from textual.widgets import DataTable

    async def go():
        app = cli._make_tui_app(str(tmp_project))
        async with app.run_test(size=(120, 40)):
            table = app.query_one("#pipeline", DataTable)
            assert table.row_count == len(cli.PIPELINE_PHASES)

    _run(go())


def test_tui_validate_button_streams_to_log(tmp_project):
    cli = _load_cli()

    async def go():
        app = cli._make_tui_app(str(tmp_project))
        async with app.run_test(size=(120, 40)) as pilot:
            from textual.widgets import Button
            app.query_one("#validate", Button).press()
            await pilot.pause()
            await app.workers.wait_for_complete()
            text = "\n".join(app.history)
            assert "validate" in text
            assert "Validation" in text

    _run(go())


def test_tui_generate_requires_name(tmp_project):
    cli = _load_cli()

    async def go():
        app = cli._make_tui_app(str(tmp_project))
        async with app.run_test(size=(120, 40)) as pilot:
            from textual.widgets import Button
            app.query_one("#generate", Button).press()
            await pilot.pause()
            assert "name is required" in "\n".join(app.history)

    _run(go())


def test_tui_has_four_tabs(tmp_project):
    cli = _load_cli()
    from textual.widgets import TabbedContent, TabPane

    async def go():
        app = cli._make_tui_app(str(tmp_project))
        async with app.run_test(size=(120, 40)):
            tabs = app.query_one(TabbedContent)
            pane_ids = [pane.id for pane in tabs.query(TabPane)]
            assert pane_ids == ["tab-pipeline", "tab-create", "tab-files", "tab-log"]

    _run(go())


def test_tui_files_tab_lazy_mounts_tree(tmp_project):
    cli = _load_cli()
    from textual.widgets import TabbedContent

    async def go():
        app = cli._make_tui_app(str(tmp_project))
        async with app.run_test(size=(120, 40)) as pilot:
            assert len(app.query("#files")) == 0  # not mounted at startup
            app.query_one(TabbedContent).active = "tab-files"
            await pilot.pause()
            assert len(app.query("#files")) == 1  # lazy-mounted on first activation

    _run(go())


def test_tui_phase_detail_updates_on_row(tmp_project):
    cli = _load_cli()
    from textual.widgets import Static

    async def go():
        app = cli._make_tui_app(str(tmp_project))
        async with app.run_test(size=(120, 40)):
            app._show_phase_detail(0)
            detail = app.query_one("#phase-detail", Static)
            text = str(detail.content)
            assert "Concept" in text
            assert "Artifact" in text

    _run(go())


def test_tui_palette_provider_returns_hits(tmp_project):
    cli = _load_cli()

    async def go():
        app = cli._make_tui_app(str(tmp_project))
        async with app.run_test(size=(120, 40)):
            provider = next(c(app.screen) for c in type(app).COMMANDS if c.__name__ == "S4Commands")
            hits = [hit async for hit in provider.search("valid")]
            assert any("Validate" in str(hit.match_display) for hit in hits)

    _run(go())


async def _wait_for(predicate, timeout=5.0):
    """Poll until predicate() is true; returns False on timeout."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(0.05)
    return predicate()


def test_tui_create_tab_type_switch_rebuilds_params(tmp_project):
    """Switching mod type must rebuild params without DuplicateIds (remove awaited)."""
    cli = _load_cli()

    async def go():
        app = cli._make_tui_app(str(tmp_project))
        async with app.run_test(size=(120, 40)):
            from textual.containers import Vertical
            from textual.widgets import Select
            assert await _wait_for(lambda: len(app.query_one("#w_params", Vertical).children) > 0)
            app.query_one("#w_type", Select).value = "career"
            # career preset: label, description, pay, level_title
            assert await _wait_for(
                lambda: len([w for w in app.query_one("#w_params", Vertical).children
                             if type(w).__name__ == "Input"]) == 4
            )
            app.query_one("#w_type", Select).value = "trait"
            assert await _wait_for(
                lambda: len([w for w in app.query_one("#w_params", Vertical).children
                             if type(w).__name__ == "Input"]) == 2
            )

    _run(go())


def test_tui_create_tab_all_fields_visible_on_small_screen(tmp_project):
    """The Create tab must keep every interactive element on-screen at 22 rows."""
    cli = _load_cli()

    async def go():
        app = cli._make_tui_app(str(tmp_project))
        async with app.run_test(size=(100, 22)):
            from textual.widgets import Select
            assert await _wait_for(lambda: bool(app.query("#w_create")))
            app.query_one("#w_type", Select).value = "career"  # 4 params = worst case
            assert await _wait_for(
                lambda: len([w for w in app.query_one("#w_params").children
                             if type(w).__name__ == "Input"]) == 4
            )
            for wid in ("w_type", "w_name", "w_create", "w_error", "w_params_scroll"):
                region = app.query_one(f"#{wid}").region
                assert region.y < 22, f"#{wid} off-screen at y={region.y}"

    _run(go())


def test_tui_create_tab_creates_artifact(tmp_project, tmp_path):
    cli = _load_cli()
    import os

    old_cwd = os.getcwd()
    os.chdir(tmp_path)  # cwd is NOT the TUI project; the form must still target it
    try:
        async def go():
            app = cli._make_tui_app(str(tmp_project))
            async with app.run_test(size=(120, 40)) as pilot:
                from textual.widgets import Button, Input
                assert await _wait_for(lambda: bool(app.query("#w_name")))
                app.query_one("#w_name", Input).value = "TabTrait"
                app.query_one("#w_create", Button).press()
                await pilot.pause()
                await app.workers.wait_for_complete()

        _run(go())
    finally:
        os.chdir(old_cwd)
    assert (tmp_project / "src" / "xml_snippets" / "TabTrait_trait" / "TabTrait_trait.xml").exists()
    # and must NOT leak a new project into the wrong cwd
    assert not (tmp_path / "TabTrait").exists()


def test_tui_create_tab_requires_name(tmp_project):
    cli = _load_cli()

    async def go():
        app = cli._make_tui_app(str(tmp_project))
        async with app.run_test(size=(120, 40)):
            from textual.widgets import Button, Label
            assert await _wait_for(lambda: bool(app.query("#w_create")))
            app.query_one("#w_create", Button).press()
            assert await _wait_for(lambda: "name is required" in str(app.query_one("#w_error", Label).content))

    _run(go())


def test_tui_create_tab_button_opens_tab(tmp_project):
    cli = _load_cli()

    async def go():
        app = cli._make_tui_app(str(tmp_project))
        async with app.run_test(size=(120, 40)):
            from textual.widgets import Button, TabbedContent
            app.query_one("#open-wizard", Button).press()
            await _wait_for(lambda: app.query_one(TabbedContent).active == "tab-create")
            assert app.query_one(TabbedContent).active == "tab-create"

    _run(go())


def test_tui_generate_creates_artifact(tmp_project, tmp_path):
    cli = _load_cli()
    import os

    old_cwd = os.getcwd()
    os.chdir(tmp_path)  # cwd is NOT the TUI project; generate must still target it
    try:
        async def go():
            app = cli._make_tui_app(str(tmp_project))
            async with app.run_test(size=(120, 40)) as pilot:
                from textual.widgets import Button, Input
                app.query_one("#gen_name", Input).value = "TuiTrait"
                app.query_one("#generate", Button).press()
                await pilot.pause()
                await app.workers.wait_for_complete()

        _run(go())
    finally:
        os.chdir(old_cwd)
    assert (tmp_project / "src" / "xml_snippets" / "TuiTrait_trait" / "TuiTrait_trait.xml").exists()


def test_tui_non_project_path_shows_hint(tmp_path):
    cli = _load_cli()
    from textual.widgets import DataTable

    async def go():
        app = cli._make_tui_app(str(tmp_path))
        async with app.run_test(size=(120, 40)):
            table = app.query_one("#pipeline", DataTable)
            assert table.row_count == 1  # "not a project" hint row

    _run(go())
