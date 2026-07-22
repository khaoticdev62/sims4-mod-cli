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


def test_tui_has_three_tabs(tmp_project):
    cli = _load_cli()
    from textual.widgets import TabbedContent, TabPane

    async def go():
        app = cli._make_tui_app(str(tmp_project))
        async with app.run_test(size=(120, 40)):
            tabs = app.query_one(TabbedContent)
            pane_ids = [pane.id for pane in tabs.query(TabPane)]
            assert pane_ids == ["tab-pipeline", "tab-files", "tab-log"]

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


def test_tui_wizard_modal_creates_artifact(tmp_project):
    cli = _load_cli()
    import os

    old_cwd = os.getcwd()
    os.chdir(tmp_project)
    try:
        async def go():
            app = cli._make_tui_app(str(tmp_project))
            async with app.run_test(size=(120, 40)) as pilot:
                from textual.widgets import Button, Input
                app.query_one("#open-wizard", Button).press()
                assert await _wait_for(lambda: type(app.screen_stack[-1]).__name__ == "WizardScreen")
                screen = app.screen_stack[-1]
                assert await _wait_for(lambda: bool(screen.query("#w_name")))
                screen.query_one("#w_name", Input).value = "ModalTrait"
                screen.query_one("#w_create", Button).press()
                await pilot.pause()
                await app.workers.wait_for_complete()

        _run(go())
    finally:
        os.chdir(old_cwd)
    assert (tmp_project / "src" / "xml_snippets" / "ModalTrait_trait" / "ModalTrait_trait.xml").exists()


def test_tui_wizard_modal_requires_name(tmp_project):
    cli = _load_cli()

    async def go():
        app = cli._make_tui_app(str(tmp_project))
        async with app.run_test(size=(120, 40)):
            from textual.widgets import Button, Label
            app.query_one("#open-wizard", Button).press()
            assert await _wait_for(lambda: type(app.screen_stack[-1]).__name__ == "WizardScreen")
            screen = app.screen_stack[-1]
            assert await _wait_for(lambda: bool(screen.query("#w_create")))
            screen.query_one("#w_create", Button).press()
            assert await _wait_for(lambda: "name is required" in str(screen.query_one("#w_error", Label).content))

    _run(go())


def test_tui_generate_creates_artifact(tmp_project):
    cli = _load_cli()
    import os

    old_cwd = os.getcwd()
    os.chdir(tmp_project)  # generate works on the project in cwd
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
