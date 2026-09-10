# Manual testing guide (PowerShell)

A walkthrough for a new user on Windows: install the tool, then run one test
case per feature. Every case is written **side by side** -- the left column is
exactly what you type, the right column is what you should see and why.

Run everything from a PowerShell prompt (Windows PowerShell 5.1 or
PowerShell 7 both work).

---

## 0. Install

Use a virtual environment. It is the reliable path on Windows: inside an
active venv the `alarm` command is on `PATH` automatically, with no folder to
add by hand.

| Do this | Expect |
| --- | --- |
| `cd C:\Users\shrey\OneDrive\Desktop\git\Python-Alram-Clock-CLI\python-Alarm-Clock-CLI` | You are in the folder that contains `pyproject.toml` and the `alarmclock\` package. |
| `python --version` | `Python 3.11` or newer. If this fails, install Python first. |
| `python -m venv .venv` | Creates `.venv\` in the project folder. |
| `.\.venv\Scripts\Activate.ps1` | Prompt gains a `(.venv)` prefix. If you get an execution-policy error, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` and try again. |
| `pip install -e ".[dev]"` | Installs the package in editable mode plus `pytest`. Last line is roughly `Successfully installed alarmclock-0.1.0 ...`. |
| `alarm --help` | Usage text listing the subcommands `set, list, delete, enable, disable, run, sounds, test-sound, config`. |

**If you skipped the venv and `alarm` is "not recognized":** you installed
with `--user` and pip put `alarm.exe` in a folder that is not on `PATH` (pip
prints a `WARNING: The script alarm.exe is installed in '...\Scripts' which is
not on PATH` line when this happens). Two fixes:

- Simplest: use `python -m alarmclock` in place of `alarm` for every command
  below. It is identical in every way.
