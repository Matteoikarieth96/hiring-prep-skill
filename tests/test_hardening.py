"""Regression tests for the security review findings, one class per item."""
import http.server
import io
import json
import os
import shutil
import stat
import struct
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.error
import zipfile
from pathlib import Path
from unittest import mock

from helpers import EXAMPLE, ROOT, TODAY, example_guide

import ats_check
import build_guide
import personal_data
import qa_check
import resume_text
import validate
from guide_lib import write_private

EN_DASH = chr(0x2013)
NB_HYPHEN = chr(0x2011)
HYPHEN = chr(0x2010)
ZWSP = chr(0x200B)
FULLWIDTH_AT = chr(0xFF20)
RLO = chr(0x202E)

# (sample, a fragment that must disappear after redaction)
ERROR_SAMPLES = [
    ("mario.rossi [at] gmail [dot] com", "gmail"),
    ("mario.rossi (at) gmail (dot) com", "gmail"),
    ("mario.rossi {at} gmail {dot} com", "gmail"),
    ("mario.rossi at gmail dot com", "gmail"),
    ("347 1234567", "1234567"),
    ("06 1234 5678", "5678"),
    ("0039 347 1234567", "1234567"),
    ("347" + EN_DASH + "1234567", "1234567"),
    ("06" + NB_HYPHEN + "1234" + NB_HYPHEN + "5678", "5678"),
    ("+39 347" + HYPHEN + "123" + HYPHEN + "4567", "4567"),
    ("Via Roma 12, 00184 Roma", "Via Roma 12"),
    ("Nato a Roma il 3 marzo 1990", "1990"),
    ("Born: 1 May 1990", "1990"),
    ("Data di nascita: 01/01/1990", "1990"),
    ("RSSMRA80A01H501U", "RSSMRA80A01H501U"),
    ("lnkd.in/abc123", "abc123"),
    ("linkedin.com/pub/mario-rossi/1/2/3", "mario-rossi"),
    ("mario.rossi" + ZWSP + "@gmail.com", "gmail"),
    ("mario" + FULLWIDTH_AT + "gmail.com", "gmail"),
]
WARNING_SAMPLES = [("@mariorossi", "mariorossi"), ("mariorossi.eth", "mariorossi")]
REDACT_ONLY_SAMPLES = [("Portfolio: mariorossi.dev", "mariorossi.dev")]
HEADER_ONLY_SAMPLES = [("mariorossi.dev | https://mario-rossi.example/about", "mario")]
BENIGN = [
    "Founded in 2022, 182,000 downloads in September, 2020-2023, +12% growth, $22M, v2.7.1.",
    "Read the docs at docs.quillmesh.example before the call.",
    "The project was born in 2022 at a hackathon.",
    "Look at the dot com era for context.",
    "300.000.000 utenti e 1,000,000,000 token.",
    "Access via Kafka 3, 2024 release; Q3 2025; 01/10/2026; 2026-10-08.",
    "Answer via email 3 times a week.",
]


def guide_with(text):
    g = example_guide()
    g["tldr"][0] = text
    return g


class M1ContactDetails(unittest.TestCase):
    def test_each_format_is_redacted_and_career_text_kept(self):
        for sample, needle in ERROR_SAMPLES + WARNING_SAMPLES + REDACT_ONLY_SAMPLES:
            out = resume_text.redact(f"# Sample Person\nSummary line\n## Experience\n{sample}\nBuilt a Kafka pipeline.\n")
            self.assertNotIn(needle, out, sample)
            self.assertIn("Built a Kafka pipeline.", out, sample)

    def test_header_block_links_and_domains_redacted(self):
        for sample, needle in HEADER_ONLY_SAMPLES:
            out = resume_text.redact(f"Sample Person\n{sample}\n\n## Experience\nShipped docs at quillmesh.example.\n")
            self.assertNotIn(needle, out)
            self.assertIn("Shipped docs at quillmesh.example.", out)  # career links outside the header stay

    def test_each_format_is_an_error_in_the_validator(self):
        for sample, _ in ERROR_SAMPLES:
            errs = validate.validate(guide_with(f"Contact: {sample} today."), TODAY).errors
            self.assertTrue(any("tldr[0]" in e and "personal data" in e for e in errs), sample)

    def test_handles_and_ens_are_warnings(self):
        for sample, _ in WARNING_SAMPLES:
            rep = validate.validate(guide_with(f"Follow {sample} for news."), TODAY)
            self.assertEqual(rep.errors, [], sample)
            self.assertTrue(any("tldr[0]" in w for w in rep.warnings), sample)

    def test_split_markup_email_is_flagged(self):
        for sample in ("mario.rossi**@**gmail.com", "mario.rossi`@`gmail.com", "mario.rossi*@*gmail.com",
                       "[mario.rossi](https://ok.example)@gmail.com"):
            errs = validate.validate(guide_with(sample), TODAY).errors
            self.assertTrue(any("email" in e for e in errs), sample)

    def test_no_false_positives_on_ordinary_text(self):
        for text in BENIGN:
            self.assertEqual(personal_data.detect(text), ([], []), text)
        rep = validate.validate(example_guide(), TODAY)
        self.assertEqual((rep.errors, rep.warnings), ([], []))


