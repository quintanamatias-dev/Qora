# Running QORA Locally

Step-by-step guide to get QORA running on your machine and exposed to ElevenLabs.

## Prerequisites

- Python 3.11 or higher
- [ngrok](https://ngrok.com/) (free account is enough)
- OpenAI API key
- ElevenLabs API key + a configured Conversational AI agent

---

## 1. Clone and Install

```bash
git clone <repo-url>
cd V1-CallCenter/backend

# Create virtual environment
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"
```

---

## 2. Configure API Keys

```bash
cp .env.example .env
```

Edit `.env` and fill in:

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | ✅ | Your OpenAI API key (GPT-4o) |
| `ELEVENLABS_API_KEY` | ✅ | Your ElevenLabs API key |
| `ELEVENLABS_AGENT_ID` | ✅ | The ID of your ElevenLabs Conversational AI agent |
| `DATABASE_URL` | Optional | Default: `sqlite+aiosqlite:///./qora.db` |
| `LOG_LEVEL` | Optional | Default: `INFO` |

**Never commit your `.env` file.** It's already in `.gitignore`.

---

## 3. Initialize the Database

On first run, QORA initializes the database automatically. You can also seed it manually:

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

---

## 4. Run the Dev Server

From the repository root, you can start the backend, ngrok tunnel, and frontend together:

```bash
./Qora
```

This keeps all local processes attached to the same terminal. Press `Ctrl+C` to stop everything.

If you only want the backend, run it manually from `backend/`:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Verify it's running:

```bash
curl http://localhost:8000/api/v1/health
```

Expected: `{"status": "ok", ...}`

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

## 8. Run Tests

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

## 9. n8n (modeling reference only)

QORA's post-call analysis pipeline is fully Python-native. Each dimension under
`backend/app/analysis/universal/` owns its own prompt, schema, and OpenAI call;
the summarizer runs all 13 in parallel via `asyncio.gather`.

The files below are kept only as diagramming / modeling references — they are
NOT part of the runtime path:

- `docs/n8n-workflows/post-call-analysis.json`
- `docker-compose.n8n-local.yml`

If you want to inspect the workflow visually, you can still spin up the local
n8n container with `docker compose -f docker-compose.n8n-local.yml up -d` and
import the JSON, but the backend will neither call it nor receive callbacks
from it.

---

## Troubleshooting

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
