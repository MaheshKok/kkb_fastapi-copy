import asyncio
import logging
import os

import uvicorn
from starlette.responses import JSONResponse

from app.database.base import lifespan
from app.setup_app import get_application
from app.utils.constants import ConfigFile


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def start_application():
    app = get_application(ConfigFile.PRODUCTION)

    @app.exception_handler(Exception)
    async def exception_handler(request, exc):
        logging.error(f"Internal Server Error: {str(exc)}")
        return JSONResponse(status_code=500, content={"message": "Internal Server Error"})

    async with lifespan(app):
        return app


# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s]: %(message)s",
    handlers=[
        logging.StreamHandler(),  # Log to console
    ],
)

# Log a sample message
logging.debug("Debug message")
logging.info("Info message")
logging.warning("Warning message")
logging.error("Error message")


if __name__ == "__main__":
    app = asyncio.run(start_application())
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
