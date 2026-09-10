# alarmclock

A command-line alarm clock: set alarms, let a foreground process poll for them, ring, snooze, dismiss.

Built as a 30-minute timed engineering exercise. CLI only, no web UI, no database, standard library only (`pytest` is the sole dev dependency).

## Quickstart

```
git clone <this-repo>
cd python-Alarm-Clock-CLI
pip install -e .
alarm set "in 1m" --label demo
alarm run
```

`alarm run` blocks and polls. When the alarm fires it rings; press Enter to dismiss, or `s` then Enter to snooze. Ctrl+C stops the loop.

If the `alarm` script is not on your PATH after `pip install -e .`, use `python -m alarmclock` instead (identical arguments).

## Command reference

| Command | What it does | Example |
| --- | --- | --- |
| `set <time> [--label] [--repeat] [--sound] [--sound-file] [--snooze-minutes]` | Add an alarm. Time accepts `HH:MM`, `HH:MM:SS`, `7:30am`, `in 45m`, `in 1h30m`. | `alarm set 07:30 --label Standup --repeat weekdays` |
| `list` | Show all alarms with id, state, time, recurrence, label. | `alarm list` |
| `delete <id>` | Remove an alarm. | `alarm delete 3f9c1a20` |
| `enable <id>` / `disable <id>` | Toggle an alarm without deleting it. | `alarm disable 3f9c1a20` |
| `run` | Run the poll loop until Ctrl+C. | `alarm run` |
| `sounds` | List the four built-in tones. | `alarm sounds` |
| `test-sound <name>` | Play a tone (or a WAV path) once. | `alarm test-sound chirp` |
| `config show` | Print all advanced settings. | `alarm config show` |
| `config set <key> <value>` | Set one setting. Keys: `puzzle.enabled`, `puzzle.type`, `puzzle.difficulty`, `puzzle.streak`. | `alarm config set puzzle.enabled true` |

`--repeat` takes `once` (default), `daily`, `weekdays`, `weekends`, or an explicit list like `mon,wed,fri`.

## Design decisions

This is the part the exercise is grading. The table is reproduced verbatim from `plan.md`, which was committed before any code.

| Decision | Reason | Rejected alternative |
| --- | --- | --- |
| `argparse`, zero runtime dependencies | `pip install` and run, on any Python 3.11+. Reviewers should not fight an environment. | `click` / `typer`: nicer, but a dependency for a 30-minute exercise is a cost with no payoff here. |
| Poll loop at 0.5s on `time.monotonic`, re-deriving wall clock each tick | Survives NTP jumps, suspend/resume and DST. Drift cannot accumulate because nothing is precomputed. | `threading.Timer` per alarm: one thread per alarm, and a long sleep is exactly what clock jumps break. |
| `Clock` injected everywhere | `FakeClock` lets a test advance a week in microseconds. Non-negotiable for a time system. | `freezegun` / `monkeypatch` on `datetime`: patches the world instead of designing the seam. |
| Atomic write (`tmp` + `os.replace`) | The process can be killed mid-write at any moment. A truncated alarms file loses every alarm silently. | Plain `open(..., "w")`. |
| Audio behind a `Player` protocol | Tests use `NullPlayer` and assert on calls. No CI machine needs a sound card. | Direct calls into a playback lib from the ringer. |
| `next_fire` is pure | Every scheduling edge case becomes a table-driven unit test with no I/O. | Time logic embedded in the loop, untestable. |

The DST and recurrence commitments (spring-forward gap, fall-back fold, weekday rollover) are written out with their proving cases in [docs/decision.md](docs/decision.md).

## Architecture

```
alarmclock/
  cli.py        argparse dispatch and printing; the only logic kept here is parse_time_spec
  models.py     Alarm, Recurrence, RingState as frozen dataclasses / enums
  clock.py      Clock protocol, SystemClock for production, FakeClock for tests
  store.py      alarm persistence: one JSON file, written atomically via tmp + os.replace
  schedule.py   next_fire(alarm, now) -> datetime | None, a pure function
  runner.py     the poll loop: monotonic tick, wall-clock decisions, startup catch-up
  ringer.py     RingSession state machine, ConsoleRinger driver, SIGINT safety valve
  audio.py      runtime tone synthesis and a degrading Player backend chain
  puzzles.py    Puzzle protocol, three implementations, streak-guarded PuzzleGate
  config.py     read/write the advanced-settings JSON file
tests/          pytest, all hermetic; no test sleeps or touches real time
docs/           decision.md (scheduling commitments), PROMPTS.md (AI usage record)
```

## Features

**Setting an alarm.** `alarm set` parses `HH:MM`, `HH:MM:SS`, 12-hour (`7:30am`), and relative (`in 45m`, `in 1h30m`) times. Recurrence is `once`, `daily`, `weekdays`, `weekends`, or an explicit weekday list. The alarm stores a local wall-clock time, never a resolved timestamp; `next_fire(alarm, now)` is a pure function that resolves it against the current instant each time it is asked, applying the spring-forward and fall-back rules.

