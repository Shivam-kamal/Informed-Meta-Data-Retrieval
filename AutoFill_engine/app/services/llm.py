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
ORDINAL_WORDS = {
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
}
ALLOWED_LLM_KEYS = {
    "company",
    "product",
    "country",
    "expDatetime",
    "production",
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
        r"(?:main\s+document\s+ti(?:tle|ltle|lte)|document\s+ti(?:tle|ltle|lte)|(?<!chapter\s)ti(?:tle|ltle|lte))\s*(?:is|:|-)\s*([^,.;\n]+)",
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


def _chapter_capable_documents(documents: list[str]) -> list[str]:
    return [
        document
        for document in documents
        if Path(document).suffix.lower() in CHAPTER_EXTENSIONS
    ]


def _message_has_chapter_intent(message: str, documents: list[str]) -> bool:
    chapter_documents = _chapter_capable_documents(documents)
    lowered_message = message.lower()
    if "chapter" in lowered_message:
        return True
    if re.search(r"\b(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\b", lowered_message):
        if re.search(r"\b(pdf|video|title|tilte|tile|sequence|order)\b", lowered_message):
            return True
    return any(document.lower() in lowered_message for document in chapter_documents)


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

    effective_pending_field = None if _message_has_chapter_intent(message, documents) else pending_field

    try:
        response = _client().chat.completions.create(
            model=settings.openai_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract metadata from the user's message and return strict JSON.\n"
                        "RULES:\n"
                        "1. Allowed keys: company, product, country, expDatetime, production, productionNotes, title, keyAuthor, coverPhoto, chapter.\n"
                        "2. Never invent values. Only extract explicit statements.\n"
                        "3. Pay special attention to the 'pending_field'; if the user provides a raw value, it likely belongs to this field.\n"
                        "4. Distinguish carefully between 'production' and 'productionNotes'.\n"
                        "5. Do not compute relative dates. 'expDatetime' must be an explicit ISO datetime if provided.\n"
                        "6. 'chapter' must be a list of objects (chapterTitle, uploadFile, fileValue, selectedVideo) using ONLY names from the provided 'documents'."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "message": message,
                            "documents": documents,
                            "pending_field": effective_pending_field,
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
        if not title and not filename:
            continue

        if not filename:
            chapters.append(_chapter_row(title or ""))
            continue

        document = document_lookup.get(filename.lower())
        if not document:
            chapters.append(_chapter_row(title or ""))
            continue

        suffix = Path(document).suffix.lower()
        if suffix == ".pdf":
            chapters.append(_chapter_row(title or "", upload_file=document))
        elif suffix in VIDEO_EXTENSIONS:
            chapters.append(_chapter_row(title or "", selected_video=document))
        else:
            chapters.append(_chapter_row(title or ""))

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
    chapter_intent = _message_has_chapter_intent(message, documents)

    if parsed_exp_datetime and set(metadata) == {"expDatetime"}:
        return metadata

    llm_metadata = _extract_with_openai(message, documents, pending_field)
    llm_metadata = _validated_llm_metadata(
        llm_metadata,
        documents,
        allow_exp_datetime=not bool(parsed_exp_datetime),
    )
    if chapter_intent and pending_field:
        llm_metadata.pop(pending_field, None)

    if parsed_exp_datetime:
        llm_metadata.pop("expDatetime", None)

    metadata.update({key: value for key, value in llm_metadata.items() if value not in EMPTY_VALUES})
    return metadata





def _chapter_number(snippet: str) -> str | None:
    match = re.search(r"chapter\s*(\d+)", snippet, re.I)
    if match:
        return match.group(1)

    for word, number in ORDINAL_WORDS.items():
        if re.search(rf"\b{word}\s+chapter\b|\bchapter\s+{word}\b", snippet, re.I):
            return str(number)

    return None


def _chapter_title(snippet: str) -> str | None:
    patterns = [
        r"(?:titled|chapter\s+ti(?:tle|lte|le|te)?\s+is)\s+([^,.;\n]+)",
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


def _parse_ordinal_reference(snippet: str) -> int | None:
    number_match = re.search(r"\bchapter\s*(\d+)\b", snippet, re.I)
    if number_match:
        return int(number_match.group(1))

    for word, number in ORDINAL_WORDS.items():
        if re.search(rf"\b{word}\b", snippet, re.I):
            return number

    return None


def _chapter_media_type(snippet: str) -> str | None:
    if re.search(r"\bpdf\b", snippet, re.I):
        return "pdf"
    if re.search(r"\bvideo\b", snippet, re.I):
        return "video"
    return None


def _ordinal_chapter_instructions(
    message: str,
    documents: list[str],
) -> list[dict[str, str]]:
    chapter_documents = _chapter_capable_documents(documents)
    if not chapter_documents:
        return []

    instructions: dict[int, dict[str, str]] = {}
    normalized_message = re.sub(r"\bone\b", "chapter", message, flags=re.I)

    title_pattern = re.compile(
        r"\b(?:(chapter\s*\d+)|((?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth))(?:\s+chapter)?)\b"
        r"[^.:\n]{0,60}?\b(?:chapter\s+)?ti(?:tle|lte|le|te)?\s*(?:is|=|:|-)\s*[\"']?([^\"'\n,.]+)",
        re.I,
    )
    for match in title_pattern.finditer(normalized_message):
        index = _parse_ordinal_reference(match.group(0))
        title = _normalize_string(match.group(3))
        if index and title:
            instructions.setdefault(index, {})["chapterTitle"] = title

    named_title_pattern = re.compile(
        r"\b(?:(chapter\s*\d+)|((?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth))(?:\s+chapter)?)\b"
        r"[^.:\n]{0,40}?\b(?:is|as|to\s+be)\s*[\"']?([^\"'\n,.]+)[\"']?",
        re.I,
    )
    for match in named_title_pattern.finditer(normalized_message):
        snippet = match.group(0)
        index = _parse_ordinal_reference(snippet)
        candidate = _normalize_string(match.group(3))
        if not index or not candidate:
            continue
        if _chapter_media_type(candidate):
            continue
        if re.search(r"\bchapter\b", candidate, re.I):
            continue
        instructions.setdefault(index, {}).setdefault("chapterTitle", candidate)

    type_pattern = re.compile(
        r"\b(?:(chapter\s*\d+)|((?:first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth))(?:\s+(?:chapter|one))?)\b"
        r"[^.:\n]{0,40}?\b(?:(?:is|as|to\s+be)\s+)?(?:a\s+)?(pdf|video)\b",
        re.I,
    )
    for match in type_pattern.finditer(normalized_message):
        index = _parse_ordinal_reference(match.group(0))
        media_type = _chapter_media_type(match.group(3))
        if index and media_type:
            instructions.setdefault(index, {})["mediaType"] = media_type

    if not instructions:
        return []

    pdf_documents = [
        document for document in chapter_documents if Path(document).suffix.lower() == ".pdf"
    ]
    video_documents = [
        document for document in chapter_documents if Path(document).suffix.lower() in VIDEO_EXTENSIONS
    ]
    unused_documents = list(chapter_documents)
    used_documents: set[str] = set()
    chapters: list[dict[str, str]] = []

    def assign_document(media_type: str | None) -> str | None:
        if media_type == "pdf":
            candidates = pdf_documents
        elif media_type == "video":
            candidates = video_documents
        else:
            candidates = chapter_documents

        for document in candidates:
            if document not in used_documents:
                used_documents.add(document)
                if document in unused_documents:
                    unused_documents.remove(document)
                return document
        return None

    for index in sorted(instructions):
        instruction = instructions[index]
        document = assign_document(instruction.get("mediaType"))
        title = instruction.get("chapterTitle", "")

        if not document:
            chapters.append(_chapter_row(title))
            continue

        suffix = Path(document).suffix.lower()
        if suffix == ".pdf":
            chapters.append(_chapter_row(title, upload_file=document))
        else:
            chapters.append(_chapter_row(title, selected_video=document))

    return chapters


def extract_chapters_from_message(message: str, documents: list[str]) -> list[dict[str, str]]:
    ordinal_chapters = _ordinal_chapter_instructions(message, documents)
    chapters_by_identity: dict[str, dict[str, str]] = {}

    for chapter in ordinal_chapters:
        identity = chapter.get("uploadFile") or chapter.get("selectedVideo")
        if identity:
            chapters_by_identity[identity] = chapter

    chapters: list[dict[str, str]] = list(ordinal_chapters)

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
            chapter = _chapter_row(title, upload_file, selected_video)
            identity = upload_file or selected_video
            existing = chapters_by_identity.get(identity)
            if existing:
                if not existing.get("chapterTitle"):
                    existing["chapterTitle"] = title
                continue
            chapters.append(chapter)
            if identity:
                chapters_by_identity[identity] = chapter

    return chapters
