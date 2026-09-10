"""The poll loop.

Every tick the loop re-derives ``next_fire`` for each alarm from the current
wall clock and rings any alarm whose fire instant has been reached. Nothing is
precomputed: a sleep is only ever ``_TICK`` seconds long, so NTP steps,
suspend/resume and DST are absorbed by simply reading the clock again.

Cadence is driven by ``clock.monotonic`` and decisions by ``clock.now``, so a
monotonic clock that keeps counting through a wall-clock jump still ticks at a
steady rate.
"""

from __future__ import annotations

import sys
import time as _time
from datetime import datetime, timedelta
from typing import Callable

from .clock import Clock
from .models import Alarm
from .ringer import Ringer
from .schedule import next_fire

_Sleep = Callable[[float], None]

_TICK = 0.5
_CATCHUP_GRACE = timedelta(minutes=15)
# Without persisted last-fired state the runner cannot know an alarm from
# yesterday was genuinely missed rather than simply already handled. It only
# looks back far enough to catch a recent suspend/crash; anything older is
# assumed to have been dealt with by a prior run.
_MISSED_LOOKBACK = timedelta(hours=3)


class Runner:
    def __init__(self, clock: Clock, ringer: Ringer, sleep: _Sleep = _time.sleep) -> None:
        self._clock = clock
        self._ringer = ringer
        self._sleep = sleep
        self._last_fired: dict[str, datetime] = {}

    def run(
        self,
        alarms: list[Alarm],
        *,
        should_stop: Callable[[], bool] | None = None,
        max_ticks: int | None = None,
    ) -> None:
        """Poll until ``should_stop`` returns True, ``max_ticks`` is reached, or
        the user interrupts. ``should_stop`` and ``max_ticks`` exist for tests;
        the CLI passes neither and relies on Ctrl+C."""
        self._catch_up(alarms)
        last_seen = self._clock.now()

        ticks = 0
        try:
            while True:
                if should_stop is not None and should_stop():
                    return
                if max_ticks is not None and ticks >= max_ticks:
                    return

                started = self._clock.monotonic()
                last_seen = self._tick(alarms, last_seen)
                ticks += 1

                elapsed = self._clock.monotonic() - started
                remaining = _TICK - elapsed
                if remaining > 0:
                    self._sleep(remaining)
        except KeyboardInterrupt:
            print("\nalarmclock: stopped.", file=sys.stderr)

    def _tick(self, alarms: list[Alarm], last_seen: datetime) -> datetime:
        """Fire any alarm whose instant falls in ``(last_seen, now]`` and return
        the new watermark. A wall-clock jump backwards leaves the watermark
        where it was so nothing is double-fired."""
        now = self._clock.now()
        if now <= last_seen:
            return last_seen
        for alarm in alarms:
            fire_at = next_fire(alarm, last_seen)
            if fire_at is None:
                continue
            if fire_at <= now and not self._already_fired(alarm.id, fire_at):
                self._fire(alarm, fire_at)
        return now

    def _catch_up(self, alarms: list[Alarm]) -> None:
        now = self._clock.now()
        for alarm in alarms:
            fire_at = _last_due_since(alarm, now, _MISSED_LOOKBACK)
            if fire_at is None:
                continue
            if now - fire_at <= _CATCHUP_GRACE:
                self._fire(alarm, fire_at)
            else:
                label = alarm.label or alarm.id
                print(
                    f"alarmclock: missed {label}, was due {fire_at.isoformat()}",
                    file=sys.stderr,
                )
                self._last_fired[alarm.id] = fire_at

    def _fire(self, alarm: Alarm, fire_at: datetime) -> None:
        self._last_fired[alarm.id] = fire_at
        self._ringer.ring(alarm)

    def _already_fired(self, alarm_id: str, fire_at: datetime) -> bool:
        seen = self._last_fired.get(alarm_id)
        return seen is not None and seen >= fire_at


def _last_due_since(
    alarm: Alarm, now: datetime, lookback: timedelta
) -> datetime | None:
    """The most recent fire instant in ``(now - lookback, now]``, or ``None``.

    ``next_fire`` only looks forward, so this walks it forward from the start
    of the window and keeps the last occurrence that is still ``<= now``.
    """
    if not alarm.enabled:
        return None
    cursor = now - lookback
    last: datetime | None = None
    while True:
        fire_at = next_fire(alarm, cursor)
        if fire_at is None or fire_at > now:
            return last
        last = fire_at
        cursor = fire_at
