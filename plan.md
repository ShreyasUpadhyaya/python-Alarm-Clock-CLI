# plan.md

**Project:** `alarmclock` — a Python CLI alarm clock
**Author:** Shreyas Upadhyaya
**Context:** Senior Software Engineer build exercise. 30-minute time box. CLI only, no web UI, no database.
**Purpose of this file:** this is the artifact produced *before* any code is written. It is committed first so the git history shows the thinking preceded the implementation.

---

## 1. Problem definition

The brief is deliberately underspecified. "Build an alarm clock" hides four hard questions that a naive implementation gets wrong, and those questions are the actual exercise:

1. **What is the source of truth for time?** Wall-clock time moves backwards (NTP corrections, DST, manual clock changes). A loop that computes `next_fire - now` once and sleeps for that duration will fire early or late or twice.
2. **What happens when the process is not running?** A laptop sleeps. An alarm set for 07:00 on a machine that wakes at 07:20 must decide: fire late, or skip and report as missed?
3. **What does "the alarm is off" mean?** Dismissal is a state transition, not a keypress. Snooze, dismiss, auto-timeout and puzzle-gated dismissal are all the same state machine with different guards.
4. **How does this get tested in under a second?** An alarm clock is a time-dependent system. If the tests need real time to pass, there are no tests.

Everything below follows from those four.

---

## 2. Scope decisions and what is explicitly out

| In scope                                 | Out of scope, and why                                                                                                      |
| ---------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| Foreground `run` process the user starts | Background daemon / systemd / launchd install. Real product need, not demonstrable in 30 minutes, and OS-specific.         |
| JSON file persistence with atomic writes | Database. Excluded by the brief, and unnecessary for tens of records.                                                      |
| Synthesised audio tones, stdlib only     | Bundled audio binaries. Licensing provenance is a liability and a repo full of `.wav` blobs proves nothing. See section 6. |
| Local timezone via `zoneinfo`            | Multi-timezone alarms. Nice idea, no user need here.                                                                       |
| One puzzle family, three difficulties    | Puzzle marketplace / plugin loading. Over-engineering.                                                                     |

**Stated assumption:** single user, single machine, alarms measured in minutes-to-days, not milliseconds. Precision target is ±1 second, which is far inside human perception for this use case and lets the run loop poll rather than busy-wait.

---

## 3. The five features

### F1 — Setting an alarm

```
alarm set 07:30 --label "Standup" --repeat weekdays
alarm set "in 45m" --label "Laundry"
alarm list
alarm delete 3
alarm disable 2 / alarm enable 2
```

- Accepts `HH:MM`, `HH:MM:SS`, 12-hour (`7:30am`), and relative (`in 20m`, `in 1h30m`).
- Recurrence: `once` (default), `daily`, `weekdays`, `weekends`, or an explicit day list `mon,wed,fri`.
- `next_fire()` is a pure function of `(alarm, now)` returning an aware datetime. This is the single most tested function in the repo.
- **DST rule:** recurring alarms are stored as local wall-clock time and resolved forward. If 02:30 does not exist on a spring-forward day, fire at the first valid instant after it. If it occurs twice on fall-back, fire on the first occurrence only. This is decided in advance, documented, and tested, rather than discovered in production.

### F2 — Snooze

```
[SNOOZE] pressed  →  next ring in 5m (snooze 1 of 3)
```

- Configurable interval (default 5m) and a **maximum snooze count** (default 3), after which snooze is refused and the only exit is a real dismissal. An alarm you can snooze forever is a clock, not an alarm.
- Snooze does not mutate the alarm's schedule. It creates a transient in-memory ring session, so a snoozed daily alarm still fires normally tomorrow.

### F3 — Sounds

```
alarm sounds                    # list available
alarm set 07:30 --sound chirp
alarm test-sound chirp
```

- Four built-in tones generated at runtime with `wave` + `math`: `beep`, `chirp`, `rising`, `pulse`. No binary assets, no download step, no licence to audit.
- `--sound-file /path/to/x.wav` accepts any user-supplied WAV, which is the escape hatch for anyone who wants a real track.
- Playback is a fallback chain, tried in order and degraded gracefully: `simpleaudio` if installed → OS player (`afplay` / `paplay` / `aplay` / `winsound`) → terminal bell + visible banner. The clock still works with zero audio backends, it just becomes a visual alarm.

### F4 — Closing mechanism (dismissal)

The ring session is a small explicit state machine:

```
RINGING ──dismiss──> DISMISSED
   │  ├──snooze (if count < max)──> SNOOZED ──timer──> RINGING
   │  └──auto-timeout (default 10m)──> MISSED
   └──[if puzzle enabled] dismiss is gated by F5
```

