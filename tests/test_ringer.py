from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

import pytest

from alarmclock.clock import FakeClock
from alarmclock.models import Alarm, Recurrence, RingState
from alarmclock.ringer import InvalidTransition, RingSession, SnoozeRefused

UTC = timezone.utc


def _alarm(**kw) -> Alarm:
    base = dict(
        id="a1",
        label="wake",
        at=time(7, 0),
        recurrence=Recurrence.daily(),
        snooze_minutes=5,
        max_snoozes=3,
    )
    base.update(kw)
    return Alarm(**base)


def _session(clock: FakeClock, **kw) -> RingSession:
    return RingSession(_alarm(**kw), clock)


def test_starts_ringing() -> None:
    clock = FakeClock(datetime(2026, 6, 1, 7, 0, tzinfo=UTC))
    assert _session(clock).state is RingState.RINGING


def test_snooze_to_the_cap_then_refused() -> None:
    clock = FakeClock(datetime(2026, 6, 1, 7, 0, tzinfo=UTC))
    session = _session(clock, max_snoozes=3, snooze_minutes=5)

    for expected_count in (1, 2, 3):
        assert session.snooze() is RingState.SNOOZED
        assert session.snooze_count == expected_count
        clock.advance(5 * 60)  # snooze interval elapses
        assert session.poll() is RingState.RINGING

    with pytest.raises(SnoozeRefused):
        session.snooze()

    assert session.state is RingState.RINGING
    assert session.dismiss() is RingState.DISMISSED


def test_auto_timeout_lands_in_missed() -> None:
    clock = FakeClock(datetime(2026, 6, 1, 7, 0, tzinfo=UTC))
    session = _session(clock)

    clock.advance(9 * 60)
    assert session.poll() is RingState.RINGING

    clock.advance(60)  # now 10 minutes since ringing started
    assert session.poll() is RingState.MISSED

    with pytest.raises(InvalidTransition):
        session.snooze()
    with pytest.raises(InvalidTransition):
        session.dismiss()


def test_dismiss_from_snoozed_is_legal() -> None:
    clock = FakeClock(datetime(2026, 6, 1, 7, 0, tzinfo=UTC))
    session = _session(clock)

    session.snooze()
    assert session.state is RingState.SNOOZED

    assert session.dismiss() is RingState.DISMISSED
    assert not session.is_active


def test_snooze_does_not_mutate_the_alarm_schedule() -> None:
    from alarmclock.schedule import next_fire

    clock = FakeClock(datetime(2026, 6, 1, 7, 0, tzinfo=UTC))
    alarm = _alarm()
    before = next_fire(alarm, clock.now())

    session = RingSession(alarm, clock)
    session.snooze()

    after = next_fire(alarm, clock.now())
    assert before == after
    tomorrow = next_fire(alarm, clock.now() + timedelta(hours=1))
    assert tomorrow.date() == datetime(2026, 6, 2, tzinfo=UTC).date()


def test_auto_timeout_window_resets_after_a_snooze_wake() -> None:
    clock = FakeClock(datetime(2026, 6, 1, 7, 0, tzinfo=UTC))
    session = _session(clock)

    session.snooze()
    clock.advance(5 * 60)
    assert session.poll() is RingState.RINGING  # re-armed at 07:05

    clock.advance(9 * 60)
    assert session.poll() is RingState.RINGING  # only 9 min into the new window

    clock.advance(60)
    assert session.poll() is RingState.MISSED
