"""Library documents: import, upload, preparation and reading prepared text.

A document moves through these states (the app polls while it is preparing):

    preparing ──extract ok──▶ ready        text in files/<id>.txt
              └─extract failed▶ unprepared  failure_reason / failure_detail

Preparation runs one file at a time in a child process (see ``extract.py``)
with a time limit. Documents still preparing when the app quit, ready ones
without prepared text, and ones rejected by an older preparer are queued again
the first time their account's workspace is opened.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import sys
from pathlib import Path
from typing import Any

from ..config import Limits
from ..errors import fail
from .records import PREPARER_VERSION, needs_preparation, new_id, now
from .store import OBJECT_ID, Workspace, WorkspaceStore

log = logging.getLogger(__name__)

DOCUMENT_KINDS = ("resume", "material")


class DocumentService:
    def __init__(self, store: WorkspaceStore, limits: Limits) -> None:
        self.store = store
        self.limits = limits
        self._queue_slot = asyncio.Semaphore(1)
        self._in_flight: dict[tuple[str, str], asyncio.Task] = {}
        store.on_first_load(self._resume_pending)

    # -- records ---------------------------------------------------------------

    def new_record(self, kind: Any, filename: str, content_type: str | None, size: int) -> dict[str, Any]:
        """Validate an incoming file and describe it as a library document."""
        if kind not in DOCUMENT_KINDS:
            fail(422, "Choose a resume or material.")
        if not size or size > self.limits.max_document_bytes:
            fail(422, f"Choose a nonempty file of at most {self.limits.max_document_bytes // (1024 * 1024)} MB.")
        return {
            "document_id": new_id(), "kind": kind, "status": "preparing", "filename": filename, "display_name": None,
            "created_at": now(), "content_type": content_type or "application/octet-stream", "byte_size": size,
        }

    async def import_file(self, username: str, kind: Any, file_path: str, filename: str, content_type: str | None) -> dict[str, Any]:
        """Copy a file the user picked into the workspace (no in-memory buffering)."""
        source = Path(file_path)
        if not source.is_file():
            fail(422, "Choose a file.")
        doc = self.new_record(kind, filename, content_type, source.stat().st_size)
        files = self.store.account_path(username) / "files"
        files.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = files / doc["document_id"]
        partial = target.with_name(target.name + ".partial")
        try:
            await asyncio.to_thread(shutil.copyfile, source, partial)
            partial.chmod(0o600)
            doc["byte_size"] = partial.stat().st_size
            self.new_record(kind, filename, content_type, doc["byte_size"])  # the file may have grown while copying
            partial.replace(target)
            async with self.store.open(username) as workspace:
                workspace.state["documents"][doc["document_id"]] = doc
                workspace.changed()
        except BaseException:
            partial.unlink(missing_ok=True)
            target.unlink(missing_ok=True)
            raise
        self.prepare(username, doc["document_id"])
        return doc

    def add_uploaded(self, workspace: Workspace, doc: dict[str, Any]) -> None:
        """Register a document whose bytes are already in ``files/`` (multipart upload)."""
        workspace.state["documents"][doc["document_id"]] = doc
        workspace.changed()
        self.prepare(workspace.username, doc["document_id"])

    async def read_text(self, username: str, document_id: str) -> tuple[dict[str, Any], str | None] | None:
        """A document's metadata and prepared text (``None`` text until it is ready)."""
        async with self.store.open(username) as workspace:
            doc = workspace.state["documents"].get(document_id)
            if not doc or not OBJECT_ID.match(document_id):
                return None
            if doc.get("status") != "ready" or not isinstance(doc.get("text_chars"), int):
                return dict(doc), None
            text_path = workspace.files / f"{document_id}.txt"
        text = await asyncio.to_thread(text_path.read_text, encoding="utf-8")
        return dict(doc), text

    # -- preparation -------------------------------------------------------------

    def _resume_pending(self, workspace: Workspace):
        pending = []
        for doc in workspace.state["documents"].values():
            if not needs_preparation(doc):
                continue
            if doc.get("status") != "preparing":
                doc["status"] = "preparing"
                workspace.changed()
            pending.append(doc["document_id"])
        username = workspace.username
        return [lambda doc_id=doc_id: self.prepare(username, doc_id) for doc_id in pending]

    def prepare(self, username: str, document_id: str) -> asyncio.Task:
        """Start (or join) preparation of one document."""
        key = (username, document_id)
        task = self._in_flight.get(key)
        if task is None:
            task = asyncio.get_running_loop().create_task(self._run(username, document_id))
            self._in_flight[key] = task
            task.add_done_callback(lambda _: self._in_flight.pop(key, None))
        return task

    async def wait_idle(self) -> None:
        """Wait for every running preparation (used by tests and shutdown)."""
        while self._in_flight:
            await asyncio.gather(*list(self._in_flight.values()), return_exceptions=True)

    async def _run(self, username: str, document_id: str) -> None:
        try:
            async with self.store.open(username) as workspace:
                doc = workspace.state["documents"].get(document_id)
                if not doc or doc.get("status") != "preparing":
                    return
                doc = dict(doc)
                files = workspace.files
            async with self._queue_slot:
                outcome = await self._extract(files / document_id, files / f"{document_id}.txt", doc)
            if not outcome.get("ok"):
                log.warning("Document preparation failed: %s %s", outcome.get("reason"), outcome.get("detail") or "")
            async with self.store.open(username) as workspace:
                record = workspace.state["documents"].get(document_id)
                if not record or record.get("status") != "preparing":
                    return
                if outcome.get("ok"):
                    record.update(status="ready", text_chars=outcome["chars"], prepared_at=now(), preparer=PREPARER_VERSION)
                    record.pop("failure_reason", None)
                    record.pop("failure_detail", None)
                else:
                    (workspace.files / f"{document_id}.txt").unlink(missing_ok=True)
                    record.update(status="unprepared", failure_reason=outcome.get("reason", "parse_failed"),
                                  failure_detail=outcome.get("message"), preparer=PREPARER_VERSION)
                workspace.changed()
        except Exception:
            log.exception("Could not prepare document %s", document_id)

    async def _extract(self, source: Path, output: Path, doc: dict[str, Any]) -> dict[str, Any]:
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "frlocal.workspace.extract",
            "--source", str(source), "--output", str(output), "--filename", doc.get("filename") or "",
            "--content-type", doc.get("content_type") or "", "--max-chars", str(self.limits.max_document_text_chars),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), self.limits.document_prepare_timeout_s)
        except TimeoutError:
            process.kill()
            await process.wait()
            output.with_name(output.name + ".partial").unlink(missing_ok=True)
            return {"ok": False, "reason": "timed_out", "message": "Preparing the file took too long."}
        except asyncio.CancelledError:
            process.kill()
            raise
        try:
            return json.loads(stdout.decode().strip().splitlines()[-1])
        except (IndexError, ValueError):
            return {"ok": False, "reason": "parse_failed", "message": "The file could not be read.",
                    "detail": stderr.decode(errors="replace")[-300:] or f"exit code {process.returncode}"}
