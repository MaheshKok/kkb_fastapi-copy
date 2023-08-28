import logging
import logging.config
import os

import uvicorn

from app.create_app import get_app
from app.utils.constants import ConfigFile


logging.basicConfig(
    level=logging.DEBUG, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
app = get_app(ConfigFile.PRODUCTION)


if __name__ == "__main__":
    try:
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=int(os.environ.get("PORT", 8000)),
        )
    except BaseException as e:
        logging.exception(e)
