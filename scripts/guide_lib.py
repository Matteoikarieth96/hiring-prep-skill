"""Shared helpers for the hiring-prep scripts (Python 3.9+, stdlib only).

Everything in a guide is treated as untrusted text: it may contain fragments
copied from web pages, job posts or a resume. The helpers here never turn
that text into markup without escaping it first.
"""
from __future__ import annotations

import errno
import hashlib
import html
import json
import os
import re
from pathlib import Path
from typing import Any, Iterator, List, Optional, Tuple, Union
from urllib.parse import urlsplit

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
HTML_FILE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}\.html$")
SECTION_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
SOURCE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,16}$")
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LETTERS = "ABCD"
ALLOWED_SCHEMES = ("http", "https")

# Dash characters the writing rules forbid: figure dash, en dash, em dash,
# horizontal bar, two-em and three-em dashes.
FORBIDDEN_DASHES = "\u2012\u2013\u2014\u2015\u2e3a\u2e3b"
DASH_RE = re.compile("[" + FORBIDDEN_DASHES + "]")

BAD_SCHEME_RE = re.compile(r"(?i)\b(javascript|vbscript|data|file|blob)\s*:(?=\S)")
# Link targets may contain one level of balanced parentheses, e.g. alert(1) or Wiki_(topic).
URL_IN_PARENS = r"(?:[^()\s]|\([^()\s]*\))+"
MD_LINK_RE = re.compile(r"\[([^\[\]\n]+)\]\((" + URL_IN_PARENS + r")\)")
PLACEHOLDER_RE = re.compile(r"\bTODO\b|\{\{|\}\}|(?i:lorem ipsum)")

INLINE_RE = re.compile(
    r"`(?P<code>[^`\n]+)`"
    r"|\[(?P<ltext>[^\[\]\n]+)\]\((?P<lurl>" + URL_IN_PARENS + r")\)"
    r"|\*\*(?P<bold>[^*\n]+?)\*\*"
    r"|(?<![*\w])\*(?P<em>[^*\s](?:[^*\n]*?[^*\s])?)\*(?![*\w])"
)


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

def load_guide(path: Path) -> Any:
    """Read a guide.json file. Raises ValueError with a readable message."""
    p = Path(path)
    if p.stat().st_size > 5 * 1024 * 1024:
        raise ValueError(f"{p} is larger than 5 MB; refusing to load it")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{p} is not valid JSON: {exc}") from exc


# --------------------------------------------------------------------------
# URLs and inline markup
# --------------------------------------------------------------------------

def is_safe_url(url: Any) -> bool:
    """True only for absolute http(s) URLs with a host and no embedded credentials."""
    if not isinstance(url, str) or not url:
        return False
    if any(ord(c) < 0x21 or ord(c) == 0x7F for c in url):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    if parts.scheme.lower() not in ALLOWED_SCHEMES or not parts.netloc:
        return False
    try:
        if parts.username or parts.password:
            return False
    except ValueError:
        return False
    return True


def tokenize_inline(text: str) -> List[list]:
    """Split text into tokens for the tiny inline markup.

    Supported: **bold**, *italic*, `code`, [text](https://url).
    Token shapes: ["t", text], ["b", text], ["i", text], ["c", text],
    ["a", text, href]. Links with any scheme other than http(s) are
    downgraded to plain text, so the URL never reaches the page.
    """
    if not isinstance(text, str):
        text = "" if text is None else str(text)
    text = text.replace("\x00", "")
    tokens: List[list] = []

    def push_text(s: str) -> None:
        if not s:
            return
        if tokens and tokens[-1][0] == "t":
            tokens[-1][1] += s
        else:
            tokens.append(["t", s])

    pos = 0
    for m in INLINE_RE.finditer(text):
        push_text(text[pos:m.start()])
        if m.group("code") is not None:
            tokens.append(["c", m.group("code")])
        elif m.group("ltext") is not None:
            url = m.group("lurl")
            if is_safe_url(url):
                tokens.append(["a", m.group("ltext"), url])
            else:
                push_text(m.group("ltext"))
        elif m.group("bold") is not None:
            tokens.append(["b", m.group("bold")])
        else:
            tokens.append(["i", m.group("em")])
        pos = m.end()
    push_text(text[pos:])
    return tokens


