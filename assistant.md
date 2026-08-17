# Plan: Network-Hosted LLM Assistant with Azure DevOps Integration (MVP)

## 1. Overview & Architecture

A **Python FastAPI backend** + **React frontend**, both served from your server and reachable from any machine on the LAN. The backend uses **LangChain** with the **OpenAI API** for function-calling (tool use), and exposes thin REST endpoints the React UI calls. The Azure DevOps REST API is wired in as a set of LangChain `StructuredTool`s the LLM can invoke autonomously. No authentication (trusting network isolation).

```
┌─────────────┐   HTTP/SSE   ┌──────────────────────┐    tools     ┌──────────────┐
│  React SPA  │ ───────────► │  FastAPI Backend     │ ──────────► │ Azure DevOps │
│ (Vite)      │ ◄───stream── │ + LangChain agent    │             │ REST API 7.1 │
└─────────────┘              │ + ADO tool functions │             └──────────────┘
                             └──────────┬───────────┘
                                        │ OpenAI API
                                        ▼
                                  ┌──────────────┐
                                  │ OpenAI (gpt) │
                                  └──────────────┘
```

The FastAPI server also serves the built React static files, so from the network the whole app is a single origin (e.g. `http://<server-ip>:8000`) — no CORS, no separate web server needed for the MVP.

## 2. Project Layout

```
assistant/
├── .env                      # secrets + config (gitignored)
├── .env.example              # template, committed
├── .gitignore
├── README.md
├── requirements.txt
├── run.sh / run.bat          # uvicorn launcher
├── backend/
│   ├── main.py               # FastAPI app, mounts /api and serves SPA
│   ├── config.py             # pydantic-settings loads .env
│   ├── api/
│   │   ├── chat.py           # POST /api/chat (SSE stream of agent tokens)
│   │   └── health.py
│   ├── agents/
│   │   └── ado_agent.py      # LangChain agent + tool registration
│   └── tools/
│       ├── ado_client.py     # thin httpx wrapper around ADO REST API
│       └── ado_tools.py      # LangChain StructuredTool definitions:
│                              #   get_work_item, list_work_items (WIQL),
│                              #   update_work_item, create_work_item,
│                              #   add_work_item_comment, list_area_paths (helper)
└── frontend/
    ├── package.json
    ├── vite.config.ts        # dev: proxy /api -> :8000; build -> backend/static
    ├── index.html
    └── src/
        ├── App.tsx
        ├── main.tsx
        ├── components/
        │   ├── ChatWindow.tsx     # message list + streaming render
        │   ├── ChatInput.tsx
        │   └── ToolCallBadge.tsx  # shows "Updated work item #123" inline
        └── api.ts                # fetch + EventSource/SSE helper
```

## 3. `.env` Schema (11 vars)

```dotenv
# --- LLM ---
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o-mini

# --- Azure DevOps ---
AZURE_DEVOPS_ORG=myorg
AZURE_DEVOPS_PROJECT=MyProject
AZURE_DEVOPS_PAT=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
AZURE_DEVOPS_DEFAULT_AREA=MyProject\\Team A   # optional default area path for new items

# --- Server ---
HOST=0.0.0.0
PORT=8000
ALLOWED_CIDR=192.168.0.0/16   # optional LAN gate middleware

# --- App ---
CORS_ORIGIN=                  # empty = same-origin (SPA served by backend)
APP_NAME=My Assistant
```

`config.py` uses `pydantic-settings` (`BaseSettings`) so values are typed and validated at startup. `ALLOWED_CIDR` is an **optional** soft gate — even though no auth is required, a CIDR check on the connecting IP is a cheap "only LAN clients can talk to me" guard.

## 4. Backend Implementation Plan

### 4.1 `backend/config.py`
- `Settings(BaseSettings)` reading `.env` via `model_config = SettingsConfigDict(env_file=".env")`.
- Exposes a `get_settings()` singleton (lru_cache).

### 4.2 `backend/tools/ado_client.py`
A thin `httpx.AsyncClient` wrapper bound to `settings`. All requests construct:
```
Base URL : https://dev.azure.com/{org}/{project}/_apis/
Headers  : Authorization: Basic base64(":" + PAT)
Timeout  : 30s
```
Key methods (async):
- `get_work_item(id) -> dict` — `GET wit/workitems/{id}?$expand=fields&api-version=7.1`
- `query_wiql(wiql: str) -> list[int]` — `POST wit/wiql?api-version=7.1` returns IDs; then `POST wit/workitemsbatch` to hydrate fields in one call (avoids N+1).
- `update_work_item(id, patch_ops: list[dict]) -> dict` — `PATCH wit/workitems/{id}?api-version=7.1`, `Content-Type: application/json-patch+json` (critical — not `application/json`).
- `create_work_item(type_, patch_ops) -> dict` — `POST wit/workitems/{type}?api-version=7.1` (URL-encode spaces: `User%20Story`).
- `add_comment(id, text)` — `POST wit/workItems/{id}/comments?api-version=7.1-preview.4` (note: this endpoint is on preview).
- `list_area_paths()` — helper to resolve the `System.AreaPath` field for creation; uses the classification API. Stops the LLM from guessing an invalid area path.

