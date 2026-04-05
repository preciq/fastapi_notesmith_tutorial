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
