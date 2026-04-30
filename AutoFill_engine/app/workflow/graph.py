from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from app.models.state import ChatState
from app.services.response_generator import generate_response
from app.services.validation import get_missing_required_fields
from app.workflow.nodes.apply_pending import apply_pending_field
from app.workflow.nodes.decide import decide_next_action


def validate_required_fields(state: ChatState) -> ChatState:
    metadata = state.get("metadata", {})
    missing_fields = get_missing_required_fields(metadata)

    if missing_fields:
        return {
            **state,
            "missing_fields": missing_fields,
        }

    return {
        **state,
        "missing_fields": [],
    }


def generate_bot_response(state: ChatState) -> ChatState:
    return {
        **state,
        "bot_message": generate_response(state),
    }


@lru_cache(maxsize=1)
def build_workflow():
    graph = StateGraph(ChatState)
    graph.add_node("apply_pending_field", apply_pending_field)
    graph.add_node("validate_required_fields", validate_required_fields)
    graph.add_node("decide_next_action", decide_next_action)
    graph.add_node("generate_bot_response", generate_bot_response)
    graph.add_edge(START, "apply_pending_field")
    graph.add_edge("apply_pending_field", "validate_required_fields")
    graph.add_edge("validate_required_fields", "decide_next_action")
    graph.add_edge("decide_next_action", "generate_bot_response")
    graph.add_edge("generate_bot_response", END)
    return graph.compile()


def run_workflow(state: ChatState) -> ChatState:
    return build_workflow().invoke(state)
