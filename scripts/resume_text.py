#!/usr/bin/env python3
"""Extract plain text from a resume and strip contact details.

Usage:
    python3 scripts/resume_text.py resume.pdf|resume.docx|resume.md|resume.txt [-o work/resume.txt] [--keep-contacts]

Contact details are replaced with placeholders by default because the guide
never needs them: email addresses (also written as "name [at] domain [dot] com"),
phone numbers, street addresses, dates of birth, tax codes, profile links,
@handles, ENS names, and any link or domain in the header block.
The output stays on this machine and is written with mode 0600; a symlink at
the output path is refused.

PDF: uses the local `pdftotext` tool (poppler) if installed; otherwise it
exits with code 2. In that case copy only the career content of the PDF into
a .txt file and run this script on that file, so redaction still happens.
DOCX: only stored or deflated parts, read in chunks with a hard size cap,
UTF-8 only, and a parser that refuses DOCTYPE and entity declarations.
Stdlib only, Python 3.9+.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import zipfile
import zlib
from pathlib import Path
from typing import List, Optional
from xml.parsers import expat

sys.path.insert(0, str(Path(__file__).resolve().parent))

from guide_lib import make_private_dir, write_private  # noqa: E402
from personal_data import redact  # noqa: E402

MAX_INPUT_BYTES = 20 * 1024 * 1024
MAX_XML_BYTES = 10 * 1024 * 1024
CHUNK = 64 * 1024
ALLOWED_COMPRESSION = (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_DECL_ENCODING_RE = re.compile(rb"^\s*<\?xml[^>]{0,200}?encoding\s*=\s*[\"']([A-Za-z0-9._-]{1,40})[\"']")


class ResumeError(Exception):
    pass


def _read_part_capped(zf: zipfile.ZipFile, name: str, cap: int) -> bytes:
    try:
        info = zf.getinfo(name)
    except KeyError:
        raise ResumeError("not a Word document (word/document.xml missing)") from None
    if info.compress_type not in ALLOWED_COMPRESSION:
        raise ResumeError("refusing a .docx part with an unusual compression method")
    if info.flag_bits & 0x1:
        raise ResumeError("refusing an encrypted .docx")
    if info.file_size > cap:
        raise ResumeError("word/document.xml is too large to be a resume")
    buf = bytearray()
    try:
        with zf.open(info) as fh:
            while True:
                chunk = fh.read(CHUNK)
                if not chunk:
                    break
                buf += chunk
                if len(buf) > cap:  # the header may lie about the size
                    raise ResumeError("word/document.xml is too large to be a resume")
    except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError) as exc:
        raise ResumeError(f"could not read the document: {exc}") from None
    return bytes(buf)


def _docx_xml_to_text(raw: bytes) -> str:
    if b"\x00" in raw:
        raise ResumeError("refusing a .docx whose XML is not UTF-8 (UTF-16 or UTF-32)")
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        raise ResumeError("refusing a .docx whose XML is not valid UTF-8") from None
    m = XML_DECL_ENCODING_RE.match(raw.lstrip(b"\xef\xbb\xbf"))
    if m and m.group(1).lower() not in (b"utf-8", b"utf8"):
        raise ResumeError("refusing a .docx that declares an encoding other than UTF-8")

    parser = expat.ParserCreate(encoding="UTF-8", namespace_separator=" ")

    def refuse(*_args: object) -> None:
        raise ResumeError("refusing a .docx with a DOCTYPE or entity declarations")

    parser.StartDoctypeDeclHandler = refuse
    parser.EntityDeclHandler = refuse
    parser.UnparsedEntityDeclHandler = refuse
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)

    lines: List[str] = []
    cur: List[str] = []
    state = {"in_t": False}

    def start(name: str, _attrs: dict) -> None:
        if name == f"{W_NS} t":
            state["in_t"] = True
        elif name == f"{W_NS} tab":
            cur.append("\t")
        elif name in (f"{W_NS} br", f"{W_NS} cr"):
            cur.append("\n")

    def end(name: str) -> None:
        if name == f"{W_NS} t":
            state["in_t"] = False
        elif name == f"{W_NS} p":
            lines.append("".join(cur))
            cur.clear()

    def chars(data: str) -> None:
        if state["in_t"]:
            cur.append(data)

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = chars
    try:
        parser.Parse(raw, True)
    except expat.ExpatError as exc:
        raise ResumeError(f"could not parse the document: {exc}") from None
    return "\n".join(lines).strip() + "\n"


def docx_text(path: Path, max_xml: int = MAX_XML_BYTES) -> str:
    try:
        with zipfile.ZipFile(path) as zf:
            raw = _read_part_capped(zf, "word/document.xml", max_xml)
    except zipfile.BadZipFile:
        raise ResumeError("not a valid .docx file") from None
    return _docx_xml_to_text(raw)


def pdf_text(path: Path) -> str:
    exe = shutil.which("pdftotext")
    if not exe:
        raise ResumeError(
            "pdftotext is not installed. Read the PDF with Claude's file reader, write only the career "
            "content (no contact lines) to a .txt file, and run this script on that file."
        )
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
    ap.add_argument("-o", "--output", type=Path, help="write the text here (mode 0600) instead of stdout")
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
        try:
            make_private_dir(args.output.parent)
            write_private(args.output, text)
        except (OSError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        print(f"Wrote {args.output} ({len(text)} characters)")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
