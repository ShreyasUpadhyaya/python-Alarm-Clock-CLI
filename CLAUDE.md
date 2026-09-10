We are building a Python CLI alarm clock as a 30-minute timed engineering
exercise. Constraints, all hard:

- Python 3.11+, CLI only. No web UI, no React, no database, no TUI framework.
- Zero runtime dependencies. Standard library only (argparse, wave, zoneinfo,
  json, os). pytest is a dev dependency and is the only one.
- The grader cares about engineering decisions, problem definition and how I
  review your output. Feature count is explicitly not the goal.

Design commitments already made. Do not relitigate them, build to them:

1. Time is polled on time.monotonic and wall-clock is re-derived every tick.
   Nothing precomputes a sleep duration. This must survive NTP jumps, suspend
   and resume, and DST.
2. A Clock protocol is injected everywhere. SystemClock in production,
   FakeClock in tests. No test may sleep or depend on real time.
3. next_fire(alarm, now) is a pure function. No I/O, no globals, no clock
   access inside it.
4. Persistence is a JSON file written atomically: temp file plus os.replace.
5. Audio is behind a Player protocol with a degrading backend chain.

Module layout:
alarmclock/{cli,models,clock,store,schedule,runner,ringer,audio,puzzles,config}.py
plus tests/.

House rules for every response:
- Write only the modules I ask for in that turn. Do not scaffold ahead.
- Type hints on every public function. Docstrings only where the reason is
  not obvious from the name.
- No comments restating the code.
- Raise specific exceptions, never bare except.
- When you make a judgement call I did not specify, state it in one line at
  the end under "Assumptions". Do not bury it in a comment.

Acknowledge in two lines. Do not write code yet.