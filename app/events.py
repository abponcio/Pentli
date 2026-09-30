"""Append-only event log that feeds every screen over server-sent events.

Audiences: "ops" (big screen), "kitchen:<donor id>", "recipient:<id>", "driver:<id>".
Kept in process memory for a single app instance; on Lambda (config.SERVERLESS) it lives in the
DynamoDB table (pk "event", sk = zero-padded id) so every copy of the app sees the same stream.
"""
import json
import threading
import time

from . import clock, config

_lock = threading.Lock()
_events: list[dict] = []


def _make(event_id: int, kind: str, rescue_id: str | None, audience: list[str], payload: dict) -> dict:
    return {
        "id": event_id,
        "ts": time.time(),
        "clock": clock.now().strftime("%H:%M:%S"),  # demo clock (Dubai time)
        "kind": kind,
        "rescue_id": rescue_id,
        "audience": audience,
        **payload,
    }


def _visible(e: dict, viewer: str) -> bool:
    return viewer == "ops" or viewer in e["audience"] or "all" in e["audience"]


class _SharedLog:
    """The same log in DynamoDB. Ids come from an atomic counter; readers query ids after their last one."""

    def __init__(self):
        from .store import store

        self.store = store
        self.table = store._table

    def emit(self, kind, rescue_id, audience, payload) -> dict:
        event = _make(self.store.next_number("event_seq", 1), kind, rescue_id, audience, payload)
        self.table.put_item(Item={"pk": "event", "sk": f"{event['id']:09d}", "doc": json.dumps(event, ensure_ascii=False, default=str)})
        return event

    def since(self, last_id: int, viewer: str):
        from boto3.dynamodb.conditions import Key

        items, kwargs = [], {"KeyConditionExpression": Key("pk").eq("event") & Key("sk").gt(f"{last_id:09d}"), "ConsistentRead": True}
        while True:
            page = self.table.query(**kwargs)
            items += page["Items"]
            if "LastEvaluatedKey" not in page:
                break
            kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        # Ids are handed out before the event is written, so a later id can land first. Stop at a gap
        # and pick it up on the next poll, unless the gap is a few seconds old (a writer that failed).
        ready, expected = [], last_id + 1
        for e in sorted((json.loads(i["doc"]) for i in items), key=lambda e: e["id"]):
            if e["id"] != expected and e["ts"] > time.time() - 3:
                break
            ready.append(e)
            expected = e["id"] + 1
        latest = ready[-1]["id"] if ready else last_id
        return [e for e in ready if _visible(e, viewer)], latest

    def latest_id(self) -> int:
        item = self.table.get_item(Key={"pk": "meta", "sk": "event_seq"}, ConsistentRead=True).get("Item")
        return int(item["n"]) if item and "n" in item else 0

    def clear(self) -> None:
        from boto3.dynamodb.conditions import Key

        with self.table.batch_writer() as batch:
            kwargs = {"KeyConditionExpression": Key("pk").eq("event"), "ProjectionExpression": "pk, sk"}
            while True:
                page = self.table.query(**kwargs)
                for item in page["Items"]:
                    batch.delete_item(Key={"pk": item["pk"], "sk": item["sk"]})
                if "LastEvaluatedKey" not in page:
                    break
                kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
        self.store.delete_meta("event_seq")


_shared = _SharedLog() if config.SERVERLESS else None


def emit(kind: str, rescue_id: str | None, audience: list[str], **payload) -> dict:
    if _shared:
        return _shared.emit(kind, rescue_id, audience, payload)
    with _lock:
        event = _make(len(_events) + 1, kind, rescue_id, audience, payload)
        _events.append(event)
        return event


def since(last_id: int, viewer: str) -> tuple[list[dict], int]:
    """Events after last_id visible to this viewer, and the new last id."""
    if _shared:
        return _shared.since(last_id, viewer)
    with _lock:
        new = _events[last_id:]
        latest = len(_events)
    return [e for e in new if _visible(e, viewer)], latest


def latest_id() -> int:
    if _shared:
        return _shared.latest_id()
    with _lock:
        return len(_events)


def clear() -> None:
    if _shared:
        _shared.clear()
        return
    with _lock:
        _events.clear()


def trace(rescue_id: str, step: str, actor: str, summary: str, detail: dict | None = None, status: str = "ok") -> dict:
    """One line on the ops screen's agent trace. actor is "AI" or "CODE"."""
    return emit("trace", rescue_id, ["ops"], step=step, actor=actor, summary=summary, detail=detail or {}, status=status)
