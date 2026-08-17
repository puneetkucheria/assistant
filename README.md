# Assistant

A network-hosted LLM assistant with Azure DevOps integration. Backend is
Python (FastAPI + LangChain), frontend is React (Vite + Tailwind). The FastAPI
process serves the built SPA so the whole app is reachable at a single origin
on the LAN.

## Quick start

1. Create the venv and install backend deps:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Configure secrets:
   ```bash
   cp .env.example .env
   # edit .env: set OPENAI_API_KEY, AZURE_DEVOPS_ORG/PROJECT/PAT
   ```

3. Build the frontend:
   ```bash
   cd frontend
   npm install
   npm run build        # outputs to ../backend/static
   cd ..
   ```

4. Run:
   ```bash
   ./run.sh
   # or: uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
   ```

5. From another machine on the LAN open `http://<server-ip>:8000/`.

## Docker

The whole app ships as a single image: the frontend is built in a stage and
its static assets are dropped into `backend/static`, so FastAPI serves the
SPA and API from one origin in production.

```bash
# Build from the project root (context must include both frontend/ and backend/):
docker build -f backend/Dockerfile -t assistant .

# Run, loading secrets from .env (see .env.example for the schema):
docker run --env-file .env -p 8000:8000 assistant
```

Open `http://localhost:8000/`.

There is also a standalone `frontend/Dockerfile` that only compiles the SPA
and is meant to be reused as a build stage rather than run directly.

## Dev mode

Two terminals:
- `uvicorn backend.main:app --reload`
- `cd frontend && npm run dev` (proxies `/api` to `:8000`, hot reloads UI)

Open `http://localhost:5173`.

## Configuration

See `.env.example` for the full schema and `assistant.md` for the architecture.

### Azure DevOps PAT scopes

Create a PAT in ADO with at least:
- `Work Items: Read` for read/search tools,
- `Work Items: Read & Write` for update/create/comment tools.

### Optional LAN gate

Set `ALLOWED_CIDR=192.168.0.0/16` to reject clients outside that network.
Leave empty to allow any origin (use only on a trusted LAN).

## Notes / MVP limitations

- Chat memory is in-process — cleared on restart.
- No user authentication (relies on network isolation).
- Single assistant (Azure DevOps); registry is scaffolded for more.
