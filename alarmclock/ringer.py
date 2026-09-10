"""The ring session as one explicit state machine.

A ``RingSession`` wraps a single ringing alarm and moves through
``RingState`` in response to two kinds of trigger:

* events -- ``dismiss()`` and ``snooze()``, driven by the user;
* time -- ``poll()``, which the caller invokes on a cadence and which applies
  the snooze-elapsed and auto-timeout transitions by reading the injected
  ``Clock``.

Transitions::

    RINGING --dismiss (puzzle gate satisfied)---> DISMISSED
    RINGING --snooze (snooze_count < max)-------> SNOOZED
    RINGING --auto timeout (>= timeout)---------> MISSED
    SNOOZED --dismiss--------------------------> DISMISSED
    SNOOZED --snooze interval elapsed---------> RINGING

The session never touches the ``Alarm``: snooze is a transient in-memory
state, so a snoozed daily alarm still fires normally the next day.

When a puzzle gate is attached, ``dismiss()`` raises ``PuzzleUnsolved`` until
the gate's streak requirement is met. Snooze is never gated. A separate
SIGINT safety valve in ``ConsoleRinger`` can force-stop the ring regardless
of the gate; it is audited to a log file.
"""

from __future__ import annotations

import signal
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

from .audio import Speaker, select_player
from .clock import Clock
from .models import Alarm, RingState
from .puzzles import PuzzleGate

_DEFAULT_TIMEOUT = timedelta(minutes=10)
_OVERRIDE_WINDOW_SECONDS = 5.0
_OVERRIDE_SIGNAL_COUNT = 3


class SnoozeRefused(Exception):
    """Raised when ``snooze()`` is called after the snooze cap is reached."""


class InvalidTransition(Exception):
    """Raised when an event is applied in a state that does not allow it."""


class PuzzleUnsolved(Exception):
    """Raised when ``dismiss()`` is called before the puzzle gate is satisfied."""


class RingSession:
    def __init__(
        self,
        alarm: Alarm,
        clock: Clock,
        *,
        auto_timeout: timedelta = _DEFAULT_TIMEOUT,
        gate: PuzzleGate | None = None,
    ) -> None:
        self._alarm = alarm
        self._clock = clock
        self._auto_timeout = auto_timeout
        self._gate = gate

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
    def gate(self) -> PuzzleGate | None:
        return self._gate

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
        if self._gate is not None and not self._gate.satisfied:
            raise PuzzleUnsolved("puzzle not solved; dismissal blocked")
        self._state = RingState.DISMISSED
        self._snooze_until = None
        return self._state

    def force_stop(self) -> RingState:
        """Terminate the ring bypassing the puzzle gate. Only the SIGINT safety
        valve calls this; the state lands in DISMISSED."""
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


def _default_speaker() -> Speaker:
    try:
        return Speaker(select_player())
    except RuntimeError:
        return Speaker(_SilentPlayer())


class _SilentPlayer:
    name = "silent"

    def play(self, path: str) -> None:
        return None

    def stop(self) -> None:
        return None


def _start_sound(speaker: Speaker, alarm: Alarm) -> None:
    import os

    try:
        if os.path.isfile(alarm.sound):
            speaker.play_file(alarm.sound)
        else:
            speaker.play_tone(alarm.sound)
    except (OSError, ValueError) as exc:
        print(f"alarmclock: sound unavailable ({exc})", file=sys.stderr)


def _stop_sound(speaker: Speaker) -> None:
    try:
        speaker.stop()
    except OSError:
        pass


def default_override_log() -> Path:
    import os

    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(
            os.environ.get("XDG_STATE_HOME", Path.home() / ".local" / "state")
        )
    return base / "alarmclock" / "overrides.log"


class SigintSafetyValve:
    """Counts SIGINTs. Three within five seconds trips the valve.

    Installed only for the duration of a ring. The first two signals are
    swallowed with a hint rather than raising ``KeyboardInterrupt``, so a
    stray Ctrl+C does not crash the ring; the third trips ``tripped``.
    """

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._hits: list[float] = []
        self._previous = None
        self.tripped = False

    def __enter__(self) -> "SigintSafetyValve":
        self._previous = signal.getsignal(signal.SIGINT)
        signal.signal(signal.SIGINT, self._on_signal)
        return self

    def __exit__(self, *exc: object) -> None:
        if self._previous is not None:
            signal.signal(signal.SIGINT, self._previous)

    def _on_signal(self, _signum: int, _frame: object) -> None:
        now = self._clock.monotonic()
        self._hits = [t for t in self._hits if now - t <= _OVERRIDE_WINDOW_SECONDS]
        self._hits.append(now)
        if len(self._hits) >= _OVERRIDE_SIGNAL_COUNT:
            self.tripped = True
        else:
            remaining = _OVERRIDE_SIGNAL_COUNT - len(self._hits)
            print(
                f"\nalarmclock: {remaining} more Ctrl+C within "
                f"{int(_OVERRIDE_WINDOW_SECONDS)}s to force-stop the alarm",
                file=sys.stderr,
            )

    def feed(self) -> None:
        """Test hook: simulate one SIGINT without a real signal."""
        self._on_signal(signal.SIGINT, None)


