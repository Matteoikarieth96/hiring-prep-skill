# Fictional example: Quillmesh, Developer Relations Lead

**Everything in this folder is invented.** Quillmesh, its product `qmc`, its investors, its competitors, the job post, the candidate, the candidate's employers, the meetup and every number are fictional. Domains end in `.example`, which is reserved for documentation and never resolves. No real company was researched.

| File | What it is |
|---|---|
| `resume.md` | the fictional candidate's resume (no contact details, on purpose) |
| `guide.json` | the complete guide data: 10 TL;DR ideas, an overview with a numbers table and a competitor table, 12 Q&A, a playbook, 4 open questions, 16 MCQs in 4 sections, 12 sources |
| `out/quillmesh-devrel-lead.html` | the page built from `guide.json` |

Rebuild it from the repository root:

```bash
python3 scripts/validate.py examples/fictional/guide.json
python3 scripts/build_guide.py examples/fictional/guide.json --out-dir examples/fictional/out
```

Open `out/quillmesh-devrel-lead.html#demo` to see the quiz with one right and one wrong answer.
