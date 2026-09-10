# Scheduling decisions: DST and recurrence

These are policy commitments for `next_fire(alarm, now)`. All three are
resolved inside the pure function against a stored IANA zone name; none
depend on the host's current zone or on wall-clock arithmetic with
`timedelta`.

| Scenario | Committed behaviour | Proving case |
| --- | --- | --- |
| **Spring-forward on a local time that does not exist.** Recurring daily alarm at 02:30 in `America/New_York`. On the spring-forward date the clocks jump 02:00 -> 03:00, so 02:30 never occurs locally. | Fire once, at the instant the wall clock skips past the target: the alarm rings at 03:00 local (= 07:00 UTC), the first real instant at or after the requested time. The occurrence is not skipped and is not duplicated. Equivalent to `fold`-agnostic "gap -> shift forward to the boundary". | `FakeClock` set to the spring-forward date, ticking 1s from 01:59:00 local. `next_fire` returns the occurrence whose UTC instant is `03:00` local; the ringer fires exactly once as the tick crosses it; the next call to `next_fire` returns the following day's 02:30, proving no double-fire and no skip. |
| **Fall-back on a local time that occurs twice.** Recurring daily alarm at 01:30 in `America/New_York`. On the fall-back date the clocks repeat 01:00 -> 02:00 then 01:00 again, so 01:30 local occurs twice (fold 0 = first/EDT, fold 1 = second/EST). | Fire once, on the **first** occurrence (`fold=0`, the earlier UTC instant, 05:30 UTC). The second 01:30 (fold 1, 06:30 UTC) is treated as already fired for that calendar day and is not rung again. Rationale: earliest-instant is the deterministic choice and matches "wake me at 01:30, once". | `FakeClock` on the fall-back date, ticking 1s from 00:59:00 local through 02:01:00 local (which spans both 01:30s). Assert the ringer fires exactly once, at the tick corresponding to `05:30` UTC; assert the second 01:30 wall-clock instant produces no fire; assert `next_fire` afterwards points at the next day's 01:30. |
| **Weekdays alarm created on a Friday evening.** Alarm with recurrence = Mon-Fri, created Friday 18:00 local for a 07:00 fire time. "Now" is Friday 18:00. | The next fire is **Monday 07:00**, not Saturday and not the already-passed Friday 07:00. `next_fire` advances day-by-day from `now`, skips any date whose weekday is not in the recurrence set, and skips a same-day match whose time is already in the past. Weekend days are silently passed over; the alarm resumes Monday. | `FakeClock` fixed at a known Friday 18:00 local (a specific dated instant, e.g. 2026-09-11T18:00 in the alarm's zone). Assert `next_fire` returns 2026-09-14T07:00 (Monday). Add cases: called Saturday 10:00 -> still Monday 07:00; called Monday 06:00 -> Monday 07:00 same day; called Monday 08:00 -> Tuesday 07:00. |

## Assumptions

- Gap policy (spring-forward): shift forward to the first valid instant.
  The alternative (skip the occurrence entirely) is rejected because a
  daily alarm that silently does not ring once a year is a worse
  surprise than one that rings 30 minutes late.
- Fold policy (fall-back): fire on `fold=0`, the earlier instant. The
  alarm is keyed to a local time, and firing once per local-time label
  per day is the contract; the repeated label does not earn a second
  ring.
- "Already fired today" is tracked by a per-alarm last-fired marker
  (UTC instant), so both the fold case and any wall-clock backward step
  are de-duplicated by the same mechanism rather than by special-casing
  DST.
- Weekday set is evaluated in the alarm's stored zone, so "is it a
  weekday" uses local calendar date, not UTC date.
- Dates in the proving cases are concrete and in the past/near-future
  relative to 2026-09-09 so the tests are deterministic; the real
  spring-forward / fall-back dates for `America/New_York` used in tests
  are 2026-03-08 and 2026-11-01.
