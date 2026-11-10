"""The workspace API: routes the original app calls, response shapes and persistence."""

from __future__ import annotations

import json

import aiohttp


async def test_requires_a_signed_in_account(backend):
    body = await backend.call("GET", "/api/v3/goals", expect=401)
    assert body == {"detail": "Sign in locally to continue."}


async def test_goals_and_knowledge_sources(signed_in):
    b = signed_in
    await b.call("POST", "/api/v3/goals", json={"role": " ", "company": "X"}, expect=422)
    goal = await b.call("POST", "/api/v3/goals", json={"role": "Engineer", "company": "Example", "job_description": "Build LTE L1."})
    assert goal["status"] == "active" and goal["defaults"] == {}
    assert (await b.call("GET", "/api/v3/goals"))["goals"][0]["goal_id"] == goal["goal_id"]
    updated = await b.call("PUT", f"/api/v3/goals/{goal['goal_id']}", json={"role": "Senior Engineer", "company": "Example"})
    assert updated["role"] == "Senior Engineer" and updated["job_description"] == "Build LTE L1."
    defaults = await b.call("PUT", f"/api/v3/goals/{goal['goal_id']}/defaults", json={"language": "zh-CN", "junk": 1})
    assert defaults["defaults"] == {"language": "zh-CN"}

    material = await b.documents.import_file("admin", "material", str(_write(b, "notes.md", b"# Notes\nPDSCH")), "notes.md", "text/markdown")
    resume = await b.documents.import_file("admin", "resume", str(_write(b, "cv.txt", b"Jane Doe")), "cv.txt", "text/plain")
    await b.documents.wait_idle()
    scope = await b.call("POST", f"/api/v3/goals/{goal['goal_id']}/documents", json={"document_id": material["document_id"]})
    assert [d["filename"] for d in scope["materials"]] == ["notes.md"]
    await b.call("POST", f"/api/v3/goals/{goal['goal_id']}/documents", json={"document_id": resume["document_id"]}, expect=422)
    scope = await b.call("PUT", f"/api/v3/goals/{goal['goal_id']}/resume", json={"document_id": resume["document_id"]})
    assert scope["resume"]["status"] == "ready"
    await b.call("POST", f"/api/v3/documents/{material['document_id']}/archive")
    assert (await b.call("GET", f"/api/v3/goals/{goal['goal_id']}/documents"))["materials"] == []
    await b.call("POST", f"/api/v3/goals/{goal['goal_id']}/archive")
    assert (await b.call("GET", "/api/v3/goals"))["goals"] == []
    assert len((await b.call("GET", "/api/v3/goals", params={"include_archived": "true"}))["goals"]) == 1


async def test_documents_list_rename_and_profile(signed_in):
    b = signed_in
    doc = await b.documents.import_file("admin", "material", str(_write(b, "a.txt", b"hello")), "a.txt", "text/plain")
    renamed = await b.call("PUT", f"/api/v3/documents/{doc['document_id']}/name", json={"display_name": "  My notes  "})
    assert renamed["display_name"] == "My notes"
    await b.call("PUT", f"/api/v3/documents/{doc['document_id']}/name", json={"display_name": 3}, expect=422)
    listed = await b.call("GET", "/api/v3/documents", params={"kind": "material", "limit": "1"})
    assert [d["document_id"] for d in listed["documents"]] == [doc["document_id"]]
    assert (await b.call("GET", "/api/v3/documents", params={"kind": "resume"}))["documents"] == []
    assert await b.call("PUT", f"/api/v3/documents/{doc['document_id']}/profile", json={"name": "Jane"}) == {"name": "Jane"}
    legacy = await b.call("GET", "/api/file/list")
    assert legacy["code"] == 0 and legacy["data"]["list"][0]["filename"] == "a.txt"


async def test_multipart_upload_is_still_accepted(signed_in):
    form = aiohttp.FormData()
    form.add_field("kind", "material")
    form.add_field("file", b"uploaded text", filename="up.txt", content_type="text/plain")
    doc = await signed_in.call("POST", "/api/v3/documents", data=form)
    assert doc["status"] == "preparing" and doc["byte_size"] == 13
    await signed_in.documents.wait_idle()
    _, text = await signed_in.documents.read_text("admin", doc["document_id"])
    assert text == "uploaded text"


async def test_playbooks_preferences_and_legacy_routes(signed_in):
    b = signed_in
    playbook = await b.call("POST", "/api/v3/playbooks", json={"name": "STAR", "style": "concise"})
    await b.call("PUT", f"/api/v3/playbooks/{playbook['playbook_id']}", json={"name": "STAR", "expected_version": 9}, expect=409)
    updated = await b.call("PUT", f"/api/v3/playbooks/{playbook['playbook_id']}", json={"name": "STAR 2", "expected_version": 1})
    assert updated["version"] == 2
    assert (await b.call("PUT", "/api/v3/me/prefs", json={"language": "zh-CN", "other": 1}))["language"] == "zh-CN"
    assert (await b.call("PUT", "/api/v3/me/consents", json={"share_data": True}))["share_data"] is True
    assert (await b.call("GET", "/api/core/payment/get-plans"))["data"]["plans"][0]["cycle"] == "local"
    assert (await b.call("GET", "/core/payment/get-plans"))["data"]["plans"][0]["cycle"] == "local"  # some clients omit /api
    assert (await b.call("GET", "/api/model-list"))["data"][0]["id"] == "gpt-5.4-mini"
    assert (await b.call("POST", "/api/preference/update", json={"data": {"theme": "dark"}}))["data"] == {"theme": "dark"}
    await b.call("DELETE", "/api/v3/me", expect=422)
    await b.call("GET", "/api/not/a/route", expect=501)


