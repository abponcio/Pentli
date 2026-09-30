"""Dubai wall clock, optionally pinned for a repeatable demo.

With DEMO_CLOCK="19:40" the clock starts at 19:40 today (Dubai time) when the
server starts or the demo is reset, and then runs in real time.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import config

TZ = ZoneInfo(config.TIMEZONE)
_anchor_real: datetime | None = None
_anchor_demo: datetime | None = None


def reset() -> None:
    global _anchor_real, _anchor_demo
    _anchor_real = datetime.now(TZ)
    if config.DEMO_CLOCK:
        hour, minute = (int(x) for x in config.DEMO_CLOCK.split(":"))
        _anchor_demo = _anchor_real.replace(hour=hour, minute=minute, second=0, microsecond=0)
    else:
        _anchor_demo = None


def now() -> datetime:
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
