# Intake

Goal: collect what the guide needs in at most two rounds, then confirm a short plan before any research.

## How to ask

- With the `AskUserQuestion` tool: at most 4 questions per call, 2 to 4 options each, recommended option first with "(Recommended)" in the label. The user can always answer "Other" in their own words.
- Without it: one numbered list in plain text, in the user's language.
- Skip what the user already said or what the attached files answer (a job post link answers the role; a resume file answers the resume question).
- Free-text items (links, file paths, pasted job text) are better asked in plain text in the same message than forced into options.

## Round 1 (always)

| # | Question | Why it matters | Default if skipped |
|---|---|---|---|
| 1 | **Which company or project, and which links?** Website, docs, X account, job post, anything else you have. | Research starts from primary sources; the links disambiguate names. | Search for the official site and confirm it with the user before going further. |
| 2 | **Which role?** Title plus the job post link or pasted text. | The playbook maps resume evidence to each requirement in the job description. | Use the title only and say the requirement map is inferred. |
| 3 | **Your resume:** file path (PDF, DOCX, Markdown or text) or pasted text. | The playbook is built only from it. | Without a resume, skip the personal playbook and say so on the page. |
| 4 | **Interview stage and who is interviewing?** Options: recruiter screen / hiring manager or founder / technical or panel round / final round. | Changes the mix: recruiter screens favour story and motivation, technical panels favour mechanism questions. | Hiring manager. |

## Round 2 (only what is still open)

| # | Question | Why it matters | Default if skipped |
|---|---|---|---|
| 5 | **Interview date?** | Sets the refresh reminder and warns if data will be stale. | No date; offer a refresh anyway. |
| 6 | **Language of the guide?** Options: same as this chat (Recommended) / English / other. | The whole page, including button labels, is written in that language. | The user's chat language. |
| 7 | **Size?** Options: Standard: 50 MCQs, 24 Q&A, 6 open questions (Recommended) / Quick: 25 MCQs, 12 Q&A, 4 open / Deep: 80 MCQs, 45 Q&A, 10 open. | Time budget. Deep takes much longer and is only worth it a week or more before the interview. | Standard. TL;DR is always about 10 ideas. |
| 8 | **Focus areas or worries?** For example "they will grill me on tokenomics", "I have no sales background". | Weights the research and the objections section. | Balanced coverage. |
| 9 | **Output?** Options: private web page (Recommended, if an artifact or page tool exists) / local HTML file / both. | Delivery step. | Local HTML file. |
| 10 | **May the playbook quote details from your resume** (employers, numbers), or keep it general? | Some people share the page with a mentor or friend. | Quote details; never contact details. |

## Checking that the role is live

Run `scripts/ats_check.py <board-slug> --title "<words>"`. The board slug is the name in the job URL: `jobs.ashbyhq.com/<org>`, `jobs.lever.co/<org>`, `boards.greenhouse.io/<org>` or `job-boards.greenhouse.io/<org>`. The script calls:

- Ashby `https://api.ashbyhq.com/posting-api/job-board/<org>`
- Lever `https://api.lever.co/v0/postings/<org>?mode=json`
- Greenhouse `https://boards-api.greenhouse.io/v1/boards/<org>/jobs`

Report exactly what you found: "live on Greenhouse, checked 2026-10-08", "the board exists but no matching title", or "not found on Ashby, Lever or Greenhouse". Other systems (Workable, SmartRecruiters, Teamtailor, a custom careers page) need a manual check; say "not verified" if you could not check. Never present an unverified role as open.

## Closing summary (then wait)

Example:

> Here is what I will build: an interview prep page for **Acme (acme.example)**, role **Developer Relations Lead** (live on Lever, checked today), second round with the Head of DevRel on **20 October**. In **English**, Standard size (10 ideas, 24 Q&A, 6 open questions, 50 MCQs), focus on open-source community metrics. The playbook will quote your resume but never your contact details. Output: a private web page. Your resume stays on this machine and is not sent to search engines or research agents. OK to start?
