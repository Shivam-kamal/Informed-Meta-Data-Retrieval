from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from openai import OpenAI

from app.core.config import Settings
from app.utils.date_parser import extract_expiry_intent, parse_expiry_datetime

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".wmv"}
CHAPTER_EXTENSIONS = {".pdf", *VIDEO_EXTENSIONS}
ALLOWED_LLM_KEYS = {
    "company",
    "product",
    "country",
    "expDatetime",
    "productionNotes",
    "title",
    "keyAuthor",
    "coverPhoto",
    "chapter",
}
EMPTY_VALUES = (None, "", [], {})

FIELD_PATTERNS = {
    "company": [
        r"(?:company(?:\s+name)?|name\s+of\s+the\s+company)\s*(?:is|:|-)\s*([^,.;\n]+)",
    ],
    "title": [
        r"(?:document\s+title|title)\s*(?:is|:|-)\s*([^,.;\n]+)",
    ],
    "keyAuthor": [
        r"(?:key\s+author|author)\s*(?:is|:|-)\s*([^,.;\n]+)",
    ],
    "product": [
        r"(?:product)\s*(?:is|:|-)\s*([^,.;\n]+)",
    ],
    "country": [
        r"(?:country)\s*(?:is|:|-)\s*([^,.;\n]+)",
    ],
    "production": [
        r"(?:production)\s*(?:is|:|-)\s*([^,.;\n]+)",
    ],
    "expDatetime": [
        r"(?:expiry|expiration|expires?|exp(?:iry)?\s+date(?:time)?|expDatetime)\s*(?:is|in|after|from now is|from now|:|-)\s*([^,.;\n]+)",
    ],
    "productionNotes": [
        r"(?:production\s+notes?|notes?)\s*(?:is|are|:|-)\s*([^.;\n]+)",
    ],
}

def _client() -> OpenAI:
    settings = Settings()
    timeout = float(settings.openai_timeout or 60)
    return OpenAI(api_key=settings.openai_api_key or None, timeout=timeout)


def _clean_value(value: str) -> str:
    cleaned = value.strip().strip("\"'")
    cleaned = re.sub(
        r"^(?:company\s+name\s+is|name\s+of\s+the\s+company\s+is|this\s+is|it\s+is)\s+",
        "",
        cleaned,
        flags=re.I,
    )
    cleaned = re.split(
        r"\s+and\s+(?:author|key author|company|company name|product|country|production|expiry|expiration|thumbnail|cover|i have|the document|doc[\w.-]*)\b",
        cleaned,
        maxsplit=1,
        flags=re.I,
    )[0]
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _normalize_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = _clean_value(value)
    return cleaned or None


def _json_from_message(message: str) -> dict[str, Any]:
    try:
        value = json.loads(message)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", message, re.S)
        if not match:
            return {}
        try:
            value = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}

    return value if isinstance(value, dict) else {}


def _heuristic_field_value(message: str, field: str) -> Any:
    if field == "chapter":
        return extract_chapters_from_message(message, [])

    if field == "expDatetime":
        candidate = extract_expiry_intent(message) or message
        parsed_exp_datetime = parse_expiry_datetime(candidate)
        return parsed_exp_datetime or ""

    for pattern in FIELD_PATTERNS.get(field, []):
        match = re.search(pattern, message, re.I)
        if match:
            return _clean_value(match.group(1))

    return _clean_value(message)


def _heuristic_metadata(message: str, documents: list[str]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}

    for field, patterns in FIELD_PATTERNS.items():
        for pattern in patterns:
            match = re.search(pattern, message, re.I)
            if match:
                metadata[field] = _clean_value(match.group(1))
                break

    metadata.pop("expDatetime", None)
    date_candidate = extract_expiry_intent(message)
    if date_candidate:
        parsed_exp_datetime = parse_expiry_datetime(date_candidate)
        if parsed_exp_datetime:
            metadata["expDatetime"] = parsed_exp_datetime

    for document in documents:
        if Path(document).suffix.lower() in IMAGE_EXTENSIONS and re.search(
            rf"\b{re.escape(document)}\b",
            message,
            re.I,
        ):
            metadata["coverPhoto"] = document
            break

    chapter_hints = extract_chapters_from_message(message, documents)
    if chapter_hints:
        metadata["chapter"] = chapter_hints

    return metadata


