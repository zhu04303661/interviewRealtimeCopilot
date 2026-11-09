"""Extract plain text from one uploaded document.

Run as a child process (``python -m frlocal.workspace.extract``) so that a
huge or malformed file can be stopped on timeout and never blocks or crashes
the server. Prints one JSON line:

* ``{"ok": true, "chars": N}`` after writing the text to ``--output``;
* ``{"ok": false, "reason": ..., "message": ..., "detail": ...}`` otherwise.

``reason`` is one of ``unsupported_type``, ``empty_text``,
``too_many_characters`` or ``parse_failed``; the app shows a matching
"Couldn't prepare" row.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import unicodedata
import zipfile
from pathlib import Path

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
TEXT_TYPES = {"text/plain", "text/markdown"}


class PreparationError(Exception):
    def __init__(self, reason: str, message: str, detail: str | None = None) -> None:
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.detail = detail


def document_format(filename: str, content_type: str) -> str | None:
    extension = Path(filename or "").suffix.lower()
    if content_type == "application/pdf" or extension == ".pdf":
        return "pdf"
    if content_type == DOCX_TYPE or extension == ".docx":
        return "docx"
    if content_type in TEXT_TYPES or extension in (".txt", ".md"):
        return "text"
    return None


def normalize(text: str) -> str:
    """Unify line endings, trim trailing spaces and squeeze blank runs."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t\f\v]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def too_many(max_chars: int) -> PreparationError:
    return PreparationError("too_many_characters", f"The file has more than {max_chars:,} characters of text.")


def pdf_text(path: Path, max_chars: int) -> str:
    import pypdfium2 as pdfium  # imported lazily: only PDF jobs pay for it

    document = pdfium.PdfDocument(str(path))
    try:
        pages: list[str] = []
        length = 0
        for index in range(len(document)):
            page = document[index]
            textpage = page.get_textpage()
            try:
                text = textpage.get_text_bounded()
            finally:
                textpage.close()
                page.close()
            length += len(text)
            if length > max_chars:
                raise too_many(max_chars)
            pages.append(text)
    finally:
        document.close()
    # PDF fonts often map CJK characters to compatibility code points
    # (for example the Kangxi radical "⽂" for "文"); NFKC folds them back.
    return unicodedata.normalize("NFKC", "\n\n".join(pages))


def word_xml_text(xml: str) -> str:
    xml = re.sub(r"<w:tab\b[^>]*/>", "\t", xml)
    xml = re.sub(r"<w:(?:br|cr)\b[^>]*/>", "\n", xml)
    xml = xml.replace("</w:p>", "\n")
    xml = re.sub(r"<w:delText\b[^>]*>.*?</w:delText>", "", xml, flags=re.S)
    return html.unescape(re.sub(r"<[^>]+>", "", xml))


def docx_text(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        if "word/document.xml" not in names:
            raise PreparationError("parse_failed", "The DOCX file has no document body.")
        parts = ["word/document.xml"] + sorted(n for n in names if re.fullmatch(r"word/(footnotes|endnotes)\.xml", n))
        return "\n\n".join(word_xml_text(archive.read(name).decode("utf-8")) for name in parts)


def plain_text(path: Path, max_chars: int) -> str:
    if path.stat().st_size > max_chars * 4:  # UTF-8 uses at most four bytes per character
        raise too_many(max_chars)
    try:
        text = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        raise PreparationError("parse_failed", "The text file is not readable text.") from None
    if "\0" in text:
        raise PreparationError("parse_failed", "The text file is not readable text.")
    return text


def extract(source: Path, filename: str, content_type: str, max_chars: int) -> str:
    kind = document_format(filename, content_type)
    if kind is None:
        raise PreparationError("unsupported_type", "Use a PDF, DOCX, TXT or Markdown file.")
    try:
        if kind == "pdf":
            text = pdf_text(source, max_chars)
        elif kind == "docx":
            text = docx_text(source)
        else:
            text = plain_text(source, max_chars)
    except PreparationError:
        raise
    except Exception as error:  # any parser failure means the file is unreadable to us
        raise PreparationError("parse_failed", "The file could not be read.", f"{type(error).__name__}: {error}"[:300]) from None
    text = normalize(text)
    if not text:
        raise PreparationError("empty_text", "The PDF has no text. It may be a scanned image." if kind == "pdf" else "The file has no text.")
    if len(text) > max_chars:
        raise too_many(max_chars)
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--filename", required=True)
    parser.add_argument("--content-type", default="")
    parser.add_argument("--max-chars", type=int, required=True)
    args = parser.parse_args(argv)
    partial = args.output.with_name(args.output.name + ".partial")
    try:
        text = extract(args.source, args.filename, args.content_type, args.max_chars)
        fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(partial, args.output)
        result = {"ok": True, "chars": len(text)}
    except PreparationError as error:
        partial.unlink(missing_ok=True)
        result = {"ok": False, "reason": error.reason, "message": error.message, "detail": error.detail}
    sys.stdout.write(json.dumps(result) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
