import logging
from functools import lru_cache

from langgraph.graph import END, START, StateGraph

from app.models.state import ChatState
from app.services.response_generator import generate_response
from app.services.validation import get_missing_required_fields
from app.workflow.nodes.apply_pending import apply_pending_field
from app.workflow.nodes.decide import decide_next_action
from app.workflow.nodes.infer import infer_metadata
from app.workflow.nodes.merge import merge_metadata

logger = logging.getLogger(__name__)


def validate_required_fields(state: ChatState) -> ChatState:
    metadata = state.get("metadata", {})
    missing_fields = get_missing_required_fields(metadata)
    logger.info(
        "Validated required fields | session_id=%s | missing_fields=%s",
        state.get("session_id"),
        missing_fields,
    )

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
    next_state = {
        **state,
        "bot_message": generate_response(state),
    }
    logger.info(
        "Generated bot response | session_id=%s | next_action=%s | bot_message=%r",
        state.get("session_id"),
        state.get("next_action"),
        next_state.get("bot_message"),
    )
    return next_state


@lru_cache(maxsize=1)
def build_workflow():
    graph = StateGraph(ChatState)
    graph.add_node("apply_pending_field", apply_pending_field)
    graph.add_node("infer_metadata", infer_metadata)
    graph.add_node("merge_metadata", merge_metadata)
    graph.add_node("validate_required_fields", validate_required_fields)
    graph.add_node("decide_next_action", decide_next_action)
    graph.add_node("generate_bot_response", generate_bot_response)
    graph.add_edge(START, "apply_pending_field")
    graph.add_edge("apply_pending_field", "infer_metadata")
    graph.add_edge("infer_metadata", "merge_metadata")
    graph.add_edge("merge_metadata", "validate_required_fields")
    graph.add_edge("validate_required_fields", "decide_next_action")
    graph.add_edge("decide_next_action", "generate_bot_response")
    graph.add_edge("generate_bot_response", END)
    return graph.compile()


def run_workflow(state: ChatState) -> ChatState:
    logger.info("Starting workflow | session_id=%s", state.get("session_id"))
    return build_workflow().invoke(state)
