# Avocado

AI-assisted CalDAV calendar orchestration project.

Project source-of-truth document (requirements, change history, TODO board):
- [PROJECT_LOG.md](./PROJECT_LOG.md)

## Project Overview

Avocado is a CalDAV-oriented AI scheduling service that can:
- discover calendars and orchestrate `user / stack / new` collaboration
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
   - optional heavy-load switch: `ai.high_load_model`, `ai.high_load_event_threshold`, `ai.high_load_auto_enabled`, `ai.high_load_auto_score_threshold`, `ai.high_load_auto_event_baseline`, `ai.high_load_use_flex`, `ai.high_load_flex_fallback_to_auto`
   - optional `sync.window_days`, `sync.interval_seconds`, `sync.timezone_source`, `sync.timezone`
   - AI system prompt is stored separately at `ai_system_prompt.txt` (managed in admin page)

### 3. Admin Port Mapping

`docker-compose.yml` contains explicit admin mapping:
- `${AVOCADO_ADMIN_PORT:-1443}:8080`

Meaning:
- container admin service listens on `8080`
- host port defaults to `1443`
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
   - default: `GET http://127.0.0.1:1443/healthz`
   - custom: `GET http://127.0.0.1:<AVOCADO_ADMIN_PORT>/healthz`

### 6. Operations

- Stop: `docker compose down`
- Restart: `docker compose restart avocado`
- Rebuild after code update: `docker compose up -d --build`

### 7. Persistence and Backup

- host `./config.yaml` -> container `/app/config.yaml`
- host `./ai_system_prompt.txt` -> container `/app/ai_system_prompt.txt`
- host `./ai_task_template.yaml` -> container `/app/ai_task_template.yaml`
- host `./data` -> container `/app/data`
- AI prompt file defaults to `/app/ai_system_prompt.txt` (override with `AVOCADO_PROMPT_PATH`)
- AI task template defaults to `/app/ai_task_template.yaml` (override with `AVOCADO_AI_TASK_TEMPLATE_PATH`)

Recommendation:
- backup `config.yaml` and `data/` regularly
- expose admin port only to trusted intranet

## Admin API

- `GET /healthz`
- `GET /` (admin page)
- `GET /api/config`
- `GET /api/config/raw`
- `GET /api/system/timezone`
- `PUT /api/config`
- `POST /api/ai/test`
- `GET /api/calendars`
- `PUT /api/calendar-rules`
- `POST /api/sync/run`
- `POST /api/sync/run-window`
- `GET /api/sync/status`
- `GET /api/audit/events`
- `GET /api/ai/changes`
- `POST /api/ai/changes/undo`
- `POST /api/ai/changes/revise`
- `GET /api/metrics/ai-request-bytes`

Default Docker admin URL:
- `http://127.0.0.1:1443`

Admin page behavior:
- secrets are masked by default
- leave `CalDAV password` or `AI API key` empty to keep existing values
- click `Run Sync` then calendar list is refreshed from CalDAV
- system ensures three managed calendars exist:
  - `stack` calendar (window target truth set)
  - `user` calendar (user-facing schedule layer)
  - `new` calendar (inbox queue for newly created events)
- on each sync, new events in `new` are merged into target set and then removed from `new`
- AI Base URL defaults to `https://api.openai.com/v1`
- API connectivity test is available as a blue inline link directly below AI Base URL
- after connectivity test, available models are loaded into Model dropdown
- optional: configure a High-Load Model + event threshold; when planning event count reaches threshold, sync switches to that model for this run
- optional: enable automatic heavy-load detection by schedule density + event count + overlap conflicts; when computed score reaches threshold, sync also switches to high-load model
- optional: enable `Use Flex Tier Above Threshold` to send `service_tier=flex` on heavy sync windows
- when Flex is enabled, client uses longer timeout (at least 10 minutes), retries resource-unavailable/timeouts with backoff, and can fallback to `service_tier=auto`
- managed calendar recovery: if configured managed calendar ID is missing and no same-name calendar exists, sync auto-creates one; if multiple same-name calendars exist, sync refuses and asks for manual cleanup
- AI system prompt can be edited directly in admin page
- timezone uses dropdown selection (with custom fallback option when needed)
- admin page supports English/Chinese UI:
  - default language follows browser language
  - manual override available from the language selector in header
- `[AI Task]` block is simplified and now includes only: `locked`, `user_intent`
- admin page includes run-log query panels (sync runs + audit events)
- logs page includes an AI token-usage line chart (derived from audit action `ai_request`)
- AI token-usage chart auto refreshes every 30s and supports custom retention days (default 90)
- admin page supports one-click custom time-range sync (start/end datetime)
- optional AI payload test logging:
  - set `ai.payload_logging_enabled: true`
  - payload I/O saved to `ai.payload_log_path` (default `data/test_logs/ai_payload_exchange.jsonl`)
- AI planning payload uses compact schema (`events_by_uid` + `target_uids`) to reduce token usage:
  - each event keeps only `t/s/l/d/k/i` minimal fields
  - internal fields (`x-*`, `etag`, `href`, `source`, `original_*`) are not sent to AI
- AI now supports both update and create planning results:
  - `changes` can be `uid`-only (calendar ID is rebuilt by mapping)
  - `creates` supports split/new sessions; created events are written to `stack` then mirrored to `user`
  - split convention: original event becomes part 1 in `changes`, remaining parts go to `creates`

## Test

- `python -m unittest discover -s tests -v`

### Integration Smoke Test (use your configured `config.yaml`)

- Basic checks (CalDAV + AI + config):
  - `python -m avocado.tools.smoke_test`
- Include one real sync run (manual-window):
  - `python -m avocado.tools.smoke_test --run-sync`
- Custom window:
  - `python -m avocado.tools.smoke_test --run-sync --start 2026-03-01T00:00:00+00:00 --end 2026-03-08T00:00:00+00:00`
- Skip one side during troubleshooting:
  - `python -m avocado.tools.smoke_test --skip-ai`
  - `python -m avocado.tools.smoke_test --skip-caldav`

### Real E2E Sync Suite (writes test events, triggers sync, keeps logs)

- Run full suite (config read/write, fixed-schedule protection, AI move instruction):
  - `python -m avocado.tools.e2e_sync_suite`
- Optional custom window:
  - `python -m avocado.tools.e2e_sync_suite --start 2026-03-01T00:00:00+00:00 --end 2026-03-08T23:59:59+00:00`
- Test logs:
  - saved under `data/test_logs/e2e_sync_suite_<timestamp>.log`
  - script also prints JSON summary to stdout

### User Case Runner (UTF-8 Chinese cases, validates stack/user/new)

- Run with default fixture:
  - `python -m avocado.tools.user_case_runner`
- Run with a custom case file:
  - `python -m avocado.tools.user_case_runner --cases tests/fixtures/user_cases_zh.json`
- What it validates for each case:
  - behavior expectation (move earlier / locked unchanged / description-only / new import)
  - calendar assertions: event exists in `user` + `stack`, raw uid removed from `new`
- Logs:
  - saved under `data/test_logs/user_cases_<timestamp>.json`
