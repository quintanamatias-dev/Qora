# Delta for Outbound Call Trigger

## MODIFIED Requirements

### Requirement: Scheduler Reuse Contract

The shared `dial_outbound_call(lead, agent, scheduled_call=None)` function
MUST serve as the sole entry point for dialing, accepting an optional
`ScheduledCall` reference. The manual trigger endpoint MUST call this
function with `scheduled_call=None`. The scheduler's auto-dialer runner MUST
call it with a live `ScheduledCall` reference for a claimed row, reusing the
same guards, retry lane, and `CallSession` writes as a manual call, without
duplicating any business logic.
(Previously: scheduler reuse was described as a "future" capability the
function signature merely accommodated; the auto-dialer runner now activates
this path.)

#### Scenario: Manual call — no ScheduledCall reference

- GIVEN a manual trigger with no associated `ScheduledCall`
- WHEN `dial_outbound_call` is invoked
- THEN `scheduled_call=None` is passed
- AND the function behaves identically except it does not update a
  `ScheduledCall` record

#### Scenario: Auto-dialer call — ScheduledCall reference is live

- GIVEN the scheduler's auto-dialer runner has claimed a due `ScheduledCall`
- WHEN it calls `dial_outbound_call(..., scheduled_call=sc)`
- THEN the function accepts the parameter without modification
- AND `sc.outcome_session_id` is set from the resulting `CallSession` when
  the dial is accepted
