from __future__ import annotations

import json
from typing import Optional

from fastapi import HTTPException, UploadFile

from schema import FieldEvidence


PDF_TYPES = {"application/pdf"}
IMAGE_TYPES = {"image/png", "image/jpeg"}
PDF_EXTENSIONS = {".pdf"}

VIDEO_TYPES = {
    "video/mp4",
    "video/mpeg",
    "video/quicktime",
    "video/webm",
    "video/x-msvideo",
    "video/x-matroska",
}
VIDEO_EXTENSIONS = {".mp4", ".mpeg", ".mpg", ".mov", ".webm", ".avi", ".mkv"}

OFFICE_TYPES = {
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
OFFICE_EXTENSIONS = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}


def file_extension(filename: Optional[str]) -> str:
    if not filename or "." not in filename:
        return ""
    return "." + filename.rsplit(".", 1)[-1].lower()


def file_kind(uploaded_file: UploadFile) -> str:
    content_type = (uploaded_file.content_type or "").lower()
    extension = file_extension(uploaded_file.filename)

    if content_type in PDF_TYPES or extension in PDF_EXTENSIONS:
        return "pdf"
    if content_type in VIDEO_TYPES or extension in VIDEO_EXTENSIONS:
        return "video"
    if content_type in OFFICE_TYPES or extension in OFFICE_EXTENSIONS:
        return "office"
    if content_type in IMAGE_TYPES:
        return "image"
    return "unsupported"


def file_kind_from_name(file_name: str) -> str:
    extension = file_extension(file_name)
    if extension in PDF_EXTENSIONS:
        return "pdf"
    if extension in VIDEO_EXTENSIONS:
        return "video"
    if extension in OFFICE_EXTENSIONS:
        return "office"
    return "unsupported"


async def collect_file_details(files: list[UploadFile]) -> list[dict]:
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required.")

    file_details: list[dict] = []
    for uploaded_file in files:
        kind = file_kind(uploaded_file)
        if kind == "unsupported":
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type: {uploaded_file.content_type}",
            )

        await uploaded_file.read()
        file_details.append(
            {
                "file_name": uploaded_file.filename,
                "content_type": uploaded_file.content_type,
                "kind": kind,
                "status": "Received",
            }
        )
    return file_details


def collect_document_details(document_names: list[str]) -> list[dict]:
    if not document_names:
        raise HTTPException(status_code=400, detail="At least one document name is required.")

    document_details: list[dict] = []
    for document_name in document_names:
        cleaned_name = str(document_name or "").strip()
        if not cleaned_name:
            raise HTTPException(status_code=400, detail="Document names cannot be empty.")

        kind = file_kind_from_name(cleaned_name)
        if kind == "unsupported":
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported document extension: {cleaned_name}",
            )

        document_details.append(
            {
                "file_name": cleaned_name,
                "content_type": "",
                "kind": kind,
                "status": "Received",
            }
        )
    return document_details


def try_collect_document_details(document_names: list[str]) -> list[dict]:
    if not document_names:
        return []
    return collect_document_details(document_names)


def safe_parse_existing_values(existing_values: Optional[str]) -> dict:
    if not existing_values:
        return {}

    try:
        obj, _ = json.JSONDecoder().raw_decode(existing_values.strip())
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def resolve_format_from_files(file_details: list[dict]) -> Optional[str]:
    kinds = [detail["kind"] for detail in file_details]
    pdf_count = kinds.count("pdf")
    video_count = kinds.count("video")

    if "office" in kinds:
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


def chapter_titles(chapter_value: object) -> list[str]:
    if not isinstance(chapter_value, list):
        return []

    titles: list[str] = []
    for item in chapter_value:
        if isinstance(item, dict):
            titles.append(str(item.get("chapterTitle") or ""))
        elif isinstance(item, str):
            titles.append(item)
    return titles


