import logging
import os

import uvicorn

from app.create_app import get_app
from app.utils.constants import ConfigFile


app = get_app(ConfigFile.PRODUCTION)

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