**Snooze.** `s` at the prompt snoozes for `snooze_minutes` (default 5), up to `max_snoozes` times (default 3). After the cap, snooze is refused and the only exit is a real dismissal. Snooze is a transient in-memory ring session: it does not touch the alarm's schedule, so a snoozed daily alarm still fires normally the next day. This also means snooze state does not survive a restart of `alarm run`.

**Sounds.** Four tones (`beep`, `chirp`, `rising`, `pulse`) are synthesised at runtime into a temporary WAV with `wave` and `math`, each with distinct frequency, envelope and repeat parameters and a short attack/release so they do not click. No audio files are bundled. `--sound-file` accepts any user WAV. Playback tries `simpleaudio`, then an OS player (`afplay` / `paplay` / `aplay` / `winsound`), then a terminal bell plus a printed banner; the clock stays functional with no audio backend at all.

**Dismissal.** The ring is an explicit state machine: `RINGING` goes to `DISMISSED` on dismiss, to `SNOOZED` on snooze (if under the cap), or to `MISSED` on a 10-minute auto-timeout; `SNOOZED` returns to `RINGING` when the interval elapses. On startup, `alarm run` catches up: an alarm whose fire time passed while the process was down rings immediately if it is within a 15-minute grace window, otherwise it is logged as missed and skipped.

**Puzzle-gated dismissal (advanced, off by default).** With `puzzle.enabled true`, dismissal is blocked until the user solves a puzzle: `math` (n-digit arithmetic), `sequence` (complete the pattern), or `retype` (transcribe a random string). Difficulty (`easy`/`medium`/`hard`) scales the parameters only, never the puzzle type. `puzzle.streak` requires N consecutive correct answers; a wrong answer resets the streak to zero and generates a fresh puzzle. Sound keeps playing throughout, and snooze is never gated. **Safety valve:** three SIGINT (Ctrl+C) within five seconds force-stops the ring regardless of the puzzle, prints a warning naming the override, and appends an audited line to an overrides log. A puzzle lock with no escape is a program that can hold a machine hostage over an arithmetic slip at 6am; the override is deliberate and is not removable.

## Testing

```
pip install -e ".[dev]"
pytest -q
```

76 tests, under a second on a laptop. They are fast because nothing waits: no test sleeps, opens an audio device, or reads the real clock.

`FakeClock` is the reason. It implements the same `Clock` protocol as `SystemClock` with `now()` and `monotonic()`, and exposes `advance(seconds)` to move both clocks together and `set(dt)` to jump wall-clock only (modelling an NTP step or DST discontinuity). A scheduling test that needs to cross a spring-forward boundary or exhaust a snooze cap does it by advancing a fake clock, so a week of simulated time costs microseconds. Audio tests use `NullPlayer`, which records calls and makes no sound, and drive backend selection with fake chains.

Breakdown: `test_schedule.py` 11 (the DST/recurrence table), `test_cli.py` 20 (time parsing and repeat parsing), `test_puzzles.py` 17 (each puzzle type, streak reset, difficulty scaling, the SIGINT override path), `test_audio.py` 15 (tone generation and backend fallthrough), `test_ringer.py` 6 (the snooze/timeout state machine), `test_store.py` 4 (round-trip, corrupt-file recovery, atomic write), `test_runner.py` 3 (the loop across a fire boundary, catch-up).

## Known limitations and what I would do next

- **No background daemon.** `alarm run` is a foreground process you leave in a terminal. There is no systemd unit, launchd plist, or Windows service. Next: a documented service wrapper per platform, with the loop unchanged.
- **No multi-timezone alarms.** The wall-clock time is interpreted in the zone reported by `now`. An alarm created in one zone and run in another follows the new zone. Next: store an IANA zone name per alarm and pass it into `next_fire`.
- **Snooze state is in-memory.** If `alarm run` restarts while an alarm is snoozed, the snooze is lost and the alarm reverts to its normal schedule. Next: persist active ring sessions to the store and reload them on startup.
- **Small puzzle set.** Three puzzle types, one parameter axis each (`difficulty`). Next: more types and a per-type parameter set, still behind the same `Puzzle` protocol.
- **Missed-alarm detection is a heuristic.** Without persisted last-fired state, the runner looks back a fixed window (3 hours) on startup to decide what was missed. Next: record each fire to the store and compare against it.
- **`config` only covers the puzzle gate.** Tick interval, auto-timeout and grace window are module constants. Next: fold them into the same settings file.

## AI usage

See [docs/PROMPTS.md](docs/PROMPTS.md). In short: an assistant was used to enumerate failure modes of the naive sleep-loop design, to draft the DST resolution logic in `schedule.py`, and to generate module and test scaffolding from explicit per-module specifications. Rejected suggestions included a background daemon, multi-timezone support, and a TUI framework, all out of scope for the time box; the first draft of the spring-forward handling returned the PEP-495 shifted time (`03:30`) rather than the transition boundary (`03:00`) the decision table commits to, and was rewritten.

## Video

_Walkthrough: TODO — link pending._
