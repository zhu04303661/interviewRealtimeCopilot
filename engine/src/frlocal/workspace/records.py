"""Pure helpers that shape workspace records into the responses the app expects.

Nothing here touches the disk; the API module loads state, calls these and
returns the result. Field names follow the vendor API the app was built for.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Iterable, Mapping

from ..errors import fail

LOCAL_PLAN = {
    "title": "Local workspace", "cycle": "local", "price": 0, "currency": "USD",
    "price_id": None, "is_current": True, "features": [],
}
EMPTY_GOAL_MEMORY = {"version": 0, "state": {"next_focus": [], "strengths": [], "weaknesses": [], "style_notes": []}}

# Raise when document preparation improves: documents prepared or rejected by
# an older preparer are retried automatically.
PREPARER_VERSION = 3


def now() -> str:
    """UTC timestamp formatted like JavaScript's ``Date.toISOString()``."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_id() -> str:
    return str(uuid.uuid4())


def parse_time(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def pick(source: Mapping[str, Any], keys: Iterable[str]) -> dict[str, Any]:
    """The subset of ``source`` whose keys are listed (absent keys stay absent)."""
    return {key: source[key] for key in keys if key in source}


def required_text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        fail(422, f"{name} is required.")
    return value.strip()


def lookup(collection: Mapping[str, Any], key: Any, name: str) -> dict[str, Any]:
    record = collection.get(key) if isinstance(key, str) else None
    if not record:
        fail(404, f"{name} was not found.")
    return record


def _int_param(params: Mapping[str, str], name: str, default: int) -> int:
    try:
        return int(params.get(name) or default)
    except ValueError:
        return default


def page(items: list[Any], params: Mapping[str, str]) -> dict[str, Any]:
    """Legacy ``pageIndex``/``pageSize`` pagination used by the older endpoints."""
    size = max(1, min(500, _int_param(params, "pageSize", 100)))
    index = max(1, _int_param(params, "pageIndex", 1))
    return {
        "list": items[(index - 1) * size:index * size],
        "pagination": {"count": len(items), "pageSize": size, "pageIndex": index, "pageTotal": -(-len(items) // size)},
    }


def windowed(items: list[Any], params: Mapping[str, str]) -> list[Any]:
    """``offset``/``limit`` pagination used by the v3 endpoints."""
    offset = max(0, _int_param(params, "offset", 0))
    limit = max(1, min(500, _int_param(params, "limit", 100)))
    return items[offset:offset + limit]


def report_of(session: dict[str, Any], transcript: list | None, preparing: bool) -> dict[str, Any]:
    """The Debrief summary row for one session."""
    created, ended = parse_time(session.get("created_at")), parse_time(session.get("ended_at"))
    duration = max(0, round((ended - created).total_seconds())) if created and ended else None
    report = session.get("report")
    failure = None
    if not report and not preparing:
        failure = "generation_failed" if session.get("report_requested") else (None if transcript else "no_content")
    return {
        **pick(session, ["session_id", "goal_id", "company", "role", "topology", "created_at", "ended_at"]),
        "end_reason": session.get("end_reason"),
        "duration_seconds": duration,
        "question_count": session.get("question_count"),
        "headline": ((report or {}).get("overall") or {}).get("headline"),
        "status": "ready" if report else "preparing" if preparing else "unprepared",
        "report": report,
        "failure_reason": failure,
    }


def legacy_session(session: dict[str, Any]) -> dict[str, Any]:
    """A session in the shape of the older ``session/*`` endpoints."""
    return {**session.get("config", {}), "id": session["session_id"], "goal_id": session["goal_id"], **session.get("fields", {})}


def legacy_goal(goal: dict[str, Any]) -> dict[str, Any]:
    return {"id": goal["goal_id"], "position": goal["role"], "company": goal["company"], "is_archived": goal.get("status") == "archived"}


def visible_documents(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Library documents, newest first, without archived ones."""
    return [doc for doc in reversed(list(state["documents"].values())) if not doc.get("archived_at")]


def goal_documents(state: dict[str, Any], goal_id: str) -> dict[str, Any]:
    """A goal's knowledge sources: its pinned resume and attached materials."""
    association = state["associations"].get(goal_id) or {"resume": None, "materials": []}

    def visible(doc_id: str | None) -> dict[str, Any] | None:
        doc = state["documents"].get(doc_id) if doc_id else None
        return doc if doc and not doc.get("archived_at") else None

    return {
        "resume": visible(association.get("resume")),
        "materials": [doc for doc in map(visible, association.get("materials", [])) if doc],
    }


def needs_preparation(doc: dict[str, Any]) -> bool:
    """Whether a document should (re)enter the preparation queue."""
    if doc.get("archived_at"):
        return False
    status = doc.get("status")
    if status == "preparing":
        return True
    if status == "ready":
        return not isinstance(doc.get("text_chars"), int)
    return status == "unprepared" and doc.get("preparer") != PREPARER_VERSION
