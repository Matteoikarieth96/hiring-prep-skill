# Security

## Threat model

The skill handles two kinds of untrusted input and one kind of sensitive input:

| Input | Risk |
|---|---|
| Web pages, docs, job posts, API responses, PDFs fetched during research | Prompt injection (text telling the agent to do something), malicious links, markup that becomes script when copied into a page |
| The guide content that ends up in `guide.json` (written by the agent from the above) | Stored XSS in the generated page: `<script>`, event handlers, `javascript:` links, `</script>` breaking out of embedded JSON |
| The candidate's resume | Personal data leaking into web searches, URLs or other tool arguments (for example because a hostile page asks the agent to send it), third-party tools, subagent prompts, the published page, other local files or a git repository; resource exhaustion from a crafted DOCX |

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
| `localStorage` reads are wrapped in try/catch and sanitized (only integer answers 0 to 3 for existing questions); the page works without storage. The progress key is `hiring-prep:q:<hash of the questions>`, with no slug or company name, because other `file://` pages in the same browser can list it | `scripts/assets/guide.js`, `scripts/build_guide.py` |
| `referrer` set to `no-referrer`, `robots` to `noindex,nofollow`; no third-party requests unless `--webfonts` is passed | `scripts/build_guide.py` |
| Slug validated (`^[a-z0-9][a-z0-9-]{0,63}$`); output path resolved (symlinks included) and refused if outside `--out-dir`; output file name must be `<slug>.html` style | `scripts/guide_lib.py` (`safe_output_path`), `scripts/build_guide.py` |
| Every file the scripts write (built page, resume text, QA screenshots) is opened with `O_NOFOLLOW` and mode 0600, in folders created with mode 0700; a symlink at the target is refused | `scripts/guide_lib.py` (`write_private`, `make_private_dir`) |
| Validator rejects unsafe schemes, em/en dashes, placeholders and personal data anywhere in the guide: email addresses (also `[at]`/`(at)`/` at ... dot ` forms), phone numbers (international with `+` or `00`, North American, Italian and similar national formats, any dash look-alike), street addresses, dates of birth, Italian tax codes and personal LinkedIn links; @handles and ENS names are warnings. Each string is checked raw and as rendered plain text, after NFKC normalisation and removal of format characters, so markup (`**@**`), zero-width characters or fullwidth signs cannot hide an address. Patterns use bounded quantifiers and left anchors (a timing test runs them on 40,000-character adversarial strings) | `scripts/personal_data.py`, `scripts/validate.py` |
| Resume handled locally and redacted by default with the same patterns, plus profile links, @handles, ENS names, labelled websites and every link or domain in the header block | `scripts/resume_text.py`, `scripts/personal_data.py` |
| DOCX: only stored or deflated parts (no bzip2/LZMA bombs), read in 64 KB chunks with a running 10 MB cap (the declared size is not trusted), no encrypted parts, UTF-8 only (NUL bytes and other declared encodings refused, which blocks UTF-16 tricks), and an expat parser whose DOCTYPE and entity handlers raise. PDF is parsed by local `pdftotext` with an argument list and a timeout | `scripts/resume_text.py` |
| Procedure: all web fetching (job post, live-role check, research, number checks) happens before the resume is read; after that no network tool is used until the private publish; resume content never goes into a URL, query, header, search, fetch or subagent prompt | `SKILL.md` ground rules 4 and 5, steps 5 and 6, `references/privacy.md` |
| Research subagents never receive the resume | `SKILL.md` step 3 |
| `.gitignore` ignores every PDF, Word, ODT, RTF, Pages and text file, anything named like a resume, CV or curriculum, every `guide.json`, and the work, evidence and output folders, then re-includes only the fictional example and the tooling (a test runs `git check-ignore` on typical CV names) | `.gitignore`, `tests/test_hardening.py` |
| Live-role check sends only the board slug to three fixed HTTPS hosts; slug validated; https only; redirects are never followed (urllib opener without a redirect handler; curl fallback with `--max-redirs 0 --proto-redir =https`); curl runs with `-q` first so `~/.curlrc` cannot turn verification off; responses capped at 8 MB; control and format characters (including bidi overrides) stripped from output; TLS verification is never disabled | `scripts/ats_check.py` |
| Subprocesses (Chrome, pdftotext, curl) use argument lists, never `shell=True` | `scripts/qa_check.py`, `scripts/resume_text.py`, `scripts/ats_check.py` |
| QA: the page copy and wrapper are served by a server bound to 127.0.0.1 from a temporary folder (no `--allow-file-access-from-files`); each Chrome run gets a fresh `--user-data-dir` that is deleted afterwards, and the Chrome process group is stopped once its output exists | `scripts/qa_check.py` |
| Generated pages are published privately by default | `SKILL.md` step 10 |

Tests with malicious inputs: `tests/test_build.py` (script and image payloads, `</script>` breakout, attribute breakout in URLs, dangerous schemes, path traversal, symlink escape), `tests/test_validate.py` (schemes, contact details, dashes), `tests/test_helpers_scripts.py` (DOCX entity expansion, control characters in API responses), `tests/test_hardening.py` (one regression test per review finding: contact formats, split-markup emails, DOCX bombs and UTF-16, symlinked outputs and file modes, curl arguments, redirects, storage key, regex timing, `.gitignore`).

## Residual risks

- **Prompt injection is mitigated by instructions and ordering, not by code.** A deceptive page could still mislead the research (for example a fake number). The verification step and the claimed/verified labels reduce this. Reading the resume only after all fetching removes the main exfiltration path, but if the user pastes the resume into the chat before research, it is in context from the start; rule 5 then carries the whole load.
- **The model provider sees the redacted resume text**, as it sees everything in the conversation.
- **Redaction is pattern-based.** Unusual phone formats, addresses without a street keyword or postal code outside the header block, or contact details inside images will not be caught; some career lines that mention "born in" are removed too. Review `work/resume.txt`.
- **Published pages.** If a user chooses to publish a page publicly, the career details in the playbook become public. The skill warns before that.
- **`--no-csp`** removes the Content-Security-Policy for hosts that inject their own scripts. Escaping still applies, but the second layer is gone.
- **`qa_check.py`** opens a loopback port for the duration of the run; any local process could read the served copy of the page during that time.
- **`--webfonts`** loads Google Fonts, which reveals the viewer's IP address to Google.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting: the **Security** tab of this repository, then **Report a vulnerability**. Do not open a public issue for security problems. Include the input that triggers the problem and what you expected to happen.
