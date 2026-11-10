"""The workspace HTTP API: every vendor endpoint the original app calls.

The Electron bridge forwards the app's requests for
``https://final-round-recovered.invalid/api/...`` (and the signed upload URLs
``/local-files/<id>`` and ``/local-recordings/<id>``) to this server. Paths,
methods and response shapes match what the app was built against:

* ``v3/...`` endpoints answer with the resource itself;
* the older endpoints answer with ``{"code": 0, "data": ...}``;
* errors answer with ``{"detail": "..."}`` and an HTTP status.

All state belongs to the signed-in local account.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any

from aiohttp import BodyPartReader, web

from ..accounts import AccountService
from ..config import Settings
from ..errors import ApiError, fail
from ..openai import OpenAI, ProviderError
from ..realtime.engine import RealtimeEngine
from ..screen import analyze_screen
from .documents import DocumentService
from .records import (EMPTY_GOAL_MEMORY, LOCAL_PLAN, goal_documents, legacy_goal, legacy_session, lookup, new_id, now, page,
                      pick, report_of, required_text, visible_documents, windowed)
from .store import OBJECT_ID, Workspace, WorkspaceStore

log = logging.getLogger(__name__)

PUBLIC_ORIGIN = "https://final-round-recovered.invalid"
SCREENSHOT_TYPES = ("image/png", "image/jpeg", "image/webp")


def raw(value: Any = None) -> web.Response:
    return web.json_response({} if value is None else value, dumps=lambda v: json.dumps(v, ensure_ascii=False))


def envelope(data: Any = None) -> web.Response:
    return raw({"code": 0, "data": {} if data is None else data})


async def json_fields(request: web.Request) -> dict[str, Any]:
    try:
        value = await request.json()
    except ValueError:
        fail(400, "Expected a JSON request body.")
    if not isinstance(value, dict):
        fail(400, "Expected a JSON object.")
    return value


class Upload:
    """The parts of a multipart form: text fields and at most one file."""

    def __init__(self) -> None:
        self.fields: dict[str, str] = {}
        self.filename: str | None = None
        self.content_type: str = ""
        self.size = 0
        self.data: bytes | None = None      # small files
        self.path: Path | None = None       # large files streamed to disk


async def read_multipart(request: web.Request, *, max_bytes: int, to_path: Path | None = None) -> Upload:
    """Read a multipart form, streaming the file to ``to_path`` when given."""
    try:
        reader = await request.multipart()
    except (AssertionError, ValueError):
        fail(400, "Expected a file upload.")
    upload = Upload()
    while (part := await reader.next()) is not None:
        if not isinstance(part, BodyPartReader):
            continue
        if part.filename is None:
            upload.fields[part.name or ""] = (await part.text())[:1000]
            continue
        upload.filename, upload.content_type = part.filename, part.headers.get("Content-Type", "")
        chunks: list[bytes] = []
        handle = open(to_path, "wb") if to_path else None
        try:
            while chunk := await part.read_chunk(1024 * 1024):
                upload.size += len(chunk)
                if upload.size > max_bytes:
                    fail(422, f"Choose a nonempty file of at most {max_bytes // (1024 * 1024)} MB.")
                if handle:
                    handle.write(chunk)
                else:
                    chunks.append(chunk)
        finally:
            if handle:
                handle.close()
        if to_path:
            to_path.chmod(0o600)
            upload.path = to_path
        else:
            upload.data = b"".join(chunks)
    return upload


class WorkspaceApi:
    def __init__(self, settings: Settings, store: WorkspaceStore, documents: DocumentService, accounts: AccountService,
                 engine: RealtimeEngine, openai: OpenAI) -> None:
        self.settings = settings
        self.store = store
        self.documents = documents
        self.accounts = accounts
        self.engine = engine
        self.openai = openai
        self._closing: dict[str, asyncio.Task] = {}
        self._preparing_reports: set[str] = set()
        self._tasks: set[asyncio.Task] = set()

    # ── entry point ─────────────────────────────────────────────────────────

    def username(self) -> str:
        session = self.accounts.current()
        if not session:
            fail(401, "Sign in locally to continue.")
        return session.account.username

    async def handle(self, request: web.Request) -> web.StreamResponse:
        try:
            username = self.username()
            path = re.sub(r"^/(?:api/)?", "", request.path)
            parts = path.split("/") if path else []
            method = request.method
            if parts == ["v3", "sessions"] and method == "POST":
                return await self.start_session(username, request)
            if len(parts) == 4 and parts[:2] == ["v3", "sessions"] and method == "POST":
                if parts[3] == "end":
                    return await self.end_session(username, parts[2])
                if parts[3] == "screen":
                    return await self.screen(username, request, parts[2])
            if parts[:2] == ["v3", "documents"] and len(parts) == 2 and method == "POST":
                return await self.upload_document(username, request)
            async with self.store.open(username) as workspace:
                return await self.route(workspace, request, parts)
        except ApiError as error:
            return web.json_response({"detail": error.detail}, status=error.status)
        except Exception:
            log.exception("Workspace request failed: %s %s", request.method, request.path)
            return web.json_response({"detail": "The local workspace could not complete this request."}, status=500)

    async def route(self, workspace: Workspace, request: web.Request, parts: list[str]) -> web.StreamResponse:
        state, params, method = workspace.state, request.query, request.method
        root, resource, rest = (parts + ["", ""])[0], (parts + ["", ""])[1], parts[2:]
        if root == "v3" and resource == "goals":
            return await self.goal(workspace, request, rest)
        if root == "v3" and resource == "documents":
            return await self.document(workspace, request, rest)
        if root == "v3" and resource == "playbooks":
            return await self.playbook(workspace, request, rest)
        if root == "v3" and resource == "sessions" and not rest and method == "GET":
            # History: every session, newest first, with its Debrief status (no report bodies).
            rows = [{k: v for k, v in self._report(workspace.username, state, session).items() if k != "report"}
                    for session in reversed(list(state["sessions"].values()))]
            # Newest first; sessions created in the same instant keep creation order (stable sort).
            return raw({"sessions": sorted(rows, key=lambda r: r.get("created_at") or "", reverse=True)})
        if root == "v3" and resource == "sessions":
            return await self.session(workspace, request, rest)
        if root == "v3" and resource == "voice-sample":
            return await self.voice_sample(workspace, request)
        if root == "local-recordings":
            return await self.blob(workspace, request, state["recordings"], resource, recording=True)
        if root == "local-files":
            return await self.blob(workspace, request, state["files"], resource)

        key = f"{method} {'/'.join(parts)}"
        username = workspace.username
        if key == "DELETE v3/me":
            fail(422, "Local account deletion is unavailable.")
        if key == "GET v3/me/prefs":
            return raw(state["prefs"])
        if key == "PUT v3/me/prefs":
            state["prefs"].update(pick(await json_fields(request), [
                "language", "coding_language", "default_language", "default_coding_language", "default_playbook_id"]))
            workspace.changed()
            return raw(state["prefs"])
        if key == "GET v3/me/consents":
            return raw(state["consents"])
        if key == "PUT v3/me/consents":
            state["consents"].update(pick(await json_fields(request), ["share_data", "ai_training"]))
            workspace.changed()
            return raw(state["consents"])
        if key == "GET v3/memory":
            return raw({"version": 0, "profile": {"facts": [], "preferences": []}, "wiped_at": state.get("memoryWipedAt")})
        if key == "DELETE v3/memory":
            state["memoryWipedAt"] = now()
            workspace.changed()
            return raw({"deleted": 0})
        if key == "DELETE v3/memory/claims":
            return raw({"removed": False})
        if key == "GET core/payment/get-plans":
            return envelope({"plans": [LOCAL_PLAN]})
        if key == "GET core/payment/get_subscription":
            return envelope({"has_subscription": False, "local_workspace": True})
        if key == "POST core/payment/offer/spin":
            return envelope({"offer": None, "can_spin": False})
        if key == "GET goal/list":
            return envelope(page([legacy_goal(g) for g in state["goals"].values() if g.get("status") != "archived"], params))
        if key == "GET file/list":
            return envelope(page([{"id": d["document_id"], "type": d["kind"], "filename": d["filename"],
                                   "original_filename": d["filename"]} for d in visible_documents(state)], params))
        if key == "GET web-token/google-cloud-storage-signed-url":
            filename = required_text(params.get("fileName"), "File name")
            item = next((f for f in state["files"].values() if f.get("filename") == filename), None) or {
                "id": new_id(), "filename": filename, "content_type": params.get("fileType") or "application/octet-stream"}
            state["files"][item["id"]] = item
            workspace.changed()
            return envelope({"signedUrl": f"{PUBLIC_ORIGIN}/local-files/{item['id']}", "originalName": filename})
        if key == "GET web-token/google-cloud-storage-access-url":
            item = next((f for f in state["files"].values() if f.get("filename") == params.get("fileName") and f.get("byte_size")), None)
            if not item:
                fail(404, "Local file was not found.")
            return envelope({"url": f"{PUBLIC_ORIGIN}/local-files/{item['id']}"})
        if key == "GET model-list":
            return envelope([{"id": self.settings.models.coaching, "name": "OpenAI GPT-5.4 mini"}] if self.openai.api_key() else [])
        if key == "GET preference/get":
            return envelope(state["preferences"])
        if key == "POST preference/update":
            state["preferences"].update((await json_fields(request)).get("data") or {})
            workspace.changed()
            return envelope(state["preferences"])
        if key == "GET session/get-last-used-config":
            return envelope(state["lastUsed"])
        if key == "GET session/get-by-id":
            return envelope(legacy_session(lookup(state["sessions"], params.get("id"), "Session")))
        if key == "POST session/update-fields":
            body = await json_fields(request)
            record = lookup(state["sessions"], body.get("id"), "Session")
            record.setdefault("fields", {}).update(body.get("data") or {})
            state["lastUsed"] = legacy_session(record)
            workspace.changed()
            return envelope()
        if key == "GET session/get-active-list":
            return envelope(page([legacy_session(s) for s in state["sessions"].values() if not s.get("ended_at")], params))
        if key in ("GET session/get-ready-list", "GET report/list"):
            ended = [legacy_session(s) for s in reversed(list(state["sessions"].values())) if s.get("ended_at")]
            return envelope(page(ended, params))
        if key == "GET session/get-archived-list":
            return envelope(page([], params))
        if key == "GET v3/reports":
            goal_id = params.get("goal_id")
            reports = [self._report(username, state, s) for s in reversed(list(state["sessions"].values()))
                       if s.get("ended_at") and (not goal_id or s.get("goal_id") == goal_id)]
            return raw({"reports": windowed(reports, params)})
        if key == "GET report/doc":
            return envelope(self._report(username, state, lookup(state["sessions"], params.get("sessionId"), "Session")))
        if key == "GET report/transcript-analyze":
            session_id = params.get("sessionId")
            lookup(state["sessions"], session_id, "Session")
            return envelope({"segments": state["transcripts"].get(session_id, [])})
        fail(501, "This operation is unavailable in the local workspace.")

    def _report(self, username: str, state: dict, session: dict) -> dict:
        key = f"{username}:{session['session_id']}"
        return report_of(session, state["transcripts"].get(session["session_id"]), key in self._preparing_reports)

    # ── goals ───────────────────────────────────────────────────────────────

    async def goal(self, workspace: Workspace, request: web.Request, parts: list[str]) -> web.Response:
        state, method = workspace.state, request.method
        goal_id, action, sub_id = (parts + [None, None, None])[:3]
        if not goal_id and method == "GET":
            include_archived = request.query.get("include_archived") == "true"
            return raw({"goals": [g for g in state["goals"].values() if include_archived or g.get("status") != "archived"]})
        if not goal_id and method == "POST":
            body = await json_fields(request)
            goal = {**pick(body, ["company_detail", "job_description"]), "goal_id": new_id(),
                    "role": required_text(body.get("role"), "Role"), "company": required_text(body.get("company"), "Company"),
                    "status": "active", "created_at": now(), "updated_at": now(), "defaults": {}}
            state["goals"][goal["goal_id"]] = goal
            workspace.changed()
            return raw(goal)
        goal = lookup(state["goals"], goal_id, "Goal")
        if not action and method == "GET":
            return raw(goal)
        if action == "memory":
            if method == "GET" and not sub_id:
                return raw(EMPTY_GOAL_MEMORY)
            if method == "DELETE" and sub_id == "claims":
                return raw({"removed": False})
        if action in ("documents", "resume"):
            if method == "GET" and action == "documents":
                return raw(goal_documents(state, goal_id))
            association = state["associations"].setdefault(goal_id, {"resume": None, "materials": []})
            if method == "POST" and action == "documents":
                document_id = (await json_fields(request)).get("document_id")
                document = lookup(state["documents"], document_id, "Document")
                if document.get("archived_at") or document.get("kind") == "resume":
                    fail(422, "Choose an active material.")
                if document_id not in association["materials"]:
                    association["materials"].append(document_id)
            elif method == "DELETE" and action == "documents" and sub_id:
                association["materials"] = [value for value in association["materials"] if value != sub_id]
            elif method == "PUT" and action == "resume":
                document_id = (await json_fields(request)).get("document_id")
                if document_id is not None:
                    document = lookup(state["documents"], document_id, "Resume")
                    if document.get("archived_at") or document.get("kind") != "resume":
                        fail(422, "Choose an active resume.")
                association["resume"] = document_id
            else:
                fail(405, "This goal operation is unavailable.")
            workspace.changed()
            return raw(goal_documents(state, goal_id))
        if not action and method == "PUT":
            body = await json_fields(request)
            goal.update(pick(body, ["company_detail", "job_description"]),
                        role=required_text(body.get("role"), "Role"), company=required_text(body.get("company"), "Company"))
        elif action == "archive" and method == "POST":
            goal["status"] = "archived"
            goal.setdefault("archived_at", now())
        elif action == "defaults" and method == "PUT":
            goal["defaults"] = pick(await json_fields(request), ["playbook_id", "language", "coding_language"])
        elif action == "lifecycle" and method == "PUT":
            goal.update(pick(await json_fields(request), ["status", "outcome", "next_interview_at"]))
        else:
            fail(405, "This goal operation is unavailable.")
        goal["updated_at"] = now()
        workspace.changed()
        return raw(goal)

    # ── documents ───────────────────────────────────────────────────────────

    async def upload_document(self, username: str, request: web.Request) -> web.Response:
        """Multipart upload (kept for compatibility; the app normally imports by file path)."""
        files = self.store.account_path(username) / "files"
        files.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = files / f"upload-{new_id()}.partial"
        try:
            upload = await read_multipart(request, max_bytes=self.settings.limits.max_document_bytes, to_path=temporary)
            if not upload.filename or not upload.path:
                fail(422, "Choose a file.")
            doc = self.documents.new_record(upload.fields.get("kind"), upload.filename, upload.content_type, upload.size)
            temporary.replace(files / doc["document_id"])
            async with self.store.open(username) as workspace:
                self.documents.add_uploaded(workspace, doc)
            return raw(doc)
        finally:
            temporary.unlink(missing_ok=True)

    async def document(self, workspace: Workspace, request: web.Request, parts: list[str]) -> web.Response:
        state, method = workspace.state, request.method
        document_id, action = (parts + [None, None])[:2]
        if not document_id and method == "GET":
            kind = request.query.get("kind")
            return raw({"documents": windowed([d for d in visible_documents(state) if not kind or d["kind"] == kind], request.query)})
        doc = lookup(state["documents"], document_id, "Document")
        if action == "archive" and method == "POST":
            doc.setdefault("archived_at", now())
        elif action == "name" and method == "PUT":
            name = (await json_fields(request)).get("display_name")
            if name is not None and not isinstance(name, str):
                fail(422, "Enter a document name.")
            doc["display_name"] = (name or "").strip()[:255] or None
        elif action == "profile":
            if method == "GET":
                return raw(state["documentProfiles"].get(document_id, {}))
            if method != "PUT":
                fail(405, "This document operation is unavailable.")
            state["documentProfiles"][document_id] = await json_fields(request)
            workspace.changed()
            return raw(state["documentProfiles"][document_id])
        else:
            fail(405, "This document operation is unavailable.")
        workspace.changed()
        return raw(doc)

    # ── playbooks ───────────────────────────────────────────────────────────

    async def playbook(self, workspace: Workspace, request: web.Request, parts: list[str]) -> web.Response:
        state, method = workspace.state, request.method
        playbook_id, action = (parts + [None, None])[:2]
        if not playbook_id and method == "GET":
            return raw({"playbooks": [p for p in state["playbooks"].values() if not p.get("archived_at")]})
        if not playbook_id and method == "POST":
            body = await json_fields(request)
            playbook = {"playbook_id": new_id(), "name": required_text(body.get("name"), "Name"), "mode": "structured",
                        "style": None, "instructions_template": None, "version": 1, "created_at": now(), "updated_at": now(),
                        **pick(body, ["mode", "style", "instructions_template"])}
            state["playbooks"][playbook["playbook_id"]] = playbook
            workspace.changed()
            return raw(playbook)
        playbook = lookup(state["playbooks"], playbook_id, "Playbook")
        if not action and method == "PUT":
            body = await json_fields(request)
            if body.get("expected_version") != playbook["version"]:
                fail(409, "The playbook was edited. Reload its latest version.")
            playbook.update(pick(body, ["mode", "style", "instructions_template"]), name=required_text(body.get("name"), "Name"),
                            version=playbook["version"] + 1, updated_at=now())
        elif action == "archive" and method == "POST":
            playbook.setdefault("archived_at", now())
        else:
            fail(405, "This playbook operation is unavailable.")
        workspace.changed()
        return raw(playbook)

    # ── interview sessions ──────────────────────────────────────────────────

    async def start_session(self, username: str, request: web.Request) -> web.Response:
        body = await json_fields(request)
        async with self.store.open(username) as workspace:
            goal = dict(lookup(workspace.state["goals"], body.get("goal_id"), "Goal"))
        if goal.get("status") == "archived":
            fail(422, "Choose an active goal.")
        if body.get("topology") not in ("general", "phone", "mock"):
            fail(422, "Choose a supported interview mode.")
        session = {"session_id": new_id(), "goal_id": goal["goal_id"], "company": goal["company"], "role": goal["role"],
                   "topology": body["topology"], "config": body.get("config") or {}, "fields": {}, "created_at": now(), "ended_at": None}
        try:
            realtime = self.engine.create(username=username, session=session, goal=goal, ws_base=f"ws://{request.host}")
        except ProviderError as error:
            fail(422, str(error))
        async with self.store.open(username) as workspace:
            workspace.state["sessions"][session["session_id"]] = session
            workspace.state["lastUsed"] = legacy_session(session)
            workspace.changed()
        return raw({"session_id": session["session_id"], **realtime})

    async def end_session(self, username: str, session_id: str) -> web.Response:
        key = f"{username}:{session_id}"
        closing = self._closing.get(key)
        if closing is None:
            closing = asyncio.get_running_loop().create_task(self._finalize(username, session_id))
            self._closing[key] = closing
            closing.add_done_callback(lambda _: self._closing.pop(key, None))
        await asyncio.shield(closing)
        return raw()

    async def _finalize(self, username: str, session_id: str) -> None:
        async with self.store.open(username) as workspace:
            session = dict(lookup(workspace.state["sessions"], session_id, "Session"))
        if session.get("ended_at"):
            return
        ended_at = now()
        key = f"{username}:{session_id}"
        result: dict[str, Any] = {}
        try:
            result = await self.engine.end(username, {**session, "ended_at": ended_at})
            if result.get("report_task"):
                self._preparing_reports.add(key)
        finally:
            async with self.store.open(username) as workspace:
                record = lookup(workspace.state["sessions"], session_id, "Session")
                record["ended_at"] = record.get("ended_at") or ended_at
                record["end_reason"] = record.get("end_reason") or "client_request"
                if result.get("report_task"):
                    record["report_requested"] = True
                if result.get("segments"):
                    workspace.state["transcripts"][session_id] = result["segments"]
                if isinstance(result.get("questions"), list):
                    record["question_count"] = len(result["questions"])
                workspace.changed()
        task = result.get("report_task")
        if task:
            saver = asyncio.get_running_loop().create_task(self._save_report(username, session_id, task))
            self._tasks.add(saver)
            saver.add_done_callback(self._tasks.discard)

    async def _save_report(self, username: str, session_id: str, task: asyncio.Task) -> None:
        try:
            report = await task
            if report:
                async with self.store.open(username) as workspace:
                    lookup(workspace.state["sessions"], session_id, "Session")["report"] = report
                    workspace.changed()
        except Exception:
            log.exception("Could not save the report")
        finally:
            self._preparing_reports.discard(f"{username}:{session_id}")

    async def screen(self, username: str, request: web.Request, session_id: str) -> web.Response:
        async with self.store.open(username) as workspace:
            session = dict(lookup(workspace.state["sessions"], session_id, "Session"))
        if session.get("ended_at"):
            fail(409, "The interview has already ended.")
        upload = await read_multipart(request, max_bytes=self.settings.limits.max_screenshot_bytes)
        purpose, origin = upload.fields.get("purpose", "context"), upload.fields.get("origin", "manual")
        command_id = upload.fields.get("command_id") or new_id()
        if not upload.data or upload.content_type not in SCREENSHOT_TYPES:
            fail(422, "Choose a screenshot of at most 10 MB.")
        if purpose not in ("context", "solve") or origin not in ("manual", "automatic") or len(command_id) > 100:
            fail(422, "Invalid screen analysis request.")
        return raw(await analyze_screen(
            self.openai, self.settings, image=upload.data, mime=upload.content_type, purpose=purpose,
            publish=lambda analysis_id, text: self.engine.publish_screen_answer(username, session_id, analysis_id, text)))

    async def session(self, workspace: Workspace, request: web.Request, parts: list[str]) -> web.Response:
        state, method = workspace.state, request.method
        session_id, action, recording_id, operation = (parts + [None] * 4)[:4]
        session = lookup(state["sessions"], session_id, "Session")
        if action == "report" and method == "GET":
            return raw(self._report(workspace.username, state, session))
        if action == "transcript" and method == "GET":
            return raw({"segments": state["transcripts"].get(session_id, [])})
        if action == "recordings" and method == "GET" and not recording_id:
            return raw({"recordings": [r for r in state["recordings"].values() if r["session_id"] == session_id and r.get("completed_at")]})
        if action == "recordings" and method == "POST":
            if not recording_id:
                body = await json_fields(request)
                kind, content_type = body.get("kind"), body.get("content_type")
                if kind != "audio" or not isinstance(content_type, str) or not content_type.startswith("audio/"):
                    fail(422, "Choose an audio recording.")
                recording = next((r for r in state["recordings"].values() if r["session_id"] == session_id and r["kind"] == kind), None) \
                    or {"session_id": session_id, "recording_id": new_id(), "kind": kind, "content_type": content_type}
                state["recordings"][recording["recording_id"]] = recording
                workspace.changed()
                return raw({"recording_id": recording["recording_id"],
                            "upload_url": f"{PUBLIC_ORIGIN}/local-recordings/{recording['recording_id']}"})
            if operation == "complete":
                recording = lookup(state["recordings"], recording_id, "Recording")
                if recording["session_id"] != session_id or not recording.get("byte_size"):
                    fail(404, "Uploaded recording was not found.")
                recording["duration_ms"] = (await json_fields(request)).get("duration_ms")
                recording["completed_at"] = now()
                workspace.changed()
                return raw()
        fail(405, "This session operation is unavailable.")

    # ── uploaded blobs ──────────────────────────────────────────────────────

    async def blob(self, workspace: Workspace, request: web.Request, collection: dict, item_id: str, *,
                   recording: bool = False) -> web.StreamResponse:
        if not OBJECT_ID.match(item_id or ""):
            fail(404, "Local file was not found.")
        item = lookup(collection, item_id, "Local file")
        limit = self.settings.limits.max_recording_bytes
        if request.method == "PUT":
            if recording:
                return await self._resumable_upload(workspace, request, item_id, item)
            if int(request.headers.get("Content-Length") or 0) > limit:
                fail(413, "The recording is too large.")
            data = await request.read()
            if not data or len(data) > limit:
                fail(413, "The recording exceeds the supported size.")
            workspace.write_file(item_id, data)
            item["byte_size"] = len(data)
            workspace.changed()
            return raw()
        if request.method == "GET":
            path = workspace.files / item_id
            if not path.is_file():
                fail(404, "Local file was not found.")
            return web.FileResponse(path, headers={"Content-Type": item.get("content_type") or "application/octet-stream"})
        fail(405, "This file operation is unavailable.")

    async def _resumable_upload(self, workspace: Workspace, request: web.Request, item_id: str, item: dict) -> web.Response:
        """Google-style resumable upload: ``Content-Range`` chunks, 308 until complete."""
        workspace.files.mkdir(parents=True, exist_ok=True, mode=0o700)
        final = workspace.files / item_id
        partial = final.with_name(item_id + ".partial")

        def progress(size: int) -> web.Response:
            return web.Response(status=308, headers={"Range": f"bytes=0-{size - 1}"} if size > 0 else {})

        if final.exists():
            size = final.stat().st_size
            if item.get("byte_size") != size:
                item["byte_size"] = size
                workspace.changed()
            return raw()
        offset = partial.stat().st_size if partial.exists() else 0
        content_range = request.headers.get("Content-Range", "")
        if content_range == "bytes */*":
            return progress(offset)
        match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range)
        if not match:
            fail(400, "Recording upload requires a byte range.")
        start, end, total = map(int, match.groups())
        if total > self.settings.limits.max_recording_bytes:
            fail(413, "The recording is too large.")
        if start != offset or start > end or end >= total:
            return progress(offset)
        data = await request.read()
        if len(data) != end - start + 1:
            fail(400, "Recording range does not match the bytes.")
        with open(partial, "ab") as handle:
            handle.write(data)
        partial.chmod(0o600)
        if end + 1 < total:
            return progress(end + 1)
        partial.replace(final)
        item["byte_size"] = total
        workspace.changed()
        return raw()

    async def voice_sample(self, workspace: Workspace, request: web.Request) -> web.Response:
        state = workspace.state
        if request.method == "GET":
            return raw({"sample": state["voiceSample"]})
        if request.method == "DELETE":
            state["voiceSample"] = None
            (workspace.files / "voice.wav").unlink(missing_ok=True)
            workspace.changed()
            return raw()
        if request.method != "PUT":
            fail(405, "This voice sample operation is unavailable.")
        upload = await read_multipart(request, max_bytes=self.settings.limits.max_voice_sample_bytes)
        data = upload.data or b""
        if len(data) < 44:
            fail(422, "An audio sample is required.")
        if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
            fail(422, "Expected a WAV audio sample.")
        byte_rate = int.from_bytes(data[28:32], "little")
        if not byte_rate:
            fail(422, "Invalid WAV audio sample.")
        workspace.write_file("voice.wav", data)
        state["voiceSample"] = {"duration_ms": round((len(data) - 44) * 1000 / byte_rate), "byte_size": len(data), "recorded_at": now()}
        workspace.changed()
        return raw({"sample": state["voiceSample"]})
