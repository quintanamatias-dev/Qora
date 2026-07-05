# Qora — Pricing (Internal Analysis + Plan Structure)

> **What this document is.** Internal pricing reference for Qora. Contains cost breakdown, competitive analysis, and the proposed plan structure. Numbers sourced from public pricing pages and observed CDR data as of June–July 2026. This is NOT a customer-facing document.
>
> ⚠️ **Pricing varies by route and scenario.** Inbound and landline calls remain cheap. Outbound to Argentine mobile is significantly more expensive than originally assumed — see Section 1 and the telephony table in Section 2 for observed rates. Always record provider CDR data per call to track actual costs.

---

## 1. Cost Structure (per minute, at cost)

Qora's cost per minute depends on call direction. Two representative scenarios:

**Scenario A — Inbound (client calls Qora agent)**

| Layer | What it is | Cost/min |
|-------|-----------|----------|
| ElevenLabs Agents | Voice engine (STT + TTS + orchestration) | $0.080 |
| LLM (GPT-4o) | Agent reasoning | ~$0.015 |
| Telephony (Telnyx, inbound) | PSTN inbound to Argentina number | ~$0.007 |
| **Total** | | **~$0.102** |

**Scenario B — Outbound to Argentine mobile (agent calls a mobile number)**

| Layer | What it is | Cost/min |
|-------|-----------|----------|
| ElevenLabs Agents | Voice engine (STT + TTS + orchestration) | $0.080 |
| LLM (GPT-4o) | Agent reasoning | ~$0.015 |
| Telephony (Telnyx, outbound mobile) | Observed CDR rate: ~$0.126/min | ~$0.126 |
| **Total** | | **~$0.221** |

> **CDR evidence (July 2026):** A real Telnyx call to an Argentine mobile was billed at $0.7572 for 360 seconds (6 min), giving an effective rate of **$0.1262/min**. This is ~2.5x higher than the ~$0.04–0.06/min previously assumed from list prices. Route selection and False Answer Supervision (FAS) can increase billed time — always record CDR data per call.

### Key observations

- ElevenLabs is the dominant cost in the inbound scenario (~78%). For outbound mobile, telephony becomes comparable to ElevenLabs.
- ElevenLabs charges a flat $0.08/min across ALL plans (Starter through Business). Volume does not reduce per-minute cost until custom Enterprise negotiation.
- **Inbound and landline outbound remain cheap.** Outbound to Argentine mobile is the expensive scenario — observed at ~$0.126/min on Telnyx vs. $0.3528/min on Twilio (official July 2026 rate). Telnyx is still cheaper, but not as cheap as list prices implied.

---

## 2. Cost Scaling by Volume

### ElevenLabs Agents plans

| Plan | Price/mo | Minutes included | Effective $/min | Concurrent calls |
|------|---------|-----------------|-----------------|-----------------|
| Starter | $6 | 75 | $0.080 | 6 |
| Creator | $22 | 275 | $0.080 | 10 |
| Pro | $99 | 1,238 | $0.080 | 20 |
| Scale | $299 | 3,738 | $0.080 | 30 |
| Business | $990 | 12,375 | $0.080 | 40 |
| Enterprise | Custom | Custom | Negotiable (~$0.05–0.06?) | Custom |

**Conclusion**: The per-minute cost is fixed at $0.08 until Enterprise. Higher plans only buy more included minutes and concurrency.

### Telephony (Telnyx — Argentina)

| Item | Cost |
|------|------|
| Local number (Buenos Aires) | ~$1/mo (drops to $0.25/mo at 50+ numbers) |
| Inbound call | ~$0.005/min + $0.002 SIP fee = ~$0.007/min |
| Outbound to landline | ~$0.008/min + $0.002 SIP fee = ~$0.010/min |
| Outbound to mobile | ~$0.04–0.06/min list; **~$0.126/min observed (CDR, July 2026)** |

> ⚠️ **Outbound mobile rate warning:** List prices suggest $0.04–0.06/min for Argentine mobile. A real CDR showed $0.1262/min effective rate (360 s billed, $0.7572 total). Use the observed rate for cost modelling until a more favorable route is confirmed. Additionally, False Answer Supervision (FAS) — where the carrier bills a call as answered before a human picks up — can create billable minutes with zero conversation value. Record CDR data per call to detect anomalies.

Twilio is 2.8x more expensive for outbound mobile (official rate July 2026). Telnyx remains the better choice even at the observed rate.