def zip_with(path, data, compression=zipfile.ZIP_DEFLATED):
    with zipfile.ZipFile(path, "w", compression=compression) as zf:
        zf.writestr("word/document.xml", data)


class M2DocxBomb(unittest.TestCase):
    def test_bzip2_and_lzma_parts_refused_quickly(self):
        body = b"<w:document>" + b" " * 3_000_000 + b"</w:document>"
        for comp in (zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA):
            with tempfile.TemporaryDirectory() as tmp:
                p = Path(tmp) / "cv.docx"
                zip_with(p, body, comp)
                start = time.monotonic()
                with self.assertRaises(resume_text.ResumeError):
                    resume_text.extract(p)
                self.assertLess(time.monotonic() - start, 1.0)

    def test_lying_size_header_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "cv.docx"
            zip_with(p, b"<x>" + b"a" * 2_000_000 + b"</x>")
            raw = bytearray(p.read_bytes())
            struct.pack_into("<I", raw, 22, 100)  # local header: uncompressed size
            cd = raw.find(b"PK\x01\x02")
            struct.pack_into("<I", raw, cd + 24, 100)  # central directory: uncompressed size
            p.write_bytes(bytes(raw))
            start = time.monotonic()
            with self.assertRaises(resume_text.ResumeError):
                resume_text.docx_text(p, max_xml=1000)
            self.assertLess(time.monotonic() - start, 1.0)

    def test_streaming_cap_does_not_trust_declared_size(self):
        info = zipfile.ZipInfo("word/document.xml")
        info.compress_type = zipfile.ZIP_DEFLATED
        info.file_size = 10  # the header claims 10 bytes
        fake = mock.Mock()
        fake.getinfo.return_value = info
        fake.open.return_value = io.BytesIO(b"a" * 1_000_000)  # the stream yields far more
        with self.assertRaisesRegex(resume_text.ResumeError, "too large"):
            resume_text._read_part_capped(fake, "word/document.xml", 100_000)


class M3ProcedureOrder(unittest.TestCase):
    def setUp(self):
        self.skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")

    def test_resume_is_read_after_all_network_steps(self):
        steps = self.skill.index("## Step 1.")
        first_resume_script = self.skill.index("resume_text.py", steps)
        self.assertGreater(first_resume_script, self.skill.index("## Step 6."))
        for network_step in ("## Step 2.", "## Step 3.", "## Step 4.", "## Step 5."):
            self.assertLess(self.skill.index(network_step), first_resume_script)
        self.assertGreater(self.skill.index("ats_check.py", steps), steps)
        self.assertLess(self.skill.index("ats_check.py", steps), self.skill.index("## Step 6."))

    def test_rules_are_explicit(self):
        self.assertIn("never goes into a URL, query string, header, search query", self.skill)
        self.assertIn("no network tool is used", self.skill)


class L4Utf16Doctype(unittest.TestCase):
    def test_utf16_document_refused(self):
        xml = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE x [<!ENTITY a "aaaaaaaaaa">]><x>&a;&a;</x>'
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "cv.docx"
            zip_with(p, xml.encode("utf-16"))
            with self.assertRaises(resume_text.ResumeError):
                resume_text.extract(p)

    def test_doctype_after_long_comment_refused_by_parser(self):
        xml = "<?xml version=\"1.0\"?><!--" + "c" * 6000 + "--><!DOCTYPE x SYSTEM \"x.dtd\"><x/>"
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "cv.docx"
            zip_with(p, xml.encode("utf-8"))
            with self.assertRaisesRegex(resume_text.ResumeError, "DOCTYPE"):
                resume_text.extract(p)

    def test_other_declared_encoding_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "cv.docx"
            zip_with(p, b'<?xml version="1.0" encoding="ISO-8859-1"?><x/>')
            with self.assertRaises(resume_text.ResumeError):
                resume_text.extract(p)


