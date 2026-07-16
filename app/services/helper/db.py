import ssl
from collections.abc import AsyncGenerator
from urllib.parse import urlsplit, urlunsplit

import certifi
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

from app.services.helper.settings import get_settings

# macOS python.org builds don't ship a root CA bundle -- point the SSL
# context at certifi's, or the Neon TLS handshake fails to verify.
_ssl_context = ssl.create_default_context(cafile=certifi.where())


def get_database_url() -> str:
    """asyncpg speaks SSL via connect_args, not sslmode/channel_binding query
    params (Neon appends both) -- strip the query string, driver stays in sync."""
    parts = urlsplit(get_settings().database_url)
    scheme = parts.scheme.replace("postgresql", "postgresql+asyncpg", 1)
    return urlunsplit((scheme, parts.netloc, parts.path, "", parts.fragment))


def make_engine(**kwargs) -> AsyncEngine:
    # Neon closes idle connections server-side, pre_ping avoids handing out a stale one
    kwargs.setdefault("pool_pre_ping", True)
    return create_async_engine(
        get_database_url(),
        connect_args={"ssl": _ssl_context},
        **kwargs,
    )


engine = make_engine(echo=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSession(engine) as session:
        yield session
