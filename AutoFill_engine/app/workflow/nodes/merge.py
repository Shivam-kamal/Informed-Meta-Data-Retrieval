import logging

from app.models.state import ChatState
from app.services.merge import merge_metadata as merge_metadata_values

logger = logging.getLogger(__name__)


def merge_metadata(state: ChatState) -> ChatState:
    metadata = merge_metadata_values(
        state.get("metadata", {}),
        state.get("inferred_metadata", {}),
        state.get("raw_llm_response", {}),
        overwrite_keys={"fileType", "formatType", "file", "officeFile", "chapter"},
    )
    logger.info(
        "Merged metadata | session_id=%s | filled_keys=%s",
        state.get("session_id"),
        [key for key, value in metadata.items() if value not in (None, "", [], {})],
    )
    return {**state, "metadata": metadata}
