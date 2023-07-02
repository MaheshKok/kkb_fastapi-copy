import logging
import os
import sys

import uvicorn

from app.create_app import get_app
from app.utils.constants import ConfigFile


# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def handle_exception(exc_type, exc_value, exc_traceback):
    logging.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))


sys.excepthook = handle_exception


app = get_app(ConfigFile.PRODUCTION)

if __name__ == "__main__":
    try:
        uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
    except BaseException as e:
        logging.exception(e)