### 4.3 `backend/tools/ado_tools.py`
LangChain `StructuredTool` wrappers using `pydantic` schemas for inputs. Each tool owns its own validation and converts human input → API shape. Concretely:

| Tool | Args schema | Returns |
|---|---|---|
| `get_work_item` | `work_item_id: int` | formatted summary (ID, title, state, assignee, type) |
| `search_work_items` | `wiql_or_keywords: str, top: int = 10` | list of `{id, title, state}` |
| `update_work_item` | `work_item_id: int, title: str\|None, state: str\|None, assigned_to: str\|None, comment: str\|None` | confirmation + final field snapshot |
| `create_work_item` | `type: Literal["Bug","Task","User Story"], title: str, description: str = "", area_path: str\|None` | `{id, url}` of created item |
| `add_work_item_comment` | `work_item_id: int, comment: str` | confirmation |

**Validation rules baked into tools (so the LLM never sends garbage):**
- `state` is validated against the project's allowed states (fetched lazily and cached).
- `assigned_to` is resolved to a known identity before PATCH: if input is free text, tool calls an identity lookup (`_apis/identities`) and refuses ambiguous matches unless `bypassRules=True` is explicitly logged — emit a clear message back to the LLM instead of silently writing garbage.
- Build JSON-Patch ops only for non-null fields; never include `None` paths.

### 4.4 `backend/agents/ado_agent.py`
- `ChatOpenAI(model=..., streaming=True, temperature=0)`.
- `create_tool_calling_agent(llm, tools, system_prompt)` from `langchain.agents`.
- System prompt: scoped instructions ("You are an Azure DevOps assistant for project X. Use the provided tools to read/search/create/update work items. Always confirm destructive actions by stating what you changed. Never invent work item IDs — use search first."). Loaded from a file so it can be tuned without touching code.
- Streaming: each token and `on_tool_start`/`on_tool_end` events are emitted separately over SSE. Tool-end events carry a small JSON payload so the React ToolCallBadge can render "✓ Updated #123: state→Active".

### 4.5 `backend/api/chat.py`
- `POST /api/chat` — accepts `{ messages: list[{role, content}], conversation_id?: str }`. Returns `text/event-stream`:
  - `event: token` — `data: "the "` (assistant tokens)
  - `event: tool_start` — `data: {"tool":"update_work_item","args":{...}}`
  - `event: tool_end` — `data: {"tool":"update_work_item","result":{...}}`
  - `event: done` — final message boundary
- Keeps a per-conversation LangChain memory in-process (for MVP, an in-memory dict keyed by `conversation_id`; restart clears it). Swap to Redis later if needed.

### 4.6 `backend/main.py`
- FastAPI app with `/api` router mounted under the prefix.
- Optional `AllowedCIDRMiddleware` reading `ALLOWED_CIDR` — returns 403 if the client IP isn't in-range.
- Static file mount on `"static"` -> `frontend/dist` (Vite build output). Catch-all route falls back to `index.html` so React Router works if routes are added later.
- `if __name__ == "__main__": uvicorn.run(...)` on `HOST:PORT`.

## 5. Frontend Implementation Plan

### 5.1 Stack
- Vite + React 18 + TypeScript.
- TailwindCSS (utility classes for fast styling).
- No state library — `useState` + a `useChat` hook is enough for the MVP.

