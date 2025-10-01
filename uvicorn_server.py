# uvicorn_server.py
import uvicorn
from app import app

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=5000,
        log_level="info",
        ws_ping_interval=20,
        ws_ping_timeout=20
    )