class L5PrivateWrites(unittest.TestCase):
    def test_resume_output_symlink_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "cv.md"
            src.write_text("Developer Advocate, 2023 to present\n", encoding="utf-8")
            victim = Path(tmp) / "victim.txt"
            victim.write_text("keep me", encoding="utf-8")
            link = Path(tmp) / "work" / "resume.txt"
            link.parent.mkdir()
            os.symlink(victim, link)
            with mock.patch("sys.stdout"), mock.patch("sys.stderr"):
                self.assertEqual(resume_text.main([str(src), "-o", str(link)]), 2)
            self.assertEqual(victim.read_text(encoding="utf-8"), "keep me")

    def test_resume_output_is_0600_in_0700_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "cv.md"
            src.write_text("Developer Advocate\n", encoding="utf-8")
            out = Path(tmp) / "newwork" / "resume.txt"
            with mock.patch("sys.stdout"):
                self.assertEqual(resume_text.main([str(src), "-o", str(out)]), 0)
            self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(out.parent.stat().st_mode), 0o700)

    def test_existing_file_reset_to_0600_and_symlink_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "a.html"
            f.write_text("old", encoding="utf-8")
            os.chmod(f, 0o644)
            write_private(f, "new")
            self.assertEqual(stat.S_IMODE(f.stat().st_mode), 0o600)
            os.symlink(f, Path(tmp) / "b.html")
            with self.assertRaises(ValueError):
                write_private(Path(tmp) / "b.html", "x")
            self.assertEqual(f.read_text(encoding="utf-8"), "new")

    def test_build_output_is_0600(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = build_guide.build(EXAMPLE, Path(tmp) / "out", today=TODAY)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)

    def test_qa_screenshots_use_private_writer(self):
        src = (ROOT / "scripts" / "qa_check.py").read_text(encoding="utf-8")
        self.assertIn("write_private(shots / name", src)


class L6CurlArguments(unittest.TestCase):
    def test_curl_reads_no_curlrc_and_follows_no_redirects(self):
        seen = {}

        def fake_run(cmd, **_kw):
            seen["cmd"] = cmd
            return subprocess.CompletedProcess(cmd, 0, stdout=b'{"jobs": []}\n200', stderr=b"")

        with mock.patch.object(ats_check.shutil, "which", return_value="/usr/bin/curl"), \
                mock.patch.object(ats_check.subprocess, "run", side_effect=fake_run):
            status, body = ats_check.curl_get("https://boards-api.greenhouse.io/v1/boards/example/jobs")
        cmd = seen["cmd"]
        self.assertEqual(cmd[0], "curl")
        self.assertEqual(cmd[1], "-q")
        self.assertEqual(cmd[cmd.index("--max-redirs") + 1], "0")
        self.assertEqual(cmd[cmd.index("--proto-redir") + 1], "=https")
        self.assertEqual(cmd[cmd.index("--proto") + 1], "=https")
        self.assertNotIn("-k", cmd)
        self.assertNotIn("--insecure", cmd)
        self.assertEqual(status, 200)


class _RedirectHandler(http.server.BaseHTTPRequestHandler):
    hits = []

    def log_message(self, *_a):
        pass

    def do_GET(self):
        type(self).hits.append(self.path)
        if self.path == "/start":
            self.send_response(302)
            self.send_header("Location", "/target")
            self.end_headers()
        else:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"{}")


class L7Redirects(unittest.TestCase):
    def test_redirect_is_not_followed(self):
        _RedirectHandler.hits = []
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _RedirectHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                ats_check.OPENER.open(f"http://127.0.0.1:{srv.server_address[1]}/start", timeout=5)
            self.assertEqual(ctx.exception.code, 302)
            ctx.exception.close()
            self.assertEqual(_RedirectHandler.hits, ["/start"])
        finally:
            srv.shutdown()
            srv.server_close()

    def test_non_https_url_refused(self):
        self.assertEqual(ats_check.http_get("http://boards-api.greenhouse.io/v1/boards/x/jobs"), (0, None))


