# Chapter 12: Capstone Project — NoteSmith

You have built NoteSmith piece by piece across the previous eleven chapters. This chapter consolidates everything into the final, complete application. It provides the definitive version of every file, adds the remaining production touches, and walks you through a full end-to-end test of the entire system.

## 12.1 Final Project Structure

```
notesmith/
├── alembic/
│   ├── versions/
│   │   └── xxxx_create_users_and_notes_tables.py
│   ├── env.py
│   ├── script.py.mako
│   └── README
├── src/
│   └── notesmith/
│       ├── __init__.py
│       ├── main.py
│       ├── config.py
│       ├── database.py
│       ├── exceptions.py
│       ├── middleware.py
│       ├── auth/
│       │   ├── __init__.py
│       │   ├── router.py
│       │   ├── schemas.py
│       │   ├── models.py
│       │   ├── service.py
│       │   └── dependencies.py
│       ├── notes/
│       │   ├── __init__.py
│       │   ├── router.py
│       │   ├── schemas.py
│       │   ├── models.py
│       │   └── service.py
│       ├── ai/
│       │   ├── __init__.py
│       │   ├── router.py
│       │   ├── schemas.py
│       │   └── service.py
│       └── mcp/
│           ├── __init__.py
│           ├── client.py
│           ├── schemas.py
│           ├── router.py
│           └── server.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_auth.py
│   ├── test_notes.py
│   ├── test_ai.py
│   └── test_mcp.py
├── .env
├── alembic.ini
├── pyproject.toml
├── poetry.lock
└── README.md
```

## 12.2 Complete File Listing

Below is the definitive, production-ready version of every file. If you followed the tutorial incrementally, your files should match these. If anything differs, update your files to match.

### pyproject.toml

```toml
[project]
name = "notesmith"
version = "0.1.0"
description = "A notes API with AI capabilities"
requires-python = ">=3.10"
dependencies = [
    "fastapi[standard]",
    "sqlalchemy[asyncio]",
    "asyncpg",
    "alembic",
    "anthropic",
    "pyjwt",
    "pwdlib[argon2]",
    "pydantic-settings",
    "python-multipart",
    "fastmcp",
]

[tool.poetry]
package-mode = false

[tool.poetry.group.dev.dependencies]
pytest = "^8.0"
pytest-asyncio = "^1.0"
httpx = "^0.28"

[build-system]
requires = ["poetry-core>=2.0,<3.0"]
build-backend = "poetry.core.masonry.api"

[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = ["src"]
```

### .env

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/notesmith
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/notesmith_test
ANTHROPIC_API_KEY=sk-ant-your-key-here
JWT_SECRET_KEY=your-generated-hex-string
```

### src/notesmith/config.py

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    # Database
    database_url: str
    test_database_url: str | None = None  # Only needed when running tests

    # Authentication
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30

    # Anthropic
    anthropic_api_key: str

    # Application
    debug: bool = False


settings = Settings()
```

### src/notesmith/database.py

```python
from typing import AsyncGenerator

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from notesmith.config import settings

convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(AsyncAttrs, DeclarativeBase):
    metadata = MetaData(naming_convention=convention)


engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_size=5,
    max_overflow=10,
    pool_recycle=1800,
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

### src/notesmith/exceptions.py

```python
class NoteSmithError(Exception):
    def __init__(self, detail: str, status_code: int = 500):
        self.detail = detail
        self.status_code = status_code


class NotFoundError(NoteSmithError):
    def __init__(self, resource: str, resource_id: int | str):
        super().__init__(
            detail=f"{resource} with id '{resource_id}' not found",
            status_code=404,
        )


class ConflictError(NoteSmithError):
    def __init__(self, detail: str):
        super().__init__(detail=detail, status_code=409)
