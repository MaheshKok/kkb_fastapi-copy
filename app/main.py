import asyncio
import logging
import os

from hypercorn.asyncio import serve
from hypercorn.config import Config

from app.core.config import get_config
from app.setup_app import get_application
from app.utils.constants import CONFIG_FILE

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def start_application():
    cnf_file = os.path.join(os.path.abspath("cfg"), CONFIG_FILE.PRODUCTION)
    config = get_config(cnf_file)
    app = await get_application(config)

    logger.info(f"Trading System API version {app.version}")

    hypercorn_config = Config.from_mapping(config.data.get("app", {}))
    await serve(app, hypercorn_config)


if __name__ == "__main__":
    asyncio.run(start_application())
