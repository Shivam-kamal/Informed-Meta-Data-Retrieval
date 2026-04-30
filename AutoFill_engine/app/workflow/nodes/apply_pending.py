import logging

from app.models.state import ChatState
from app.services.llm import extract_pending_field_value

logger = logging.getLogger(__name__)


def apply_pending_field(state: ChatState) -> ChatState:
    pending_field = state.get("pending_field")
    user_message = state.get("user_message")

    if not pending_field or not user_message:
        logger.info(
            "No pending field to apply | session_id=%s | pending_field=%s",
            state.get("session_id"),
            pending_field,
        )
        return state

    metadata = dict(state.get("metadata", {}))
    metadata[pending_field] = extract_pending_field_value(
        user_message,
        pending_field,
        state.get("documents", []),
    )
    logger.info(
        "Applied user reply to pending field | session_id=%s | field=%s | value=%r",
        state.get("session_id"),
        pending_field,
        metadata[pending_field],
    )

    return {
        **state,
        "metadata": metadata,
        "pending_field": None,
        "pending_question": None,
        "is_followup": True,
    }
