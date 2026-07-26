from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=12000)


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(min_length=1, max_length=30)
    temperature: float = Field(default=0.1, ge=0, le=1)
    max_tokens: int = Field(default=700, ge=64, le=2048)
    tenant_id: str = Field(default="default", pattern=r"^[a-zA-Z0-9_-]{1,64}$")


class Source(BaseModel):
    document: str
    chunk: int
    score: float


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]
    request_id: str
    grounded: bool