def record_override(alarm: Alarm, clock: Clock, log_path: Path | None = None) -> None:
    path = log_path or default_override_log()
    path.parent.mkdir(parents=True, exist_ok=True)
    label = alarm.label or alarm.id
    line = (
        f"{clock.now().isoformat()}\tSIGINT-OVERRIDE\talarm={alarm.id}\t"
        f"label={label}\n"
    )
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(line)


class ConsoleRinger:
    """Drives a ``RingSession`` from stdin: 's' snoozes, anything else attempts
    dismissal. Between keypresses it calls ``poll`` so the auto-timeout and
    snooze-elapsed transitions still fire while the user is away.

    If ``gate`` is supplied, dismissal shows the puzzle and is refused until
    the streak requirement is met. A SIGINT safety valve is active throughout:
    three Ctrl+C within five seconds force-stops the ring and writes an
    audited override line.
    """

    def __init__(
        self,
        clock: Clock,
        gate_factory=None,
        override_log: Path | None = None,
        speaker_factory=None,
    ) -> None:
        self._clock = clock
        self._gate_factory = gate_factory
        self._override_log = override_log
        self._speaker_factory = speaker_factory or _default_speaker

    def ring(self, alarm: Alarm) -> RingState:
        gate = self._gate_factory() if self._gate_factory is not None else None
        session = RingSession(alarm, self._clock, gate=gate)
        label = alarm.label or alarm.id
        print(f"\n*** ALARM: {label} ({alarm.at.isoformat()}) ***", file=sys.stderr)

        speaker = self._speaker_factory()
        _start_sound(speaker, alarm)

        try:
            with SigintSafetyValve(self._clock) as valve:
                while session.is_active:
                    if valve.tripped:
                        session.force_stop()
                        record_override(alarm, self._clock, self._override_log)
                        print(
                            "alarmclock: ring force-stopped by SIGINT override "
                            "(logged)",
                            file=sys.stderr,
                        )
                        break

                    was_snoozed = session.state is RingState.SNOOZED
                    session.poll()
                    if not session.is_active:
                        break
                    if was_snoozed and session.state is RingState.RINGING:
                        _start_sound(speaker, alarm)

                    if session.state is RingState.SNOOZED:
                        try:
                            input("")
                        except EOFError:
                            pass
                        continue

                    prompt = self._dismiss_prompt(session)
                    try:
                        choice = input(prompt).strip()
                    except EOFError:
                        self._try_dismiss(session, "")
                        break

                    if choice.lower() == "s":
                        try:
                            session.snooze()
                            if session.state is RingState.SNOOZED:
                                _stop_sound(speaker)
                        except SnoozeRefused as exc:
                            print(f"alarmclock: {exc}", file=sys.stderr)
                    else:
                        self._try_dismiss(session, choice)
        finally:
            _stop_sound(speaker)
            speaker.cleanup()

        return session.state

    def _dismiss_prompt(self, session: RingSession) -> str:
        if session.gate is None:
            return "[s]nooze / [d]ismiss: "
        gate = session.gate
        return (
            f"[s]nooze | solve to dismiss ({gate.streak}/{gate.target}): "
            f"{gate.current_prompt()}\n> "
        )

    def _try_dismiss(self, session: RingSession, answer: str) -> None:
        gate = session.gate
        if gate is not None and not gate.satisfied:
            before = gate.streak
            gate.submit(answer)
            if gate.satisfied:
                pass  # falls through to dismiss below
            elif gate.streak > before:
                remaining = gate.target - gate.streak
                print(
                    f"alarmclock: correct, {remaining} more to go", file=sys.stderr
                )
                return
            else:
                print("alarmclock: wrong, streak reset", file=sys.stderr)
                return
        try:
            session.dismiss()
        except PuzzleUnsolved:
            print("alarmclock: puzzle not solved", file=sys.stderr)