async def test_state_survives_a_restart_in_the_same_format(signed_in):
    b = signed_in
    goal = await b.call("POST", "/api/v3/goals", json={"role": "Engineer", "company": "Example"})
    state = json.loads((b.settings.workspace_dir / "admin" / "workspace.json").read_text())
    assert state["goals"][goal["goal_id"]]["company"] == "Example"
    assert set(state) >= {"goals", "documents", "playbooks", "associations", "sessions", "transcripts", "prefs", "consents"}
    assert (b.settings.workspace_dir / "admin" / "workspace.json").stat().st_mode & 0o777 == 0o600


async def test_recordings_resumable_upload_and_voice_sample(signed_in, monkeypatch):
    b = signed_in
    session_id, _ = await _session(b)
    created = await b.call("POST", f"/api/v3/sessions/{session_id}/recordings", json={"kind": "audio", "content_type": "audio/webm"})
    url = created["upload_url"].replace("https://final-round-recovered.invalid", b.base)
    async with b.session.put(url, data=b"abc", headers={"Content-Range": "bytes 0-2/6"}) as response:
        assert response.status == 308 and response.headers["Range"] == "bytes=0-2"
    async with b.session.put(url, headers={"Content-Range": "bytes */*"}) as response:
        assert response.status == 308 and response.headers["Range"] == "bytes=0-2"
    async with b.session.put(url, data=b"def", headers={"Content-Range": "bytes 3-5/6"}) as response:
        assert response.status == 200
    await b.call("POST", f"/api/v3/sessions/{session_id}/recordings/{created['recording_id']}/complete", json={"duration_ms": 1000})
    async with b.session.get(url) as response:
        assert await response.read() == b"abcdef"

    wav = b"RIFF" + (36).to_bytes(4, "little") + b"WAVEfmt " + bytes(16) + b"data" + bytes(4) + bytes(32000)
    wav = wav[:28] + (32000).to_bytes(4, "little") + wav[32:]
    form = aiohttp.FormData()
    form.add_field("file", wav, filename="voice.wav", content_type="audio/wav")
    sample = (await b.call("PUT", "/api/v3/voice-sample", data=form))["sample"]
    assert sample["duration_ms"] == 1000
    await b.call("DELETE", "/api/v3/voice-sample")
    assert (await b.call("GET", "/api/v3/voice-sample"))["sample"] is None


async def test_session_start_requires_a_key_and_a_supported_mode(signed_in, monkeypatch):
    b = signed_in
    goal = await b.call("POST", "/api/v3/goals", json={"role": "Engineer", "company": "Example"})
    phone = await b.call("POST", "/api/v3/sessions", json={"topology": "phone", "goal_id": goal["goal_id"]}, expect=422)
    assert "speaker separation" in phone["detail"]
    monkeypatch.delenv("OPENAI_API_KEY")
    missing = await b.call("POST", "/api/v3/sessions", json={"topology": "general", "goal_id": goal["goal_id"]}, expect=422)
    assert "OPENAI_API_KEY" in missing["detail"]
    assert (await b.call("GET", "/api/model-list"))["data"] == []


async def _session(b):
    goal = await b.call("POST", "/api/v3/goals", json={"role": "Engineer", "company": "Example"})
    started = await b.call("POST", "/api/v3/sessions", json={"topology": "general", "goal_id": goal["goal_id"], "config": {}})
    return started["session_id"], started["ws_url"]


def _write(b, name, data):
    path = b.settings.workspace_dir.parent / name
    path.write_bytes(data)
    return path


def test_workspaces_move_once_from_the_old_profile_folder(tmp_path):
    from frlocal.workspace.store import migrate_legacy_workspaces
    legacy, target = tmp_path / "profile" / "workspace", tmp_path / "data" / "workspace"
    (legacy / "admin" / "files").mkdir(parents=True)
    (legacy / "admin" / "workspace.json").write_text('{"goals": {"g": {"company": "Old"}}}')
    (legacy / "admin" / "files" / "doc").write_bytes(b"pdf")
    (legacy / "not an account").mkdir()
    assert migrate_legacy_workspaces(legacy, target) == ["admin"]
    assert json.loads((target / "admin" / "workspace.json").read_text())["goals"]["g"]["company"] == "Old"
    assert (target / "admin" / "files" / "doc").read_bytes() == b"pdf"
    assert (legacy / "admin" / "workspace.json").exists()          # the old folder stays as a backup
    (target / "admin" / "workspace.json").write_text('{"goals": {}}')
    assert migrate_legacy_workspaces(legacy, target) == []          # never overwrites newer data
    assert migrate_legacy_workspaces(None, target) == []


async def test_session_history_lists_sessions_newest_first(signed_in):
    goal = await signed_in.call("POST", "/api/v3/goals", json={"role": "SEM", "company": "AccelerComm"})
    first = await signed_in.call("POST", "/api/v3/sessions", json={"topology": "mock", "goal_id": goal["goal_id"], "config": {}})
    second = await signed_in.call("POST", "/api/v3/sessions", json={"topology": "general", "goal_id": goal["goal_id"], "config": {}})
    rows = (await signed_in.call("GET", "/api/v3/sessions"))["sessions"]
    assert [r["session_id"] for r in rows] == [second["session_id"], first["session_id"]]
    assert rows[0]["topology"] == "general" and rows[0]["company"] == "AccelerComm" and "report" not in rows[0]
