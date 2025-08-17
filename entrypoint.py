import threading
import uvicorn
from app.api import api
from app.bot import run_bot

def run_api():
    uvicorn.run(api, host="0.0.0.0", port=8080)

if __name__ == "__main__":
    t = threading.Thread(target=run_api, daemon=True)
    t.start()
    run_bot()