- Or add the folder to `PATH` for the current window (read the exact path
  from pip's warning; it is usually the one below), then re-run `alarm --help`:

  ```
  $env:Path += ";$env:APPDATA\Python\Python314\Scripts"
  ```

  To make that permanent, set it on the user profile and open a new window:

  ```
  [Environment]::SetEnvironmentVariable("Path",
    [Environment]::GetEnvironmentVariable("Path","User") + ";$env:APPDATA\Python\Python314\Scripts",
    "User")
  ```

**Where state is stored.** Alarms, settings and the override log all live under
`C:\Users\<you>\AppData\Roaming\alarmclock\`:

| File | Holds |
| --- | --- |
| `alarms.json` | your alarms |
| `config.json` | the advanced (puzzle) settings |
| `overrides.log` | one line per SIGINT force-stop |

To start from a clean slate at any point:

```
Remove-Item "$env:APPDATA\alarmclock" -Recurse -Force -ErrorAction SilentlyContinue
```

---

## 1. Run the automated tests first

| Do this | Expect |
| --- | --- |
| `pytest -q` | `76 passed in <1s`. Confirms the install is sound before you test by hand. |

---

## 2. Set a one-off alarm and see it listed

| Do this | Expect |
| --- | --- |
| `alarm set "07:30" --label "Standup"` | `added <id>  07:30:00  once` -- `<id>` is an 8-character hex string, note it down. |
| `alarm list` | A row: `<id>  [on ]  07:30:00  once       Standup`. `[on ]` means enabled. |
| `alarm set "7:30am" --label "Same time, 12h format"` | `added <id2>  07:30:00  once` -- the 12-hour form parses to the same 24-hour time. |
| `alarm set "in 45m" --label "Relative"` | `added <id3>  HH:MM:SS  once` where the time is 45 minutes from now. Relative times are converted to a wall-clock time immediately. |
| `alarm list` | All three rows present. |

---

## 3. Recurrence variants

| Do this | Expect |
| --- | --- |
| `alarm set "06:15" --label Weekdays --repeat weekdays` | `added <id>  06:15:00  weekdays` |
| `alarm set "09:00" --label Weekend --repeat weekends` | `added <id>  09:00:00  weekends` |
| `alarm set "18:00" --label Gym --repeat mon,wed,fri` | `added <id>  18:00:00  mon,wed,fri` |
| `alarm set "08:00" --repeat funday` | Error: `alarmclock: unrecognised repeat: 'funday'`, exit code 2. Nothing is added. |
| `alarm list` | The three valid recurring alarms are listed with their recurrence in column 4. |

Check the exit code of the last command with `$LASTEXITCODE` (should be `2`
for the bad one, `0` for the good ones).

---

## 4. Enable, disable, delete

| Do this | Expect |
| --- | --- |
| `alarm set "12:00" --label Scratch` | `added <id>  12:00:00  once`. Copy this `<id>` for the next rows. |
| `alarm disable <id>` | No output, exit 0. |
| `alarm list` | The Scratch row now shows `[off]` instead of `[on ]`. A disabled alarm is skipped by `run`. |
| `alarm enable <id>` | No output. `alarm list` shows `[on ]` again. |
| `alarm delete <id>` | No output, exit 0. |
| `alarm list` | The Scratch row is gone. |
| `alarm delete <id>` (same id again) | Error: `alarmclock: no alarm '<id>'`, exit code 1. |

---

## 5. Invalid time input is rejected cleanly

| Do this | Expect |
| --- | --- |
| `alarm set "25:00"` | `alarmclock: unrecognised time: '25:00'`, exit 2, nothing added. |
| `alarm set "banana"` | `alarmclock: unrecognised time: 'banana'`, exit 2. |
| `alarm set "in banana"` | `alarmclock: unrecognised time: 'in banana'`, exit 2. |
| `alarm set "13:00pm"` | `alarmclock: invalid 12-hour time: '13:00pm'`, exit 2. |
| `alarm list` | Unchanged -- none of the above created an alarm. |

---

## 6. Sounds: list and preview

| Do this | Expect |
| --- | --- |
| `alarm sounds` | Four lines: `beep`, `chirp`, `rising`, `pulse`. |
| `alarm test-sound beep` | You hear a short triple beep. Prints `playing beep via <backend>` -- backend is `simpleaudio`, `os-player`, or `banner`. |
| `alarm test-sound chirp` | A faster, higher two-tone chirp -- audibly different from `beep`. |
| `alarm test-sound rising` | A four-note rising arpeggio, ~1 second, twice. |
| `alarm test-sound pulse` | A wavering (tremolo) tone. |
| `alarm test-sound nope` | Error: `alarmclock: unknown sound 'nope'; try 'sounds' or a WAV path`, exit 2. |
| `alarm test-sound "C:\Windows\Media\Alarm01.wav"` | Plays that system WAV once. Any readable `.wav` path works. If the file does not exist you get a `FileNotFoundError` line, exit 1. |

If you have no working audio backend at all, `test-sound` still runs: it rings
the terminal bell and prints a banner instead of failing.

---

## 7. First real alarm: set, run, dismiss

This is the core end-to-end. `alarm run` loads alarms **once at startup**, so
always `set` before you `run`.

| Do this | Expect |
| --- | --- |
| `alarm set "in 1m" --label "Ring test"` | `added <id>  HH:MM:SS  once` -- one minute from now. |
| `alarm run` | The process blocks with no output and polls every half second. |
| _(wait ~1 minute)_ | `*** ALARM: Ring test (HH:MM:SS) ***` prints, sound starts, and you get the prompt `[s]nooze / [d]ismiss:` |
| Press `Enter` (or type `d` then `Enter`) | Sound stops. The ring session ends. Because it was a one-off alarm, `run` has nothing left and you are returned to the shell. |

To stop `run` at any time without an alarm firing: press `Ctrl+C` once. You
should see `alarmclock: stopped.` and a clean exit, no traceback.

---

## 8. Snooze, then the snooze cap

| Do this | Expect |
| --- | --- |
| `alarm set "in 1m" --label Snoozer --snooze-minutes 1` | Alarm one minute out, snooze interval set to 1 minute so you don't wait 5. |
| `alarm run` then wait for the ring | Prompt `[s]nooze / [d]ismiss:` |
| Type `s`, `Enter` | Sound stops. The alarm is snoozed; `run` keeps going silently. |
| _(wait ~1 minute)_ | It rings again. This is snooze 1 of 3. |
| `s`, `Enter` -- repeat until you have snoozed 3 times total | Each snooze works. |
| On the 4th ring, type `s`, `Enter` | `alarmclock: snooze limit reached (3); dismiss the alarm to stop it`. Sound keeps playing. |
| Press `Enter` (dismiss) | Now it stops. Dismissal is the only exit once the cap is hit. |

Snooze is in-memory only. If you `Ctrl+C` out of `run` mid-snooze and start
it again, the snooze is forgotten and the alarm reverts to its normal
schedule.

---

## 9. Auto-timeout to MISSED

| Do this | Expect |
| --- | --- |
| `alarm set "in 1m" --label Ignore-me` | One minute out. |
| `alarm run`, wait for the ring, then walk away | Do not press anything. |
| _(wait 10 minutes)_ | The sound stops on its own. The alarm is recorded as `MISSED` rather than ringing into an empty room. `run` continues (or exits if this was the only alarm). |

(10 minutes is the fixed auto-timeout. This case is worth doing once; it is
slow by design.)

---

## 10. Missed-alarm catch-up on startup

| Do this | Expect |
| --- | --- |
| `alarm set "in 1m" --label CatchMe` | One minute out. |
| _Do not run yet._ Wait ~2 minutes so the fire time passes with no `run` process alive. | The alarm's time is now in the past. |
| `alarm run` | On startup it notices the fire time passed within the last 15 minutes and **rings immediately**. You get the normal prompt. |
| Dismiss it. | Back to the shell. |

If you instead wait more than 15 minutes before running, startup prints
`alarmclock: missed CatchMe, was due <timestamp>` to stderr and does **not**
ring -- it is treated as a genuine miss.

---

## 11. Advanced: puzzle-gated dismissal

| Do this | Expect |
| --- | --- |
| `alarm config show` | Four lines, all defaults: `puzzle.enabled = false`, `puzzle.type = math`, `puzzle.difficulty = easy`, `puzzle.streak = 1`. |
| `alarm config set puzzle.enabled true` | Echoes `puzzle.enabled = true`. |
| `alarm config set puzzle.type math` | `puzzle.type = math` |
| `alarm config set puzzle.difficulty easy` | `puzzle.difficulty = easy` |
| `alarm config set puzzle.streak 2` | `puzzle.streak = 2` -- you will need two correct answers in a row. |
| `alarm config set puzzle.type nope` | Error: `alarmclock: puzzle.type must be one of math, sequence, retype, got 'nope'`, exit 2. Setting unchanged. |
| `alarm config set puzzle.streak 0` | Error: `alarmclock: puzzle.streak must be at least 1`, exit 2. |
| `alarm set "in 1m" --label Puzzled` | One minute out. |
| `alarm run`, wait for the ring | Prompt shows a sum, e.g. `[s]nooze | solve to dismiss (0/2): 7 + 3 = ?` followed by `> `. Sound is playing. |
| Type a **wrong** answer, `Enter` | `alarmclock: not solved yet`. A **new** puzzle appears and the streak is back to `0/2`. Sound never stopped. |
| Type the **correct** answer, `Enter` | Streak goes to `1/2`, a fresh puzzle appears. |
| Type the next correct answer, `Enter` | Streak reaches `2/2`, the gate opens, sound stops, alarm dismissed. |
| `alarm config set puzzle.enabled false` | Turn the gate back off when done. |

Snooze is never gated: typing `s` at the puzzle prompt still snoozes normally.

---

## 12. Advanced: the SIGINT safety valve

A puzzle you cannot solve must not trap you. Three `Ctrl+C` within five
seconds force-stop the ring regardless of the puzzle.

| Do this | Expect |
| --- | --- |
| Ensure the puzzle gate is on (`alarm config set puzzle.enabled true`). | |
| `alarm set "in 1m" --label Trapped` then `alarm run`, wait for the ring | Puzzle prompt, sound playing. |
| Press `Ctrl+C` once | `alarmclock: 2 more Ctrl+C within 5s to force-stop the alarm`. Sound keeps playing, the ring does **not** crash. |
| Press `Ctrl+C` again | `alarmclock: 1 more Ctrl+C within 5s to force-stop the alarm`. |
| Press `Ctrl+C` a third time (all within 5 seconds) | `alarmclock: ring force-stopped by SIGINT override (logged)`. Sound stops, alarm ends. |
| `Get-Content "$env:APPDATA\alarmclock\overrides.log"` | One line per override: `<timestamp>  SIGINT-OVERRIDE  alarm=<id>  label=Trapped`. |

If more than five seconds pass between presses the count resets -- a single
stray `Ctrl+C` will never force-stop anything.

---

## 13. Corrupt state file does not crash the CLI

| Do this | Expect |
| --- | --- |
| `alarm set "08:00" --label Canary` | Ensures `alarms.json` exists. |
| `Set-Content "$env:APPDATA\alarmclock\alarms.json" '{ this is not valid json'` | Truncates the file to garbage. |
| `alarm list` | `alarmclock: warning: ...alarms.json is corrupt or unreadable (...); starting with no alarms` on stderr, then `no alarms`. Exit 0 -- the CLI degrades instead of dying. |
| `alarm set "08:00" --label Recovered` | Writes a fresh valid file. `alarm list` now shows the one alarm. |

---

## Cleanup

```
Remove-Item "$env:APPDATA\alarmclock" -Recurse -Force -ErrorAction SilentlyContinue
deactivate
```

---

## Quick reference: what each command does

| Command | Purpose | Example |
| --- | --- | --- |
| `alarm set <time> [opts]` | Add an alarm | `alarm set "in 30m" --label Tea` |
| `alarm list` | Show all alarms | `alarm list` |
| `alarm enable <id>` / `disable <id>` | Toggle one alarm | `alarm disable 3f9c1a20` |
| `alarm delete <id>` | Remove one alarm | `alarm delete 3f9c1a20` |
| `alarm run` | Poll and ring until Ctrl+C | `alarm run` |
| `alarm sounds` | List built-in tones | `alarm sounds` |
| `alarm test-sound <name\|path>` | Preview a tone once | `alarm test-sound rising` |
| `alarm config show` | Print advanced settings | `alarm config show` |
| `alarm config set <key> <value>` | Change one setting | `alarm config set puzzle.enabled true` |

`set` options: `--label`, `--repeat once|daily|weekdays|weekends|<day,list>`,
`--sound beep|chirp|rising|pulse`, `--sound-file <path.wav>`,
`--snooze-minutes <n>`.
