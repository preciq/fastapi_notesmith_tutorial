# Chapter 11: MCP Integration with FastMCP

This chapter adds Model Context Protocol (MCP) capabilities to NoteSmith. You will use FastMCP to connect to external MCP servers as a client (consuming tools from the `mcp-server-fetch` server) and to expose NoteSmith's own functionality as an MCP server that any MCP client can connect to.

## 11.1 What MCP Is

The Model Context Protocol is a standard for connecting AI applications to tools and data sources. It defines a structured way for a **client** (your application) to discover and call **tools** provided by a **server** (an external process or service). Think of it as a universal plugin interface for AI systems.

MCP servers expose three types of components: **tools** (executable functions), **resources** (readable data sources), and **prompts** (reusable message templates). In this chapter, we focus on tools — the most practical component for a backend API.

FastMCP is the standard Python framework for building both MCP servers and clients. It handles protocol details, transport negotiation, and connection lifecycle automatically.

We will do two things:

1. **NoteSmith as an MCP client** — Connect to the `mcp-server-fetch` server to fetch web content, then save it as a note or summarize it with Claude.
2. **NoteSmith as an MCP server** — Expose note operations (list, get, create, search) as MCP tools so that any MCP client (Claude Desktop, Cursor, other applications) can interact with NoteSmith's data.

## 11.2 Installing Dependencies

Add FastMCP to the project:

```bash
poetry add fastmcp
```

| Package | Purpose |
|---------|---------|
| `fastmcp` | MCP framework — provides both the `Client` class (for connecting to servers) and the `FastMCP` server class (for exposing tools). |

The fetch MCP server (`mcp-server-fetch`) is **not** installed into your project's virtual environment. It runs as a separate subprocess with its own dependencies — this is the standard pattern for MCP servers. We use `uvx` (from the `uv` package manager) to run it in an isolated environment, which avoids dependency conflicts between the fetch server and your project. Specifically, `mcp-server-fetch` pins `httpx <0.28`, while our project requires `httpx >=0.28.1` (from `fastapi[standard]`). Keeping them in separate environments sidesteps this entirely.

Install `uv` if you do not have it already:

```bash
pipx install uv
```

Verify that `uvx` can run the fetch server (this downloads it on first run):

```bash
uvx mcp-server-fetch --help
```

Verify FastMCP:

```bash
python -c "
import fastmcp
print(f'FastMCP: {fastmcp.__version__}')
"
```

## 11.3 NoteSmith as an MCP Client

The FastMCP `Client` connects to any MCP server. For the fetch server, the client launches it as a subprocess and communicates over standard I/O (STDIO transport). The client manages the subprocess lifecycle automatically.

The architecture for this feature:

1. User calls `POST /api/v1/mcp/fetch-to-note` with a URL.
2. NoteSmith's MCP client calls the `fetch` tool on `mcp-server-fetch`.
3. The fetch server retrieves the web page and converts it to markdown.
4. NoteSmith saves the markdown as a note in the database.

### The MCP Client Service

Create the directory and files for the MCP module:

```bash
mkdir -p src/notesmith/mcp
touch src/notesmith/mcp/__init__.py
touch src/notesmith/mcp/client.py
touch src/notesmith/mcp/schemas.py
touch src/notesmith/mcp/router.py
```

Open `src/notesmith/mcp/client.py`:

```python
# src/notesmith/mcp/client.py
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

Key points:

**`uvx` for dependency isolation.** The fetch server has its own dependency tree (including `httpx <0.28`) that conflicts with ours. `uvx` runs it in an isolated temporary environment, so the two never interfere. This is the standard approach in the MCP ecosystem — MCP servers over STDIO are designed to run as independent processes with their own dependencies.

**Tool name prefixing** — When using a configuration dictionary with named servers, FastMCP prefixes tool names with the server name. The fetch server's `fetch` tool becomes `fetch_fetch` (server name `fetch` + tool name `fetch`).

**Per-request client** — Each call to `fetch_url` creates a new `Client` instance and subprocess. This is simpler than managing a long-lived subprocess and avoids issues with subprocess state. The overhead is acceptable because web fetching is inherently slow (network I/O dominates).

**`result.content`** — The MCP protocol returns results as a list of content blocks (text, images, etc.). The fetch tool returns a single `TextContent` block containing the markdown-converted page.

### MCP Schemas

Open `src/notesmith/mcp/schemas.py`:

```python
# src/notesmith/mcp/schemas.py
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

