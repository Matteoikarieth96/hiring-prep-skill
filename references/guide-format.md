# guide.json format

One JSON object. `scripts/validate.py` enforces everything marked required. A complete working example is `examples/fictional/guide.json`; a skeleton is `templates/guide.template.json`.

## Text and inline markup

All text fields are plain text, HTML-escaped at build time. Raw HTML is shown literally, never rendered. A tiny inline markup is supported everywhere:

| Markup | Result |
|---|---|
| `**bold**` | bold |
| `*italic*` | italic |
| `` `code` `` | inline code |
| `[text](https://example.com/page)` | link, opens in a new tab with `rel="noopener noreferrer"` |

Only absolute `http` and `https` links are rendered; any other scheme (`javascript:`, `data:`, `file:` ...) is dropped and the validator reports it as an error. Link targets may contain one level of parentheses.

"Paragraphs" below means a string or a list of strings; each string becomes a paragraph.

Forbidden anywhere: em and en dashes, email addresses, phone numbers, `TODO`, `{{ }}`.

## Top level

| Key | Type | Required |
|---|---|---|
| `meta` | object | yes |
| `tldr` | list of strings (about 10) | yes |
| `overview` | object | yes |
| `qa` | list of groups | yes |
| `playbook` | object | yes |
| `exam` | object | yes |
| `sources` | list | yes |

## meta

| Key | Type | Notes |
|---|---|---|
| `slug` | string, required | `^[a-z0-9][a-z0-9-]{0,63}$`; output file is `<slug>.html` |
| `title`, `company`, `role` | strings, required | |
| `as_of` | `YYYY-MM-DD`, required | the date the data was checked; warning after 45 days |
| `target_counts` | object, required | `{"tldr": n, "qa": n, "open": n, "mcq": n}`; actual counts must match |
| `eyebrow`, `dek` | strings | header lines; eyebrow defaults to "Interview prep · company · role" |
| `interview_date` | `YYYY-MM-DD` | warning if in the past |
| `stage` | string | for example "Second round, hiring manager" |
| `job_post_status` | string | result of the live-role check |
| `lang` | string | HTML `lang` attribute, default `en` |
| `labels` | object of strings | overrides UI text for other languages; keys are in `DEFAULT_LABELS` in `scripts/build_guide.py` |
| `shuffle` | boolean | default `true`; `false` keeps authored option order |
| `shuffle_seed` | integer | default derived from the slug |
| `fictional` | boolean | shows a "fictional example" banner |

## overview

| Key | Type | Required |
|---|---|---|
| `what_it_is`, `how_it_works`, `business_model`, `team`, `funding` | paragraphs | yes |
| `risks` | list of strings | yes |
| `numbers` | list of `{label, value, status, source, date, note?}` | yes, at least one |
| `competitors` | `{intro?, columns[], rows[][], note?}` | yes; every row has as many cells as `columns`; first cell is the row label |
| `news` | list of `{date, text, source}` | recommended (warning if empty) |
| `traps` | list of `{myth, fact, source?}` | yes, at least one |
| `tips` | list of strings | optional, shown as interview tips |

`status` is `verified`, `claimed` or `estimate`. `source` is a source id or a list of ids from `sources`.

## qa

```json
[{ "group": "Ecosystem and product", "items": [{ "q": "...", "a": ["paragraph", "paragraph"] }] }]
```

The total number of items must equal `meta.target_counts.qa`.

## playbook

| Key | Type |
|---|---|
| `positioning` | list of strings |
| `evidence_map` | list of `{requirement, evidence, fit}`; `fit` is `strong`, `partial` or `gap` |
| `objections` | list of `{objection, reframe}` |
| `star_stories` | list of `{title, situation, task, action, result, use_for?}`; 3 expected |
| `questions_to_ask` | list of strings |
| `do`, `dont` | lists of strings |
| `cheat_sheet` | list of `{term, value}` |
| `plan_30_60_90` | list of `{phase, goal?, items[]}`; 3 expected |

All required and non-empty.

## exam

| Key | Type | Notes |
|---|---|---|
| `open` | list of `{q, a}` | `a` is paragraphs; count equals `target_counts.open` |
| `sections` | list of `{id, title, dek?}` | `id` matches `^[a-z0-9][a-z0-9-]{0,40}$` |
| `mcq` | list | count equals `target_counts.mcq` |
| `verdicts` | list of `{min, title, text}` | optional; `min` is a fraction 0 to 1; one band must have `min: 0` |

Each MCQ:

| Key | Type | Rule |
|---|---|---|
| `s` | string | an existing section id |
| `q` | string | non-empty |
| `o` | list of 4 strings | non-empty, unique (case and spacing ignored), no "all/none of the above" |
| `a` | integer 0 to 3 | index of the correct option as authored |
| `e` | list of strings | non-empty; 2 paragraphs recommended; no positional references |
| `k` | string | key point, non-empty |
| `d` | 1, 2 or 3 | optional difficulty |

### Shuffle

At build time the options of every question are reordered with a deterministic seeded generator (`meta.shuffle_seed`, or a seed derived from the slug). Correct positions are spread evenly over A to D (each letter within one of n/4, never the same letter three times in a row), so no letter exceeds 35 percent from 8 questions up. The same guide always produces the same page. The validator runs the same shuffle and reports the letter distribution.

## sources

```json
[{ "id": "S1", "title": "...", "url": "https://...", "accessed": "2026-10-07", "kind": "primary", "publisher": "..." }]
```

`id` matches `^[A-Za-z0-9_-]{1,16}$` and is unique. `url` must be an absolute http(s) URL without credentials. `kind` is `primary` or `secondary` (optional, but a `verified` number that cites no primary source gets a warning).

## Page features driven by the data

- Quiz progress is saved in `localStorage` under `hiring-prep:<slug>:<hash of the questions>`, so a refreshed guide with new questions starts clean. The page works without storage.
- `#demo` in the URL shows only the quiz with the first question answered right and the second wrong, without saving anything (for screenshots). `#focus-<section>` shows one section (`tldr`, `overview`, `qa`, `playbook`, `exam`, `sources`).