def _extract_with_openai(
    message: str,
    documents: list[str],
    pending_field: str | None,
) -> dict[str, Any]:
    settings = Settings()
    if not settings.openai_api_key:
        return {}

    try:
        response = _client().chat.completions.create(
            model=settings.openai_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract metadata from the user's message only. Return only strict JSON. "
                        "Allowed keys: company, product, country, expDatetime, productionNotes, "
                        "title, keyAuthor, coverPhoto, chapter. Do not include other keys. "
                        "Do not compute relative dates. Only include expDatetime when the user provides "
                        "an explicit ISO datetime. chapter must be a list of objects with chapterTitle, "
                        "uploadFile, fileValue, selectedVideo. Use uploaded document names only. "
                        "Do not invent values."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "message": message,
                            "documents": documents,
                            "pending_field": pending_field,
                        },
                        ensure_ascii=True,
                    ),
                },
            ],
            temperature=0,
            max_tokens=800,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        logger.warning("OpenAI message metadata extraction failed | error=%s", exc)
        return {}

    return _json_from_message(response.choices[0].message.content or "{}")


def _normalize_iso_datetime(value: Any) -> str | None:
    if not _is_valid_iso_datetime(value):
        return None
    try:
        return datetime.fromisoformat(str(value).strip().replace("Z", "+00:00")).replace(microsecond=0).isoformat()
    except ValueError:
        return None


def _validated_cover_photo(value: Any, documents: list[str]) -> str | None:
    cleaned = _normalize_string(value)
    if not cleaned:
        return None
    for document in documents:
        if Path(document).suffix.lower() in IMAGE_EXTENSIONS and document.lower() == cleaned.lower():
            return document
    return None


def _validated_chapters(value: Any, documents: list[str]) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []

    document_lookup = {document.lower(): document for document in documents}
    chapters: list[dict[str, str]] = []
    for chapter in value:
        if not isinstance(chapter, dict):
            continue

        title = _normalize_string(chapter.get("chapterTitle"))
        upload_file = _normalize_string(chapter.get("uploadFile") or chapter.get("fileValue"))
        selected_video = _normalize_string(chapter.get("selectedVideo"))
        filename = upload_file or selected_video
        if not title or not filename:
            continue

        document = document_lookup.get(filename.lower())
        if not document:
            continue

        suffix = Path(document).suffix.lower()
        if suffix == ".pdf":
            chapters.append(_chapter_row(title, upload_file=document))
        elif suffix in VIDEO_EXTENSIONS:
            chapters.append(_chapter_row(title, selected_video=document))

    return chapters


def _validated_llm_metadata(
    metadata: dict[str, Any],
    documents: list[str],
    allow_exp_datetime: bool,
) -> dict[str, Any]:
    validated: dict[str, Any] = {}

    for key, value in metadata.items():
        if key not in ALLOWED_LLM_KEYS or value in EMPTY_VALUES:
            continue

        if key == "expDatetime":
            if allow_exp_datetime:
                normalized_datetime = _normalize_iso_datetime(value)
                if normalized_datetime:
                    validated[key] = normalized_datetime
            continue

        if key == "coverPhoto":
            cover_photo = _validated_cover_photo(value, documents)
            if cover_photo:
                validated[key] = cover_photo
            continue

        if key == "chapter":
            chapters = _validated_chapters(value, documents)
            if chapters:
                validated[key] = chapters
            continue

        cleaned = _normalize_string(value)
        if cleaned:
            validated[key] = cleaned

    return validated


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


