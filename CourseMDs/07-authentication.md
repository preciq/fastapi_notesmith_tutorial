# Chapter 7: JWT Authentication

This chapter implements user registration, login, and JWT-protected endpoints using **PyJWT** for token handling and **pwdlib** for password hashing. These libraries replace the legacy passlib and python-jose stack that appears in older tutorials.

## 7.1 How JWT Authentication Works

The flow is:

1. **Register** — The client sends a username, email, and password. The server hashes the password and stores the user.
2. **Login** — The client sends credentials. The server verifies the password, then generates a **JSON Web Token** (JWT) containing the user's identity and an expiration time.
3. **Authenticated requests** — The client includes the JWT in the `Authorization: Bearer <token>` header. The server decodes the token, extracts the user identity, and loads the user from the database.

The JWT itself is a base64-encoded JSON string with three parts: header (algorithm), payload (your data + expiration), and signature (cryptographic proof that the token was not tampered with). The server signs tokens with a secret key that only it knows.

## 7.2 Password Hashing with pwdlib

Password hashing is a one-way transformation. You store the hash, not the password. When a user logs in, you hash the provided password and compare it to the stored hash.

pwdlib defaults to **Argon2**, which is the current recommendation from OWASP for password hashing (preferred over bcrypt for new projects).

Create the auth service. Open `src/notesmith/auth/service.py`:

```python
# src/notesmith/auth/service.py
from datetime import datetime, timedelta, timezone

import jwt
from jwt.exceptions import InvalidTokenError
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from notesmith.auth.models import User
from notesmith.auth.schemas import UserCreate
from notesmith.config import settings

# Password hashing instance — uses Argon2 by default
password_hash = PasswordHash.recommended()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check a plaintext password against a stored hash."""
    return password_hash.verify(plain_password, hashed_password)


def hash_password(password: str) -> str:
    """Hash a plaintext password for storage."""
    return password_hash.hash(password)


def create_access_token(subject: str, expires_delta: timedelta | None = None) -> str:
    """Create a signed JWT token.

    Args:
        subject: The token subject — typically the user's ID as a string.
        expires_delta: How long the token is valid. Defaults to the
            configured access_token_expire_minutes.
    """
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.access_token_expire_minutes)
    )
    payload = {
        "sub": subject,
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """Decode and verify a JWT token. Raises InvalidTokenError on failure."""
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
    session: AsyncSession, username: str, password: str
) -> User | None:
    """Verify credentials. Returns the User if valid, None otherwise.

    To prevent timing attacks, we always run the password verification
    even if the user does not exist. This ensures the response time is
    constant regardless of whether the username is valid.
    """
    user = await get_user_by_username(session, username)
    if user is None:
        # Dummy verify to prevent timing-based user enumeration
        password_hash.verify(password, password_hash.hash("dummy"))
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user
```

The timing attack prevention in `authenticate_user` deserves explanation. If you returned immediately when the user does not exist, an attacker could measure response times to determine which usernames are registered. By always running a password hash comparison, both cases take approximately the same time.

## 7.3 Auth Schemas

Open `src/notesmith/auth/schemas.py`:

```python
# src/notesmith/auth/schemas.py
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


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

The `username` field uses a regex pattern constraint to allow only alphanumeric characters, underscores, and hyphens. Notice that `UserResponse` does not include `hashed_password` — this is why separate input/output schemas matter.

## 7.4 The Current User Dependency

FastAPI's dependency injection system lets you create reusable authentication checks. Open `src/notesmith/auth/dependencies.py`:

```python
# src/notesmith/auth/dependencies.py
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jwt.exceptions import InvalidTokenError
from sqlalchemy.ext.asyncio import AsyncSession

from notesmith.auth import service
from notesmith.auth.models import User
from notesmith.database import get_db

