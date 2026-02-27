# Avocado

AI-assisted CalDAV calendar orchestration project.

Project source-of-truth document (requirements, change history, TODO board):
- [PROJECT_LOG.md](./PROJECT_LOG.md)

## Quick Start

1. Copy `config.example.yaml` to `config.yaml` and fill your CalDAV + AI settings.
2. Run locally:
   - `python -m pip install -r requirements.txt`
   - `python -m avocado.main`
3. Or run with Docker:
   - `docker compose up --build -d`

Service endpoints:
- `GET /healthz`
- `GET /api/config`
- `PUT /api/config`
- `GET /api/calendars`
- `PUT /api/calendar-rules`
- `POST /api/sync/run`
- `GET /api/sync/status`
- `GET /api/audit/events`
