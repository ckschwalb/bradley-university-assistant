# Bradley University AI Assistant

> A university-sponsored preview, built with guidance and support from Bradley University and with its permission. It hasn't launched. It reads only the university's public website and course catalog.

A chat assistant that answers questions about Bradley University using the university's public website and course catalog. It runs on your own computer in Docker. It works out of the box in **demo mode**, answering by quoting the most relevant passages from Bradley's pages. Add your own API key (Claude, OpenAI, or Gemini) for AI-written answers. Search runs on a local model either way.

## Quick start

You need [Docker Desktop](https://www.docker.com/products/docker-desktop/). For AI-written answers you also need an API key from one of [Anthropic](https://console.anthropic.com/settings/keys), [OpenAI](https://platform.openai.com/api-keys), or [Google AI Studio](https://aistudio.google.com/apikey); without one the chat runs in demo mode.

```bash
git clone https://github.com/ckschwalb/bradley-university-assistant.git
cd bradley-university-assistant
docker compose up --build
```

Then:

1. Open **http://localhost:8000**. The start screen offers **Try the demo**, or **Add your own API key** to have the assistant write full answers. You can also add a key later in the admin center (**Admin** in the chat's title bar, then **Assistant**).
2. Watch **Knowledge** in the admin center. On first start the crawler indexes bradley.edu and the course catalog: about 20 minutes (roughly 6 for the website's ~1,400 pages, 12 for ~3,100 courses). Chat works meanwhile, with whatever is indexed so far. Later crawls only re-index what changed.

The app listens only on `127.0.0.1`, so nothing else on your network can reach it. To use a different port: `PORT=8080 docker compose up`.

## What's in the app

**Chat** (`/`): a chat widget that answers from the indexed content, streams each answer as it's written, cites the pages it used, remembers the conversation, and lets people rate answers. Its start screen explains that it's a working prototype, not officially launched, and offers demo mode or your own API key. The title bar links to the admin center. It opens over the live bradley.edu home page so it looks the way it would on the real site; add `?site=<url>` to load another page behind it, or `?site=off` for a static screenshot when you're offline.

**Admin dashboard** (`/admin`):

| Page | What it does |
|---|---|
| Overview | Whether answering and crawling are working, usage counts, the share of answers the quality judge found grounded, recent questions, and **Needs review**: answers that look wrong (the assistant couldn't find something, linked a Bradley page that isn't indexed, answered in vague terms without citing anything, or the quality judge scored it low) and thumbs-down ratings |
| Conversations | Every conversation as a full transcript, with the model, sources and quality judge scores behind each answer; filter by needs review or rated; delete one or all |
| Knowledge | Crawl status and **Crawl now** (website, course catalog or both; optionally a full re-crawl), auto-crawl interval, what's indexed by type, **Test a question** to see exactly what search returns, and a browser for every indexed page |
| Assistant | Choose Claude, OpenAI, or Gemini and the model; turn the quality judge on or off and pick its model; edit the system prompt (or go back to the default in `systemprompt.txt`), and preview an answer from a draft before saving it |
| Observability | Every call to the AI provider over the last day, week or month: answers and failures over time, response time (median, p95, time to first words), tokens, quality judge averages, a per-model comparison, and the latest calls with their timings |

Needs review combines simple text checks ([review.py](backend/review.py)) with the quality judge ([evaluator.py](backend/evaluator.py)): after each answer, a second model call scores it from 1 to 5 for groundedness (every fact comes from the retrieved sources), relevance and completeness, and lists any claims the sources don't support. The judge uses the chat provider's key, so each answer costs one more request; turn it off under Assistant. Treat both as prompts to look, not verdicts.

By default the dashboard has no password because the app is only reachable from your machine. To require one, set `ADMIN_TOKEN` (`ADMIN_TOKEN=choose-a-long-random-string docker compose up`): the dashboard then asks for the token before it loads, and the admin and settings APIs refuse requests without `Authorization: Bearer <token>`. The chat itself stays open. Questions are limited to 1,000 characters.

## How it works

```
                 ┌──────────────────────── Docker Compose ─────────────────────────┐
 browser ──────► │  app (FastAPI + React)                crawler (crawler_service) │
 localhost:8000  │   • chat: search index → prompt →      • crawls on request or   │
                 │     Claude / OpenAI / Gemini             on a schedule          │
                 │   • admin API                          • embeds text locally    │
                 │            │                                     │              │
                 │            └──────► /data/app.db (SQLite) ◄──────┘              │
                 └─────────────────────────────────────────────────────────────────┘
```

- **Crawling** ([sitemap_crawler.py](backend/sitemap_crawler.py), [course_catalog_crawler.py](backend/course_catalog_crawler.py)): lists every page, program, department, college, post and faculty profile through the bradley.edu WordPress API, fetches only what changed since the last run, and converts it to clean markdown. Course descriptions come from catalog.bradley.edu. Pages removed from the site are removed from the index.
- **Embeddings** ([embeddings.py](backend/embeddings.py)): `snowflake/snowflake-arctic-embed-s` runs on the CPU through fastembed and is baked into the image. It was picked by benchmarking five small models on real site content (the scripts are in [eval/embedding-benchmark/](eval/embedding-benchmark/)).
- **Search** ([search.py](backend/search.py)): the question's vector is compared against every indexed chunk in memory, which takes milliseconds at this size. The five best chunks become the context.
- **Chat** ([main.py](backend/main.py), [answering.py](backend/answering.py), [llm.py](backend/llm.py)): LangChain builds a system prompt (with today's date on campus and the search results), the conversation's recent messages loaded from the database, and the new question, then streams the answer from the provider selected in the dashboard to the widget as newline-delimited JSON. The answer ends with a `Used: 1, 3` line naming the sources it drew on; the server turns that into source links and keeps it out of the stream.
- **Demo mode** ([demo.py](backend/demo.py)): with no API key set up, search runs as usual and the answer quotes the best-matching passage from each of the top pages, with links. No AI is involved, so it's free and never states anything the website doesn't; demo answers aren't judged or traced.
- **Quality and observability** ([evaluator.py](backend/evaluator.py), [observability.py](backend/observability.py)): once an answer is sent, the judge grades it in the background. Every provider call (answer, judgement, prompt preview) is recorded as a trace with its timings, token counts and outcome, but not its text.
- **Storage**: one SQLite file holds conversations, feedback, settings (including API keys), the edited system prompt, traces and evaluations, and the index. Times are stored in UTC and shown in the viewer's time zone. On start, the app migrates a database from an older version in place.

## Data and backups

Everything lives in the `data` Docker volume, so it survives restarts and rebuilds.

```bash
# Export conversations, messages and feedback to JSON
docker compose exec app python manage_db.py export
docker compose cp app:/data/backups ./backups

# Delete everything and start over (conversations, settings, keys, index)
docker compose down -v
```

API keys are stored unencrypted in that database. They never leave your machine except in requests to the provider you chose.

## Development without Docker

Python 3.11+ and Node 24+.

```bash
# Backend (uses uv: https://docs.astral.sh/uv/)
cd backend
uv sync                                       # installs the exact versions in uv.lock
uv run uvicorn main:app --reload --port 8000  # terminal 1
uv run python crawler_service.py              # terminal 2

# Frontend with hot reload (Vite; proxies API calls to port 8000)
cd frontend
npm install
npm start                                     # Vite dev server, http://localhost:3000
```

The database defaults to `backend/local.db`. Useful commands:

```bash
uv run python crawler_service.py --once [--force]   # crawl now and exit
uv run python manage_db.py export                    # conversations to backups/*.json
uv run python manage_db.py reset --yes               # export, then empty the database
```

Dependencies are declared in `backend/pyproject.toml` and pinned in `backend/uv.lock`, which the Docker image and CI install from. Add a package with `uv add <name>`; update the pins with `uv lock --upgrade`.

## Tests

```bash
cd backend && uv run pytest        # API, streaming, admin token, judge, traces, migration, crawler helpers
cd backend && uv run ruff check .  # lint
cd frontend && npm test            # chat widget and streaming, request and data-loading helpers, message component, time helpers
cd frontend && npm run lint        # lint
```

The backend tests use a throwaway database and fake chat and judge models, so they need no API key or network. CI runs both linters, both suites and the frontend build ([.github/workflows/ci.yml](.github/workflows/ci.yml)).

## Measuring answer quality

`evaluate.py` runs a fixed question set through search, the chat model and the quality judge, using the indexed content, the active prompt and the provider set up in the dashboard. It reports the retrieval hit rate (did search find a page that answers the question?) and the judge's average scores. Each question costs two model calls, and nothing is saved to the conversation history.

```bash
cd backend
uv run python evaluate.py                       # the embedding benchmark's 40 questions
uv run python evaluate.py --limit 10 --out results.json
```

## Project structure

```
backend/
  main.py                  app setup: CORS and the cross-site write guard, routers, static frontend
  auth.py                  the optional admin token (ADMIN_TOKEN)
  demo.py                  demo mode: answers that quote the best-matching pages, no AI
  answering.py             search → prompt → model, shared by chat, prompt preview and evaluate.py
  evaluator.py             the quality judge: groundedness, relevance and completeness scores
  evaluate.py              end-to-end answer quality over a fixed question set
  observability.py         traces of every provider call, and their summaries
  review.py                text checks behind the admin's Needs review list
  llm.py                   provider list, model listing, chat model setup
  search.py                in-memory semantic search
  embeddings.py            local embedding model
  sitemap_crawler.py       bradley.edu WordPress crawler
  course_catalog_crawler.py catalog.bradley.edu course crawler
  crawler_service.py       runs crawls on request / on schedule
  system_prompt.py         active prompt and placeholder filling
  settings_store.py        settings shared by app and crawler
  models.py, db.py         database tables and connection
  manage_db.py             export and reset
  routers/                 chat (streaming endpoint), system (health, status), admin (crawl,
                           prompt, sources), conversations (overview, transcripts, review,
                           search test), observability, settings, feedback, suggestions
  pyproject.toml, uv.lock  dependencies, pinned; ruff and pytest settings
frontend/src/              React chat widget
frontend/src/admin/        admin dashboard: Overview, Conversations, Knowledge, Assistant, Observability
                           (useApi.js is the shared data-loading hook; AdminLogin.jsx the token sign-in)
systemprompt.txt           default system prompt
eval/embedding-benchmark/  scripts behind the embedding model choice
```
