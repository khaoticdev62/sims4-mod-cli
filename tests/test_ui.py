"""UI refinement tests: color-off, ASCII fallback, help table, wizard confirm flow."""
import io
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI = REPO_ROOT / "s4chemist_cli.py"
VISIBLE_COMMANDS = [
    "init", "new", "validate", "build", "package", "install",
    "doctor", "version", "help", "generate", "wizard", "changelog",
    "doctor-mod", "repair-placeholders",
]


def run_cli(args, cwd, env_extra=None):
    env = dict(os.environ)
    env.update(env_extra or {})
    result = subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
        stdin=subprocess.DEVNULL,
        env=env,
    )
    return (
        result.stdout.decode("utf-8", errors="replace"),
        result.stderr.decode("utf-8", errors="replace"),
        result.returncode,
    )


def test_help_shows_brand_banner():
    stdout, _, rc = run_cli(["--help"], REPO_ROOT)
    assert rc == 0
    assert "S4CHEMIST" in stdout
    assert "⚗" in stdout
    assert "▸" in stdout  # section glyph


def test_panel_border_style_follows_state():
    sys.path.insert(0, str(REPO_ROOT))
    import s4chemist_cli as cli

    assert cli._panel_border_style(cli._meta_block("fail", "X", "y")) == "fail"
    assert cli._panel_border_style(cli._meta_block("verified", "X", "y")) == "ok"
    assert cli._panel_border_style(cli._meta_block("ok", "X", "y")) == "ok"
    assert cli._panel_border_style(cli._meta_block("local", "X", "y")) == "local"
    assert cli._panel_border_style(["plain"]) == "accent"


def test_ascii_mode_brand_fallback():
    stdout, _, rc = run_cli(["--help"], REPO_ROOT, env_extra={"S4_ASCII": "1"})
    assert rc == 0
    assert "⚗" not in stdout and "▸" not in stdout
    assert "S4CHEMIST" in stdout


def test_ascii_mode_survives_wrapped_stdout(monkeypatch):
    """Regression: Textual replaces sys.stdout with a wrapper lacking .encoding —
    _ascii_mode must not crash and must stay unicode-capable."""
    sys.path.insert(0, str(REPO_ROOT))
    import s4chemist_cli as cli

    class NoEncoding:
        pass

    monkeypatch.setattr(sys, "stdout", NoEncoding())
    monkeypatch.delenv("S4_ASCII", raising=False)
    assert cli._ascii_mode() is False
    assert cli._brand_glyph() == "⚗"


def test_piped_output_has_no_ansi():
    stdout, _, rc = run_cli(["--help"], REPO_ROOT)
    assert rc == 0
    assert "\x1b" not in stdout


def test_no_color_env_has_no_ansi():
    stdout, _, rc = run_cli(["doctor"], REPO_ROOT, env_extra={"NO_COLOR": "1"})
    assert rc in (0, 1)
    assert "\x1b" not in stdout


def test_no_color_flag_accepted():
    stdout, _, rc = run_cli(["--no-color", "version"], REPO_ROOT)
    assert rc == 0
    assert "\x1b" not in stdout
    assert "s4chemist_cli v" in stdout


def test_ascii_mode_uses_no_box_drawing_chars():
    stdout, _, rc = run_cli(["--help"], REPO_ROOT, env_extra={"S4_ASCII": "1"})
    assert rc == 0
    for ch in "┌│└┐─❯":
        assert ch not in stdout
    assert ">" in stdout  # ASCII prompt glyph fallback


def test_unicode_mode_uses_box_drawing():
    stdout, _, rc = run_cli(["--help"], REPO_ROOT)
    assert rc == 0
    assert "┌" in stdout and "└" in stdout


def test_help_lists_all_visible_commands():
    stdout, _, rc = run_cli(["--help"], REPO_ROOT)
    assert rc == 0
    for cmd in VISIBLE_COMMANDS:
        assert cmd in stdout


def test_help_table_has_status_tags():
    stdout, _, rc = run_cli(["--help"], REPO_ROOT)
    assert rc == 0
    assert "[VERIFIED]" in stdout
    assert "[LOCAL]" in stdout


def run_wizard_in_process(cwd, argv, typed):
    """Drive the interactive wizard with a fake TTY and scripted input."""
    import importlib

    class FakeTTY(io.StringIO):
        def isatty(self):
            return True

    old_stdin, old_stdout = sys.stdin, sys.stdout
    sys.stdin = FakeTTY(typed)
    sys.stdout = FakeTTY()
    old_cwd = os.getcwd()
    os.chdir(cwd)
    try:
        sys.path.insert(0, str(REPO_ROOT))
        import s4chemist_cli as cli
        importlib.reload(cli)
        rc = cli.main(argv)
        output = sys.stdout.getvalue()
    finally:
        os.chdir(old_cwd)
        sys.stdin, sys.stdout = old_stdin, old_stdout
    return output, rc


def test_bare_launch_piped_prints_help_and_exits():
    stdout, _, rc = run_cli([], REPO_ROOT)
    assert rc == 0
    assert "COMMANDS" in stdout


def _load_cli():
    import importlib

    sys.path.insert(0, str(REPO_ROOT))
    import s4chemist_cli as cli
    importlib.reload(cli)
    return cli


def _capture_console():
    class FakeTTY(io.StringIO):
        def isatty(self):
            return True

    old_stdin, old_stdout = sys.stdin, sys.stdout
    sys.stdin = FakeTTY("")
    sys.stdout = FakeTTY()
    return old_stdin, old_stdout


