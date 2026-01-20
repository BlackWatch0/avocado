# avocado

A self-hosted, CalDAV-based intelligent scheduler that aggregates external calendars and turns fuzzy tasks into dynamically planned events using AI.

**Language:** [中文](README.md) | English

---

## Project Name

**avocado** (a CalDAV-based WebDAV/ICS aggregation and intelligent task scheduling system)

---

## Overview

avocado is a self-hosted smart calendar and task management system that uses **CalDAV** as the only input and output interface. It can act as a widget managing user calendars on the server:

- Aggregates multiple **WebDAV / URL-ICS** external calendars
- Lets users create events or tasks directly from the native mobile calendar
- Schedules “flexible time” tasks automatically via GPT
- Supports dynamic rescheduling, task splitting, and conflict awareness
- Exposes standard **CalDAV / WebDAV / ICS** access

System positioning:

- **CalDAV = Single Source of Truth**
- **WebDAV / ICS = read-only inputs**
- **GPT = scheduling and decision engine**

---

## Core Constraints (Must-Haves)

- ✅ All user input goes through CalDAV
- ✅ Tasks must be entered as calendar events (`VEVENT`)
- ✅ Native mobile calendar is sufficient for creation and edits
- ❌ No dependency on client-specific APIs
- ❌ No requirement for precise time inputs

---

## Technology Choices

### CalDAV Server (Core Data Layer)

- Compatible with all standard **CalDAV** servers (no vendor lock-in)

---

## Calendar Structure (Strong Conventions)

A CalDAV server should maintain at least the following collections:

| Calendar | Purpose |
| --- | --- |
| `schedule` | Fixed events + GPT-scheduled tasks |
| `inbox-tasks` | User-created unscheduled tasks |
| `external-feeds` | Aggregated external WebDAV / ICS (read-only) |
| `ai-generated` | GPT summaries, plans, logs (optional) |

---

## Unified Modeling for Events and Tasks

### Fixed Events

- Standard `VEVENT`
- Explicit `DTSTART / DTEND`
- Written directly to `schedule`
- GPT does not modify (only warns on conflicts)

### Flexible Tasks

To keep mobile creation simple, tasks are still `VEVENT` entries with the following rules:

- Created in `inbox-tasks`
- `CATEGORIES` must include `TASK`
- `DTSTART` not required
- Must include a deadline constraint (explicit or implicit)

#### Task Metadata (Recommended: DESCRIPTION block)

Users can add a structured block in the description and the system will parse it:

```
[AI_TASK]
deadline=2026-02-01 23:59
estimate=90m
window=weeknights
flex=soft
[/AI_TASK]
```

Equivalent `X-AI-*` fields are also supported (machine-friendly, optional):

- `X-AI-TYPE: TASK`
- `X-AI-DEADLINE`
- `X-AI-ESTIMATE-MIN`
- `X-AI-WINDOW`
- `X-AI-FLEX`

---

## Scheduling Rules

### Principles

- Fixed events > scheduled tasks > unscheduled tasks
- `deadline` defaults to a hard constraint (unless `flex=soft`)
- Manually moved/marked events are treated as locked (`X-AI-LOCK:1`)

### Output

The scheduler creates new `VEVENT` items in `schedule`:

- Explicit `DTSTART / DTEND`
- `CATEGORIES: TASK,SCHEDULED`
- `X-AI-ORIGIN-UID` points to the original inbox task
- Supports splitting into multiple sub-events

---

## Dynamic Adjustments

Triggers for incremental rescheduling:

- User adds/edits fixed events
- User updates task deadline / estimate
- GPT updates time estimates
- External ICS updates occupied time

Principles:

- Only reschedule impacted tasks
- `X-AI-LOCK:1` events are never moved

---

## Component Layout (Suggested Repo Structure)

```
repo/
├── caldav/        # CalDAV server config / Docker (optional)
├── aggregator/    # WebDAV / ICS → CalDAV (external-feeds)
├── scheduler/     # Task recognition + scheduling (inbox → schedule)
├── ai/            # GPT: estimation / splitting / summaries / decisions
├── config/
│   ├── calendars.yaml
│   └── rules.yaml
└── docs/
```

---

## User Workflow (Zero Learning Cost)

- Subscribe/login to CalDAV via the native mobile calendar
- Create a new event:
  - With explicit time → fixed event (stored in `schedule`)
  - No explicit time + deadline/estimate in notes → task (stored in `inbox-tasks`)
- The system schedules tasks into `schedule` as one or more time blocks

---

## Non-Goals

- ❌ Build a custom calendar UI
- ❌ Replace system To-Do apps
- ❌ Force users to provide precise parameters
