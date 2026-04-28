# n8n-MCP Integration Setup

This document covers how to configure n8n for the Qora post-call analysis pipeline and
how to use the **n8n-MCP plugin** so AI agents can inspect and manage n8n workflows
programmatically.

---

## What is n8n-MCP?

[**n8n-mcp**](https://github.com/czlonkowski/n8n-mcp) is an open-source MCP (Model Context
Protocol) server that bridges AI assistants ↔ a live n8n instance.

| Feature | Description |
|---------|-------------|
| **Stars** | ~18.9k on GitHub |
| **License** | MIT |
| **Compatible clients** | Claude Desktop, Claude Code, Cursor, Windsurf, VS Code Copilot |
| **Minimum n8n** | v2.16.1+ |

### Core Tools Provided

| Category | Tools |
|----------|-------|
| **Discovery** | `search_nodes`, `get_node`, `validate_node`, `validate_workflow`, `search_templates`, `get_template`, `tools_documentation` |
| **Management** | `list_workflows`, `get_workflow`, `create_workflow`, `update_workflow`, `delete_workflow`, `execute_workflow`, `list_credentials`, `create_credential`, `delete_credential`, `audit_workflows`, `health_check` |

With these tools, an AI agent can:

- Inspect existing Qora n8n workflows without leaving the IDE.
- Validate a workflow JSON before importing it into n8n.
- Trigger a test execution and inspect the result.
- Search node documentation to troubleshoot a broken step.

---

## n8n Architecture in Qora

Qora uses n8n as an **external orchestrator** for the post-call analysis pipeline.
The integration is a **dual-write bridge** (Phase 1 of migration) — the local
Python summarizer still runs in parallel; n8n results are compared and logged.

```
Backend (call ends)                    n8n instance
───────────────────                    ─────────────
close_session()
  └─ _schedule_summarize(session_id)
       ├─ asyncio.create_task(local)   ← always runs (safety net)
       └─ HTTP POST N8N_WEBHOOK_URL    ← fires when N8N_ENABLED=true
            payload: {session_id, client_id}
                                              ↓
                                        Webhook Trigger Node
                                              ↓
                               GET /api/v1/internal/transcript/{session_id}
                                              ↓
                               GET /api/v1/internal/extraction-config/{client_id}
                                              ↓
                                        OpenAI Node (GPT-4o-mini)
                                        maxTries=3, continueOnFail=true
                                              ↓ (success)
                               POST /api/v1/internal/analysis-result
                               {session_id, summary, facts}
                                              ↓ (all retries exhausted)
                                        Log GPT Failure (noOp node)
```

The workflow JSON is exported to `docs/n8n-workflows/post-call-analysis.json` and
can be imported directly into any n8n instance.

---

## Required Environment Variables

### Backend (`.env`)

These variables control Qora's outbound webhook trigger and inbound internal API.

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `N8N_ENABLED` | No | `false` | Feature flag. Set `true` to activate the n8n trigger path. When `false`, zero behavior change — only the local summarizer runs. |
| `N8N_WEBHOOK_URL` | When enabled | `""` | Full URL to the n8n webhook trigger endpoint. Example: `https://n8n.example.com/webhook/post-call-analysis` |
| `N8N_WEBHOOK_SECRET` | When enabled | `""` | Shared HMAC secret. Qora signs every outbound webhook POST with an `X-Webhook-Signature` header so n8n can verify the request origin. |
| `N8N_INTERNAL_API_KEY` | When enabled | `""` | Static API key n8n uses when calling back into Qora's internal API. Sent as the `X-Internal-Secret` header on all n8n → backend requests. |
| `N8N_TIMEOUT_SECONDS` | No | `5` | HTTP timeout (seconds) for the outbound webhook POST. n8n failure is non-blocking — local path always runs. |

### n8n (Credentials in n8n UI)

| Variable | Where set | Description |
|----------|-----------|-------------|
| `QORA_INTERNAL_SECRET` | n8n Credential → Generic Auth / Header Auth | Value of `N8N_INTERNAL_API_KEY` from backend. Added as `X-Internal-Secret` header on all HTTP Request nodes that call back to the Qora backend. |
| `OPENAI_API_KEY` | n8n Credential → OpenAI | Standard OpenAI API key. Used by the OpenAI node in the post-call-analysis workflow. |

### n8n-MCP (AI agent configuration)

| Variable | Description |
|----------|-------------|
| `N8N_API_URL` | n8n instance base URL. Example: `https://n8n.example.com` |
| `N8N_API_KEY` | n8n personal API key (generated in n8n → Settings → API). Grants the MCP server access to read/write workflows. |

