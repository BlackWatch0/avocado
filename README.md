# Avocado

AI-assisted CalDAV calendar orchestration project.

Project source-of-truth document (requirements, change history, TODO board):
- [PROJECT_LOG.md](./PROJECT_LOG.md)

## Project Overview

Avocado is a CalDAV-oriented AI scheduling service that can:
- discover calendars and classify immutable vs editable events
- manage a structured `[AI Task]` block in event `DESCRIPTION`
- call an OpenAI-compatible API to generate scheduling changes
- expose an intranet admin API for config, sync trigger, and audit
- provide a no-login admin page at `/` for config editing

## Repository Layout

- `avocado/`: service code (CalDAV, AI, sync engine, web admin)
- `tests/`: unit tests
- `config.example.yaml`: config template
- `docker-compose.yml`: Docker deployment and admin port mapping
- `PROJECT_LOG.md`: project source-of-truth log

## Local Run

1. Install dependencies:
   - `python -m pip install -r requirements.txt`
2. Prepare config:
   - copy `config.example.yaml` to `config.yaml`
   - fill `caldav.*` and `ai.*`
3. Start service:
   - `python -m avocado.main`
4. Check health:
   - `GET http://127.0.0.1:8080/healthz`

## Docker Deployment (Complete Flow)

### 1. Prerequisites

- Docker and Docker Compose installed
- run commands from repository root

### 2. Prepare Config

1. Copy template:
   - Linux/macOS: `cp config.example.yaml config.yaml`
   - Windows PowerShell: `Copy-Item config.example.yaml config.yaml`
2. Edit `config.yaml`:
   - `caldav.base_url`, `caldav.username`, `caldav.password`
   - `ai.base_url`, `ai.api_key`, `ai.model`
   - optional `sync.window_days`, `sync.interval_seconds`, `sync.timezone`

### 3. Admin Port Mapping

`docker-compose.yml` contains explicit admin mapping:
- `${AVOCADO_ADMIN_PORT:-18080}:8080`

Meaning:
- container admin service listens on `8080`
- host port defaults to `18080`
- override host port with environment variable `AVOCADO_ADMIN_PORT`

PowerShell example:
- `$env:AVOCADO_ADMIN_PORT=28080`
- `docker compose up -d --build`

### 4. Start

- `docker compose up -d --build`

### 5. Verify

1. Container status:
   - `docker compose ps`
2. Logs:
   - `docker compose logs -f avocado`
3. Health check:
   - default: `GET http://127.0.0.1:18080/healthz`
   - custom: `GET http://127.0.0.1:<AVOCADO_ADMIN_PORT>/healthz`

### 6. Operations

- Stop: `docker compose down`
- Restart: `docker compose restart avocado`
- Rebuild after code update: `docker compose up -d --build`

### 7. Persistence and Backup

- host `./config.yaml` -> container `/app/config.yaml`
- host `./data` -> container `/app/data`

Recommendation:
- backup `config.yaml` and `data/` regularly
- expose admin port only to trusted intranet

## Admin API

- `GET /healthz`
- `GET /` (admin page)
- `GET /api/config`
- `GET /api/config/raw`
- `PUT /api/config`
- `POST /api/ai/test`
- `GET /api/calendars`
- `PUT /api/calendar-rules`
- `POST /api/sync/run`
- `GET /api/sync/status`
- `GET /api/audit/events`

Default Docker admin URL:
- `http://127.0.0.1:18080`

Admin page behavior:
- secrets are masked by default
- leave `CalDAV password` or `AI API key` empty to keep existing values
- click `Run Sync` then calendar list is refreshed from CalDAV
- scheduler compares user-layer calendars (non-stage) with stage calendar to detect deltas and trigger re-planning
- per-calendar default behavior can be configured in UI:
  - immutable/editable
  - default locked
  - default mandatory
- AI Base URL defaults to `https://api.openai.com/v1`
- AI system prompt can be edited directly in admin page
- timezone uses dropdown selection (with custom fallback option when needed)
- `[AI Task]` block is simplified and includes key fields: `locked`, `mandatory`, `editable_fields`, `category`, `user_intent`

## Test

- `python -m unittest discover -s tests -v`
