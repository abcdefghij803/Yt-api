# Yt-api

# yt-music-control-api (single container)

Runs a yt-dlp extractor API (FastAPI) + a Telegram Control Bot in one container.

## Endpoints
- `GET /` → service status
- `GET /health` → health + uptime
- `GET /extract?url=YOUTUBE_URL` → returns `{id,title,duration,thumbnail,url}`
- `GET /metrics` → Prometheus-like text metrics
- `POST /_admin/toggle?state=on|off` (header: `x-api-key: API_SECRET`)

## Bot Commands
