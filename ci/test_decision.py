"""임시 테스트 (커밋 금지): 결정 기록, 디자이너 절차의 시안 출처"""
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


class Space:
    def __init__(self, tmp_path):
        self.root = tmp_path / "repo"
        self.root.mkdir()
        self.home = tmp_path / "home"
        self.home.mkdir()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)

    def cli(self, *args):
        env = {**os.environ, "HOME": str(self.home), "USERPROFILE": str(self.home), "PROJECTOPS_HOME": str(self.home / ".projectops"),
               "PYTHONIOENCODING": "utf-8"}
        out = subprocess.run([sys.executable, str(CLI), *args, "--root", str(self.root)],
                             capture_output=True, text=True, encoding="utf-8", env=env, timeout=30)
        return json.loads(out.stdout)


@pytest.fixture()
def space(tmp_path):
    workspace = Space(tmp_path)
    yield workspace
    workspace.cli("stop")


def test_decision_absent_is_ok_empty(space):
    result = space.cli("decision")
    assert result["ok"] and result["decision"] is None


def test_decide_without_session(space):
    assert space.cli("decide", "--choice", "a", "--reason", "x")["code"] == "no_session"


def test_decide_then_read_roundtrip(space):
    started = space.cli("start", "--title", "sheet", "--issue", "12")
    screens = Path(started["screens_dir"])
    (screens / "motion.html").write_text("<p>x</p>")
    captures = Path(started["run_dir"]) / "captures"
    captures.mkdir()
    (captures / "motion__b.png").write_text("x")
    (captures / "other__a.png").write_text("x")
    events = Path(started["state_dir"]) / "events.jsonl"
    events.write_text(json.dumps({"choice": "b", "text": "B. Spring", "screen": "motion.html"}) + "\n")
    saved = space.cli("decide", "--choice", "b", "--reason", "fits the app", "--comment-url", "https://x/1")
    assert saved["ok"] and "pro-report" in saved["next"]
    decision = space.cli("decision")["decision"]
    assert decision["chosen"] == "b" and decision["chosen_name"] == "B. Spring"
    assert decision["reason"] == "fits the app" and decision["issue"] == 12
    assert decision["screen"] == "motion.html" and decision["comment_url"] == "https://x/1"
    assert [Path(p).name for p in decision["captures"]] == ["motion__b.png"]
    assert decision["run_dir"] == started["run_dir"]


def test_terminal_only_choice_needs_screen_or_uses_newest(space):
    started = space.cli("start", "--title", "sheet")
    (Path(started["screens_dir"]) / "layout.html").write_text("<p>x</p>")
    space.cli("decide", "--choice", "a", "--reason", "said in terminal")
    decision = space.cli("decision")["decision"]
    assert decision["screen"] == "layout.html" and decision["chosen_name"] is None


def test_latest_decision_found_after_another_session_starts(space):
    first = space.cli("start", "--title", "one")
    (Path(first["screens_dir"]) / "a.html").write_text("x")
    space.cli("decide", "--choice", "a", "--reason", "r")
    space.cli("start", "--title", "two")
    assert space.cli("decision")["decision"]["title"] == "one"
    space.cli("stop")


def test_mockup_source_allowed_only_in_alternatives():
    from pro_ui_design.board_markdown import preflight
    assert preflight({"alternatives": [{"id": "A", "source": "mockup", "image": "a.png"}]}) == []
    current = preflight({"current": [{"label": "Now", "source": "mockup", "image": "a.png"}]})
    assert any("mockup" in warning for warning in current)
    state = preflight({"states": [{"name": "Empty", "reachable": "yes", "source": "mockup", "image": "a.png"}]})
    assert any("mockup" in warning for warning in state)
    assert any("no evidence" in warning or "mockup" in warning
               for warning in preflight({"facts": [{"claim": "x", "basis": "mockup", "ref": "y"}]}))


def test_mockup_source_has_board_label():
    from pro_ui_design.board_html import SOURCE_TAG
    assert "mockup" in SOURCE_TAG
