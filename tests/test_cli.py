from __future__ import annotations

from datetime import datetime, time, timezone

import pytest

from alarmclock.cli import TimeSpecError, parse_repeat, parse_time_spec
from alarmclock.models import RecurrenceKind

NOW = datetime(2026, 6, 1, 14, 20, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "spec, expected",
    [
        ("07:30", time(7, 30)),
        ("7:30", time(7, 30)),
        ("23:05:45", time(23, 5, 45)),
        ("7:30am", time(7, 30)),
        ("7:30AM", time(7, 30)),
        ("12:00am", time(0, 0)),
        ("12:15pm", time(12, 15)),
        ("1:05pm", time(13, 5)),
        ("in 45m", time(15, 5)),
        ("in 1h30m", time(15, 50)),
        ("in 2h", time(16, 20)),
    ],
)
def test_parse_time_spec_valid(spec: str, expected: time) -> None:
    assert parse_time_spec(spec, NOW) == expected


@pytest.mark.parametrize(
    "spec",
    ["25:00", "07:60", "banana", "in banana", "in", "13:00pm", "0:00am", "in 90x"],
)
def test_parse_time_spec_invalid(spec: str) -> None:
    with pytest.raises(TimeSpecError):
        parse_time_spec(spec, NOW)


def test_parse_repeat() -> None:
    assert parse_repeat(None).kind is RecurrenceKind.ONCE
    assert parse_repeat("daily").kind is RecurrenceKind.DAILY
    assert parse_repeat("weekdays").kind is RecurrenceKind.WEEKDAYS
    assert parse_repeat("weekends").kind is RecurrenceKind.WEEKENDS

    days = parse_repeat("mon,wed,fri")
    assert days.kind is RecurrenceKind.DAYS
    assert days.days == frozenset({0, 2, 4})

    with pytest.raises(TimeSpecError):
        parse_repeat("someday")
