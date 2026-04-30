import logging

from app.models.state import ChatState
from app.services.inference import infer_file_metadata
from app.services.llm import extract_message_metadata

logger = logging.getLogger(__name__)


def infer_metadata(state: ChatState) -> ChatState:
    documents = state.get("documents", [])
    inferred_metadata, format_warnings = infer_file_metadata(
        documents,
        state.get("metadata", {}),
    )
    message_metadata = extract_message_metadata(
        state.get("user_message", ""),
        documents,
        state.get("pending_field"),
    )

    logger.info(
        "Inferred upload format and message metadata | session_id=%s | inferred_metadata=%s | message_keys=%s | warnings=%s",
        state.get("session_id"),
        inferred_metadata,
        list(message_metadata.keys()),
        format_warnings,
    )
    return {
        **state,
        "inferred_metadata": inferred_metadata,
        "raw_llm_response": message_metadata,
        "warnings": format_warnings,
    }
