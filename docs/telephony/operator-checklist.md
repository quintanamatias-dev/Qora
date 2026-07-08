# Operator Checklist: Telnyx + ElevenLabs SIP Trunk Setup

> **Phase C1 — Telephony Validation Prerequisites**
>
> This checklist must be completed before any test calls are made. Work through it
> top to bottom. Record only status flags and names here — never credential values,
> phone numbers, or API tokens. Store all secret values in your local `.env` file
> or your operator dashboard; they must never appear in committed files.
>
> **Legend**: `[x]` = code-verified (env var exists in config.py, feature implemented).
> `[ ]` = operator must verify (account setup, portal config, local `.env` values).

---

## 1. Telnyx Account Prerequisites

### 1.1 Account Status

| Prerequisite | Status | Notes |
|--------------|--------|-------|
| Telnyx account active (not suspended) | `[ ] confirmed` | Log in at portal.telnyx.com |
| Account has available credit | `[ ] confirmed` | ~40 test calls needed (20 AR + 20 US). Estimated cost: $2–5 USD at Telnyx rates. Add credit if balance is low. |
| Two-factor authentication enabled | `[ ] confirmed` | Required for security; do not store recovery codes in repo |

### 1.2 Telnyx API Key

| Prerequisite | Status | Notes |
|--------------|--------|-------|
| API key created in Telnyx portal | `[ ] confirmed` | Keys → API Keys → Create key. Operator must verify — Qora does not call Telnyx API directly (ElevenLabs handles SIP routing). |
| Key name recorded (name only, not the value) | `[ ] confirmed` | Example name: `qora-c1-test` |
| Key added to local `.env` as `TELNYX_API_KEY` | `[ ] confirmed` | **Do not commit this value.** Note: Qora's backend does not read this var — it is used only for Telnyx portal management. |

> ⚠️ The `.env` file is gitignored. Verify with `git status` before committing anything.

### 1.3 SIP Trunk Connection

| Prerequisite | Status | Notes |
|--------------|--------|-------|
| SIP connection created in Telnyx portal | `[ ] confirmed` | Connections → SIP Connections → Add Connection |
| Connection name recorded | `[ ] name: ___________` | Example: `qora-elevenlabs-sip` |
| Auth method selected | `[ ] digest auth` or `[ ] IP ACL` | Digest auth is simpler for local dev; IP ACL is more secure for VPS |
| SIP username/password set (digest) OR IP added (IP ACL) | `[ ] confirmed` | Store credentials in `.env` — do not commit |
| Connection ID noted (not a secret) | `[ ] id: ___________` | Visible in portal; used in ElevenLabs SIP trunk config |

> **Digest auth setup**: Create a SIP username and password in the connection settings.
> Store as `TELNYX_SIP_USERNAME` and `TELNYX_SIP_PASSWORD` in `.env`.

### 1.4 Outbound Voice Profile

| Prerequisite | Status | Notes |
|--------------|--------|-------|
| Outbound voice profile created | `[ ] confirmed` | Numbers → Outbound Voice Profiles → Add Profile |
| Profile name recorded | `[ ] name: ___________` | Example: `qora-outbound` |
| Argentina (`AR`) traffic allowed in profile | `[ ] confirmed` | Edit profile → Destinations → enable AR or set custom list |
| SIP connection linked to this voice profile | `[ ] confirmed` | Profile → Connections → assign the connection created above |

### 1.5 Caller ID / Phone Number

| Prerequisite | Status | Notes |
|--------------|--------|-------|
| Phone number purchased or verified in Telnyx | `[ ] confirmed` | Numbers → Buy Numbers |
| Number type | `[ ] US DID` or `[ ] Argentina DID` | US DID can dial Argentina; AR DID improves local CLI presentation |
| Number format confirmed E.164 | `[ ] confirmed` | Example format: `+1XXXXXXXXXX` (do not commit the actual number) |
| Number assigned to the SIP connection above | `[ ] confirmed` | Numbers → Manage → assign to connection |
| Number added to `.env` as `TELNYX_CALLER_ID` | `[ ] confirmed` | **Do not commit this value** |

### 1.6 Argentina Test Destination Number

| Prerequisite | Status | Notes |
|--------------|--------|-------|
| Argentina mobile test number available | `[ ] confirmed` | Must be a real number you control or have consent to test-call |
| Number format confirmed E.164 | `[ ] confirmed` | Format: `+54 9 XXXXXXXXXX` (mobile) or `+54 11 XXXXXXXX` (Buenos Aires landline) |
| Number added to `.env` as `ARGENTINA_TEST_NUMBER` | `[ ] confirmed` | **Do not commit this value** |
| Optional: US control number available | `[ ] confirmed` | For geographic baseline comparison; add as `US_CONTROL_NUMBER` in `.env` |

---

## 2. ElevenLabs SIP Trunk Prerequisites

### 2.1 ElevenLabs Account

