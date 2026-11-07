"""임시 테스트 (커밋 금지): 리뷰 지적 재현"""
import json, os, socket, sys, threading, subprocess, urllib.parse
from pathlib import Path
import pytest
from test_server import Workspace, request, session_of, auth, write_screen, CLI, REPO

@pytest.fixture()
def space(tmp_path):
    w = Workspace(tmp_path)
    yield w
    w.cli("stop", "--all")

def test_foreign_cookies_do_not_block(space):
    port, key = session_of(space.start())
    name = f"ui_design_key_{port}"
    for cookie in (f'prefs={{"lng":"ko"}}; {name}={key}', f"flag; {name}={key}", f"a=b c; {name}={key}; z"):
        assert request(port, "GET", "/", {"Cookie": cookie})[0] == 200, cookie
    assert request(port, "GET", "/", {"Cookie": f"{name}=wrong"})[0] == 403

def test_non_ascii_key_is_rejected_not_crashed(space):
    port, _ = session_of(space.start())
    assert request(port, "GET", "/?key=%ED%95%9C")[0] == 403

def test_relative_image_in_screen_is_served(space):
    data = space.start()
    port, key = session_of(data)
    write_screen(data, "logo.png", b"PNG")
    write_screen(data, "v/b.png", b"PNG2")
    assert request(port, "GET", "/screens/logo.png", auth(key))[2] == b"PNG"
    assert request(port, "GET", "/screens/v/b.png", auth(key))[2] == b"PNG2"
    assert request(port, "GET", "/screens/../session.json", auth(key))[0] in (403, 404)

def test_tokens_skip_own_session_files(space):
    (space.root / "lib").mkdir()
    (space.root / "lib/app_colors.dart").write_text("a")
    data = space.start()
    write_screen(data, "tokens.css", "x")
    write_screen(data, "fonts/a.ttf", b"x")
    found = {c["path"] for c in space.cli("tokens")["candidates"]}
    assert found == {"lib/app_colors.dart"}
    space.cli("tokens", "--save")
    write_screen(data, "tokens.css", "changed")
    assert space.cli("start", "--title", "login")["project_profile"]["changed_files"] == []

def test_tokens_report_truncation(space):
    (space.root / "lib").mkdir()
    for index in range(25):
        (space.root / f"lib/c{index}_colors.dart").write_text("a")
    result = space.cli("tokens")
    assert result["is_truncated"] is True and len(result["candidates"]) == 20

def test_title_selects_session(space):
    one = space.start("one")
    two = space.start("two")
    write_screen(one, "a.html", "<style>.a{color:#111111}</style>")
    write_screen(two, "b.html", "<p>x</p>")
    assert space.cli("check", "--title", "one")["unknown_colors"] == ["#111111"]
    assert space.cli("status", "--title", "one")["url"] == one["url"]
    assert space.cli("status")["url"] == two["url"]
    space.cli("decide", "--title", "one", "--choice", "a", "--reason", "r")
    assert (Path(one["run_dir"]) / "decision.json").is_file()
    assert not (Path(two["run_dir"]) / "decision.json").exists()
    assert space.cli("check", "--title", "none")["code"] == "no_session"

def test_stop_only_current_unless_all(space):
    one = space.start("one")
    two = space.start("two")
    result = space.cli("stop")
    assert result["stopped_sessions"] == 1
    assert space.cli("status", "--title", "one")["running"] is True
    assert space.cli("status", "--title", "two")["running"] is False
    assert space.cli("stop", "--all")["stopped_sessions"] == 1
    assert space.cli("status", "--title", "one")["running"] is False

def test_same_title_resumes_on_a_later_day(space):
    first = space.start("login")
    write_screen(first, "a.html", "x")
    space.cli("stop")
    old = Path(first["run_dir"])
    moved = old.with_name("19990101_001_login")
    old.rename(moved)
    pointer = next((space.home / ".projectops/ui-design/current").glob("*.json"))
    text = pointer.read_text().replace(str(old), str(moved))
    pointer.write_text(text)
    session = json.loads((moved / "session.json").read_text())
    session["run_dir"] = str(moved)
    (moved / "session.json").write_text(json.dumps(session))
    again = space.start("login")
    assert again["run_dir"] == str(moved) and (Path(again["screens_dir"]) / "a.html").is_file()
    assert session_of(again)[1] == session_of(first)[1]

def test_non_http_or_odd_service_on_port(space):
    first = space.start()
    port, _ = session_of(first)
    space.cli("stop")
    blocker = socket.socket()
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    blocker.bind(("127.0.0.1", port))
    blocker.listen(5)
    stop_event = threading.Event()
    def serve():
        blocker.settimeout(0.2)
        while not stop_event.is_set():
            try:
                conn, _ = blocker.accept()
                conn.sendall(b"SSH-2.0-OpenSSH_9\r\n")
                conn.close()
            except OSError:
                pass
    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        assert space.cli("status")["running"] is False
        second = space.start()
        assert second["ok"] and second["port_changed"] is True
    finally:
        stop_event.set()
        thread.join()
        blocker.close()

def test_broken_config_is_not_overwritten(space):
    config = space.home / ".projectops/config/config.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"github": {"global_pat": "keep"},')
    result = space.cli("config", "set", "--key", "themes", "--value", "light")
    assert result["ok"] is False and result["code"] == "config_unreadable"
    assert "keep" in config.read_text()

def test_config_with_bom_is_read(space):
    config = space.home / ".projectops/config/config.json"
    config.parent.mkdir(parents=True)
    config.write_bytes(b"\xef\xbb\xbf" + json.dumps({"ui-design": {"themes": ["dark"]}}).encode())
    assert space.cli("config", "show")["resolved"]["themes"] == ["dark"]

def test_old_skill_preferences_still_apply():
    sys.path.insert(0, str(REPO / "scripts"))
    from common.preferences import resolve
    result = resolve("pro-ui-design", data={"skills": {"pro-design-brief": {"language": "ko"}}})
    assert result["values"].get("language") == "ko"

def test_decision_captures_exact_and_current_flag(space):
    data = space.start("sheet")
    write_screen(data, "layout.html", "x")
    captures = Path(data["run_dir"]) / "captures"
    captures.mkdir()
    for name in ("layout.png", "layout__b.png", "layout-v2__a.png"):
        (captures / name).write_text("x")
    saved = space.cli("decide", "--choice", "b", "--reason", "r", "--screen", "layout.html")["decision"]
    assert sorted(Path(p).name for p in saved["captures"]) == ["layout.png", "layout__b.png"]
    assert space.cli("decision")["is_current_session"] is True
    space.start("other")
    assert space.cli("decision")["is_current_session"] is False

def test_get_output_path_accepts_root(space):
    assert space.cli("get-output-path", "--title", "x")["ok"]

def test_start_returns_option_defaults(space):
    started = space.start()
    assert started["defaults"] == {"default_fidelity": "html", "motion_format": "gif"}

def test_title_cannot_break_shell_script(space):
    data = space.start("a<!--<script>b")
    port, key = session_of(data)
    body = request(port, "GET", "/", auth(key))[2].decode()
    settings_line = next(line for line in body.splitlines() if "UI_DESIGN_SETTINGS" in line)
    assert "<!--" not in settings_line and "<script>b" not in settings_line