### The MCP Router

Open `src/notesmith/mcp/router.py`:

```python
# src/notesmith/mcp/router.py
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
    """Fetch a web page via the MCP fetch server and save it as a note.

    Uses the mcp-server-fetch MCP server to retrieve the page content,
    converts it to markdown, and stores it as a new note owned by the
    authenticated user.
    """
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
    """Fetch a web page and summarize it with Claude.

    Combines two capabilities: the MCP fetch server retrieves the page
    content, then the Anthropic SDK summarizes it. The summary is
    returned directly (not saved to the database).
    """
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

The `fetch-to-note` endpoint chains two systems: the MCP fetch server provides the content, and the existing database layer stores it. The `fetch-and-summarize` endpoint chains three systems: MCP fetch → Anthropic Claude → response. Both endpoints require authentication because they create data or consume API credits on behalf of the user.

## 11.4 NoteSmith as an MCP Server

Now we go the other direction: exposing NoteSmith's note operations as MCP tools so that external MCP clients (Claude Desktop, Cursor, other applications) can read and create notes through the MCP protocol.

Create `src/notesmith/mcp/server.py`:

```python
# src/notesmith/mcp/server.py
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

Walk through the design decisions:

**Each tool manages its own session.** MCP tools are standalone functions, not FastAPI endpoints. They do not participate in FastAPI's dependency injection system, so they cannot use the `get_db` dependency. Instead, each tool creates a session from the `async_session_maker` factory directly and manages its own transaction boundary. For `create_note`, we call `session.commit()` explicitly because there is no `get_db` wrapper to do it for us.

**Docstrings are the tool descriptions.** FastMCP uses the function's docstring as the tool description in the MCP protocol. These descriptions are what an LLM sees when deciding which tool to call. Write them clearly.

**`Args:` section in docstrings.** FastMCP extracts parameter descriptions from the `Args:` section and includes them in the tool's JSON schema. This helps LLM clients understand what each parameter means.

**Content truncation in list results.** The `list_notes` and `search_notes` tools truncate content to 200 characters. An MCP client can then call `get_note` with a specific ID to get the full content. This keeps list responses small enough for LLM context windows.

**No authentication.** The MCP server tools accept `owner_id` as a parameter rather than extracting it from a JWT. This is a deliberate simplification — MCP tool authentication is its own topic (FastMCP supports it via OAuth and JWT, but it is beyond the scope of this tutorial). In production, you would add an auth provider to the `FastMCP()` constructor.

## 11.5 Mounting the MCP Server on FastAPI

The MCP server needs to be accessible over HTTP so external clients can connect. FastMCP provides an `http_app()` method that creates a Starlette/ASGI application, which you can mount on your FastAPI app.

Update `src/notesmith/main.py` to mount the MCP server:

```python
# src/notesmith/main.py
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

The MCP server is now accessible at `http://127.0.0.1:8000/mcp-server/mcp`. Any MCP client can connect to this URL:

```python
from fastmcp import Client

async with Client("http://127.0.0.1:8000/mcp-server/mcp") as client:
    tools = await client.list_tools()
    for tool in tools:
        print(f"  {tool.name}: {tool.description}")
```

## 11.6 Testing

### Testing the MCP Server

The MCP server tools can be tested using FastMCP's in-memory transport. This bypasses HTTP entirely — the client talks directly to the server object in the same process.

Create `tests/test_mcp.py`:

```python
# tests/test_mcp.py
from unittest.mock import AsyncMock, MagicMock, patch

from anthropic.types import TextBlock
from fastmcp import Client
from httpx import AsyncClient
from mcp.types import TextContent
from sqlalchemy.ext.asyncio import AsyncSession

from notesmith.mcp.server import mcp as mcp_server
from notesmith.notes.models import Note


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


async def test_mcp_server_create_and_get_note(db_session: AsyncSession):
    """Test creating a note via MCP and retrieving it."""
    # Create a test user directly in the database
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


async def test_mcp_server_get_nonexistent_note():
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
    # Set up the mock chain: create_fetch_client() returns a mock Client
    # whose __aenter__ returns itself, and call_tool returns a result.
    # Use real TextContent so isinstance() checks in client.py pass.
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
    # Mock MCP fetch
    mock_mcp = AsyncMock()
    mock_content = TextContent(type="text", text="Long article content about FastAPI and Python.")
    mock_result = MagicMock()
    mock_result.content = [mock_content]
    mock_mcp.call_tool = AsyncMock(return_value=mock_result)
    mock_mcp.__aenter__ = AsyncMock(return_value=mock_mcp)
    mock_mcp.__aexit__ = AsyncMock(return_value=False)
    mock_create_client.return_value = mock_mcp

    # Mock Anthropic AI
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

Walk through the testing patterns:

**MCP server tests use in-memory transport.** `Client(mcp_server)` connects directly to the FastMCP server instance without any network or subprocess. This is fast and reliable for unit testing.

**MCP client tests mock the client factory.** The `@patch("notesmith.mcp.client.create_fetch_client")` decorator replaces the function that creates the FastMCP Client with a mock. This prevents the tests from spawning a real `mcp-server-fetch` subprocess. The mock chain (`__aenter__`, `call_tool`, `content`) simulates the full async context manager lifecycle.

**Combined mock test.** `test_fetch_and_summarize` mocks both the MCP client (for fetching) and the Anthropic client (for summarization). This verifies the full chain works without network calls.

### Running the Tests

```bash
pytest tests/test_mcp.py -v
```

You should see:

```
tests/test_mcp.py::test_mcp_server_list_tools PASSED
tests/test_mcp.py::test_mcp_server_create_and_get_note PASSED
tests/test_mcp.py::test_mcp_server_get_nonexistent_note PASSED
tests/test_mcp.py::test_fetch_to_note PASSED
tests/test_mcp.py::test_fetch_and_summarize PASSED
tests/test_mcp.py::test_fetch_to_note_unauthenticated PASSED
```

## 11.7 Manual Verification

### Test the REST API Endpoints

Start the server:

```bash
uvicorn src.notesmith.main:app --reload --port 8000
```

Log in and get a token:

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -d "username=alice&password=securepassword123" | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

Fetch a web page and save it as a note:

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/mcp/fetch-to-note \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "title": "Example.com"}' | python -m json.tool
```

Fetch a page and summarize it:

```bash
curl -s -X POST http://127.0.0.1:8000/api/v1/mcp/fetch-and-summarize \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}' | python -m json.tool
```

### Test the MCP Server

With the NoteSmith server running, use a Python script to connect as an MCP client:

```bash
python -c "
import asyncio
from fastmcp import Client

async def main():
    async with Client('http://127.0.0.1:8000/mcp-server/mcp') as client:
        tools = await client.list_tools()
        print('Available tools:')
        for t in tools:
            print(f'  {t.name}')

        # List notes for user 1
        result = await client.call_tool('list_notes', {'owner_id': 1})
        print(f'\nNotes: {result.data}')

asyncio.run(main())
"
```

You can also use the FastMCP CLI to inspect the server:

```bash
fastmcp list http://127.0.0.1:8000/mcp-server/mcp --auth none
```

## 11.8 Updated Project Structure

The MCP module adds these files:

```
src/notesmith/
└── mcp/
    ├── __init__.py
    ├── client.py      # FastMCP Client wrapper for mcp-server-fetch
    ├── schemas.py      # Pydantic schemas for MCP endpoints
    ├── router.py       # FastAPI endpoints (fetch-to-note, fetch-and-summarize)
    └── server.py       # FastMCP Server exposing NoteSmith tools
```

And one new test file:

```
tests/
└── test_mcp.py
```

## 11.9 What This Chapter Covered

1. **MCP fundamentals** — The protocol structure (client, server, tools) and where it fits in an AI application stack.
2. **FastMCP Client** — Connecting to external MCP servers over STDIO transport, calling tools, and processing results.
3. **FastMCP Server** — Exposing Python functions as MCP tools with automatic schema generation from type hints and docstrings.
4. **Integration pattern** — Chaining MCP tools with existing services (database writes, AI summarization) to build compound features.
5. **Mounting on FastAPI** — Serving the MCP server alongside REST endpoints in a single application using `http_app()` and `app.mount()`.
6. **Testing** — In-memory transport for server tests, mock-based testing for client operations, combined mock tests for multi-service chains.

---

Proceed to [Chapter 12: Capstone Project](./12-capstone-project.md).