| Scenario | Telnyx total/min | Twilio total/min | Source |
|----------|-----------------|-----------------|--------|
| Inbound (client calls agent) | ~$0.007 | ~$0.015 | List price |
| Outbound to landline | ~$0.010 | ~$0.064 | List price |
| Outbound to mobile | **~$0.126** (observed) | ~$0.353 (official) | CDR / Twilio pricing page |

### LLM cost

OpenAI does not offer real-time volume discounts. Per-token pricing is flat. GPT-4o-mini is 10x cheaper than GPT-4o but quality may be insufficient for complex conversations.

| Model | Estimated $/min of conversation |
|-------|-------------------------------|
| GPT-4o | ~$0.015 |
| GPT-4o-mini | ~$0.001 |
| GPT-4.1 | ~$0.015 |

### Projected cost at scale

Costs shown for two scenarios: **Inbound** (cheapest) and **Outbound mobile Argentina** (most expensive based on observed data).

| Monthly volume | ElevenLabs plan | ElevenLabs $/min | LLM | Telephony (inbound) | **Total — Inbound** | Telephony (outbound mobile, observed) | **Total — Outbound Mobile** |
|---------------|----------------|-----------------|-----|---------------------|---------------------|---------------------------------------|----------------------------|
| 75 min | Starter ($6) | $0.080 | $0.015 | $0.007 | **$0.102** | $0.126 | **$0.221** |
| 1,238 min | Pro ($99) | $0.080 | $0.015 | $0.007 | **$0.102** | $0.126 | **$0.221** |
| 3,738 min | Scale ($299) | $0.080 | $0.015 | $0.007 | **$0.102** | $0.126 | **$0.221** |
| 12,375 min | Business ($990) | $0.080 | $0.015 | $0.007 | **$0.102** | $0.126 | **$0.221** |
| 50,000+ min | Enterprise | ~$0.055 | $0.015 | $0.005 | **~$0.075** | ~$0.110 | **~$0.180** |

**Bottom line**: Inbound cost is flat at ~$0.10/min until Enterprise. Outbound mobile is ~$0.22/min at current observed Telnyx rates — plan margins accordingly for outbound-heavy use cases.

---

## 3. Competitive Landscape

### Platform pricing (developer-facing)

These are platforms where developers build their own voice agents. Prices are what the developer pays.

| Platform | Model | Advertised rate | Typical all-in cost/min | Notes |
|----------|-------|----------------|------------------------|-------|
| **Bland AI** | All-inclusive | $0.14 (Start) → $0.11 (Scale) | $0.11–$0.14 | Everything included. Platform fee $0–$499/mo. |
| **Synthflow** | Components | Voice $0.09 + LLM + Telco | $0.15–$0.24 | Add-ons for low latency (+$0.04), performance routing (+$0.04). |
| **Vapi** | Platform + providers | $0.05 platform fee | $0.13–$0.30 | You pay STT/LLM/TTS/Telco separately at cost. |
| **Retell AI** | Components | Infra $0.055 + components | $0.11–$0.31 | Transparent component pricing. ElevenLabs TTS is $0.04/min vs $0.015 for others. |
| **ElevenLabs Agents** | Hosted | $0.08/min + LLM + Telco | $0.10–$0.12 | What Qora uses today. |

### Solution pricing (business-facing)

These are the price ranges businesses pay for a ready-to-use AI voice agent, not a platform.

| Segment | Typical price/min |
|---------|------------------|
| DIY Platform (Vapi, Retell, Bland) | $0.10–$0.25 |
| Managed solution (configured + supported) | $0.25–$0.50 |
| Agency-built (custom development) | $0.30–$1.00 + setup fee |
| Human call center (Argentina) | $0.80–$2.00 |

**Qora's position**: Managed solution. The client gets a working agent, not a toolkit.

---

## 4. Qora Pricing (Proposed)

### Plan structure

| | **Starter** | **Pro** | **Business** |
|---|---|---|---|
| Target | Small business, pilot | Serious SMB | Company with volume |
| Minutes included | 200 | 1,000 | 5,000 |
| Monthly price | $49 | $199 | $799 |
| Effective client $/min | $0.245 | $0.199 | $0.160 |
| Our cost/min (inbound) | $0.102 | $0.102 | $0.102 |
| Our cost/min (outbound mobile) | ~$0.221 | ~$0.221 | ~$0.221 |
| **Gross margin (inbound)** | **58%** | **49%** | **36%** |
| **Gross margin (outbound mobile)** | **10%** | **10%** | **27%** |
| Overage per minute | $0.30 | $0.25 | $0.20 |
| Agents included | 1 | 3 | 10 |
| Phone numbers included | 1 | 2 | 5 |
| Post-call analysis | Basic | Full | Full + custom |
| CRM integration | Webhook | Webhook + Airtable | Custom |
| Support | Email | Email + priority | Dedicated |

