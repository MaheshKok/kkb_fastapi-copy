import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine

from app.core.config import get_config
from app.database.base import db
from app.database.base import get_db_url
from app.database.models import *  # noqa

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
from app.utils.constants import CONFIG_FILE

config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = db

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    cnf_file = os.path.join(os.path.abspath("app/cfg"), CONFIG_FILE.PRODUCTION)
    config_ = get_config(cnf_file)

    db_url = get_db_url(config_, drivername="postgresql")
    # Create SQLAlchemy engine
    engine = create_engine(db_url)

    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema="public",  # Modify this if your version table is in a different schema
            include_schemas=True,
        )

        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations_online())