def plain_text(text: Any) -> str:
    """What a reader sees once the inline markup is rendered, plus link targets.

    Used for privacy checks, so that markup cannot split an email address
    (for example mario.rossi**@**mail.example) and hide it from a scan.
    """
    toks = tokenize_inline("" if text is None else str(text))
    seen = "".join(t[1] for t in toks)
    hrefs = " ".join(t[2] for t in toks if t[0] == "a")
    return seen + (" " + hrefs if hrefs else "")


def compact_tokens(text: str) -> Any:
    """Plain strings stay strings; marked-up strings become token lists."""
    toks = tokenize_inline(text)
    if not toks:
        return ""
    if len(toks) == 1 and toks[0][0] == "t":
        return toks[0][1]
    return toks


def esc(s: Any) -> str:
    return html.escape("" if s is None else str(s), quote=True)


def render_inline(text: Any) -> str:
    """Escape text, then apply the safe inline markup. Returns HTML."""
    out = []
    for tok in tokenize_inline("" if text is None else str(text)):
        kind = tok[0]
        if kind == "t":
            out.append(esc(tok[1]))
        elif kind == "b":
            out.append("<strong>" + esc(tok[1]) + "</strong>")
        elif kind == "i":
            out.append("<em>" + esc(tok[1]) + "</em>")
        elif kind == "c":
            out.append("<code>" + esc(tok[1]) + "</code>")
        elif kind == "a" and is_safe_url(tok[2]):
            out.append(
                '<a href="' + esc(tok[2]) + '" target="_blank" rel="noopener noreferrer">'
                + esc(tok[1]) + "</a>"
            )
        else:
            out.append(esc(tok[1]))
    return "".join(out)


