# infra/perf-backfill: xut heavy backfill lane

Stacked on `infra/nice` (#31). This is a draft, parked until fewer than 3 of
my PRs are open.

## What changed

- **The head.** The command holding the gate is the head. It publishes its
  wait (`head.json`: need, since, pid). While its wait is younger than
  `BACKFILL_AGE_S` (300 s), it takes its tokens all at once or none, under
  `backfill.lock`, so free tokens stay free.
- **Backfill.** A command waiting for the gate tries a backfill: an
  all-or-none take of its tokens under `backfill.lock`, allowed only while
  the head's wait is younger than the cap. A dead head's file (its process is
  gone) never blocks a backfill.
- **Past the cap.** The head hoards tokens as they are released, under
  `backfill.lock`, and no backfill is allowed, so it cannot starve.
- **Invariant.** Every token is still an exclusive flock, so the 96G budget
  holds in any order.
- **AGENTS §10.1** describes the lane.

## Tests

`test_heavy.py`: 54 passed, 20 runs out of 20, in a capped scope. New tests:
- without backfill (cap 0) the head is never overtaken;
- a small command backfills ahead of a young head;
- **starvation:** past the cap, a command that would fit waits behind the
  head, and the head is admitted first when tokens are released;
- a dead head's `head.json` never blocks a backfill.