- Default dismissal is a single keypress plus confirmation.
- `--dismiss type-phrase` requires retyping a randomly generated phrase exactly.
- Auto-timeout stops the noise after 10 minutes and records the alarm as `MISSED` rather than ringing into an empty room indefinitely.
- **Missed-alarm policy on startup:** on `run`, any alarm whose fire time passed while the process was down fires immediately if it is within a 15-minute grace window, otherwise it is logged as missed and skipped. This is the sleeping-laptop question from section 1, answered explicitly.

### F5 — Puzzle-gated dismissal (advanced setting, off by default)

```
alarm config set puzzle.enabled true
alarm config set puzzle.type math
alarm config set puzzle.difficulty hard
alarm config set puzzle.streak 2
```

- `Puzzle` is a protocol with `prompt() -> str` and `check(answer) -> bool`. Implementations: `math` (n-digit arithmetic), `sequence` (complete the pattern), `retype` (transcribe a random string exactly).
- Difficulty scales the parameters, not the puzzle type. `streak` requires N consecutive correct answers, since one lucky guess should not disarm anything.
- Sound keeps playing while the puzzle is on screen. That is the entire point of the feature.
- **Safety valve, and this is a deliberate design decision:** three `Ctrl+C` within five seconds force-stops the ring, prints a warning, and writes the override to the event log. A puzzle lock with no escape is a program that can hold a user's machine hostage over an arithmetic error at 6am. Auditable override beats no override.

---

## 4. Architecture

```
alarmclock/
├── cli.py          argparse dispatch, no logic
├── models.py       Alarm, Recurrence, RingState  (frozen dataclasses)
├── clock.py        Clock protocol | SystemClock | FakeClock
├── store.py        load/save JSON, atomic via tmp + os.replace
├── schedule.py     next_fire(alarm, now) -> datetime | None   [pure]
├── runner.py       the poll loop
├── ringer.py       ring session state machine
├── audio.py        Player protocol + backend fallback chain
├── puzzles.py      Puzzle protocol + 3 implementations
└── config.py       settings + XDG-ish paths
tests/              pytest, all hermetic
docs/PROMPTS.md     the AI prompts used and what was rejected
docs/DECISIONS.md   short ADR-style log
```

**Key decisions and their reasons:**

| Decision                                                                | Reason                                                                                                 | Rejected alternative                                                                                   |
| ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------ |
| `argparse`, zero runtime dependencies                                   | `pip install` and run, on any Python 3.11+. Reviewers should not fight an environment.                 | `click` / `typer`: nicer, but a dependency for a 30-minute exercise is a cost with no payoff here.     |
| Poll loop at 0.5s on `time.monotonic`, re-deriving wall clock each tick | Survives NTP jumps, suspend/resume and DST. Drift cannot accumulate because nothing is precomputed.    | `threading.Timer` per alarm: one thread per alarm, and a long sleep is exactly what clock jumps break. |
| `Clock` injected everywhere                                             | `FakeClock` lets a test advance a week in microseconds. Non-negotiable for a time system.              | `freezegun` / `monkeypatch` on `datetime`: patches the world instead of designing the seam.            |
| Atomic write (`tmp` + `os.replace`)                                     | The process can be killed mid-write at any moment. A truncated alarms file loses every alarm silently. | Plain `open(..., "w")`.                                                                                |
| Audio behind a `Player` protocol                                        | Tests use `NullPlayer` and assert on calls. No CI machine needs a sound card.                          | Direct calls into a playback lib from the ringer.                                                      |
| `next_fire` is pure                                                     | Every scheduling edge case becomes a table-driven unit test with no I/O.                               | Time logic embedded in the loop, untestable.                                                           |

---

## 5. Time-boxed build order

Vertical slice first. At every cut line the repo is in a working, demonstrable state.

| Time      | Slice                                                        | Done when                                         |
| --------- | ------------------------------------------------------------ | ------------------------------------------------- |
| 0:00–0:06 | AI-assisted requirements and design refinement, this file    | `plan.md` and `docs/DECISIONS.md` committed       |
| 0:06–0:11 | `models`, `clock`, `store`, `schedule.next_fire` + its tests | `pytest` green on scheduling table                |
| 0:11–0:17 | `runner` + `ringer` + `cli set/list/run`                     | **First working alarm: set, wait, ring, dismiss** |
| 0:17–0:21 | Snooze with cap, auto-timeout, missed-alarm catch-up         | State machine tests green                         |
| 0:21–0:25 | `audio` synth + backend fallback + `sounds` / `test-sound`   | Audible on the recording                          |
| 0:25–0:29 | `puzzles` + config gate + safety valve                       | Puzzle demo on camera                             |
| 0:29–0:30 | Full test run, README                                        | `pytest -q` green on camera                       |

