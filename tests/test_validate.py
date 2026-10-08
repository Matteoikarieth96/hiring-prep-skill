import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from helpers import TODAY, example_guide

import validate


def errors_of(guide):
    return validate.validate(guide, TODAY).errors


class ValidateGoodFile(unittest.TestCase):
    def test_example_passes(self):
        rep = validate.validate(example_guide(), TODAY)
        self.assertEqual(rep.errors, [])

    def test_cli_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "good.json"
            good.write_text(json.dumps(example_guide()), encoding="utf-8")
            bad_guide = example_guide()
            bad_guide["exam"]["mcq"][0]["a"] = 7
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps(bad_guide), encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(validate.main([str(good), "--today", "2026-10-08"]), 0)
                self.assertEqual(validate.main([str(bad), "--today", "2026-10-08"]), 1)

    def test_invalid_json_exits_1(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "broken.json"
            p.write_text("{not json", encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(validate.main([str(p)]), 1)


class ValidateTemplate(unittest.TestCase):
    def test_template_only_fails_on_placeholders_and_counts(self):
        path = Path(__file__).resolve().parent.parent / "templates" / "guide.template.json"
        guide = json.loads(path.read_text(encoding="utf-8"))
        errs = validate.validate(guide, TODAY).errors
        self.assertTrue(errs)
        for e in errs:
            self.assertTrue("placeholder" in e or "target_counts" in e, e)


class ValidateMcq(unittest.TestCase):
    def test_bad_answer_index(self):
        g = example_guide()
        g["exam"]["mcq"][0]["a"] = 4
        self.assertTrue(any("exam.mcq[0].a" in e for e in errors_of(g)))

    def test_boolean_answer_index(self):
        g = example_guide()
        g["exam"]["mcq"][0]["a"] = True
        self.assertTrue(any("exam.mcq[0].a" in e for e in errors_of(g)))

    def test_duplicate_options(self):
        g = example_guide()
        q = g["exam"]["mcq"][2]
        q["o"][1] = "  " + q["o"][0].upper() + " "
        self.assertTrue(any("exam.mcq[2].o" in e and "unique" in e for e in errors_of(g)))

    def test_three_options(self):
        g = example_guide()
        g["exam"]["mcq"][1]["o"].pop()
        self.assertTrue(any("exactly 4" in e for e in errors_of(g)))

    def test_empty_option(self):
        g = example_guide()
        g["exam"]["mcq"][1]["o"][3] = "   "
        self.assertTrue(any("exam.mcq[1].o" in e for e in errors_of(g)))

    def test_missing_explanation_and_key_point(self):
        g = example_guide()
        g["exam"]["mcq"][3]["e"] = []
        g["exam"]["mcq"][3]["k"] = ""
        errs = errors_of(g)
        self.assertTrue(any("exam.mcq[3].e" in e for e in errs))
        self.assertTrue(any("exam.mcq[3].k" in e for e in errs))

    def test_all_of_the_above_rejected(self):
        g = example_guide()
        g["exam"]["mcq"][5]["o"][2] = "All of the above"
        self.assertTrue(any("all/none of the above" in e for e in errors_of(g)))

    def test_positional_reference_rejected(self):
        for text in ("The second option is the trap.", "Option C confuses stars with downloads.", "The last answer is wrong."):
            g = example_guide()
            g["exam"]["mcq"][6]["e"][1] = text
            self.assertTrue(any("exam.mcq[6].e" in e and "position" in e for e in errors_of(g)), text)

    def test_unknown_section(self):
        g = example_guide()
        g["exam"]["mcq"][0]["s"] = "nope"
        self.assertTrue(any("unknown section" in e for e in errors_of(g)))

    def test_unbalanced_letters_without_shuffle(self):
        g = example_guide()
        g["meta"]["shuffle"] = False  # every authored answer is option A
        self.assertTrue(any("unbalanced" in e for e in errors_of(g)))

    def test_balanced_after_shuffle(self):
        rep = validate.validate(example_guide(), TODAY)
        self.assertFalse(any("unbalanced" in e for e in rep.errors))


class ValidateStructure(unittest.TestCase):
    def test_missing_section(self):
        g = example_guide()
        del g["playbook"]
        self.assertTrue(any(e.startswith("playbook:") for e in errors_of(g)))

    def test_count_mismatch(self):
        g = example_guide()
        g["meta"]["target_counts"]["mcq"] = 17
        self.assertTrue(any("target_counts.mcq" in e for e in errors_of(g)))
        g = example_guide()
        g["qa"][0]["items"].pop()
        self.assertTrue(any("target_counts.qa" in e for e in errors_of(g)))

    def test_bad_slug(self):
        for slug in ("../x", "Bad Slug", "", "a" * 65, "-x"):
            g = example_guide()
            g["meta"]["slug"] = slug
            self.assertTrue(any("meta.slug" in e for e in errors_of(g)), slug)

    def test_bad_as_of(self):
        g = example_guide()
        g["meta"]["as_of"] = "2026-13-01"
        self.assertTrue(any("meta.as_of" in e for e in errors_of(g)))

    def test_stale_as_of_is_warning(self):
        g = example_guide()
        g["meta"]["as_of"] = "2026-01-01"
        rep = validate.validate(g, TODAY)
        self.assertEqual(rep.errors, [])
        self.assertTrue(any("refresh" in w for w in rep.warnings))

    def test_unknown_source_reference(self):
        g = example_guide()
        g["overview"]["numbers"][0]["source"] = "S99"
        self.assertTrue(any("S99" in e for e in errors_of(g)))

    def test_number_needs_status_and_date(self):
        g = example_guide()
        g["overview"]["numbers"][0]["status"] = "probably"
        del g["overview"]["numbers"][1]["date"]
        errs = errors_of(g)
        self.assertTrue(any("numbers[0].status" in e for e in errs))
        self.assertTrue(any("numbers[1].date" in e for e in errs))

    def test_source_needs_access_date(self):
        g = example_guide()
        del g["sources"][0]["accessed"]
        self.assertTrue(any("sources[0].accessed" in e for e in errors_of(g)))

    def test_competitor_row_width(self):
        g = example_guide()
        g["overview"]["competitors"]["rows"][0].pop()
        self.assertTrue(any("competitors.rows[0]" in e for e in errors_of(g)))

    def test_placeholder_left(self):
        g = example_guide()
        g["tldr"][0] = "TODO write this"
        self.assertTrue(any("placeholder" in e for e in errors_of(g)))


class ValidateSecurityAndPrivacy(unittest.TestCase):
    def test_javascript_link_in_text(self):
        g = example_guide()
        g["tldr"][0] += " [click](javascript:alert(1))"
        self.assertTrue(any("tldr[0]" in e for e in errors_of(g)))

    def test_javascript_source_url(self):
        for url in ("javascript:alert(1)", "data:text/html,<b>x</b>", "file:///etc/passwd", "//evil.example/x", "https://user:pw@evil.example/"):
            g = example_guide()
            g["sources"][0]["url"] = url
            self.assertTrue(any("sources[0].url" in e for e in errors_of(g)), url)

    def test_data_scheme_in_text(self):
        g = example_guide()
        g["qa"][0]["items"][0]["a"][0] += " see data:text/html;base64,PHNjcmlwdD4="
        self.assertTrue(any("non-http(s)" in e for e in errors_of(g)))

    def test_email_in_content(self):
        g = example_guide()
        g["playbook"]["positioning"].append("Reach me at someone@mail.example.org any time.")
        self.assertTrue(any("email" in e for e in errors_of(g)))

    def test_phone_in_content(self):
        for phone in ("+44 20 7946 0958", "+1 (415) 555-0100", "415-555-0100", "(415) 555 0100"):
            g = example_guide()
            g["exam"]["open"][0]["a"].append(f"Call {phone} after six.")
            self.assertTrue(any("phone" in e for e in errors_of(g)), phone)

    def test_numbers_are_not_phones(self):
        g = example_guide()
        g["tldr"][1] += " $4M seed 2023, 182,000 downloads, 2020 to 2023, 2026-10-08, +12% growth, v2.7.1."
        self.assertFalse(any("phone" in e for e in errors_of(g)))

    def test_em_dash_rejected(self):
        g = example_guide()
        g["tldr"][2] = "A sentence \u2014 with an em dash."
        self.assertTrue(any("tldr[2]" in e and "dash" in e for e in errors_of(g)))

    def test_en_dash_rejected(self):
        g = example_guide()
        g["exam"]["mcq"][4]["k"] = "Years 2023\u20132025."
        self.assertTrue(any("exam.mcq[4].k" in e and "dash" in e for e in errors_of(g)))

    def test_html_in_text_is_allowed_because_it_is_escaped(self):
        g = example_guide()
        g["exam"]["mcq"][0]["q"] = "<img src=x onerror=alert(1)> what?"
        self.assertEqual(errors_of(g), [])


if __name__ == "__main__":
    unittest.main()
