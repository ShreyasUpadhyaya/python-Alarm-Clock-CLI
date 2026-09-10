from __future__ import annotations

import random
import re

import pytest

from alarmclock.clock import FakeClock
from alarmclock.models import Alarm, Recurrence, RingState
from alarmclock.puzzles import (
    MathPuzzle,
    PuzzleGate,
    RetypePuzzle,
    SequencePuzzle,
    make_puzzle,
    puzzle_types,
)
from alarmclock.audio import NullPlayer, Speaker
from alarmclock.ringer import (
    ConsoleRinger,
    RingSession,
    SigintSafetyValve,
    record_override,
)
from datetime import datetime, time, timezone


def _silent_speaker_factory():
    return lambda: Speaker(NullPlayer())

UTC = timezone.utc


def _rng() -> random.Random:
    return random.Random(1234)


# --- each puzzle type: solves correct, rejects wrong ----------------------

def _correct_answer_for(puzzle) -> str:
    text = puzzle.prompt()
    if isinstance(puzzle, MathPuzzle):
        a, op, b = re.match(r"(\d+) (.) (\d+)", text).groups()
        return str({"+": int(a) + int(b), "-": int(a) - int(b), "*": int(a) * int(b)}[op])
    if isinstance(puzzle, SequencePuzzle):
        nums = [int(n) for n in re.findall(r"-?\d+", text)]
        diff = nums[1] - nums[0]
        if all(nums[i + 1] - nums[i] == diff for i in range(len(nums) - 1)):
            return str(nums[-1] + diff)
        ratio = nums[1] // nums[0]
        return str(nums[-1] * ratio)
    if isinstance(puzzle, RetypePuzzle):
        return text.split("type exactly: ", 1)[1]
    raise AssertionError(type(puzzle))


@pytest.mark.parametrize("kind", puzzle_types())
def test_puzzle_accepts_correct_and_rejects_wrong(kind: str) -> None:
    puzzle = make_puzzle(kind, "medium", _rng())
    correct = _correct_answer_for(puzzle)

    assert puzzle.check(correct) is True
    assert puzzle.check(correct + "0") is False
    assert puzzle.check("definitely not right") is False


# --- difficulty scales parameters, never the type -----------------------

def test_math_difficulty_scales_digit_count() -> None:
    def prompt_digits(difficulty: str) -> int:
        text = MathPuzzle(difficulty, _rng()).prompt()
        return max(len(tok) for tok in re.findall(r"\d+", text))

    assert prompt_digits("easy") == 1
    assert prompt_digits("medium") == 2
    assert prompt_digits("hard") == 3


def test_sequence_difficulty_scales_length() -> None:
    def shown_terms(difficulty: str) -> int:
        text = SequencePuzzle(difficulty, _rng()).prompt()
        return len(re.findall(r"-?\d+", text))

    assert shown_terms("easy") == 3  # sequence length 4, final term hidden
    assert shown_terms("medium") == 4
    assert shown_terms("hard") == 5


def test_retype_difficulty_scales_length() -> None:
    def target_len(difficulty: str) -> int:
        return len(RetypePuzzle(difficulty, _rng()).prompt().split(": ", 1)[1])

    assert target_len("easy") == 5
    assert target_len("medium") == 8
    assert target_len("hard") == 12


@pytest.mark.parametrize("kind", puzzle_types())
def test_difficulty_never_swaps_type(kind: str) -> None:
    types = {
        type(make_puzzle(kind, d, _rng())) for d in ("easy", "medium", "hard")
    }
    assert len(types) == 1


# --- streak: advances on correct, resets on wrong ---------------------

def test_streak_advances_and_resets_on_failure() -> None:
    gate = PuzzleGate("math", "easy", streak=3, rng=_rng())

    def solve() -> None:
        gate.submit(_correct_answer_for_gate(gate))

    solve()
    assert gate.streak == 1
    solve()
    assert gate.streak == 2

    gate.submit("wrong")
    assert gate.streak == 0
    assert gate.satisfied is False

    for _ in range(3):
        gate.submit(_correct_answer_for_gate(gate))
    assert gate.streak == 3
    assert gate.satisfied is True


def test_wrong_answer_generates_a_new_puzzle() -> None:
    gate = PuzzleGate("retype", "hard", streak=1, rng=_rng())
    first = gate.current_prompt()
    gate.submit("not it")
    assert gate.current_prompt() != first


def _correct_answer_for_gate(gate: PuzzleGate) -> str:
    text = gate.current_prompt()
    if text.startswith("type exactly: "):
        return text.split(": ", 1)[1]
    if "next in sequence" in text:
        nums = [int(n) for n in re.findall(r"-?\d+", text)]
        diff = nums[1] - nums[0]
        return str(nums[-1] + diff)
    a, op, b = re.match(r".*?(\d+) (.) (\d+)", text).groups()
    return str({"+": int(a) + int(b), "-": int(a) - int(b), "*": int(a) * int(b)}[op])


# --- ring: dismissal gated by the puzzle, snooze unaffected ------------

def _alarm() -> Alarm:
    return Alarm(id="p1", label="wake", at=time(7, 0), recurrence=Recurrence.daily())


