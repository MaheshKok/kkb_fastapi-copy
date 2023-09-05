import logging.config
import os

import uvicorn
from fastapi import HTTPException
from starlette.responses import JSONResponse

from app.create_app import get_app
from app.utils.constants import ConfigFile


logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
app = get_app(ConfigFile.PRODUCTION)


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    logging.error(f"HTTPException occurred: {exc.detail}")
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


if __name__ == "__main__":
    try:
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=int(os.environ.get("PORT", 8000)),
        )
    except BaseException as e:
        logging.error(f"Error running fastapi: {e}")