### 5.2 Components
- `App.tsx` lays out the sidebar (assistant switcher stub) + chat panel.
- `ChatWindow.tsx` — message list; renders assistant stream token-by-token as they arrive via SSE; renders `ToolCallBadge` between user msg and assistant reply when tool events arrive.
- `ChatInput.tsx` — textarea + send; disabled while streaming; Enter to send, Shift+Enter newline.
- `api.ts` `chat(messages, onToken, onToolEvent)` — uses `fetch` with `ReadableStream` reader + manual SSE parsing (avoids `EventSource`'s GET-only limitation, lets us POST the message history).

### 5.3 Vite config
- Dev: `server.proxy['/api'] = 'http://localhost:8000'`.
- Build: `outDir` = `../backend/static`, `emptyOutDir: true`. After `npm run build`, the FastAPI server serves the SPA — single origin, no CORS config needed.

## 6. Frontend→Backend Contract
- `POST /api/chat` body & SSE stream (see 4.6).
- `GET /api/health` → `{ status: "ok", openai: true, ado: true }` (ado check does a cheap `GET _apis/projects/{project}`).

## 7. Build / Run Steps
1. `python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
2. `cp .env.example .env` and fill in keys.
3. `cd frontend && npm install && npm run build` (emits into `../backend/static/`).
4. `./run.sh` → `uvicorn backend.main:app --host $HOST --port $PORT`.
5. From another LAN machine open `http://<server-ip>:8000/`.

For dev mode: two terminals — `uvicorn backend.main:app --reload` (`npm run dev` for Vite with the proxy). The dev loop doesn't require a frontend rebuild.

## 8. `requirements.txt` (proposed)
```
fastapi
uvicorn[standard]
pydantic-settings
httpx
python-dotenv
langchain
langchain-openai
langchain-core
```
Frontend: `react`, `react-dom`, `vite`, `@vitejs/plugin-react`, `typescript`, `tailwindcss`, `postcss`, `autoprefixer`.

## 9. Edge Cases & Risks Captured in the Plan
| Risk | Mitigation |
|---|---|
| `Content-Type: application/json-patch+json` is non-obvious; using `application/json` makes ADO throw a silent 400 | Centralised in `ado_client.update_work_item` so it's correct by construction |
| `System.AssignedTo` ambiguous by display name | Tool resolves identity first; refuses ambiguous matches; uses `DisplayName<email>` form when available |
| WIQL returns only IDs | Always batch-hydrate via `POST wit/workitemsbatch` (one call, not N) |
| Creation needs valid `System.AreaPath` | `list_area_paths()` tool + a `AZURE_DEVOPS_DEFAULT_AREA` fallback in `.env` |
| Preview endpoint (`7.1-preview.4`) for comments differs from the GA `7.1` used elsewhere | Each tool method hard-codes its own api-version param |
| OpenAI tool-selection mistakes (e.g., fabricates a work item ID) | System prompt forbids it; agent is equipped with `search_work_items` and the prompt insists on search-then-act |
| Replaying `System.State` strings that don't exist in project process | Tool validates state against project's allowed values list; if not cached we can hard-code a small allowlist for the MVP |
| In-memory memory is lost on restart | Acceptable for MVP; flag in README. Swap to a SQLite file or Redis for v2 |
| Server reachable from outside the LAN if firewall is open | Optional `ALLOWED_CIDR` middleware; document firewall rule (allow 8000 only on LAN iface) |

## 10. Stretch / Future (not in MVP, parked)
- Multiple assistants: the agent layer already supports swapping `system_prompt` + toolsets per "assistant name" — adding a `/api/assistants` registry + a sidebar picker is a small follow-up.
- Persistent chat history (SQLite), per-user accounts, file uploads.
- Other "tasks" (Jira, GitHub Issues, calendar) follow the same `tools/*` pattern — no agent changes needed.

## 11. Implementation Decisions (locked in)
- Tech stack: **Python (FastAPI) + React (Vite/TS)**.
- LLM provider: **OpenAI API** (model defaults to `gpt-4o-mini`, configurable via `.env`).
- Auth: **No auth** (intranet only); optional `ALLOWED_CIDR` soft gate middleware (kept in for cheap defense-in-depth, disabled by leaving it empty).
- Azure DevOps scope: **Full CRUD** — get, search (WIQL), update fields, create, and comment.
- LLM framework: **LangChain** (`create_tool_calling_agent` with `ChatOpenAI`, streaming via SSE).
- **Feature钩1: State allowlist**: lazy-fetch valid states per work-item-type on first use, cache for the process lifetime (most correct, one-off cost).
- **Decision 2: LAN gate**: keep optional `ALLOWED_CIDR` middleware (defence-in-depth; leave empty to fully disable).
- **Decision 3: Streaming**: SSE streaming for UX (token-by-token + tool-call badges rendered inline).
- **Decision 4: Multi-assistant scaffold**: build the single Azure DevOps assistant now, but scaffold an `assistant registry` (dict of name → (system_prompt, tools)) so the next assistant is just a new tool module + 3 lines of registration.

## 12. Azure DevOps REST API Reference (quick lookup)
- Auth: HTTP Basic with **empty username** + PAT as password → `Authorization: Basic base64(":" + PAT)`.
- Base URL: `https://dev.azure.com/{org}/{project}/_apis/`.
- Get work item: `GET wit/workitems/{id}?api-version=7.1`
- Update: `PATCH wit/workitems/{id}?api-version=7.1` with `Content-Type: application/json-patch+json`, body is JSON Patch array (`[{ "op":"add", "path":"/fields/System.Title", "value":"..." }]`). Common fields: `System.Title`, `System.State`, `System.AssignedTo`, `System.History` (inline history).
- Create: `POST wit/workitems/{type}?api-version=7.1` (URL-encode spaces in type like `User%20Story`), same JSON Patch body.
- Add threaded comment: `POST wit/workItems/{id}/comments?api-version=7.1-preview.4` with `{"text": "..."}` (preview API).
- WIQL query: `POST wit/wiql?api-version=7.1` with `{"query": "SELECT ... FROM WorkItems WHERE ..."}` — returns only IDs; hydrate via `POST wit/workitemsbatch`.
- AssignedTo formats: display name `"Jamal Hartnett"` (ambiguous), disambiguated `"Jamal Hartnett<fabrikamfiber4@hotmail.com>"`, or full `IdentityRef` object from a prior GET; empty string `""` to clear.
