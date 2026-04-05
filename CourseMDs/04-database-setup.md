# Chapter 4: Database Setup with Async SQLAlchemy

This chapter covers the async SQLAlchemy 2.0 ORM: creating the engine, session factory, declarative base, and model classes. Everything uses the modern `mapped_column()` syntax — not the legacy `Column()` pattern.

## 4.1 Async Engine and Session Factory

The engine is your connection to the database. The session factory creates individual sessions (units of work) for each request. Open `src/notesmith/database.py`:

```python
# src/notesmith/database.py
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
    echo=settings.debug,   # Log SQL statements when debug=True
    pool_size=5,           # Number of persistent connections
    max_overflow=10,       # Additional connections allowed under load
    pool_recycle=1800,     # Recycle connections after 30 minutes
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
```

Walk through each piece:

**`Base`** is the declarative base class. All your models will inherit from it. It includes two important elements:

- **`AsyncAttrs`** — A mixin that enables `await obj.awaitable_attrs.relationship_name` for lazy-loaded relationships in async code. Without it, accessing an unloaded relationship raises `MissingGreenlet`.
- **`MetaData(naming_convention=...)`** — Tells SQLAlchemy how to name constraints (indexes, unique constraints, foreign keys). Without this, Alembic cannot generate reliable migration downgrades because it does not know the constraint names.

**`create_async_engine`** creates the connection pool. The URL format is `postgresql+asyncpg://user:password@host:port/database`. The `+asyncpg` part tells SQLAlchemy to use the asyncpg driver.

Pool settings:

- `pool_size=5` — Keep 5 connections open permanently.
- `max_overflow=10` — Allow up to 10 additional connections during spikes (total max: 15).
- `pool_recycle=1800` — Close and reopen connections older than 30 minutes to avoid stale connections from firewall timeouts.
- `echo=True` — Print every SQL statement. Useful during development; disable in production.

**`async_sessionmaker`** is a factory that produces `AsyncSession` instances. `expire_on_commit=False` is critical: without it, accessing any attribute on a model after `session.commit()` triggers an implicit lazy load, which fails in async context because there is no active event loop in the synchronous attribute access path.

## 4.2 The Database Session Dependency

FastAPI's dependency injection system will provide a database session to each endpoint. Add this function to `database.py`:

```python
# src/notesmith/database.py (add at the bottom)
from typing import AsyncGenerator


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

This is a **generator dependency**. Here is what happens for each request:

1. FastAPI calls `get_db()`.
2. The generator creates an `AsyncSession` using the context manager (`async with`).
3. `yield session` hands the session to the endpoint function.
4. After the endpoint completes, execution resumes after `yield`.
5. If the endpoint succeeded, `session.commit()` persists all changes.
6. If the endpoint raised an exception, `session.rollback()` discards all changes.
7. The `async with` block closes the session automatically.

This means your endpoint code never needs to call `commit()` or `rollback()` manually — the dependency handles it.

## 4.3 Defining Models with mapped_column

Now define the actual database tables. Start with the User model. Open `src/notesmith/auth/models.py`:

```python
# src/notesmith/auth/models.py
import datetime
from typing import TYPE_CHECKING

from sqlalchemy import String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from notesmith.database import Base

if TYPE_CHECKING:
    from notesmith.notes.models import Note # error goes away after Note is added later


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(256))
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    notes: Mapped[list["Note"]] = relationship(
        back_populates="owner", lazy="selectin", cascade="all, delete-orphan"
    )