| Prerequisite | Status | Notes |
|--------------|--------|-------|
| ElevenLabs account active with Conversational AI access | `[ ] confirmed` | Operator must verify — required for SIP trunk endpoint |
| API key present in local `.env` as `ELEVENLABS_API_KEY` | `[x] code-verified` | CRITICAL secret — `config.py` validates on startup. Startup aborts if missing/empty/placeholder. |
| Conversational AI agent exists and is working in browser | `[ ] confirmed` | Operator must verify — if browser demo works, this is satisfied |

### 2.2 ElevenLabs SIP Trunk Configuration

| Prerequisite | Status | Notes |
|--------------|--------|-------|
| SIP trunk enabled for your ElevenLabs account | `[ ] confirmed` | Operator must verify — check ElevenLabs dashboard → Conversational AI → Phone |
| SIP trunk endpoint confirmed as active | `[x] code-verified` | Endpoint: `POST /v1/convai/sip-trunk/outbound-call` — implemented in `elevenlabs/service.py` |
| ElevenLabs Phone Number resource created | `[ ] confirmed` | Operator must verify — Dashboard → Conversational AI → Phone Numbers → Add |
| Phone number resource ID noted | `[ ] id: ___________` | Not a secret; used as `agent_phone_number_id` in API calls |
| Phone number resource ID added to Agent model | `[x] code-verified` | Stored as `Agent.elevenlabs_phone_number_id` in DB. Code guard: `dial_outbound_call()` rejects if missing. |
| SIP trunk credentials registered in ElevenLabs | `[ ] confirmed` | Operator must verify — ElevenLabs must know your Telnyx SIP connection credentials |

### 2.3 SIP Trunk Pairing (Telnyx → ElevenLabs)

Follow these steps to pair the Telnyx SIP connection with ElevenLabs:

1. In ElevenLabs dashboard, navigate to **Conversational AI → Phone Numbers**.
2. Select **Add Phone Number → SIP Trunk**.
3. Enter the Telnyx SIP connection credentials:
   - **SIP server hostname**: Telnyx SIP domain (check your connection settings in Telnyx portal)
   - **Username / Password**: The digest auth credentials you created in step 1.3
4. Confirm the phone number displays as "Active" in ElevenLabs.
5. Record the ElevenLabs Phone Number ID (not a secret) for use in C2 API calls.

> **Tip**: ElevenLabs will attempt a SIP REGISTER or OPTIONS probe when you save the pairing.
> If it fails, double-check the Telnyx SIP hostname format and that your connection allows
> inbound SIP (from ElevenLabs) as well as outbound.

---

## 3. Local Environment Validation

### 3.1 .env File Contents

Your local `.env` should contain the following keys before proceeding.
Record only key names here — values are private.

```
# Telnyx (portal management only — Qora backend does not read these)
TELNYX_API_KEY=<your-telnyx-api-key>
TELNYX_SIP_USERNAME=<your-sip-username>
TELNYX_SIP_PASSWORD=<your-sip-password>
TELNYX_CALLER_ID=<your-verified-number-e164>

# ElevenLabs (code-verified — config.py reads these)
ELEVENLABS_API_KEY=<already-set>              # CRITICAL — startup aborts if missing
ELEVENLABS_AGENT_ID=<agent-id>                # Default set in config.py

# Outbound calls (code-verified — config.py reads these)
ENABLE_OUTBOUND_CALLS=true                    # Feature flag — gates all telephony
QORA_WEBHOOK_AUTH_ENABLED=true                # Required when outbound is enabled
QORA_WEBHOOK_SECRET=<strong-random-secret>    # HMAC validation for webhooks

# Test targets (never commit)
ARGENTINA_TEST_NUMBER=<ar-mobile-number-e164>
US_CONTROL_NUMBER=<us-number-e164>            # optional
```

> **Note**: `ELEVENLABS_PHONE_NUMBER_ID` is stored on the `Agent` model in the
> database, not as an env var. Set it via the Agent API or admin panel.

> **Security check**: Run `git diff --stat` and `git status` before any commit.
> If any of these keys or their values appear in tracked files, remove them immediately.

### 3.2 Gitignore Verification

| Check | Status |
|-------|--------|
| `.env` is listed in `.gitignore` | `[ ] confirmed` |
| `git status` shows `.env` as untracked/ignored | `[ ] confirmed` |
| No credential values visible in `git diff` | `[ ] confirmed` |

### 3.3 Webhook Reachability

| Check | Status | Notes |
|-------|--------|-------|
| ngrok (or equivalent) tunnel running and pointing to backend | `[ ] confirmed` | Required for ElevenLabs to reach Custom LLM webhook |
| Tunnel URL updated in ElevenLabs agent config | `[ ] confirmed` | Must match `ELEVENLABS_AGENT_ID`'s webhook URL |
| Backend starts without errors | `[ ] confirmed` | `cd backend && uvicorn app.main:app --reload` |
| Existing browser demo works | `[ ] confirmed` | Confirms pipeline is intact before adding telephony |

