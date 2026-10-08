# Privacy: handling the resume

A resume is personal data. It identifies a person and often contains contact details, a home address, a date of birth, a photo and employment history. Treat it accordingly.

## Rules

1. **Keep it local.** Read the file where the user keeps it. Extract text into the work folder with `scripts/resume_text.py`, which strips email addresses, phone numbers, profile links, street-address lines and dates of birth by default. Never upload the resume anywhere.
2. **Do not commit it.** The work folder lives outside any repository by default (`${HIRING_PREP_HOME:-~/hiring-prep}`). This repository's `.gitignore` ignores `resume*` files everywhere except the fictional example.
3. **Do not paste it into third-party services or web searches.** Search queries contain the company and topic, never the candidate's name, employers paired with their name, or any resume text. Research subagents never receive the resume; the playbook is written by the lead agent from the local text.
4. **No contact details in the guide.** No email, phone, home address, date of birth, ID numbers or photo. The validator rejects email addresses and phone numbers anywhere in `guide.json`. Address the candidate as "you"; a name is not needed.
5. **Publish privately.** A guide built for a real person is private by default. Publishing anything public is the user's explicit choice, after you have pointed out that the page contains career details.
6. **Minimal quoting.** If the user asked for a general playbook, describe experience without employer names or exact figures.
7. **Delete on request.** When the user is done, offer to delete `work/resume.txt`, the evidence files and built pages. Delete only after a clear yes, and list what you deleted.

## What the page stores

The built page keeps quiz progress and the theme choice in the viewer's own browser (`localStorage`, key `hiring-prep:<slug>:<hash>`). Nothing is sent anywhere. Fonts are local unless the guide is built with `--webfonts`, which loads Google Fonts and reveals the viewer's IP address to Google.
