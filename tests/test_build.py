import base64
import hashlib
import html
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

from helpers import EXAMPLE, SCRIPTS, TODAY, example_guide

import build_guide
from guide_lib import compact_tokens, render_inline, safe_output_path

IMG = "<img src=x onerror=alert(1)>"
BREAKOUT = "</script><script>alert(1)</script>"
JSON_OPEN = '<script type="application/json" id="quiz-data">'


def quiz_json(html_text):
    start = html_text.index(JSON_OPEN) + len(JSON_OPEN)
    end = html_text.index("</script>", start)
    return json.loads(html_text[start:end])


def poisoned_guide():
    g = example_guide()
    q = g["exam"]["mcq"][0]
    q["q"] = f"{IMG} {BREAKOUT} Which one?"
    q["o"][1] = BREAKOUT
    q["o"][2] = IMG
    q["e"][0] = f"Explanation {IMG} {BREAKOUT}"
    q["k"] = BREAKOUT
    g["exam"]["sections"][0]["title"] = BREAKOUT
    g["tldr"][0] = f"{IMG} {BREAKOUT}"
    g["qa"][0]["items"][0]["q"] = IMG
    g["qa"][0]["items"][0]["a"] = [BREAKOUT]
    g["overview"]["what_it_is"][0] = f'{IMG} "quoted" \'single\' {BREAKOUT}'
    g["overview"]["competitors"]["rows"][0][1] = IMG
    g["playbook"]["star_stories"][0]["action"] = BREAKOUT
    g["sources"][0]["title"] = IMG
    g["meta"]["title"] = f"{IMG} title"
    g["meta"]["dek"] = BREAKOUT
    return g


class BuildEscaping(unittest.TestCase):
    def setUp(self):
        self.guide = poisoned_guide()
        self.html = build_guide.render_page(self.guide)

    def test_only_our_two_script_tags(self):
        self.assertEqual(len(re.findall(r"<script\b", self.html, re.I)), 2)
        self.assertEqual(self.html.count("</script>"), 2)
        self.assertNotIn("<script>alert", self.html)

    def test_no_injected_elements_or_handlers(self):
        self.assertNotIn("<img", self.html.lower())
        self.assertIsNone(re.search(r"<[a-z][^>]*\son\w+\s*=", self.html, re.I))
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", self.html)
        self.assertIn("&lt;/script&gt;&lt;script&gt;alert(1)&lt;/script&gt;", self.html)

    def test_quiz_json_round_trips_payload_as_text(self):
        data = quiz_json(self.html)
        item = data["mcq"][0]
        self.assertEqual(item["q"], f"{IMG} {BREAKOUT} Which one?")
        self.assertIn(BREAKOUT, item["o"])
        self.assertIn(IMG, item["o"])
        self.assertEqual(item["k"], BREAKOUT)
        self.assertEqual(data["sections"][0]["title"], BREAKOUT)
        raw = self.html[self.html.index(JSON_OPEN) + len(JSON_OPEN):]
        raw = raw[: raw.index("</script>")]
        self.assertNotIn("<", raw)
        self.assertNotIn(">", raw)

    def test_quotes_escaped_in_text(self):
        self.assertIn("&quot;quoted&quot;", self.html)
        self.assertIn("&#x27;single&#x27;", self.html)

    def test_page_script_never_uses_html_sinks(self):
        js = (SCRIPTS / "assets" / "guide.js").read_text(encoding="utf-8")
        for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
            self.assertNotIn(sink, js, sink)


class BuildLinks(unittest.TestCase):
    def test_safe_markup(self):
        out = render_inline("**b** *i* `c<d>` [t](https://e.example/p?q=1&r=2)")
        self.assertIn("<strong>b</strong>", out)
        self.assertIn("<em>i</em>", out)
        self.assertIn("<code>c&lt;d&gt;</code>", out)
        self.assertIn('<a href="https://e.example/p?q=1&amp;r=2" target="_blank" rel="noopener noreferrer">t</a>', out)

    def test_dangerous_schemes_dropped(self):
        for url in ("javascript:alert(1)", "JaVaScRiPt:alert(1)", "data:text/html,x", "vbscript:x", "file:///etc/passwd", "//evil.example", "https://u:p@evil.example/"):
            out = render_inline(f"[click]({url})")
            self.assertEqual(out, "click", url)
            self.assertEqual(compact_tokens(f"[click]({url})"), "click", url)

    def test_attribute_breakout_in_url_is_escaped(self):
        out = render_inline('[x](https://ok.example/a"onmouseover="alert(1))')
        self.assertNotIn('"onmouseover', out)
        self.assertIn("&quot;onmouseover=&quot;", out)

    def test_javascript_link_never_reaches_page(self):
        g = example_guide()
        g["tldr"][0] += " [a](javascript:alert(1))"
        g["exam"]["mcq"][0]["e"][0] += " [b](javascript:alert(2))"
        g["sources"][0]["url"] = "javascript:alert(3)"
        html_text = build_guide.render_page(g)  # render without validation on purpose
        self.assertNotIn("javascript:", html_text.lower())

    def test_links_get_noopener(self):
        html_text = build_guide.render_page(example_guide())
        for tag in re.findall(r"<a\s[^>]*href=\"https?://[^>]*>", html_text):
            self.assertIn('target="_blank"', tag)
            self.assertIn('rel="noopener noreferrer"', tag)


