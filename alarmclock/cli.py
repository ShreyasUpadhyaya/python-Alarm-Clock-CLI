"""Command-line surface: argument parsing, dispatch and printing only.

All scheduling, persistence and loop logic lives in the other modules. The one
piece of real logic kept here is ``parse_time_spec`` -- and it is a pure
function taking ``now``, so it is unit-tested directly.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import uuid
from datetime import datetime, time, timedelta

from .audio import Speaker, select_player, tone_names
from .clock import Clock, SystemClock
from .models import Alarm, Recurrence, RecurrenceKind
from .ringer import ConsoleRinger
from .runner import Runner
from .store import load, save

_REL_RE = re.compile(r"^in\s+(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?$", re.IGNORECASE)
_CLOCK_12_RE = re.compile(r"^(\d{1,2}):(\d{2})\s*([ap]m)$", re.IGNORECASE)

_DAY_NAMES = {
    "mon": 0,
    "tue": 1,
    "wed": 2,
    "thu": 3,
    "fri": 4,
    "sat": 5,
    "sun": 6,
}


class TimeSpecError(ValueError):
    """The alarm time string could not be parsed."""


def parse_time_spec(spec: str, now: datetime) -> time:
    """Parse a user time string into a wall-clock ``time``.

    Accepts ``HH:MM``, ``HH:MM:SS``, 12-hour ``7:30am``, and relative
    ``in 45m`` / ``in 1h30m``. Relative specs are resolved against ``now`` and
    reduced to a time of day; the date is not retained (the alarm model stores
    wall-clock time only).
    """
    text = spec.strip()

    rel = _REL_RE.match(text)
    if rel and (rel.group(1) or rel.group(2)):
        hours = int(rel.group(1) or 0)
        minutes = int(rel.group(2) or 0)
        return (now + timedelta(hours=hours, minutes=minutes)).time().replace(
            microsecond=0
        )

    twelve = _CLOCK_12_RE.match(text)
    if twelve:
        hour = int(twelve.group(1))
        minute = int(twelve.group(2))
        meridiem = twelve.group(3).lower()
        if not 1 <= hour <= 12 or minute >= 60:
            raise TimeSpecError(f"invalid 12-hour time: {spec!r}")
        if meridiem == "am":
            hour = 0 if hour == 12 else hour
        else:
            hour = 12 if hour == 12 else hour + 12
        return time(hour, minute)

    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue

    raise TimeSpecError(f"unrecognised time: {spec!r}")


def parse_repeat(spec: str | None) -> Recurrence:
    if spec is None or spec == "once":
        return Recurrence.once()
    if spec == "daily":
        return Recurrence.daily()
    if spec == "weekdays":
        return Recurrence.weekdays()
    if spec == "weekends":
        return Recurrence.weekends()
    days = set()
    for token in spec.split(","):
        key = token.strip().lower()[:3]
        if key not in _DAY_NAMES:
            raise TimeSpecError(f"unrecognised repeat: {spec!r}")
        days.add(_DAY_NAMES[key])
    return Recurrence.on_days(days)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="alarmclock")
    sub = parser.add_subparsers(dest="command", required=True)

    p_set = sub.add_parser("set", help="add an alarm")
    p_set.add_argument("time")
    p_set.add_argument("--label", default="")
    p_set.add_argument("--repeat", default=None)
    p_set.add_argument("--sound", default="beep", help=f"one of: {', '.join(tone_names())}")
    p_set.add_argument("--sound-file", default=None, help="path to a custom WAV file")
    p_set.add_argument("--snooze-minutes", type=int, default=5)

    sub.add_parser("list", help="list alarms")

    p_del = sub.add_parser("delete", help="remove an alarm")
    p_del.add_argument("id")

    p_en = sub.add_parser("enable", help="enable an alarm")
    p_en.add_argument("id")

    p_dis = sub.add_parser("disable", help="disable an alarm")
    p_dis.add_argument("id")

    sub.add_parser("run", help="run the poll loop until interrupted")

    sub.add_parser("sounds", help="list the built-in tones")

    p_test = sub.add_parser("test-sound", help="play a tone once")
    p_test.add_argument("name")
    return parser


def main(argv: list[str] | None = None, clock: Clock | None = None) -> int:
    clock = clock or SystemClock()
    args = build_parser().parse_args(argv)

    if args.command == "set":
        return _cmd_set(args, clock)
    if args.command == "list":
        return _cmd_list()
    if args.command == "delete":
        return _cmd_mutate(args.id, _delete)
    if args.command == "enable":
        return _cmd_mutate(args.id, lambda a: _set_enabled(a, True))
    if args.command == "disable":
        return _cmd_mutate(args.id, lambda a: _set_enabled(a, False))
    if args.command == "run":
        return _cmd_run(clock)
    if args.command == "sounds":
        return _cmd_sounds()
    if args.command == "test-sound":
        return _cmd_test_sound(args.name)
    return 2


def _cmd_set(args: argparse.Namespace, clock: Clock) -> int:
    try:
        at = parse_time_spec(args.time, clock.now())
        recurrence = parse_repeat(args.repeat)
        sound = _resolve_sound(args.sound, args.sound_file)
    except TimeSpecError as exc:
        print(f"alarmclock: {exc}", file=sys.stderr)
        return 2

    alarm = Alarm(
        id=uuid.uuid4().hex[:8],
        label=args.label,
        at=at,
        recurrence=recurrence,
        sound=sound,
        snooze_minutes=args.snooze_minutes,
    )
    alarms = load()
    alarms.append(alarm)
    save(alarms)
    print(f"added {alarm.id}  {at.isoformat()}  {_describe_recurrence(recurrence)}")
    return 0


def _cmd_list() -> int:
    alarms = load()
    if not alarms:
        print("no alarms")
        return 0
    for alarm in alarms:
        state = "on " if alarm.enabled else "off"
        label = alarm.label or "-"
        print(
            f"{alarm.id}  [{state}]  {alarm.at.isoformat():>8}  "
            f"{_describe_recurrence(alarm.recurrence):<9}  {label}"
        )
    return 0


def _cmd_mutate(alarm_id: str, op) -> int:
    alarms = load()
    updated = []
    found = False
    for alarm in alarms:
        if alarm.id == alarm_id:
            found = True
            replacement = op(alarm)
            if replacement is not None:
                updated.append(replacement)
        else:
            updated.append(alarm)
    if not found:
        print(f"alarmclock: no alarm {alarm_id!r}", file=sys.stderr)
        return 1
    save(updated)
    return 0


def _cmd_run(clock: Clock) -> int:
    alarms = [a for a in load() if a.enabled]
    Runner(clock, ConsoleRinger(clock)).run(alarms)
    return 0


def _cmd_sounds() -> int:
    for name in tone_names():
        print(name)
    return 0


def _cmd_test_sound(name: str) -> int:
    try:
        speaker = Speaker(select_player())
    except RuntimeError as exc:
        print(f"alarmclock: {exc}", file=sys.stderr)
        return 1
    try:
        if os.path.isfile(name):
            speaker.play_file(name)
        elif name in tone_names():
            speaker.play_tone(name)
        else:
            print(
                f"alarmclock: unknown sound {name!r}; try 'sounds' or a WAV path",
                file=sys.stderr,
            )
            return 2
        print(f"playing {name} via {speaker.player.name}")
        return 0
    finally:
        speaker.cleanup()


def _resolve_sound(sound: str, sound_file: str | None) -> str:
    if sound_file is None:
        return sound
    path = os.path.abspath(sound_file)
    if not os.path.isfile(path):
        raise TimeSpecError(f"no such WAV file: {sound_file!r}")
    return path


def _delete(_alarm: Alarm) -> None:
    return None


def _set_enabled(alarm: Alarm, enabled: bool) -> Alarm:
    from dataclasses import replace

    return replace(alarm, enabled=enabled)


def _describe_recurrence(recurrence: Recurrence) -> str:
    if recurrence.kind is not RecurrenceKind.DAYS:
        return recurrence.kind.value
    names = [name for name, idx in sorted(_DAY_NAMES.items(), key=lambda kv: kv[1])
             if idx in recurrence.days]
    return ",".join(names)


if __name__ == "__main__":
    raise SystemExit(main())
