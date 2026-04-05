# Chapter 9: Anthropic SDK Integration

This chapter integrates the Anthropic Python SDK into the application. You will build endpoints that send data to Claude and return AI-generated responses, including a streaming endpoint.

## 9.1 The AsyncAnthropic Client

The Anthropic SDK provides both a synchronous (`Anthropic`) and asynchronous (`AsyncAnthropic`) client. Since our entire stack is async, **always use `AsyncAnthropic`**. Using the synchronous client inside an `async def` endpoint would block the event loop and stall all other requests.

Open `src/notesmith/ai/service.py`:

```python
# src/notesmith/ai/service.py
from anthropic import AsyncAnthropic

from notesmith.config import settings
from anthropic.types import TextBlock

# Create a single client instance at module level.
# The client manages its own connection pool internally.
# It reads ANTHROPIC_API_KEY from the environment by default,
# but we pass it explicitly for clarity.
client = AsyncAnthropic(api_key=settings.anthropic_api_key)

# The model to use across all AI features.
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
        messages=[
            {"role": "user", "content": text},
        ],
    )
    # message.content is a list of content blocks. For text responses,
    # there is typically one TextBlock.
    text_block = message.content[0]
    if not isinstance(text_block, TextBlock):
        raise ValueError("Unexpected response type from Anthropic API")
    return text_block.text


async def analyze_text(text: str, analysis_type: str) -> str:
    """Analyze text according to the specified analysis type.

    Args:
        text: The text to analyze.
        analysis_type: One of 'sentiment', 'key_topics', 'action_items'.
    """
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
        messages=[
            {"role": "user", "content": text},
        ],
    )
    text_block = message.content[0]
    if not isinstance(text_block, TextBlock):
        raise ValueError("Unexpected response type from Anthropic API")
    return text_block.text


async def stream_summarize(text: str):
    """Stream a summary of the provided text, yielding chunks as they arrive.

    This is an async generator — each yield produces a chunk of text.
    """
    async with client.messages.stream(
        model=MODEL,
        max_tokens=1024,
        system="You are a precise summarizer. Produce a clear, detailed summary "
        "of the provided text. Cover all key points. Do not include "
        "preamble like 'Here is a summary'. Just provide the summary directly.",
        messages=[
            {"role": "user", "content": text},
        ],
    ) as stream:
        async for text_chunk in stream.text_stream:
            yield text_chunk
```

Key concepts:

**System prompt is a top-level parameter**, not a message. This is specific to the Anthropic Messages API — the `system` parameter is separate from the `messages` list (which only contains `user` and `assistant` roles).

**`message.content`** is a list of content blocks. For simple text responses, it contains a single `TextBlock` object with a `.text` attribute. The list structure exists because Claude can return multiple content blocks (e.g., when using tool use or mixed content).

**`client.messages.stream()`** returns an async context manager. Inside it, `stream.text_stream` is an async iterator that yields text chunks as Claude generates them. This is used for real-time streaming to the client.

**Module-level client** — Creating `AsyncAnthropic()` at the module level is fine. The client is lightweight and manages its HTTP connection pool internally. Do not create a new client per request.

## 9.2 AI Schemas

Create schemas for the AI endpoints. Open `src/notesmith/ai/schemas.py` (create this file):

```python
# src/notesmith/ai/schemas.py
from pydantic import BaseModel, Field
from enum import Enum


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

Using `str, Enum` for `AnalysisType` makes FastAPI render the allowed values in the OpenAPI docs and validate that the client sends one of them.

## 9.3 The AI Router

Open `src/notesmith/ai/router.py`:

```python
# src/notesmith/ai/router.py
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
        result = await ai_service.analyze_text(request.text, request.analysis_type.value)
    except APIError as e:
        logger.error("Anthropic API error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI service temporarily unavailable",
        )
    return AnalyzeResponse(analysis_type=request.analysis_type.value, result=result)


