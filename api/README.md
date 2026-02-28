# Polisi API

FastAPI service for the PolisiGPT product runtime.

## Local development

```bash
cd api
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
uvicorn polisi_api.main:app --reload
```

Copy `.env.example` to `.env` and provide:

- `SUPABASE_URL`
- `SUPABASE_DB_URL`
- `SUPABASE_JWT_SECRET` or `SUPABASE_JWKS_JSON`
- `ANTHROPIC_API_KEY`

## API surface

- `GET /healthz`
- `POST /api/chat`
- `GET /api/conversations`
- `GET /api/conversations/{conversation_id}`
