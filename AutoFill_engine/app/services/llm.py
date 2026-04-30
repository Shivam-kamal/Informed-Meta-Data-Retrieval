from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from openai import OpenAI

from app.core.config import Settings

logger = logging.getLogger(__name__)

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

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
        r"(?:expiry|expiration|exp(?:iry)?\s+date(?:time)?|expDatetime)\s*(?:is|:|-)\s*([^,.;\n]+)",
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
    cleaned = re.split(
        r"\s+and\s+(?:author|key author|company|company name|product|country|production|expiry|expiration|thumbnail|cover|i have|the document|doc[\w.-]*)\b",
        cleaned,
        maxsplit=1,
        flags=re.I,
    )[0]
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


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
                        "Extract metadata from the user's message only. Return strict JSON. "
                        "Allowed keys: company, product, country, production, expDatetime, "
                        "productionNotes, title, keyAuthor, coverPhoto, chapter. "
                        "chapter must be a list of objects with chapterTitle, uploadFile, "
                        "fileValue, selectedVideo. Use uploaded document names when mentioned. "
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
        )
    except Exception as exc:
        logger.warning("OpenAI message metadata extraction failed | error=%s", exc)
        return {}

    return _json_from_message(response.choices[0].message.content or "{}")


def extract_message_metadata(
    message: str,
    documents: list[str],
    pending_field: str | None = None,
) -> dict[str, Any]:
    metadata = _heuristic_metadata(message, documents)
    llm_metadata = _extract_with_openai(message, documents, pending_field)
    metadata.update({key: value for key, value in llm_metadata.items() if value not in (None, "", [], {})})
    return metadata


def extract_pending_field_value(message: str, field: str, documents: list[str]) -> Any:
    metadata = extract_message_metadata(message, documents, field)
    if field in metadata and metadata[field] not in (None, "", [], {}):
        return metadata[field]
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
        if suffix not in {".pdf", ".mp4", ".mov", ".mkv", ".webm", ".avi", ".wmv"}:
            continue

        match = re.search(re.escape(document), message, re.I)
        if not match:
            continue

        snippet = message[match.start() : match.end() + 180]
        number = _chapter_number(snippet)
        title = _chapter_title(snippet)
        if not title and number:
            title = f"Chapter {number}"

        if title:
            selected_video = document if suffix in {".mp4", ".mov", ".mkv", ".webm", ".avi", ".wmv"} else ""
            upload_file = "" if selected_video else document
            chapters.append(_chapter_row(title, upload_file, selected_video))

    if chapters:
        return chapters

    ordered_titles = []
    for match in re.finditer(r"chapter\s*\d+\s*[:\-]?\s*([^,.;\n]+)", message, re.I):
        title = _clean_value(match.group(1))
        if title:
            ordered_titles.append(title)

    if not ordered_titles:
        return []

    pdf_documents = [document for document in documents if Path(document).suffix.lower() == ".pdf"]
    for index, title in enumerate(ordered_titles):
        upload_file = pdf_documents[index] if index < len(pdf_documents) else ""
        chapters.append(_chapter_row(title, upload_file))

    return chapters
