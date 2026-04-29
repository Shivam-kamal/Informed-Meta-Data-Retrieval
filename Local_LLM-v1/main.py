from __future__ import annotations

import json
from typing import Annotated, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from llm1 import LocalLLMClient
from matcher1 import FormMatcher
from schema1 import AutofillRequest, CombinedResponse, FieldEvidence, HealthResponse, PromptContext

app = FastAPI(
    title="Metadata Prompt Autofill API",
    description="Extracts structured form updates from natural language prompts.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

llm_client = LocalLLMClient()

PDF_TYPES = {"application/pdf"}
VIDEO_TYPES = {
    "video/mp4",
    "video/mpeg",
    "video/quicktime",
    "video/webm",
    "video/x-msvideo",
    "video/x-matroska",
}
OFFICE_TYPES = {
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}
IMAGE_TYPES = {"image/png", "image/jpeg"}

PDF_EXTENSIONS = {".pdf"}
VIDEO_EXTENSIONS = {".mp4", ".mpeg", ".mpg", ".mov", ".webm", ".avi", ".mkv"}
OFFICE_EXTENSIONS = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}


def _file_extension(filename: Optional[str]) -> str:
    if not filename or "." not in filename:
        return ""
    return "." + filename.rsplit(".", 1)[-1].lower()


def _file_kind(uploaded_file: UploadFile) -> str:
    content_type = (uploaded_file.content_type or "").lower()
    extension = _file_extension(uploaded_file.filename)
    if content_type in PDF_TYPES or extension in PDF_EXTENSIONS:
        return "pdf"
    if content_type in VIDEO_TYPES or extension in VIDEO_EXTENSIONS:
        return "video"
    if content_type in OFFICE_TYPES or extension in OFFICE_EXTENSIONS:
        return "office"
    if content_type in IMAGE_TYPES:
        return "image"
    return "unsupported"


def _resolve_format_from_files(file_details: list[dict]) -> Optional[str]:
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


def _safe_parse_existing_values(existing_values: Optional[str]) -> dict:
    """Parse first JSON object from form field; ignore trailing garbage."""
    if not existing_values:
        return {}
    text = existing_values.strip()
    if not text:
        return {}
    try:
        obj, _ = json.JSONDecoder().raw_decode(text)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _chapter_titles(chapter_value: object) -> list[str]:
    if not isinstance(chapter_value, list):
        return []
    titles: list[str] = []
    for item in chapter_value:
        if isinstance(item, dict):
            titles.append(str(item.get("chapterTitle") or ""))
        elif isinstance(item, str):
            titles.append(item)
    return titles


def _build_chapters_for_files(file_details: list[dict], mapped_fields: dict) -> list[dict]:
    titles = _chapter_titles(mapped_fields.get("chapter"))
    chapters: list[dict] = []

    for index, detail in enumerate(file_details):
        kind = detail.get("kind")
        file_name = detail.get("file_name") or ""
        chapter = {
            "chapterTitle": titles[index] if index < len(titles) else "",
            "uploadFile": "",
            "fileValue": "",
            "selectedVideo": "",
        }
        if kind == "video":
            chapter["selectedVideo"] = file_name
        else:
            chapter["uploadFile"] = file_name
            chapter["fileValue"] = file_name
        chapters.append(chapter)

    return chapters


def _remove_stale_resolution_messages(analysis, resolved_fields: set[str]) -> None:
    analysis.unresolved_fields = [
        field for field in getattr(analysis, "unresolved_fields", [])
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
        warning for warning in getattr(analysis, "warnings", [])
        if not any(fragment in str(warning).lower() for fragment in fragments)
    ]


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    try:
        reachable = llm_client.is_reachable()
    except Exception:
        reachable = False

    return HealthResponse(
        llm_configured=llm_client.is_configured(),
        llm_endpoint=llm_client.base_url,
        llm_endpoint_reachable=reachable,
    )


