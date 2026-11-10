"""
Unified runner for POCO AI:
Runs the POCO AI Web Studio (FastAPI) and optionally the Telegram Bot concurrently.
"""

import asyncio
import logging
import os
import uvicorn
from web import app as web_app
from bot import main as run_bot

logger = logging.getLogger(__name__)


async def run_server():
    port = int(os.getenv("PORT", "7860"))
    config = uvicorn.Config(web_app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


async def main():
    enable_bot = os.getenv("ENABLE_BOT", "0").lower() in ("1", "true", "yes")
    tasks = [run_server()]
    if enable_bot:
        logger.info("Starting Telegram Bot along with Web Studio...")
        tasks.append(run_bot())
    else:
        logger.info("Running Web Studio only (Telegram Bot is running separately on GitHub Actions).")

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
