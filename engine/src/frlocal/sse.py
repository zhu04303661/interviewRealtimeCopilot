"""Incremental parser for server-sent events (the Responses API stream format).

Network chunks can split an event anywhere, including in the middle of a
UTF-8 character or between ``\\r`` and ``\\n``; :class:`SseParser` buffers
until complete lines are available and dispatches an event at each blank
line, following the WHATWG event-stream rules that matter here (``data``
lines joined with ``\\n``, ``event`` names, comments ignored).
"""

from __future__ import annotations

import codecs
from dataclasses import dataclass


@dataclass(frozen=True)
class SseEvent:
    event: str
    data: str


class SseParser:
    def __init__(self) -> None:
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._buffer = ""
        self._event = ""
        self._data: list[str] = []

    def feed(self, chunk: bytes) -> list[SseEvent]:
        """Add bytes from the network and return the events they complete."""
        self._buffer += self._decoder.decode(chunk)
        events: list[SseEvent] = []
        while True:
            newline = min((i for i in (self._buffer.find("\n"), self._buffer.find("\r")) if i >= 0), default=-1)
            if newline < 0:
                break
            # A lone "\r" at the end of the buffer may be the first half of "\r\n".
            if self._buffer[newline] == "\r" and newline == len(self._buffer) - 1:
                break
            line = self._buffer[:newline]
            skip = 2 if self._buffer.startswith("\r\n", newline) else 1
            self._buffer = self._buffer[newline + skip:]
            event = self._line(line)
            if event:
                events.append(event)
        return events

    def close(self) -> list[SseEvent]:
        """Flush a final event that was not followed by a blank line."""
        tail = self.feed(b"\n\n") if self._buffer or self._data else []
        return tail

    def _line(self, line: str) -> SseEvent | None:
        if line == "":
            if not self._data:
                self._event = ""
                return None
            event = SseEvent(self._event or "message", "\n".join(self._data))
            self._event, self._data = "", []
            return event
        if line.startswith(":"):
            return None
        name, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if name == "data":
            self._data.append(value)
        elif name == "event":
            self._event = value
        return None
