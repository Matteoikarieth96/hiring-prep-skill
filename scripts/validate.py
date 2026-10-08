#!/usr/bin/env python3
"""Validate a hiring-prep guide.json before building it.

Usage:
    python3 scripts/validate.py guide.json [--today YYYY-MM-DD] [--quiet]

Exit code 1 when there are errors, 0 otherwise (warnings are printed but do
not fail). Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))

from guide_lib import (  # noqa: E402
    BAD_SCHEME_RE,
    DASH_RE,
    DOB_RE,
    ISO_DATE_RE,
    LETTERS,
    MD_LINK_RE,
    PLACEHOLDER_RE,
    SECTION_ID_RE,
    SLUG_RE,
    SOURCE_ID_RE,
    as_paragraphs,
    contact_hits,
    final_mcqs,
    is_safe_url,
    iter_strings,
    letter_counts,
    load_guide,
)

REQUIRED_TOP = ("meta", "tldr", "overview", "qa", "playbook", "exam", "sources")
COUNT_KEYS = ("tldr", "qa", "open", "mcq")
OVERVIEW_TEXT_KEYS = ("what_it_is", "how_it_works", "business_model", "team", "funding", "risks")
PLAYBOOK_LIST_KEYS = ("positioning", "questions_to_ask", "do", "dont")
NUMBER_STATUSES = ("verified", "claimed", "estimate")
FIT_LEVELS = ("strong", "partial", "gap")
SOURCE_KINDS = ("primary", "secondary")
MAX_LETTER_SHARE = 0.35
BALANCE_MIN_QUESTIONS = 8
STALE_DAYS = 45
POSITIONAL_RE = re.compile(
    r"(?i:\b(?:first|second|third|fourth|last)\s+(?:option|answer|choice)s?\b)"
    r"|\b(?i:option|answer|choice)\s+[A-D]\b(?![-\w])"
)


class Report:
    def __init__(self) -> None:
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.info: Optional[str] = None

    def err(self, path: str, msg: str) -> None:
        self.errors.append(f"{path}: {msg}")

    def warn(self, path: str, msg: str) -> None:
        self.warnings.append(f"{path}: {msg}")


def _nonempty_str(v: Any) -> bool:
    return isinstance(v, str) and v.strip() != ""


def _parse_date(v: Any) -> Optional[date]:
    if not isinstance(v, str) or not ISO_DATE_RE.match(v):
        return None
    try:
        return date.fromisoformat(v)
    except ValueError:
        return None


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _check_date(rep: Report, path: str, v: Any, required: bool = True) -> Optional[date]:
    if v is None and not required:
        return None
    d = _parse_date(v)
    if d is None:
        rep.err(path, f"expected an ISO date YYYY-MM-DD, got {v!r}")
    return d


def _check_paras(rep: Report, path: str, v: Any, required: bool = True) -> None:
    if isinstance(v, str):
        if required and not v.strip():
            rep.err(path, "is empty")
        return
    if isinstance(v, list):
        if required and not as_paragraphs(v):
            rep.err(path, "needs at least one non-empty paragraph")
        for i, item in enumerate(v):
            if not isinstance(item, str):
                rep.err(f"{path}[{i}]", "must be a string")
        return
    if required or v is not None:
        rep.err(path, "must be a string or a list of strings")


def _check_source_ref(rep: Report, path: str, ref: Any, source_ids: set, required: bool) -> None:
    if ref is None or ref == "":
        if required:
            rep.err(path, "missing source id")
        return
    refs = ref if isinstance(ref, list) else [ref]
    for r in refs:
        if not isinstance(r, str) or r not in source_ids:
            rep.err(path, f"unknown source id {r!r} (add it to sources)")


# --------------------------------------------------------------------------
# Section checks
# --------------------------------------------------------------------------

def check_meta(rep: Report, meta: Any, today: date) -> dict:
    if not isinstance(meta, dict):
        rep.err("meta", "must be an object")
        return {}
    slug = meta.get("slug")
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        rep.err("meta.slug", f"invalid slug {slug!r}: lowercase letters, digits, hyphens, max 64")
    for key in ("title", "company", "role"):
        if not _nonempty_str(meta.get(key)):
            rep.err(f"meta.{key}", "is required")
    as_of = _check_date(rep, "meta.as_of", meta.get("as_of"))
    if as_of:
        if as_of > today:
            rep.warn("meta.as_of", f"{as_of} is in the future")
        elif (today - as_of).days > STALE_DAYS:
            rep.warn("meta.as_of", f"data is {(today - as_of).days} days old: offer a refresh")
    idate = meta.get("interview_date")
    if idate is not None:
        d = _check_date(rep, "meta.interview_date", idate)
        if d and d < today:
            rep.warn("meta.interview_date", f"{d} is in the past")
    tc = meta.get("target_counts")
    if not isinstance(tc, dict):
        rep.err("meta.target_counts", "must be an object with tldr, qa, open and mcq")
        tc = {}
    for k in COUNT_KEYS:
        if not _is_int(tc.get(k)) or tc.get(k) < 0:
            rep.err(f"meta.target_counts.{k}", "must be a non-negative integer")
    seed = meta.get("shuffle_seed")
    if seed is not None and not _is_int(seed):
        rep.err("meta.shuffle_seed", "must be an integer")
    if "shuffle" in meta and not isinstance(meta["shuffle"], bool):
        rep.err("meta.shuffle", "must be true or false")
    labels = meta.get("labels")
    if labels is not None:
        if not isinstance(labels, dict) or not all(isinstance(v, str) for v in labels.values()):
            rep.err("meta.labels", "must be an object of strings")
    return meta


def check_sources(rep: Report, sources: Any) -> set:
    ids: set = set()
    if not isinstance(sources, list) or not sources:
        rep.err("sources", "must be a non-empty list")
        return ids
    for i, s in enumerate(sources):
        p = f"sources[{i}]"
        if not isinstance(s, dict):
            rep.err(p, "must be an object")
            continue
        sid = s.get("id")
        if not isinstance(sid, str) or not SOURCE_ID_RE.match(sid):
            rep.err(f"{p}.id", f"invalid id {sid!r} (letters, digits, _ or -, max 16)")
        elif sid in ids:
            rep.err(f"{p}.id", f"duplicate id {sid!r}")
        else:
            ids.add(sid)
        if not _nonempty_str(s.get("title")):
            rep.err(f"{p}.title", "is required")
        if not is_safe_url(s.get("url")):
            rep.err(f"{p}.url", f"must be an absolute http(s) URL, got {s.get('url')!r}")
        _check_date(rep, f"{p}.accessed", s.get("accessed"))
        kind = s.get("kind")
        if kind is not None and kind not in SOURCE_KINDS:
            rep.err(f"{p}.kind", f"must be one of {SOURCE_KINDS}")
    return ids


def check_tldr(rep: Report, tldr: Any) -> int:
    if not isinstance(tldr, list):
        rep.err("tldr", "must be a list of strings")
        return 0
    for i, item in enumerate(tldr):
        if not _nonempty_str(item):
            rep.err(f"tldr[{i}]", "must be a non-empty string")
    return len(tldr)


def check_overview(rep: Report, ov: Any, source_ids: set, sources_by_id: dict) -> None:
    if not isinstance(ov, dict):
        rep.err("overview", "must be an object")
        return
    for key in OVERVIEW_TEXT_KEYS:
        _check_paras(rep, f"overview.{key}", ov.get(key))
    nums = ov.get("numbers")
    if not isinstance(nums, list) or not nums:
        rep.err("overview.numbers", "must be a non-empty list (every number needs source, date, status)")
        nums = []
    for i, n in enumerate(nums):
        p = f"overview.numbers[{i}]"
        if not isinstance(n, dict):
            rep.err(p, "must be an object")
            continue
        for key in ("label", "value"):
            if not _nonempty_str(n.get(key)):
                rep.err(f"{p}.{key}", "is required")
        status = n.get("status")
        if status not in NUMBER_STATUSES:
            rep.err(f"{p}.status", f"must be one of {NUMBER_STATUSES}")
        _check_date(rep, f"{p}.date", n.get("date"))
        _check_source_ref(rep, f"{p}.source", n.get("source"), source_ids, required=True)
        if status == "verified":
            refs = n.get("source") if isinstance(n.get("source"), list) else [n.get("source")]
            kinds = {sources_by_id.get(r, {}).get("kind") for r in refs if isinstance(r, str)}
            if kinds and "primary" not in kinds:
                rep.warn(p, "marked verified but cites no primary source")
    comp = ov.get("competitors")
    if not isinstance(comp, dict):
        rep.err("overview.competitors", "must be an object with columns and rows")
    else:
        cols = comp.get("columns")
        rows = comp.get("rows")
        if not isinstance(cols, list) or len(cols) < 2 or not all(isinstance(c, str) for c in cols):
            rep.err("overview.competitors.columns", "needs at least two string columns")
            cols = []
        if not isinstance(rows, list) or not rows:
            rep.err("overview.competitors.rows", "needs at least one row")
            rows = []
        for i, r in enumerate(rows):
            if not isinstance(r, list) or not all(isinstance(c, str) for c in r):
                rep.err(f"overview.competitors.rows[{i}]", "must be a list of strings")
            elif cols and len(r) != len(cols):
                rep.err(f"overview.competitors.rows[{i}]", f"has {len(r)} cells, expected {len(cols)}")
        _check_paras(rep, "overview.competitors.intro", comp.get("intro"), required=False)
    news = ov.get("news")
    if not isinstance(news, list) or not news:
        rep.warn("overview.news", "no recent news: say so explicitly if nothing was found")
        news = []
    for i, n in enumerate(news):
        p = f"overview.news[{i}]"
        if not isinstance(n, dict):
            rep.err(p, "must be an object")
            continue
        _check_date(rep, f"{p}.date", n.get("date"))
        if not _nonempty_str(n.get("text")):
            rep.err(f"{p}.text", "is required")
        _check_source_ref(rep, f"{p}.source", n.get("source"), source_ids, required=True)
    traps = ov.get("traps")
    if not isinstance(traps, list) or not traps:
        rep.err("overview.traps", "list at least one stale or commonly wrong fact")
        traps = []
    for i, t in enumerate(traps):
        p = f"overview.traps[{i}]"
        if not isinstance(t, dict):
            rep.err(p, "must be an object")
            continue
        for key in ("myth", "fact"):
            if not _nonempty_str(t.get(key)):
                rep.err(f"{p}.{key}", "is required")
        _check_source_ref(rep, f"{p}.source", t.get("source"), source_ids, required=False)
    tips = ov.get("tips")
    if tips is not None:
        _check_paras(rep, "overview.tips", tips, required=False)


def check_qa(rep: Report, qa: Any) -> int:
    if not isinstance(qa, list) or not qa:
        rep.err("qa", "must be a non-empty list of groups")
        return 0
    total = 0
    for gi, g in enumerate(qa):
        p = f"qa[{gi}]"
        if not isinstance(g, dict):
            rep.err(p, "must be an object with group and items")
            continue
        if not _nonempty_str(g.get("group")):
            rep.err(f"{p}.group", "is required")
        items = g.get("items")
        if not isinstance(items, list) or not items:
            rep.err(f"{p}.items", "must be a non-empty list")
            continue
        for ii, it in enumerate(items):
            ip = f"{p}.items[{ii}]"
            if not isinstance(it, dict):
                rep.err(ip, "must be an object with q and a")
                continue
            if not _nonempty_str(it.get("q")):
                rep.err(f"{ip}.q", "is required")
            _check_paras(rep, f"{ip}.a", it.get("a"))
            total += 1
    return total


def check_playbook(rep: Report, pb: Any) -> None:
    if not isinstance(pb, dict):
        rep.err("playbook", "must be an object")
        return
    for key in PLAYBOOK_LIST_KEYS:
        v = pb.get(key)
        if not isinstance(v, list) or not as_paragraphs(v):
            rep.err(f"playbook.{key}", "must be a non-empty list of strings")
    em = pb.get("evidence_map")
    if not isinstance(em, list) or not em:
        rep.err("playbook.evidence_map", "map each job requirement to resume evidence")
        em = []
    for i, row in enumerate(em):
        p = f"playbook.evidence_map[{i}]"
        if not isinstance(row, dict):
            rep.err(p, "must be an object")
            continue
        for key in ("requirement", "evidence"):
            if not _nonempty_str(row.get(key)):
                rep.err(f"{p}.{key}", "is required (write 'No direct evidence' for a gap)")
        if row.get("fit") not in FIT_LEVELS:
            rep.err(f"{p}.fit", f"must be one of {FIT_LEVELS}")
    obj = pb.get("objections")
    if not isinstance(obj, list) or not obj:
        rep.err("playbook.objections", "must be a non-empty list")
        obj = []
    for i, o in enumerate(obj):
        p = f"playbook.objections[{i}]"
        if not isinstance(o, dict) or not _nonempty_str(o.get("objection")) or not _nonempty_str(o.get("reframe")):
            rep.err(p, "needs objection and reframe")
    star = pb.get("star_stories")
    if not isinstance(star, list) or not star:
        rep.err("playbook.star_stories", "must be a non-empty list")
        star = []
    elif len(star) != 3:
        rep.warn("playbook.star_stories", f"has {len(star)} stories, the playbook asks for 3")
    for i, s in enumerate(star):
        p = f"playbook.star_stories[{i}]"
        if not isinstance(s, dict):
            rep.err(p, "must be an object")
            continue
        for key in ("title", "situation", "task", "action", "result"):
            if not _nonempty_str(s.get(key)):
                rep.err(f"{p}.{key}", "is required")
    cheat = pb.get("cheat_sheet")
    if not isinstance(cheat, list) or not cheat:
        rep.err("playbook.cheat_sheet", "must be a non-empty list")
        cheat = []
    for i, c in enumerate(cheat):
        if not isinstance(c, dict) or not _nonempty_str(c.get("term")) or not _nonempty_str(c.get("value")):
            rep.err(f"playbook.cheat_sheet[{i}]", "needs term and value")
    plan = pb.get("plan_30_60_90")
    if not isinstance(plan, list) or not plan:
        rep.err("playbook.plan_30_60_90", "must be a non-empty list of phases")
        plan = []
    elif len(plan) != 3:
        rep.warn("playbook.plan_30_60_90", f"has {len(plan)} phases, expected 3")
    for i, ph in enumerate(plan):
        p = f"playbook.plan_30_60_90[{i}]"
        if not isinstance(ph, dict) or not _nonempty_str(ph.get("phase")):
            rep.err(p, "needs a phase label")
            continue
        items = ph.get("items")
        if not isinstance(items, list) or not as_paragraphs(items):
            rep.err(f"{p}.items", "must be a non-empty list of strings")


def check_exam(rep: Report, exam: Any, meta: dict, guide: dict) -> Tuple[int, int]:
    if not isinstance(exam, dict):
        rep.err("exam", "must be an object")
        return 0, 0
    open_q = exam.get("open")
    n_open = 0
    if not isinstance(open_q, list):
        rep.err("exam.open", "must be a list")
    else:
        for i, it in enumerate(open_q):
            p = f"exam.open[{i}]"
            if not isinstance(it, dict) or not _nonempty_str(it.get("q")):
                rep.err(p, "needs q")
                continue
            _check_paras(rep, f"{p}.a", it.get("a"))
            n_open += 1
    sections = exam.get("sections")
    sec_ids: set = set()
    if not isinstance(sections, list) or not sections:
        rep.err("exam.sections", "must be a non-empty list")
        sections = []
    for i, s in enumerate(sections):
        p = f"exam.sections[{i}]"
        if not isinstance(s, dict):
            rep.err(p, "must be an object")
            continue
        sid = s.get("id")
        if not isinstance(sid, str) or not SECTION_ID_RE.match(sid):
            rep.err(f"{p}.id", f"invalid section id {sid!r}")
        elif sid in sec_ids:
            rep.err(f"{p}.id", f"duplicate section id {sid!r}")
        else:
            sec_ids.add(sid)
        if not _nonempty_str(s.get("title")):
            rep.err(f"{p}.title", "is required")
    mcq = exam.get("mcq")
    if not isinstance(mcq, list) or not mcq:
        rep.err("exam.mcq", "must be a non-empty list")
        return n_open, 0
    used_secs: set = set()
    seen_q: set = set()
    for i, q in enumerate(mcq):
        p = f"exam.mcq[{i}]"
        if not isinstance(q, dict):
            rep.err(p, "must be an object")
            continue
        if q.get("s") not in sec_ids:
            rep.err(f"{p}.s", f"unknown section {q.get('s')!r}")
        else:
            used_secs.add(q.get("s"))
        if not _nonempty_str(q.get("q")):
            rep.err(f"{p}.q", "is required")
        else:
            norm = " ".join(q["q"].lower().split())
            if norm in seen_q:
                rep.warn(f"{p}.q", "duplicate question text")
            seen_q.add(norm)
        a = q.get("a")
        a_ok = _is_int(a) and 0 <= a <= 3
        opts = q.get("o")
        if not isinstance(opts, list) or len(opts) != 4:
            rep.err(f"{p}.o", "must have exactly 4 options")
        else:
            if not all(_nonempty_str(o) for o in opts):
                rep.err(f"{p}.o", "options must be non-empty strings")
            else:
                normed = [" ".join(o.lower().split()) for o in opts]
                if len(set(normed)) != 4:
                    rep.err(f"{p}.o", "options must be unique")
                for oi, o in enumerate(normed):
                    if "all of the above" in o or "none of the above" in o:
                        rep.err(f"{p}.o[{oi}]", "no 'all/none of the above' options (they break when shuffled)")
                if a_ok:
                    lens = [len(o) for o in opts]
                    others = [ln for oi, ln in enumerate(lens) if oi != a]
                    if lens[a] > 1.8 * max(others):
                        rep.warn(f"{p}.o", "the correct option is much longer than the others (a giveaway)")
        if not a_ok:
            rep.err(f"{p}.a", f"must be an integer 0 to 3, got {a!r}")
        e = q.get("e")
        if not isinstance(e, list) or not as_paragraphs(e):
            rep.err(f"{p}.e", "explanation is required (a list of paragraphs)")
        elif len(as_paragraphs(e)) < 2:
            rep.warn(f"{p}.e", "explanations should have 2 short paragraphs with a concrete example")
        if not _nonempty_str(q.get("k")):
            rep.err(f"{p}.k", "key point is required")
        if meta.get("shuffle", True) is not False:
            for field, val in (("e", e), ("k", q.get("k"))):
                for txt in as_paragraphs(val):
                    if POSITIONAL_RE.search(txt):
                        rep.err(f"{p}.{field}", "refers to an option by position or letter; options are shuffled, so quote the option text instead")
        d = q.get("d")
        if d is not None and d not in (1, 2, 3):
            rep.err(f"{p}.d", "difficulty must be 1, 2 or 3")
    for sid in sec_ids - used_secs:
        rep.warn("exam.sections", f"section {sid!r} has no questions")
    verdicts = exam.get("verdicts")
    if verdicts is not None:
        if not isinstance(verdicts, list) or not verdicts:
            rep.err("exam.verdicts", "must be a non-empty list")
        else:
            for i, v in enumerate(verdicts):
                p = f"exam.verdicts[{i}]"
                if not isinstance(v, dict) or not isinstance(v.get("min"), (int, float)) or isinstance(v.get("min"), bool):
                    rep.err(p, "needs a numeric min between 0 and 1")
                    continue
                if not 0 <= v["min"] <= 1:
                    rep.err(f"{p}.min", "must be between 0 and 1")
                if not _nonempty_str(v.get("title")) or not _nonempty_str(v.get("text")):
                    rep.err(p, "needs title and text")
            if not any(isinstance(v, dict) and v.get("min") == 0 for v in verdicts):
                rep.err("exam.verdicts", "needs a band with min 0 so every score gets a verdict")

    # Balance of the correct letter after the deterministic shuffle.
    shuffled = final_mcqs(guide)
    counts = letter_counts(shuffled)
    n = sum(counts)
    if n:
        share = max(counts) / n
        dist = ", ".join(f"{LETTERS[i]}={counts[i]}" for i in range(4))
        if share > MAX_LETTER_SHARE:
            msg = f"correct answers are unbalanced after shuffle ({dist}); no letter may exceed 35%"
            if n >= BALANCE_MIN_QUESTIONS:
                rep.err("exam.mcq", msg)
            else:
                rep.warn("exam.mcq", msg + f" (only {n} questions, so not enforced)")
        rep.info = f"answer letters after shuffle: {dist}"
    return n_open, len(mcq)


def check_text_rules(rep: Report, guide: Any) -> None:
    for path, s in iter_strings(guide):
        if DASH_RE.search(s):
            rep.err(path, "contains an em or en dash; use a comma, colon or parentheses")
        for kind in contact_hits(s):
            rep.err(path, f"looks like an {kind}: contact details must never appear in the guide")
        if DOB_RE.search(s):
            rep.warn(path, "mentions a date of birth: remove personal data")
        if BAD_SCHEME_RE.search(s):
            rep.err(path, "contains a non-http(s) URL scheme (javascript:, data:, file:, ...)")
        for m in MD_LINK_RE.finditer(s):
            if not is_safe_url(m.group(2)):
                rep.err(path, f"link target {m.group(2)!r} is not an absolute http(s) URL")
        if PLACEHOLDER_RE.search(s):
            rep.err(path, "template placeholder left in the text (TODO, {{ }})")


def validate(guide: Any, today: Optional[date] = None) -> Report:
    rep = Report()
    today = today or date.today()
    if not isinstance(guide, dict):
        rep.err("$", "the guide must be a JSON object")
        return rep
    for key in REQUIRED_TOP:
        if key not in guide:
            rep.err(key, "required section is missing")
    meta = check_meta(rep, guide.get("meta"), today)
    source_ids = check_sources(rep, guide.get("sources"))
    sources_by_id = {
        s.get("id"): s for s in guide.get("sources", []) if isinstance(s, dict) and isinstance(s.get("id"), str)
    } if isinstance(guide.get("sources"), list) else {}
    counts = {
        "tldr": check_tldr(rep, guide.get("tldr")),
        "qa": check_qa(rep, guide.get("qa")),
    }
    check_overview(rep, guide.get("overview"), source_ids, sources_by_id)
    check_playbook(rep, guide.get("playbook"))
    counts["open"], counts["mcq"] = check_exam(rep, guide.get("exam"), meta, guide)
    tc = meta.get("target_counts") if isinstance(meta.get("target_counts"), dict) else {}
    for k in COUNT_KEYS:
        want = tc.get(k)
        if _is_int(want) and counts.get(k) != want:
            rep.err(f"meta.target_counts.{k}", f"expects {want}, the guide has {counts.get(k)}")
    check_text_rules(rep, guide)
    return rep


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Validate a hiring-prep guide.json")
    ap.add_argument("guide", type=Path)
    ap.add_argument("--today", help="override today's date (YYYY-MM-DD) for staleness checks")
    ap.add_argument("--quiet", action="store_true", help="print errors only")
    args = ap.parse_args(argv)
    try:
        guide = load_guide(args.guide)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 1
    today = date.fromisoformat(args.today) if args.today else None
    rep = validate(guide, today)
    for e in rep.errors:
        print(f"ERROR   {e}")
    if not args.quiet:
        for w in rep.warnings:
            print(f"WARNING {w}")
        if rep.info:
            print(f"INFO    {rep.info}")
    print(f"{len(rep.errors)} error(s), {len(rep.warnings)} warning(s)")
    return 1 if rep.errors else 0


if __name__ == "__main__":
    sys.exit(main())
