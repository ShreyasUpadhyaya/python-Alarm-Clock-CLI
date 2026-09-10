# AI usage record

This file records where an AI assistant was used during the build, and what
of its output was changed or discarded. It is a truthful log of review, not a
performance of scepticism.

## Requirements and failure-mode analysis

**Prompt.** Given the naive "while loop with a sleep" alarm clock, enumerate
the edge cases that break it, ranked by how likely each is to bite a real
laptop user; for each, the mechanism and the cheapest correct fix. Then a
separate list of what NOT to build inside a 30-minute box.

**Used.** The failure list drove the design commitments: monotonic tick with
wall-clock re-derived each poll (laptop suspend, NTP steps), atomic writes
(kill mid-write), the degrading audio chain (no sound device), startup
catch-up with a grace window (machine asleep through a fire time).

**Rejected.** Suggestions that were explicitly ruled out of scope for the
time box: a background daemon / systemd / launchd service, multi-timezone
alarms, a TUI framework, a plugin system for audio backends or puzzles,
snooze with its own persisted backoff queue.

## Scheduling (`schedule.py`)

**Prompt.** Write `next_fire(alarm, now)` as a pure function with exact rules
for `once` / `daily` / `weekdays` / `weekends` / explicit days, plus the
spring-forward and fall-back behaviour from the decision table.

**Rewritten.** The first draft resolved a non-existent spring-forward local
time (e.g. 02:30 on the US spring-forward date) to the PEP-495 shifted time,
03:30, by interpreting the wall time with `fold=1`. The decision table
commits to the transition boundary itself, 03:00 / 07:00 UTC — "the first
valid instant after it". Reworked `_gap_instant` to floor the wall time to
the transition hour and read it with the pre-transition offset.

**Also fixed on review.** Same-zone `datetime` comparison ignores `fold`, so
a `fold=0` fall-back candidate compared greater than a `fold=1` `now` that
was actually later. The strict-after check now converts both sides to UTC.

## Module and test scaffolding

**Prompt.** Per-module specifications (one module per turn) with the protocol
shape, the transitions, and the required test cases stated explicitly.

**Used.** Generated the dataclasses, the state machine skeleton, the tone
synthesis, and the table-driven tests from those specs.

**Changed.** House rules applied throughout: specific exceptions rather than
bare `except`, type hints on every public function, docstrings only where the
name is not self-explanatory, and any unspecified judgement call surfaced in
an "Assumptions" note rather than buried in a comment. The catch-up
lookback window was tightened from 24h to 3h after testing showed a 24h
window logged a spurious "missed" on every startup for any daily alarm.
