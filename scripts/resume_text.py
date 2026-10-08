#!/usr/bin/env python3
"""Extract plain text from a resume and strip contact details.

Usage:
    python3 scripts/resume_text.py resume.pdf|resume.docx|resume.md|resume.txt [-o work/resume.txt] [--keep-contacts]

Contact details (email addresses, phone numbers, profile links, street-address
lines, dates of birth) are replaced with placeholders by default, because the
guide never needs them. The output stays on this machine: nothing is uploaded.

PDF: uses the local `pdftotext` tool (poppler) if installed; otherwise it
exits with code 2 and asks you to read the PDF with Claude's file reader.
DOCX: read with zipfile + ElementTree, with size and DOCTYPE guards.
Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import List, Optional
from xml.etree import ElementTree

sys.path.insert(0, str(Path(__file__).resolve().parent))

from guide_lib import EMAIL_RE, PHONE_RES  # noqa: E402

MAX_INPUT_BYTES = 20 * 1024 * 1024
MAX_XML_BYTES = 10 * 1024 * 1024
W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"

PROFILE_RE = re.compile(
    r"(?i)\b(?:https?://)?(?:www\.)?(?:linkedin\.com/in|github\.com|x\.com|twitter\.com|t\.me|wa\.me|instagram\.com|facebook\.com)/[^\s)\]>,;]+"
)
DOB_LINE_RE = re.compile(r"(?im)^.*\b(date of birth|born on|birthday|data di nascita|nato il|nata il|DOB)\b.*$")
ADDRESS_LINE_RE = re.compile(
    r"(?im)^.*\b\d{1,5}\s+[A-Za-z][A-Za-z .'-]{1,40}\b(street|st\.|avenue|ave\.|road|rd\.|lane|boulevard|blvd|via|viale|piazza|corso|rue|calle|stra(?:ss|\u00df)e)\b.*$"
)


class ResumeError(Exception):
    pass


def redact(text: str) -> str:
    text = DOB_LINE_RE.sub("[date of birth removed]", text)
    text = ADDRESS_LINE_RE.sub("[address removed]", text)
    text = PROFILE_RE.sub("[profile link removed]", text)
    text = EMAIL_RE.sub("[email removed]", text)
    for rx in PHONE_RES:
        text = rx.sub("[phone removed]", text)
    return text


def docx_text(path: Path, max_xml: int = MAX_XML_BYTES) -> str:
    try:
        with zipfile.ZipFile(path) as zf:
            try:
                info = zf.getinfo("word/document.xml")
            except KeyError:
                raise ResumeError("not a Word document (word/document.xml missing)") from None
            if info.file_size > max_xml:
                raise ResumeError("word/document.xml is too large to be a resume")
            raw = zf.read(info)
    except zipfile.BadZipFile:
        raise ResumeError("not a valid .docx file") from None
    head = raw[:4096].upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in raw.upper():
        raise ResumeError("refusing a .docx with a DOCTYPE or entity declarations")
    try:
        root = ElementTree.fromstring(raw)
    except ElementTree.ParseError as exc:
        raise ResumeError(f"could not parse the document: {exc}") from None
    lines: List[str] = []
    for para in root.iter(f"{W_NS}p"):
        parts: List[str] = []
        for node in para.iter():
            if node.tag == f"{W_NS}t" and node.text:
                parts.append(node.text)
            elif node.tag == f"{W_NS}tab":
                parts.append("\t")
            elif node.tag in (f"{W_NS}br", f"{W_NS}cr"):
                parts.append("\n")
        lines.append("".join(parts))
    return "\n".join(lines).strip() + "\n"


def pdf_text(path: Path) -> str:
    exe = shutil.which("pdftotext")
    if not exe:
        raise ResumeError("pdftotext is not installed: read the PDF with Claude's file reader instead")
    try:
        res = subprocess.run(
            [exe, "-layout", "-enc", "UTF-8", str(path), "-"],
            capture_output=True, timeout=60, check=False,
        )
    except subprocess.TimeoutExpired:
        raise ResumeError("pdftotext timed out") from None
    if res.returncode != 0:
        raise ResumeError("pdftotext failed: " + res.stderr.decode("utf-8", "replace").strip()[:200])
    return res.stdout.decode("utf-8", "replace")


def extract(path: Path) -> str:
    p = Path(path)
    if not p.is_file():
        raise ResumeError(f"{p} is not a file")
    if p.stat().st_size > MAX_INPUT_BYTES:
        raise ResumeError("file is larger than 20 MB")
    ext = p.suffix.lower()
    if ext == ".docx":
        return docx_text(p)
    if ext == ".pdf":
        return pdf_text(p)
    if ext in (".md", ".markdown", ".txt", ".text"):
        return p.read_text(encoding="utf-8", errors="replace")
    raise ResumeError(f"unsupported file type {ext!r}: use PDF, DOCX, Markdown or plain text")


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Extract resume text locally, with contact details removed")
    ap.add_argument("resume", type=Path)
    ap.add_argument("-o", "--output", type=Path, help="write the text here instead of stdout")
    ap.add_argument("--keep-contacts", action="store_true", help="do not redact contact details")
    args = ap.parse_args(argv)
    try:
        text = extract(args.resume)
    except ResumeError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    if not args.keep_contacts:
        text = redact(text)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"Wrote {args.output} ({len(text)} characters)")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