### Margin guardrails

- **Never below 30%** gross margin per minute. Below that, support and infrastructure costs eat the profit.
- ⚠️ **Outbound mobile Argentina breaks the 30% floor on Starter and Pro** at current observed Telnyx rates (~$0.221/min cost vs. $0.245–$0.199 effective client price). This must be resolved before selling outbound-heavy plans — either via route optimization, an outbound surcharge, or adjusted plan pricing. See Section 6.
- **Overage minutes** are the highest margin item (~65–70%) on inbound. For outbound mobile, overage at $0.25–$0.30/min may run near-zero or negative margin.
- **Phone numbers** cost us ~$1/mo each (Telnyx). Charging them as "included" is negligible cost, high perceived value.

---

## 5. Competitive Comparison

| Capability | **Qora** | Bland AI | Synthflow | Vapi | Retell AI |
|-----------|---------|---------|-----------|------|-----------|
| **Type** | Managed solution | Platform | Platform | Platform | Platform |
| **Price/min (client pays)** | $0.16–$0.25 | $0.11–$0.14 | $0.15–$0.24 | $0.13–$0.30 | $0.11–$0.31 |
| **Setup required by client** | None | Build your own agent | Build your own agent | Build your own agent | Build your own agent |
| Agent design + prompt | Included | DIY | DIY | DIY | DIY |
| Voice customization | Included | DIY | DIY | DIY | DIY |
| Phone number (Argentina) | Included | BYO | BYO or +$0.02/min | BYO | +$2/mo |
| Post-call analysis | Included (auto) | Not included | Not included | Not included | +$0.10/min |
| CRM integration | Included | DIY via API | DIY via Zapier | DIY via API | DIY via API |
| Memory across calls | Included | Not available | Not available | Not available | Not available |
| Conversation scheduling | Included | Not available | Basic | Not available | Batch call only |
| Multi-agent (per client) | Included | DIY | DIY | DIY | DIY |
| Spanish LATAM optimization | Native | Generic | Generic | Generic | Generic |
| Support | Dedicated | Docs/Slack | Ticketing | Discord/Email | Community/Email |
| SOC2 / HIPAA | Roadmap | Yes (Enterprise) | Yes | Add-on $2K/mo | Yes |

### Where Qora wins

1. **Zero setup for the client**. Competitors sell Lego bricks; Qora delivers the finished house.
2. **Post-call analysis included**. Competitors either don't offer it or charge extra ($0.10/min on Retell).
3. **Cross-call memory**. No competitor offers persistent memory that lets the agent remember previous conversations with the same person.
4. **LATAM-first**. Spanish optimization, Argentine telephony, local market understanding.
5. **Cheaper than humans**. 4–10x less than a human call center in Argentina.

### Where Qora is weaker (today)

1. **Higher per-minute price** than DIY platforms. We charge $0.16–$0.25 vs $0.11–$0.14 (Bland). This is the managed-service premium.
2. **No compliance certifications yet**. SOC2/HIPAA are on the roadmap but not done.
3. **Concurrency limits** tied to ElevenLabs plan. At Scale (30 concurrent) this may bottleneck high-volume clients.
4. **Single voice infrastructure dependency**. Qora runs on ElevenLabs. If ElevenLabs has an outage, Qora has an outage.

---

## 6. Key Decisions to Make

1. **ElevenLabs lock-in**: At what volume do we negotiate Enterprise, or evaluate switching to Retell/Vapi as the voice layer to reduce the $0.08/min?
2. **Outbound to mobile pricing**: Observed Telnyx rate is ~$0.126/min (not ~$0.05/min as assumed). Outbound mobile costs ~$0.221/min all-in, which breaks the 30% margin floor on current Starter and Pro plan prices. Options: (a) outbound surcharge, (b) route optimization / alternative carrier, (c) reprice plans, (d) restrict outbound mobile to Business+ only.
3. **CDR monitoring**: Implement per-call CDR logging to catch FAS (False Answer Supervision) and route-cost anomalies before they erode margins silently.
4. **Free tier**: Do we offer a trial (e.g., 15 free minutes) to reduce friction?
5. **Annual pricing**: Offer 2 months free on annual plans to improve cash flow predictability?

---

*Last updated: July 2026 — Outbound mobile Argentina rates updated from observed CDR data ($0.1262/min Telnyx effective rate, $0.3528/min Twilio official). Previous assumption of $0.04–0.06/min for outbound mobile was too optimistic.*
