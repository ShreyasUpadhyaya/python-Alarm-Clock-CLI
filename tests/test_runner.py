from __future__ import annotations

from datetime import datetime, time, timezone

from alarmclock.clock import FakeClock
from alarmclock.models import Alarm, Recurrence
from alarmclock.runner import Runner

UTC = timezone.utc


class RecordingRinger:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def ring(self, alarm: Alarm) -> None:
        self.calls.append(alarm.id)


def test_loop_fires_once_across_a_boundary() -> None:
    clock = FakeClock(datetime(2026, 6, 1, 6, 59, 0, tzinfo=UTC))
    ringer = RecordingRinger()
    runner = Runner(clock, ringer, sleep=lambda _seconds: None)

    alarm = Alarm(id="a1", label="wake", at=time(7, 0), recurrence=Recurrence.daily())

    def advance_then_stop() -> bool:
        if clock.now() >= datetime(2026, 6, 1, 7, 1, 0, tzinfo=UTC):
            return True
        clock.advance(0.5)
        return False

    runner.run([alarm], should_stop=advance_then_stop)

    assert ringer.calls == ["a1"]


def test_catch_up_fires_a_recently_missed_alarm() -> None:
    clock = FakeClock(datetime(2026, 6, 1, 7, 5, 0, tzinfo=UTC))
    ringer = RecordingRinger()
    runner = Runner(clock, ringer, sleep=lambda _seconds: None)

    alarm = Alarm(id="a2", label="wake", at=time(7, 0), recurrence=Recurrence.daily())

    runner.run([alarm], should_stop=lambda: True)

    assert ringer.calls == ["a2"]


def test_catch_up_skips_an_alarm_past_the_grace_window(capsys) -> None:
    clock = FakeClock(datetime(2026, 6, 1, 8, 0, 0, tzinfo=UTC))
    ringer = RecordingRinger()
    runner = Runner(clock, ringer, sleep=lambda _seconds: None)

    alarm = Alarm(id="a3", label="wake", at=time(7, 0), recurrence=Recurrence.daily())

    runner.run([alarm], should_stop=lambda: True)

    assert ringer.calls == []
    assert "missed" in capsys.readouterr().err.lower()
