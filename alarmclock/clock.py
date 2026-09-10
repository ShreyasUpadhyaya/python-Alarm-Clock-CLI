"""The time seam.

Everything that needs the current time takes a ``Clock``. Production wires in
``SystemClock``; tests wire in ``FakeClock`` and drive it with ``advance``.
``now()`` returns an aware datetime in the local zone; ``monotonic()`` returns
a strictly-for-intervals float on the same base as ``time.monotonic``.
"""

from __future__ import annotations

import time as _time
from datetime import datetime, timedelta, timezone
from typing import Protocol, runtime_checkable


@runtime_checkable
class Clock(Protocol):
    def now(self) -> datetime:
        """Current time as an aware datetime in the local zone."""
        ...

    def monotonic(self) -> float:
        """Seconds from an unspecified epoch; only differences are meaningful."""
        ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc).astimezone()

    def monotonic(self) -> float:
        return _time.monotonic()


class FakeClock:
    """A clock the test controls.

    ``advance(seconds)`` moves the wall clock and the monotonic clock together
    by the same amount, so code that mixes ``now()`` and ``monotonic()`` sees a
    consistent passage of time. ``set(dt)`` jumps the wall clock only, to model
    an NTP step or a DST discontinuity without a matching monotonic jump.
    """

    def __init__(self, start: datetime, *, monotonic_start: float = 0.0) -> None:
        if start.tzinfo is None:
            raise ValueError("FakeClock start must be an aware datetime")
        self._now = start
        self._monotonic = monotonic_start

    def now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._monotonic

    def advance(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError("advance does not go backwards; use set() for a jump")
        self._now = self._now + timedelta(seconds=seconds)
        self._monotonic += seconds

    def set(self, when: datetime) -> None:
        if when.tzinfo is None:
            raise ValueError("FakeClock.set requires an aware datetime")
        self._now = when
