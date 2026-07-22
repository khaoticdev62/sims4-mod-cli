import zipfile
from pathlib import Path

from tests.utils import cli_runner


def test_init_creates_project(tmp_path, repo_root):
    proj = tmp_path / "NewMod"
    stdout, _, rc = cli_runner(["init", str(proj)], repo_root)
    assert rc == 0
    assert proj.exists()
    assert (proj / "s4modconfig.yaml").exists()
    assert (proj / ".gitignore").exists()


def test_new_creates_artifacts(tmp_project, repo_root):
    kinds = ["trait", "buff", "career", "ts4script", "package"]
    for kind in kinds:
        name = f"{kind.title()}Test"
        stdout, _, rc = cli_runner(["new", str(tmp_project), kind, name], repo_root)
        assert rc == 0
        assert name in stdout


def test_validate_counts_issues(tmp_project, repo_root):
    stdout, _, rc = cli_runner(["validate", str(tmp_project)], repo_root)
    assert rc >= 0
    assert "Validation" in stdout


def test_build_creates_zip(tmp_project, repo_root):
    stdout, _, rc = cli_runner(["build", str(tmp_project)], repo_root)
    assert rc == 0
    zips = list((tmp_project / "dist").glob("*.zip"))
    assert len(zips) == 1
    assert zipfile.is_zipfile(zips[0])


def test_package_creates_release_zip(tmp_project, repo_root):
    stdout, _, rc = cli_runner(["package", str(tmp_project)], repo_root)
    assert rc == 0
    zips = list((tmp_project / "dist").glob("*.zip"))
    assert any("-release-" in z.name for z in zips)


def test_build_release_uses_release_name(tmp_project, repo_root):
    stdout, _, rc = cli_runner(["build", "--release", str(tmp_project)], repo_root)
    assert rc == 0
    zips = list((tmp_project / "dist").glob("*.zip"))
    assert any("-release-" in z.name for z in zips)


def test_pipeline_status_renders(tmp_project, repo_root):
    stdout, _, rc = cli_runner(["pipeline", str(tmp_project)], repo_root)
    assert rc == 0
    assert "pipeline" in stdout.lower() or "Phase" in stdout


ALL_KINDS = [
    "xml_snippet", "ts4script", "package", "career", "trait", "buff", "interaction",
    "event", "achievement", "aspiration", "whim", "club", "holiday", "loot_action",
    "testset", "relationship", "skill", "motive",
]


def test_new_supports_all_mod_kinds(tmp_project, repo_root):
    for kind in ALL_KINDS:
        name = f"All{kind.title().replace('_', '')}"
        stdout, stderr, rc = cli_runner(["new", str(tmp_project), kind, name], repo_root)
        assert rc == 0, f"new {kind} failed: {stderr}"
    stdout, _, rc = cli_runner(["validate", str(tmp_project)], repo_root)
    assert rc == 0, f"validate after all kinds reported issues: {stdout}"
    stdout, _, rc = cli_runner(["build", str(tmp_project)], repo_root)
    assert rc == 0
    zips = list((tmp_project / "dist").glob("*.zip"))
    assert len(zips) == 1
    with zipfile.ZipFile(zips[0]) as zf:
        assert zf.testzip() is None
        assert not any(n.startswith("dist/") for n in zf.namelist())
