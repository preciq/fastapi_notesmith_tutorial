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
    """Summarize arbitrary text using Claude."""
    try:
        summary = await ai_service.summarize_text(request.text)
    except APIError as e:
        logger.error("Anthropic API error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI service temporarily unavailable",
        )
    return SummarizeResponse(summary=summary)


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze_text(request: AnalyzeRequest, current_user: CurrentUser):
    """Analyze text for sentiment, key topics, or action items."""
    try:
        result = await ai_service.analyze_text(
            request.text, request.analysis_type.value
        )
    except APIError as e:
        logger.error("Anthropic API error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI service temporarily unavailable",
        )
    return AnalyzeResponse(analysis_type=request.analysis_type.value, result=result)


@router.post("/notes/{note_id}/summarize", response_model=NoteSummarizeResponse)
async def summarize_note(
    note_id: int,
    db: DB,
    current_user: CurrentUser,
):
    """Summarize an existing note and store the result.

    This endpoint reads the note from the database, sends its content
    to Claude for summarization, and saves the summary back to the note.
    """
    note = await notes_service.get_note_by_id(db, note_id)
    if note is None or note.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Note not found")

    try:
        summary = await ai_service.summarize_text(note.content)
    except APIError as e:
        logger.error("Anthropic API error for note %d: %s", note_id, e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI service temporarily unavailable",
        )

    # Save the summary to the note
    note.summary = summary
    await db.flush()

    return NoteSummarizeResponse(note_id=note.id, summary=summary)


@router.post("/summarize/stream")
async def summarize_text_stream(
    request: SummarizeRequest,
    current_user: CurrentUser,
):
    """Stream a summary of the provided text.

    Returns a streaming response where text chunks arrive as Claude
    generates them. This is useful for long texts where you want to
    show results progressively rather than waiting for the full summary.
    """

    async def generate():
        try:
            async for chunk in ai_service.stream_summarize(request.text):
                yield chunk
        except APIError as e:
            logger.error("Anthropic API streaming error: %s", e)
            yield "\n\n[Error: AI service temporarily unavailable]"

    return StreamingResponse(generate(), media_type="text/plain")
