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
        content = await mcp_client.fetch_url(request.url, max_length=request.max_length)
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
        content = await mcp_client.fetch_url(request.url, max_length=request.max_length)
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
