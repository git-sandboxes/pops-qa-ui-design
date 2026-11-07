"""임시 테스트 (커밋 금지): 실제 서버를 띄워 세션, 인증, 경로, 이벤트 검사"""
import http.client
import json
import os
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

import pytest

REPO = Path(__import__("os").environ["REPO_ROOT"])
CLI = REPO / "skills/pro-ui-design/scripts/ui_design_cli.py"


class Workspace:
    def __init__(self, tmp_path, git=True):
        self.root = tmp_path / ("repo" if git else "plain")
        self.root.mkdir(exist_ok=True)
        self.home = tmp_path / "home"
        self.home.mkdir(exist_ok=True)
        if git:
            subprocess.run(["git", "init", "-q", str(self.root)], check=True)
            (self.root / "pubspec.yaml").write_text("name: x\n")
        self.started = []

    def cli(self, *args):
        env = {**os.environ, "HOME": str(self.home), "PROJECTOPS_HOME": str(self.home / ".projectops"),
               "PYTHONIOENCODING": "utf-8"}
        out = subprocess.run([sys.executable, str(CLI), *args, "--root", str(self.root)],
                             capture_output=True, text=True, encoding="utf-8", env=env, timeout=30)
        return json.loads(out.stdout)

    def start(self, title="login"):
        data = self.cli("start", "--title", title)
        assert data["ok"], data
        self.started.append(title)
        return data


@pytest.fixture()
def space(tmp_path):
    workspace = Workspace(tmp_path)
    yield workspace
    workspace.cli("stop", "--all")


def request(port, method, path, headers=None, body=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request(method, path, body=body, headers=headers or {})
    response = conn.getresponse()
    data = response.read()
    return response.status, dict(response.getheaders()), data


def session_of(data):
    parsed = urllib.parse.urlparse(data["url"])
    return parsed.port, urllib.parse.parse_qs(parsed.query)["key"][0]


def auth(key):
    return {"X-UI-Design-Key": key, "Host": "localhost"}


def write_screen(data, name, body):
    path = Path(data["screens_dir"]) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body if isinstance(body, bytes) else body.encode("utf-8"))
    return path


def test_rejects_without_key(space):
    port, _ = session_of(space.start())
    assert request(port, "GET", "/")[0] == 403
    assert request(port, "GET", "/api/state")[0] == 403
    assert request(port, "GET", "/?key=wrong")[0] == 403


def test_key_sets_cookie_then_serves_shell(space):
    port, key = session_of(space.start())
    status, headers, _ = request(port, "GET", f"/?key={key}")
    assert status == 302 and "HttpOnly" in headers["Set-Cookie"] and "SameSite=Lax" in headers["Set-Cookie"]
    cookie = headers["Set-Cookie"].split(";")[0]
    status, _, body = request(port, "GET", "/", {"Cookie": cookie})
    assert status == 200 and b"ui-design-shell" in body


def test_wrong_host_rejected(space):
    port, key = session_of(space.start())
    assert request(port, "GET", "/api/state", {"X-UI-Design-Key": key, "Host": "evil.example"})[0] == 403


def test_path_escape_blocked(space):
    data = space.start()
    port, key = session_of(data)
    outside = Path(data["run_dir"]).parent / "secret.txt"
    outside.write_text("secret")
    os.symlink(outside, Path(data["screens_dir"]) / "link.txt")
    for path in ["/files/../session.json", "/files/%2e%2e/session.json", "/files/..%2fsession.json",
                 "/files/link.txt", "/screens/../session.json", "/assets/../../SKILL.md"]:
        status, _, body = request(port, "GET", path, auth(key))
        assert status in (400, 403, 404), path
        assert b"secret" not in body and b"server_token" not in body


def test_korean_space_and_subfolder_files_served(space):
    data = space.start()
    port, key = session_of(data)
    write_screen(data, "v3/한글 파일.png", b"PNGDATA")
    path = "/files/" + urllib.parse.quote("v3/한글 파일.png")
    status, headers, body = request(port, "GET", path, auth(key))
    assert status == 200 and body == b"PNGDATA" and headers["Content-Type"] == "image/png"


