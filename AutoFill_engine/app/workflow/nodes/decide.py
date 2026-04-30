from app.config.field_config import QUESTIONS
from app.models.state import ChatState


def decide_next_action(state: ChatState) -> ChatState:
    missing_fields = state.get("missing_fields", [])

    if missing_fields:
        pending_field = missing_fields[0]
        return {
            **state,
            "pending_field": pending_field,
            "pending_question": QUESTIONS[pending_field],
            "next_action": "ask_user",
        }

    return {
        **state,
        "pending_field": None,
        "pending_question": None,
        "next_action": "ready",
    }
