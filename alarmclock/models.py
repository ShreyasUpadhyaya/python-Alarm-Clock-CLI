"""Domain types for alarms and ring sessions.

All types here are immutable. An ``Alarm`` stores a local wall-clock time,
never a resolved UTC timestamp: the resolution to an absolute instant is the
job of ``schedule.next_fire`` and depends on the day it is resolved against.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from enum import Enum

_WEEKDAYS = frozenset({0, 1, 2, 3, 4})
_WEEKENDS = frozenset({5, 6})


class RecurrenceKind(str, Enum):
    ONCE = "once"
    DAILY = "daily"
    WEEKDAYS = "weekdays"
    WEEKENDS = "weekends"
    DAYS = "days"


@dataclass(frozen=True, slots=True)
class Recurrence:
    """When an alarm repeats.

    ``kind`` is the discriminator. ``days`` is only meaningful for
    ``RecurrenceKind.DAYS`` and holds ``date.weekday()`` values (Mon=0).
    For every other kind the effective day set is fixed and ``days`` is empty.
    """

    kind: RecurrenceKind = RecurrenceKind.ONCE
    days: frozenset[int] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        if self.kind is RecurrenceKind.DAYS:
            if not self.days:
                raise ValueError("RecurrenceKind.DAYS requires a non-empty day set")
            if not self.days <= frozenset(range(7)):
                raise ValueError(f"day values out of range 0..6: {sorted(self.days)}")
        elif self.days:
            raise ValueError(f"{self.kind} does not take an explicit day set")

    @classmethod
    def once(cls) -> "Recurrence":
        return cls(RecurrenceKind.ONCE)

    @classmethod
    def daily(cls) -> "Recurrence":
        return cls(RecurrenceKind.DAILY)

    @classmethod
    def weekdays(cls) -> "Recurrence":
        return cls(RecurrenceKind.WEEKDAYS)

    @classmethod
    def weekends(cls) -> "Recurrence":
        return cls(RecurrenceKind.WEEKENDS)

    @classmethod
    def on_days(cls, days: frozenset[int] | set[int] | list[int]) -> "Recurrence":
        return cls(RecurrenceKind.DAYS, frozenset(days))

    def weekday_set(self) -> frozenset[int]:
        """The concrete set of ``weekday()`` values this recurrence fires on.

        Empty for ``ONCE`` (a one-shot has no repeating day set).
        """
        if self.kind is RecurrenceKind.ONCE:
            return frozenset()
        if self.kind is RecurrenceKind.DAILY:
            return frozenset(range(7))
        if self.kind is RecurrenceKind.WEEKDAYS:
            return _WEEKDAYS
        if self.kind is RecurrenceKind.WEEKENDS:
            return _WEEKENDS
        return self.days


@dataclass(frozen=True, slots=True)
class Alarm:
    id: str
    label: str
    at: time
    recurrence: Recurrence = field(default_factory=Recurrence.once)
    sound: str = "beep"
    enabled: bool = True
    snooze_minutes: int = 5
    max_snoozes: int = 3

    def __post_init__(self) -> None:
        if self.at.tzinfo is not None:
            raise ValueError("Alarm.at must be a naive wall-clock time, not tz-aware")
        if self.snooze_minutes <= 0:
            raise ValueError("snooze_minutes must be positive")
        if self.max_snoozes < 0:
            raise ValueError("max_snoozes must not be negative")


class RingState(str, Enum):
    RINGING = "ringing"
    SNOOZED = "snoozed"
    DISMISSED = "dismissed"
    MISSED = "missed"