```

Let's break down the syntax:

**`Mapped[int]`** declares both the Python type and the column's nullability:

- `Mapped[int]` → column is `INTEGER NOT NULL`
- `Mapped[Optional[int]]` → column is `INTEGER` (nullable)
- `Mapped[str]` → column is `VARCHAR NOT NULL` (you should specify length with `String(n)`)

**`mapped_column(...)`** configures the column. It replaces the legacy `Column()` function. Common parameters:

| Parameter | Purpose |
|-----------|---------|
| `primary_key=True` | Marks the primary key column. |
| `String(320)` | Sets the SQL type explicitly (VARCHAR(320)). Required for string columns if you want a length limit. |
| `unique=True` | Adds a UNIQUE constraint. |
| `index=True` | Creates a database index for faster lookups. |
| `default=True` | Python-side default (set before INSERT). |
| `server_default=func.now()` | Database-side default (the database sets it during INSERT). |
| `onupdate=func.now()` | Database-side value set on every UPDATE. |

**`relationship(...)`** defines the ORM-level relationship to another model:

- `back_populates="owner"` — The inverse side of the relationship. `Note.owner` will point back to `User`.
- `lazy="selectin"` — When you load a `User`, SQLAlchemy automatically loads their notes with a second `SELECT ... IN (...)` query. This avoids the `MissingGreenlet` error that occurs with the default lazy loading in async code.
- `cascade="all, delete-orphan"` — When a user is deleted, their notes are deleted too.

**`TYPE_CHECKING`** — The `Note` import is inside `if TYPE_CHECKING:` to avoid circular imports at runtime. Both `models.py` files import from `database.py`, and if they also imported each other directly, Python would raise an `ImportError`. The string `"Note"` in the type annotation is resolved lazily.

Now create the Note model. Open `src/notesmith/notes/models.py`:

```python
# src/notesmith/notes/models.py
import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from notesmith.database import Base

if TYPE_CHECKING:
    from notesmith.auth.models import User


class Note(Base):
    __tablename__ = "notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text)
    is_pinned: Mapped[bool] = mapped_column(default=False)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime.datetime] = mapped_column(
        server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    owner: Mapped["User"] = relationship(back_populates="notes")
```

New elements here:

- **`Text`** — Unbounded text column (as opposed to `String(n)` which has a limit). Used for note content and summaries.
- **`Mapped[Optional[str]]`** — The `summary` field is nullable because it is only populated when the user requests AI summarization.
- **`ForeignKey("users.id")`** — Creates a foreign key to the `users.id` column. The string `"users.id"` uses the **table name** (not the class name).

## 4.4 How Type Annotations Map to SQL Types

SQLAlchemy 2.0 infers SQL types from Python type annotations:

| Python Type | SQL Type |
|-------------|----------|
| `int` | `INTEGER` |
| `str` | `VARCHAR` (specify length with `String(n)`) |
| `float` | `FLOAT` |
| `bool` | `BOOLEAN` |
| `datetime.datetime` | `TIMESTAMP` |
| `datetime.date` | `DATE` |
| `bytes` | `BLOB` / `BYTEA` |

When you need a specific SQL type (like `Text` or `String(320)`), pass it as the first argument to `mapped_column()`. The `Mapped[]` annotation still controls nullability.

## 4.5 The Lifespan Handler

The lifespan context manager runs startup and shutdown logic for the application. We will use it to verify the database connection on startup. Update `src/notesmith/main.py`:

```python
# src/notesmith/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI

from notesmith.database import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: verify database connection
    async with engine.begin() as conn:
        # This will raise if the database is unreachable
        await conn.run_sync(lambda conn: None)
    yield
    # Shutdown: dispose of the connection pool
    await engine.dispose()


app = FastAPI(
    title="NoteSmith API",
    version="0.1.0",
    description="A notes API with AI capabilities.",
    lifespan=lifespan,
)


@app.get("/health")
async def health_check():
    return {"status": "ok"}
```

What this does:

- **Before `yield`** (startup): Opens a connection to verify the database is reachable. If PostgreSQL is down, the application will fail to start instead of silently accepting requests it cannot serve.
- **After `yield`** (shutdown): Closes all connections in the pool cleanly.

The old `@app.on_event("startup")` decorator is deprecated. If you pass a `lifespan` parameter to `FastAPI()`, `on_event` handlers are ignored entirely. Always use the lifespan pattern.

## 4.6 Verify the Connection

Make sure your PostgreSQL server is running and the `notesmith` database exists (from Chapter 1). Then start the server:

```bash
uvicorn src.notesmith.main:app --reload --port 8000
```

If you see the standard Uvicorn startup message without errors, the database connection is working. If you see a connection error, check:

1. Is PostgreSQL running? (`pg_isready` or `sudo systemctl status postgresql`)
2. Is the `DATABASE_URL` in `.env` correct?
3. Does the `notesmith` database exist? (`psql -l` to list databases)

The database has no tables yet — that happens in the next chapter with Alembic.

---

Proceed to [Chapter 5: Alembic Migrations](./05-alembic-migrations.md).