def test_media_and_font_mime(space):
    data = space.start()
    port, key = session_of(data)
    for name, mime in [("a.gif", "image/gif"), ("a.webm", "video/webm"), ("a.mp4", "video/mp4"), ("a.woff2", "font/woff2")]:
        write_screen(data, name, b"x")
        assert request(port, "GET", f"/files/{name}", auth(key))[1]["Content-Type"] == mime


def test_event_needs_same_origin_and_is_recorded(space):
    data = space.start()
    port, key = session_of(data)
    body = json.dumps({"type": "click", "choice": "b", "text": "B", "screen": "a.html"})
    bad = {**auth(key), "Origin": "http://evil.example", "Content-Type": "application/json"}
    assert request(port, "POST", "/api/events", bad, body)[0] == 403
    assert request(port, "POST", "/api/events", {"Host": "localhost", "Origin": f"http://localhost:{port}"}, body)[0] == 403
    good = {**auth(key), "Origin": f"http://localhost:{port}", "Content-Type": "application/json"}
    assert request(port, "POST", "/api/events", good, body)[0] == 204
    choices = space.cli("choices")
    assert choices["ok"] and choices["last_choice"]["choice"] == "b"
    assert choices["by_screen"]["a.html"][0]["choice"] == "b"


def test_event_body_limit_and_bad_json(space):
    port, key = session_of(space.start())
    good = {**auth(key), "Origin": f"http://localhost:{port}"}
    assert request(port, "POST", "/api/events", good, "{bad")[0] == 400
    assert request(port, "POST", "/api/events", good, "x" * 70000)[0] == 413


def test_fragment_wrapped_and_full_document_kept(space):
    data = space.start()
    port, key = session_of(data)
    write_screen(data, "frag.html", "<h2>fragment</h2>")
    write_screen(data, "full.html", "<!DOCTYPE html><html><head><title>t</title></head><body>full</body></html>")
    frag = request(port, "GET", "/screens/frag.html", auth(key))[2].decode()
    full = request(port, "GET", "/screens/full.html", auth(key))[2].decode()
    assert "<h2>fragment</h2>" in frag and "/assets/viewer.js" in frag and "/assets/viewer.css" in frag
    assert "<title>t</title>" in full and "/assets/viewer.js" in full and "ui-design-frame" not in full


def test_tokens_css_linked_when_present(space):
    data = space.start()
    port, key = session_of(data)
    write_screen(data, "frag.html", "<p>x</p>")
    assert b"/files/tokens.css" not in request(port, "GET", "/screens/frag.html", auth(key))[2]
    write_screen(data, "tokens.css", ":root{--ui-bg:#fff}")
    assert b"/files/tokens.css" in request(port, "GET", "/screens/frag.html", auth(key))[2]


def test_state_lists_screens_newest_first_and_hides_support_files(space):
    data = space.start()
    port, key = session_of(data)
    first = write_screen(data, "old.html", "a")
    os.utime(first, (1000, 1000))
    write_screen(data, "new.html", "b")
    write_screen(data, "_draft.html", "c")
    write_screen(data, "tokens.css", "d")
    write_screen(data, "v2/nested.html", "e")
    state = json.loads(request(port, "GET", "/api/state", auth(key))[2])
    assert [s["name"] for s in state["screens"]] == ["new.html", "old.html"]
    assert state["current"] == "new.html"
    before = state["revision"]
    write_screen(data, "newer.html", "f")
    assert json.loads(request(port, "GET", "/api/state", auth(key))[2])["revision"] != before


def test_empty_folder_and_invalid_utf8_do_not_crash(space):
    data = space.start()
    port, key = session_of(data)
    assert json.loads(request(port, "GET", "/api/state", auth(key))[2])["current"] is None
    write_screen(data, "bad.html", b"\xff\xfe<p>x</p>")
    assert request(port, "GET", "/screens/bad.html", auth(key))[0] == 200
    assert request(port, "GET", "/screens/missing.html", auth(key))[0] == 404


def test_status_recovers_without_memory(space):
    data = space.start()
    status = space.cli("status")
    assert status["ok"] and status["running"] is True
    assert status["url"] == data["url"] and status["screens_dir"] == data["screens_dir"]