def test_interactive_shell_runs_commands_and_exits():
    cli = _load_cli()
    old_stdin, old_stdout = _capture_console()
    try:
        lines = iter(["version", "badcmd", "exit"])
        rc = cli.interactive_shell(reader=lambda: next(lines, None))
        output = sys.stdout.getvalue()
    finally:
        sys.stdin, sys.stdout = old_stdin, old_stdout
    assert rc == 0
    assert "COMMANDS" in output               # help shown on entry
    assert "s4chemist_cli v" in output        # dispatched 'version'
    assert "Unknown command: badcmd" in output  # error shown, shell kept going


def test_interactive_shell_quit_alias():
    cli = _load_cli()
    old_stdin, old_stdout = _capture_console()
    try:
        lines = iter(["quit"])
        rc = cli.interactive_shell(reader=lambda: next(lines, None))
        output = sys.stdout.getvalue()
    finally:
        sys.stdin, sys.stdout = old_stdin, old_stdout
    assert rc == 0
    assert "COMMANDS" in output


def test_menu_runs_command_and_exits():
    cli = _load_cli()
    old_stdin, old_stdout = _capture_console()
    try:
        choices = iter([cli.MENU_DOCTOR, cli.MENU_EXIT])
        rc = cli.menu_shell(select=lambda _msg, _opts: next(choices, "Exit"))
        output = sys.stdout.getvalue()
    finally:
        sys.stdin, sys.stdout = old_stdin, old_stdout
    assert rc == 0
    assert "sims docs" in output.lower()


def test_menu_cancel_is_safe():
    cli = _load_cli()
    old_stdin, old_stdout = _capture_console()
    try:
        # Esc/Ctrl+C on the main menu (None) exits cleanly with no dispatch
        rc = cli.menu_shell(select=lambda _msg, _opts: None)
    finally:
        sys.stdin, sys.stdout = old_stdin, old_stdout
    assert rc == 0


def test_menu_flow_new_collects_args():
    cli = _load_cli()
    answers = {"Existing project path": "/tmp/proj", "Artifact/module name": "CoolTrait"}
    cli._menu_text = lambda msg, default="": answers.get(msg, default)
    cli._menu_select = lambda msg, choices: "trait"
    assert cli._menu_flow("new") == ["new", "/tmp/proj", "trait", "CoolTrait"]


def test_menu_flow_validate_strict_flag():
    cli = _load_cli()
    cli._menu_text = lambda msg, default="": default
    cli._menu_confirm = lambda msg, default=False: True
    assert cli._menu_flow("validate") == ["validate", ".", "--strict"]


def test_menu_session_reuses_project_path(tmp_project):
    cli = _load_cli()
    session = cli.MenuSession()
    defaults = []

    def fake_text(msg, default=""):
        defaults.append((msg, default))
        if msg == "Project path" and default == ".":
            return str(tmp_project)
        return default

    cli._menu_text = fake_text
    cli._menu_confirm = lambda msg, default=False: False

    assert cli._menu_flow("validate", session) == ["validate", str(tmp_project)]
    assert cli._menu_flow("build", session) == ["build", str(tmp_project)]
    assert defaults[1] == ("Project path", str(tmp_project))


def test_guided_create_uses_new_for_existing_project(tmp_project):
    cli = _load_cli()
    session = cli.MenuSession()
    answers = {"Project path": str(tmp_project), "Artifact/module name": "MenuTrait"}
    cli._menu_text = lambda msg, default="": answers.get(msg, default)
    action = cli._guided_action(
        cli.MENU_CREATE,
        session,
        select=lambda msg, choices: "trait" if msg == "Mod type" else choices[0],
    )
    assert action == cli.MenuAction(["new", str(tmp_project), "trait", "MenuTrait"])


def test_menu_flow_generate_params():
    cli = _load_cli()
    answers = {"Module or object name": "MyBuff", "Params k=v, comma-separated (optional)": "label=Chill, mood_weight=3"}
    cli._menu_text = lambda msg, default="": answers.get(msg, default)
    cli._menu_select = lambda msg, choices: "buff"
    assert cli._menu_flow("generate") == ["generate", "buff", "MyBuff", "--param", "label=Chill", "--param", "mood_weight=3"]


def test_menu_flow_cancel_returns_none():
    cli = _load_cli()
    cli._menu_text = lambda msg, default="": None  # user pressed Esc
    assert cli._menu_flow("init") is None


def test_wizard_interactive_confirm_accept(tmp_project):
    typed = "FancyTrait\n"      # label
    typed += "\n"               # description -> default
    typed += "y\n"              # confirm create
    output, rc = run_wizard_in_process(tmp_project, ["wizard", "trait", "UiTrait"], typed)
    assert rc == 0
    assert "Wizard Complete" in output
    assert "Create files?" in output
    assert (tmp_project / "src" / "xml_snippets" / "UiTrait_trait" / "UiTrait_trait.xml").exists()


def test_wizard_interactive_confirm_decline(tmp_project):
    typed = "FancyTrait\n"      # label
    typed += "\n"               # description -> default
    typed += "n\n"              # decline create
    output, rc = run_wizard_in_process(tmp_project, ["wizard", "trait", "NoTrait"], typed)
    assert rc == 2
    assert "Cancelled" in output
    assert not (tmp_project / "src" / "xml_snippets" / "NoTrait_trait").exists()
