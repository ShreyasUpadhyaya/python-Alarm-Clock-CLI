"""Alarm persistence: a single JSON file, written atomically.

``save`` writes to a temp file in the same directory, flushes and fsyncs it,
then ``os.replace``s it over the target so a reader ever sees only the whole
old file or the whole new file. ``load`` treats a missing, corrupt or
truncated file as "no alarms" and reports the problem on stderr rather than
letting the CLI die on startup.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import time
from pathlib import Path

from .models import Alarm, Recurrence, RecurrenceKind

_SCHEMA_VERSION = 1


def default_path() -> Path:
    """Config-dir location of the alarms file, honouring XDG on POSIX."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "alarmclock" / "alarms.json"


def load(path: Path | None = None) -> list[Alarm]:
    target = path or default_path()
    try:
        raw = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        _warn(f"could not read {target}: {exc}; starting with no alarms")
        return []

    try:
        doc = json.loads(raw)
        return [_alarm_from_dict(item) for item in doc["alarms"]]
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        _warn(f"{target} is corrupt or unreadable ({exc}); starting with no alarms")
        return []


def save(alarms: list[Alarm], path: Path | None = None) -> None:
    target = path or default_path()
    target.parent.mkdir(parents=True, exist_ok=True)

    doc = {
        "version": _SCHEMA_VERSION,
        "alarms": [_alarm_to_dict(a) for a in alarms],
    }
    payload = json.dumps(doc, indent=2, sort_keys=True)

    fd, tmp_name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
    )
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, target)
    except OSError:
        tmp_path.unlink(missing_ok=True)
        raise


def _alarm_to_dict(alarm: Alarm) -> dict:
    return {
        "id": alarm.id,
        "label": alarm.label,
        "at": alarm.at.isoformat(),
        "recurrence": {
            "kind": alarm.recurrence.kind.value,
            "days": sorted(alarm.recurrence.days),
        },
        "sound": alarm.sound,
        "enabled": alarm.enabled,
        "snooze_minutes": alarm.snooze_minutes,
        "max_snoozes": alarm.max_snoozes,
    }


def _alarm_from_dict(item: dict) -> Alarm:
    rec = item["recurrence"]
    kind = RecurrenceKind(rec["kind"])
    days = frozenset(int(d) for d in rec.get("days", ()))
    recurrence = (
        Recurrence(kind, days) if kind is RecurrenceKind.DAYS else Recurrence(kind)
    )
    return Alarm(
        id=str(item["id"]),
        label=str(item["label"]),
        at=time.fromisoformat(item["at"]),
        recurrence=recurrence,
        sound=str(item["sound"]),
        enabled=bool(item["enabled"]),
        snooze_minutes=int(item["snooze_minutes"]),
        max_snoozes=int(item["max_snoozes"]),
    )


def _warn(message: str) -> None:
    print(f"alarmclock: warning: {message}", file=sys.stderr)