def test_status_without_session(space):
    status = space.cli("status")
    assert status["ok"] and status["running"] is False and status["url"] is None


def test_same_title_reuses_running_server(space):
    first = space.start()
    second = space.start()
    assert second["url"] == first["url"] and second["reused"] is True


def test_stop_then_restart_same_port_and_key(space):
    first = space.start()
    port, _ = session_of(first)
    assert space.cli("stop")["ok"]
    with pytest.raises(OSError):
        request(port, "GET", "/")
    second = space.start()
    assert second["url"] == first["url"] and second["port_changed"] is False


def test_port_busy_moves_and_reports(space):
    import socket
    first = space.start()
    port, _ = session_of(first)
    space.cli("stop")
    blocker = socket.socket()
    blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    blocker.bind(("127.0.0.1", port))
    blocker.listen(1)
    try:
        second = space.start()
        assert second["port_changed"] is True and session_of(second)[0] != port
    finally:
        blocker.close()


def test_two_sessions_isolated(space, tmp_path):
    first = space.start("one")
    second = space.start("two")
    assert session_of(first)[0] != session_of(second)[0]
    write_screen(first, "a.html", "x")
    port, key = session_of(second)
    assert json.loads(request(port, "GET", "/api/state", auth(key))[2])["screens"] == []
    assert session_of(first)[1] != key
    assert space.cli("status")["title"] == "two"
    request(session_of(first)[0], "POST", "/api/stop", auth(session_of(first)[1]))


def test_stop_does_not_kill_foreign_pid(space):
    data = space.start()
    sleeper = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(60)"])
    try:
        session_file = Path(data["run_dir"]) / "session.json"
        session = json.loads(session_file.read_text())
        real_port = session["port"]
        request(real_port, "POST", "/api/stop", auth(session["key"]))
        time.sleep(0.3)
        session["pid"] = sleeper.pid
        session_file.write_text(json.dumps(session))
        assert space.cli("stop")["ok"]
        assert sleeper.poll() is None
    finally:
        sleeper.kill()


def test_idle_exit(tmp_path):
    workspace = Workspace(tmp_path)
    workspace.cli("config", "set", "--key", "idle_timeout_minutes", "--value", "1")
    data = workspace.cli("start", "--title", "idle", "--idle-seconds", "1")
    port, key = session_of(data)
    deadline = time.time() + 8
    stopped = False
    while time.time() < deadline:
        try:
            request(port, "GET", "/api/state", auth(key))
        except OSError:
            stopped = True
            break
        time.sleep(0.3)
    assert stopped, "polling must not keep the server alive"
    assert workspace.cli("status")["running"] is False


def test_works_without_git_repo(tmp_path):
    workspace = Workspace(tmp_path, git=False)
    data = workspace.start()
    try:
        assert str(workspace.home) in data["run_dir"]
        assert not (workspace.root / "docs").exists()
        assert workspace.cli("status")["running"] is True
    finally:
        workspace.cli("stop", "--all")


def test_git_repo_session_is_ignored_by_git(space):
    data = space.start()
    write_screen(data, "a.html", "x")
    out = subprocess.run(["git", "-C", str(space.root), "status", "--short", "--untracked-files=all"],
                         capture_output=True, text=True, encoding="utf-8").stdout
    assert "a.html" not in out and "session.json" not in out


def test_viewer_settings_follow_config(tmp_path):
    workspace = Workspace(tmp_path)
    workspace.cli("config", "set", "--key", "devices", "--value", "phone")
    data = workspace.start()
    try:
        port, key = session_of(data)
        body = request(port, "GET", "/", auth(key))[2].decode()
        assert '"devices": ["phone"]' in body or '"devices":["phone"]' in body
    finally:
        workspace.cli("stop", "--all")


def test_stop_stops_every_session_of_the_project(space):
    first = space.start("one")
    second = space.start("two")
    result = space.cli("stop", "--all")
    assert result["stopped"] is True and result["stopped_sessions"] == 2
    for data in (first, second):
        with pytest.raises(OSError):
            request(session_of(data)[0], "GET", "/")
