# Running QORA Locally

Step-by-step guide to get QORA running on your machine and exposed to ElevenLabs.

**You will**: clone the repo → configure API keys → start the dev server → expose it via ngrok → connect it to your ElevenLabs agent → run the demo. Total setup time: ~10 minutes assuming you already have API keys.

## Prerequisites

- Python 3.11 or higher
- [ngrok](https://ngrok.com/) (free account is enough)
- OpenAI API key
- ElevenLabs API key + a configured Conversational AI agent

---

## 1. Clone and Install

```bash
git clone <repo-url>
cd Qora

# Create virtual environment inside the backend folder
python -m venv backend/.venv
source backend/.venv/bin/activate   # Windows: backend\.venv\Scripts\activate

# Install dependencies
pip install -e "backend/.[dev]"
```

---

## 2. Configure API Keys

```bash
# Run from the repo root — that is where .env.example lives
cp .env.example .env
```

Edit `.env` (at the repo root) and fill in:

### Core variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | ✅ | Your OpenAI API key (GPT-4o) |
| `ELEVENLABS_API_KEY` | ✅ | Your ElevenLabs API key |
| `ELEVENLABS_AGENT_ID` | ✅ | The ID of your ElevenLabs Conversational AI agent |
| `DATABASE_URL` | Optional | Default: `sqlite+aiosqlite:///./qora.db` |
| `LOG_LEVEL` | Optional | Default: `INFO` |

### Auth variables (Phase B5)

| Variable | Required | Description |
|----------|----------|-------------|
| `QORA_API_KEY` | ✅ (all environments) | Admin Bearer token — protects all admin routes. Local dev can use any non-placeholder value (e.g. `dev-key`). Generate a strong key for staging/production: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `QORA_DOCS_ENABLED` | Optional | Toggle `/docs` and `/redoc`. Default: `true`. Set `false` in production. |
| `QORA_DEMO_CLIENT_ID` | Required for demo | `client_id` of the demo tenant in your DB (e.g. `qora-demo`). Enables `/api/v1/demo/*` endpoints. |
| `QORA_DEMO_AGENT_ID` | Required for demo | Agent UUID for the demo tenant. |
| `QORA_SESSION_TTL_SECONDS` | Optional | In-memory session TTL in seconds. Default: `14400` (4 hours). |
| `QORA_WEBHOOK_SECRET` | Required if webhook auth enabled | Shared secret for `X-Webhook-Secret` header validation. Must match ElevenLabs agent setting. |
| `QORA_WEBHOOK_AUTH_ENABLED` | Optional | Enable ElevenLabs webhook authentication. Default: `false`. When `true`, `QORA_WEBHOOK_SECRET` must be set or startup fails. |
| `QORA_ALLOWED_ORIGINS` | Optional | Comma-separated CORS origin allow-list. Default: `*` (open — dev only). Example: `https://app.example.com,https://admin.example.com` |

Edit `frontend/.env` (copy from `frontend/.env.example`):

| Variable | Description |
|----------|-------------|
| `VITE_API_KEY` | Must match `QORA_API_KEY`. Sent by the React admin UI as a `Bearer` token. **Browser-visible — acceptable only for current Phase B static admin auth.** Will be replaced by JWT in Phase C. |
| `VITE_API_BASE_URL` | Leave empty for Vite proxy (same-origin). |

> **Do NOT create `backend/.env`.** The backend reads from root `.env` only (B8). Any old `backend/.env` is ignored — delete it if it exists.

Run the pre-flight check to validate all REQUIRED secrets before starting:

```bash
python backend/scripts/check-secrets.py
```

**Never commit your `.env` files.** Both root `.env` and `frontend/.env` are already in `.gitignore`.

---

## 3. Initialize the Database

Run Alembic migrations before starting the server. The application no longer
auto-creates the schema on startup — `python scripts/migrate.py` must run first.

```bash
cd backend
python scripts/migrate.py
```

This is idempotent: safe to run on a fresh DB (creates schema) or an existing one
(stamps or applies pending migrations). The `Qora` launcher (step 4) does this
automatically for you.

To also seed demo data after migrating:

```bash
python -c "
import asyncio
from app.core.config import Settings
from app.core import database as db
from app.tenants.service import seed_quintana
from app.leads.service import seed_leads

async def main():
    s = Settings()
    await db.init_db(s)
    async with db.async_session_factory() as sess:
        await seed_quintana(sess)
        await seed_leads(sess)
        await sess.commit()
    await db.close_db()
    print('DB seeded')

asyncio.run(main())
"
```

> **Important**: the seed snippet above requires migrations to have already run
> (`python scripts/migrate.py`). It does not create schema itself.

---

## 4. Run the Dev Server

From the repository root, you can start the backend, ngrok tunnel, and frontend together:

```bash
./Qora
```

This keeps all local processes attached to the same terminal. Press `Ctrl+C` to stop everything.
The `Qora` launcher automatically runs `python scripts/migrate.py` before starting uvicorn.

If you only want the backend, **always run migrations first**:

```bash
cd backend
python scripts/migrate.py && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Starting uvicorn directly without migrations on a fresh database will fail —
the schema does not exist yet.

Verify it's running:

```bash
curl http://localhost:8000/api/v1/health
```

Expected: `{"status": "healthy", "uptime_seconds": ..., "version": "0.1.0"}`

The demo UI is available at: **http://localhost:8000/demo/**

---

## 5. Expose via ngrok

ElevenLabs needs a public HTTPS URL to reach your webhook. The `Qora` launcher starts ngrok automatically:

```bash
Qora
```

ngrok will print something like:

```
Forwarding  https://abc123.ngrok-free.app -> http://localhost:8000
```

Copy the HTTPS forwarding URL from the ngrok logs — you'll need it in step 6.

If you only need ngrok manually, run:

```bash
ngrok http 8000
```

> **Tip:** Use `ngrok http 8000 --domain your-static-domain.ngrok-free.app` if you have a free static ngrok domain — this way the URL never changes between restarts.

---

## 6. Configure the ElevenLabs Agent

In the [ElevenLabs dashboard](https://elevenlabs.io/app/conversational-ai):

1. Open your agent → **Voice** tab → **Custom LLM**
2. Set **Custom LLM URL** to:
   ```
   https://abc123.ngrok-free.app/api/v1/voice
   ```
   ElevenLabs will append `/chat/completions` automatically.

3. Set **Custom LLM Extra Body** (JSON):
   ```json
   {
     "client_id": "quintana-seguros"
   }
   ```
   This tells QORA which tenant config to load.

4. Save the agent.

---

## 7. Run the Demo

1. Open **http://localhost:8000/demo/** in your browser
2. The **ElevenLabs Agent ID** field is pre-filled — verify it matches your agent
3. Select a **Lead** from the dropdown
4. Click **🎙️ Iniciar Conversación**
5. Allow microphone access when prompted
6. Talk to Jaumpablo!

---

## 8. Run Tests (optional)

```bash
# All tests
pytest tests/ -q

# With coverage
pytest tests/ --cov=app --cov-report=term-missing

# Specific module
pytest tests/unit/prompts/ -v
pytest tests/integration/voice/ -v
```

---

## 9. Admin API — curl Examples

All admin routes require the `Authorization: Bearer` header. Replace `<YOUR_KEY>` with the value of `QORA_API_KEY` in your `.env`.

```bash
# Health check (public — no auth)
curl http://localhost:8000/api/v1/health

# List clients (requires auth)
curl -H "Authorization: Bearer <YOUR_KEY>" http://localhost:8000/api/v1/clients

# Create a client
curl -X POST http://localhost:8000/api/v1/clients \
  -H "Authorization: Bearer <YOUR_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"name": "Acme Corp"}'

# List leads for a client
curl -H "Authorization: Bearer <YOUR_KEY>" \
  "http://localhost:8000/api/v1/leads?client_id=acme-corp"

# List call sessions
curl -H "Authorization: Bearer <YOUR_KEY>" \
  "http://localhost:8000/api/v1/calls?client_id=acme-corp"

# Demo context (public — no auth needed)
curl http://localhost:8000/api/v1/demo/context
```

**401 response** when key is wrong or missing:
```json
{ "error": "authentication_required", "message": "Authorization header missing" }
```

---

## 10. Post-Call Analysis

QORA's post-call analysis pipeline is fully Python-native. When a call ends, the
summarizer (`backend/app/summarizer.py`) fans out 13 analysis dimensions in parallel
via `asyncio.gather`. Each dimension under `backend/app/analysis/universal/` owns its
own prompt, schema, and OpenAI call.

See [`docs/analysis-pipeline.md`](analysis-pipeline.md) for full documentation on the
analysis pipeline and all 13 dimensions.

---

## 11. Troubleshooting

### `422 Unprocessable Entity` from webhook

The `client_id` is missing from the ElevenLabs request. Verify the **Custom LLM Extra Body** in the ElevenLabs dashboard includes `"client_id": "quintana-seguros"`.

### `404 client not found`

The `client_id` sent by ElevenLabs doesn't match any row in the `clients` table. Re-run the seed script (step 3) or check the DB:

```bash
sqlite3 qora.db "SELECT id FROM clients;"
```

### WebSocket 1006 disconnect

ngrok disconnected or the server crashed. Check:
1. `ngrok` is still running — restart if needed
2. The server is still running at port 8000
3. Click **🔄 Reconectar** in the demo UI

### `ELEVENLABS_AGENT_ID not configured`

Add `ELEVENLABS_AGENT_ID=agent_xxxxxxxxxxxxxxxx` to your `.env` file.

### Import errors on startup

Make sure you installed with `pip install -e ".[dev]"` and that your virtualenv is active.