```

### src/notesmith/middleware.py

```python
import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("notesmith")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        start_time = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start_time) * 1000
        logger.info(
            "%s %s → %d (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response
```

### src/notesmith/main.py

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from notesmith.ai.router import router as ai_router
from notesmith.auth.router import router as auth_router
from notesmith.database import engine
from notesmith.exceptions import NoteSmithError
from notesmith.mcp.router import router as mcp_router
from notesmith.mcp.server import mcp as mcp_server
from notesmith.middleware import RequestLoggingMiddleware
from notesmith.notes.router import router as notes_router

# Create the MCP ASGI app. The path parameter sets the endpoint
# within the mounted sub-application (default is "/mcp").
mcp_app = mcp_server.http_app(path="/mcp")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Database startup
    async with engine.begin() as conn:
        await conn.run_sync(lambda conn: None)
    # MCP server startup — required for the mounted MCP app to function.
    # FastMCP's http_app() has an internal lifespan that initializes
    # session management and transport state. The FastMCP documentation
    # requires connecting it to the host application's lifespan.
    # We nest it inside ours so both lifecycles run.
    async with mcp_app.router.lifespan_context(mcp_app):
        yield
    # Database shutdown
    await engine.dispose()


app = FastAPI(
    title="NoteSmith API",
    version="0.1.0",
    description="A notes API with AI capabilities.",
    lifespan=lifespan,
)

# Middleware (applied in reverse order — last added runs first)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST API routers
app.include_router(auth_router, prefix="/api/v1")
app.include_router(notes_router, prefix="/api/v1")
app.include_router(ai_router, prefix="/api/v1")
app.include_router(mcp_router, prefix="/api/v1")

# MCP server mount — accessible at /mcp-server/mcp
app.mount("/mcp-server", mcp_app)


# Exception handlers
@app.exception_handler(NoteSmithError)
async def notesmith_error_handler(request: Request, exc: NoteSmithError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.get("/health")
async def health_check():
    return {"status": "ok"}
```

### src/notesmith/auth/models.py

```python
import datetime
from typing import TYPE_CHECKING

from sqlalchemy import String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from notesmith.database import Base

if TYPE_CHECKING:
    from notesmith.notes.models import Note


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

    notes: Mapped[list["Note"]] = relationship(
        back_populates="owner", lazy="selectin", cascade="all, delete-orphan"
    )
```

### src/notesmith/auth/schemas.py

```python
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserCreate(BaseModel):
    email: str = Field(max_length=320)
    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_-]+$")
    password: str = Field(min_length=8, max_length=128)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    username: str
    is_active: bool
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    user_id: int
```

### src/notesmith/auth/service.py

```python
from datetime import datetime, timedelta, timezone

import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from notesmith.auth.models import User
from notesmith.auth.schemas import UserCreate
from notesmith.config import settings

password_hash = PasswordHash.recommended()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return password_hash.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    return jwt.decode(
        token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm]
    )


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    stmt = select(User).where(User.email == email)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_user_by_username(session: AsyncSession, username: str) -> User | None:
    stmt = select(User).where(User.username == username)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_user_by_id(session: AsyncSession, user_id: int) -> User | None:
    stmt = select(User).where(User.id == user_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def create_user(session: AsyncSession, user_data: UserCreate) -> User:
    user = User(
        email=user_data.email,
        username=user_data.username,
        hashed_password=hash_password(user_data.password),
    )
    session.add(user)
    await session.flush()
    return user


async def authenticate_user(
    session: AsyncSession, username: str, password: str,
) -> User | None:
    user = await get_user_by_username(session, username)
    if user is None:
        password_hash.verify(password, password_hash.hash("dummy"))
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user
```

### src/notesmith/auth/dependencies.py

```python
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from sqlalchemy.ext.asyncio import AsyncSession

from notesmith.auth import service
from notesmith.auth.models import User
from notesmith.database import get_db

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = service.decode_access_token(token)
        user_id_str: str | None = payload.get("sub")
        if user_id_str is None:
            raise credentials_exception
        user_id = int(user_id_str)
    except (InvalidTokenError, ValueError):
        raise credentials_exception

    user = await service.get_user_by_id(db, user_id)
    if user is None:
        raise credentials_exception
    return user


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account",
        )
    return current_user


CurrentUser = Annotated[User, Depends(get_current_active_user)]
```

### src/notesmith/auth/router.py

```python
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from notesmith.auth import service
from notesmith.auth.dependencies import CurrentUser
from notesmith.auth.schemas import Token, UserCreate, UserResponse
from notesmith.database import get_db

router = APIRouter(prefix="/auth", tags=["auth"])
DB = Annotated[AsyncSession, Depends(get_db)]


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(user_data: UserCreate, db: DB):
    existing = await service.get_user_by_email(db, user_data.email)
    if existing:
        raise HTTPException(status_code=409, detail="A user with this email already exists")
    existing = await service.get_user_by_username(db, user_data.username)
    if existing:
        raise HTTPException(status_code=409, detail="A user with this username already exists")
    user = await service.create_user(db, user_data)
    return user


@router.post("/login", response_model=Token)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()], db: DB,
):
    user = await service.authenticate_user(db, form_data.username, form_data.password)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = service.create_access_token(subject=str(user.id))
    return Token(access_token=access_token)


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: CurrentUser):
    return current_user
```

### src/notesmith/notes/models.py

```python
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

    owner: Mapped["User"] = relationship(back_populates="notes")
```

### src/notesmith/notes/schemas.py

```python
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class NoteCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)
    is_pinned: bool = False


class NoteUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    content: str | None = Field(default=None, min_length=1)
    is_pinned: bool | None = None


class NoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    content: str
    is_pinned: bool
    summary: str | None
    owner_id: int
    created_at: datetime
    updated_at: datetime
```

### src/notesmith/notes/service.py

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from notesmith.notes.models import Note
from notesmith.notes.schemas import NoteCreate, NoteUpdate


async def create_note(
    session: AsyncSession, note_data: NoteCreate, owner_id: int,
) -> Note:
    note = Note(
        title=note_data.title,
        content=note_data.content,
        is_pinned=note_data.is_pinned,
        owner_id=owner_id,
    )
    session.add(note)
    await session.flush()
    return note


async def get_note_by_id(session: AsyncSession, note_id: int) -> Note | None:
    stmt = select(Note).where(Note.id == note_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_notes_by_owner(
    session: AsyncSession, owner_id: int, skip: int = 0, limit: int = 50,
) -> list[Note]:
    stmt = (
        select(Note)
        .where(Note.owner_id == owner_id)
        .order_by(Note.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def update_note(
    session: AsyncSession, note: Note, note_data: NoteUpdate,
) -> Note:
    update_fields = note_data.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        setattr(note, field, value)
    await session.flush()
    await session.refresh(note)
    return note


async def delete_note(session: AsyncSession, note: Note) -> None:
    await session.delete(note)
    await session.flush()
```

### src/notesmith/notes/router.py

```python
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from notesmith.auth.dependencies import CurrentUser
from notesmith.database import get_db
from notesmith.notes import service
from notesmith.notes.schemas import NoteCreate, NoteResponse, NoteUpdate

router = APIRouter(prefix="/notes", tags=["notes"])
DB = Annotated[AsyncSession, Depends(get_db)]


@router.post("/", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
async def create_note(note_data: NoteCreate, db: DB, current_user: CurrentUser):
    return await service.create_note(db, note_data, owner_id=current_user.id)


@router.get("/", response_model=list[NoteResponse])
async def list_notes(db: DB, current_user: CurrentUser, skip: int = 0, limit: int = 50):
    return await service.get_notes_by_owner(db, owner_id=current_user.id, skip=skip, limit=limit)


@router.get("/{note_id}", response_model=NoteResponse)
async def get_note(note_id: int, db: DB, current_user: CurrentUser):
    note = await service.get_note_by_id(db, note_id)
    if note is None or note.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


@router.patch("/{note_id}", response_model=NoteResponse)
async def update_note(note_id: int, note_data: NoteUpdate, db: DB, current_user: CurrentUser):
    note = await service.get_note_by_id(db, note_id)
    if note is None or note.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Note not found")
    return await service.update_note(db, note, note_data)


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(note_id: int, db: DB, current_user: CurrentUser):
    note = await service.get_note_by_id(db, note_id)
    if note is None or note.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Note not found")
    await service.delete_note(db, note)
    return None
```

### src/notesmith/ai/schemas.py

```python
from enum import Enum

from pydantic import BaseModel, Field


class AnalysisType(str, Enum):
    sentiment = "sentiment"
    key_topics = "key_topics"
    action_items = "action_items"


class SummarizeRequest(BaseModel):
    text: str = Field(min_length=10, description="The text to summarize.")


class SummarizeResponse(BaseModel):
    summary: str


class AnalyzeRequest(BaseModel):
    text: str = Field(min_length=10, description="The text to analyze.")
    analysis_type: AnalysisType


class AnalyzeResponse(BaseModel):
    analysis_type: str
    result: str


class NoteSummarizeResponse(BaseModel):
    note_id: int
    summary: str
```

### src/notesmith/ai/service.py

```python
from anthropic import AsyncAnthropic
from anthropic.types import TextBlock

from notesmith.config import settings

client = AsyncAnthropic(api_key=settings.anthropic_api_key)
MODEL = "claude-sonnet-4-20250514"


async def summarize_text(text: str) -> str:
    """Generate a concise summary of the provided text."""
    message = await client.messages.create(
        model=MODEL,
        max_tokens=512,
        system="You are a precise summarizer. Produce a clear, concise summary "
        "of the provided text. The summary should capture the key points "
        "in 2-4 sentences. Do not include preamble like 'Here is a summary'. "
        "Just provide the summary directly.",
        messages=[{"role": "user", "content": text}],
    )
    text_block = message.content[0]
    if not isinstance(text_block, TextBlock):
        raise ValueError("Unexpected response type from Anthropic API")
    return text_block.text


async def analyze_text(text: str, analysis_type: str) -> str:
    """Analyze text according to the specified analysis type."""
    prompts = {
        "sentiment": (
            "Analyze the sentiment of the following text. Categorize it as "
            "positive, negative, neutral, or mixed. Explain your reasoning "
            "in 2-3 sentences. Respond with a JSON object containing 'sentiment' "
            "(string) and 'explanation' (string) fields. Return only the JSON."
        ),
        "key_topics": (
            "Extract the key topics and themes from the following text. "
            "Respond with a JSON object containing a 'topics' field, which is "
            "an array of objects, each with 'topic' (string) and 'relevance' "
            "(string: 'high', 'medium', or 'low') fields. Return only the JSON."
        ),
        "action_items": (
            "Extract any action items, tasks, or to-dos from the following text. "
            "Respond with a JSON object containing an 'action_items' field, which "
            "is an array of strings. If there are no action items, return an empty "
            "array. Return only the JSON."
        ),
    }
    system_prompt = prompts.get(analysis_type)
    if system_prompt is None:
        raise ValueError(f"Unknown analysis type: {analysis_type}")

    message = await client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": text}],
    )
    text_block = message.content[0]
    if not isinstance(text_block, TextBlock):
        raise ValueError("Unexpected response type from Anthropic API")
    return text_block.text


async def stream_summarize(text: str):
    """Stream a summary of the provided text, yielding chunks as they arrive."""
    async with client.messages.stream(
        model=MODEL,
        max_tokens=1024,
        system="You are a precise summarizer. Produce a clear, detailed summary "
        "of the provided text. Cover all key points. Do not include "
        "preamble like 'Here is a summary'. Just provide the summary directly.",
        messages=[{"role": "user", "content": text}],
    ) as stream:
        async for text_chunk in stream.text_stream:
            yield text_chunk
```

### src/notesmith/ai/router.py

```python
import logging
from typing import Annotated

from anthropic import APIError
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from notesmith.ai import service as ai_service
from notesmith.ai.schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    NoteSummarizeResponse,
    SummarizeRequest,
    SummarizeResponse,
)
from notesmith.auth.dependencies import CurrentUser
from notesmith.database import get_db
from notesmith.notes import service as notes_service

logger = logging.getLogger("notesmith.ai")
router = APIRouter(prefix="/ai", tags=["ai"])
DB = Annotated[AsyncSession, Depends(get_db)]


@router.post("/summarize", response_model=SummarizeResponse)
async def summarize_text(request: SummarizeRequest, current_user: CurrentUser):
    try:
        summary = await ai_service.summarize_text(request.text)
    except APIError as e:
        logger.error("Anthropic API error: %s", e)
        raise HTTPException(status_code=502, detail="AI service temporarily unavailable")
    return SummarizeResponse(summary=summary)


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_text(request: AnalyzeRequest, current_user: CurrentUser):
    try:
        result = await ai_service.analyze_text(request.text, request.analysis_type.value)
    except APIError as e:
        logger.error("Anthropic API error: %s", e)
        raise HTTPException(status_code=502, detail="AI service temporarily unavailable")
    return AnalyzeResponse(analysis_type=request.analysis_type.value, result=result)


@router.post("/notes/{note_id}/summarize", response_model=NoteSummarizeResponse)
async def summarize_note(note_id: int, db: DB, current_user: CurrentUser):
    note = await notes_service.get_note_by_id(db, note_id)
    if note is None or note.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Note not found")
    try:
        summary = await ai_service.summarize_text(note.content)
    except APIError as e:
        logger.error("Anthropic API error for note %d: %s", note_id, e)
        raise HTTPException(status_code=502, detail="AI service temporarily unavailable")
    note.summary = summary
    await db.flush()
    return NoteSummarizeResponse(note_id=note.id, summary=summary)


@router.post("/summarize/stream")
async def summarize_text_stream(request: SummarizeRequest, current_user: CurrentUser):
    async def generate():
        try:
            async for chunk in ai_service.stream_summarize(request.text):
                yield chunk
        except APIError as e:
            logger.error("Anthropic API streaming error: %s", e)
            yield "\n\n[Error: AI service temporarily unavailable]"

    return StreamingResponse(generate(), media_type="text/plain")
```

### src/notesmith/mcp/client.py

```python
import logging

from fastmcp import Client
from mcp.types import TextContent

logger = logging.getLogger("notesmith.mcp")


def create_fetch_client() -> Client:
    """Create a FastMCP Client configured for the mcp-server-fetch server.

    The fetch server runs as a subprocess over STDIO transport.
    We use uvx to launch it in an isolated environment rather than
    installing it into our project's virtual environment. This avoids
    dependency conflicts — mcp-server-fetch pins httpx <0.28, while
    our project requires httpx >=0.28.1.
    """
    return Client(
        {
            "mcpServers": {
                "fetch": {
                    "command": "uvx",
                    "args": ["mcp-server-fetch"],
                }
            }
        }
    )


async def fetch_url(url: str, max_length: int = 50000) -> str:
    """Fetch a URL via the MCP fetch server and return its content as markdown.

    Each call opens a fresh connection to the fetch server subprocess.
    This is simpler than keeping a persistent connection and is
    acceptable for the infrequent nature of web fetching operations.

    Args:
        url: The URL to fetch.
        max_length: Maximum number of characters to return.

    Returns:
        The page content as markdown text.
    """
    client = create_fetch_client()
    async with client:
        result = await client.call_tool(
            "fetch_fetch",
            {"url": url, "max_length": max_length},
        )
        # result.content is a list of content blocks.
        # The fetch tool returns a single TextContent block.
        if not result.content:
            raise ValueError("Fetch server returned no content")
        text_block = result.content[0]
        if not isinstance(text_block, TextContent):
            raise ValueError("Fetch server returned non-text content")
        return text_block.text
```

### src/notesmith/mcp/schemas.py

```python
from pydantic import BaseModel, ConfigDict, Field
from datetime import datetime


class FetchToNoteRequest(BaseModel):
    url: str = Field(description="The URL to fetch and save as a note.")
    title: str | None = Field(
        default=None,
        max_length=200,
        description="Optional title for the note. If omitted, the URL is used.",
    )
    max_length: int = Field(
        default=50000,
        gt=0,
        le=100000,
        description="Maximum characters to fetch from the page.",
    )


class FetchToNoteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    content: str
    owner_id: int
    created_at: datetime


class FetchAndSummarizeRequest(BaseModel):
    url: str = Field(description="The URL to fetch and summarize.")
    max_length: int = Field(
        default=50000,
        gt=0,
        le=100000,
        description="Maximum characters to fetch from the page.",
    )


class FetchAndSummarizeResponse(BaseModel):
    url: str
    summary: str
```

### src/notesmith/mcp/router.py

```python
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from notesmith.ai import service as ai_service
from notesmith.auth.dependencies import CurrentUser
from notesmith.database import get_db
from notesmith.mcp import client as mcp_client
from notesmith.mcp.schemas import (
    FetchAndSummarizeRequest,
    FetchAndSummarizeResponse,
    FetchToNoteRequest,
    FetchToNoteResponse,
)
from notesmith.notes.models import Note

logger = logging.getLogger("notesmith.mcp")

router = APIRouter(prefix="/mcp", tags=["mcp"])

DB = Annotated[AsyncSession, Depends(get_db)]


@router.post("/fetch-to-note", response_model=FetchToNoteResponse, status_code=201)
async def fetch_to_note(
    request: FetchToNoteRequest,
    db: DB,
    current_user: CurrentUser,
):
    """Fetch a web page via the MCP fetch server and save it as a note."""
    try:
        content = await mcp_client.fetch_url(
            request.url, max_length=request.max_length
        )
    except Exception as e:
        logger.error("MCP fetch failed for %s: %s", request.url, e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch URL: {request.url}",
        )

    title = request.title or request.url[:200]

    note = Note(
        title=title,
        content=content,
        owner_id=current_user.id,
    )
    db.add(note)
    await db.flush()
    return note


@router.post("/fetch-and-summarize", response_model=FetchAndSummarizeResponse)
async def fetch_and_summarize(
    request: FetchAndSummarizeRequest,
    current_user: CurrentUser,
):
    """Fetch a web page and summarize it with Claude."""
    try:
        content = await mcp_client.fetch_url(
            request.url, max_length=request.max_length
        )
    except Exception as e:
        logger.error("MCP fetch failed for %s: %s", request.url, e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to fetch URL: {request.url}",
        )

    try:
        summary = await ai_service.summarize_text(content)
    except Exception as e:
        logger.error("Summarization failed for %s: %s", request.url, e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI summarization failed",
        )

    return FetchAndSummarizeResponse(url=request.url, summary=summary)
```

### src/notesmith/mcp/server.py

```python
from fastmcp import FastMCP

from notesmith.database import async_session_maker
from notesmith.notes import service as notes_service
from notesmith.notes.schemas import NoteCreate

mcp = FastMCP(
    "NoteSmith",
    instructions=(
        "NoteSmith is a notes API. Use these tools to list, retrieve, "
        "create, and search notes for a given user."
    ),
)


@mcp.tool
async def list_notes(owner_id: int, skip: int = 0, limit: int = 50) -> list[dict]:
    """List all notes for a user, ordered by creation date (newest first).

    Args:
        owner_id: The ID of the user whose notes to list.
        skip: Number of notes to skip (for pagination).
        limit: Maximum number of notes to return.
    """
    async with async_session_maker() as session:
        notes = await notes_service.get_notes_by_owner(
            session, owner_id, skip=skip, limit=limit
        )
        return [
            {
                "id": n.id,
                "title": n.title,
                "content": n.content[:200] + "..." if len(n.content) > 200 else n.content,
                "is_pinned": n.is_pinned,
                "created_at": n.created_at.isoformat(),
            }
            for n in notes
        ]


@mcp.tool
async def get_note(note_id: int) -> dict:
    """Get the full content of a specific note by its ID.

    Args:
        note_id: The ID of the note to retrieve.
    """
    async with async_session_maker() as session:
        note = await notes_service.get_note_by_id(session, note_id)
        if note is None:
            return {"error": f"Note {note_id} not found"}
        return {
            "id": note.id,
            "title": note.title,
            "content": note.content,
            "is_pinned": note.is_pinned,
            "summary": note.summary,
            "owner_id": note.owner_id,
            "created_at": note.created_at.isoformat(),
            "updated_at": note.updated_at.isoformat(),
        }


@mcp.tool
async def create_note(owner_id: int, title: str, content: str, is_pinned: bool = False) -> dict:
    """Create a new note for a user.

    Args:
        owner_id: The ID of the user who owns the note.
        title: The title of the note (max 200 characters).
        content: The content of the note.
        is_pinned: Whether to pin the note (default: false).
    """
    note_data = NoteCreate(title=title, content=content, is_pinned=is_pinned)
    async with async_session_maker() as session:
        note = await notes_service.create_note(session, note_data, owner_id)
        await session.commit()
        return {
            "id": note.id,
            "title": note.title,
            "content": note.content,
            "is_pinned": note.is_pinned,
            "owner_id": note.owner_id,
            "created_at": note.created_at.isoformat(),
        }


@mcp.tool
async def search_notes(owner_id: int, query: str) -> list[dict]:
    """Search notes by keyword in title or content.

    Args:
        owner_id: The ID of the user whose notes to search.
        query: The search term to look for in note titles and content.
    """
    from sqlalchemy import select, or_

    from notesmith.notes.models import Note

    async with async_session_maker() as session:
        stmt = (
            select(Note)
            .where(
                Note.owner_id == owner_id,
                or_(
                    Note.title.ilike(f"%{query}%"),
                    Note.content.ilike(f"%{query}%"),
                ),
            )
            .order_by(Note.created_at.desc())
            .limit(20)
        )
        result = await session.execute(stmt)
        notes = result.scalars().all()
        return [
            {
                "id": n.id,
                "title": n.title,
                "content": n.content[:200] + "..." if len(n.content) > 200 else n.content,
                "is_pinned": n.is_pinned,
                "created_at": n.created_at.isoformat(),
            }
            for n in notes
        ]
```

### alembic/env.py

```python
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy import pool

from notesmith.config import settings
from notesmith.database import Base

import notesmith.auth.models  # noqa: F401
import notesmith.notes.models  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

### tests/conftest.py

```python
from typing import AsyncGenerator
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from notesmith.auth.models import User
from notesmith.auth.service import create_access_token, hash_password
from notesmith.config import settings
from notesmith.database import Base, get_db
from notesmith.main import app

if settings.test_database_url is None:
    raise RuntimeError(
        "TEST_DATABASE_URL is not set. Add it to your .env file. "
        "Example: TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres"
        "@localhost:5432/notesmith_test"
    )

test_engine = create_async_engine(
    settings.test_database_url, echo=False, poolclass=NullPool,
)
test_session_maker = async_sessionmaker(
    test_engine, class_=AsyncSession, expire_on_commit=False,
)


@pytest.fixture(autouse=True)
async def setup_database():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with test_session_maker() as session:
        yield session


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def test_user(db_session: AsyncSession) -> User:
    user = User(
        email="test@example.com",
        username="testuser",
        hashed_password=hash_password("testpassword123"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def auth_headers(test_user: User) -> dict[str, str]:
    token = create_access_token(subject=str(test_user.id))
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def patch_mcp_server_db():
    """Redirect MCP server tools to the test database.

    MCP tools use async_session_maker directly (they bypass FastAPI's
    dependency injection). Without this patch, they connect to the
    production database, which causes foreign key violations (the test
    user does not exist there) and event loop mismatches.
    """
    with patch("notesmith.mcp.server.async_session_maker", test_session_maker):
        yield
```

### tests/test_auth.py

```python
from httpx import AsyncClient


async def test_register_user(client: AsyncClient):
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "new@example.com",
            "username": "newuser",
            "password": "securepassword123",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "new@example.com"
    assert data["username"] == "newuser"
    assert "hashed_password" not in data


async def test_register_duplicate_email(client: AsyncClient, test_user):
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "test@example.com",
            "username": "different",
            "password": "securepassword123",
        },
    )
    assert response.status_code == 409


async def test_login_success(client: AsyncClient, test_user):
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": "testuser", "password": "testpassword123"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


async def test_login_wrong_password(client: AsyncClient, test_user):
    response = await client.post(
        "/api/v1/auth/login",
        data={"username": "testuser", "password": "wrongpassword"},
    )
    assert response.status_code == 401


async def test_get_current_user(client: AsyncClient, auth_headers):
    response = await client.get("/api/v1/auth/me", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "testuser"


async def test_get_current_user_no_token(client: AsyncClient):
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401
```

### tests/test_notes.py

```python
from httpx import AsyncClient


async def test_create_note(client: AsyncClient, auth_headers):
    response = await client.post(
        "/api/v1/notes/",
        headers=auth_headers,
        json={"title": "Test note", "content": "This is test content."},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Test note"
    assert data["content"] == "This is test content."
    assert data["is_pinned"] is False
    assert "id" in data
    assert "created_at" in data


async def test_create_note_unauthenticated(client: AsyncClient):
    response = await client.post(
        "/api/v1/notes/",
        json={"title": "Test note", "content": "Content"},
    )
    assert response.status_code == 401


async def test_create_note_invalid_data(client: AsyncClient, auth_headers):
    response = await client.post(
        "/api/v1/notes/",
        headers=auth_headers,
        json={"title": "Test note"},
    )
    assert response.status_code == 422


async def test_list_notes(client: AsyncClient, auth_headers):
    await client.post(
        "/api/v1/notes/",
        headers=auth_headers,
        json={"title": "Note 1", "content": "Content 1"},
    )
    await client.post(
        "/api/v1/notes/",
        headers=auth_headers,
        json={"title": "Note 2", "content": "Content 2"},
    )

    response = await client.get("/api/v1/notes/", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2


async def test_get_note(client: AsyncClient, auth_headers):
    create_response = await client.post(
        "/api/v1/notes/",
        headers=auth_headers,
        json={"title": "Test", "content": "Content"},
    )
    note_id = create_response.json()["id"]

    response = await client.get(f"/api/v1/notes/{note_id}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["title"] == "Test"


async def test_get_nonexistent_note(client: AsyncClient, auth_headers):
    response = await client.get("/api/v1/notes/99999", headers=auth_headers)
    assert response.status_code == 404


async def test_update_note(client: AsyncClient, auth_headers):
    create_response = await client.post(
        "/api/v1/notes/",
        headers=auth_headers,
        json={"title": "Original", "content": "Original content"},
    )
    note_id = create_response.json()["id"]

    response = await client.patch(
        f"/api/v1/notes/{note_id}",
        headers=auth_headers,
        json={"title": "Updated"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Updated"
    assert data["content"] == "Original content"


async def test_delete_note(client: AsyncClient, auth_headers):
    create_response = await client.post(
        "/api/v1/notes/",
        headers=auth_headers,
        json={"title": "To delete", "content": "Will be deleted"},
    )
    note_id = create_response.json()["id"]

    response = await client.delete(f"/api/v1/notes/{note_id}", headers=auth_headers)
    assert response.status_code == 204

    response = await client.get(f"/api/v1/notes/{note_id}", headers=auth_headers)
    assert response.status_code == 404
```

### tests/test_ai.py

```python
from unittest.mock import AsyncMock, MagicMock, patch

from anthropic.types import TextBlock
from httpx import AsyncClient


def _mock_message(text: str):
    """Create a mock Anthropic message response.

    Uses the real TextBlock class from the Anthropic SDK so that
    isinstance() checks in the service layer pass correctly.
    """
    block = TextBlock(type="text", text=text)
    message = MagicMock()
    message.content = [block]
    return message


@patch("notesmith.ai.service.client")
async def test_summarize_text(mock_client, client: AsyncClient, auth_headers):
    mock_client.messages.create = AsyncMock(
        return_value=_mock_message("This is a summary of the text.")
    )

    response = await client.post(
        "/api/v1/ai/summarize",
        headers=auth_headers,
        json={"text": "A long piece of text that needs to be summarized for testing purposes."},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["summary"] == "This is a summary of the text."

    mock_client.messages.create.assert_called_once()
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "claude-sonnet-4-20250514"


@patch("notesmith.ai.service.client")
async def test_analyze_sentiment(mock_client, client: AsyncClient, auth_headers):
    mock_client.messages.create = AsyncMock(
        return_value=_mock_message('{"sentiment": "positive", "explanation": "The text expresses enthusiasm."}')
    )

    response = await client.post(
        "/api/v1/ai/analyze",
        headers=auth_headers,
        json={
            "text": "I absolutely love this product, it changed my life!",
            "analysis_type": "sentiment",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["analysis_type"] == "sentiment"


@patch("notesmith.ai.service.client")
async def test_summarize_note(mock_client, client: AsyncClient, auth_headers):
    mock_client.messages.create = AsyncMock(
        return_value=_mock_message("Note summary here.")
    )

    create_response = await client.post(
        "/api/v1/notes/",
        headers=auth_headers,
        json={"title": "Test note", "content": "Content to be summarized by AI."},
    )
    note_id = create_response.json()["id"]

    response = await client.post(
        f"/api/v1/ai/notes/{note_id}/summarize",
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["note_id"] == note_id
    assert data["summary"] == "Note summary here."


async def test_summarize_unauthenticated(client: AsyncClient):
    response = await client.post(
        "/api/v1/ai/summarize",
        json={"text": "Some text to summarize for this test."},
    )
    assert response.status_code == 401


async def test_analyze_invalid_type(client: AsyncClient, auth_headers):
    response = await client.post(
        "/api/v1/ai/analyze",
        headers=auth_headers,
        json={
            "text": "Some text for analysis purposes here.",
            "analysis_type": "invalid_type",
        },
    )
    assert response.status_code == 422
```

### tests/test_mcp.py

```python
from unittest.mock import AsyncMock, MagicMock, patch

from anthropic.types import TextBlock
from fastmcp import Client
from httpx import AsyncClient
from mcp.types import TextContent
from sqlalchemy.ext.asyncio import AsyncSession

from notesmith.mcp.server import mcp as mcp_server


# ----------------------------------------------------------------
# MCP Server Tests (in-memory transport, no HTTP)
# ----------------------------------------------------------------


async def test_mcp_server_list_tools():
    """Verify the MCP server exposes the expected tools."""
    async with Client(mcp_server) as client:
        tools = await client.list_tools()
        tool_names = {t.name for t in tools}
        assert "list_notes" in tool_names
        assert "get_note" in tool_names
        assert "create_note" in tool_names
        assert "search_notes" in tool_names


async def test_mcp_server_create_and_get_note(
    db_session: AsyncSession, patch_mcp_server_db,
):
    """Test creating a note via MCP and retrieving it."""
    from notesmith.auth.models import User
    from notesmith.auth.service import hash_password

    user = User(
        email="mcpuser@example.com",
        username="mcpuser",
        hashed_password=hash_password("testpassword123"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    async with Client(mcp_server) as client:
        # Create a note
        create_result = await client.call_tool(
            "create_note",
            {
                "owner_id": user.id,
                "title": "MCP Test Note",
                "content": "Created via MCP tools.",
            },
        )
        note_data = create_result.data
        assert note_data["title"] == "MCP Test Note"
        assert "id" in note_data

        # Retrieve the same note
        get_result = await client.call_tool(
            "get_note", {"note_id": note_data["id"]}
        )
        retrieved = get_result.data
        assert retrieved["title"] == "MCP Test Note"
        assert retrieved["content"] == "Created via MCP tools."


async def test_mcp_server_get_nonexistent_note(patch_mcp_server_db):
    """Test that get_note returns an error for missing notes."""
    async with Client(mcp_server) as client:
        result = await client.call_tool("get_note", {"note_id": 99999})
        assert "error" in result.data


# ----------------------------------------------------------------
# MCP Client Router Tests (REST API endpoints)
# ----------------------------------------------------------------


@patch("notesmith.mcp.client.create_fetch_client")
async def test_fetch_to_note(
    mock_create_client, client: AsyncClient, auth_headers, db_session,
):
    """Test the fetch-to-note endpoint with a mocked MCP client."""
    mock_mcp = AsyncMock()
    mock_content = TextContent(type="text", text="# Example Page\n\nThis is the fetched content.")
    mock_result = MagicMock()
    mock_result.content = [mock_content]
    mock_mcp.call_tool = AsyncMock(return_value=mock_result)
    mock_mcp.__aenter__ = AsyncMock(return_value=mock_mcp)
    mock_mcp.__aexit__ = AsyncMock(return_value=False)
    mock_create_client.return_value = mock_mcp

    response = await client.post(
        "/api/v1/mcp/fetch-to-note",
        headers=auth_headers,
        json={"url": "https://example.com", "title": "Example"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["title"] == "Example"
    assert "fetched content" in data["content"]


@patch("notesmith.ai.service.client")
@patch("notesmith.mcp.client.create_fetch_client")
async def test_fetch_and_summarize(
    mock_create_client,
    mock_ai_client,
    client: AsyncClient,
    auth_headers,
):
    """Test the fetch-and-summarize endpoint with mocked MCP and AI clients."""
    mock_mcp = AsyncMock()
    mock_content = TextContent(type="text", text="Long article content about FastAPI and Python.")
    mock_result = MagicMock()
    mock_result.content = [mock_content]
    mock_mcp.call_tool = AsyncMock(return_value=mock_result)
    mock_mcp.__aenter__ = AsyncMock(return_value=mock_mcp)
    mock_mcp.__aexit__ = AsyncMock(return_value=False)
    mock_create_client.return_value = mock_mcp

    block = TextBlock(type="text", text="A concise summary of the article.")
    message = MagicMock()
    message.content = [block]
    mock_ai_client.messages.create = AsyncMock(return_value=message)

    response = await client.post(
        "/api/v1/mcp/fetch-and-summarize",
        headers=auth_headers,
        json={"url": "https://example.com/article"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["url"] == "https://example.com/article"
    assert data["summary"] == "A concise summary of the article."


async def test_fetch_to_note_unauthenticated(client: AsyncClient):
    """MCP endpoints require authentication."""
    response = await client.post(
        "/api/v1/mcp/fetch-to-note",
        json={"url": "https://example.com"},
    )
    assert response.status_code == 401
```

## 12.3 End-to-End Verification

Follow these steps to verify the complete system works.

### Step 1: Database Setup

Ensure both the development and test databases exist. If you are using a local PostgreSQL instance:

```bash
createdb notesmith 2>/dev/null || true
createdb notesmith_test 2>/dev/null || true
```

If you are using a remote instance via DBeaver, create both databases through the SQL editor:

```sql
CREATE DATABASE notesmith;
CREATE DATABASE notesmith_test;
```

Then run migrations against the development database:

```bash
alembic upgrade head
```

### Step 2: Start the Server

```bash
uvicorn src.notesmith.main:app --reload --port 8000
```

### Step 3: Register and Login

```bash
# Register
curl -s -X POST http://127.0.0.1:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "alice@example.com", "username": "alice", "password": "securepassword123"}' | python -m json.tool

# Login and capture token
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -d "username=alice&password=securepassword123" | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

echo "Token: $TOKEN"
```

### Step 4: CRUD Notes

```bash
# Create notes
curl -s -X POST http://127.0.0.1:8000/api/v1/notes/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Project Ideas",
    "content": "Build a REST API with FastAPI. Integrate Claude for AI features. Add PostgreSQL for persistence. Write comprehensive tests. Deploy to production with Docker."
  }' | python -m json.tool

curl -s -X POST http://127.0.0.1:8000/api/v1/notes/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Meeting Notes",
    "content": "Discussed Q2 roadmap. Team agreed to prioritize API stability over new features. Action items: review security audit results by Friday, schedule load testing for next sprint, update documentation for the new authentication flow.",
    "is_pinned": true
  }' | python -m json.tool

# List all notes
curl -s http://127.0.0.1:8000/api/v1/notes/ \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool

# Update a note
curl -s -X PATCH http://127.0.0.1:8000/api/v1/notes/1 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title": "Project Ideas (Updated)"}' | python -m json.tool
```

### Step 5: AI Features

```bash
# Summarize arbitrary text
curl -s -X POST http://127.0.0.1:8000/api/v1/ai/summarize \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "FastAPI is a modern web framework for building APIs with Python 3.10+ based on standard type hints. It provides automatic data validation, serialization, and interactive API documentation. The framework achieves high performance through Starlette and Pydantic, making it one of the fastest Python frameworks available."}' | python -m json.tool

# Analyze sentiment
curl -s -X POST http://127.0.0.1:8000/api/v1/ai/analyze \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "The meeting was extremely productive and everyone left feeling motivated about the direction.", "analysis_type": "sentiment"}' | python -m json.tool

# Extract action items
curl -s -X POST http://127.0.0.1:8000/api/v1/ai/analyze \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "Discussed Q2 roadmap. Team agreed to prioritize API stability over new features. Action items: review security audit results by Friday, schedule load testing for next sprint, update documentation for the new authentication flow.", "analysis_type": "action_items"}' | python -m json.tool

# Summarize a note and store the result (replace 2 with your note ID)
curl -s -X POST http://127.0.0.1:8000/api/v1/ai/notes/2/summarize \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool

# Stream a summary
curl -X POST http://127.0.0.1:8000/api/v1/ai/summarize/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "FastAPI is a modern web framework for building APIs with Python 3.10+ based on standard type hints. It provides automatic data validation, serialization, and interactive API documentation."}'
```

### Step 6: MCP Features

```bash
# Fetch a web page and save it as a note
curl -s -X POST http://127.0.0.1:8000/api/v1/mcp/fetch-to-note \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "title": "Example.com"}' | python -m json.tool

# Fetch a page and summarize it with Claude
curl -s -X POST http://127.0.0.1:8000/api/v1/mcp/fetch-and-summarize \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}' | python -m json.tool
```

Test the MCP server with an external client:

```bash
python -c "
import asyncio
from fastmcp import Client

async def main():
    async with Client('http://127.0.0.1:8000/mcp-server/mcp') as client:
        tools = await client.list_tools()
        print('Available MCP tools:')
        for t in tools:
            print(f'  {t.name}')

        result = await client.call_tool('list_notes', {'owner_id': 1})
        print(f'\nNotes: {result.data}')

asyncio.run(main())
"
```

### Step 7: Run Tests

```bash
pytest -v
```

All tests should pass.

## 12.4 API Endpoint Summary

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | No | Health check |
| POST | `/api/v1/auth/register` | No | Create user account |
| POST | `/api/v1/auth/login` | No | Get JWT token |
| GET | `/api/v1/auth/me` | Yes | Current user profile |
| POST | `/api/v1/notes/` | Yes | Create a note |
| GET | `/api/v1/notes/` | Yes | List user's notes |
| GET | `/api/v1/notes/{id}` | Yes | Get a single note |
| PATCH | `/api/v1/notes/{id}` | Yes | Update a note |
| DELETE | `/api/v1/notes/{id}` | Yes | Delete a note |
| POST | `/api/v1/ai/summarize` | Yes | Summarize arbitrary text |
| POST | `/api/v1/ai/summarize/stream` | Yes | Stream a summary |
| POST | `/api/v1/ai/analyze` | Yes | Analyze text (sentiment, topics, actions) |
| POST | `/api/v1/ai/notes/{id}/summarize` | Yes | Summarize a note and save the result |
| POST | `/api/v1/mcp/fetch-to-note` | Yes | Fetch a URL and save as a note |
| POST | `/api/v1/mcp/fetch-and-summarize` | Yes | Fetch a URL and summarize with Claude |
| — | `/mcp-server/mcp` | No | MCP server (tools: list, get, create, search notes) |

## 12.5 What This Tutorial Covered

Across 12 chapters, you learned:

1. **Poetry** — Project creation, PEP 621 metadata, dependency management, virtual environments, lock files.
2. **FastAPI** — Routing, path/query parameters, request bodies, status codes, response models, APIRouter.
3. **Pydantic v2** — Model definition, field constraints, validators, ConfigDict, serialization methods, separate input/output schemas, settings management.
4. **Async SQLAlchemy 2.0** — Async engine, session factory, DeclarativeBase, mapped_column with Mapped[] annotations, relationships, eager loading.
5. **Alembic** — Async initialization, env.py configuration, autogenerated migrations, migration workflow.
6. **CRUD patterns** — Service layer, select() API, flush vs commit, session.refresh for server-side values, partial updates with exclude_unset.
7. **JWT authentication** — Password hashing (pwdlib/Argon2), token creation/verification (PyJWT), OAuth2PasswordBearer, dependency chain for current_user, timing attack prevention.
8. **Dependency injection** — Generator dependencies with yield, caching, class-based dependencies, middleware (CORS, request logging), custom exception handling.
9. **Anthropic SDK** — AsyncAnthropic client, Messages API, system prompts, TextBlock type checking, streaming responses, error handling for external services.
10. **Testing** — pytest-asyncio configuration, httpx AsyncClient with ASGITransport, dependency overrides, PostgreSQL test database, mock fixtures for external APIs.
11. **MCP** — FastMCP client (STDIO transport, `uvx` for dependency isolation), FastMCP server (tool registration from type hints/docstrings), mounting on FastAPI with lifespan nesting, session factory patching for test isolation.

## 12.6 Where to Go from Here

This tutorial built a solid foundation. Here are natural next steps:

- **Docker** — Containerize the application with a `Dockerfile` and `docker-compose.yml` for PostgreSQL.
- **Rate limiting** — Add per-user rate limits to the AI endpoints using `slowapi` or custom middleware.
- **Pagination** — Replace the simple skip/limit with cursor-based pagination for better performance at scale.
- **Background tasks** — Use FastAPI's `BackgroundTasks` or Celery for long-running AI operations.
- **Refresh tokens** — Add a token refresh flow for longer sessions without re-entering credentials.
- **Logging and monitoring** — Structured logging with `structlog`, metrics with Prometheus.
- **CI/CD** — GitHub Actions pipeline running tests, linting, and deployment.
- **Advanced MCP** — Add OAuth authentication to the MCP server, deploy to Prefect Horizon, or connect additional MCP servers (filesystem, memory, git).
- **Frontend** — Build a frontend with Svelte 5 and SvelteKit to consume this API.