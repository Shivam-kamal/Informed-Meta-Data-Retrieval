import streamlit as st
import json
import re
from matcher1 import extract_metadata

st.set_page_config(page_title="AutoFill POC", layout="wide")

# ---------------- STATE ----------------
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if "last_result" not in st.session_state:
    st.session_state.last_result = {}

if "pending_field" not in st.session_state:
    st.session_state.pending_field = None

st.title("AutoFill Request POC")

PROMPTABLE_FIELDS = ["title", "keyAuthor", "fileType", "formatType", "expDatetime"]

PDF_EXTENSIONS = {".pdf"}
VIDEO_EXTENSIONS = {".mp4", ".mpeg", ".mpg", ".mov", ".webm", ".avi", ".mkv"}
OFFICE_EXTENSIONS = {".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}
PDF_TYPES = {"application/pdf"}
VIDEO_TYPES = {"video/mp4", "video/mpeg", "video/quicktime", "video/webm", "video/x-msvideo", "video/x-matroska"}
OFFICE_TYPES = {
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def _file_extension(filename):
    if not filename or "." not in filename:
        return ""
    return "." + filename.rsplit(".", 1)[-1].lower()


def _file_kind(file):
    content_type = (getattr(file, "type", "") or "").lower()
    extension = _file_extension(getattr(file, "name", ""))
    if content_type in PDF_TYPES or extension in PDF_EXTENSIONS:
        return "pdf"
    if content_type in VIDEO_TYPES or extension in VIDEO_EXTENSIONS:
        return "video"
    if content_type in OFFICE_TYPES or extension in OFFICE_EXTENSIONS:
        return "office"
    return "other"


def _resolve_format_from_files(files):
    kinds = [_file_kind(file) for file in (files or [])]
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


def _question_for_field(field_name: str, files) -> str:
    if field_name == "title":
        return "Please enter the title."
    #if  field_name == "expDatetime":
        return "Please enter the expiry date."
    if field_name == "keyAuthor":
        return "Please enter the author name."
    if field_name in {"fileType", "formatType"}:
        return "Please tell me the format: `pdf`, `ebook`, `ebook+ video`, `video`, or `MS Office`."
    if field_name == "chapter":
        file_count = len(files or [])
        if file_count > 1:
            return (
                f"Please provide {file_count} chapter name(s), one for each uploaded PDF, "
                "for example: Chapters: Introduction, Methods, Conclusion."
            )
        return "Please provide the chapter name for the uploaded ebook PDF."
    return f"Please enter the {field_name.replace('_', ' ')}."


def _parse_chapter_reply(reply: str):
    pieces = []
    normalized = reply.strip()
    if ":" in normalized and normalized.lower().startswith("chap"):
        normalized = normalized.split(":", 1)[1]

    for piece in re.split(r"[,;|]", normalized):
        cleaned = piece.strip(" .-_")
        if cleaned:
            pieces.append({"chapterTitle": cleaned})
    return pieces


def _chapter_titles(chapter_value):
    if not isinstance(chapter_value, list):
        return []
    titles = []
    for item in chapter_value:
        if isinstance(item, dict):
            titles.append(str(item.get("chapterTitle") or ""))
        elif isinstance(item, str):
            titles.append(item)
    return titles


def _build_chapters_for_files(files, mapped_fields):
    titles = _chapter_titles(mapped_fields.get("chapter"))
    chapters = []

    for index, file in enumerate(files or []):
        file_name = getattr(file, "name", "") or ""
        kind = _file_kind(file)
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


def _remove_stale_resolution_messages(result, resolved_fields):
    result["unresolved_fields"] = [
        field for field in result.get("unresolved_fields", [])
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
    result["warnings"] = [
        warning for warning in result.get("warnings", [])
        if not any(fragment in str(warning).lower() for fragment in fragments)
    ]


def _apply_pending_value(field_name: str, reply: str):
    if field_name == "chapter":
        return _parse_chapter_reply(reply)
    if field_name in {"fileType", "formatType"}:
        normalized = reply.strip().lower()
        if normalized in {"e-book", "e book"}:
            normalized = "ebook"
        if normalized in {"ebook video", "ebook+video", "ebook + video"}:
            normalized = "ebook+ video"
        if normalized in {"ms office", "microsoft office", "office", "word", "excel", "powerpoint"}:
            normalized = "MS Office"
        if normalized in {"pdf", "ebook", "ebook+ video", "video", "MS Office"}:
            return normalized
    return reply


def _looks_like_multi_field_reply(reply: str) -> bool:
    lowered = reply.lower()
    signal_words = [
        "title",
        "author",
        "format",
        "pdf",
        "ebook",
        "video",
        "office",
        "expiry",
        "expiration",
        "expire",
    ]
    matches = sum(1 for word in signal_words if word in lowered)
    return matches >= 2 or len(reply.split()) > 6

uploaded_files = st.file_uploader(
    "Upload Files",
    accept_multiple_files=True
)

prompt = st.chat_input("Enter your prompt...")

# ---------------- PROCESS ----------------

def process_prompt(user_prompt, files, existing_values=None):
    """We have to Process the user prompt using the local LLM client with ollama.
    The function keeps the original signature for compatibility but ignores the
    `files` argument (the current workflow does not need file uploads for the
    metadata extraction). It delegates to `matcher1.extract_metadata`, which
    handles the LLM call, post‑processing, and returns a dict containing
    `mapped_fields`, `unresolved_fields` and `warnings`.
    """
    existing_values = existing_values or {}
    # Call the new LLM‑driven extraction helper  function 
    result = extract_metadata(user_prompt, existing_values)

    mapped_fields = result.get("mapped_fields", {}) or {}
    detected_format = _resolve_format_from_files(files)
    if detected_format:
        mapped_fields["fileType"] = detected_format
        mapped_fields["formatType"] = detected_format
        result["mapped_fields"] = mapped_fields
        _remove_stale_resolution_messages(result, {"fileType", "formatType"})

    normalized_format = str(
        mapped_fields.get("fileType") or mapped_fields.get("formatType") or ""
    ).strip().lower()
    file_count = len(files or [])
    pdf_count = sum(1 for file in (files or []) if _file_kind(file) == "pdf")
    video_count = sum(1 for file in (files or []) if _file_kind(file) == "video")

    if normalized_format == "pdf" and pdf_count != 1:
        result.setdefault("warnings", []).append(
            "PDF format expects exactly one uploaded PDF."
        )

    if normalized_format in {"ebook", "ebook+ video"}:
        mapped_fields["chapter"] = _build_chapters_for_files(files, mapped_fields)
        result["mapped_fields"] = mapped_fields
        _remove_stale_resolution_messages(result, {"chapter"})

    if normalized_format == "ebook":
        if pdf_count <= 1:
            result.setdefault("warnings", []).append(
                "Ebook format expects multiple uploaded PDFs."
            )

    if normalized_format == "video" and video_count != 1:
        result.setdefault("warnings", []).append(
            "Video format expects exactly one uploaded video."
        )

    result["unresolved_fields"] = list(dict.fromkeys(result.get("unresolved_fields", [])))
    result["warnings"] = list(dict.fromkeys(result.get("warnings", [])))
    return result


# ---------------- MAIN FLOW ----------------
if prompt:
    # Save user message
    st.session_state.chat_history.append({"role": "user", "content": prompt})

    # If we were waiting for a specific field, update it directly
    current_prompt = prompt
    current_existing_values = dict(st.session_state.last_result)
    if st.session_state.pending_field:
        field_to_fill = st.session_state.pending_field
        if not _looks_like_multi_field_reply(prompt):
            resolved_value = _apply_pending_value(field_to_fill, prompt)
            current_existing_values[field_to_fill] = resolved_value
            if field_to_fill in {"fileType", "formatType"}:
                current_existing_values["fileType"] = resolved_value
                current_existing_values["formatType"] = resolved_value
        st.session_state.pending_field = None

    # Assistant response
    with st.chat_message("assistant"):
        with st.spinner("Processing..."):
            try:
                result = process_prompt(
                    current_prompt, 
                    uploaded_files, 
                    current_existing_values
                )
                st.session_state.current_api_response = result
                
                promptable_missing = [
                    field for field in result.get("unresolved_fields", [])
                    if field in PROMPTABLE_FIELDS
                ]

                # Ask follow-up only for title, author, and format.
                if promptable_missing:
                    missing = promptable_missing[0]
                    st.session_state.pending_field = missing
                    
                    bot_msg = _question_for_field(missing, uploaded_files)
                    st.info(bot_msg)
                    st.session_state.chat_history.append({"role": "assistant", "content": bot_msg})
                else:
                    st.session_state.pending_field = None
                    st.success("All data have been extracted successfully.")
                    st.session_state.chat_history.append({"role": "assistant", "content": "All parameters have been captured."})

                if result.get("warnings"):
                    for warning in result["warnings"]:
                        st.warning(warning)

                # Update global state
                if result.get("mapped_fields"):
                    st.session_state.last_result.update(result["mapped_fields"])

            except Exception as e:
                st.error(f"Error: {e}")

if "current_api_response" in st.session_state:
    result = st.session_state.current_api_response

    # -------- EXTRACTED FIELDS --------
    if result.get("mapped_fields"):
        with st.sidebar:
            st.write("### Current Metadata")
            # We show everything that has a value
            active_fields = {k: v for k, v in result["mapped_fields"].items() if v is not None}
            st.json(active_fields)

    # -------- RAW PARSED JSON (FULL SCHEMA) --------
    if result.get("mapped_fields"):
        with st.expander("🧾 Full Schema (JSON)"):
            st.json(result["mapped_fields"])


# ---------------- RENDER CHAT ----------------
for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.write(msg["content"])


# ---------------- SIDEBAR ----------------
if uploaded_files:
    st.sidebar.title("Uploaded Files")
    for file in uploaded_files:
        st.sidebar.write(f"- {file.name}")
