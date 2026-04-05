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
