---
name: Nakima command-center UI architecture
description: How the command-center.html dashboard is built and what it wires up
---

## Architecture
`static/command-center.html` is a single-file SPA (no build step, no framework).
- Served directly from the Python/FastAPI app at `/`
- Uses vanilla JS + fetch API to call all `/api/v1/` endpoints
- Fonts: Space Grotesk (display), IBM Plex Sans (body), IBM Plex Mono (code)
- Color system: CSS custom properties (`--signal-cyan`, `--signal-amber`, `--signal-red`, `--signal-violet`, `--signal-green`)

## Sections and their API endpoints
- Tasks → `GET/POST /api/v1/tasks/`
- NEIS Reasoning → static UI (trail nodes are interactive)
- Security score → `POST /api/v1/security/{repo}/scan`, `GET /api/v1/security/{repo}/findings`
- Decision Registry → `GET /api/v1/intelligence/{repo}/decisions`
- Event Log → `GET /api/v1/intelligence/{repo}/events`
- Repositories → `GET /api/v1/repositories/`, `POST /api/v1/repositories/index`
- Documents → `GET/POST /api/v1/documents/{repo}/`
- Health → `GET /health`

## Auto-refresh
Tasks table refreshes every 15 seconds. All data loads on `refreshAll()` at init.

**Why:** No WebSocket in the initial build — polling is sufficient for the task cycle (~60s per issue).
