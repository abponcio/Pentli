"""Append-only event log that feeds every screen over server-sent events.

Audiences: "ops" (big screen), "kitchen:<donor id>", "recipient:<id>", "driver:<id>".
Kept in process memory; run one app instance for the demo.
"""
import threading
import time

from . import clock

_lock = threading.Lock()
_events: list[dict] = []


def emit(kind: str, rescue_id: str | None, audience: list[str], **payload) -> dict:
    with _lock:
        event = {
            "id": len(_events) + 1,
            "ts": time.time(),
            "clock": clock.now().strftime("%H:%M:%S"),  # demo clock (Dubai time)
            "kind": kind,
            "rescue_id": rescue_id,
            "audience": audience,
            **payload,
        }
        _events.append(event)
        return event


def since(last_id: int, viewer: str) -> tuple[list[dict], int]:
    """Events after last_id visible to this viewer, and the new last id."""
    with _lock:
        new = _events[last_id:]
        latest = len(_events)
    return [e for e in new if viewer == "ops" or viewer in e["audience"] or "all" in e["audience"]], latest


def latest_id() -> int:
    with _lock:
        return len(_events)


def clear() -> None:
    with _lock:
        _events.clear()


def trace(rescue_id: str, step: str, actor: str, summary: str, detail: dict | None = None, status: str = "ok") -> dict:
    """One line on the ops screen's agent trace. actor is "AI" or "CODE"."""
    return emit("trace", rescue_id, ["ops"], step=step, actor=actor, summary=summary, detail=detail or {}, status=status)
