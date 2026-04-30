from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    documents: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None


class ChatResponse(BaseModel):
    session_id: str
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    pending_field: str | None = None
    next_action: Literal["ask_user", "ready", "error"]
