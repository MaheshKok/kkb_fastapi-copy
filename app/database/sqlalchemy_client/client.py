from contextvars import ContextVar
from typing import Dict
from typing import Optional
from typing import Union

from fastapi_async_sqlalchemy.exceptions import MissingSessionError
from fastapi_async_sqlalchemy.exceptions import SessionNotInitialisedError
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import URL
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine


_Session: Optional[async_sessionmaker] = None
_session: ContextVar[Optional[AsyncSession]] = ContextVar("_session", default=None)


class DBSessionMeta(type):
    # using this metaclass means that we can access db.session as a property at a class level,
    # rather than db().session
    @property
    def session(self) -> AsyncSession:
        """Return an instance of Session local to the current async context."""
        if _Session is None:
            raise SessionNotInitialisedError

        session = _session.get()
        if session is None:
            raise MissingSessionError

        return session


class Database(metaclass=DBSessionMeta):
    def __init__(self, session_args: Dict = None, commit_on_exit: bool = True):
        self.token = None
        self.session_args = session_args or {}
        self.commit_on_exit = commit_on_exit

    async def __aenter__(self):
        if not isinstance(_Session, async_sessionmaker):
            raise SessionNotInitialisedError

        self.token = _session.set(_Session(**self.session_args))
        return self.session  # Note that we now return the session

    async def __aexit__(self, exc_type, exc_value, traceback):
        session = _session.get()
        if exc_type is not None:
            await session.rollback()

        if self.commit_on_exit:
            await session.commit()

        await session.close()
        _session.reset(self.token)

    @classmethod
    def init(
        cls,
        db_url: Optional[Union[str, URL]] = None,
        custom_engine: Optional[Engine] = None,
        engine_kw: Dict = None,
        session_args: Dict = None,
    ):
        engine_kw = engine_kw or {}
        session_args = session_args or {}

        if not custom_engine and not db_url:
            raise ValueError("You need to pass a db_url or a custom_engine parameter.")
        if not custom_engine:
            engine = create_async_engine(db_url, **engine_kw)
        else:
            engine = custom_engine

        global _Session
        _Session = async_sessionmaker(engine, expire_on_commit=False, **session_args)

    # using metaclass property
    @property
    def session(self) -> AsyncSession:
        """Return an instance of Session local to the current async context."""
        if _Session is None:
            raise SessionNotInitialisedError

        session = _session.get()
        if session is None:
            raise MissingSessionError

        return session
