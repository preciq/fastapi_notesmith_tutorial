from unittest.mock import AsyncMock, MagicMock, patch
from anthropic.types import TextBlock

from httpx import AsyncClient


def _mock_message(text: str):
    """Create a mock Anthropic message response."""
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
        json={
            "text": "A long piece of text that needs to be summarized for testing purposes."
        },
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
        return_value=_mock_message(
            '{"sentiment": "positive", "explanation": "The text expresses enthusiasm."}'
        )
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
