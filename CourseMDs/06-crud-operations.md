# Chapter 6: CRUD Operations and the Service Layer

This chapter builds the database interaction layer: writing async queries with SQLAlchemy 2.0's `select()` API, organizing logic into service modules, and connecting services to FastAPI endpoints through dependency injection.

## 6.1 The select() API

SQLAlchemy 2.0 replaced the legacy `session.query(Model)` pattern with explicit `select()` statements. All queries follow this structure:

```python
from sqlalchemy import select

# Build a statement
stmt = select(Note).where(Note.owner_id == user_id)

# Execute it
result = await session.execute(stmt)

# Extract results
notes = result.scalars().all()
```

The key methods:

| Method | Returns |
|--------|---------|
| `result.scalars().all()` | List of model instances |
| `result.scalars().first()` | First instance or `None` |
| `result.scalars().one()` | Exactly one instance (raises if 0 or 2+) |
| `result.scalars().one_or_none()` | One instance or `None` (raises if 2+) |
| `result.scalar_one_or_none()` | Same as above but for single-column queries |

**Do not use `session.query()`** — it is the SQLAlchemy 1.x API and does not work with async sessions.

## 6.2 Note Schemas

Before writing the service layer, define the Pydantic schemas for notes. Open `src/notesmith/notes/schemas.py`:

```python
# src/notesmith/notes/schemas.py
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

## 6.3 The Notes Service

The service layer contains all database logic. Endpoints call service functions — they do not contain SQL themselves. This separation keeps routes thin and makes the database logic testable independently.

Open `src/notesmith/notes/service.py`:

```python
# src/notesmith/notes/service.py
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from notesmith.notes.models import Note
from notesmith.notes.schemas import NoteCreate, NoteUpdate


