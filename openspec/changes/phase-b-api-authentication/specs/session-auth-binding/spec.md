# Session Auth Binding Specification

## Purpose

Auth context resolution happens exactly once per call or demo session at session start. The resolved identity is cached in memory for the session lifetime. All subsequent per-turn agent responses and tool calls read from the in-memory cache — zero DB or network operations per turn. This is the mandatory fast path that preserves voice response latency.

## Requirements

### Requirement: Session-Start Context Resolution

At call or demo session start, the system MUST resolve and validate the full auth context: `client_id`, `agent_id`/slug, `lead_id`, scopes/permissions, and voice context. The resolved identity MUST be stored in an `AuthorizedSession` object cached in memory, keyed by the call/session ID.

#### Scenario: Voice session established at call start

- GIVEN a valid incoming voice initiation webhook with a resolvable `client_id`
- WHEN the initiation handler runs
- THEN an `AuthorizedSession` is created with `client_id`, `agent_id`, `lead_id`, scopes, and voice context; it is stored in the in-memory session store keyed by the call session ID

#### Scenario: Invalid client_id at session start

- GIVEN a voice initiation webhook with an unknown or unauthorized `client_id`
- WHEN the initiation handler attempts to resolve the session context
- THEN no `AuthorizedSession` is created and the request is rejected with HTTP 401 or 403

### Requirement: Per-Turn Fast Path (Non-Negotiable)

The per-turn agent response handler (`/voice/custom-llm/*`) MUST NOT perform any DB reads, network calls, or external auth lookups. It MUST retrieve the `AuthorizedSession` from the in-memory session store using the call/session ID. Any DB or network operation on this path is a build-blocking defect.

#### Scenario: Turn uses in-memory session — no DB I/O

- GIVEN an active voice session with a cached `AuthorizedSession`
- WHEN `/voice/custom-llm/*` receives a turn request
- THEN the handler retrieves `AuthorizedSession` from memory; zero DB queries are executed; response latency added by auth is ~0 ms

#### Scenario: Turn arrives with unknown session ID

- GIVEN a turn request with a session ID not present in the session store
- WHEN the handler attempts to retrieve the `AuthorizedSession`
- THEN the request is rejected with HTTP 401; no handler logic executes

### Requirement: Tool Scope Validation

Before executing any write or data-load operation, a tool MUST validate its required scope against the caller's `AuthorizedSession`. Scope checks MUST be synchronous and in-memory — no external calls.

#### Scenario: Tool with valid scope executes

- GIVEN a tool call during an active voice turn with an `AuthorizedSession` carrying the required scope
- WHEN the tool's scope check runs
- THEN the tool proceeds to read/write data within the authorized boundary

#### Scenario: Tool with insufficient scope is blocked

- GIVEN a tool call whose required scope is not present in the `AuthorizedSession`
- WHEN the tool's scope check runs
- THEN the tool returns an error without reading or writing any data; no DB side-effects occur

### Requirement: Session Lifecycle and Cleanup

`AuthorizedSession` objects MUST be removed from the in-memory store when the associated call lifecycle ends (call completion, post-call webhook received, or explicit session close). A configurable TTL safety cleanup MUST exist to prevent stale sessions accumulating from abnormal terminations. TTL cleanup MUST NOT evict sessions for calls still in progress.

**Assumption**: Call lifecycle events are the primary cleanup trigger. TTL is a safety net only. Default TTL: 4 hours. Configurable via `QORA_SESSION_TTL_SECONDS`.

#### Scenario: Session removed on call end

- GIVEN an active `AuthorizedSession` for a completed call
- WHEN the post-call lifecycle event is received
- THEN the `AuthorizedSession` is evicted from the session store

#### Scenario: TTL evicts stale session only after call is gone

- GIVEN a session that has not received a lifecycle end event and has exceeded the configured TTL
- WHEN the TTL cleanup runs
- THEN the session is evicted; active in-progress calls are not affected

### Requirement: Scheduler-Derived Session

Scheduler-started calls MUST derive an `AuthorizedSession` from the `scheduled_call → lead → client → agent` identity chain at call creation time. No manual auth input or separate auth resolution is required for scheduler-initiated calls.

#### Scenario: Scheduler call creates valid session

- GIVEN a `ScheduledCall` record with resolvable `lead → client → agent` chain
- WHEN the scheduler triggers call creation
- THEN an `AuthorizedSession` is created and stored with identity derived from the chain; subsequent voice turns use this session normally
