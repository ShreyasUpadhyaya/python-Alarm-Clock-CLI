from __future__ import annotations

from datetime import time
from pathlib import Path

from alarmclock.models import Alarm, Recurrence
from alarmclock.store import load, save


def _sample() -> list[Alarm]:
    return [
        Alarm(id="1", label="Standup", at=time(7, 30), recurrence=Recurrence.weekdays()),
        Alarm(
            id="2",
            label="Gym",
            at=time(6, 15, 0),
            recurrence=Recurrence.on_days({0, 2, 4}),
            sound="chirp",
            enabled=False,
            snooze_minutes=10,
            max_snoozes=1,
        ),
        Alarm(id="3", label="Laundry", at=time(21, 0), recurrence=Recurrence.once()),
    ]


def test_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "alarms.json"
    original = _sample()

    save(original, path)
    restored = load(path)

    assert restored == original


def test_missing_file_loads_empty(tmp_path: Path) -> None:
    assert load(tmp_path / "does-not-exist.json") == []


def test_corrupt_file_recovers_with_warning(tmp_path: Path, capsys) -> None:
    path = tmp_path / "alarms.json"
    save(_sample(), path)

    good = path.read_text(encoding="utf-8")
    path.write_text(good[: len(good) // 2], encoding="utf-8")  # truncate mid-JSON

    assert load(path) == []
    assert "corrupt" in capsys.readouterr().err.lower()


def test_successful_save_leaves_no_temp_file(tmp_path: Path) -> None:
    path = tmp_path / "alarms.json"

    save(_sample(), path)

    leftovers = [
        p.name
        for p in tmp_path.iterdir()
        if p.name != path.name and (p.name.endswith(".tmp") or p.name.startswith("."))
    ]
    assert leftovers == []
    assert list(tmp_path.iterdir()) == [path]
