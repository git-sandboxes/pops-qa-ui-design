"""임시 테스트 (커밋 금지): tokens, check, 프로젝트 하네스"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__import__("os").environ["REPO_ROOT"])
CLI = REPO / "skills/pro-ui-design/scripts/ui_design_cli.py"


class Space:
    def __init__(self, tmp_path):
        self.root = tmp_path / "repo"
        self.root.mkdir()
        self.home = tmp_path / "home"
        self.home.mkdir()
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)

    def cli(self, *args):
        env = {**os.environ, "HOME": str(self.home), "PROJECTOPS_HOME": str(self.home / ".projectops"),
               "PYTHONIOENCODING": "utf-8"}
        out = subprocess.run([sys.executable, str(CLI), *args, "--root", str(self.root)],
                             capture_output=True, text=True, encoding="utf-8", env=env, timeout=30)
        return json.loads(out.stdout)

    def write(self, relative, text=""):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path


@pytest.fixture()
def space(tmp_path):
    workspace = Space(tmp_path)
    yield workspace
    workspace.cli("stop")


def paths_of(result, kind=None):
    return {c["path"] for c in result["candidates"] if kind is None or c["kind"] == kind}


def test_flutter_candidates(space):
    space.write("client/pubspec.yaml", "name: x\nflutter:\n  fonts:\n    - family: Foo\n")
    space.write("client/lib/core/theme/app_colors.dart")
    space.write("client/lib/core/theme/app_theme.dart")
    space.write("client/lib/core/theme/app_motion.dart")
    space.write("client/assets/fonts/Foo.ttf")
    space.write("docs/design-system.md")
    result = space.cli("tokens")
    assert "client/lib/core/theme/app_colors.dart" in paths_of(result, "color")
    assert "client/lib/core/theme/app_theme.dart" in paths_of(result, "theme")
    assert "client/lib/core/theme/app_motion.dart" in paths_of(result, "motion")
    assert "client/assets/fonts/Foo.ttf" in paths_of(result, "font")
    assert "client/pubspec.yaml" in paths_of(result, "font")
    assert "docs/design-system.md" in paths_of(result, "document")


def test_auth_token_files_are_not_design_tokens(space):
    space.write("lib/core/storage/token_store.dart")
    space.write("lib/features/push/push_token_registrar.dart")
    assert space.cli("tokens")["candidates"] == []


def test_web_candidates(space):
    space.write("package.json", '{"dependencies":{"next":"1"}}')
    space.write("tailwind.config.ts")
    space.write("src/styles/tokens.css")
    space.write("src/app/globals.css")
    space.write("src/components/ui/button.tsx")
    result = space.cli("tokens")
    assert {"tailwind.config.ts", "src/styles/tokens.css", "src/app/globals.css"} <= paths_of(result)
    assert "src/components/ui/button.tsx" in paths_of(result, "component")


def test_native_candidates(space):
    space.write("ios/App/Theme/AppColors.swift")
    space.write("android/app/src/main/java/x/ui/theme/Color.kt")
    space.write("android/app/src/main/res/values/colors.xml")
    found = paths_of(space.cli("tokens"))
    assert "ios/App/Theme/AppColors.swift" in found
    assert "android/app/src/main/java/x/ui/theme/Color.kt" in found
    assert "android/app/src/main/res/values/colors.xml" in found


def test_ignored_folders_skipped(space):
    space.write("node_modules/x/tailwind.config.js")
    space.write("build/app_colors.dart")
    space.write(".dart_tool/theme.dart")
    assert space.cli("tokens")["candidates"] == []


def test_no_tokens_returns_empty_not_error(space):
    space.write("server/main.py")
    result = space.cli("tokens")
    assert result["ok"] and result["candidates"] == [] and "neutral" in result["next"]


def test_start_reports_no_profile_then_saved_profile(space):
    space.write("lib/theme/app_colors.dart", "a")
    assert space.cli("start", "--title", "a")["project_profile"]["exists"] is False
    saved = space.cli("tokens", "--save")
    assert saved["saved"]["readme_created"] is True
    readme = Path(saved["saved"]["readme"])
    assert readme.is_file() and "## Summary" in readme.read_text()
    assert "/launch/" in str(readme) and "/harness/ui-design/" in str(readme)
    readme.write_text("# ui-design\n\n## Summary\nUse AppColors only.\n")
    again = space.cli("tokens", "--save")
    assert again["saved"]["readme_created"] is False and "AppColors" in readme.read_text()
    profile = space.cli("start", "--title", "a")["project_profile"]
    assert profile["exists"] is True and "AppColors" in profile["excerpt"] and profile["changed_files"] == []


def test_changed_token_file_is_reported(space):
    token_file = space.write("lib/theme/app_colors.dart", "a")
    space.cli("tokens", "--save")
    token_file.write_text("b")
    started = space.cli("start", "--title", "a")
    assert started["project_profile"]["changed_files"] == ["lib/theme/app_colors.dart"]
    assert "tokens --save" in started["next"]


def test_deleted_token_file_is_reported(space):
    token_file = space.write("lib/theme/app_colors.dart", "a")
    space.cli("tokens", "--save")
    token_file.unlink()
    assert space.cli("start", "--title", "a")["project_profile"]["changed_files"] == ["lib/theme/app_colors.dart"]


def screen(space, name, html):
    data = space.cli("start", "--title", "chk")
    path = Path(data["screens_dir"]) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return Path(data["screens_dir"])


def test_check_flags_color_font_url_path(space):
    screen(space, "a.html", '<style>.a{color:#123456;font-family:"Foo",sans-serif}</style>'
                            '<img src="https://cdn.example/a.png"><img src="/files/none.png">')
    result = space.cli("check")
    assert result["unknown_colors"] == ["#123456"]
    assert result["unloaded_fonts"] == ["Foo"]
    assert result["external_urls"] == ["https://cdn.example/a.png"]
    assert result["broken_paths"] == ["/files/none.png"]
    assert result["issue_count"] == 4 and "Fix" in result["next"]


def test_check_passes_when_token_and_font_face_present(space):
    folder = screen(space, "a.html", '<style>.a{color:#ABCDEF;background:#fff;font-family:"Foo",system-ui}</style>'
                                     '<img src="/files/fonts/a.png"><img src="v/b.png">')
    (folder / "tokens.css").write_text(':root{--a:#abcdef;--b:#FFFFFF}@font-face{font-family:"Foo";src:url(/files/Foo.ttf)}')
    (folder / "Foo.ttf").write_text("x")
    (folder / "fonts").mkdir()
    (folder / "fonts/a.png").write_text("x")
    (folder / "v").mkdir()
    (folder / "v/b.png").write_text("x")
    result = space.cli("check")
    assert result["issue_count"] == 0, result


def test_check_ignores_non_colors_and_namespaces(space):
    screen(space, "a.html", '<a href="#abc">x</a><style>#add{margin:0}#fade .x,#bad{top:0}</style>&#123;'
                            '<svg xmlns="http://www.w3.org/2000/svg"></svg><a href="https://example.com">l</a>'
                            '<img src="data:image/png;base64,AA"><img src="${path}">')
    result = space.cli("check")
    assert result["issue_count"] == 0, result


def test_check_single_screen_and_no_session(space):
    assert space.cli("check")["code"] == "no_session"
    screen(space, "a.html", "<style>.a{color:#111111}</style>")
    screen(space, "b.html", "<style>.a{color:#222222}</style>")
    assert space.cli("check", "--screen", "b.html")["unknown_colors"] == ["#222222"]
    assert space.cli("check", "--screen", "none.html")["code"] == "screen_not_found"


def test_check_notes_missing_tokens_file(space):
    screen(space, "a.html", "<p>x</p>")
    result = space.cli("check")
    assert result["has_tokens_css"] is False
