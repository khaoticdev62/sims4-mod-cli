from tests.utils import cli_runner


def test_help_shows_commands(repo_root):
    stdout, _, rc = cli_runner(["--help"], repo_root)
    assert rc == 0
    assert "init" in stdout
    assert "validate" in stdout
    assert "build" in stdout


def test_version_prints(repo_root):
    stdout, _, rc = cli_runner(["version"], repo_root)
    assert rc == 0
    assert "s4chemist_cli v0.1.1" in stdout


def test_doctor_checks_environment(repo_root):
    stdout, _, rc = cli_runner(["doctor"], repo_root)
    assert rc in (0, 1)
    assert "Python" in stdout