@router.post("/notes/{note_id}/summarize", response_model=NoteSummarizeResponse)
async def summarize_note(
    note_id: int, db: DB, current_user: CurrentUser,
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
    request: SummarizeRequest, current_user: CurrentUser,
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
```

Key patterns:

**Error handling for external services** — The Anthropic API can fail (rate limits, network issues, server errors). Catch `APIError` and return a 502 Bad Gateway to the client. This tells the client the failure is upstream, not in your application. Log the actual error for debugging.

**The streaming endpoint** uses `StreamingResponse` with an async generator. FastAPI sends each yielded chunk to the client immediately as it becomes available. The `media_type="text/plain"` tells the client to expect plain text, not JSON. For Server-Sent Events (SSE) format, you would use `text/event-stream` and format each chunk as `data: {chunk}\n\n`.

**`summarize_note`** demonstrates the pattern of combining database operations with AI calls: load the note → call Claude → save the result. All within a single request and database session.

## 9.4 Register the AI Router

Update `main.py` to include the AI router:

```python
# src/notesmith/main.py (add the import and include)
from notesmith.ai.router import router as ai_router

# ... (after the other include_router calls)
app.include_router(ai_router, prefix="/api/v1")
```

The full `main.py` now includes three routers:

```python
app.include_router(auth_router, prefix="/api/v1")
app.include_router(notes_router, prefix="/api/v1")
app.include_router(ai_router, prefix="/api/v1")
```

## 9.5 Test the AI Endpoints

Start the server and get a token:

```bash
# Login
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/v1/auth/login \
  -d "username=alice&password=securepassword123" | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Summarize arbitrary text
curl -X POST http://127.0.0.1:8000/api/v1/ai/summarize \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "FastAPI is a modern, fast web framework for building APIs with Python based on standard Python type hints. It is designed to be easy to use and learn, while also being ready for production. FastAPI achieves high performance through its use of Starlette for the web parts and Pydantic for the data parts. It automatically generates OpenAPI documentation and supports async operations natively."
  }' | python -m json.tool

# Analyze sentiment
curl -X POST http://127.0.0.1:8000/api/v1/ai/analyze \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "I absolutely love this new framework. The documentation is clear and the development experience is fantastic.",
    "analysis_type": "sentiment"
  }' | python -m json.tool

# Stream a summary
curl -X POST http://127.0.0.1:8000/api/v1/ai/summarize/stream \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "FastAPI is a modern, fast web framework for building APIs with Python. It leverages type hints for automatic validation and documentation. It supports async operations natively and achieves high performance. The framework has gained significant adoption since its release."
  }'

# Summarize an existing note (replace 1 with an actual note ID)
curl -X POST http://127.0.0.1:8000/api/v1/ai/notes/1/summarize \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool
```

The streaming endpoint will display text progressively in your terminal as chunks arrive.

## 9.6 Cost and Rate Limit Awareness

When integrating AI APIs into a production application, keep these considerations in mind:

**Cost** — Every API call costs money based on input and output tokens. For a notes application, summarization calls are infrequent and short, so costs are minimal. But if you were processing thousands of documents, you would want to cache results and avoid redundant calls. Our `summarize_note` endpoint stores the summary, preventing repeated API calls for the same content.

**Rate limits** — The Anthropic API has rate limits on requests per minute and tokens per minute. The SDK includes built-in retry logic with exponential backoff (2 retries by default). For high-throughput applications, you would implement a queue or use the batch API.

**Timeouts** — AI API calls can take several seconds. For non-streaming endpoints, the default timeout in the SDK is 10 minutes. You can set a shorter timeout when creating the client:

```python
client = AsyncAnthropic(
    api_key=settings.anthropic_api_key,
    timeout=30.0,  # 30-second timeout
)
```

**Input validation** — Always validate and limit the size of text sent to the API. Our schemas enforce `min_length=10` to reject empty inputs. You should also consider a `max_length` to prevent sending massive documents that would be expensive to process.

---

Proceed to [Chapter 10: Testing with pytest and httpx](./10-testing.md).
