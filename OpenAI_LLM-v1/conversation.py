from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional
from uuid import uuid4

from schema import ConversationMemory


REQUIRED_FIELD_ORDER = ["title", "keyAuthor", "fileType"]

FIELD_QUESTIONS = {
    "document_names": "Please share the document file name or names.",
    "title": "Please enter the title of the document.",
    "keyAuthor": "Please enter the author of the document.",
    "fileType": "Please confirm the document format: pdf, ebook, ebook+ video, video, or MS Office.",
    "chapter": "Please enter the chapter names in the same order as the documents.",
}


class ConversationStore:
    """Small in-process short-term memory store for chatbot sessions."""

    def __init__(self) -> None:
        self._sessions: Dict[str, ConversationMemory] = {}

    def get(self, session_id: Optional[str]) -> tuple[str, ConversationMemory]:
        resolved_session_id = session_id or str(uuid4())
        memory = self._sessions.get(resolved_session_id) or ConversationMemory()
        return resolved_session_id, deepcopy(memory)

    def save(self, session_id: str, memory: ConversationMemory) -> None:
        self._sessions[session_id] = deepcopy(memory)


def normalize_metadata(metadata: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not metadata:
        return {}
    return {key: value for key, value in metadata.items() if value not in (None, "", [], {})}


def merge_memory(
    stored_memory: ConversationMemory,
    request_memory: Optional[ConversationMemory],
    existing_values: Dict[str, Any],
    document_names: List[str],
) -> ConversationMemory:
    memory = deepcopy(request_memory or stored_memory)
    memory.metadata.update(normalize_metadata(stored_memory.metadata))
    memory.metadata.update(normalize_metadata(existing_values))

    if document_names:
        memory.document_names = document_names
    elif stored_memory.document_names and not memory.document_names:
        memory.document_names = stored_memory.document_names

    return memory


def apply_pending_answer(memory: ConversationMemory, message: str) -> None:
    pending_field = memory.pending_field
    answer = message.strip()
    if not pending_field or not answer:
        return

    if pending_field == "chapter":
        chapters = [
            {"chapterTitle": part.strip()}
            for part in answer.replace("|", ",").replace(";", ",").split(",")
            if part.strip()
        ]
        if chapters:
            memory.metadata["chapter"] = chapters
        return

    if pending_field == "fileType":
        memory.metadata["fileType"] = answer
        memory.metadata["formatType"] = answer
        return

    if pending_field in {"title", "keyAuthor"}:
        memory.metadata[pending_field] = answer


def merge_mapped_fields(memory: ConversationMemory, mapped_fields: Dict[str, Any]) -> None:
    for field, value in mapped_fields.items():
        if value in (None, "", [], {}):
            continue
        memory.metadata[field] = value


def missing_required_fields(metadata: Dict[str, Any], document_names: List[str]) -> List[str]:
    missing: List[str] = []
    if not document_names:
        missing.append("document_names")

    for field in REQUIRED_FIELD_ORDER:
        if not metadata.get(field):
            missing.append(field)

    file_type = str(metadata.get("fileType") or metadata.get("formatType") or "").lower()
    if file_type == "ebook":
        chapter_value = metadata.get("chapter")
        has_chapters = isinstance(chapter_value, list) and any(
            isinstance(item, dict) and item.get("chapterTitle")
            for item in chapter_value
        )
        if not has_chapters:
            missing.append("chapter")

    return list(dict.fromkeys(missing))


def choose_next_field(missing_fields: List[str], asked_fields: List[str]) -> Optional[str]:
    for field in missing_fields:
        if field not in asked_fields:
            return field
    return missing_fields[0] if missing_fields else None


def build_bot_message(next_field: Optional[str]) -> str:
    if not next_field:
        return "All required metadata is captured. You can review and submit the JSON."
    return FIELD_QUESTIONS.get(next_field, f"Please provide {next_field}.")
