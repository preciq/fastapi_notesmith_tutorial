# Chapter 10: Testing with pytest and httpx

This chapter covers writing async tests for FastAPI applications: configuring pytest-asyncio, using httpx's `AsyncClient` to test endpoints, overriding dependencies for test isolation, and testing authenticated routes. All tests run against a real PostgreSQL database to guarantee full behavioral parity with production.

## 10.1 Test Configuration

First, configure pytest-asyncio in `pyproject.toml`. Add this section:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
pythonpath = ["src"]
```

- **`asyncio_mode = "auto"`** — All async test functions run as asyncio tasks automatically. Without this, you would need to add `@pytest.mark.asyncio` to every async test.
- **`pythonpath = ["src"]`** — Adds `src/` to the Python path so imports like `from notesmith.main import app` work in tests.

## 10.2 The Test Database

Tests run against a **separate PostgreSQL database**, not your development database. This ensures tests never corrupt your development data, and your development data never leaks into tests.

### Add the Environment Variable

Update `src/notesmith/config.py` to include the test database URL:

```python
# src/notesmith/config.py
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

`test_database_url` is `Optional` with a default of `None` because production deployments do not need it. It is only required when running the test suite.

### Create the Test Database

Create a dedicated PostgreSQL database for tests:

```bash
createdb notesmith_test
```

Or if you need to authenticate:

```bash
psql -U postgres -c "CREATE DATABASE notesmith_test;"
```

### Add to .env

Add the test database URL to your `.env` file:

```env
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/notesmith
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/notesmith_test
ANTHROPIC_API_KEY=sk-ant-your-key-here
JWT_SECRET_KEY=change-me-to-a-random-hex-string
```

The test database URL follows the same format as the main one — same driver (`asyncpg`), same host, different database name.

## 10.3 Test Fixtures

Fixtures provide reusable setup for tests. Create `tests/conftest.py`:

```python
# tests/conftest.py
from typing import AsyncGenerator

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
    """Create all tables before each test, drop them after.

    This ensures each test starts with a clean, empty database.
    The create/drop cycle is slower than transaction rollback,
    but it is simple and avoids event loop issues with
    session-scoped async fixtures in pytest-asyncio.
    """
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide a test database session."""
    async with test_session_maker() as session:
        yield session


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    """Provide an httpx AsyncClient wired to the FastAPI app.

    Overrides the get_db dependency to use the test database session.
    This means the endpoint and the test share the same session and
    can see each other's changes.
    """
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
    """Create and return a test user."""
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
    """Return Authorization headers with a valid JWT for the test user."""
    token = create_access_token(subject=str(test_user.id))
    return {"Authorization": f"Bearer {token}"}
```

Walk through each fixture:

**`setup_database`** — `autouse=True` means it runs for every test automatically. It creates all tables before the test and drops them after, ensuring each test starts with a clean database. Using `Base.metadata.create_all` (instead of Alembic migrations) is simpler for tests — it creates all tables in one call based on the current model definitions.

**`NullPool`** — The engine is created with `poolclass=NullPool`, which means no persistent connection pool. Each database operation opens a fresh connection and closes it when done. This is critical because pytest-asyncio creates a new event loop for each test. A standard connection pool would hold connections bound to the first test's event loop, and those connections would fail on subsequent tests when the loop changes. `NullPool` avoids this entirely — no persistent connections means no stale loop bindings.

**`db_session`** — Provides a single `AsyncSession` for the test. Since this session is also used by the endpoint (via dependency override), the test and the endpoint share the same session and can see each other's changes.

**`client`** — Creates an `AsyncClient` that sends requests directly to the FastAPI app in-process (no network, no Uvicorn needed). The critical line is `app.dependency_overrides[get_db] = override_get_db` — this replaces the real database dependency with our test session. After the test, `dependency_overrides.clear()` restores the original behavior.

**`ASGITransport(app=app)`** — This is the current httpx pattern for testing ASGI apps. The older `app=` parameter on `AsyncClient` was deprecated and removed. Always use `ASGITransport`.

**`test_user`** — Creates a user with a real hashed password. Tests that need authentication use this fixture.

**`auth_headers`** — Generates a valid JWT for the test user. Pass this as the `headers` parameter in test requests.

**Why all fixtures are function-scoped** — Every fixture here uses the default function scope. pytest-asyncio creates a new event loop for each test, and all function-scoped fixtures for that test run on the same loop. This avoids the `RuntimeError: ... attached to a different loop` that occurs when a session-scoped async fixture creates connections on one loop that are then reused on subsequent tests' different loops. The `NullPool` on the engine reinforces this — even though the engine object is module-level, it never holds connections between tests.

## 10.4 Testing Endpoints

Create `tests/test_auth.py`:

```python
# tests/test_auth.py
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
    assert "hashed_password" not in data  # Must not leak


async def test_register_duplicate_email(client: AsyncClient, test_user):
    response = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "test@example.com",  # Same as test_user
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

Notice: `test_login_success` uses `data=` (form-encoded) because the login endpoint expects `OAuth2PasswordRequestForm`. All other endpoints use `json=`.

Create `tests/test_notes.py`:

```python
# tests/test_notes.py
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
    # Missing required 'content' field
    response = await client.post(
        "/api/v1/notes/",
        headers=auth_headers,
        json={"title": "Test note"},
    )
    assert response.status_code == 422


