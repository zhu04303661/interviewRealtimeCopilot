"""Errors that cross module boundaries."""

from __future__ import annotations

from typing import NoReturn


class ApiError(Exception):
    """A failure the app should show to the user.

    ``status`` is the HTTP status the workspace API answers with and
    ``detail`` is the message the original app displays (it reads ``detail``
    from error bodies).
    """

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


def fail(status: int, detail: str) -> NoReturn:
    """Raise an :class:`ApiError`; reads well inside validation chains."""
    raise ApiError(status, detail)
