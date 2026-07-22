import subprocess
import sys
from pathlib import Path
import pytest


@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    proj = tmp_path / "TestMod"
    proj.mkdir()
    (proj / "src" / "xml_snippets").mkdir(parents=True)
    (proj / "src" / "ts4script").mkdir(parents=True)
    (proj / "src" / "package").mkdir(parents=True)
    (proj / "dist").mkdir()
    (proj / "tmp").mkdir()
    (proj / "s4modconfig.yaml").write_text(
        "mod_name: TestMod\ncreator: Tester\nversion: 0.1.0\nmod_type: xml_snippet\nxml_injector_required: false\ngame_versions:\n  - '*'\n",
        encoding="utf-8",
    )
    (proj / "mod_notes.txt").write_text("# Test notes\n", encoding="utf-8")
    (proj / ".gitignore").write_text("dist/\ntmp/\n", encoding="utf-8")
    return proj


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def cli_runner(args, cwd):
    result = subprocess.run(
        [sys.executable, "s4chemist_cli.py", *args],
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
    )
    # Decode manually: text=True loses output on some Windows Pythons (3.11.9)
    # because the CLI reconfigures its stdout to UTF-8.
    return (
        result.stdout.decode("utf-8", errors="replace"),
        result.stderr.decode("utf-8", errors="replace"),
        result.returncode,
    )
