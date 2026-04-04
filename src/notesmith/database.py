from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from notesmith.config import settings

# Naming conventions for constraints. This ensures Alembic can properly
# detect and name constraints during migrations, which is required for
# reliable downgrade (drop constraint) operations.
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(AsyncAttrs, DeclarativeBase):
    """Base class for all SQLAlchemy models."""

    metadata = MetaData(naming_convention=convention)


engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,  # Log SQL statements when debug=True
    pool_size=5,  # Number of persistent connections
    max_overflow=10,  # Additional connections allowed under load
    pool_recycle=1800,  # Recycle connections after 30 minutes
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


from typing import AsyncGenerator # ignore warning, will put this on top in a real app


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
