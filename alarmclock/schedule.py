"""Pure scheduling: given an alarm and the current instant, when does it next
fire?

``next_fire`` performs no I/O, reads no clock and touches no global state.
The current time is the ``now`` argument, and the local zone is taken from
``now.tzinfo`` -- the wall-clock ``alarm.at`` is interpreted in that zone.

DST handling, decided in advance (see docs/decision.md):

* Spring forward, the target wall-clock time does not exist that day: fire at
  the first valid instant after the gap -- the moment the clock jumps to.
* Fall back, the target wall-clock time occurs twice that day: fire on the
  first occurrence only (``fold=0``, the earlier UTC instant).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone, tzinfo

from .models import Alarm, RecurrenceKind

_MAX_LOOKAHEAD_DAYS = 8


def next_fire(alarm: Alarm, now: datetime) -> datetime | None:
    """The next instant this alarm fires, strictly after ``now``, or ``None``.

    ``None`` means the alarm has nothing left to fire: it is disabled, or it
    is a one-shot whose time has already passed.
    """
    if not alarm.enabled:
        return None
    if now.tzinfo is None:
        raise ValueError("next_fire requires an aware `now`")

    now_utc = now.astimezone(timezone.utc)

    if alarm.recurrence.kind is RecurrenceKind.ONCE:
        candidate = _resolve(now.date(), alarm.at, now.tzinfo)
        return candidate if _after(candidate, now_utc) else None

    fire_days = alarm.recurrence.weekday_set()
    for offset in range(_MAX_LOOKAHEAD_DAYS):
        day = (now + timedelta(days=offset)).date()
        if day.weekday() not in fire_days:
            continue
        candidate = _resolve(day, alarm.at, now.tzinfo)
        if _after(candidate, now_utc):
            return candidate
    return None


def _after(candidate: datetime, now_utc: datetime) -> bool:
    """Strictly-after, compared as absolute instants.

    Same-zone ``datetime`` comparison ignores ``fold``, so a fall-back
    ``fold=0`` candidate can compare greater than a ``fold=1`` ``now`` that is
    actually later; converting both to UTC forces an instant comparison.
    """
    return candidate.astimezone(timezone.utc) > now_utc


def _resolve(day: date, at: time, tz: tzinfo) -> datetime:
    """Resolve wall-clock ``at`` on ``day`` into an aware instant in ``tz``,
    applying the gap rule (the fall-back fold is handled by ``fold=0``)."""
    wall = datetime.combine(day, at).replace(tzinfo=tz, fold=0)
    if _is_in_gap(wall):
        return _gap_instant(wall)
    return wall


def _is_in_gap(wall: datetime) -> bool:
    """True if ``wall`` names a local time that does not exist (spring forward).

    Distinguishes a gap from a fall-back fold: in both, the ``fold=0`` and
    ``fold=1`` offsets differ, but only in a gap does normalising the instant
    through UTC and back fail to reproduce the original wall reading.
    """
    if wall.replace(fold=0).utcoffset() == wall.replace(fold=1).utcoffset():
        return False
    normalised = wall.astimezone(timezone.utc).astimezone(wall.tzinfo)
    return normalised.timetuple()[:6] != wall.timetuple()[:6]


def _gap_instant(wall: datetime) -> datetime:
    """The first valid instant at or after a non-existent local time: the
    instant the clock jumps to at the spring-forward transition.

    The transition falls on a whole hour in every IANA zone, so the gap
    starts at ``wall`` floored to the hour. That floored local time read with
    the pre-transition offset (``fold=0``) is the transition instant itself.
    """
    gap_start = wall.replace(minute=0, second=0, microsecond=0, fold=0)
    return gap_start.astimezone(timezone.utc).astimezone(wall.tzinfo)
