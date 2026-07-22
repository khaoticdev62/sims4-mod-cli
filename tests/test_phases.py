"""Regression tests for PLAN.md phases 3-5: validation output, wizard scriptability,
packaging hardening (S4_MODS_DIR + archive integrity)."""
import os
import subprocess
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLI = REPO_ROOT / "s4chemist_cli.py"


def run_cli(args, cwd, env_extra=None):
    env = dict(os.environ)
    env.update(env_extra or {})
    result = subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
        stdin=subprocess.DEVNULL,  # force non-interactive
        env=env,
    )
    # Decode manually: text=True loses output on some Windows Pythons (3.11.9)
    # because the CLI reconfigures its stdout to UTF-8.
    return (
        result.stdout.decode("utf-8", errors="replace"),
        result.stderr.decode("utf-8", errors="replace"),
        result.returncode,
    )


# --- Phase 3: validation -------------------------------------------------

def test_validate_lists_actionable_issue_for_bad_xml(tmp_project):
    bad = tmp_project / "src" / "xml_snippets" / "broken.xml"
    bad.write_text("<I d=\"0x1\"></I>\n", encoding="utf-8")
    stdout, _, rc = run_cli(["validate", str(tmp_project)], REPO_ROOT)
    assert rc >= 1
    assert "broken.xml" in stdout
    assert "XML declaration" in stdout


def test_validate_lists_missing_tuning_tags(tmp_project):
    buff = tmp_project / "src" / "xml_snippets" / "My_buff.xml"
    buff.write_text("<?xml version='1.0' encoding='utf-8'?>\n<I d=\"0x1\"></I>\n", encoding="utf-8")
    stdout, _, rc = run_cli(["validate", str(tmp_project)], REPO_ROOT)
    assert rc >= 1
    assert "buff_name" in stdout
    assert "mood_type" in stdout


def test_validate_clean_scaffold_stays_zero(tmp_project, repo_root):
    from tests.utils import cli_runner
    cli_runner(["new", str(tmp_project), "trait", "CoolTrait"], repo_root)
    stdout, _, rc = run_cli(["validate", str(tmp_project)], REPO_ROOT)
    assert rc == 0
    assert "0 issues" in stdout


def test_validate_strict_flags_template_and_placeholders(tmp_project):
    cfg = tmp_project / "s4modconfig.yaml"
    cfg.write_text(cfg.read_text(encoding="utf-8").replace("TestMod", "ReplaceMe"), encoding="utf-8")
    trait = tmp_project / "src" / "xml_snippets" / "T_trait.xml"
    trait.write_text(
        "<?xml version='1.0' encoding='utf-8'?>\n<I d=\"0x00000000\">\n"
        "  <T n=\"trait_name\">T</T>\n  <T n=\"trait_description\">Replace with trait flavor text.</T>\n</I>\n",
        encoding="utf-8",
    )
    stdout, _, rc = run_cli(["validate", str(tmp_project), "--strict"], REPO_ROOT)
    assert rc >= 3
    assert "ReplaceMe" in stdout
    assert "0x00000000" in stdout
    assert "tune-ids" in stdout
    assert "flavor text" in stdout


def test_validate_non_strict_ignores_placeholders(tmp_project):
    trait = tmp_project / "src" / "xml_snippets" / "T_trait.xml"
    trait.write_text(
        "<?xml version='1.0' encoding='utf-8'?>\n<I d=\"0x00000000\">\n"
        "  <T n=\"trait_name\">T</T>\n  <T n=\"trait_description\">Replace with trait flavor text.</T>\n</I>\n",
        encoding="utf-8",
    )
    _, _, rc = run_cli(["validate", str(tmp_project)], REPO_ROOT)
    assert rc == 0


# --- Phase 4: wizard scriptability ---------------------------------------

def test_wizard_noninteractive_scaffolds_with_name(tmp_project):
    stdout, _, rc = run_cli(["wizard", "trait", "WizTrait"], tmp_project)
    assert rc == 0
    assert "non-interactive" in stdout
    assert "Wizard Complete" in stdout
    assert (tmp_project / "src" / "xml_snippets" / "WizTrait_trait" / "WizTrait_trait.xml").exists()
    assert (tmp_project / "CHANGELOG.md").exists()


def test_wizard_noninteractive_requires_name(tmp_project):
    stdout, _, rc = run_cli(["wizard", "trait"], tmp_project)
    assert rc == 2
    assert "name is required" in stdout


