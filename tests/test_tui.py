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
    from textual.widgets import RichLog

    async def go():
        app = cli._make_tui_app(str(tmp_project))
        async with app.run_test(size=(120, 40)) as pilot:
            from textual.widgets import Button
            app.query_one("#validate", Button).press()
            await pilot.pause()
            await app.workers.wait_for_complete()
            log = app.query_one("#log", RichLog)
            text = "\n".join(getattr(strip, "text", str(strip)) for strip in log.lines)
            assert "validate" in text
            assert "Validation" in text

    _run(go())


def test_tui_generate_requires_name(tmp_project):
    cli = _load_cli()
    from textual.widgets import RichLog

    async def go():
        app = cli._make_tui_app(str(tmp_project))
        async with app.run_test(size=(120, 40)) as pilot:
            from textual.widgets import Button
            app.query_one("#generate", Button).press()
            await pilot.pause()
            log = app.query_one("#log", RichLog)
            text = "\n".join(getattr(strip, "text", str(strip)) for strip in log.lines)
            assert "name is required" in text

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
