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