def test_wizard_param_name_form(tmp_project):
    stdout, _, rc = run_cli(["wizard", "buff", "--param", "name=NamedBuff"], tmp_project)
    assert rc == 0
    assert (tmp_project / "src" / "xml_snippets" / "NamedBuff_buff" / "NamedBuff_buff.xml").exists()


def test_wizard_param_overrides_prompt(tmp_project):
    stdout, _, rc = run_cli(["wizard", "trait", "ParamTrait", "--param", "label=FancyTrait"], tmp_project)
    assert rc == 0
    xml = (tmp_project / "src" / "xml_snippets" / "ParamTrait_trait" / "ParamTrait_trait.xml").read_text(encoding="utf-8")
    assert "<T n=\"trait_name\">FancyTrait</T>" in xml


# --- Phase 5: packaging hardening ----------------------------------------

def test_install_uses_s4_mods_dir(tmp_project, tmp_path):
    mods = tmp_path / "CustomMods"
    mods.mkdir()
    stdout, _, rc = run_cli(["install", str(tmp_project)], REPO_ROOT, env_extra={"S4_MODS_DIR": str(mods)})
    assert rc == 0
    installed = mods / tmp_project.name
    assert installed.exists()
    assert (installed / "s4modconfig.yaml").exists()
    assert not (installed / "dist").exists()
    assert not (installed / "tmp").exists()


def test_install_to_dir_beats_s4_mods_dir(tmp_project, tmp_path):
    env_mods = tmp_path / "EnvMods"
    cli_mods = tmp_path / "CliMods"
    env_mods.mkdir()
    cli_mods.mkdir()
    stdout, _, rc = run_cli(
        ["install", str(tmp_project), "--to-dir", str(cli_mods)],
        REPO_ROOT,
        env_extra={"S4_MODS_DIR": str(env_mods)},
    )
    assert rc == 0
    assert (cli_mods / tmp_project.name).exists()
    assert not (env_mods / tmp_project.name).exists()


def test_install_missing_s4_mods_dir_errors(tmp_project, tmp_path):
    _, stderr, rc = run_cli(
        ["install", str(tmp_project)],
        REPO_ROOT,
        env_extra={"S4_MODS_DIR": str(tmp_path / "does-not-exist")},
    )
    assert rc != 0
    assert "S4_MODS_DIR does not exist" in stderr


def test_build_zip_passes_integrity_and_excludes(tmp_project, repo_root):
    from tests.utils import cli_runner
    cli_runner(["new", str(tmp_project), "trait", "ZipTrait"], repo_root)
    _, _, rc = run_cli(["build", str(tmp_project)], REPO_ROOT)
    assert rc == 0
    zips = list((tmp_project / "dist").glob("*.zip"))
    assert len(zips) == 1
    assert zipfile.is_zipfile(zips[0])
    with zipfile.ZipFile(zips[0]) as zf:
        assert zf.testzip() is None
        names = zf.namelist()
    assert names, "archive must not be empty"
    assert any(n.endswith("s4modconfig.yaml") for n in names)
    assert not any(n.startswith(("dist/", "tmp/", "dist\\", "tmp\\")) for n in names)
    assert not any(n.endswith(".gitignore") for n in names)


def test_package_excludes_owners_guide_but_build_includes_it(tmp_project, repo_root):
    from tests.utils import cli_runner
    cli_runner(["new", str(tmp_project), "trait", "GuideTrait"], repo_root)
    (tmp_project / "OWNERS-GUIDE.txt").write_text("guide\n", encoding="utf-8")
    _, _, rc = run_cli(["package", str(tmp_project)], REPO_ROOT)
    assert rc == 0
    release = next(z for z in (tmp_project / "dist").glob("*.zip") if "-release-" in z.name)
    with zipfile.ZipFile(release) as zf:
        assert not any(n.endswith("OWNERS-GUIDE.txt") for n in zf.namelist())
    _, _, rc = run_cli(["build", str(tmp_project)], REPO_ROOT)
    assert rc == 0
    plain = next(z for z in (tmp_project / "dist").glob("*.zip") if "-release-" not in z.name)
    with zipfile.ZipFile(plain) as zf:
        assert any(n.endswith("OWNERS-GUIDE.txt") for n in zf.namelist())
