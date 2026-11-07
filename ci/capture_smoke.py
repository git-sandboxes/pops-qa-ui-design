"""캡처 스모크: 실제 브라우저로 PNG, GIF 생성"""
import json, os, subprocess, sys, tempfile
from pathlib import Path
from PIL import Image
repo = Path(os.environ["REPO_ROOT"])
cli_path = repo / "skills/pro-ui-design/scripts/ui_design_cli.py"
root = Path(tempfile.mkdtemp(prefix="smoke 한글 "))
subprocess.run(["git", "init", "-q", str(root)], check=True)
def cli(*args):
    out = subprocess.run([sys.executable, str(cli_path), *args, "--root", str(root)], capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    print(args[0], out.stdout[:400], out.stderr[-400:])
    return json.loads(out.stdout)
started = cli("start", "--title", "스모크 smoke")
assert started["ok"]
screens = Path(started["screens_dir"])
for name in ("motion.html", "linked.html"):
    (screens / name).write_text((repo / "ci/examples" / name).read_text(encoding="utf-8"), encoding="utf-8")
(screens / "한글 시안.html").write_text('<h2>한글</h2><div class="ui-option"><h3>가</h3><button data-choice="가">x</button></div>', encoding="utf-8")
png = cli("capture", "--screen", "motion.html", "--all-options")
assert png["ok"] and len(png["files"]) == 3
korean = cli("capture", "--screen", "한글 시안.html", "--all-options")
assert korean["ok"], korean
steps = root / "s.json"
steps.write_text(json.dumps([{"action": "wait", "ms": 200}, {"action": "click", "selector": "#send", "ms": 400}]))
gif = cli("capture", "--gif", "--screen", "linked.html", "--steps", str(steps))
assert gif["ok"]
with Image.open(gif["files"][0]["path"]) as image:
    assert image.n_frames >= 2
stopped = cli("stop", "--all")
assert stopped["stopped_sessions"] == 1
masked_source = root / "a.png"
Image.new("RGB", (20, 20), (255, 255, 255)).save(masked_source)
launch = repo / "skills/pro-launch/scripts/launch_cli.py"
out = subprocess.run([sys.executable, str(launch), "mask", str(masked_source), "--rect", "1,1,5,5"], capture_output=True, text=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"})
print(out.stdout[:300], out.stderr[-300:])
assert json.loads(out.stdout)["ok"]
print("SMOKE OK")
