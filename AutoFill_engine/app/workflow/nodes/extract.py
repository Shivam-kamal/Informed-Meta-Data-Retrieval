import logging

from app.models.state import ChatState

logger = logging.getLogger(__name__)


def extract_documents(state: ChatState) -> ChatState:
    logger.info(
        "Document parsing is disabled; using uploaded file names only | session_id=%s",
        state.get("session_id"),
    )
    return {**state, "extracted_documents": []}
