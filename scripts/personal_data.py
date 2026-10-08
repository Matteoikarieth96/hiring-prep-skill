"""Detect and redact personal contact details (Python 3.9+, stdlib only).

Used by:
  * validate.py: contact details anywhere in guide.json are errors; possible
    personal handles (@name, name.eth) are warnings, because a guide may
    legitimately mention the company's own handle;
  * resume_text.py: redacts the same patterns (and more) from resume text.

Text is normalised first (NFKC, format characters such as zero-width and
bidi controls removed, dash look-alikes folded to "-"), so tricks like
fullwidth at signs, zero-width spaces or en-dash phone numbers do not hide
anything. Every pattern uses bounded quantifiers and a left anchor, so a scan
stays roughly linear even on long adversarial strings.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Callable, List, Tuple

Pattern = re.Pattern
Match = re.Match

# --------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------

DASH_LIKE = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe58\ufe63\uff0d"
_DASH_MAP = {ord(c): "-" for c in DASH_LIKE}


def normalize(text: str) -> str:
    """NFKC, drop format characters (category Cf), fold dashes to '-'."""
    text = unicodedata.normalize("NFKC", text or "")
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cf")
    return text.translate(_DASH_MAP)


# --------------------------------------------------------------------------
# Patterns
# --------------------------------------------------------------------------

_LOCAL = r"(?<![\w.%+-])[\w.%+-]{1,64}"
_LABEL = r"[A-Za-z0-9-]{1,63}"
_COMMON_TLDS = (
    r"(?:com|net|org|io|co|it|de|fr|es|pt|uk|eu|ch|nl|be|at|se|no|dk|fi|pl|cz|ie|us|ca|au|nz|in|jp|br|mx|ar"
    r"|me|dev|app|ai|xyz|info|biz|tech|email|mail|online|site)"
)

EMAIL_RE = re.compile(_LOCAL + r"@(?:" + _LABEL + r"\.){1,8}[A-Za-z]{2,24}(?![A-Za-z])")

_AT_BRACKETED = r"\s{0,3}[\[({<]\s{0,3}(?i:at|@|chiocciola)\s{0,3}[\])}>]\s{0,3}"
_DOT_OBFUSCATED = r"(?:\s{0,3}[\[({<]\s{0,3}(?i:dot|punto|\.)\s{0,3}[\])}>]\s{0,3}|\s{1,3}(?i:dot|punto)\s{1,3})"
EMAIL_OBFUSCATED_RES = (
    # mario.rossi [at] gmail [dot] com, (at), {at}, <at>; dots may be literal
    re.compile(_LOCAL + _AT_BRACKETED + _LABEL + r"(?:(?:" + _DOT_OBFUSCATED + r"|\.)" + _LABEL + r"){1,6}"),
    # mario.rossi at gmail dot com: bare words need an obfuscated dot and a common TLD
    re.compile(
        _LOCAL + r"\s{1,3}(?i:at|chiocciola)\s{1,3}(?!(?i:the|a|an|this|that|its|their|our|your|his|her)\b)" + _LABEL
        + r"(?:" + _DOT_OBFUSCATED + _LABEL + r"){0,4}" + _DOT_OBFUSCATED + r"(?i:" + _COMMON_TLDS + r")(?![A-Za-z])"
    ),
)

# Phones. Each candidate is checked by a predicate on its digits, so years,
# ranges, percentages, money and thousands-grouped numbers are not flagged.
PHONE_INTL_RE = re.compile(r"(?<![\w+])(?:\+|00)[1-9]\d{0,2}(?:[\s./-]{0,2}\(?\d{1,5}\)?){2,6}(?!\w)")
PHONE_NANP_RE = re.compile(r"(?<![\w-])\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?![\w-])")
PHONE_NATIONAL_RE = re.compile(r"(?<![\w.,+/-])(?:0\d{1,3}|3\d{2})(?:[\s./-]{0,2}\d{2,8}){1,4}(?![\w])")
LONG_DIGITS_RE = re.compile(r"(?<![\w.,])[1-9]\d{9,12}(?![\w])")

_STREET_WORDS = (
    r"via|viale|piazza|piazzale|corso|largo|strada|vicolo|contrada|rue|calle|avenida|avenue|ave|street|st"
    r"|road|rd|boulevard|blvd|lane|ln|drive|dr|platz|stra(?:ss|\u00df)e|weg"
)
ADDRESS_RES = (
    # Via Roma 12, 00184 Roma / Calle Mayor 5 28013: street word, name, number, 5-digit postal code
    re.compile(
        r"(?<![\w])(?i:" + _STREET_WORDS + r")\.?\s{1,3}(?:[\w'.-]{1,30}\s{1,3}){1,5}?\d{1,5}[A-Za-z]?"
        r"(?:\s{0,3}[,/]\s{0,3}|\s{1,3})\d{5}(?!\d)"
    ),
    # 12 Example Street / 221B Baker St.
    re.compile(
        r"(?<![\w])\d{1,5}[A-Za-z]?\s{1,3}(?:[A-Z][\w'.-]{0,30}\s{1,3}){1,4}"
        r"(?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Boulevard|Blvd|Drive|Dr|Way|Court|Ct|Place|Pl)\b\.?"
    ),
)

DOB_RE = re.compile(
    r"(?i)\b(?:date\s{1,3}of\s{1,3}birth|d\.o\.b\b|dob\s{0,2}[:.]|born\s{0,2}:|born\s{1,3}on\s{1,3}\d"
    r"|birth\s{0,2}date\s{0,2}:|data\s{1,3}di\s{1,3}nascita"
    r"|nat[oa]\s{1,3}(?:a\s{1,3}[\w'-]{1,30}(?:\s{1,3}[\w'-]{1,30})?\s{1,3})?il\s{1,3}\d"
    r"|geboren\s{1,3}am|fecha\s{1,3}de\s{1,3}nacimiento|date\s{1,3}de\s{1,3}naissance)"
)

CODICE_FISCALE_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])[A-Z]{6}[0-9LMNPQRSTUV]{2}[ABCDEHLMPRST][0-9LMNPQRSTUV]{2}[A-Z][0-9LMNPQRSTUV]{3}[A-Z](?![A-Za-z0-9])"
)

LINKEDIN_PERSONAL_RE = re.compile(
    r"(?i)(?<![\w.-])(?:https?://)?(?:[a-z]{2,3}\.)?(?:www\.)?(?:linkedin\.com/(?:in|pub|profile)/|lnkd\.in/)[^\s)\]>,;]{1,200}"
)
PROFILE_LINK_RE = re.compile(
    r"(?i)(?<![\w.-])(?:https?://)?(?:[a-z]{2,3}\.)?(?:www\.)?"
    r"(?:linkedin\.com/|lnkd\.in/|github\.com/|gitlab\.com/|x\.com/|twitter\.com/|t\.me/|wa\.me/|instagram\.com/"
    r"|facebook\.com/|fb\.com/|medium\.com/@|about\.me/|calendly\.com/|keybase\.io/|bsky\.app/profile/)"
    r"[^\s)\]>,;]{1,200}"
)
HANDLE_RE = re.compile(r"(?<![\w.@/])@[A-Za-z0-9_]{2,30}(?![\w.@])")
ENS_RE = re.compile(r"(?i)(?<![\w.-])[a-z0-9-]{1,63}(?:\.[a-z0-9-]{1,63}){0,3}\.eth(?![\w-])")
LABELLED_SITE_RE = re.compile(
    r"(?i)\b(?:portfolio|website|web\s{0,2}site|homepage|home\s{0,2}page|blog|sito(?:\s{1,3}web)?|personal\s{1,3}site)"
    r"\s{0,3}[:-]\s{0,3}\S{1,200}"
)
URL_OR_DOMAIN_RE = re.compile(
    r"(?i)(?<![\w@.-])(?:https?://)?(?:www\.)?(?:[a-z0-9-]{1,63}\.){1,6}[a-z]{2,24}(?:/[^\s)\]>,;]{0,200})?(?![\w-])"
)

# --------------------------------------------------------------------------
# Predicates on phone candidates
# --------------------------------------------------------------------------


def _digits(s: str) -> str:
    return "".join(ch for ch in s if ch.isdigit())


def _intl_ok(m: Match) -> bool:
    s = m.group(0)
    d = _digits(s[2:] if s.startswith("00") else s)
    return 8 <= len(d) <= 15


def _national_ok(m: Match) -> bool:
    s = m.group(0)
    d = _digits(s)
    if not 9 <= len(d) <= 11:
        return False
    groups = re.split(r"[\s./-]+", s.strip())
    # 300.000.000 or 300 000 000 is a grouped number, not a phone
    if not s.startswith("0") and len(groups) > 1 and 1 <= len(groups[0]) <= 3 and all(len(g) == 3 for g in groups[1:]):
        return False
    return True


def _long_digits_ok(m: Match) -> bool:
    d = m.group(0)
    return not d.endswith("00000") and len(set(d)) > 2


def _always(m: Match) -> bool:
    return True


# (kind, pattern, predicate) for errors in a guide
ERROR_CHECKS: Tuple[Tuple[str, Pattern, Callable[[Match], bool]], ...] = (
    ("email address", EMAIL_RE, _always),
    ("obfuscated email address", EMAIL_OBFUSCATED_RES[0], _always),
    ("obfuscated email address", EMAIL_OBFUSCATED_RES[1], _always),
    ("phone number", PHONE_INTL_RE, _intl_ok),
    ("phone number", PHONE_NANP_RE, _always),
    ("phone number", PHONE_NATIONAL_RE, _national_ok),
    ("street address", ADDRESS_RES[0], _always),
    ("street address", ADDRESS_RES[1], _always),
    ("date of birth", DOB_RE, _always),
    ("tax code (codice fiscale)", CODICE_FISCALE_RE, _always),
    ("personal LinkedIn link", LINKEDIN_PERSONAL_RE, _always),
)
WARNING_CHECKS: Tuple[Tuple[str, Pattern, Callable[[Match], bool]], ...] = (
    ("@handle", HANDLE_RE, _always),
    ("ENS name", ENS_RE, _always),
)


def _found(pattern: Pattern, pred: Callable[[Match], bool], text: str) -> bool:
    return any(pred(m) for m in pattern.finditer(text))


def detect(text: str) -> Tuple[List[str], List[str]]:
    """Return (error kinds, warning kinds) found in text, without duplicates."""
    t = normalize(text)
    errors: List[str] = []
    warnings: List[str] = []
    for kind, pattern, pred in ERROR_CHECKS:
        if kind not in errors and _found(pattern, pred, t):
            errors.append(kind)
    for kind, pattern, pred in WARNING_CHECKS:
        if kind not in warnings and _found(pattern, pred, t):
            warnings.append(kind)
    return errors, warnings


# --------------------------------------------------------------------------
# Redaction (resume text)
# --------------------------------------------------------------------------

DOB_LINE_RE = re.compile(
    r"(?i)\b(?:date\s{1,3}of\s{1,3}birth\b|d\.?o\.?b\b|born\s{0,3}(?::|on\b|in\b|\d)|birthday\b|birth\s{0,2}date\b"
    r"|data\s{1,3}di\s{1,3}nascita\b|nat[oa]\s{1,3}(?:a|il|in|nel)\b|geboren\b|fecha\s{1,3}de\s{1,3}nacimiento\b"
    r"|lugar\s{1,3}de\s{1,3}nacimiento\b|date\s{1,3}de\s{1,3}naissance\b|n\u00e9e?\s{1,3}le\b)"
)
ADDRESS_LINE_RE = re.compile(
    r"(?<![\w])(?i:" + _STREET_WORDS + r")\.?\s{1,3}[\w'.-]{1,30}(?:\s{1,3}[\w'.-]{1,30}){0,4}?\s{1,3}\d{1,5}[A-Za-z]?\b"
    r"|(?<!\d)\d{5}\s{1,3}[A-Z][\w'-]{1,30}"
)
SECTION_RE = re.compile(
    r"(?i)^(?:#{1,6}\s|(?:work\s+|professional\s+)?experience|employment|summary|profile|about(?:\s+me)?|skills"
    r"|education|esperienz[ae](?:\s+lavorative)?|profilo|competenze|formazione|istruzione|experiencia|formaci\u00f3n)\b"
)
HEADER_MAX_LINES = 12


def header_end(lines: List[str]) -> int:
    """Index of the first line after the contact header block."""
    seen = 0
    for i, line in enumerate(lines):
        s = line.strip()
        if not s:
            continue
        seen += 1
        if seen > 1 and SECTION_RE.match(s):
            return i
        if seen >= HEADER_MAX_LINES:
            return i + 1
    return len(lines)


def _sub(pattern: Pattern, repl: str, text: str, pred: Callable[[Match], bool] = _always) -> str:
    return pattern.sub(lambda m: repl if pred(m) else m.group(0), text)


def redact_line(line: str, in_header: bool) -> str:
    line = _sub(PROFILE_LINK_RE, "[profile link removed]", line)
    for rx in EMAIL_OBFUSCATED_RES:
        line = _sub(rx, "[email removed]", line)
    line = _sub(EMAIL_RE, "[email removed]", line)
    line = _sub(CODICE_FISCALE_RE, "[tax code removed]", line)
    for rx in ADDRESS_RES:
        line = _sub(rx, "[address removed]", line)
    line = _sub(PHONE_INTL_RE, "[phone removed]", line, _intl_ok)
    line = _sub(PHONE_NANP_RE, "[phone removed]", line)
    line = _sub(PHONE_NATIONAL_RE, "[phone removed]", line, _national_ok)
    line = _sub(LONG_DIGITS_RE, "[phone removed]", line, _long_digits_ok)
    line = _sub(HANDLE_RE, "[handle removed]", line)
    line = _sub(ENS_RE, "[name removed]", line)
    line = _sub(LABELLED_SITE_RE, "[website removed]", line)
    if in_header:
        line = _sub(URL_OR_DOMAIN_RE, "[link removed]", line)
    return line


def redact(text: str) -> str:
    """Remove contact details from resume text. Career content is kept."""
    t = normalize(text)
    lines = t.split("\n")
    end = header_end(lines)
    out = []
    for i, line in enumerate(lines):
        in_header = i < end
        if DOB_LINE_RE.search(line):
            out.append("[date of birth removed]")
        elif in_header and ADDRESS_LINE_RE.search(line):
            out.append("[address removed]")
        else:
            out.append(redact_line(line, in_header))
    return "\n".join(out)