---

## 4. Prerequisite Status Summary

Fill in this table before beginning measurement:

| # | Prerequisite | Status | Verification |
|---|--------------|--------|--------------|
| 1 | Telnyx account active with credit | `[ ]` | Operator — portal.telnyx.com |
| 2 | Telnyx API key obtained | `[ ]` | Operator — Qora does not read this var |
| 3 | Telnyx SIP connection created (auth method chosen) | `[ ]` | Operator — portal config |
| 4 | Telnyx outbound voice profile configured for Argentina | `[ ]` | Operator — portal config |
| 5 | Caller ID / phone number verified | `[ ]` | Operator — portal config |
| 6 | Argentina test destination number available | `[ ]` | Operator — real number required |
| 7 | ElevenLabs SIP trunk + phone number resource created | `[ ]` | Operator — EL dashboard |
| 8 | Telnyx SIP connection paired with ElevenLabs phone number | `[ ]` | Operator — EL dashboard |
| 9 | `ELEVENLABS_API_KEY` in `.env` and startup passes | `[x]` | Code — config.py startup validation |
| 10 | `ENABLE_OUTBOUND_CALLS=true` + webhook auth configured | `[x]` | Code — config.py fail-closed validator |
| 11 | Phone number ID set on Agent model | `[x]` | Code — `dial_outbound_call()` guard |
| 12 | ngrok tunnel running; browser demo confirmed working | `[ ]` | Operator — manual verification |

**Proceed to live testing when all operator items are confirmed and backend starts without errors.**

---

## 4.1 Voicemail Detection (CRITICAL — Production Cost Protection)

Without voicemail detection, the agent talks to answering machines for 3-5+ minutes per unanswered call, incurring full billing. Three layers are configured:

### Layer 1: ElevenLabs `voicemail_detection` Built-In Tool (Primary)

| Step | Action | Status |
|------|--------|--------|
| 1 | Set `Agent.voicemail_detection_enabled=True` in Qora DB | `[x] code-verified` |
| 2 | Run `sync_agent_config()` or trigger agent sync endpoint | `[x] code-verified` |
| 3 | Test with a number known to go to voicemail — verify call ends within seconds | `[ ] operator must verify` |

> **API-managed (PR #138)**: Layer 1 is now configured via Qora's backend
> (`ElevenLabsService.sync_agent_config()`), NOT via the ElevenLabs dashboard.
> The correct API path is `conversation_config.agent.prompt.built_in_tools.voicemail_detection`.
> Setting `voicemail_detection_enabled=True` sends `{"system_tool_type": "voicemail_detection"}`.
> Setting it to `False` sends `null` (explicitly disables). `NULL` skips the field in the PATCH.

### Layer 2: System Prompt Instruction (Fallback)

The agent's system-prompt includes a `<voicemail_detection>` section instructing it to hang up immediately upon detecting a recorded message, beep, or operator announcement. **Status: `[x]` — already deployed in code.**

### Layer 3: Max Call Duration (Safety Net)

| Step | Action | Status |
|------|--------|--------|
| 1 | Set `Agent.max_call_duration_seconds=120` in Qora DB | `[x] code-verified` |
| 2 | Run `sync_agent_config()` or trigger agent sync endpoint | `[x] code-verified` |
| 3 | Verify with a test call that exceeds 2 min → call should auto-terminate | `[ ] operator must verify` |

> **API-managed (PR #138)**: Layer 3 is now configured via Qora's backend.
> The correct API path is `conversation_config.conversation.max_duration_seconds`.
>
> **Why 120s?** A typical lead qualification call runs 60-90s. If the agent hasn't completed or detected voicemail by 120s, something is wrong. The cost of a false positive (cutting a real call at 2 min) is much lower than the cost of a 5-min voicemail conversation.

---

## 5. What You Will Need from Telnyx (Summary for Planning)

You do not need to configure all of this now, but budget time for these steps when you begin:

| Task | Estimated time | Where |
|------|---------------|-------|
| Create Telnyx account + verify email | 10 min | portal.telnyx.com |
| Add billing credit | 5 min | Billing → Add credit |
| Create API key | 5 min | API Keys |
| Create SIP connection | 15 min | Connections → SIP |
| Configure outbound voice profile | 10 min | Numbers → Outbound Profiles |
| Purchase/verify phone number | 10 min | Numbers → Buy Numbers |
| Pair SIP connection in ElevenLabs | 15 min | ElevenLabs → Phone Numbers |
| **Total** | **~70 min** | |

> This estimate assumes no account approval delays. Telnyx account approval is usually instant
> for credit card signups. Argentina-capable numbers are available on Telnyx US inventory.

---

## What's Next

This checklist is a setup companion. Once all items are confirmed:
1. Proceed to the next incomplete Phase in `docs/ROADMAP.md`
2. This file will be archived — the permanent telephony reference is `docs/telephony-integration.md`
