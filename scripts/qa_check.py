#!/usr/bin/env python3
"""Check a built guide in headless Chrome and optionally take screenshots.

Usage:
    python3 scripts/qa_check.py out/<slug>.html [--shots out/qa] [--chrome PATH]

Checks, at 375 px, 320 px and 1280 px wide:
  * no horizontal page scroll (wide tables scroll inside their own box),
  * the quiz rendered every question from the embedded data,
  * the #demo state shows one right and one wrong answer.
Headless Chrome will not render narrower than about 500 px, so the page is
loaded in iframes of the target width inside a throwaway wrapper page.

Isolation:
  * a copy of the page and the wrapper are served from a temporary folder by
    a server bound to 127.0.0.1 only, so wrapper and page share an origin and
    no --allow-file-access-from-files flag is needed;
  * every Chrome run gets its own fresh --user-data-dir in that temporary
    folder, deleted afterwards. With an explicit profile, headless Chrome on
    macOS writes its output but does not exit, so the run waits for the output
    (the screenshot file, or the end of the dumped DOM) and then stops the
    Chrome process group.
Find Chrome via --chrome, $CHROME_PATH, the macOS default location, or
google-chrome / chromium on PATH. Exit code 1 if a check fails.
Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import argparse
import functools
import html
import http.server
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from guide_lib import make_private_dir, write_private  # noqa: E402

MAC_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
WIDTHS = (375, 320, 1280)
RUN_TIMEOUT = 90
BASE_FLAGS = [
    "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--no-default-browser-check",
    "--disable-extensions", "--disable-background-networking", "--disable-sync", "--disable-component-update",
    "--disable-default-apps", "--use-mock-keychain", "--password-store=basic", "--virtual-time-budget=8000",
]

PROBE_JS = r"""
(function () {
  var frames = Array.prototype.slice.call(document.querySelectorAll("iframe"));
  var left = frames.length, out = {};
  function measure(f) {
    var r = { width: +f.getAttribute("width"), hash: f.getAttribute("data-hash") };
    try {
      var d = f.contentDocument, w = f.contentWindow;
      r.scrollWidth = d.documentElement.scrollWidth;
      r.clientWidth = d.documentElement.clientWidth;
      r.mcq = d.querySelectorAll(".mcq").length;
      r.answered = d.querySelectorAll(".mcq.done").length;
      r.right = d.querySelectorAll(".verdict.ok:not([hidden])").length;
      r.wrong = d.querySelectorAll(".verdict.ko:not([hidden])").length;
      var wide = [];
      Array.prototype.forEach.call(d.querySelectorAll("body *"), function (e) {
        if (e.closest(".tablewrap")) return;
        var b = e.getBoundingClientRect();
        if (b.width > 0 && b.right > w.innerWidth + 1) wide.push(e.tagName.toLowerCase() + (e.className ? "." + String(e.className).split(" ")[0] : ""));
      });
      r.wide = wide.slice(0, 6);
    } catch (e) { r.error = String(e); }
    return r;
  }
  function done() {
    out.frames = frames.map(measure);
    var body = JSON.stringify(out);
    document.getElementById("result").textContent = body;
    fetch("/result", { method: "POST", body: body });
  }
  frames.forEach(function (f) {
    f.addEventListener("load", function () { if (--left === 0) setTimeout(done, 800); });
  });
})();
"""


def find_chrome(explicit: Optional[str]) -> str:
    for cand in (explicit, os.environ.get("CHROME_PATH"), MAC_CHROME):
        if cand and Path(cand).is_file():
            return cand
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome"):
        found = shutil.which(name)
        if found:
            return found
    raise SystemExit("ERROR: Chrome not found. Pass --chrome or set CHROME_PATH.")


def expected_questions(page: Path) -> int:
    text = page.read_text(encoding="utf-8")
    m = re.search(r'<script type="application/json" id="quiz-data">(.*?)</script>', text, re.S)
    if not m:
        return 0
    return len(json.loads(m.group(1)).get("mcq", []))


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args: object) -> None:
        pass

    def do_POST(self) -> None:  # the probe page reports its measurements here
        if self.path != "/result":
            self.send_error(404)
            return
        length = min(int(self.headers.get("Content-Length") or 0), 1_000_000)
        self.server.result = self.rfile.read(length)  # type: ignore[attr-defined]
        self.server.result_event.set()  # type: ignore[attr-defined]
        self.send_response(204)
        self.end_headers()


def serve(directory: Path) -> http.server.ThreadingHTTPServer:
    """Serve one folder on 127.0.0.1 (random port) in a background thread."""
    handler = functools.partial(_QuietHandler, directory=str(directory))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    srv.result = b""  # type: ignore[attr-defined]
    srv.result_event = threading.Event()  # type: ignore[attr-defined]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def chrome_command(exe: str, profile: Path, args: List[str]) -> List[str]:
    return [exe] + BASE_FLAGS + [f"--user-data-dir={profile}"] + args


def _stop(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    try:
        if hasattr(os, "killpg"):
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            proc.kill()
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass


def run_chrome(
    exe: str, work: Path, args: List[str], screenshot: Optional[Path] = None, event: Optional[threading.Event] = None,
) -> Tuple[bool, str]:
    """Run Chrome with a fresh profile; return (ok, stdout). Waits for the screenshot
    file, the event (probe result posted) or the end of the dumped DOM, then stops
    Chrome and deletes the profile."""
    profile = Path(tempfile.mkdtemp(prefix="profile-", dir=str(work)))
    out_buf: List[bytes] = []
    proc = subprocess.Popen(
        chrome_command(exe, profile, args), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )

    def pump() -> None:
        assert proc.stdout is not None
        for chunk in iter(lambda: proc.stdout.read(4096), b""):
            out_buf.append(chunk)

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    deadline = time.monotonic() + RUN_TIMEOUT
    ok = False
    last_size = -1
    try:
        while time.monotonic() < deadline:
            if event is not None and event.is_set():
                ok = True
                break
            if screenshot is not None and screenshot.exists():
                size = screenshot.stat().st_size
                if size > 0 and size == last_size:
                    ok = True
                    break
                last_size = size
            if screenshot is None and event is None and b"</html>" in b"".join(out_buf).lower():
                ok = True
                break
            if proc.poll() is not None:
                reader.join(timeout=2)
                ok = screenshot.exists() if screenshot is not None else b"</html>" in b"".join(out_buf).lower()
                break
            time.sleep(0.25)
    finally:
        _stop(proc)
        reader.join(timeout=2)
        shutil.rmtree(profile, ignore_errors=True)
    if not ok:
        print("WARN Chrome did not produce output in time", file=sys.stderr)
    return ok, b"".join(out_buf).decode("utf-8", "replace")


def write_wrapper(dirpath: Path, name: str, frames: List[tuple], probe: bool) -> None:
    tags = []
    for width, height, src, hash_ in frames:
        tags.append(
            f'<iframe src="{html.escape(src + hash_, quote=True)}" width="{int(width)}" height="{int(height)}"'
            f' data-hash="{html.escape(hash_, quote=True)}"'
            f' style="width:{int(width)}px;height:{int(height)}px;border:0;flex:none;background:#fff"></iframe>'
        )
    script = f"<pre id=\"result\"></pre><script>{PROBE_JS}</script>" if probe else ""
    page = (
        "<!doctype html><html><head><meta charset=\"utf-8\"></head>"
        "<body style=\"margin:0;padding:24px;display:flex;gap:24px;align-items:flex-start;background:#d9d6cc\">"
        f"{''.join(tags)}{script}</body></html>"
    )
    write_private(dirpath / name, page)


def run_checks(exe: str, page: Path, work: Path, srv: http.server.ThreadingHTTPServer, base_url: str) -> bool:
    frames = [(w, 900, "page.html", "") for w in WIDTHS] + [(375, 900, "page.html", "#demo")]
    write_wrapper(work / "site", "probe.html", frames, probe=True)
    run_chrome(exe, work, ["--window-size=2600,1200", base_url + "probe.html"], event=srv.result_event)  # type: ignore[attr-defined]
    raw = srv.result  # type: ignore[attr-defined]
    if not raw:
        print("FAIL could not read the probe result from Chrome")
        return False
    data = json.loads(raw.decode("utf-8", "replace"))
    want = expected_questions(page)
    ok = True
    for fr in data["frames"]:
        label = f"{fr['width']}px{' ' + fr['hash'] if fr['hash'] else ''}"
        if fr.get("error"):
            print(f"FAIL {label}: {fr['error']}")
            ok = False
            continue
        problems = []
        if fr["scrollWidth"] > fr["clientWidth"]:
            problems.append(f"horizontal scroll ({fr['scrollWidth']} > {fr['clientWidth']}): {', '.join(fr['wide']) or 'unknown element'}")
        if fr["mcq"] != want:
            problems.append(f"quiz rendered {fr['mcq']} of {want} questions")
        if fr["hash"] == "#demo" and want >= 2 and (fr["answered"], fr["right"], fr["wrong"]) != (2, 1, 1):
            problems.append(f"demo state wrong (answered {fr['answered']}, right {fr['right']}, wrong {fr['wrong']})")
        if problems:
            ok = False
            print(f"FAIL {label}: " + "; ".join(problems))
        else:
            print(f"OK   {label}: no horizontal scroll, {fr['mcq']}/{want} questions rendered")
    return ok


def take_shots(exe: str, work: Path, base_url: str, shots: Path) -> None:
    make_private_dir(shots)
    raw = work / "shots"
    make_private_dir(raw)
    light, dark = "--blink-settings=preferredColorScheme=1", "--blink-settings=preferredColorScheme=0"
    write_wrapper(
        work / "site", "mobile.html",
        [(375, 760, "page.html", ""), (375, 760, "page.html", "#focus-overview"), (375, 760, "page.html", "#demo")],
        probe=False,
    )
    jobs = [
        ("desktop-light.png", "1400,1000", "page.html", light),
        ("desktop-dark.png", "1400,1000", "page.html", dark),
        ("overview.png", "1400,1500", "page.html#focus-overview", light),
        ("quiz-demo.png", "1400,1500", "page.html#demo", light),
        ("mobile.png", "1221,808", "mobile.html", light),
    ]
    for name, size, target, scheme in jobs:
        tmp_png = raw / name
        ok, _ = run_chrome(exe, work, [scheme, f"--window-size={size}", f"--screenshot={tmp_png}", base_url + target], screenshot=tmp_png)
        if ok:
            write_private(shots / name, tmp_png.read_bytes())  # never follows a symlink in the shots folder
            print(f"shot {shots / name}")
        else:
            print(f"FAIL screenshot {name}")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Headless Chrome QA for a built guide")
    ap.add_argument("page", type=Path)
    ap.add_argument("--shots", type=Path, help="folder for screenshots (desktop light/dark, overview, quiz demo, mobile)")
    ap.add_argument("--chrome", help="path to the Chrome or Chromium executable")
    args = ap.parse_args(argv)
    if not args.page.is_file() or args.page.suffix != ".html":
        print(f"ERROR: {args.page} is not an .html file", file=sys.stderr)
        return 2
    exe = find_chrome(args.chrome)
    with tempfile.TemporaryDirectory(prefix="hiring-prep-qa-") as t:
        work = Path(t)
        site = make_private_dir(work / "site")
        write_private(site / "page.html", args.page.read_bytes())
        srv = serve(site)
        base_url = f"http://127.0.0.1:{srv.server_address[1]}/"
        try:
            ok = run_checks(exe, args.page, work, srv, base_url)
            if args.shots:
                take_shots(exe, work, base_url, args.shots)
        finally:
            srv.shutdown()
            srv.server_close()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
