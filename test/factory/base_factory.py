from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.orm import scoped_session
from sqlalchemy.orm import sessionmaker

from app.core.config import get_config
from app.database.base import get_db_url
from app.utils.constants import ConfigFile


engine: AsyncEngine = create_async_engine(get_db_url(get_config(ConfigFile.TEST)))
async_session = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

sc_session = scoped_session(async_session)
