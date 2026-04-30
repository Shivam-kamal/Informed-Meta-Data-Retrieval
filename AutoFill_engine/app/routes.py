from uuid import uuid4

from fastapi import APIRouter

from app.models.schemas import ChatRequest, ChatResponse
from app.models.state import ChatState, Message
from app.workflow.graph import run_workflow

router = APIRouter()

_sessions: dict[str, ChatState] = {}


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    session_id = request.session_id or str(uuid4())
    previous_state = _sessions.get(session_id, {})
    messages = list(previous_state.get("messages", []))
    messages.append(Message(role="user", content=request.message))

    state: ChatState = {
        **previous_state,
        "session_id": session_id,
        "user_message": request.message,
        "documents": request.documents,
        "metadata": request.metadata or previous_state.get("metadata", {}),
        "messages": messages[-5:],
    }

    result = run_workflow(state)

    if result.get("bot_message"):
        result["messages"] = [
            *result.get("messages", []),
            Message(role="assistant", content=result["bot_message"]),
        ][-5:]

    _sessions[session_id] = result

    return ChatResponse(
        session_id=session_id,
        message=result.get("bot_message", ""),
        metadata=result.get("metadata", {}),
        missing_fields=result.get("missing_fields", []),
        pending_field=result.get("pending_field"),
        next_action=result.get("next_action", "ready"),
    )