def extract_message_metadata(
    message: str,
    documents: list[str],
    pending_field: str | None = None,
) -> dict[str, Any]:
    metadata = _heuristic_metadata(message, documents)
    parsed_exp_datetime = metadata.get("expDatetime")

    if parsed_exp_datetime and set(metadata) == {"expDatetime"}:
        return metadata

    llm_metadata = _extract_with_openai(message, documents, pending_field)
    llm_metadata = _validated_llm_metadata(
        llm_metadata,
        documents,
        allow_exp_datetime=not bool(parsed_exp_datetime),
    )

    if parsed_exp_datetime:
        llm_metadata.pop("expDatetime", None)

    metadata.update({key: value for key, value in llm_metadata.items() if value not in EMPTY_VALUES})
    return metadata


def extract_pending_field_value(message: str, field: str, documents: list[str]) -> Any:
    if field == "expDatetime":
        parsed_exp_datetime = parse_expiry_datetime(extract_expiry_intent(message) or message)
        if parsed_exp_datetime:
            return parsed_exp_datetime

    metadata = extract_message_metadata(message, documents, field)
    if field in metadata and metadata[field] not in (None, "", [], {}):
        return metadata[field]
    if field == "chapter":
        return extract_chapters_from_message(message, documents)
    return _heuristic_field_value(message, field)


def _chapter_number(snippet: str) -> str | None:
    match = re.search(r"chapter\s*(\d+)", snippet, re.I)
    if match:
        return match.group(1)

    ordinals = {
        "first": "1",
        "second": "2",
        "third": "3",
        "fourth": "4",
        "fifth": "5",
        "sixth": "6",
        "seventh": "7",
        "eighth": "8",
        "ninth": "9",
        "tenth": "10",
    }
    for word, number in ordinals.items():
        if re.search(rf"\b{word}\s+chapter\b|\bchapter\s+{word}\b", snippet, re.I):
            return number

    return None


def _chapter_title(snippet: str) -> str | None:
    patterns = [
        r"(?:titled|chapter\s+title\s+is)\s+([^,.;\n]+)",
        r"(?:called|named)\s+([^,.;\n]+)",
        r"chapter\s*\d+\s*(?:is|:|-)\s*([^,.;\n]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, snippet, re.I)
        if match:
            return _clean_value(match.group(1))
    return None


def _chapter_row(
    chapter_title: str,
    upload_file: str = "",
    selected_video: str = "",
) -> dict[str, str]:
    return {
        "chapterTitle": chapter_title,
        "uploadFile": upload_file,
        "fileValue": upload_file,
        "selectedVideo": selected_video,
    }


def extract_chapters_from_message(message: str, documents: list[str]) -> list[dict[str, str]]:
    chapters: list[dict[str, str]] = []

    for document in documents:
        suffix = Path(document).suffix.lower()
        if suffix not in CHAPTER_EXTENSIONS:
            continue

        title = None
        file_pattern = re.escape(document)
        patterns = [
            rf"\b{file_pattern}\b\s*(?:is|as|=)?\s*chapter\s*\d+\s*(?:titled|called|named|:|-)?\s*([^,.;\n]+)",
            rf"chapter\s*\d+\s*(?:is|:|-)\s*\b{file_pattern}\b\s*(?:titled|called|named|:|-)?\s*([^,.;\n]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, message, re.I)
            if match:
                title = _clean_value(match.group(1))
                break

        if not title:
            match = re.search(file_pattern, message, re.I)
            if match:
                snippet = message[max(0, match.start() - 80) : match.end() + 180]
                title = _chapter_title(snippet)

        if title:
            selected_video = document if suffix in VIDEO_EXTENSIONS else ""
            upload_file = "" if selected_video else document
            chapters.append(_chapter_row(title, upload_file, selected_video))

    return chapters