# This tells FastAPI where the login endpoint is.
# It makes the Swagger UI show a login button.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Decode the JWT and load the user from the database.

    This is a dependency — FastAPI calls it automatically for any
    endpoint that declares a parameter of type CurrentUser.
    """
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
    """Verify the user account is active."""
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account",
        )
    return current_user


# Convenience type alias — use this in your endpoint signatures
CurrentUser = Annotated[User, Depends(get_current_active_user)]
```

The dependency chain is:

1. `OAuth2PasswordBearer` extracts the token from the `Authorization: Bearer <token>` header.
2. `get_current_user` decodes the token with PyJWT and loads the user from the database.
3. `get_current_active_user` checks `is_active`.

Any endpoint that declares a `CurrentUser` parameter will require a valid JWT. If the token is missing, expired, or invalid, FastAPI returns 401 before your endpoint code runs.

## 7.5 The Auth Router

Open `src/notesmith/auth/router.py`:

```python
# src/notesmith/auth/router.py
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
    """Register a new user account."""
    # Check for existing email
    existing = await service.get_user_by_email(db, user_data.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this email already exists",
        )

    # Check for existing username
    existing = await service.get_user_by_username(db, user_data.username)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with this username already exists",
        )

    user = await service.create_user(db, user_data)
    return user


@router.post("/login", response_model=Token)
async def login(
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DB,
):
    """Authenticate and receive a JWT token.

    This endpoint accepts form data (not JSON) because it follows
    the OAuth2 password flow specification. The Swagger UI login
    button sends data in this format automatically.
    """
    user = await service.authenticate_user(db, form_data.username, form_data.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = service.create_access_token(subject=str(user.id))
    return Token(access_token=access_token)


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: CurrentUser):
    """Return the authenticated user's profile."""
    return current_user
```

The login endpoint uses `OAuth2PasswordRequestForm`, which parses form-encoded data (not JSON). This is an OAuth2 standard — the fields are `username` and `password` sent as form data. The Swagger UI login button follows this standard automatically.

## 7.6 Register the Auth Router

Update `main.py`:

```python
# src/notesmith/main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI

from notesmith.auth.router import router as auth_router
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

app.include_router(auth_router, prefix="/api/v1")
app.include_router(notes_router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    return {"status": "ok"}
```

## 7.7 Protect the Notes Endpoints

Now replace the `TEMP_USER_ID` placeholder in the notes router with real authentication. Update `src/notesmith/notes/router.py`:

```python
# src/notesmith/notes/router.py
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
    note = await service.create_note(db, note_data, owner_id=current_user.id)
    return note


@router.get("/", response_model=list[NoteResponse])
async def list_notes(db: DB, current_user: CurrentUser, skip: int = 0, limit: int = 50):
    notes = await service.get_notes_by_owner(db, owner_id=current_user.id, skip=skip, limit=limit)
    return notes


@router.get("/{note_id}", response_model=NoteResponse)
async def get_note(note_id: int, db: DB, current_user: CurrentUser):
    note = await service.get_note_by_id(db, note_id)
    if note is None or note.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


@router.patch("/{note_id}", response_model=NoteResponse)
async def update_note(
    note_id: int, note_data: NoteUpdate, db: DB, current_user: CurrentUser,
):
    note = await service.get_note_by_id(db, note_id)
    if note is None or note.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Note not found")
    updated = await service.update_note(db, note, note_data)
    return updated


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(note_id: int, db: DB, current_user: CurrentUser):
    note = await service.get_note_by_id(db, note_id)
    if note is None or note.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Note not found")
    await service.delete_note(db, note)
    return None
```

The only change from Chapter 6: every endpoint now declares `current_user: CurrentUser` instead of using `TEMP_USER_ID`. FastAPI's dependency chain handles the rest.

## 7.8 Test the Authentication Flow

First, delete the test user we inserted manually in Chapter 6 (the password was a placeholder, not a real hash) via DBeaver:

```SQL
DELETE FROM notes; DELETE FROM users;
```

Start the server and test the full flow:

```bash
# Register
curl -X POST http://127.0.0.1:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "alice@example.com", "username": "alice", "password": "securepassword123"}' | python -m json.tool

# Login (note: form data, not JSON)
curl -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -d "username=alice&password=securepassword123" | python -m json.tool
```

The login response will contain `{"access_token": "eyJhbG...", "token_type": "bearer"}`. Copy the token value. Use it in subsequent requests:

```bash
TOKEN="eyJhbG..."  # Paste your token here

# Create a note (authenticated)
curl -X POST http://127.0.0.1:8000/api/v1/notes/ \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title": "Authenticated note", "content": "This is my note."}' | python -m json.tool

# Try without a token (should get 401)
curl -X GET http://127.0.0.1:8000/api/v1/notes/
# {"detail":"Not authenticated"}

# Get user profile
curl -H "Authorization: Bearer $TOKEN" \
  http://127.0.0.1:8000/api/v1/auth/me | python -m json.tool
```

You can also test through the Swagger UI at `/docs`. Click the "Authorize" button, enter the username and password, and the UI will handle token management for all subsequent requests.

---

Proceed to [Chapter 8: Dependency Injection, Middleware, and Error Handling](./08-dependency-injection.md).