def build_chapters_for_files(file_details: list[dict], mapped_fields: dict) -> list[dict]:
    titles = chapter_titles(mapped_fields.get("chapter"))
    chapters: list[dict] = []

    for index, detail in enumerate(file_details):
        file_name = detail.get("file_name") or ""
        chapter = {
            "chapterTitle": titles[index] if index < len(titles) else "",
            "uploadFile": "",
            "fileValue": "",
            "selectedVideo": "",
        }
        if detail.get("kind") == "video":
            chapter["selectedVideo"] = file_name
        else:
            chapter["uploadFile"] = file_name
            chapter["fileValue"] = file_name
        chapters.append(chapter)

    return chapters


def remove_stale_resolution_messages(analysis, resolved_fields: set[str]) -> None:
    analysis.unresolved_fields = [
        field
        for field in getattr(analysis, "unresolved_fields", [])
        if field not in resolved_fields
    ]

    stale_fragments = {
        "fileType": ["filetype is required", "format is required", "format must be"],
        "formatType": ["format is required", "format must be"],
        "chapter": ["chapter is required", "please mention the chapter", "please provide one chapter"],
    }
    fragments = [
        fragment
        for field in resolved_fields
        for fragment in stale_fragments.get(field, [])
    ]
    analysis.warnings = [
        warning
        for warning in getattr(analysis, "warnings", [])
        if not any(fragment in str(warning).lower() for fragment in fragments)
    ]


def apply_file_overrides(analysis, file_details: list[dict]) -> None:
    mapped_fields = getattr(analysis, "mapped_fields", {}) or {}
    detected_format = resolve_format_from_files(file_details)

    if detected_format:
        mapped_fields["fileType"] = detected_format
        mapped_fields["formatType"] = detected_format
        analysis.mapped_fields = mapped_fields
        analysis.evidence["fileType"] = FieldEvidence(
            value=detected_format,
            confidence=1.0,
            source="rule",
            reasoning="format resolved from uploaded file count and type",
        )
        analysis.evidence["formatType"] = FieldEvidence(
            value=detected_format,
            confidence=1.0,
            source="rule",
            reasoning="formatType mirrored from uploaded file format",
        )
        remove_stale_resolution_messages(analysis, {"fileType", "formatType"})

    resolved_file_type = str(
        mapped_fields.get("fileType") or mapped_fields.get("formatType") or ""
    ).strip().lower()

    if resolved_file_type in {"ebook", "ebook+ video"}:
        mapped_fields["chapter"] = build_chapters_for_files(file_details, mapped_fields)
        analysis.mapped_fields = mapped_fields
        analysis.evidence["chapter"] = FieldEvidence(
            value=mapped_fields["chapter"],
            confidence=1.0,
            source="rule",
            reasoning="chapter file entries built from uploaded files in sequence",
        )
        remove_stale_resolution_messages(analysis, {"chapter"})


def add_upload_warnings(analysis, file_details: list[dict]) -> None:
    mapped_fields = getattr(analysis, "mapped_fields", {}) or {}
    resolved_file_type = str(
        mapped_fields.get("fileType") or mapped_fields.get("formatType") or ""
    ).strip().lower()

    pdf_count = sum(1 for detail in file_details if detail["kind"] == "pdf")
    video_count = sum(1 for detail in file_details if detail["kind"] == "video")

    if resolved_file_type == "pdf" and pdf_count != 1:
        analysis.warnings.append("PDF format expects exactly one uploaded PDF.")
    if resolved_file_type == "ebook" and pdf_count <= 1:
        analysis.warnings.append("Ebook format expects multiple uploaded PDFs.")
    if resolved_file_type == "video" and video_count != 1:
        analysis.warnings.append("Video format expects exactly one uploaded video.")


def document_info(document_details: list[dict]) -> list[dict]:
    return [
        {
            "file_name": detail["file_name"],
            "kind": detail["kind"],
            "status": detail["status"],
        }
        for detail in document_details
    ]
