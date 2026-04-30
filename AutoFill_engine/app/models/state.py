from typing import Any, Literal, NotRequired, TypedDict

NextAction = Literal["ask_user", "ready", "error"]


class Message(TypedDict):
    role: Literal["user", "assistant"]
    content: str


class ChatState(TypedDict):
    session_id: NotRequired[str]
    user_message: NotRequired[str]
    messages: NotRequired[list[Message]]
    documents: NotRequired[list[str]]
    metadata: NotRequired[dict[str, Any]]
    pending_field: NotRequired[str | None]
    pending_question: NotRequired[str | None]
    missing_fields: NotRequired[list[str]]
    bot_message: NotRequired[str]
    next_action: NotRequired[NextAction]
    raw_llm_response: NotRequired[dict[str, Any]]
    extracted_documents: NotRequired[list[dict[str, Any]]]
    inferred_metadata: NotRequired[dict[str, Any]]
    warnings: NotRequired[list[str]]
    is_followup: NotRequired[bool]
