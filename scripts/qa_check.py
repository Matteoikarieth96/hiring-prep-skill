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

Chrome runs headless with its own temporary profile and with
--allow-file-access-from-files so the wrapper can measure the local page.
Find Chrome via --chrome, $CHROME_PATH, the macOS default location, or
google-chrome / chromium on PATH. Exit code 1 if a check fails.
Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

MAC_CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
WIDTHS = (375, 320, 1280)

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
    document.getElementById("result").textContent = JSON.stringify(out);
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


def chrome(exe: str, args: List[str]) -> Optional[subprocess.CompletedProcess]:
    # Headless Chrome runs with its own temporary profile, so the user's
    # browser profile, cookies and extensions are never touched.
    base = [
        exe, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
        "--no-default-browser-check", "--disable-extensions",
        "--allow-file-access-from-files", "--virtual-time-budget=8000",
    ]
    try:
        return subprocess.run(base + args, capture_output=True, timeout=90, check=False)
    except subprocess.TimeoutExpired:
        print("WARN Chrome timed out", file=sys.stderr)
        return None


def write_wrapper(dirpath: Path, name: str, frames: List[tuple], probe: bool) -> Path:
    tags = []
    for width, height, url, hash_ in frames:
        src = html.escape(url + hash_, quote=True)
        tags.append(
            f'<iframe src="{src}" width="{int(width)}" height="{int(height)}" data-hash="{html.escape(hash_, quote=True)}"'
            f' style="width:{int(width)}px;height:{int(height)}px;border:0;flex:none;background:#fff"></iframe>'
        )
    body = "".join(tags)
    script = f"<pre id=\"result\"></pre><script>{PROBE_JS}</script>" if probe else ""
    page = (
        "<!doctype html><html><head><meta charset=\"utf-8\"></head>"
        "<body style=\"margin:0;padding:24px;display:flex;gap:24px;align-items:flex-start;background:#d9d6cc\">"
        f"{body}{script}</body></html>"
    )
    path = dirpath / name
    path.write_text(page, encoding="utf-8")
    return path


def run_checks(exe: str, page: Path, tmp: Path) -> bool:
    url = page.resolve().as_uri()
    frames = [(w, 900, url, "") for w in WIDTHS] + [(375, 900, url, "#demo")]
    wrapper = write_wrapper(tmp, "probe.html", frames, probe=True)
    res = chrome(exe, ["--window-size=2600,1200", "--dump-dom", wrapper.as_uri()])
    out = res.stdout.decode("utf-8", "replace") if res else ""
    m = re.search(r'<pre id="result">(.*?)</pre>', out, re.S)
    if not m or not m.group(1).strip():
        print("FAIL could not read the probe result from Chrome")
        return False
    data = json.loads(html.unescape(m.group(1)))
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


def take_shots(exe: str, page: Path, tmp: Path, shots: Path) -> None:
    shots.mkdir(parents=True, exist_ok=True)
    url = page.resolve().as_uri()
    light, dark = "--blink-settings=preferredColorScheme=1", "--blink-settings=preferredColorScheme=0"
    jobs = [
        ("desktop-light.png", "1400,1000", url, light),
        ("desktop-dark.png", "1400,1000", url, dark),
        ("overview.png", "1400,1500", url + "#focus-overview", light),
        ("quiz-demo.png", "1400,1500", url + "#demo", light),
    ]
    for name, size, target, scheme in jobs:
        chrome(exe, [scheme, f"--window-size={size}", f"--screenshot={shots / name}", target])
        print(f"shot {shots / name}")
    frames = [(375, 760, url, ""), (375, 760, url, "#focus-overview"), (375, 760, url, "#demo")]
    wrapper = write_wrapper(tmp, "mobile.html", frames, probe=False)
    chrome(exe, [light, "--window-size=1221,808", f"--screenshot={shots / 'mobile.png'}", wrapper.as_uri()])
    print(f"shot {shots / 'mobile.png'}")


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
        tmp = Path(t)
        ok = run_checks(exe, args.page, tmp)
        if args.shots:
            take_shots(exe, args.page, tmp, args.shots)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
