import logging
import os

import uvicorn

from app.create_app import get_app
from app.utils.constants import ConfigFile


app = get_app(ConfigFile.PRODUCTION)


if __name__ == "__main__":
    try:
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=int(os.environ.get("PORT", 8000)),
            log_config="log.ini",
        )
    except BaseException as e:
        logging.exception(e)
