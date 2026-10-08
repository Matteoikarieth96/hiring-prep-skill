"""Tests for resume_text.py (local extraction + redaction) and ats_check.py (offline)."""
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import helpers  # noqa: F401  (path setup)

import ats_check
import resume_text

DOCX_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
    "<w:p><w:r><w:t>Sample Person</w:t></w:r></w:p>"
    "<w:p><w:r><w:t>sample.person@mail.example.org</w:t></w:r><w:r><w:tab/><w:t>+44 20 7946 0000</w:t></w:r></w:p>"
    "<w:p><w:r><w:t>Developer Advocate, 2023 to present</w:t></w:r></w:p>"
    "</w:body></w:document>"
)


def make_docx(path: Path, xml: str) -> None:
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", xml)


class ResumeTextTests(unittest.TestCase):
    def test_redacts_contact_details(self):
        text = (
            "Sample Person\n"
            "sample.person@mail.example.org | +44 20 7946 0321 | linkedin.com/in/sample-person\n"
            "12 Example Street, Sampletown\n"
            "Date of birth: 1 January 1990\n"
            "Cut onboarding from 3 days to 40 minutes in 2024 to 2025.\n"
        )
        out = resume_text.redact(text)
        self.assertNotIn("@", out)
        self.assertNotIn("7946 0321", out)
        self.assertNotIn("linkedin.com/in", out)
        self.assertNotIn("Example Street", out)
        self.assertNotIn("1990", out)
        self.assertIn("3 days to 40 minutes in 2024 to 2025", out)

    def test_docx_extraction(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "cv.docx"
            make_docx(p, DOCX_XML)
            text = resume_text.extract(p)
            self.assertIn("Developer Advocate, 2023 to present", text)
            self.assertIn("Sample Person", text)
            red = resume_text.redact(text)
            self.assertNotIn("mail.example.org", red)
            self.assertNotIn("7946", red)

    def test_docx_with_entities_rejected(self):
        evil = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]><x>&b;</x>'
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "cv.docx"
            make_docx(p, evil)
            with self.assertRaises(resume_text.ResumeError):
                resume_text.extract(p)

    def test_docx_size_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "cv.docx"
            make_docx(p, DOCX_XML)
            with self.assertRaises(resume_text.ResumeError):
                resume_text.docx_text(p, max_xml=10)

    def test_not_a_docx(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "cv.docx"
            p.write_text("plain text pretending", encoding="utf-8")
            with self.assertRaises(resume_text.ResumeError):
                resume_text.extract(p)

    def test_unsupported_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "cv.exe"
            p.write_bytes(b"MZ")
            with self.assertRaises(resume_text.ResumeError):
                resume_text.extract(p)


class AtsCheckTests(unittest.TestCase):
    def fake_fetch(self, responses):
        calls = []

        def fetch(url):
            calls.append(url)
            for host, resp in responses.items():
                if host in url:
                    return resp
            return 404, None

        return fetch, calls

    def test_invalid_slug_rejected(self):
        for bad in ("../x", "a/b", "x?y=1", "", "a b"):
            with self.assertRaises(ValueError, msg=bad):
                ats_check.check(bad, fetch=lambda u: (404, None))

    def test_not_found_everywhere(self):
        fetch, calls = self.fake_fetch({})
        res = ats_check.check("example-org", "developer relations", fetch=fetch)
        self.assertEqual({r["status"] for r in res.values()}, {"not found"})
        self.assertEqual(len(calls), 3)
        self.assertTrue(all(c.startswith("https://") for c in calls))

    def test_match_on_greenhouse(self):
        body = json.dumps({"jobs": [
            {"title": "Developer Relations Lead, EMEA", "location": {"name": "Remote"}, "absolute_url": "https://boards.greenhouse.io/example/jobs/1"},
            {"title": "Account Executive", "location": {"name": "Remote"}, "absolute_url": "https://boards.greenhouse.io/example/jobs/2"},
            {"title": "Developer Relations Engineer", "location": {"name": "Remote"}, "absolute_url": "javascript:alert(1)"},
        ]}).encode()
        fetch, _ = self.fake_fetch({"greenhouse.io": (200, body)})
        res = ats_check.check("example-org", "developer relations lead", fetch=fetch)
        self.assertEqual(res["greenhouse"]["status"], "board found")
        self.assertEqual([j["title"] for j in res["greenhouse"]["jobs"]], ["Developer Relations Lead, EMEA"])
        self.assertEqual(res["greenhouse"]["total"], 2)  # the javascript: URL is dropped
        self.assertEqual(res["lever"]["status"], "not found")

    def test_lever_and_ashby_parsing(self):
        lever = json.dumps([{"text": "DevRel Lead", "categories": {"location": "Lisbon"}, "hostedUrl": "https://jobs.lever.co/example/1"}]).encode()
        ashby = json.dumps({"jobs": [
            {"title": "DevRel Lead", "location": "Remote", "jobUrl": "https://jobs.ashbyhq.com/example/1", "isListed": True},
            {"title": "DevRel Lead (unlisted)", "location": "Remote", "jobUrl": "https://jobs.ashbyhq.com/example/2", "isListed": False},
        ]}).encode()
        fetch, _ = self.fake_fetch({"lever.co": (200, lever), "ashbyhq.com": (200, ashby)})
        res = ats_check.check("example-org", "devrel", fetch=fetch)
        self.assertEqual(len(res["lever"]["jobs"]), 1)
        self.assertEqual(len(res["ashby"]["jobs"]), 1)

    def test_control_characters_stripped(self):
        body = json.dumps({"jobs": [{"title": "Lead\x1b[31m\nEvil", "location": {"name": "x"}, "absolute_url": "https://ok.example/1"}]}).encode()
        fetch, _ = self.fake_fetch({"greenhouse.io": (200, body)})
        res = ats_check.check("example-org", fetch=fetch)
        self.assertNotIn("\x1b", res["greenhouse"]["jobs"][0]["title"])
        self.assertNotIn("\n", res["greenhouse"]["jobs"][0]["title"])


if __name__ == "__main__":
    unittest.main()
