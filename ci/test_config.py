"""임시 테스트 (커밋 금지): 옵션 표와 설정 해석"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__import__("os").environ["REPO_ROOT"])
SCRIPTS = REPO / "skills/pro-ui-design/scripts"
CLI = SCRIPTS / "ui_design_cli.py"
sys.path.insert(0, str(SCRIPTS))


@pytest.fixture()
def github_repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "remote", "add", "origin", "https://github.com/a/b.git"], check=True)
    return root


def run_cli(home, *args):
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home), "PYTHONIOENCODING": "utf-8"}
    result = subprocess.run([sys.executable, str(CLI), *args], capture_output=True, text=True, encoding="utf-8", env=env)
    return json.loads(result.stdout)


def test_project_overrides_default_and_legacy(github_repo):
    from pro_ui_design.config import resolve_config
    resolved = resolve_config(github_repo, {
        "ui-design": {"devices": ["phone"], "projects": [{"match": "a/b", "devices": ["desktop"]}]},
        "design_brief": {"designer": "old-id"},
    })
    assert resolved["resolved"]["devices"] == ["desktop"]
    assert resolved["source"]["devices"] == "project"
    assert resolved["resolved"]["designer"] == "old-id"
    assert resolved["source"]["designer"] == "legacy"
    assert resolved["resolved"]["idle_timeout_minutes"] == 240
    assert resolved["source"]["idle_timeout_minutes"] == "builtin"


def test_new_section_beats_legacy_project(github_repo):
    from pro_ui_design.config import resolve_config
    resolved = resolve_config(github_repo, {
        "ui-design": {"destination": "html"},
        "design_brief": {"projects": [{"match": "a/b", "destination": "issue"}]},
    })
    assert resolved["resolved"]["destination"] == "html"
    assert resolved["source"]["destination"] == "default"


def test_invalid_stored_value_falls_back_and_is_reported(github_repo):
    from pro_ui_design.config import resolve_config
    resolved = resolve_config(github_repo, {"ui-design": {"motion_format": "avi"}})
    assert resolved["resolved"]["motion_format"] == "gif"
    assert "motion_format" in resolved["invalid"]


def test_unknown_key_reported_and_kept_on_save(github_repo, tmp_path):
    home = tmp_path / "home"
    config_file = home / ".projectops/config/config.json"
    config_file.parent.mkdir(parents=True)
    config_file.write_text(json.dumps({"ui-design": {"future_option": 1}, "github": {"global_pat": "x"}}))
    shown = run_cli(home, "config", "show", "--root", str(github_repo))
    assert "future_option" in shown["ignored"]
    saved = run_cli(home, "config", "set", "--root", str(github_repo), "--scope", "default", "--destination", "html")
    assert saved["ok"]
    stored = json.loads(config_file.read_text())
    assert stored["ui-design"]["future_option"] == 1
    assert stored["ui-design"]["destination"] == "html"
    assert stored["github"]["global_pat"] == "x"


def test_set_key_value_parses_and_validates(github_repo, tmp_path):
    home = tmp_path / "home"
    saved = run_cli(home, "config", "set", "--root", str(github_repo), "--key", "devices", "--value", "phone,tablet")
    assert saved["ok"]
    assert saved["resolved"]["devices"] == ["phone", "tablet"]
    rejected = run_cli(home, "config", "set", "--root", str(github_repo), "--key", "devices", "--value", "watch")
    assert rejected["ok"] is False and rejected["code"] == "bad_option_value"
    unknown = run_cli(home, "config", "set", "--root", str(github_repo), "--key", "nope", "--value", "1")
    assert unknown["ok"] is False and unknown["code"] == "unknown_option"


def test_parse_minimum_and_bool():
    from pro_ui_design.options import parse_option_value
    assert parse_option_value("idle_timeout_minutes", "30") == 30
    assert parse_option_value("auto_approve", "true") is True
    with pytest.raises(ValueError):
        parse_option_value("idle_timeout_minutes", "0")


def test_config_options_lists_every_definition(tmp_path):
    from pro_ui_design.options import OPTION_DEFINITIONS
    listed = run_cli(tmp_path, "config", "options")
    assert {o["name"] for o in listed["options"]} == {d.name for d in OPTION_DEFINITIONS}


def test_works_without_git_or_config(tmp_path):
    folder = tmp_path / "plain"
    folder.mkdir()
    shown = run_cli(tmp_path, "config", "show", "--root", str(folder))
    assert shown["ok"]
    assert shown["suggest"]["destination"] == "html"
    assert shown["resolved"]["themes"] == ["light", "dark"]
