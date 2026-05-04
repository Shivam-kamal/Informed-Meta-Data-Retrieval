import logging
from uuid import uuid4

from fastapi import APIRouter

from app.models.schemas import FRONTEND_METADATA_TEMPLATE, ChatRequest, ChatResponse
from app.models.state import ChatState, Message
from app.workflow.graph import run_workflow

router = APIRouter()
logger = logging.getLogger(__name__)

_sessions: dict[str, ChatState] = {}


def _full_metadata(metadata: dict | None) -> dict:
    metadata = metadata or {}
    return {
        key: metadata.get(key)
        for key in FRONTEND_METADATA_TEMPLATE
    }


def _filled_metadata_keys(metadata: dict) -> list[str]:
    return [
        key
        for key, value in metadata.items()
        if value is not None and value != "" and value != [] and value != {}
    ]


def _merge_metadata(previous_metadata: dict | None, request_metadata: dict | None) -> dict:
    merged = _full_metadata(previous_metadata)

    for key, value in _full_metadata(request_metadata).items():
        if value is not None and value != "" and value != [] and value != {}:
            merged[key] = value

    return merged


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    session_id = request.session_id or str(uuid4())
    previous_state = _sessions.get(session_id, {})
    logger.info(
        "Received /chat request | session_id=%s | existing_session=%s | message=%r | documents=%d",
        session_id,
        bool(previous_state),
        request.message,
        len(request.documents),
    )

    messages = list(previous_state.get("messages", []))
    messages.append(Message(role="user", content=request.message))
    metadata = _merge_metadata(previous_state.get("metadata", {}), request.metadata)

    logger.info(
        "Prepared chat state | session_id=%s | filled_metadata=%s | previous_pending_field=%s",
        session_id,
        _filled_metadata_keys(metadata),
        previous_state.get("pending_field"),
    )

    state: ChatState = {
        **previous_state,
        "session_id": session_id,
        "user_message": request.message,
        "documents": request.documents,
        "metadata": metadata,
        "messages": messages[-5:],
    }

    result = run_workflow(state)
    logger.info(
        "Workflow completed | session_id=%s | next_action=%s | pending_field=%s | missing_fields=%s",
        session_id,
        result.get("next_action"),
        result.get("pending_field"),
        result.get("missing_fields", []),
    )

    if result.get("bot_message"):
        result["messages"] = [
            *result.get("messages", []),
            Message(role="assistant", content=result["bot_message"]),
        ][-5:]

    _sessions[session_id] = result
    logger.info(
        "Sending /chat response | session_id=%s | question=%r | bot_message=%r",
        session_id,
        result.get("pending_question"),
        result.get("bot_message", ""),
    )

    return ChatResponse(
        session_id=session_id,
        bot_message=result.get("bot_message", ""),
        mapped_fields=_full_metadata(result.get("metadata", {})),
        missing_fields=result.get("missing_fields", []),
        warnings=result.get("warnings", []),
        pending_field=result.get("pending_field"),
        question=result.get("pending_question"),
        next_action=result.get("next_action", "ready"),
    )
