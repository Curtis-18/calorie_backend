# Calorie Backend

FastAPI service for the Calorie Tracker app: food logging, targets, insights and photo estimation.

## Deploying to Render

`render.yaml` is committed, so Render can build this as a Blueprint.

Required environment variables (set these in the Render dashboard, they are
deliberately **not** in the repo — see `.env.example` for the full list):

| Variable | Notes |
| --- | --- |
| `SUPABASE_URL` | e.g. `https://yourproject.supabase.co` |
| `DATABASE_URL` | Supabase connection string. A bare `postgresql://` URL is rewritten to `postgresql+asyncpg://` on startup. |
| `USDA_API_KEY` | USDA FoodData Central key |
| `GEMINI_API_KEY` | Google AI Studio key |
| `CORS_ORIGINS` | Comma separated list of allowed web origins. **Set this**, otherwise a deployed frontend is blocked by the browser. |

The app fails fast on boot if any of the first four are missing, so a
misconfigured deploy reports the problem immediately instead of 500ing on
the first request.

### Why the start command looks the way it does

`gunicorn app.main:app` on its own does **not** work. Gunicorn's default
`sync` worker calls the app as WSGI, and FastAPI is ASGI, so every request
dies with:

```
TypeError: FastAPI.__call__() missing 1 required positional argument: 'send'
```

The start command therefore pins `--worker-class uvicorn.workers.UvicornWorker`.

### Health check

`GET /health` runs a real `SELECT 1` against the database and returns 503
if it fails, so Render restarts the service when the connection pooler goes
away. `GET /` is a plain liveness probe.

## Local development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill it in
uvicorn app.main:app --reload
```

Interactive docs at `http://localhost:8000/docs`.

## Tests

```bash
pip install -r requirements.txt -r tests/requirements.txt
pytest
```

The suite covers config normalization, target math, upstream API response
parsing, auth enforcement and input validation. It does not need a database.

## Schema

Tables are created out of band with `create_tables.py`. The service never
runs migrations on startup, so a deploy can never drop or rewrite data:

```bash
python create_tables.py
```

## Notes

- `/foods/search` requires auth. It proxies a metered USDA key, so leaving
  it open would let anyone burn the quota.
- `python-multipart` is required by the `UploadFile` endpoint
  `POST /logs/analyze-photo`.