async def create_note(
    session: AsyncSession,
    note_data: NoteCreate,
    owner_id: int,
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


async def get_note_by_id(
    session: AsyncSession,
    note_id: int,
) -> Note | None:
    stmt = select(Note).where(Note.id == note_id)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def get_notes_by_owner(
    session: AsyncSession,
    owner_id: int,
    skip: int = 0,
    limit: int = 50,
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
    session: AsyncSession,
    note: Note,
    note_data: NoteUpdate,
) -> Note:
    update_fields = note_data.model_dump(exclude_unset=True)
    for field, value in update_fields.items():
        setattr(note, field, value)
    await session.flush()
    await session.refresh(note)
    return note


async def delete_note(
    session: AsyncSession,
    note: Note,
) -> None:
    await session.delete(note)
    await session.flush()
```

Key patterns to understand:

**`session.add(note)`** — Adds the new object to the session's identity map. It does not hit the database yet.

**`await session.flush()`** — Sends pending changes (INSERTs, UPDATEs, DELETEs) to the database but does **not** commit the transaction. The actual `commit()` happens in the `get_db` dependency (from Chapter 4) after the endpoint returns successfully. Flushing is useful because it populates server-generated fields (like `id` and `created_at`) so the function can return a fully-populated object.

**`await session.refresh(note)`** — Reloads all attributes of the object from the database. This is necessary in `update_note` because the `updated_at` column uses `onupdate=func.now()`, which is set server-side during the UPDATE. After the flush, SQLAlchemy marks `updated_at` as expired (it knows the database changed it, but does not know the new value). If FastAPI then tries to serialize the object and reads `updated_at`, SQLAlchemy would attempt an implicit lazy load — which fails in async context with a `MissingGreenlet` error. The explicit `refresh()` fetches the current value so serialization works. This is not needed for `create_note` because PostgreSQL's `INSERT ... RETURNING` clause returns server-generated values inline with the insert.

**`model_dump(exclude_unset=True)`** — Returns only the fields the client explicitly included in the request. If the client sends `{"title": "New title"}`, this returns `{"title": "New title"}` — not `{"title": "New title", "content": None, "is_pinned": None}`. This is how partial updates work correctly without overwriting existing values with `None`.

**`setattr(note, field, value)`** — Dynamically sets attributes on the SQLAlchemy model. Combined with `exclude_unset`, this updates only the fields the client changed.

## 6.4 The Notes Router

Now wire the service to HTTP endpoints. Open `src/notesmith/notes/router.py`:

```python
# src/notesmith/notes/router.py
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from notesmith.database import get_db
from notesmith.notes import service
from notesmith.notes.schemas import NoteCreate, NoteResponse, NoteUpdate

router = APIRouter(prefix="/notes", tags=["notes"])

# Type alias for the database session dependency
DB = Annotated[AsyncSession, Depends(get_db)]

# Placeholder: we will replace this with real auth in Chapter 7
TEMP_USER_ID = 1


@router.post("/", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
async def create_note(note_data: NoteCreate, db: DB):
    note = await service.create_note(db, note_data, owner_id=TEMP_USER_ID)
    return note


@router.get("/", response_model=list[NoteResponse])
async def list_notes(db: DB, skip: int = 0, limit: int = 50):
    notes = await service.get_notes_by_owner(db, owner_id=TEMP_USER_ID, skip=skip, limit=limit)
    return notes


@router.get("/{note_id}", response_model=NoteResponse)
async def get_note(note_id: int, db: DB):
    note = await service.get_note_by_id(db, note_id)
    if note is None or note.owner_id != TEMP_USER_ID:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


@router.patch("/{note_id}", response_model=NoteResponse)
async def update_note(note_id: int, note_data: NoteUpdate, db: DB):
    note = await service.get_note_by_id(db, note_id)
    if note is None or note.owner_id != TEMP_USER_ID:
        raise HTTPException(status_code=404, detail="Note not found")
    updated = await service.update_note(db, note, note_data)
    return updated


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(note_id: int, db: DB):
    note = await service.get_note_by_id(db, note_id)
    if note is None or note.owner_id != TEMP_USER_ID:
        raise HTTPException(status_code=404, detail="Note not found")
    await service.delete_note(db, note)
    return None
```

Key points:

**`Annotated[AsyncSession, Depends(get_db)]`** — This is a type alias. It tells FastAPI: "This parameter is an `AsyncSession` obtained by calling `get_db`." Using `Annotated` avoids repeating `Depends(get_db)` on every parameter.

**`response_model=NoteResponse`** — FastAPI serializes the return value through this Pydantic model. Since `NoteResponse` has `from_attributes=True`, it can read attributes from the SQLAlchemy `Note` instance directly. Fields not listed in `NoteResponse` (like `hashed_password` on User) are excluded.

**`TEMP_USER_ID = 1`** — A placeholder until we implement authentication in Chapter 7. We will replace this with the authenticated user's ID.

**Ownership check** — `note.owner_id != TEMP_USER_ID` prevents users from accessing other users' notes. We return 404 (not 403) to avoid leaking information about whether a note exists.

## 6.5 Register the Router

Update `main.py` to include the notes router:

```python
# src/notesmith/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI

import notesmith.auth.models  # noqa: F401  — registers User with Base
from notesmith.database import engine
from notesmith.notes.router import router as notes_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(lambda conn: None)
    yield
    await engine.dispose()


app = FastAPI(
    title="NoteSmith API",
    version="0.1.0",
    description="A notes API with AI capabilities.",
    lifespan=lifespan,
)

app.include_router(notes_router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    return {"status": "ok"}
```

The `import notesmith.auth.models` line is necessary because the `Note` model's relationship references `"User"` as a string. SQLAlchemy resolves that string by looking up registered model classes in `Base`'s mapper registry. If `User` has not been imported (and therefore registered) by the time SQLAlchemy resolves the relationship, it will fail with a mapper initialization error. The notes router import chain pulls in `Note` but not `User`, so the explicit import is required. In Chapter 7, the auth router's import chain will handle this naturally, but until then, we need it here.

## 6.6 Test the Endpoints

Before testing, you need a user in the database (since notes require an `owner_id`). Run this quick insert in DBeaver:

```SQL
INSERT INTO users (email, username, hashed_password, is_active)
VALUES ('test@example.com', 'testuser', 'placeholder', true);
```

Start the server:

```bash
uvicorn src.notesmith.main:app --reload --port 8000
```

Create a note:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/notes/ \
  -H "Content-Type: application/json" \
  -d '{"title": "My first note", "content": "Hello from NoteSmith!"}' | python -m json.tool
```

List notes:

```bash
curl http://127.0.0.1:8000/api/v1/notes/ | python -m json.tool
```

Update a note (assuming id=1):

```bash
curl -X PATCH http://127.0.0.1:8000/api/v1/notes/1 \
  -H "Content-Type: application/json" \
  -d '{"title": "Updated title"}' | python -m json.tool
```

Delete a note:

```bash
curl -X DELETE http://127.0.0.1:8000/api/v1/notes/1 -v
```

You should see a `204 No Content` response.

You can also test interactively in the Swagger UI at `http://127.0.0.1:8000/docs`.

## 6.7 Eager Loading and the N+1 Problem

When your endpoint returns a list of notes and the `NoteResponse` schema includes a relationship (like `owner`), SQLAlchemy would issue a separate query for each note's owner. This is the **N+1 problem**: 1 query for notes + N queries for owners.

We configured `lazy="selectin"` on the `User.notes` relationship in Chapter 4, which tells SQLAlchemy to load related objects with a single `SELECT ... WHERE id IN (...)` query. For the Note → User direction, if you ever need to include owner data in note responses, add `selectinload` to the query:

```python
from sqlalchemy.orm import selectinload

stmt = (
    select(Note)
    .where(Note.owner_id == owner_id)
    .options(selectinload(Note.owner))
)
```

The `options()` method on a select statement lets you override the default loading strategy per query. Common strategies:

- **`selectinload()`** — One additional `SELECT ... IN (...)` query. Best for one-to-many relationships.
- **`joinedload()`** — Uses a JOIN. Best for many-to-one relationships (loading the "one" side).
- **`lazyload()`** — Load on access. Does not work in async (raises `MissingGreenlet`).

---

Proceed to [Chapter 7: JWT Authentication](./07-authentication.md).