class L8StorageKey(unittest.TestCase):
    def test_storage_key_has_no_slug_or_company(self):
        html_text = build_guide.render_page(example_guide())
        start = html_text.index('id="quiz-data">') + len('id="quiz-data">')
        key = json.loads(html_text[start:html_text.index("</script>", start)])["storage_key"]
        self.assertRegex(key, r"^hiring-prep:q:[0-9a-f]{16}$")
        self.assertNotIn("quillmesh", key.lower())


class L9RegexTiming(unittest.TestCase):
    def test_scans_stay_fast_on_adversarial_input(self):
        inputs = [
            "a" * 40000, "a." * 20000, "a@" * 20000, "1 " * 20000, "+1 " * 13000, "0" * 40000,
            "via " * 10000, " " * 40000, "[at] " * 8000, "a [at] b [dot] " * 2500, "@" * 40000,
            "a at b dot " * 4000, "x" * 39990 + "@mail.com", "1-" * 20000,
        ]
        for text in inputs:
            start = time.monotonic()
            personal_data.detect(text)
            personal_data.redact(text)
            self.assertLess(time.monotonic() - start, 1.5, text[:20])


class L10Gitignore(unittest.TestCase):
    def setUp(self):
        git = shutil.which("git")
        if not git:
            self.skipTest("git not installed")
        probe = subprocess.run([git, "-C", str(ROOT), "rev-parse", "--is-inside-work-tree"], capture_output=True)
        if probe.returncode != 0:
            self.skipTest("not a git work tree")
        self.git = git

    def ignored(self, path):
        r = subprocess.run([self.git, "-C", str(ROOT), "check-ignore", "--no-index", "-q", path], capture_output=True)
        return r.returncode == 0

    def test_cv_names_and_documents_ignored(self):
        for name in ("CV_Mario_Rossi.pdf", "Mario_Rossi_CV.pdf", "mario-cv.docx", "my_cv.md", "Resume 2026.pdf",
                     "cover-letter.docx", "notes/guide.json", "curriculum-vitae.odt", "CV.txt", "letter.rtf",
                     "work/resume.txt", "evidence/business.md", "out/x.html"):
            self.assertTrue(self.ignored(name), name)

    def test_repository_files_kept(self):
        for name in ("examples/fictional/resume.md", "examples/fictional/guide.json", "scripts/resume_text.py",
                     "templates/guide.template.json", "examples/fictional/out/quillmesh-devrel-lead.html",
                     "scripts/personal_data.py", "tests/test_hardening.py"):
            self.assertFalse(self.ignored(name), name)


class L11PdfFallback(unittest.TestCase):
    def test_fallback_routes_text_through_redaction(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("resume_text.py work/resume-raw.txt -o work/resume.txt", skill)
        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp) / "resume-raw.txt"
            raw.write_text("Developer Advocate\nmario.rossi [at] gmail [dot] com\n", encoding="utf-8")
            self.assertNotIn("gmail", resume_text.redact(resume_text.extract(raw)))


class L12ReadmeWording(unittest.TestCase):
    def test_readme_does_not_overstate_privacy(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertNotIn("stays on your machine", readme)
        self.assertIn("model provider", readme)


class InfoItems(unittest.TestCase):
    def test_ats_output_strips_bidi_and_format_characters(self):
        self.assertNotIn(RLO, ats_check.clean("Lead" + RLO + "evil" + ZWSP))

    def test_qa_chrome_profile_and_no_file_access_flag(self):
        cmd = qa_check.chrome_command("chrome", Path("/tmp/profile-x"), ["http://127.0.0.1:1/page.html"])
        self.assertIn("--user-data-dir=/tmp/profile-x", cmd)
        self.assertNotIn("--allow-file-access-from-files", cmd)
        self.assertNotIn("--allow-file-access-from-files", (ROOT / "scripts" / "qa_check.py").read_text(encoding="utf-8").split('"""', 2)[2])

    def test_ci_checkout_does_not_persist_credentials(self):
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn("persist-credentials: false", ci)


if __name__ == "__main__":
    unittest.main()
