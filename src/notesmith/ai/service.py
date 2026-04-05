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