**Cut line, stated in advance:** if behind at 0:21, ship `math` puzzle only and drop `sequence` and `retype`. If behind at 0:25, README gets a stub and the honest "not finished" note. Nothing gets half-committed to look complete. If the session runs past 30 minutes, the README says so and says by how much, because the grader can read the commit timestamps anyway.

---

## 6. Sounds and licensing

Open-source audio was the obvious route and I rejected it for the built-ins. Freesound and similar require per-file attribution, and CC-BY vs CC0 varies file by file. Committing five `.wav` files means committing five licence obligations that a reviewer has to take on trust.

Generating the tones instead makes the repo self-contained, keeps it under 100KB, means the sound set is parameterised rather than fixed, and removes the licence question entirely. `--sound-file` covers anyone who wants their own audio, and `docs/DECISIONS.md` records this trade so it reads as a decision and not an omission.

---

## 7. Commit structure

Ten commits. The log is a deliverable: it should read as a narrative of the build, and each commit should be individually reviewable.

| #   | Message                                                           | Contents                                                   |
| --- | ----------------------------------------------------------------- | ---------------------------------------------------------- |
| 1   | `docs: requirements, design and build plan before writing code`   | `plan.md`, `docs/DECISIONS.md`, `.gitignore`               |
| 2   | `docs: record AI prompts used and output rejected`                | `docs/PROMPTS.md`                                          |
| 3   | `feat: alarm model, injectable clock and atomic JSON store`       | `models.py`, `clock.py`, `store.py`, `tests/test_store.py` |
| 4   | `feat: pure next_fire scheduling with DST and recurrence rules`   | `schedule.py`, `tests/test_schedule.py`                    |
| 5   | `feat: CLI set/list/delete and the run loop, first ringing alarm` | `cli.py`, `runner.py`, minimal `ringer.py`                 |
| 6   | `feat: snooze with cap, auto-timeout and missed-alarm catch-up`   | `ringer.py` state machine, `tests/test_ringer.py`          |
| 7   | `feat: synthesised tones with a degrading playback backend chain` | `audio.py`, `tests/test_audio.py`                          |
| 8   | `feat: puzzle-gated dismissal behind advanced config`             | `puzzles.py`, `config.py`, `tests/test_puzzles.py`         |
| 9   | `fix: <the real bug found while testing>`                         | Whatever actually broke. Do not fake this one.             |
| 10  | `docs: README with architecture, usage and known limitations`     | `README.md`                                                |

Rules: no commit named `wip` or `update`. Every message says what changed and implies why. Commit 9 exists because something will break, and a history with no fix commit in it is a history that was rewritten.

---

## 8. README specification

Ordered so a reviewer with four minutes gets what they need from the first screen.

1. **One line** on what it is, and one line on the constraint it was built under (30-minute exercise, CLI only).
2. **Quickstart**, four commands: clone, `pip install -e .`, `alarm set "in 1m"`, `alarm run`.
3. **Command reference table**: command, what it does, example.
4. **Design decisions**: the table from section 4 above, verbatim. This is the section the exercise is actually grading.
5. **Architecture**: the module tree with one line per module.
6. **The five features**, one short paragraph each, with the puzzle safety valve called out explicitly.
7. **Testing**: `pytest -q`, why it runs in under a second, what `FakeClock` does.
8. **Known limitations and what I would do next**, honest and specific: no background daemon, no multi-timezone, puzzle set is small, snooze state is in-memory so a restart mid-snooze loses it. Naming real gaps is worth more than a feature list.
9. **AI usage**: link to `docs/PROMPTS.md`, one paragraph on what the AI was used for and what its output got rejected.
10. **Video link.**

No badges, no roadmap section, no emoji headers.

---

## 9. How AI was directed (and the record of it)

`docs/PROMPTS.md` is a committed artifact, not a formality. It records, for each phase: the prompt given, what came back, and what was changed or thrown away. At minimum it should contain:

- The requirements-refinement prompt, and the suggestions rejected as out of scope (background daemon, multiple timezones, TUI framework).
- The scheduling prompt, and the DST edge case the first output missed.
- One instance of a generated function being rewritten, with the reason.

If the AI output is used unchanged everywhere, the log says that too. The point is a truthful record of review, not a performance of scepticism.

---

## 10. Validation before submitting

- `pytest -q` green, on camera, unedited.
- Manual end-to-end: `alarm set "in 1m"` → `alarm run` → hear it → snooze → hear it again → dismiss.
- Puzzle path: enable in config, ring, fail once deliberately, then solve and dismiss.
- Fresh clone into a clean venv, run the quickstart exactly as the README states it.
- `git log --oneline` reads as a coherent story.
