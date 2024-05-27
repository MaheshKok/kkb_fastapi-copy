import logging.config
import os

import uvicorn
from fastapi import HTTPException
from fastapi import Request
from fastapi import status
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse

from app.create_app import get_app
from app.create_app import register_sentry
from app.utils.constants import ConfigFile


logging.basicConfig(level=logging.DEBUG)

register_sentry()

app = get_app(ConfigFile.PRODUCTION)


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    logging.error(f"HTTPException occurred: {exc.detail}")
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": exc.errors(),
            "body": await request.json(),
            "message": "Validation error",
        },
    )


if __name__ == "__main__":
    try:
        uvicorn.run(
            app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), log_level="debug"
        )
    except BaseException as e:
        logging.error(f"Error running fastapi: {e}")
