# Writing questions that teach

The test exists to make the candidate better in the room, not to show off trivia. Each question should change what the candidate will say.

## Multiple-choice questions

**Shape**: `{ "s": section id, "q": question, "o": [4 options], "a": index of the correct option, "e": [2 short paragraphs], "k": key point, "d": 1 to 3 }`.

### The rules

1. **Exactly one defensible answer.** If an expert could argue for a second option, rewrite the distractor. Avoid "best" unless the explanation proves why the others are worse.
2. **Distractors come from real confusions.** The stale number, the old product name, the competitor's mechanism, the definition people mix up, the inflated total. A good distractor is something a careless candidate would actually say.
3. **No "all of the above" or "none of the above"**, no "A and C". Options are shuffled, so these break (the validator rejects them).
4. **Never refer to options by position or letter** in the explanation or key point ("the second option", "answer C"). The order is shuffled at build time. Quote the option text instead: `The answer "per seat" is the classic trap`.
5. **Similar length and grammar for all four options.** The correct answer must not be the longest or the only precise one (the validator warns when it is much longer).
6. **One idea per question.** No double negatives, no "which is NOT" unless the trap is exactly that.
7. **Numbers in options are realistic neighbours**: the right figure, the claimed figure, a figure from a different denominator, an outdated figure.

### Explanations

Two short paragraphs:
1. **Why the answer is right**, in plain words, with the mechanism or the source.
2. **A concrete example**, then why the tempting distractor is wrong.

Then the **key point**: one line the candidate can say or remember in the interview. Tie it to the resume when relevant ("Your 3 days to 40 minutes story proves you already work this way").

### Difficulty mix

- `d: 1` basics a recruiter could ask: about 30 percent.
- `d: 2` mechanism, numbers, trade-offs: about 45 percent.
- `d: 3` scenarios, judgement, traps: about 25 percent.

Order sections from the company basics to the candidate's story. Typical sections: product and mechanism, business and numbers, market and competitors, the role's craft, the candidate in the room.

### Interview value over trivia

Ask: "Would a sharp interviewer care whether the candidate knows this?" Founding dates and office addresses rarely matter. The pricing model, the moat, the latest launch, the open controversy, the metric the role owns: those matter.

### Example

Weak: "In what year was the company founded? 2020 / 2021 / 2022 / 2023."

Strong: "Which download figure can you quote as verified?" with the registry figure, the blog's inflated claim, a lifetime number from a slide, and the star count confused for downloads. The explanation teaches the claimed versus verified habit; the key point gives the sentence to say.

## Quick Q&A

- Short questions an interviewer would really ask, grouped by theme: ecosystem and product, the role's craft, the company.
- Model answers of 2 to 5 sentences: conclusion first, then evidence, then a number or an example.
- Write answers the candidate can say out loud. No bullet dumps.

## Open questions (exam part A)

- Prompts that need a spoken answer: the 30-second pitch, "walk me through", "what would you do in your first 90 days", "how would you handle" a real controversy.
- Model answer in quotes or as a structure, then one line on why it works.
- Include at least one question that uses a STAR story from the playbook and one about the company's current controversy or risk.

## Verdict bands

Three bands in `exam.verdicts` with `min` as a fraction: for example 0.85 ready, 0.6 solid base, 0 not yet. Each says what to do next, not just a grade.
