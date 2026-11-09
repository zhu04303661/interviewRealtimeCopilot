"""Document preparation: formats, failures, limits, imports and resuming after a restart."""

from __future__ import annotations

import json
import zipfile
from dataclasses import replace

import pytest

from frlocal.app import build_app
from frlocal.workspace.documents import DocumentService
from frlocal.workspace.extract import PreparationError, extract
from frlocal.workspace.records import PREPARER_VERSION
from frlocal.workspace.store import WorkspaceStore


def pdf_fixture(lines: list[str], *, per_page: int = 48, pad_bytes: int = 0) -> bytes:
    """A minimal multi-page PDF with Helvetica text (48 lines per page)."""
    pages = [lines[i:i + per_page] for i in range(0, max(len(lines), 1), per_page)] or [[]]
    font = 3 + len(pages) * 2
    objects = ["<< /Type /Catalog /Pages 2 0 R >>",
               "<< /Type /Pages /Kids [" + " ".join(f"{3 + i * 2} 0 R" for i in range(len(pages))) + f"] /Count {len(pages)} >>"]
    for index, page in enumerate(pages):
        escaped = [line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)") for line in page]
        stream = ("BT /F1 12 Tf 72 720 Td 14 TL " + " ".join(f"({line}) Tj T*" for line in escaped) + " ET") if page else ""
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 {font} 0 R >> >> /Contents {4 + index * 2} 0 R >>")
        objects.append(f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")
    objects.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    if pad_bytes:
        objects.append(f"<< /Length {pad_bytes} >>\nstream\n{' ' * pad_bytes}\nendstream")
    body = "%PDF-1.4\n"
    offsets = []
    for index, obj in enumerate(objects):
        offsets.append(len(body))
        body += f"{index + 1} 0 obj\n{obj}\nendobj\n"
    xref = len(body)
    body += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n" + "".join(f"{o:010d} 00000 n \n" for o in offsets)
    body += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n"
    return body.encode("latin-1")


def docx_fixture(path, paragraphs: list[str]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
        archive.writestr("word/document.xml", f'<w:document xmlns:w="w"><w:body>{body}</w:body></w:document>')


# ── extraction (runs in-process here; the service runs it in a child process) ──


def test_extracts_pdf_docx_markdown(tmp_path):
    pdf = tmp_path / "cv.pdf"
    pdf.write_bytes(pdf_fixture(["Jane Doe", "Led the payments migration (2024)"]))
    assert extract(pdf, "cv.pdf", "application/pdf", 1000) == "Jane Doe\nLed the payments migration (2024)"
    docx = tmp_path / "notes.docx"
    docx_fixture(docx, ["STAR story: on-call &amp; incident review", "Second paragraph"])
    assert extract(docx, "notes.docx", "", 1000) == "STAR story: on-call & incident review\nSecond paragraph"
    md = tmp_path / "plan.md"
    md.write_bytes(b"# Plan\r\n\r\n\r\n\r\nAsk about the team.   \r\n")
    assert extract(md, "plan.md", "text/markdown", 1000) == "# Plan\n\nAsk about the team."


@pytest.mark.parametrize(("name", "content", "reason"), [
    ("scan.pdf", pdf_fixture([]), "empty_text"),
    ("letter.rtf", b"{\\rtf1 hello}", "unsupported_type"),
    ("binary.txt", b"\xff\xfe\x00", "parse_failed"),
    ("broken.pdf", b"%PDF-1.4 not really", "parse_failed"),
    ("broken.docx", b"PK not a zip", "parse_failed"),
])
def test_unreadable_files_are_reported_with_a_reason(tmp_path, name, content, reason):
    path = tmp_path / name
    path.write_bytes(content)
    with pytest.raises(PreparationError) as error:
        extract(path, name, "", 1000)
    assert error.value.reason == reason


def test_text_limit_applies_to_every_format(tmp_path):
    pdf = tmp_path / "long.pdf"
    pdf.write_bytes(pdf_fixture([f"Line {i} of the physical downlink shared channel" for i in range(200)]))
    with pytest.raises(PreparationError) as error:
        extract(pdf, "long.pdf", "", 2000)
    assert error.value.reason == "too_many_characters"
    big = tmp_path / "big.txt"
    with open(big, "wb") as handle:
        handle.truncate(9000)
    with pytest.raises(PreparationError) as error:
        extract(big, "big.txt", "text/plain", 2000)
    assert error.value.reason == "too_many_characters"


def test_pdf_compatibility_characters_are_normalised(tmp_path):
    # pdfium returns what the PDF maps; NFKC must fold compatibility forms such as "⽂".
    from frlocal.workspace.extract import normalize
    import unicodedata
    assert unicodedata.normalize("NFKC", "中⽂") == "中文"
    assert normalize("a  \n\n\n\nb\r\n") == "a\n\nb"


# ── the preparation service ───────────────────────────────────────────────────


async def test_import_prepares_in_a_child_process_and_records_status(signed_in, tmp_path):
    b = signed_in
    long_lines = [f"Line {i} of the physical downlink shared channel specification text" for i in range(2000)]
    files = {
        "cv.pdf": pdf_fixture(["Jane Doe", "Payments migration"]),
        "spec.pdf": pdf_fixture(long_lines, pad_bytes=12 * 1024 * 1024),
        "scan.pdf": pdf_fixture([]),
        "letter.rtf": b"{\\rtf1}",
    }
    docs = {}
    for name, content in files.items():
        (tmp_path / name).write_bytes(content)
        kind = "resume" if name == "cv.pdf" else "material"
        docs[name] = await b.documents.import_file("admin", kind, str(tmp_path / name), name, None)
        assert docs[name]["status"] == "preparing"
    assert docs["spec.pdf"]["byte_size"] > 12 * 1024 * 1024
    await b.documents.wait_idle()
    listed = {d["filename"]: d for d in (await b.call("GET", "/api/v3/documents"))["documents"]}
    assert listed["cv.pdf"]["status"] == "ready" and listed["cv.pdf"]["preparer"] == PREPARER_VERSION
    assert listed["spec.pdf"]["text_chars"] > 100_000
    assert (listed["scan.pdf"]["status"], listed["scan.pdf"]["failure_reason"]) == ("unprepared", "empty_text")
    assert listed["letter.rtf"]["failure_reason"] == "unsupported_type"
    _, text = await b.documents.read_text("admin", docs["cv.pdf"]["document_id"])
    assert text == "Jane Doe\nPayments migration"
    assert (await b.documents.read_text("admin", docs["scan.pdf"]["document_id"]))[1] is None


async def test_import_enforces_the_500_mb_limit_without_reading_the_file(signed_in, tmp_path):
    huge = tmp_path / "huge.txt"
    with open(huge, "wb") as handle:
        handle.truncate(500 * 1024 * 1024 + 1)
    response = await signed_in.call("POST", "/local/documents/import", expect=422, json={
        "kind": "material", "filePath": str(huge), "filename": "huge.txt", "contentType": "text/plain"})
    assert "at most 500 MB" in response["detail"]
    big = tmp_path / "big.txt"
    with open(big, "wb") as handle:
        handle.truncate(120 * 1024 * 1024)
    doc = await signed_in.call("POST", "/local/documents/import", json={
        "kind": "material", "filePath": str(big), "filename": "big.txt", "contentType": "text/plain"})
    assert doc["byte_size"] == 120 * 1024 * 1024
    await signed_in.documents.wait_idle()
    listed = (await signed_in.call("GET", "/api/v3/documents"))["documents"]
    assert listed[0]["failure_reason"] == "too_many_characters"


async def test_restart_resumes_pending_and_retries_older_rejections(signed_in, tmp_path):
    b = signed_in
    (tmp_path / "a.md").write_text("alpha")
    (tmp_path / "b.md").write_text("beta")
    (tmp_path / "c.md").write_text("gamma")
    ids = [(await b.documents.import_file("admin", "material", str(tmp_path / n), n, "text/markdown"))["document_id"]
           for n in ("a.md", "b.md", "c.md")]
    await b.documents.wait_idle()
    path = b.settings.workspace_dir / "admin" / "workspace.json"
    state = json.loads(path.read_text())
    state["documents"][ids[0]]["status"] = "preparing"                                 # app quit mid-way
    del state["documents"][ids[1]]["text_chars"]                                       # prepared by nothing yet
    state["documents"][ids[2]].update(status="unprepared", failure_reason="parse_failed", preparer=2)  # older preparer
    path.write_text(json.dumps(state))

    store = WorkspaceStore(b.settings.workspace_dir)
    service = DocumentService(store, b.settings.limits)
    async with store.open("admin"):
        pass
    await service.wait_idle()
    async with store.open("admin") as workspace:
        statuses = [workspace.state["documents"][i]["status"] for i in ids]
    assert statuses == ["ready", "ready", "ready"]


async def test_preparation_times_out_and_is_reported(signed_in, tmp_path, monkeypatch):
    b = signed_in
    slow = DocumentService(WorkspaceStore(b.settings.workspace_dir), replace(b.settings.limits, document_prepare_timeout_s=0.01))
    (tmp_path / "x.pdf").write_bytes(pdf_fixture(["text"] * 3000))
    doc = await slow.import_file("admin", "material", str(tmp_path / "x.pdf"), "x.pdf", None)
    await slow.wait_idle()
    async with slow.store.open("admin") as workspace:
        record = workspace.state["documents"][doc["document_id"]]
    assert (record["status"], record["failure_reason"]) == ("unprepared", "timed_out")


def test_app_builds_with_default_settings(tmp_path):
    from .conftest import make_settings
    assert build_app(make_settings(tmp_path)) is not None
