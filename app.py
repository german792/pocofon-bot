"""
Unified runner for POCO AI:
Runs both the POCO AI Web Studio (FastAPI) and the Telegram Bot concurrently.
"""

import asyncio
import os
import uvicorn
from web import app as web_app
from bot import main as run_bot


async def run_server():
    port = int(os.getenv("PORT", "7860"))
    config = uvicorn.Config(web_app, host="0.0.0.0", port=port, log_level="warning")
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    # Run both the web studio and the telegram bot concurrently
    await asyncio.gather(
        run_server(),
        run_bot(),
    )


if __name__ == "__main__":
    asyncio.run(main())
