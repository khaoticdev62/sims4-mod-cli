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


def test_interactive_shell_runs_commands_and_exits(tmp_project):
    typed = "version\nbadcmd\nexit\n"
    output, rc = run_wizard_in_process(tmp_project, [], typed)
    assert rc == 0
    assert "COMMANDS" in output               # help shown on entry
    assert "s4chemist_cli v" in output        # dispatched 'version'
    assert "Unknown command: badcmd" in output  # error shown, shell kept going


def test_interactive_shell_quit_alias(tmp_project):
    output, rc = run_wizard_in_process(tmp_project, [], "quit\n")
    assert rc == 0
    assert "COMMANDS" in output


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
