import re
from datetime import datetime
from typing import Any

from app.config.field_config import FIELD_CONFIG


def _required_user_fields() -> list[str]:
    required_fields = FIELD_CONFIG.get("required")
    if isinstance(required_fields, list):
        return required_fields

    return [
        field
        for field, config in FIELD_CONFIG.items()
        if isinstance(config, dict)
        and config.get("required") is True
        and config.get("source", "user") == "user"
    ]


def get_missing_required_fields(metadata: dict[str, Any]) -> list[str]:
    missing_fields: list[str] = []

    for field in _required_user_fields():
        value = metadata.get(field)
        if value is None or value == "" or value == [] or value == {}:
            missing_fields.append(field)
        elif field == "expDatetime" and not _is_valid_iso_datetime(value):
            missing_fields.append(field)

    if _chapters_need_documents(metadata):
        missing_fields.append("missing_documents")

    if _chapters_need_titles(metadata):
        missing_fields.append("chapter")

    return missing_fields


def _chapters_need_documents(metadata: dict[str, Any]) -> bool:
    chapters = metadata.get("chapter")
    if not isinstance(chapters, list):
        return False

    for chapter in chapters:
        if not isinstance(chapter, dict):
            continue
        title = chapter.get("chapterTitle")
        upload_file = chapter.get("uploadFile")
        selected_video = chapter.get("selectedVideo")
        if title and not upload_file and not selected_video:
            return True
            
    return False


def _chapters_need_titles(metadata: dict[str, Any]) -> bool:
    file_type = metadata.get("fileType")
    if file_type not in {"pdf", "ebook", "ebook+ video"}:
        return False

    chapters = metadata.get("chapter")
    if not isinstance(chapters, list) or not chapters:
        return True

    return any(
        not isinstance(chapter, dict) or not chapter.get("chapterTitle")
        for chapter in chapters
    )


def _is_valid_iso_datetime(value: Any) -> bool:
    if not isinstance(value, str):
        return False

    value = value.strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?", value):
        return False

    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False

    return True
