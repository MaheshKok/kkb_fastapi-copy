import logging
import os

import uvicorn

from app.setup_app import get_application
from app.utils.constants import ConfigFile


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = get_application(ConfigFile.PRODUCTION)

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
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
