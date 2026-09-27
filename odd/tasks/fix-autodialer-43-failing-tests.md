# Fix the 43 failing autodialer tests

## Objective

Bring `backend/tests/unit/outbound/` back to green so end-to-end product testing
happens against a branch where red means "new problem", not "pre-existing noise".

## Problem

43 tests fail in `tests/unit/outbound/`. 3433 tests pass elsewhere. The failures
are not 43 independent problems: triage grouped them into **two root causes**,
both of which are production changes that outran their test fixtures.

### Root cause A — tenant ownership Guard 0 (uncommitted)

`backend/app/outbound/service.py` gained an uncommitted `Guard 0: Tenant ownership`
at the top of `dial_outbound_call`. It rejects the call when
`lead.client_id != client.id`, returning
`DialResult(status="failed", failure_code="ownership_mismatch", error="Outbound target does not belong to this client.")`.

Most outbound tests build `lead` / `agent` with bare `MagicMock()`. A `MagicMock`
auto-creates `.client_id` as a new mock object, which never equals `client.id`, so
Guard 0 short-circuits before every other guard. That single guard explains the
whole symptom cluster:

- `failure_code == 'ownership_mismatch'` where the test expects
  `concurrent_scheduled_call` / `concurrent_active_session`
- `status == 'failed'` where the test expects `'dialing'`
- `0` provider calls where the test expects `1`
- error text `'Outbound target does not belong to this client.'` where the test
  expects a flag / phone_number_id / overlap message

The guard is deliberate tenant isolation and stays. The **fixtures** are what is
stale. `test_dial_service_behavior.py::_make_agent` already shows the intended
pattern (`agent.client_id = "client-a"`); it just was not propagated.

### Root cause B — AR-only phone normalizer

`backend/app/phones/normalization.py` is fail-closed and Argentina-only
(`_ALLOWED_REGION = "AR"`, `_ALLOWED_COUNTRY_CODE = 54`). Non-AR numbers raise
`PhoneNormalizationError("unsupported_country")`, and malformed AR numbers raise
`invalid_number`. The outbound router validates the lead phone at Guard 4 and
maps that error to **HTTP 422**.

Fixtures still carry US numbers such as `+14155552671`, so router tests get 422
where they expect 200 or 409. The router already maps
`failure_code in {concurrent_active_session, concurrent_scheduled_call}` to 409
correctly — the 409 mapping is not broken, the request never reaches it.

Commit `055f36a` ("repair seed phone numbers rejected by the AR normalizer") and
the uncommitted `+54119999001` → `+5491109999001` edit are the same repair,
applied partially.

## Scope

**In scope:** test fixture repair under `backend/tests/unit/outbound/`.

**Out of scope:** weakening or deleting assertions; changing `Guard 0`; changing
the phone normalizer; changing the 409 mapping. If a failure turns out to be a
genuine production bug rather than fixture drift, it is reported, not silently
patched around.

## Constraints

- Strict TDD mode is enabled. The tests are already RED; the work is to make them
  GREEN **without lowering the bar they assert**.
- Test runner: `backend/.venv/bin/python -m pytest`
- Valid AR mobile E.164 is `+549` + 10 digits (14 chars total), e.g.
  `+5491109999001`. Valid AR fixed-line is `+54` + 10 digits (13 chars).
- The other 3433 tests must stay green.

## Tasks

- [x] **T1** — Repair ownership fixtures: every outbound test that mocks a lead or
      agent sets `client_id` to match the client under test. Covers the
      `ownership_mismatch` / `'failed'` / `0 provider calls` cluster.
      Correction: `lead.client_id` was usually already set; the missing one was
      almost always `agent.client_id`.
- [x] **T2** — Repair phone fixtures: replace non-AR and malformed-AR numbers in
      `tests/unit/outbound/` with valid AR E.164. Covers the 422 cluster.
- [x] **T3** — Re-run the full suite, re-triage anything still red, and report
      whether each residual failure is fixture drift or a real production bug.
      Result: 0 residual red. **A third root cause was found** (see below).
- [x] **T4** — Commit as work units.
      `32e3594` test fixtures, `b2d60e5` tenant ownership guards.
      Both verified green standalone, so the branch bisects cleanly.

## Root cause C — CAS accepted path vs. in-memory observation (found during T3)

Not in the original triage. Commit `7ffa608` changed the accepted path from
mutating the in-memory `CallSession` to a conditional `UPDATE` plus
`db.refresh()`. Two tests observed the old behavior:

- `test_accepted_path_still_persists_all_fields_after_two_commit_flow` asserted
  `telephony_status == "ringing"` on the in-memory object. Against a mocked
  `db`, `refresh()` is a no-op, so the object stays `"dialing"` forever.
- `test_scheduled_call_no_overlap_guard_when_no_other_in_progress` used a finite
  `execute.side_effect` list; the extra `UPDATE` exhausted it into
  `StopIteration`.

Proven independent of Guard 0: with `service.py` stashed, the failure reproduced
identically. Verdict: test observation-point drift, not a product defect — the
production code documents the choice and the real-session tests added by that
same commit pass. Repaired by running the test against the real engine and
reading the committed row, which is a stronger proof than the in-memory
attribute.

## Acceptance criteria

- `backend/.venv/bin/python -m pytest tests/unit/outbound/ -q` → 0 failed.
- `backend/.venv/bin/python -m pytest tests/ -q` → 0 failed, 3476 passed.
- No assertion weakened, no test skipped, no test deleted.
- `app/outbound/service.py` Guard 0 and `app/phones/normalization.py` unchanged.

## Route

- Triage: direct inline (parent) — pytest runs + codegraph, no file reads needed.
- T1–T3: **delegated writer** (writer trigger — 10+ non-trivial test files).
- T4: direct inline (parent).

## TDD

Mode: strict (enabled, from session configuration).
Runner: `backend/.venv/bin/python -m pytest`.
RED already observed: 43 failed, 3433 passed (108s full suite).

## Progress

- Pushed the 6 pending commits to `origin/feat/c6b-auto-dialer-slice3-reaper`
  (`3f21910..055f36a`). Nothing of ours is unbacked anymore.
- Triage complete: 43 failures → 3 root causes (A, B, C).
- T1–T3 delegated to one writer; T4 committed by the parent.

## Verification evidence

- `.venv/bin/python -m pytest tests/unit/outbound/ -q` → `403 passed` (0 failed),
  re-run by the parent as a spot check.
- `.venv/bin/python -m pytest tests/ -q` → `3476 passed` (0 failed) in 103s.
- Guard check: no `skip` / `xfail` added; `app/phones/normalization.py` and
  `app/outbound/router.py` untouched.
- `gentle-ai review assess --base-ref 055f36a --committed-only` →
  `risk: medium`, `review_due: false` (`under_budget`, 234 changed lines).
  The slice stays pending until a later commit reaches the 400-line budget.

## Known open item (not part of this feature)

`.gitignore` gained `# Local Pi runtime state` / `.atl/`, but `.atl/` is still
tracked and modified, so the ignore rule does nothing on its own. Untracking it
changes whether the skill registry is shared with the team, which is a call for
the maintainer, not an incidental cleanup. Left uncommitted deliberately.

## Merge to main

The branch was the tip of a three-PR stacked chain, not a single branch:

```
#142  slice1-claim-dial      -> main
#144  slice2-completion-hook -> slice1
#147  slice3-reaper          -> slice2   (this work)
```

Verifying each slice before merging found that **slice1 and slice2 were each
1 test red on their own**, with the same invalid AR seed phone
(`+54119999001`) in the tech-retry durability fixture. Root cause B reached
further down the chain than the triage assumed.

Merged with merge commits, not squash: squashing a parent rewrites the base and
forces every stacked child to show the parent's work again as its own diff.
After merging #142 with a merge commit, #144 still showed only its own 10 files
/ 912 lines.

Order executed: `#142` -> fixture fix committed directly on main (`aa1b4be`,
maintainer's call) -> `#144` -> merge `main` into slice3 to resolve one
trivial conflict -> `#147`. Full suite verified green on main at every step
(3273 -> 3289 -> 3476 passed).

## Environment gotcha — iCloud duplicate files

Midway through, main appeared catastrophically broken: 20 failed, 741 errors,
`alembic MultipleHeads: 20260727_0011, 20260727_0011`. It was **not** a merge
defect. The repository lives under `~/Desktop`, which syncs with iCloud, and
rapid branch switching produced conflict-copy duplicates:

```
backend/alembic/versions/...auto_dialer_active_lead_index 2.py   (untracked)
openspec/changes/phase-c6b-auto-dialer/{design,proposal,tasks} 2.md
backend/qora 2.db-shm, backend/qora 2.db-wal
```

Alembic scans the whole `versions/` directory, so an untracked duplicate
migration carrying the same revision id creates two heads and takes down most
of the suite. The duplicate was moved aside, not deleted. **Verify this class
of file before believing a sudden mass failure after branch switching.**

## Next step

End-to-end on main, which is now fully green (3476 passed, single alembic head).
