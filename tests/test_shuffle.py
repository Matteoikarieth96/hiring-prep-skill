import copy
import unittest

from helpers import example_guide

from guide_lib import XorShift32, balanced_targets, final_mcqs, letter_counts, longest_run, shuffle_mcqs


def make_questions(n):
    return [
        {"s": "x", "q": f"Question {i}", "o": [f"right {i}", f"wrong a {i}", f"wrong b {i}", f"wrong c {i}"], "a": 0, "e": ["e"], "k": "k"}
        for i in range(n)
    ]


class ShuffleTests(unittest.TestCase):
    def test_deterministic(self):
        qs = make_questions(40)
        self.assertEqual(shuffle_mcqs(qs, 1234), shuffle_mcqs(qs, 1234))

    def test_different_seeds_differ(self):
        qs = make_questions(16)
        a = [q["a"] for q in shuffle_mcqs(qs, 1)]
        b = [q["a"] for q in shuffle_mcqs(qs, 2)]
        self.assertNotEqual(a, b)

    def test_correct_answer_and_options_preserved(self):
        qs = make_questions(30)
        for orig, new in zip(qs, shuffle_mcqs(qs, 99)):
            self.assertEqual(new["o"][new["a"]], orig["o"][orig["a"]])
            self.assertEqual(sorted(new["o"]), sorted(orig["o"]))

    def test_input_not_mutated(self):
        qs = make_questions(12)
        before = copy.deepcopy(qs)
        shuffle_mcqs(qs, 7)
        self.assertEqual(qs, before)

    def test_balance_no_letter_above_35_percent(self):
        for seed in (1, 42, 20261008):
            for n in range(8, 160):
                counts = letter_counts(shuffle_mcqs(make_questions(n), seed))
                self.assertEqual(sum(counts), n)
                self.assertLessEqual(max(counts) / n, 0.35, (seed, n, counts))
                self.assertLessEqual(max(counts) - min(counts), 1, (seed, n, counts))

    def test_no_letter_three_times_in_a_row(self):
        for seed in range(1, 30):
            for n in (8, 16, 25, 50, 80, 100, 150):
                self.assertLessEqual(longest_run(balanced_targets(n, XorShift32(seed))), 2, (seed, n))

    def test_example_guide_is_balanced(self):
        counts = letter_counts(final_mcqs(example_guide()))
        self.assertEqual(counts, [4, 4, 4, 4])

    def test_shuffle_can_be_disabled(self):
        g = example_guide()
        g["meta"]["shuffle"] = False
        self.assertEqual([q["a"] for q in final_mcqs(g)], [q["a"] for q in g["exam"]["mcq"]])


if __name__ == "__main__":
    unittest.main()