def test_dismiss_blocked_until_gate_satisfied() -> None:
    from alarmclock.ringer import PuzzleUnsolved

    clock = FakeClock(datetime(2026, 6, 1, 7, 0, tzinfo=UTC))
    gate = PuzzleGate("math", "easy", streak=1, rng=_rng())
    session = RingSession(_alarm(), clock, gate=gate)

    with pytest.raises(PuzzleUnsolved):
        session.dismiss()
    assert session.state is RingState.RINGING

    gate.submit(_correct_answer_for_gate(gate))
    assert session.dismiss() is RingState.DISMISSED


def test_snooze_is_not_gated_by_the_puzzle() -> None:
    clock = FakeClock(datetime(2026, 6, 1, 7, 0, tzinfo=UTC))
    gate = PuzzleGate("math", "hard", streak=5, rng=_rng())
    session = RingSession(_alarm(), clock, gate=gate)

    assert session.snooze() is RingState.SNOOZED


# --- SIGINT safety valve: fires after exactly three, not two ----------

def test_safety_valve_trips_on_the_third_signal_not_the_second() -> None:
    clock = FakeClock(datetime(2026, 6, 1, 7, 0, tzinfo=UTC), monotonic_start=100.0)
    valve = SigintSafetyValve(clock)
    valve._previous = None  # not entering the context; no real handler swap

    valve.feed()
    assert valve.tripped is False
    valve.feed()
    assert valve.tripped is False
    valve.feed()
    assert valve.tripped is True


def test_safety_valve_window_expires_between_signals() -> None:
    clock = FakeClock(datetime(2026, 6, 1, 7, 0, tzinfo=UTC), monotonic_start=0.0)
    valve = SigintSafetyValve(clock)

    valve.feed()
    valve.feed()
    clock.advance(6.0)  # older than the 5s window
    valve.feed()
    assert valve.tripped is False


def test_override_is_written_to_the_log(tmp_path) -> None:
    clock = FakeClock(datetime(2026, 6, 1, 7, 0, tzinfo=UTC))
    log = tmp_path / "overrides.log"

    record_override(_alarm(), clock, log)
    record_override(_alarm(), clock, log)

    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert "SIGINT-OVERRIDE" in lines[0]
    assert "alarm=p1" in lines[0]


def test_console_ringer_force_stops_and_logs_on_override(tmp_path, monkeypatch) -> None:
    clock = FakeClock(datetime(2026, 6, 1, 7, 0, tzinfo=UTC), monotonic_start=0.0)
    log = tmp_path / "overrides.log"
    gate = PuzzleGate("retype", "hard", streak=3, rng=_rng())
    ringer = ConsoleRinger(
        clock,
        gate_factory=lambda: gate,
        override_log=log,
        speaker_factory=_silent_speaker_factory(),
    )

    # Feed three signals into the valve on the first input() call, so the loop
    # sees `tripped` before it ever blocks on stdin.
    valve_box = {}
    real_enter = SigintSafetyValve.__enter__

    def capturing_enter(self):
        valve_box["v"] = self
        return real_enter(self)

    monkeypatch.setattr(SigintSafetyValve, "__enter__", capturing_enter)

    def fake_input(_prompt=""):
        v = valve_box["v"]
        v.feed()
        v.feed()
        v.feed()
        return ""

    monkeypatch.setattr("builtins.input", fake_input)

    state = ringer.ring(_alarm())

    assert state is RingState.DISMISSED
    assert log.exists()
    assert "SIGINT-OVERRIDE" in log.read_text(encoding="utf-8")


# --- audio is wired into the ring ------------------------------------------

def test_ring_starts_and_stops_the_sound(monkeypatch) -> None:
    clock = FakeClock(datetime(2026, 6, 1, 7, 0, tzinfo=UTC))
    player = NullPlayer()
    ringer = ConsoleRinger(clock, speaker_factory=lambda: Speaker(player))

    monkeypatch.setattr("builtins.input", lambda _p="": "")  # immediate dismiss

    state = ringer.ring(_alarm())

    assert state is RingState.DISMISSED
    assert len(player.played) == 1  # started once
    assert player.stops >= 1  # stopped on the way out


def test_snooze_stops_the_sound_and_wake_restarts_it(monkeypatch) -> None:
    clock = FakeClock(datetime(2026, 6, 1, 7, 0, tzinfo=UTC))
    player = NullPlayer()
    alarm = Alarm(
        id="p1", label="wake", at=time(7, 0), recurrence=Recurrence.daily(),
        snooze_minutes=5,
    )
    ringer = ConsoleRinger(clock, speaker_factory=lambda: Speaker(player))

    calls = iter(["s", "", ""])  # snooze, then (after wake) dismiss

    def fake_input(_prompt=""):
        try:
            choice = next(calls)
        except StopIteration:
            return ""
        if choice == "s":
            return "s"
        clock.advance(5 * 60 + 1)  # push past the snooze window before next poll
        return choice

    monkeypatch.setattr("builtins.input", fake_input)

    state = ringer.ring(alarm)

    assert state is RingState.DISMISSED
    assert len(player.played) == 2  # initial ring + restart after snooze wake
