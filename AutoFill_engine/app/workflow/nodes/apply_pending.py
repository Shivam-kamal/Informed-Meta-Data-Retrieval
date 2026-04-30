from app.models.state import ChatState


def apply_pending_field(state: ChatState) -> ChatState:
    pending_field = state.get("pending_field")
    user_message = state.get("user_message")

    if not pending_field or not user_message:
        return state

    metadata = dict(state.get("metadata", {}))
    metadata[pending_field] = user_message

    return {
        **state,
        "metadata": metadata,
        "pending_field": None,
        "pending_question": None,
        "is_followup": True,
    }