async def test_list_notes(client: AsyncClient, auth_headers):
    # Create two notes
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
    # Create a note
    create_response = await client.post(
        "/api/v1/notes/",
        headers=auth_headers,
        json={"title": "Test", "content": "Content"},
    )
    note_id = create_response.json()["id"]

    # Get it
    response = await client.get(f"/api/v1/notes/{note_id}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["title"] == "Test"


async def test_get_nonexistent_note(client: AsyncClient, auth_headers):
    response = await client.get("/api/v1/notes/99999", headers=auth_headers)
    assert response.status_code == 404


async def test_update_note(client: AsyncClient, auth_headers):
    # Create
    create_response = await client.post(
        "/api/v1/notes/",
        headers=auth_headers,
        json={"title": "Original", "content": "Original content"},
    )
    note_id = create_response.json()["id"]

    # Update title only (partial update)
    response = await client.patch(
        f"/api/v1/notes/{note_id}",
        headers=auth_headers,
        json={"title": "Updated"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["title"] == "Updated"
    assert data["content"] == "Original content"  # Unchanged


async def test_delete_note(client: AsyncClient, auth_headers):
    # Create
    create_response = await client.post(
        "/api/v1/notes/",
        headers=auth_headers,
        json={"title": "To delete", "content": "Will be deleted"},
    )
    note_id = create_response.json()["id"]

    # Delete
    response = await client.delete(f"/api/v1/notes/{note_id}", headers=auth_headers)
    assert response.status_code == 204

    # Verify it is gone
    response = await client.get(f"/api/v1/notes/{note_id}", headers=auth_headers)
    assert response.status_code == 404
```

## 10.5 Testing AI Endpoints with Mocking

Testing the Anthropic SDK requires mocking — you do not want to make real API calls in tests (they cost money, are slow, and require network access).

Create `tests/test_ai.py`:

```python
# tests/test_ai.py
from unittest.mock import AsyncMock, MagicMock, patch

from anthropic.types import TextBlock
from httpx import AsyncClient


def _mock_message(text: str):
    """Create a mock Anthropic message response.

    Uses the real TextBlock class from the Anthropic SDK so that
    isinstance() checks in the service layer pass correctly.
    The outer message object can remain a MagicMock since we only
    access .content on it.
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

    # Verify the SDK was called correctly
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

    # First create a note
    create_response = await client.post(
        "/api/v1/notes/",
        headers=auth_headers,
        json={"title": "Test note", "content": "Content to be summarized by AI."},
    )
    note_id = create_response.json()["id"]

    # Summarize it
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

The `@patch("notesmith.ai.service.client")` decorator replaces the Anthropic client with a mock. `AsyncMock` handles `await` calls correctly. The `_mock_message` helper uses the real `TextBlock` class from the Anthropic SDK — this is important because the service layer uses `isinstance()` to verify the response type. A `MagicMock` would fail that check. The outer message wrapper can stay as `MagicMock` since the service code only accesses `.content` on it.

## 10.6 Running Tests

```bash
pytest -v
```

You should see output like:

```
tests/test_auth.py::test_register_user PASSED
tests/test_auth.py::test_register_duplicate_email PASSED
tests/test_auth.py::test_login_success PASSED
tests/test_auth.py::test_login_wrong_password PASSED
tests/test_auth.py::test_get_current_user PASSED
tests/test_auth.py::test_get_current_user_no_token PASSED
tests/test_notes.py::test_create_note PASSED
tests/test_notes.py::test_create_note_unauthenticated PASSED
...
```

Useful pytest flags:

```bash
pytest -v                    # Verbose: show each test name and result
pytest -x                    # Stop on first failure
pytest -k "test_login"       # Run only tests matching the pattern
pytest --tb=short            # Shorter tracebacks
pytest tests/test_auth.py    # Run only tests in one file
```

## 10.7 Why PostgreSQL Instead of SQLite

Many FastAPI testing tutorials use an in-memory SQLite database for speed. We use PostgreSQL deliberately because SQLite does not support all PostgreSQL features. Array columns, JSONB, `server_default=func.now()`, `FOR UPDATE` locks, and certain constraint behaviors all differ between the two engines. Tests that pass on SQLite can fail on PostgreSQL in production, or vice versa. Using the same database engine in tests and production eliminates this entire category of bugs.

The tradeoff is speed — each test creates and drops all tables via `create_all` / `drop_all`, which involves DDL statements against a real PostgreSQL server. For a test suite of this size (under 20 tests), the overhead is negligible. For larger suites (hundreds of tests), you would look into transaction-based isolation with savepoints, but that requires careful event loop management with pytest-asyncio that is beyond the scope of this tutorial.

## 10.8 Dropping the aiosqlite Dependency

Since tests now use PostgreSQL exclusively, the `aiosqlite` dev dependency is no longer needed. Remove it:

```bash
poetry remove --group dev aiosqlite
```

Your test dependencies are now:

```bash
poetry add --group dev pytest pytest-asyncio httpx
```

---

Proceed to [Chapter 11: Capstone Project](./11-capstone-project.md).
