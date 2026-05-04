import logging

from app.config.field_config import QUESTIONS
from app.models.state import ChatState

logger = logging.getLogger(__name__)


def decide_next_action(state: ChatState) -> ChatState:
   
    missing_fields = state.get("missing_fields", [])

    if missing_fields:
        pending_field = missing_fields[0]
        logger.info(
            "Decided next action | session_id=%s | next_action=ask_user | pending_field=%s",
            state.get("session_id"),
            pending_field,
        )
        return {
            **state,
            "pending_field": pending_field,
            "pending_question": QUESTIONS.get(
                pending_field,
                f"Please provide {pending_field}.",
            ),
            "next_action": "ask_user",
        }

    logger.info(
        "Decided next action | session_id=%s | next_action=ready",
        state.get("session_id"),
    )
    return {
        **state,
        "pending_field": None,
        "pending_question": None,
        "next_action": "ready",
    }
