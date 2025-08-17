import os, time, threading
from collections import deque, defaultdict
from typing import Optional

from fastapi import FastAPI, Query, Header, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
import yt_dlp

APP_START = time.time()

# ====== Config ======
API_SECRET = os.getenv("API_SECRET", "")  # if set, required for admin ops
MAINTENANCE = {"enabled": False}  # toggle via /_admin/toggle

# ====== Metrics (in-memory) ======
lock = threading.Lock()
TOTAL_REQ = 0
ENDPOINT_REQ = defaultdict(int)
LAST_REQ_TS = 0.0
WINDOWS = {
    60: deque(),   # 1 min
    300: deque(),  # 5 min
    900: deque(),  # 15 min
}

def _now():
    return time.time()

def _bump(endpoint: str):
    global TOTAL_REQ, LAST_REQ_TS
    with lock:
        t = _now()
        TOTAL_REQ += 1
        ENDPOINT_REQ[endpoint] += 1
        LAST_REQ_TS = t
        for w, dq in WINDOWS.items():
            dq.append(t)
            # drop old
            while dq and t - dq[0] > w:
                dq.popleft()

# ====== App ======
api = FastAPI(title="yt-dlp Extractor API", version="1.0.0")

@api.get("/health")
def health():
    _bump("/health")
    return {
        "ok": not MAINTENANCE["enabled"],
        "maintenance": MAINTENANCE["enabled"],
        "uptime_sec": round(_now() - APP_START, 3),
        "last_request_ts": LAST_REQ_TS,
    }

@api.get("/")
def root():
    _bump("/")
    return {"status": "running", "service": "yt-dlp extractor", "version": "1.0.0"}

# Core extractor
@api.get("/extract")
def extract(url: str = Query(..., description="YouTube video URL")):
    _bump("/extract")
    if MAINTENANCE["enabled"]:
        raise HTTPException(status_code=503, detail="Service in maintenance mode")
    try:
        ydl_opts = {
            "format": "bestaudio/best",
            "quiet": True,
            "noplaylist": True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        data = {
            "id": info.get("id"),
            "title": info.get("title"),
            "duration": info.get("duration"),
            "thumbnail": info.get("thumbnail"),
            "url": info["url"],  # direct stream URL
        }
        return JSONResponse(data)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Admin: enable/disable without redeploy
@api.post("/_admin/toggle")
def toggle(state: Optional[str] = Query(None), x_api_key: Optional[str] = Header(default=None)):
    _bump("/_admin/toggle")
    if API_SECRET:
        if x_api_key != API_SECRET:
            raise HTTPException(status_code=401, detail="Invalid x-api-key")
    if state not in {"on", "off"}:
        raise HTTPException(status_code=400, detail="state must be 'on' or 'off'")
    MAINTENANCE["enabled"] = (state == "off")
    return {"maintenance": MAINTENANCE["enabled"]}

# Prometheus-like or simple text metrics
@api.get("/metrics")
def metrics():
    _bump("/metrics")
    t = _now()
    with lock:
        lines = [
            f"app_uptime_seconds {int(t-APP_START)}",
            f"app_requests_total {TOTAL_REQ}",
            f"app_last_request_ts {int(LAST_REQ_TS or 0)}",
        ]
        for ep, cnt in ENDPOINT_REQ.items():
            lines.append(f"app_endpoint_requests_total{{endpoint=\"{ep}\"}} {cnt}")
        for w, dq in WINDOWS.items():
            lines.append(f"app_requests_window{{window=\"{w}\"}} {len(dq)}")
        return PlainTextResponse("\n".join(lines) + "\n")
