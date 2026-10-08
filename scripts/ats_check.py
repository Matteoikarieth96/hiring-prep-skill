#!/usr/bin/env python3
"""Check whether a role is live on the public Ashby, Lever or Greenhouse job boards.

Usage:
    python3 scripts/ats_check.py <org-slug> [--title "developer relations"] [--json]

<org-slug> is the board name in the company's job URLs, for example
jobs.ashbyhq.com/<org>, jobs.lever.co/<org> or boards.greenhouse.io/<org>.
Only the slug and nothing personal is sent, to these three fixed hosts:
    https://api.ashbyhq.com/posting-api/job-board/<org>
    https://api.lever.co/v0/postings/<org>?mode=json
    https://boards-api.greenhouse.io/v1/boards/<org>/jobs
A board that answers 404 is reported as "not found". Other job systems
(Workable, SmartRecruiters, Teamtailor, a custom careers page) are not covered:
check those by hand and say so.
Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import ssl
import subprocess
import sys
import unicodedata
import urllib.error
import urllib.request
from typing import Callable, Dict, List, Optional, Tuple

ORG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
MAX_BYTES = 8 * 1024 * 1024
TIMEOUT = 20
CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")
TLS_FAILED = -1  # certificate verification failed; never retried without verification

ENDPOINTS = {
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{org}",
    "lever": "https://api.lever.co/v0/postings/{org}?mode=json",
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{org}/jobs",
}

Fetcher = Callable[[str], Tuple[int, Optional[bytes]]]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Never follow redirects: a 3xx is reported as an error, not chased to another host or scheme."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        return None


# Replaces the default redirect handler; TLS verification stays on (default context).
OPENER = urllib.request.build_opener(_NoRedirect())


def http_get(url: str) -> Tuple[int, Optional[bytes]]:
    if not url.startswith("https://"):
        return 0, None
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "hiring-prep-ats-check"})
    try:
        with OPENER.open(req, timeout=TIMEOUT) as resp:  # noqa: S310 (fixed https hosts)
            body = resp.read(MAX_BYTES + 1)
            if len(body) > MAX_BYTES:
                return resp.status, None
            return resp.status, body
    except urllib.error.HTTPError as exc:
        return exc.code, None
    except urllib.error.URLError as exc:
        if isinstance(getattr(exc, "reason", None), ssl.SSLCertVerificationError):
            # Some Python builds (python.org on macOS) ship without CA certificates. curl uses the system
            # trust store and still verifies certificates; verification is never turned off.
            return curl_get(url)
        return 0, None
    except (TimeoutError, OSError):
        return 0, None


def curl_get(url: str) -> Tuple[int, Optional[bytes]]:
    if not shutil.which("curl"):
        return TLS_FAILED, None
    # -q must come first: it stops curl from reading ~/.curlrc (which could say "insecure").
    cmd = ["curl", "-q", "-sS", "--proto", "=https", "--proto-redir", "=https", "--max-redirs", "0",
           "-m", str(TIMEOUT), "--max-filesize", str(MAX_BYTES),
           "-H", "Accept: application/json", "-A", "hiring-prep-ats-check", "-w", "\n%{http_code}", url]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT + 5)
    except (subprocess.TimeoutExpired, OSError):
        return 0, None
    if r.returncode == 60:  # curl: peer certificate cannot be authenticated
        return TLS_FAILED, None
    body, _, code = r.stdout.rpartition(b"\n")
    try:
        status = int(code.strip() or 0)
    except ValueError:
        return 0, None
    return status, (body if status == 200 and len(body) <= MAX_BYTES else None)


def clean(s: object) -> str:
    """Drop control and format characters (including bidi overrides such as U+202E)."""
    text = CTRL_RE.sub(" ", str(s or ""))
    text = "".join(" " if unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp") else ch for ch in text)
    return text.strip()[:300]


def parse(board: str, data: object) -> List[Dict[str, str]]:
    jobs: List[Dict[str, str]] = []
    if board == "ashby" and isinstance(data, dict):
        for j in data.get("jobs") or []:
            if isinstance(j, dict) and j.get("isListed", True):
                jobs.append({"title": clean(j.get("title")), "location": clean(j.get("location")), "url": clean(j.get("jobUrl"))})
    elif board == "lever" and isinstance(data, list):
        for j in data:
            if isinstance(j, dict):
                cats = j.get("categories") if isinstance(j.get("categories"), dict) else {}
                jobs.append({"title": clean(j.get("text")), "location": clean(cats.get("location")), "url": clean(j.get("hostedUrl"))})
    elif board == "greenhouse" and isinstance(data, dict):
        for j in data.get("jobs") or []:
            if isinstance(j, dict):
                loc = j.get("location") if isinstance(j.get("location"), dict) else {}
                jobs.append({"title": clean(j.get("title")), "location": clean(loc.get("name")), "url": clean(j.get("absolute_url"))})
    return [j for j in jobs if j["url"].startswith("https://") or not j["url"]]


def check(org: str, title: Optional[str] = None, fetch: Fetcher = http_get) -> Dict[str, dict]:
    if not ORG_RE.match(org or "") or ".." in org:
        raise ValueError(f"invalid board slug {org!r}")
    words = [w for w in re.split(r"\W+", (title or "").lower()) if w]
    results: Dict[str, dict] = {}
    for board, tmpl in ENDPOINTS.items():
        status, body = fetch(tmpl.format(org=org))
        if status == 404:
            results[board] = {"status": "not found", "jobs": []}
            continue
        if status == TLS_FAILED:
            results[board] = {"status": "error (TLS certificate verification failed: install your Python's CA certificates, or open the URL in a browser)", "jobs": []}
            continue
        if status != 200 or body is None:
            results[board] = {"status": f"error (HTTP {status or 'no response'})", "jobs": []}
            continue
        try:
            data = json.loads(body.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            results[board] = {"status": "error (not JSON)", "jobs": []}
            continue
        jobs = parse(board, data)
        matches = [j for j in jobs if all(w in j["title"].lower() for w in words)] if words else jobs
        results[board] = {"status": "board found", "total": len(jobs), "jobs": matches}
    return results


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Check public ATS job boards for a live role")
    ap.add_argument("org", help="board slug, e.g. the <org> in jobs.lever.co/<org>")
    ap.add_argument("--title", help="words that must all appear in the job title (case-insensitive)")
    ap.add_argument("--json", action="store_true", help="print JSON")
    args = ap.parse_args(argv)
    try:
        res = check(args.org, args.title)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        found_any = False
        for board, r in res.items():
            extra = f", {r.get('total', 0)} open roles" if r["status"] == "board found" else ""
            print(f"{board}: {r['status']}{extra}")
            for j in r["jobs"]:
                found_any = True
                print(f"  - {j['title']} | {j['location'] or 'location not stated'} | {j['url']}")
        if not found_any:
            print("No matching role found on Ashby, Lever or Greenhouse. Check the company careers page by hand and report the role as unverified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
