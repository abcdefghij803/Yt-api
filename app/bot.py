import os, re, json, asyncio
from urllib.parse import urlencode

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

try:
    from youtubesearchpython import VideosSearch
    HAS_SEARCH = True
except Exception:
    HAS_SEARCH = False

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
DEFAULT_BASE = os.getenv("API_BASE", "http://localhost:8080")
API_SECRET = os.getenv("API_SECRET", "")  # for /enable /disable
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").split(',') if x.strip().isdigit()}

# Optional (for future Pyrogram usage)
API_ID = os.getenv("API_ID", "")
API_HASH = os.getenv("API_HASH", "")

STATE = {"base": DEFAULT_BASE.rstrip('/')}
YT_RE = re.compile(r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/")

# ===== HTTP helper =====
async def get_json(url: str, headers=None, timeout=60):
    import httpx
    async with httpx.AsyncClient(timeout=timeout) as cli:
        r = await cli.get(url, headers=headers)
        r.raise_for_status()
        return r.json()

async def post_json(url: str, headers=None, params=None, timeout=60):
    import httpx
    async with httpx.AsyncClient(timeout=timeout) as cli:
        r = await cli.post(url, headers=headers, params=params)
        r.raise_for_status()
        return r.json()

# ===== Commands =====
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Control Bot ready!\n\nCommands:\n"
        "/setapi <base> — set base URL\n"
        "/getapi — show base\n"
        "/ping — API health\n"
        "/requests — totals + windows\n"
        "/stats — detailed status\n"
        "/enable /disable — maintenance toggle (admin)\n"
        "/test <url|query> — extract link and show\n"
        "\nTip: /setapi https://ytx-1234.app"
    )

async def setapi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if ADMIN_IDS and uid not in ADMIN_IDS:
        return await update.message.reply_text("🚫 Not allowed")
    parts = update.message.text.split(maxsplit=1)
    if len(parts) < 2:
        return await update.message.reply_text("Usage: /setapi <base>")
    base = parts[1].strip().rstrip('/')
    STATE["base"] = base
    await update.message.reply_text(f"✅ Base set: {base}")

async def getapi(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    base = STATE.get("base", "")
    await update.message.reply_text(f"🔗 Base: {base or 'not set'}")

async def ping(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    base = STATE.get("base")
    if not base:
        return await update.message.reply_text("Set base first: /setapi <base>")
    try:
        data = await get_json(f"{base}/health")
        await update.message.reply_text("✅ Health: " + json.dumps(data))
    except Exception as e:
        await update.message.reply_text(f"❌ Health error: {e}")

def _parse_metrics(text: str):
    out = {"total": 0, "last_ts": 0, "endpoints": {}, "windows": {}}
    for line in text.splitlines():
        if line.startswith("app_requests_total"):
            out["total"] = int(line.split()[-1])
        elif line.startswith("app_last_request_ts"):
            out["last_ts"] = int(line.split()[-1])
        elif line.startswith("app_endpoint_requests_total"):
            try:
                ep = line.split('endpoint="', 1)[1].split('"}', 1)[0]
                val = int(line.rsplit(' ', 1)[-1])
                out["endpoints"][ep] = val
            except Exception:
                pass
        elif line.startswith("app_requests_window"):
            w = line.split('window="', 1)[1].split('"}', 1)[0]
            val = int(line.rsplit(' ', 1)[-1])
            out["windows"][w] = val
    return out

async def requests_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    base = STATE.get("base")
    if not base:
        return await update.message.reply_text("Set base first: /setapi <base>")
    import httpx
    try:
        async with httpx.AsyncClient(timeout=30) as cli:
            r = await cli.get(f"{base}/metrics")
            r.raise_for_status()
            m = _parse_metrics(r.text)
        lines = [
            f"📊 Requests Total: {m['total']}",
            "Per Endpoint:",
        ]
        for ep, cnt in m["endpoints"].items():
            lines.append(f"• {ep}: {cnt}")
        if m["windows"]:
            lines.append("Recent windows:")
            for k, v in m["windows"].items():
                mins = int(int(k) // 60) or 1
                lines.append(f"• last {mins} min: {v}")
        await update.message.reply_text("\n".join(lines))
    except Exception as e:
        await update.message.reply_text(f"❌ Metrics error: {e}")

async def stats(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    base = STATE.get("base")
    if not base:
        return await update.message.reply_text("Set base first: /setapi <base>")
    try:
        health = await get_json(f"{base}/health")
        import httpx
        async with httpx.AsyncClient(timeout=30) as cli:
            r = await cli.get(f"{base}/metrics")
            r.raise_for_status()
            m = _parse_metrics(r.text)
        text = (
            f"🩺 <b>Health</b>: {'OK' if health.get('ok') else 'DOWN'}\n"
            f"🕒 Uptime: {health.get('uptime_sec')}s\n"
            f"🧰 Maintenance: {health.get('maintenance')}\n"
            f"📈 Total: {m['total']} | /extract: {m['endpoints'].get('/extract', 0)}\n"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    except Exception as e:
        await update.message.reply_text(f"❌ Stats error: {e}")

async def _resolve_query(q: str) -> str:
    if YT_RE.search(q):
        return q
    if not HAS_SEARCH:
        raise RuntimeError("Install youtubesearchpython or pass a full YouTube URL")
    vs = VideosSearch(q, limit=1)
    res = vs.result().get("result")
    if not res:
        raise RuntimeError("No results found")
    return res[0]["link"]

async def test_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    base = STATE.get("base")
    if not base:
        return await update.message.reply_text("Set base first: /setapi <base>")
    if not ctx.args:
        return await update.message.reply_text("Usage: /test <YouTube URL or query>")
    q = " ".join(ctx.args)
    try:
        url = await _resolve_query(q)
        data = await get_json(f"{base}/extract?" + urlencode({"url": url}))
        title = data.get("title", "Unknown")
        stream = data.get("url")
        await update.message.reply_text(
            f"🎵 <b>{title}</b>\n🔗 <code>{stream}</code>", parse_mode=ParseMode.HTML
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Test error: {e}")

async def _admin_toggle(update: Update, state: str):
    base = STATE.get("base")
    if not base:
        return await update.message.reply_text("Set base first: /setapi <base>")
    uid = update.effective_user.id
    if ADMIN_IDS and uid not in ADMIN_IDS:
        return await update.message.reply_text("🚫 Not allowed")
    headers = {"x-api-key": API_SECRET} if API_SECRET else None
    try:
        data = await post_json(f"{base}/_admin/toggle", headers=headers, params={"state": state})
        await update.message.reply_text(f"✅ Maintenance: {data.get('maintenance')}")
    except Exception as e:
        await update.message.reply_text(f"❌ Toggle error: {e}")

async def enable_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _admin_toggle(update, "on")

async def disable_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _admin_toggle(update, "off")

def run_bot():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN not set")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("setapi", setapi))
    app.add_handler(CommandHandler("getapi", getapi))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("requests", requests_cmd))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("test", test_cmd))
    app.add_handler(CommandHandler("enable", enable_cmd))
    app.add_handler(CommandHandler("disable", disable_cmd))
    app.run_polling()
