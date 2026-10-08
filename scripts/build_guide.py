#!/usr/bin/env python3
"""Build a single self-contained HTML interview prep page from guide.json.

Usage:
    python3 scripts/build_guide.py guide.json [-o out/<slug>.html] [--out-dir out]
                                   [--webfonts] [--no-csp]

The guide is validated first; the build stops on validation errors.
Every piece of text is HTML-escaped. A tiny inline markup is supported
(**bold**, *italic*, `code`, [text](https://url)); links with any scheme other
than http(s) are dropped. The quiz data is embedded as application/json and
rendered by the page script with createElement/textContent only.
Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

from guide_lib import (  # noqa: E402
    as_paragraphs,
    compact_tokens,
    esc,
    final_mcqs,
    is_safe_url,
    json_for_script,
    load_guide,
    make_private_dir,
    render_inline,
    safe_output_path,
    write_private,
)
from validate import validate  # noqa: E402

ASSETS = Path(__file__).resolve().parent / "assets"

DEFAULT_LABELS: Dict[str, str] = {
    "toc_tldr": "TL;DR", "toc_overview": "Overview", "toc_qa": "Quick Q&A",
    "toc_playbook": "Playbook", "toc_exam": "Exam", "toc_sources": "Sources",
    "part_tldr": "1 \u00b7 TL;DR", "part_overview": "2 \u00b7 Overview", "part_qa": "3 \u00b7 Quick Q&A",
    "part_playbook": "4 \u00b7 Personal playbook", "part_exam": "5 \u00b7 Exam", "part_sources": "Sources",
    "tldr_title": "The ideas to walk in with",
    "overview_title": "The company and the market",
    "what_it_is": "What it is", "how_it_works": "How it works", "business_model": "Business model",
    "numbers": "Numbers that matter", "team": "Team", "funding": "Funding", "competitors": "Competitors",
    "news": "Recent news", "risks": "Risks and controversies",
    "traps": "Traps: facts careless candidates get wrong", "tip": "Interview tip",
    "numbers_legend": "Verified: checked against a primary source. Claimed: stated by the company and not independently checked. Estimate: derived or third-party.",
    "col_metric": "Metric", "col_value": "Value", "col_status": "Status", "col_source": "Source, date",
    "status_verified": "verified", "status_claimed": "claimed", "status_estimate": "estimate",
    "myth": "Careless version", "fact": "Accurate version",
    "qa_title": "Quick questions and model answers",
    "qa_dek": "Say your answer out loud first, then open the model answer.",
    "playbook_title": "Your personal playbook",
    "playbook_dek": "Built only from your resume. Where the resume has no evidence for a requirement, the gap is named instead of filled.",
    "positioning": "How to position yourself", "evidence_map": "Resume evidence for each requirement",
    "col_requirement": "Requirement", "col_evidence": "Evidence from your resume", "col_fit": "Fit",
    "fit_strong": "strong", "fit_partial": "partial", "fit_gap": "gap",
    "objections": "Likely objections and honest reframes", "reframe": "Reframe",
    "star": "Three STAR stories to prepare", "situation": "Situation", "task": "Task",
    "action": "Action", "result": "Result", "use_for": "Use it for",
    "questions_to_ask": "Questions to ask the interviewers", "do_dont": "Do and don't",
    "do": "Do", "dont": "Don't", "cheat_sheet": "Numbers cheat sheet", "plan": "30-60-90 day skeleton",
    "exam_title": "Test yourself",
    "exam_dek": "Do this cold, a day or two before the interview.",
    "open_title": "Part A: open questions",
    "open_dek": "Answer out loud, then open the model answer.",
    "mcq_title": "Part B: multiple choice",
    "mcq_dek": "Click an option to check it. The explanation opens right away. Study mode reveals every answer; Start over clears your progress. Progress is saved in this browser only.",
    "study_mode": "Study mode", "start_over": "Start over", "key_point": "Key point",
    "correct": "Correct", "wrong": "Wrong. Correct answer:", "answer": "Answer:",
    "right_of": "right of", "answered": "answered", "questions": "questions",
    "progress": "Quiz progress", "sections_nav": "Quiz sections",
    "nojs": "The multiple-choice test needs JavaScript. Everything else on this page works without it.",
    "sources_title": "Sources", "accessed": "accessed", "primary": "primary", "secondary": "secondary",
    "footer": "Data as of {as_of}. Numbers marked claimed come from the company itself. Check anything you plan to quote.",
    "theme": "Theme", "contents": "Contents",
    "fictional": "Fictional example: the company, the candidate, the people and every number on this page are invented.",
    "chip_role": "Role", "chip_interview": "Interview", "chip_stage": "Stage", "chip_job": "Job post",
    "chip_as_of": "Data as of",
}

DEFAULT_VERDICTS = [
    {"min": 0.85, "title": "Ready", "text": "Review only the questions you missed, then rehearse your STAR stories out loud."},
    {"min": 0.6, "title": "Solid base", "text": "Reread the overview and the traps, then retake the test tomorrow."},
    {"min": 0, "title": "Not yet", "text": "Go through the guide in study mode, then press Start over and retake the test."},
]

SEP = " \u00b7 "

FONTS_URL = (
    "https://fonts.googleapis.com/css2?family=Archivo:wght@500;600;700;800"
    "&family=Literata:ital,opsz,wght@0,7..72,400;0,7..72,600;1,7..72,400"
    "&family=JetBrains+Mono:wght@500&display=swap"
)


def _sha256_b64(text: str) -> str:
    return base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode("ascii")


class Page:
    def __init__(self, guide: dict) -> None:
        self.g = guide
        self.meta = guide.get("meta", {})
        labels = dict(DEFAULT_LABELS)
        labels.update({k: v for k, v in (self.meta.get("labels") or {}).items() if isinstance(v, str)})
        self.L = labels

    # -- small helpers ---------------------------------------------------
    def l(self, key: str) -> str:  # noqa: E743
        return esc(self.L.get(key, key))

    @staticmethod
    def paras(value: Any) -> str:
        return "".join(f"<p>{render_inline(p)}</p>" for p in as_paragraphs(value))

    @staticmethod
    def refs(ref: Any) -> str:
        if not ref:
            return ""
        ids = ref if isinstance(ref, list) else [ref]
        return " " + " ".join(
            f'<a class="ref" href="#src-{esc(i)}">[{esc(i)}]</a>' for i in ids if isinstance(i, str)
        )

    def section_open(self, sid: str, badge_key: str, title_key: str, title: Optional[str] = None) -> str:
        t = render_inline(title) if title else self.l(title_key)
        return (
            f'<section class="part" id="{sid}" aria-labelledby="{sid}-h">'
            f'<span class="partbadge">{self.l(badge_key)}</span><h2 id="{sid}-h">{t}</h2>'
        )

    # -- parts -----------------------------------------------------------
    def header(self) -> str:
        m = self.meta
        eyebrow = m.get("eyebrow") or f"Interview prep \u00b7 {m.get('company', '')} \u00b7 {m.get('role', '')}"
        chips = [("chip_role", m.get("role"))]
        if m.get("interview_date"):
            chips.append(("chip_interview", m.get("interview_date")))
        if m.get("stage"):
            chips.append(("chip_stage", m.get("stage")))
        if m.get("job_post_status"):
            chips.append(("chip_job", m.get("job_post_status")))
        chips.append(("chip_as_of", m.get("as_of")))
        chip_html = "".join(f"<li><b>{self.l(k)}</b> {render_inline(v)}</li>" for k, v in chips if v)
        banner = f'<p class="banner">{self.l("fictional")}</p>' if m.get("fictional") else ""
        toc = "".join(
            f'<a href="#{sid}"><b>{n}</b>{self.l(key)}</a>'
            for n, sid, key in (
                ("1", "tldr", "toc_tldr"), ("2", "overview", "toc_overview"), ("3", "qa", "toc_qa"),
                ("4", "playbook", "toc_playbook"), ("5", "exam", "toc_exam"), ("\u00b7", "sources", "toc_sources"),
            )
        )
        return (
            "<header>"
            f'<div class="topline"><p class="eyebrow">{render_inline(eyebrow)}</p>'
            f'<button class="btn theme-btn" id="themeBtn" type="button" data-label="{self.l("theme")}">{self.l("theme")}: auto</button></div>'
            f"<h1>{render_inline(m.get('title'))}</h1>"
            + (f'<p class="dek">{render_inline(m["dek"])}</p>' if m.get("dek") else "")
            + f'<ul class="chips">{chip_html}</ul>{banner}'
            f'<nav class="toc" aria-label="{self.l("contents")}">{toc}</nav>'
            "</header>"
        )

    def tldr(self) -> str:
        items = "".join(f"<li>{render_inline(t)}</li>" for t in self.g.get("tldr", []))
        return self.section_open("tldr", "part_tldr", "tldr_title") + f'<div class="tldr"><ol>{items}</ol></div></section>'

    def overview(self) -> str:
        ov = self.g.get("overview", {})
        out = [self.section_open("overview", "part_overview", "overview_title")]
        for key in ("what_it_is", "how_it_works", "business_model"):
            out.append(f"<h3>{self.l(key)}</h3>{self.paras(ov.get(key))}")
        # Numbers table
        rows = []
        for n in ov.get("numbers", []):
            status = n.get("status", "")
            rows.append(
                f"<tr><td>{render_inline(n.get('label'))}"
                + (f"<br><small>{render_inline(n['note'])}</small>" if n.get("note") else "")
                + f"</td><td>{render_inline(n.get('value'))}</td>"
                f'<td><span class="badge {esc(status)}">{self.l("status_" + status)}</span></td>'
                f'<td><span class="num">{esc(n.get("date"))}</span>{self.refs(n.get("source"))}</td></tr>'
            )
        out.append(
            f"<h3>{self.l('numbers')}</h3><p class=\"legend\">{self.l('numbers_legend')}</p>"
            '<div class="tablewrap"><table class="wide"><thead><tr>'
            f"<th>{self.l('col_metric')}</th><th>{self.l('col_value')}</th><th>{self.l('col_status')}</th><th>{self.l('col_source')}</th>"
            f"</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
        )
        for key in ("team", "funding"):
            out.append(f"<h3>{self.l(key)}</h3>{self.paras(ov.get(key))}")
        comp = ov.get("competitors", {})
        cols = comp.get("columns", [])
        head = "".join(f"<th scope=\"col\">{render_inline(c)}</th>" for c in cols)
        body = "".join(
            "<tr>" + "".join(
                (f'<th scope="row">{render_inline(c)}</th>' if i == 0 else f"<td>{render_inline(c)}</td>")
                for i, c in enumerate(r)
            ) + "</tr>"
            for r in comp.get("rows", [])
        )
        out.append(
            f"<h3>{self.l('competitors')}</h3>{self.paras(comp.get('intro'))}"
            f'<div class="tablewrap"><table class="wide"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'
            + self.paras(comp.get("note"))
        )
        news = ov.get("news") or []
        if news:
            items = "".join(
                f'<li><time datetime="{esc(n.get("date"))}">{esc(n.get("date"))}</time>'
                f"<span>{render_inline(n.get('text'))}{self.refs(n.get('source'))}</span></li>"
                for n in news
            )
            out.append(f"<h3>{self.l('news')}</h3><ul class=\"news\">{items}</ul>")
        risks = as_paragraphs(ov.get("risks"))
        out.append(f"<h3>{self.l('risks')}</h3><ul>" + "".join(f"<li>{render_inline(r)}</li>" for r in risks) + "</ul>")
        traps = "".join(
            '<div class="trap">'
            f'<p class="myth"><b>{self.l("myth")}:</b> {render_inline(t.get("myth"))}</p>'
            f'<p class="fact"><b>{self.l("fact")}:</b> {render_inline(t.get("fact"))}{self.refs(t.get("source"))}</p>'
            "</div>"
            for t in ov.get("traps", [])
        )
        out.append(f"<h3>{self.l('traps')}</h3>{traps}")
        for tip in as_paragraphs(ov.get("tips")):
            out.append(f'<div class="tip"><span class="tag">{self.l("tip")}</span>{render_inline(tip)}</div>')
        out.append("</section>")
        return "".join(out)

    def qa(self) -> str:
        out = [self.section_open("qa", "part_qa", "qa_title"), f'<p class="lede">{self.l("qa_dek")}</p>']
        n = 0
        for g in self.g.get("qa", []):
            out.append(f'<p class="qagroup">{render_inline(g.get("group"))}</p><div class="qalist">')
            for it in g.get("items", []):
                n += 1
                out.append(
                    f'<details class="qa"><summary><span class="qn">{n}</span><span>{render_inline(it.get("q"))}</span></summary>'
                    f'<div class="a">{self.paras(it.get("a"))}</div></details>'
                )
            out.append("</div>")
        out.append("</section>")
        return "".join(out)

    def playbook(self) -> str:
        pb = self.g.get("playbook", {})
        out = [self.section_open("playbook", "part_playbook", "playbook_title"), f'<p class="lede">{self.l("playbook_dek")}</p>']
        out.append(f"<h3>{self.l('positioning')}</h3><ul>" + "".join(f"<li>{render_inline(x)}</li>" for x in as_paragraphs(pb.get("positioning"))) + "</ul>")
        rows = "".join(
            f"<tr><td>{render_inline(r.get('requirement'))}</td><td>{render_inline(r.get('evidence'))}</td>"
            f'<td><span class="badge {esc(r.get("fit"))}">{self.l("fit_" + str(r.get("fit")))}</span></td></tr>'
            for r in pb.get("evidence_map", [])
        )
        out.append(
            f"<h3>{self.l('evidence_map')}</h3>"
            f'<div class="tablewrap"><table class="wide"><thead><tr><th>{self.l("col_requirement")}</th><th>{self.l("col_evidence")}</th><th>{self.l("col_fit")}</th></tr></thead>'
            f"<tbody>{rows}</tbody></table></div>"
        )
        objs = "".join(
            f'<div class="card objection"><p class="say">\u201c{render_inline(o.get("objection"))}\u201d</p>'
            f'<p><b>{self.l("reframe")}:</b> {render_inline(o.get("reframe"))}</p></div>'
            for o in pb.get("objections", [])
        )
        out.append(f"<h3>{self.l('objections')}</h3><div class=\"cards\">{objs}</div>")
        stars = []
        for s in pb.get("star_stories", []):
            dl = "".join(
                f"<dt>{self.l(k)}</dt><dd>{render_inline(s.get(k))}</dd>" for k in ("situation", "task", "action", "result")
            )
            use = f'<p class="use"><b>{self.l("use_for")}:</b> {render_inline(s["use_for"])}</p>' if s.get("use_for") else ""
            stars.append(f'<div class="card star"><h4>{render_inline(s.get("title"))}</h4><dl>{dl}</dl>{use}</div>')
        out.append(f"<h3>{self.l('star')}</h3><div class=\"cards\">{''.join(stars)}</div>")
        out.append(f"<h3>{self.l('questions_to_ask')}</h3><ol>" + "".join(f"<li>{render_inline(x)}</li>" for x in as_paragraphs(pb.get("questions_to_ask"))) + "</ol>")
        dos = "".join(f'<div class="do"><b>{self.l("do")}:</b> {render_inline(x)}</div>' for x in as_paragraphs(pb.get("do")))
        donts = "".join(f'<div class="dont"><b>{self.l("dont")}:</b> {render_inline(x)}</div>' for x in as_paragraphs(pb.get("dont")))
        out.append(f"<h3>{self.l('do_dont')}</h3>{dos}{donts}")
        cheat = "".join(f"<dt>{render_inline(c.get('term'))}</dt><dd>{render_inline(c.get('value'))}</dd>" for c in pb.get("cheat_sheet", []))
        out.append(f"<h3>{self.l('cheat_sheet')}</h3><div class=\"cheat\"><dl>{cheat}</dl></div>")
        phases = "".join(
            f'<div class="card"><h4>{render_inline(p.get("phase"))}</h4>'
            + (f"<p>{render_inline(p['goal'])}</p>" if p.get("goal") else "")
            + "<ul>" + "".join(f"<li>{render_inline(i)}</li>" for i in as_paragraphs(p.get("items"))) + "</ul></div>"
            for p in pb.get("plan_30_60_90", [])
        )
        out.append(f"<h3>{self.l('plan')}</h3><div class=\"plan\">{phases}</div></section>")
        return "".join(out)

    def exam(self, n_mcq: int) -> str:
        ex = self.g.get("exam", {})
        out = [self.section_open("exam", "part_exam", "exam_title"), f'<p class="lede">{self.l("exam_dek")}</p>']
        out.append(f"<h3>{self.l('open_title')}</h3><p>{self.l('open_dek')}</p><div class=\"qalist\">")
        for i, it in enumerate(ex.get("open", []), 1):
            out.append(
                f'<details class="qa"><summary><span class="qn">A{i}</span><span>{render_inline(it.get("q"))}</span></summary>'
                f'<div class="a">{self.paras(it.get("a"))}</div></details>'
            )
        out.append("</div>")
        out.append(
            '<div class="quiz-area">'
            f'<h3 id="exam-quiz">{self.l("mcq_title")}</h3><p>{self.l("mcq_dek")}</p>'
            '<div class="rail">'
            f'<span class="score" id="score" role="status" aria-live="polite">0 {self.l("right_of")} 0 {self.l("answered")}</span>'
            f'<span class="meter" id="meter" role="progressbar" aria-label="{self.l("progress")}" aria-valuemin="0" aria-valuemax="{n_mcq}" aria-valuenow="0"><i id="meterFill"></i></span>'
            '<span class="ctrls">'
            f'<button class="btn" id="studyBtn" type="button" aria-pressed="false">{self.l("study_mode")}</button>'
            f'<button class="btn" id="resetBtn" type="button">{self.l("start_over")}</button>'
            "</span></div>"
            f'<nav class="sec" id="secNav" aria-label="{self.l("sections_nav")}"></nav>'
            '<div id="quiz"></div>'
            f'<noscript><p class="nojs">{self.l("nojs")}</p></noscript>'
            '<div class="final" id="final" hidden><h4 id="finalTitle"></h4><p id="finalText"></p></div>'
            "</div></section>"
        )
        return "".join(out)

    def sources(self) -> str:
        items = []
        for s in self.g.get("sources", []):
            kind = s.get("kind")
            meta = [f"{self.l('accessed')} {esc(s.get('accessed'))}"]
            if s.get("publisher"):
                meta.insert(0, render_inline(s["publisher"]))
            if kind in ("primary", "secondary"):
                meta.append(self.l(kind))
            title = render_inline(s.get("title"))
            if is_safe_url(s.get("url")):
                title = f'<a href="{esc(s.get("url"))}" target="_blank" rel="noopener noreferrer">{title}</a>'
            items.append(
                f'<li id="src-{esc(s.get("id"))}"><b>[{esc(s.get("id"))}]</b> '
                f'{title} <span class="meta">{SEP.join(meta)}</span></li>'
            )
        return (
            self.section_open("sources", "part_sources", "sources_title")
            + f'<ol class="sources">{"".join(items)}</ol></section>'
        )

    def quiz_payload(self, mcqs: List[dict]) -> dict:
        ex = self.g.get("exam", {})
        sections = [
            {"id": s.get("id"), "title": compact_tokens(s.get("title", "")), "dek": compact_tokens(s.get("dek", ""))}
            for s in ex.get("sections", [])
        ]
        items = [
            {
                "s": q.get("s"),
                "q": compact_tokens(q.get("q", "")),
                "o": [compact_tokens(o) for o in q.get("o", [])],
                "a": q.get("a"),
                "e": [compact_tokens(p) for p in as_paragraphs(q.get("e"))],
                "k": compact_tokens(q.get("k", "")),
            }
            for q in mcqs
        ]
        # The key holds only a hash of the questions: no slug or company name, because
        # other local pages opened from file:// can list this browser storage.
        digest = hashlib.sha256(json.dumps(items, sort_keys=True).encode("utf-8")).hexdigest()[:16]
        verdicts = ex.get("verdicts") or DEFAULT_VERDICTS
        label_keys = ("key_point", "correct", "wrong", "answer", "right_of", "answered", "questions")
        return {
            "storage_key": f"hiring-prep:q:{digest}",
            "sections": sections,
            "mcq": items,
            "verdicts": [{"min": v["min"], "title": v["title"], "text": v["text"]} for v in verdicts],
            "labels": {k: self.L[k] for k in label_keys},
        }

    def render(self, csp: bool = True, webfonts: bool = False) -> str:
        mcqs = final_mcqs(self.g)
        css = (ASSETS / "guide.css").read_text(encoding="utf-8")
        js = (ASSETS / "guide.js").read_text(encoding="utf-8")
        payload = json_for_script(self.quiz_payload(mcqs))
        lang = self.meta.get("lang") if isinstance(self.meta.get("lang"), str) else "en"
        head = [
            "<!doctype html>",
            f'<html lang="{esc(lang)}">',
            "<head>",
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width,initial-scale=1">',
            '<meta name="referrer" content="no-referrer">',
            '<meta name="robots" content="noindex,nofollow">',
        ]
        if csp:
            style_src = f"'sha256-{_sha256_b64(css)}'" + (" https://fonts.googleapis.com" if webfonts else "")
            font_src = " font-src https://fonts.gstatic.com;" if webfonts else ""
            policy = (
                "default-src 'none'; "
                f"script-src 'sha256-{_sha256_b64(js)}'; "
                f"style-src {style_src};{font_src} "
                "img-src data:; base-uri 'none'; form-action 'none'"
            )
            head.append(f'<meta http-equiv="Content-Security-Policy" content="{esc(policy)}">')
        head.append(f"<title>{esc(self.meta.get('title'))}</title>")
        if webfonts:
            head.append('<link rel="preconnect" href="https://fonts.googleapis.com">')
            head.append('<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>')
            head.append(f'<link rel="stylesheet" href="{esc(FONTS_URL)}">')
        head.append(f"<style>{css}</style>")
        head.append("</head>")
        footer_text = self.L["footer"].replace("{as_of}", str(self.meta.get("as_of", "")))
        body = (
            '<body><div class="wrap">'
            + self.header()
            + "<main>"
            + self.tldr()
            + self.overview()
            + self.qa()
            + self.playbook()
            + self.exam(len(mcqs))
            + self.sources()
            + "</main>"
            + f"<footer><p>{esc(footer_text)}</p></footer>"
            + "</div>"
            + f'<script type="application/json" id="quiz-data">{payload}</script>'
            + f"<script>{js}</script>"
            + "</body></html>\n"
        )
        return "\n".join(head) + "\n" + body


def render_page(guide: dict, csp: bool = True, webfonts: bool = False) -> str:
    return Page(guide).render(csp=csp, webfonts=webfonts)


def build(
    guide_path: Path,
    out_dir: Path,
    output: Optional[Path] = None,
    csp: bool = True,
    webfonts: bool = False,
    today: Optional[date] = None,
) -> Path:
    """Validate, render and write the page. Raises ValueError on any problem."""
    guide = load_guide(guide_path)
    rep = validate(guide, today)
    if rep.errors:
        raise ValueError("validation failed:\n  " + "\n  ".join(rep.errors))
    target = safe_output_path(out_dir, output, guide["meta"]["slug"])
    html_text = render_page(guide, csp=csp, webfonts=webfonts)
    make_private_dir(target.parent)
    write_private(target, html_text)  # mode 0600, never follows a symlink at the target
    return target


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Build the interview prep HTML page from guide.json")
    ap.add_argument("guide", type=Path)
    ap.add_argument("-o", "--output", type=Path, help="output file, must be inside --out-dir (default: <out-dir>/<slug>.html)")
    ap.add_argument("--out-dir", type=Path, default=Path("out"), help="output folder (default: ./out)")
    ap.add_argument("--webfonts", action="store_true", help="load Google Fonts (off by default: no third-party requests)")
    ap.add_argument("--no-csp", action="store_true", help="omit the Content-Security-Policy meta tag (only for hosts that inject their own scripts)")
    ap.add_argument("--today", help="override today's date (YYYY-MM-DD) for validation")
    args = ap.parse_args(argv)
    try:
        today = date.fromisoformat(args.today) if args.today else None
        target = build(args.guide, args.out_dir, args.output, csp=not args.no_csp, webfonts=args.webfonts, today=today)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
