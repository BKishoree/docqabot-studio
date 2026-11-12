# DocQABot Studio

Ask questions about your own documents and get answers that show exactly which passages they came from.

Upload PDF, Markdown or plain-text files and wait until they are indexed. Then ask questions in plain language. Every answer lists its sources: the file name, how relevant the source is, and the full passage. Conversations are kept, so you can come back to them later.

Studio is a complete application (web interface, HTTP API, container image) built around the original DocQABot core, which is kept unchanged (see [How the core is preserved](#how-the-core-is-preserved)).

## Quick start

You need Docker (Docker Desktop on Windows or macOS, Docker Engine with the compose plugin on Linux).

```bash
docker compose -f compose.yaml -f compose.demo.yaml up -d --build        # demo, no key
docker compose up -d --build                                             # live (needs OPENAI_API_KEY in .env)
docker compose down                                                      # stop, data kept
```

Then open <http://127.0.0.1:8000>.

- **Demo mode** needs no OpenAI key. Answers come from a built-in simulator, and the interface says so on every screen. Use it to try the app.
- **Live mode** uses OpenAI. Copy `.env.example` to `.env` and set `OPENAI_API_KEY`. Without a key the app still starts and explains what is missing, but uploading and asking are blocked.
- Demo and live keep their data in **separate volumes** (`docqabot_pgdata_demo`, `docqabot_pgdata`), because simulated vectors are meaningless to real OpenAI ones.
- `docker compose down` keeps your data. `docker compose down -v` deletes it.

To stop the demo stack, use the same two `-f` files: `docker compose -f compose.yaml -f compose.demo.yaml down`.

## Modes

| Mode | How | Behaviour |
| --- | --- | --- |
| live | `OPENAI_API_KEY` set, `STUDIO_DEMO_MODE=false` | Real OpenAI (`text-embedding-3-small`, `gpt-4o-mini`) |
| live, not configured | no key | App runs; the status screen and a notice explain the missing key; upload and ask return `503 openai_not_configured` |
| demo | `compose.demo.yaml`, or `STUDIO_DEMO_MODE=true` | The core talks to the local OpenAI stub (`python -m studio.stub`); any real key is ignored and never sent anywhere |

## Web interface

Open <http://127.0.0.1:8000> (or your `STUDIO_BIND_ADDR:STUDIO_PORT`).

- **Ask** (`/`): type a question and press Enter (Shift+Enter for a new line). Each answer is followed by its sources: the file name, how closely it matches (for example "62% match"), and the exact passage, with the words of your question highlighted. Answers with no matching passage are marked "Not found in your documents".
- **Conversations** (left rail): kept across restarts. Rename or delete them from the rail or from the conversation header.
- **Library** (`/library`): drag files in or use Choose files (PDF, Markdown, plain text; up to the upload limit). Each file shows Indexing, then Ready or Failed (with the reason). Deleting a document removes it from future answers; earlier answers keep the passages they quoted, marked as removed.
- **Status** (`/status`): database and OpenAI state, mode, limits; "Check again" re-tests right away.
- In demo mode a yellow notice on every screen says answers are simulated.

## Configuration

All configuration comes from environment variables. Put them in `.env`, which compose reads and git ignores. `.env.example` lists the common ones with placeholders.

| Variable | Default | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | empty | OpenAI key for live mode. Only in `.env` or the environment, never in a file you commit. |
| `STUDIO_DEMO_MODE` | `false` | `true` = simulated answers from the stub |
| `STUDIO_BIND_ADDR` | `127.0.0.1` | Host address the app is published on. `0.0.0.0` on a server (then set the login pair). |
| `STUDIO_PORT` | `8000` | Host port for the app |
| `STUDIO_AUTH_USER`, `STUDIO_AUTH_PASSWORD` | empty | Both set = one shared login (HTTP Basic) on every page and API call, except `/api/v1/health/live` |
| `POSTGRES_PASSWORD` | `docqabot_local` | Database password. The default is only for a laptop where the database is bound to loopback. **Change it on any server.** Use only letters, digits and `- _ . ~` (it becomes part of the database URL). It takes effect only when the database volume is first created; see [Changing the database password](#changing-the-database-password). |
| `POSTGRES_USER`, `POSTGRES_DB` | `docqabot` | Database user and name |
| `STUDIO_DB_BIND_ADDR`, `STUDIO_DB_PORT` | `127.0.0.1`, `5433` | Where the database port is published on the host (5433 avoids a local PostgreSQL on 5432) |
| `STUDIO_MAX_UPLOAD_MB` | `20` | Largest file accepted |
| `STUDIO_OPENAI_TIMEOUT_S` | `60` | Timeout per OpenAI request |
| `STUDIO_OPENAI_MAX_RETRIES` | `1` | OpenAI SDK retries |
| `STUDIO_DB_STARTUP_RETRIES` | `30` | Database attempts at startup, 2 s apart, before starting in a degraded state |
| `STUDIO_LOG_LEVEL` | `INFO` | Logs go to stdout (`docker compose logs app`) |
| `DATABASE_URL` | set by compose | Only needed when running the app outside compose. It carries `options=-c ivfflat.probes=100` for exact vector search. |
| `STUDIO_STUB_URL` | `http://openai-stub:8001/v1` | Where demo mode sends OpenAI calls |
| `STUDIO_WEB_DIST` | `/srv/web` in the image, `web/dist` otherwise | Built web interface |

## Running on a server

You use the same image and the same compose files; only `.env` differs. On a Linux server:

1. Install Docker Engine and the compose plugin, then clone this repository.
2. Create `.env` with at least `OPENAI_API_KEY`, a strong URL-safe `POSTGRES_PASSWORD`, `STUDIO_BIND_ADDR=0.0.0.0`, `STUDIO_AUTH_USER` and `STUDIO_AUTH_PASSWORD`.
3. `docker compose up -d --build`, then check `docker compose ps` (the app reports `healthy`).

Set `POSTGRES_PASSWORD` before the first `up`: it is only applied when the volume is created.

The app logs a warning if it is published on a non-loopback address with the login off. Put a TLS-terminating reverse proxy in front of it; the app itself speaks plain HTTP. The only persistent state is the named Postgres volume, so the app container can be replaced at any time.

### Changing the database password

PostgreSQL reads `POSTGRES_PASSWORD` only when it initialises an empty volume. Changing the value in `.env` later does not change the password stored in an existing volume, and the app then fails to connect (the status screen shows the database as unavailable). To change it and keep your data:

```bash
docker compose exec db psql -U docqabot -d docqabot -c "ALTER USER docqabot PASSWORD 'new-password'"
```

Then set `POSTGRES_PASSWORD=new-password` in `.env` and run `docker compose up -d` so the app picks it up. Use your own `POSTGRES_USER`/`POSTGRES_DB` if you changed them; in demo mode add `-f compose.yaml -f compose.demo.yaml` to both commands. Alternatively, `docker compose down -v` deletes the volume and all its data, and the next `up` creates a new one with the new password.

## Developing

```bash
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-studio.txt          # Windows; use .venv/bin/python on Linux/macOS
docker compose up -d db                                                  # database on 127.0.0.1:5433
.venv\Scripts\python -m studio.stub --host 127.0.0.1 --port 8001         # optional: OpenAI stub
```

Then start the API. Set `OPENAI_BASE_URL=http://127.0.0.1:8001/v1` and `OPENAI_API_KEY=sk-stub-dev` to use the stub. Without `DATABASE_URL`, the app uses the database on `127.0.0.1:5433`.

```bash
.venv\Scripts\python -m uvicorn studio.main:app --reload --port 8000
```

Frontend (Node 22.12+):

```bash
npm --prefix web ci
npm --prefix web run dev      # http://127.0.0.1:5173, proxies /api to 127.0.0.1:8000
npm --prefix web test         # Vitest, once
npm --prefix web run build    # writes web/dist, served by the app
```

`VITE_MOCK_API=true npm --prefix web run dev` runs the interface against an in-memory mock API, with no backend needed. Fonts are bundled; the interface loads nothing from third-party hosts.

- API documentation: <http://127.0.0.1:8000/docs>.
- Tests: `pip install -r requirements-dev.txt`, then `pytest` (see `pytest.ini` and `tests/`). They never need a real key.
- Post-deploy check: `python tests/smoke/smoke.py --base-url http://127.0.0.1:8000`.

## How the core is preserved

The original DocQABot is the five files in `app/` plus the root `requirements.txt`, tagged `core-baseline`. None of them is edited (`git diff core-baseline -- app/ requirements.txt` is empty). Its original README is kept as [docs/CORE_README.md](docs/CORE_README.md).

- `studio/core_adapter.py` is the only module that imports from `app`. `studio/bootstrap.py` runs before it, so the core can be imported without a key and pointed at the stub in demo mode.
- The core's endpoints `POST /upload`, `GET /documents` and `POST /ask` are still served unchanged. The only additions are the upload size limit and, when enabled, the login.
- Studio's own tables are all prefixed `studio_` and created by `studio/migrations/`. The core tables are never altered.
- One runtime adjustment, approved by the owner: the core's two OpenAI client objects get a 60 s timeout and 1 retry (the SDK default timeout is 10 minutes).

## Known limits

- One shared workspace; no user accounts.
- Answers are not streamed.
- Questions always search all documents.
- A failed document must be removed and uploaded again.
- No OCR: scanned PDFs are rejected as having no text. DOCX is not supported.
- The core embeds a whole document in one OpenAI request, so very large documents (roughly over 150,000 words) fail to process.
- Follow-up questions are searched by their own words only. "And for part-timers?" may find less than the full question would.

The full design, API contract and acceptance criteria are in [docs/DESIGN.md](docs/DESIGN.md).
