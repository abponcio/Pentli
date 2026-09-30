"""Dubai wall clock, optionally pinned for a repeatable demo.

With DEMO_CLOCK="19:40" the clock starts at 19:40 today (Dubai time) when the
server starts or the demo is reset, and then runs in real time. On Lambda the anchor is kept in
DynamoDB so every copy of the app shows the same time.
"""
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import config

TZ = ZoneInfo(config.TIMEZONE)
_anchor_real: datetime | None = None
_anchor_demo: datetime | None = None


_loaded_at = 0.0


def reset() -> None:
    global _anchor_real, _anchor_demo, _loaded_at
    _anchor_real = datetime.now(TZ)
    if config.DEMO_CLOCK:
        hour, minute = (int(x) for x in config.DEMO_CLOCK.split(":"))
        _anchor_demo = _anchor_real.replace(hour=hour, minute=minute, second=0, microsecond=0)
    else:
        _anchor_demo = None
    if config.SERVERLESS:
        from .store import store

        store.set_meta("clock", {"real": _anchor_real.isoformat(), "demo": _anchor_demo.isoformat() if _anchor_demo else None})
        _loaded_at = time.time()


def _load_shared() -> None:
    global _anchor_real, _anchor_demo, _loaded_at
    from .store import store

    anchor = store.get_meta("clock")
    if not anchor:
        reset()
        return
    _anchor_real = datetime.fromisoformat(anchor["real"])
    _anchor_demo = datetime.fromisoformat(anchor["demo"]) if anchor["demo"] else None
    _loaded_at = time.time()


def now() -> datetime:
    if config.SERVERLESS and time.time() - _loaded_at > 2:
        _load_shared()
    if _anchor_real is None:
        reset()
    real = datetime.now(TZ)
    if _anchor_demo is None:
        return real
    return _anchor_demo + (real - _anchor_real)


def fmt(dt: datetime) -> str:
    return dt.astimezone(TZ).strftime("%H:%M")


def minutes_between(a: datetime, b: datetime) -> float:
    return (b - a) / timedelta(minutes=1)