@app.post("/upload-and-analysis", response_model=CombinedResponse)
async def upload_and_analyze(
    files: Annotated[list[UploadFile], File(...)],
    prompt: str = Form(...),
    existing_values: Optional[str] = Form(None),
) -> CombinedResponse:
    print("\n================ NEW REQUEST ================")

    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required.")

    file_details = []
    for uploaded_file in files:
        kind = _file_kind(uploaded_file)
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

    past_metadata = _safe_parse_existing_values(existing_values)

    payload = AutofillRequest(
        prompt=prompt,
        context=PromptContext(),
        existing_values=past_metadata,
    )

    try:
        raw_fields = await llm_client.extract_fields(payload)
    except Exception as e:
        print("LLM error:", e)
        raw_fields = {
            "mapped_fields": {},
            "analysis_summary": None,
            "raw_parsed": {},
        }

    if (
        not isinstance(raw_fields, dict)
        or not isinstance(raw_fields.get("mapped_fields"), dict)
    ):
        raw_fields = {
            "mapped_fields": {},
            "analysis_summary": None,
            "raw_parsed": raw_fields.get("raw_parsed", {}) if isinstance(raw_fields, dict) else {},
        }

    matcher = FormMatcher(payload.context)

    try:
        analysis = matcher.post_process(
            prompt=prompt,
            llm_output=raw_fields,
            existing_values=past_metadata,
        )
    except Exception as e:
        print("Matcher error:", e)
        return CombinedResponse(
            file_info=file_details[0],
            files_info=file_details,
            comments=[],
            mapped_fields={},
            unresolved_fields=raw_fields.get("unresolved_fields", []),
            warnings=["Matcher failed"],
            confidence=0.0,
            raw_parsed=raw_fields.get("raw_parsed", {}),
        )

    if not analysis:
        return CombinedResponse(
            file_info=file_details[0],
            files_info=file_details,
            comments=[],
            mapped_fields={},
            unresolved_fields=[],
            warnings=["Empty analysis"],
            confidence=0.0,
            raw_parsed=raw_fields.get("raw_parsed", {}),
        )

    mapped_fields = getattr(analysis, "mapped_fields", {}) or {}
    detected_format = _resolve_format_from_files(file_details)
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
        _remove_stale_resolution_messages(analysis, {"fileType", "formatType"})

    resolved_file_type = str(
        mapped_fields.get("fileType") or mapped_fields.get("formatType") or ""
    ).strip().lower()
    if resolved_file_type in {"ebook", "ebook+ video"}:
        mapped_fields["chapter"] = _build_chapters_for_files(file_details, mapped_fields)
        analysis.mapped_fields = mapped_fields
        analysis.evidence["chapter"] = FieldEvidence(
            value=mapped_fields["chapter"],
            confidence=1.0,
            source="rule",
            reasoning="chapter file entries built from uploaded files in sequence",
        )
        _remove_stale_resolution_messages(analysis, {"chapter"})

    pdf_count = sum(1 for detail in file_details if detail["kind"] == "pdf")
    video_count = sum(1 for detail in file_details if detail["kind"] == "video")
    if resolved_file_type == "pdf" and pdf_count != 1:
        analysis.warnings.append("PDF format expects exactly one uploaded PDF.")
    if resolved_file_type == "ebook" and pdf_count <= 1:
        analysis.warnings.append("Ebook format expects multiple uploaded PDFs.")
    if resolved_file_type == "video" and video_count != 1:
        analysis.warnings.append("Video format expects exactly one uploaded video.")

    file_status = file_details[0]
    file_status["status"] = f"Received {len(file_details)} file(s)"

    return CombinedResponse(
        file_info=file_status,
        files_info=file_details,
        comments=getattr(analysis, "comments", []),
        mapped_fields=getattr(analysis, "mapped_fields", {}),
        unresolved_fields=getattr(analysis, "unresolved_fields", []),
        warnings=getattr(analysis, "warnings", []),
        confidence=getattr(analysis, "confidence", 0.0),
        raw_parsed=raw_fields.get("raw_parsed", {}),
    )
