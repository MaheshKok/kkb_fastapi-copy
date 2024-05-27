"""
middleware
"""

from typing import Dict
from typing import Optional
from typing import Union

from sqlalchemy import URL
from sqlalchemy import Engine
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.base import RequestResponseEndpoint
from starlette.requests import Request
from starlette.types import ASGIApp

from app.database.session_manager.db_session import Database


# havent tested yet


class SQLAlchemyMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        db_url: Optional[Union[str, URL]] = None,
        custom_engine: Optional[Engine] = None,
        engine_kw: Dict = None,
        session_args: Dict = None,
        commit_on_exit: bool = False,
    ):
        super().__init__(app)
        self.commit_on_exit = commit_on_exit
        engine_kw = engine_kw or {}
        session_args = session_args or {}

        # Initialize the DBSession
        Database.init(
            db_url=db_url,
            custom_engine=custom_engine,
            engine_kw=engine_kw,
            session_args=session_args,
        )


async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
    async with Database(commit_on_exit=self.commit_on_exit):
        return await call_next(request)
