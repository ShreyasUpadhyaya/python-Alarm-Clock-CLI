"""The ring session as one explicit state machine.

A ``RingSession`` wraps a single ringing alarm and moves through
``RingState`` in response to two kinds of trigger:

* events -- ``dismiss()`` and ``snooze()``, driven by the user;
* time -- ``poll()``, which the caller invokes on a cadence and which applies
  the snooze-elapsed and auto-timeout transitions by reading the injected
  ``Clock``.

Transitions::

    RINGING --dismiss--------------------------> DISMISSED
    RINGING --snooze (snooze_count < max)------> SNOOZED
    RINGING --auto timeout (>= timeout)--------> MISSED
    SNOOZED --dismiss--------------------------> DISMISSED
    SNOOZED --snooze interval elapsed---------> RINGING

The session never touches the ``Alarm``: snooze is a transient in-memory
state, so a snoozed daily alarm still fires normally the next day.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from typing import Protocol

from .clock import Clock
from .models import Alarm, RingState

_DEFAULT_TIMEOUT = timedelta(minutes=10)


class SnoozeRefused(Exception):
    """Raised when ``snooze()`` is called after the snooze cap is reached."""


class InvalidTransition(Exception):
    """Raised when an event is applied in a state that does not allow it."""


class RingSession:
    def __init__(
        self,
        alarm: Alarm,
        clock: Clock,
        *,
        auto_timeout: timedelta = _DEFAULT_TIMEOUT,
    ) -> None:
        self._alarm = alarm
        self._clock = clock
        self._auto_timeout = auto_timeout

        self._state = RingState.RINGING
        self._snooze_count = 0
        self._ringing_since: datetime = clock.now()
        self._snooze_until: datetime | None = None

    @property
    def state(self) -> RingState:
        return self._state

    @property
    def snooze_count(self) -> int:
        return self._snooze_count

    @property
    def is_active(self) -> bool:
        return self._state in (RingState.RINGING, RingState.SNOOZED)

    def poll(self) -> RingState:
        """Apply any time-driven transition that is now due and return the
        resulting state. Safe to call at any cadence and in any state."""
        now = self._clock.now()

        if self._state is RingState.SNOOZED:
            if self._snooze_until is not None and now >= self._snooze_until:
                self._enter_ringing(now)
        elif self._state is RingState.RINGING:
            if now - self._ringing_since >= self._auto_timeout:
                self._state = RingState.MISSED

        return self._state

    def snooze(self) -> RingState:
        if self._state is not RingState.RINGING:
            raise InvalidTransition(f"cannot snooze from {self._state.value}")
        if self._snooze_count >= self._alarm.max_snoozes:
            raise SnoozeRefused(
                f"snooze limit reached ({self._alarm.max_snoozes}); "
                "dismiss the alarm to stop it"
            )

        self._snooze_count += 1
        self._state = RingState.SNOOZED
        self._snooze_until = self._clock.now() + timedelta(
            minutes=self._alarm.snooze_minutes
        )
        return self._state

    def dismiss(self) -> RingState:
        if self._state not in (RingState.RINGING, RingState.SNOOZED):
            raise InvalidTransition(f"cannot dismiss from {self._state.value}")
        self._state = RingState.DISMISSED
        self._snooze_until = None
        return self._state

    def _enter_ringing(self, now: datetime) -> None:
        self._state = RingState.RINGING
        self._ringing_since = now
        self._snooze_until = None


class Ringer(Protocol):
    def ring(self, alarm: Alarm) -> RingState:
        """Bring the alarm to the user's attention and block until the ring
        session leaves its active states, returning the terminal state."""
        ...


class ConsoleRinger:
    """Drives a ``RingSession`` from stdin: 's' snoozes, anything else
    dismisses. Between keypresses it calls ``poll`` so the auto-timeout and
    snooze-elapsed transitions still fire while the user is away."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock

    def ring(self, alarm: Alarm) -> RingState:
        session = RingSession(alarm, self._clock)
        label = alarm.label or alarm.id
        print(f"\n*** ALARM: {label} ({alarm.at.isoformat()}) ***", file=sys.stderr)

        while session.is_active:
            session.poll()
            if not session.is_active:
                break
            prompt = "[s]nooze / [d]ismiss: " if session.state is RingState.RINGING else ""
            try:
                choice = input(prompt).strip().lower()
            except EOFError:
                session.dismiss()
                break

            if session.state is RingState.SNOOZED:
                continue
            if choice == "s":
                try:
                    session.snooze()
                except SnoozeRefused as exc:
                    print(f"alarmclock: {exc}", file=sys.stderr)
            else:
                session.dismiss()

        return session.state
