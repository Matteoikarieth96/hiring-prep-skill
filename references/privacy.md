# Privacy: handling the resume

A resume is personal data. It identifies a person and often contains contact details, a home address, a date of birth, a photo and employment history. Treat it accordingly.

## Rules

1. **Fetch first, read the resume last.** Do all web work (job post, live-role check, research, number checks) before opening the resume. After the resume is read, use no network tool (web fetch, search, browser, `curl`, `ats_check.py`, subagents) until the private publish the user asked for. A hostile page read later could otherwise try to make the agent send resume text somewhere.
2. **Resume content never goes into a tool argument that leaves the machine.** Not in a URL, query string, header, search query, fetch or subagent prompt. Local file writes and the local scripts in `scripts/` are the only places it goes.
3. **Keep it local and redacted.** Extract text with `scripts/resume_text.py`, which strips email addresses (including "name [at] domain [dot] com" forms), phone numbers (including national formats and numbers written with unusual dashes), street addresses, dates of birth, tax codes, profile links, @handles, ENS names, and any link or domain in the header block. The output file is written with mode 0600 in a 0700 folder and never through a symlink. Pattern-based redaction is not perfect: read `work/resume.txt` before relying on it.
4. **PDF without `pdftotext`.** Read the PDF with the file reader, write only the career content (no name, contact lines, address, photo, links) to a text file, run `resume_text.py` on it, and delete the raw text file. The raw PDF is then in the conversation; that is why rules 1 and 2 matter.
5. **What the model provider sees.** The redacted resume text is processed by the AI model provider as part of the conversation, like anything else the user shares. It is not uploaded to search engines, job boards or research agents.
6. **Do not commit it.** The work folder lives outside any repository by default (`${HIRING_PREP_HOME:-~/hiring-prep}`). This repository's `.gitignore` ignores PDFs, Word and text documents, anything named like a resume or CV, and `guide.json` files, except the fictional example.
7. **No contact details in the guide.** No email, phone, home address, date of birth, ID or tax numbers, or photo. The validator rejects these anywhere in `guide.json`, checking both the raw text and the text as rendered (so markup such as `**@**` cannot split an address), and warns on @handles and ENS names. Address the candidate as "you"; a name is not needed.
8. **Publish privately.** A guide built for a real person is private by default. Publishing anything public is the user's explicit choice, after you have pointed out that the page contains career details.
9. **Minimal quoting.** If the user asked for a general playbook, describe experience without employer names or exact figures.
10. **Delete on request.** When the user is done, offer to delete `work/resume.txt`, the evidence files and built pages. Delete only after a clear yes, and list what you deleted.

## What the page stores

The built page keeps quiz progress (which option was picked for each question) and the theme choice in the viewer's own browser storage (`localStorage`). The progress key is `hiring-prep:q:<hash of the questions>`: it contains no company name or slug, because when the page is opened as a local file, other local pages in the same browser can list this storage. Nothing is sent anywhere. Clearing the browser's site data, or pressing Start over, removes the progress. Fonts are local unless the guide is built with `--webfonts`, which loads Google Fonts and reveals the viewer's IP address to Google.
