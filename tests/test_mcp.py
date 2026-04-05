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
    """Verify the MCP server exposes the expected tools.

    This test does not touch the database — it only inspects the
    tool registry, so it does not need the session patch.
    """
    async with Client(mcp_server) as client:
        tools = await client.list_tools()
        tool_names = {t.name for t in tools}
        assert "list_notes" in tool_names
        assert "get_note" in tool_names
        assert "create_note" in tool_names
        assert "search_notes" in tool_names


async def test_mcp_server_create_and_get_note(
    db_session: AsyncSession,
    patch_mcp_server_db,
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
        get_result = await client.call_tool("get_note", {"note_id": note_data["id"]})
        retrieved = get_result.data
        assert retrieved["title"] == "MCP Test Note"
        assert retrieved["content"] == "Created via MCP tools."


async def test_mcp_server_get_nonexistent_note(patch_mcp_server_db):
    """Test that get_note returns an error for missing notes.

    Even though no test data is needed, the tool still opens a
    database session, so the patch is required to avoid the
    'attached to a different loop' error.
    """
    async with Client(mcp_server) as client:
        result = await client.call_tool("get_note", {"note_id": 99999})
        assert "error" in result.data


# ----------------------------------------------------------------
# MCP Client Router Tests (REST API endpoints)
# ----------------------------------------------------------------


@patch("notesmith.mcp.client.create_fetch_client")
async def test_fetch_to_note(
    mock_create_client,
    client: AsyncClient,
    auth_headers,
    db_session,
):
    """Test the fetch-to-note endpoint with a mocked MCP client."""
    # Set up the mock chain: create_fetch_client() returns a mock Client
    # whose __aenter__ returns itself, and call_tool returns a result.
    # Use real TextContent so isinstance() checks in client.py pass.
    mock_mcp = AsyncMock()
    mock_content = TextContent(
        type="text", text="# Example Page\n\nThis is the fetched content."
    )
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
    mock_content = TextContent(
        type="text", text="Long article content about FastAPI and Python."
    )
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
