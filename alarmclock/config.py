"""Settings: a small JSON file plus ``config set`` / ``config show``.

Only the puzzle gate is configurable. Everything is off by default; an absent
or unreadable file yields the defaults rather than an error.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from .puzzles import puzzle_types

_SCHEMA_VERSION = 1

_DEFAULTS: dict[str, Any] = {
    "puzzle.enabled": False,
    "puzzle.type": "math",
    "puzzle.difficulty": "easy",
    "puzzle.streak": 1,
}

_DIFFICULTIES = ("easy", "medium", "hard")


class ConfigError(ValueError):
    """A config key or value was rejected."""


def default_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "alarmclock" / "config.json"


def load(path: Path | None = None) -> dict[str, Any]:
    """Return the full settings dict: defaults overlaid with any saved values."""
    target = path or default_path()
    settings = dict(_DEFAULTS)
    try:
        raw = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return settings
    except OSError as exc:
        _warn(f"could not read {target}: {exc}; using defaults")
        return settings

    try:
        saved = json.loads(raw).get("settings", {})
    except (json.JSONDecodeError, AttributeError) as exc:
        _warn(f"{target} is unreadable ({exc}); using defaults")
        return settings

    for key in _DEFAULTS:
        if key in saved:
            settings[key] = saved[key]
    return settings


def save(settings: dict[str, Any], path: Path | None = None) -> None:
    target = path or default_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    doc = {"version": _SCHEMA_VERSION, "settings": {k: settings[k] for k in _DEFAULTS}}
    payload = json.dumps(doc, indent=2, sort_keys=True)

    tmp = target.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, target)


def set_value(key: str, value: str, path: Path | None = None) -> Any:
    """Validate and persist one setting. Returns the coerced value."""
    if key not in _DEFAULTS:
        raise ConfigError(f"unknown key {key!r}; choices: {', '.join(_DEFAULTS)}")
    coerced = _coerce(key, value)
    settings = load(path)
    settings[key] = coerced
    save(settings, path)
    return coerced


def _coerce(key: str, value: str) -> Any:
    if key == "puzzle.enabled":
        lowered = value.strip().lower()
        if lowered in ("true", "1", "yes", "on"):
            return True
        if lowered in ("false", "0", "no", "off"):
            return False
        raise ConfigError(f"puzzle.enabled must be true or false, got {value!r}")
    if key == "puzzle.type":
        if value not in puzzle_types():
            raise ConfigError(
                f"puzzle.type must be one of {', '.join(puzzle_types())}, got {value!r}"
            )
        return value
    if key == "puzzle.difficulty":
        if value not in _DIFFICULTIES:
            raise ConfigError(
                f"puzzle.difficulty must be one of {', '.join(_DIFFICULTIES)}, "
                f"got {value!r}"
            )
        return value
    if key == "puzzle.streak":
        try:
            n = int(value)
        except ValueError:
            raise ConfigError(f"puzzle.streak must be an integer, got {value!r}") from None
        if n < 1:
            raise ConfigError("puzzle.streak must be at least 1")
        return n
    raise ConfigError(f"unhandled key {key!r}")


def _warn(message: str) -> None:
    print(f"alarmclock: warning: {message}", file=sys.stderr)
