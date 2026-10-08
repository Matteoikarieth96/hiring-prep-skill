# Security

## Threat model

The skill handles two kinds of untrusted input and one kind of sensitive input:

| Input | Risk |
|---|---|
| Web pages, docs, job posts, API responses, PDFs fetched during research | Prompt injection (text telling the agent to do something), malicious links, markup that becomes script when copied into a page |
| The guide content that ends up in `guide.json` (written by the agent from the above) | Stored XSS in the generated page: `<script>`, event handlers, `javascript:` links, `</script>` breaking out of embedded JSON |
| The candidate's resume | Personal data leaking into web searches, third-party tools, subagent prompts, the published page or a git repository |

Assets protected: the person viewing the page (no script injection), the candidate's personal data, and the local file system (no writes outside the chosen folder).

## Mitigations implemented

| Mitigation | Where |
|---|---|
| Fetched and supplied content is treated as data; instructions inside it are quoted to the user, never followed | `SKILL.md` ground rules, `references/research.md` |
| Every text field is HTML-escaped (`html.escape(..., quote=True)`); the inline markup is tokenized and each token escaped, so only `<strong>`, `<em>`, `<code>` and `<a>` can be produced | `scripts/guide_lib.py` (`tokenize_inline`, `render_inline`) |
| Links: only absolute `http`/`https` URLs without credentials; anything else (`javascript:`, `data:`, `vbscript:`, `file:`, protocol-relative) is dropped to plain text; links get `target="_blank" rel="noopener noreferrer"` | `scripts/guide_lib.py` (`is_safe_url`), checked again in `scripts/assets/guide.js` (`safeHref`) |
| Quiz data embedded as `<script type="application/json">` with `<`, `>` and `&` written as `\u003c`, `\u003e`, `\u0026`, so `</script>` cannot appear | `scripts/guide_lib.py` (`json_for_script`) |
| The page script builds the quiz with `createElement` and `textContent` only; no `innerHTML`, `insertAdjacentHTML`, `document.write` or `eval` (a test enforces this) | `scripts/assets/guide.js`, `tests/test_build.py` |
| Content-Security-Policy meta tag: `default-src 'none'`, script and style allowed only by SHA-256 hash of the page's own inline code, `base-uri 'none'`, `form-action 'none'` | `scripts/build_guide.py` |
| `localStorage` reads are wrapped in try/catch and sanitized (only integer answers 0 to 3 for existing questions); the page works without storage | `scripts/assets/guide.js` |
| `referrer` set to `no-referrer`, `robots` to `noindex,nofollow`; no third-party requests unless `--webfonts` is passed | `scripts/build_guide.py` |
| Slug validated (`^[a-z0-9][a-z0-9-]{0,63}$`); output path resolved (symlinks included) and refused if outside `--out-dir`; output file name must be `<slug>.html` style; symlink targets are never overwritten | `scripts/guide_lib.py` (`safe_output_path`), `scripts/build_guide.py` |
| Validator rejects unsafe schemes, email addresses, phone numbers, em/en dashes and template placeholders anywhere in the guide; warns on dates of birth | `scripts/validate.py` |
| Resume handled locally; contact details (email, phone, profile links, street-address lines, date of birth) redacted by default; DOCX parsing refuses DOCTYPE/entity declarations and oversized parts; PDF parsed by local `pdftotext` with an argument list and a timeout | `scripts/resume_text.py`, `references/privacy.md` |
| Research subagents never receive the resume; search queries never contain resume text | `SKILL.md` step 3, `references/privacy.md` |
| `.gitignore` excludes resumes, work and evidence folders and built pages (except the fictional example) | `.gitignore` |
| Live-role check sends only the board slug to three fixed HTTPS hosts; slug validated; responses capped at 8 MB; control characters stripped from output; TLS verification is never disabled | `scripts/ats_check.py` |
| Subprocesses (Chrome, pdftotext) use argument lists, never `shell=True` | `scripts/qa_check.py`, `scripts/resume_text.py` |
| Generated pages are published privately by default | `SKILL.md` step 9 |

Tests with malicious inputs: `tests/test_build.py` (script and image payloads, `</script>` breakout, attribute breakout in URLs, dangerous schemes, path traversal, symlink escape), `tests/test_validate.py` (schemes, contact details, dashes), `tests/test_helpers_scripts.py` (DOCX entity expansion, control characters in API responses).

## Residual risks

- **Prompt injection is mitigated by instructions, not by code.** A sufficiently deceptive page could still mislead the research (for example a fake number). The verification step and the claimed/verified labels reduce, but do not remove, this risk.
- **Redaction is pattern-based.** Unusual phone formats, addresses without a street keyword or contact details inside images will not be caught. Review `work/resume.txt`.
- **Published pages.** If a user chooses to publish a page publicly, the career details in the playbook become public. The skill warns before that.
- **`--no-csp`** removes the Content-Security-Policy for hosts that inject their own scripts. Escaping still applies, but the second layer is gone.
- **`qa_check.py`** runs headless Chrome with `--allow-file-access-from-files` so the wrapper page can measure the local guide. It only loads the generated page and its own wrapper, in a temporary headless profile.
- **`--webfonts`** loads Google Fonts, which reveals the viewer's IP address to Google.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting: the **Security** tab of this repository, then **Report a vulnerability**. Do not open a public issue for security problems. Include the input that triggers the problem and what you expected to happen.