---

## Installing n8n-MCP

### Option A — npx (recommended for development)

```bash
# Add to your MCP client config (Claude Desktop / Claude Code)
npx n8n-mcp
```

Configuration for Claude Code (`.claude/mcp.json` or `~/.claude/mcp.json`):

```json
{
  "mcpServers": {
    "n8n": {
      "command": "npx",
      "args": ["-y", "n8n-mcp"],
      "env": {
        "N8N_API_URL": "https://n8n.example.com",
        "N8N_API_KEY": "your-n8n-api-key"
      }
    }
  }
}
```

### Option B — Docker

```bash
docker run -e N8N_API_URL=https://n8n.example.com \
           -e N8N_API_KEY=your-api-key \
           ghcr.io/czlonkowski/n8n-mcp:latest
```

### Option C — Hosted service

Visit [context7.com/czlonkowski/n8n-mcp](https://github.com/czlonkowski/n8n-mcp) for
the hosted option — no local installation required.

---

## Importing the Qora Workflow

1. Open your n8n instance → **Workflows** → **Import from file**.
2. Select `docs/n8n-workflows/post-call-analysis.json`.
3. In n8n, update the two HTTP Request credential references to point to your
   `QORA_INTERNAL_SECRET` credential.
4. Update the OpenAI node credential to your OpenAI API key.
5. Activate the workflow — the webhook URL shown in the Webhook Trigger node is
   your `N8N_WEBHOOK_URL` backend env var value.

---

## Available MCP Tools for Agents

Once n8n-MCP is configured, agents working on Qora can use:

| Tool | Purpose |
|------|---------|
| `get_workflow` | Read the current state of the post-call-analysis workflow |
| `validate_workflow` | Validate the exported JSON before importing |
| `execute_workflow` | Trigger a test run (requires a real session_id) |
| `search_nodes` | Find node types when building new workflow steps |
| `get_node` | Get full docs for a specific node (e.g. the OpenAI node) |
| `health_check` | Verify n8n instance is reachable and the API key is valid |
| `audit_workflows` | Check for misconfigured credentials or exposed secrets |

---

## Verifying the Integration

After setting `N8N_ENABLED=true` and deploying both backend and n8n:

1. **Trigger a call session** and end it — watch backend logs for:
   ```
   n8n_trigger_sent session_id=<id> status_code=200
   ```
2. **In n8n UI**, open the post-call-analysis workflow → **Executions** — you should
   see a new execution row with each step's input/output visible.
3. **Verify dual-write agreement** — backend logs emit:
   ```
   n8n_verification_comparison session_id=<id> agreed=true|false|null
   ```
   `agreed=None` means n8n callback arrived before local result; `agreed=True` means
   both results match; `agreed=False` means divergence (review manually).

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| Backend logs `n8n_trigger_background_failed` | n8n unreachable or `N8N_WEBHOOK_URL` wrong | Verify URL, check n8n is running |
| n8n execution shows 401 on callback | Wrong `QORA_INTERNAL_SECRET` in n8n credential | Match value to `N8N_INTERNAL_API_KEY` in backend `.env` |
| n8n execution shows 404 on transcript | Workflow fired before session was committed | Add a short delay node or check session flush order |
| `agreed=false` in comparison logs | GPT non-determinism or extraction config drift | Review both payloads in logs; increase verification window |
| MCP tool `health_check` fails | `N8N_API_KEY` invalid or `N8N_API_URL` wrong | Regenerate key in n8n → Settings → API |

---

## Security Notes

- **Never commit** `N8N_WEBHOOK_SECRET`, `N8N_INTERNAL_API_KEY`, or `N8N_API_KEY` to git.
- The `/api/v1/internal/*` endpoints require `X-Internal-Secret` on every request — they
  are not intended to be exposed publicly. Consider restricting them to an internal
  network or VPN.
- HMAC signature verification (`X-Webhook-Signature`) on inbound webhook triggers is
  recommended for production — see `backend/app/n8n/client.py` for the signing logic.

---

## References

- [n8n-mcp GitHub](https://github.com/czlonkowski/n8n-mcp)
- [n8n documentation](https://docs.n8n.io)
- [Qora n8n workflow JSON](./n8n-workflows/post-call-analysis.json)
- [Qora n8n architecture exploration](./../.sdd/qora-n8n-orchestration/exploration.md)
- [Backend n8n settings](../backend/app/core/config.py) — `Settings` class, n8n fields
- [Backend n8n client](../backend/app/n8n/client.py) — HMAC signing, HTTP trigger
- [Backend internal router](../backend/app/n8n/router.py) — callback endpoints
