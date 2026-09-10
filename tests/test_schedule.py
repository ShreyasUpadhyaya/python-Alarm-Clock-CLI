"""Table-driven tests for ``next_fire``.

Each row is one case from docs/decision.md, resolved against
``America/New_York`` so the DST transitions are real: 2026-03-08 is
spring forward (02:00 -> 03:00), 2026-11-01 is fall back (02:00 -> 01:00).

``now`` and the expected instant are written as UTC and converted into the
zone, so the assertions compare absolute instants and never depend on how
Python renders a folded local time.
"""

from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import pytest

from alarmclock.models import Alarm, Recurrence
from alarmclock.schedule import next_fire

NY = ZoneInfo("America/New_York")
UTC = timezone.utc


def _ny(y: int, mo: int, d: int, h: int, mi: int) -> datetime:
    """A UTC wall time, as an aware instant expressed in the NY zone."""
    return datetime(y, mo, d, h, mi, tzinfo=UTC).astimezone(NY)


CASES = [
    pytest.param(
        Alarm(id="once-future", label="x", at=time(7, 0), recurrence=Recurrence.once()),
        _ny(2026, 6, 1, 10, 0),
        _ny(2026, 6, 1, 11, 0),
        id="once: next occurrence strictly after now",
    ),
    pytest.param(
        Alarm(id="once-passed", label="x", at=time(7, 0), recurrence=Recurrence.once()),
        _ny(2026, 6, 1, 12, 0),
        None,
        id="once: returns None after it has passed",
    ),
    pytest.param(
        Alarm(id="daily", label="x", at=time(7, 0), recurrence=Recurrence.daily()),
        _ny(2026, 6, 1, 12, 0),
        _ny(2026, 6, 2, 11, 0),
        id="daily: rolls to next day when today's time is gone",
    ),
    pytest.param(
        Alarm(
            id="wd-fri-eve",
            label="x",
            at=time(7, 0),
            recurrence=Recurrence.weekdays(),
        ),
        _ny(2026, 9, 11, 22, 0),  # Friday 18:00 EDT
        _ny(2026, 9, 14, 11, 0),  # Monday 07:00 EDT
        id="weekdays: Friday evening skips the weekend to Monday",
    ),
    pytest.param(
        Alarm(
            id="wd-mon-early",
            label="x",
            at=time(7, 0),
            recurrence=Recurrence.weekdays(),
        ),
        _ny(2026, 9, 14, 10, 0),  # Monday 06:00 EDT
        _ny(2026, 9, 14, 11, 0),  # Monday 07:00 EDT
        id="weekdays: same-day when the time is still ahead",
    ),
    pytest.param(
        Alarm(
            id="weekends",
            label="x",
            at=time(9, 0),
            recurrence=Recurrence.weekends(),
        ),
        _ny(2026, 9, 11, 22, 0),  # Friday
        _ny(2026, 9, 12, 13, 0),  # Saturday 09:00 EDT
        id="weekends: Friday evening lands on Saturday",
    ),
    pytest.param(
        Alarm(
            id="days-mwf",
            label="x",
            at=time(9, 0),
            recurrence=Recurrence.on_days({0, 2, 4}),
        ),
        _ny(2026, 9, 12, 14, 0),  # Saturday
        _ny(2026, 9, 14, 13, 0),  # Monday 09:00 EDT
        id="explicit days: Saturday skips to Monday",
    ),
    pytest.param(
        Alarm(id="spring", label="x", at=time(2, 30), recurrence=Recurrence.daily()),
        _ny(2026, 3, 8, 6, 59),  # 01:59 EST, one minute before the gap
        _ny(2026, 3, 8, 7, 0),  # 03:00 EDT, the instant the clock jumps to
        id="spring forward: nonexistent 02:30 fires at the gap boundary",
    ),
    pytest.param(
        Alarm(id="fall", label="x", at=time(1, 30), recurrence=Recurrence.daily()),
        _ny(2026, 11, 1, 5, 29),  # one minute before the first 01:30
        _ny(2026, 11, 1, 5, 30),  # the FIRST 01:30 (fold 0), 05:30 UTC
        id="fall back: doubled 01:30 fires on the first occurrence only",
    ),
    pytest.param(
        Alarm(id="fall2", label="x", at=time(1, 30), recurrence=Recurrence.daily()),
        _ny(2026, 11, 1, 6, 0),  # AFTER the first 01:30, before the second
        _ny(2026, 11, 2, 6, 30),  # next day, not the second 01:30 at 06:30 UTC
        id="fall back: the second 01:30 is never selected",
    ),
    pytest.param(
        Alarm(
            id="disabled",
            label="x",
            at=time(7, 0),
            recurrence=Recurrence.daily(),
            enabled=False,
        ),
        _ny(2026, 6, 1, 10, 0),
        None,
        id="disabled: returns None regardless of schedule",
    ),
]


@pytest.mark.parametrize("alarm, now, expected", CASES)
def test_next_fire(alarm: Alarm, now: datetime, expected: datetime | None) -> None:
    result = next_fire(alarm, now)

    if expected is None:
        assert result is None
        return

    assert result is not None
    assert result.astimezone(UTC) == expected.astimezone(UTC)
