from __future__ import annotations

from pathlib import Path
from typing import Any


PDF_EXTENSIONS = {".pdf"}
MS_OFFICE_EXTENSIONS = {
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".xlsm",
}
VIDEO_EXTENSIONS = {
    ".avi",
    ".flv",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".webm",
    ".wmv",
}


def _empty_chapter_row(
    upload_file: str = "",
    selected_video: str = "",
) -> dict[str, str]:
    return {
        "chapterTitle": "",
        "uploadFile": upload_file,
        "fileValue": upload_file,
        "selectedVideo": selected_video,
    }


def infer_document_category(document: str) -> str | None:
    suffix = Path(document).suffix.lower()

    if suffix in PDF_EXTENSIONS:
        return "pdf"
    if suffix in MS_OFFICE_EXTENSIONS:
        return "MS Office"
    if suffix in VIDEO_EXTENSIONS:
        return "video"

    return None


def _normalize_format(value: object) -> str:
    return str(value or "").strip().lower()


def resolve_production_format(documents: list[str]) -> str | None:
    categories = [infer_document_category(document) for document in documents]
    pdf_count = categories.count("pdf")
    video_count = categories.count("video")
    has_office = "MS Office" in categories

    if has_office:
        return "MS Office"

    if pdf_count and video_count:
        return "ebook+ video"

    if video_count > 1:
        return "ebook+ video"

    if video_count == 1:
        return "video"

    if pdf_count > 1:
        return "ebook"

    if pdf_count == 1:
        return "pdf"

    return None


def infer_file_type(documents: list[str]) -> str | None:
    return resolve_production_format(documents)


def infer_format_warnings(
    documents: list[str],
    mapped_format: object,
) -> list[str]:
    normalized_format = _normalize_format(mapped_format)
    categories = [infer_document_category(document) for document in documents]
    pdf_count = categories.count("pdf")
    video_count = categories.count("video")
    warnings: list[str] = []

    if not normalized_format:
        return warnings

    if normalized_format == "pdf" and pdf_count != 1:
        warnings.append("Format is mapped as pdf, but uploaded file names do not contain exactly one PDF.")

    if normalized_format == "ebook" and pdf_count <= 1:
        warnings.append("Format is mapped as ebook, but uploaded file names contain only one PDF or no PDFs.")

    if normalized_format == "video" and video_count != 1:
        warnings.append("Format is mapped as video, but uploaded file names do not contain exactly one video.")

    return warnings


def infer_file_metadata(
    documents: list[str],
    current_metadata: dict[str, object] | None = None,
) -> tuple[dict[str, object], list[str]]:
    metadata: dict[str, object] = {}
    production_format = resolve_production_format(documents)

    if production_format:
        metadata["fileType"] = production_format
        metadata["formatType"] = production_format

    if documents:
        metadata["file"] = documents[0]

    office_documents = [
        document
        for document in documents
        if infer_document_category(document) == "MS Office"
    ]
    if office_documents:
        metadata["officeFile"] = office_documents[0]

    chapters = infer_default_chapters(documents)
    if chapters:
        metadata["chapter"] = chapters

    requested_format = None
    if current_metadata:
        requested_format = current_metadata.get("formatType") or current_metadata.get("fileType")

    warnings = infer_format_warnings(documents, requested_format or production_format)
    return metadata, warnings


def infer_default_chapters(documents: list[str]) -> list[dict[str, Any]]:
    chapters: list[dict[str, Any]] = []
    production_format = resolve_production_format(documents)

    if production_format not in {"ebook", "ebook+ video"}:
        return []

    chapters:list[dict[str,Any]] = []

    for document in documents:
        category = infer_document_category(document)
        if category == "pdf":
            chapters.append(_empty_chapter_row(upload_file=document))
        elif category == "video":
            chapters.append(_empty_chapter_row(selected_video=document))

    return chapters