class BuildPaths(unittest.TestCase):
    def test_bad_slug_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            for slug in ("../x", "x/../../y", "X", ""):
                with self.assertRaises(ValueError, msg=slug):
                    safe_output_path(Path(tmp), None, slug)
            g = example_guide()
            g["meta"]["slug"] = "../x"
            p = Path(tmp) / "g.json"
            p.write_text(json.dumps(g), encoding="utf-8")
            with self.assertRaises(ValueError):
                build_guide.build(p, Path(tmp) / "out", today=TODAY)

    def test_output_outside_folder_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            for target in (Path(tmp) / "elsewhere" / "x.html", out / ".." / "x.html", Path("/tmp/x.html")):
                with self.assertRaises(ValueError, msg=str(target)):
                    build_guide.build(EXAMPLE, out, target, today=TODAY)

    def test_symlink_escape_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            out.mkdir()
            outside = Path(tmp) / "outside.html"
            outside.write_text("keep me", encoding="utf-8")
            os.symlink(outside, out / "link.html")
            with self.assertRaises(ValueError):
                build_guide.build(EXAMPLE, out, out / "link.html", today=TODAY)
            self.assertEqual(outside.read_text(encoding="utf-8"), "keep me")

    def test_bad_output_name_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            for name in ("x.htm", "X.html", "a b.html", ".html"):
                with self.assertRaises(ValueError, msg=name):
                    build_guide.build(EXAMPLE, out, out / name, today=TODAY)

    def test_build_writes_inside_folder_and_is_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            first = build_guide.build(EXAMPLE, out, today=TODAY)
            self.assertEqual(first.parent, out.resolve())
            self.assertEqual(first.name, "quillmesh-devrel-lead.html")
            a = first.read_bytes()
            second = build_guide.build(EXAMPLE, out, today=TODAY)
            self.assertEqual(a, second.read_bytes())

    def test_validation_errors_stop_the_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            g = example_guide()
            g["exam"]["mcq"][0]["a"] = 9
            p = Path(tmp) / "g.json"
            p.write_text(json.dumps(g), encoding="utf-8")
            with self.assertRaises(ValueError):
                build_guide.build(p, Path(tmp) / "out", today=TODAY)
            self.assertFalse((Path(tmp) / "out").exists())


class BuildPage(unittest.TestCase):
    def setUp(self):
        self.html = build_guide.render_page(example_guide())

    def test_csp_hashes_match_inline_code(self):
        csp = html.unescape(re.search(r'http-equiv="Content-Security-Policy" content="([^"]+)"', self.html).group(1))
        js = re.search(r"<script>(.*?)</script>", self.html, re.S).group(1)
        css = re.search(r"<style>(.*?)</style>", self.html, re.S).group(1)
        for code in (js, css):
            digest = base64.b64encode(hashlib.sha256(code.encode("utf-8")).digest()).decode()
            self.assertIn(f"sha256-{digest}", csp)
        self.assertIn("default-src 'none'", csp)

    def test_no_third_party_requests_by_default(self):
        self.assertNotIn("fonts.googleapis.com", self.html)
        with_fonts = build_guide.render_page(example_guide(), webfonts=True)
        self.assertIn("fonts.googleapis.com", with_fonts)

    def test_theme_variables_and_dark_mode(self):
        self.assertIn('@media (prefers-color-scheme: dark)', self.html)
        self.assertIn(':root:not([data-theme="light"])', self.html)
        self.assertIn(':root[data-theme="dark"]', self.html)

    def test_sections_and_a11y_hooks(self):
        for anchor in ('id="tldr"', 'id="overview"', 'id="qa"', 'id="playbook"', 'id="exam"', 'id="sources"'):
            self.assertIn(anchor, self.html)
        self.assertIn('aria-live="polite"', self.html)
        self.assertIn('role="progressbar"', self.html)
        self.assertIn('id="studyBtn"', self.html)
        self.assertIn('id="resetBtn"', self.html)

    def test_storage_key_is_namespaced(self):
        key = quiz_json(self.html)["storage_key"]
        self.assertRegex(key, r"^hiring-prep:quillmesh-devrel-lead:[0-9a-f]{10}$")

    def test_no_forbidden_dashes_in_output(self):
        self.assertIsNone(re.search("[\u2012\u2013\u2014\u2015]", self.html))


if __name__ == "__main__":
    unittest.main()
