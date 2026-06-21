# Backend — FastAPI + agent pipeline

```bash
./run.sh                 # venv + deps + seed + serve on :8000
# or
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Interactive API docs: http://localhost:8000/docs

## Layout

```
app/
  main.py                 FastAPI app, WebSocket, lifespan (seed + build index), /health /metrics
  config.py               settings (env-driven, offline defaults)
  db.py  models.py         SQLAlchemy (SQLite default → Postgres via DATABASE_URL)
  schemas.py              Pydantic request/response + WS event models
  agent/
    graph.py              minimal LangGraph-compatible StateGraph
    pipeline.py           intent → retrieve → answer → actions
    intent.py             FR-003 intent detection (rule-based, <5ms)
    retrieval.py          FR-004 CRM facts + document hits (relevance-floored)
    answer.py             FR-005 grounded answer · sources · confidence
    actions.py            FR-006 next-best-actions (linked to real docs)
    summary.py            FR-007 summary + follow-up email
  knowledge/store.py      vector/TF-IDF retriever (embeddings or offline)
  integrations/
    llm.py                Anthropic/OpenAI with offline fallback
    hubspot.py            CRM read + write (mock DB ↔ real HubSpot)
  realtime/
    simulator.py          scripted Google-Meet stand-in (FR-001/002)
    engine.py             live turn loop: persist + run agent + broadcast
    manager.py            per-meeting WebSocket rooms
  seed/data.py            Northwind demo CRM + Drive docs
tests/test_agent.py       offline tests (intent, pipeline, summary)
```

## Key endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/meetings/demo` | create the seeded Northwind meeting |
| POST | `/api/meetings/{id}/start` | begin the live (simulated) call |
| POST | `/api/meetings/{id}/utterance` | feed one customer line (runs the agent) |
| GET | `/api/meetings/{id}/transcript` `/suggestions` `/intents` | live data |
| POST | `/api/meetings/{id}/end` | summary + CRM automation (FR-007) |
| GET | `/api/knowledge/search?q=` | enterprise doc retrieval |
| GET | `/api/crm/company/{id}` | CRM snapshot |
| WS | `/ws/meetings/{id}` | live event stream |
| GET | `/health` `/metrics` | status + KPI metrics |

## Turning on real integrations

Copy `.env.example` → `.env` and set any of: `ANTHROPIC_API_KEY` / `OPENAI_API_KEY`
(LLM + embeddings), `DATABASE_URL` (Postgres), `QDRANT_URL`, `HUBSPOT_TOKEN`,
`GOOGLE_CREDENTIALS_JSON`, `REDIS_URL`. Each is optional and independently
upgradeable — the app degrades gracefully to the offline path for anything unset.

```bash
pytest -q          # run tests
```