def json_for_script(data: Any) -> str:
    """Serialize data for a <script type="application/json"> block.

    '<', '>' and '&' are written as JSON unicode escapes so that no
    sequence such as </script> or <!-- can appear in the raw HTML.
    """
    raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=False)
    return (
        raw.replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


# --------------------------------------------------------------------------
# Walking strings
# --------------------------------------------------------------------------

def iter_strings(obj: Any, path: str = "$") -> Iterator[Tuple[str, str]]:
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from iter_strings(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from iter_strings(v, f"{path}[{i}]")


def as_paragraphs(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str) and v.strip()]
    return []


# --------------------------------------------------------------------------
# Deterministic, balanced shuffle of multiple-choice options
# --------------------------------------------------------------------------

class XorShift32:
    """Tiny deterministic PRNG. Same seed, same sequence, on every platform."""

    def __init__(self, seed: int) -> None:
        self.state = (seed & 0xFFFFFFFF) or 0x9E3779B9

    def next_u32(self) -> int:
        x = self.state
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        self.state = x & 0xFFFFFFFF
        return self.state

    def below(self, n: int) -> int:
        return self.next_u32() % n

    def shuffle(self, items: list) -> None:
        for i in range(len(items) - 1, 0, -1):
            j = self.below(i + 1)
            items[i], items[j] = items[j], items[i]


def shuffle_seed(guide: dict) -> int:
    meta = guide.get("meta") if isinstance(guide, dict) else None
    meta = meta if isinstance(meta, dict) else {}
    seed = meta.get("shuffle_seed")
    if isinstance(seed, int) and not isinstance(seed, bool):
        return seed
    slug = str(meta.get("slug", "guide"))
    return int(hashlib.sha256(slug.encode("utf-8")).hexdigest()[:8], 16)


def longest_run(seq: list) -> int:
    best = run = 0
    prev = object()
    for x in seq:
        run = run + 1 if x == prev else 1
        prev = x
        best = max(best, run)
    return best


def balanced_targets(n: int, rng: XorShift32) -> List[int]:
    """Correct-answer positions for n questions: each letter used n/4 times
    (plus or minus one), in a seeded order with no letter three times in a row."""
    base = [n // 4 + (1 if i < n % 4 else 0) for i in range(4)]
    letters = list(range(4))
    rng.shuffle(letters)  # which letters get the extra slots
    for _ in range(64):
        remaining = [0, 0, 0, 0]
        for i, letter in enumerate(letters):
            remaining[letter] = base[i]
        seq: List[int] = []
        while len(seq) < n:
            allowed = [x for x in range(4) if remaining[x] and not (len(seq) >= 2 and seq[-1] == seq[-2] == x)]
            if not allowed:
                break
            pick = rng.below(sum(remaining[x] for x in allowed))
            for x in allowed:
                pick -= remaining[x]
                if pick < 0:
                    break
            seq.append(x)
            remaining[x] -= 1
        if len(seq) == n:
            return seq
    # Fallback (not expected): balanced but runs may remain.
    seq = [letters[i % 4] for i in range(n)]
    rng.shuffle(seq)
    return seq


def shuffle_mcqs(mcqs: list, seed: int) -> list:
    """Return copies of the questions with options reordered.

    The correct option lands on a balanced target position; distractors are
    shuffled around it. Input questions are not modified.
    """
    rng = XorShift32(seed)
    valid = [q for q in mcqs if _is_well_formed_mcq(q)]
    targets = balanced_targets(len(valid), rng)
    out = []
    t = iter(targets)
    for q in mcqs:
        if not _is_well_formed_mcq(q):
            out.append(dict(q) if isinstance(q, dict) else q)
            continue
        target = next(t)
        opts = list(q["o"])
        correct = opts[q["a"]]
        distractors = [o for i, o in enumerate(opts) if i != q["a"]]
        rng.shuffle(distractors)
        new_opts = distractors[:target] + [correct] + distractors[target:]
        nq = dict(q)
        nq["o"] = new_opts
        nq["a"] = target
        out.append(nq)
    return out


def _is_well_formed_mcq(q: Any) -> bool:
    return (
        isinstance(q, dict)
        and isinstance(q.get("o"), list)
        and len(q["o"]) == 4
        and isinstance(q.get("a"), int)
        and not isinstance(q.get("a"), bool)
        and 0 <= q["a"] < 4
    )


def final_mcqs(guide: dict) -> list:
    """The questions exactly as they will appear on the page."""
    exam = guide.get("exam") if isinstance(guide.get("exam"), dict) else {}
    mcqs = exam.get("mcq") if isinstance(exam.get("mcq"), list) else []
    meta = guide.get("meta") if isinstance(guide.get("meta"), dict) else {}
    if meta.get("shuffle", True) is False:
        return [dict(q) if isinstance(q, dict) else q for q in mcqs]
    return shuffle_mcqs(mcqs, shuffle_seed(guide))


def letter_counts(mcqs: list) -> List[int]:
    counts = [0, 0, 0, 0]
    for q in mcqs:
        if _is_well_formed_mcq(q):
            counts[q["a"]] += 1
    return counts


def safe_output_path(out_dir: Path, output: Optional[Path], slug: str) -> Path:
    """Resolve the output file and refuse anything outside out_dir."""
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        raise ValueError(f"invalid slug {slug!r}: use lowercase letters, digits and hyphens (max 64)")
    base = Path(out_dir).expanduser().resolve()
    if output is None:
        target = base / f"{slug}.html"
    else:
        target = Path(output).expanduser()
        if not target.is_absolute():
            target = Path.cwd() / target
        target = target.resolve()
    if not HTML_FILE_RE.match(target.name):
        raise ValueError(f"output file name {target.name!r} must look like <slug>.html")
    try:
        target.relative_to(base)
    except ValueError:
        raise ValueError(f"output {target} is outside the output folder {base}") from None
    return target


def make_private_dir(path: Path) -> Path:
    """Create a folder (and parents) readable only by the current user."""
    p = Path(path)
    p.mkdir(mode=0o700, parents=True, exist_ok=True)
    return p


def write_private(path: Path, data: Union[str, bytes], mode: int = 0o600) -> None:
    """Write a file without following a symlink at the target, mode 0600.

    O_NOFOLLOW makes the open fail if the final path component is a symlink,
    so a planted link cannot redirect the write. Existing files are reset to
    the private mode as well.
    """
    p = Path(path)
    if p.is_symlink():
        raise ValueError(f"refusing to write through the symlink {p}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(str(p), flags, mode)
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise ValueError(f"refusing to write through the symlink {p}") from None
        raise
    with os.fdopen(fd, "wb") as fh:
        if hasattr(os, "fchmod"):
            os.fchmod(fh.fileno(), mode)
        fh.write(data.encode("utf-8") if isinstance(data, str) else data)
