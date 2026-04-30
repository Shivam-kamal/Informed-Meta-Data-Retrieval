from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from app.config.field_config import QUESTIONS
from app.models.state import ChatState
from app.services.validation import get_missing_required_fields
from app.workflow.nodes.apply_pending import apply_pending_field


def validate_required_fields(state: ChatState) -> ChatState:
    metadata = state.get("metadata", {})
    missing_fields = get_missing_required_fields(metadata)

    if missing_fields:
        pending_field = missing_fields[0]
        return {
            **state,
            "missing_fields": missing_fields,
            "pending_field": pending_field,
            "pending_question": QUESTIONS.get(pending_field),
            "bot_message": QUESTIONS.get(pending_field, f"Please provide {pending_field}."),
            "next_action": "ask_user",
        }

    return {
        **state,
        "missing_fields": [],
        "pending_field": None,
        "pending_question": None,
        "bot_message": "All required fields are complete.",
        "next_action": "ready",
    }


@lru_cache(maxsize=1)
def build_workflow():
    graph = StateGraph(ChatState)
    graph.add_node("apply_pending_field", apply_pending_field)
    graph.add_node("validate_required_fields", validate_required_fields)
    graph.add_edge(START, "apply_pending_field")
    graph.add_edge("apply_pending_field", "validate_required_fields")
    graph.add_edge("validate_required_fields", END)
    return graph.compile()


def run_workflow(state: ChatState) -> ChatState:
    return build_workflow().invoke(state)
