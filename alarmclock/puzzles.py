"""Dismissal puzzles.

An advanced, off-by-default gate on the ``dismiss`` transition. Three
implementations of one ``Puzzle`` protocol; difficulty scales parameters only
and never changes which puzzle type is in play.

A ``PuzzleGate`` wraps a puzzle with a ``streak`` requirement: dismissal is
allowed only after N consecutive correct answers. A wrong answer resets the
streak to zero and generates a fresh puzzle.
"""

from __future__ import annotations

import random
import string
from typing import Protocol

Difficulty = str
_DIFFICULTIES = ("easy", "medium", "hard")


class Puzzle(Protocol):
    def prompt(self) -> str:
        """The question to show the user."""
        ...

    def check(self, answer: str) -> bool:
        """True if ``answer`` solves the puzzle as currently posed."""
        ...


class MathPuzzle:
    """n-digit arithmetic; digit count scales with difficulty."""

    _DIGITS = {"easy": 1, "medium": 2, "hard": 3}

    def __init__(self, difficulty: Difficulty = "easy", rng: random.Random | None = None):
        self._rng = rng or random.Random()
        self._digits = self._DIGITS[_validate(difficulty)]
        self._a, self._b, self._op = self._make()

    def _make(self) -> tuple[int, int, str]:
        lo, hi = 10 ** (self._digits - 1), 10**self._digits - 1
        a = self._rng.randint(lo, hi)
        b = self._rng.randint(lo, hi)
        op = self._rng.choice(("+", "-", "*") if self._digits > 1 else ("+", "-"))
        if op == "-" and b > a:
            a, b = b, a
        return a, b, op

    def prompt(self) -> str:
        return f"{self._a} {self._op} {self._b} = ?"

    def check(self, answer: str) -> bool:
        try:
            given = int(answer.strip())
        except ValueError:
            return False
        expected = {"+": self._a + self._b, "-": self._a - self._b, "*": self._a * self._b}
        return given == expected[self._op]


class SequencePuzzle:
    """Complete an arithmetic/geometric sequence; length and step complexity
    scale with difficulty."""

    _PARAMS = {
        "easy": {"length": 4, "steps": (1, 2, 3, 5)},
        "medium": {"length": 5, "steps": (2, 3, 4, 6, 7)},
        "hard": {"length": 6, "steps": (3, 4, 6, 7, 9, 11)},
    }

    def __init__(self, difficulty: Difficulty = "easy", rng: random.Random | None = None):
        self._rng = rng or random.Random()
        params = self._PARAMS[_validate(difficulty)]
        self._length = params["length"]
        self._steps = params["steps"]
        self._terms, self._answer = self._make()

    def _make(self) -> tuple[list[int], int]:
        start = self._rng.randint(1, 9)
        step = self._rng.choice(self._steps)
        geometric = self._length >= 6 and self._rng.random() < 0.5
        if geometric:
            ratio = self._rng.choice((2, 3))
            terms = [start * ratio**i for i in range(self._length)]
        else:
            terms = [start + step * i for i in range(self._length)]
        return terms[:-1], terms[-1]

    def prompt(self) -> str:
        shown = ", ".join(str(t) for t in self._terms)
        return f"next in sequence: {shown}, ?"

    def check(self, answer: str) -> bool:
        try:
            return int(answer.strip()) == self._answer
        except ValueError:
            return False


class RetypePuzzle:
    """Transcribe a random string exactly; length scales with difficulty."""

    _LENGTH = {"easy": 5, "medium": 8, "hard": 12}

    def __init__(self, difficulty: Difficulty = "easy", rng: random.Random | None = None):
        self._rng = rng or random.Random()
        length = self._LENGTH[_validate(difficulty)]
        alphabet = string.ascii_uppercase + string.digits
        self._target = "".join(self._rng.choice(alphabet) for _ in range(length))

    def prompt(self) -> str:
        return f"type exactly: {self._target}"

    def check(self, answer: str) -> bool:
        return answer.strip() == self._target


_TYPES: dict[str, type] = {
    "math": MathPuzzle,
    "sequence": SequencePuzzle,
    "retype": RetypePuzzle,
}


def puzzle_types() -> list[str]:
    return list(_TYPES)


def make_puzzle(
    kind: str, difficulty: Difficulty = "easy", rng: random.Random | None = None
) -> Puzzle:
    try:
        cls = _TYPES[kind]
    except KeyError:
        raise ValueError(
            f"unknown puzzle type {kind!r}; choices: {', '.join(_TYPES)}"
        ) from None
    return cls(difficulty, rng)


class PuzzleGate:
    """A streak-guarded wrapper around a puzzle type.

    ``current_prompt`` shows the active puzzle. ``submit(answer)`` advances the
    streak on a correct answer and returns whether the streak target is now
    met; a wrong answer resets the streak and re-generates the puzzle.
    """

    def __init__(
        self,
        kind: str,
        difficulty: Difficulty = "easy",
        streak: int = 1,
        rng: random.Random | None = None,
    ) -> None:
        if streak < 1:
            raise ValueError("streak must be at least 1")
        self._kind = kind
        self._difficulty = difficulty
        self._target = streak
        self._rng = rng or random.Random()
        self._streak = 0
        self._puzzle = make_puzzle(kind, difficulty, self._rng)

    @property
    def streak(self) -> int:
        return self._streak

    @property
    def target(self) -> int:
        return self._target

    @property
    def satisfied(self) -> bool:
        return self._streak >= self._target

    def current_prompt(self) -> str:
        return self._puzzle.prompt()

    def submit(self, answer: str) -> bool:
        if self._puzzle.check(answer):
            self._streak += 1
        else:
            self._streak = 0
            self._puzzle = make_puzzle(self._kind, self._difficulty, self._rng)
        return self.satisfied


def _validate(difficulty: Difficulty) -> Difficulty:
    if difficulty not in _DIFFICULTIES:
        raise ValueError(
            f"unknown difficulty {difficulty!r}; choices: {', '.join(_DIFFICULTIES)}"
        )
    return difficulty
