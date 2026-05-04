from __future__ import annotations

import json
from uuid import uuid4

import streamlit as st

from app.models.schemas import FRONTEND_METADATA_TEMPLATE
from app.models.state import ChatState, Message
from app.workflow.graph import run_workflow


EMPTY_VALUES = (None, "", [], {})


def _full_metadata(metadata: dict | None) -> dict:
    metadata = metadata or {}
    return {key: metadata.get(key) for key in FRONTEND_METADATA_TEMPLATE}


def _merge_metadata(previous_metadata: dict | None, request_metadata: dict | None) -> dict:
    merged = _full_metadata(previous_metadata)

    for key, value in _full_metadata(request_metadata).items():
        if value not in EMPTY_VALUES:
            merged[key] = value

    return merged


def _filled_metadata(metadata: dict) -> dict:
    return {key: value for key, value in metadata.items() if value not in EMPTY_VALUES}


def _parse_json_metadata(raw_metadata: str) -> tuple[dict | None, str | None]:
    if not raw_metadata.strip():
        return {}, None

    try:
        parsed = json.loads(raw_metadata)
    except json.JSONDecodeError as exc:
        return None, f"Metadata JSON is invalid: {exc.msg} at line {exc.lineno}, column {exc.colno}."

    if not isinstance(parsed, dict):
        return None, "Metadata JSON must be an object."

    return parsed, None


def _reset_session() -> None:
    st.session_state.session_id = str(uuid4())
    st.session_state.messages = []
    st.session_state.metadata = _full_metadata({})
    st.session_state.documents = []
    st.session_state.pending_field = None
    st.session_state.pending_question = None
    st.session_state.missing_fields = []
    st.session_state.warnings = []
    st.session_state.next_action = "ready"
    st.session_state.metadata_json = json.dumps(st.session_state.metadata, indent=2)


def _ensure_session() -> None:
    if "session_id" not in st.session_state:
        _reset_session()


def _run_chat(message: str, request_metadata: dict, documents: list[str]) -> None:
    messages: list[Message] = list(st.session_state.messages)
    messages.append({"role": "user", "content": message})

    metadata = _merge_metadata(st.session_state.metadata, request_metadata)
    state: ChatState = {
        "session_id": st.session_state.session_id,
        "user_message": message,
        "documents": documents,
        "metadata": metadata,
        "messages": messages[-5:],
        "pending_field": st.session_state.pending_field,
        "pending_question": st.session_state.pending_question,
        "missing_fields": st.session_state.missing_fields,
    }

    result = run_workflow(state)
    if result.get("bot_message"):
        result["messages"] = [
            *result.get("messages", []),
            {"role": "assistant", "content": result["bot_message"]},
        ][-5:]

    st.session_state.messages = result.get("messages", [])
    st.session_state.metadata = _full_metadata(result.get("metadata", {}))
    st.session_state.documents = documents
    st.session_state.pending_field = result.get("pending_field")
    st.session_state.pending_question = result.get("pending_question")
    st.session_state.missing_fields = result.get("missing_fields", [])
    st.session_state.warnings = result.get("warnings", [])
    st.session_state.next_action = result.get("next_action", "ready")
    st.session_state.metadata_json = json.dumps(st.session_state.metadata, indent=2, default=str)


def main() -> None:
    st.set_page_config(page_title="AutoFill Engine", layout="wide")
    _ensure_session()

    st.title("AutoFill Engine")

    with st.sidebar:
        st.caption(f"Session: {st.session_state.session_id}")
        if st.button("New session", use_container_width=True):
            _reset_session()
            st.rerun()

        st.subheader("Documents")
        uploaded_files = st.file_uploader(
            "Upload or pick files",
            accept_multiple_files=True,
            help="Only filenames are sent to the metadata workflow.",
        )
        uploaded_names = [file.name for file in uploaded_files]
        manual_documents = st.text_area(
            "Extra filenames",
            value="\n".join(name for name in st.session_state.documents if name not in uploaded_names),
            placeholder="brochure.pdf\ncover.png",
        )
        manual_names = [line.strip() for line in manual_documents.splitlines() if line.strip()]
        documents = list(dict.fromkeys([*uploaded_names, *manual_names]))

        st.subheader("Status")
        st.write(f"Next action: `{st.session_state.next_action}`")
        if st.session_state.pending_question:
            st.info(st.session_state.pending_question)
        if st.session_state.missing_fields:
            st.warning("Missing: " + ", ".join(st.session_state.missing_fields))
        if st.session_state.warnings:
            for warning in st.session_state.warnings:
                st.warning(warning)

    metadata_col, chat_col = st.columns([1, 1], gap="large")

    with metadata_col:
        st.subheader("Metadata")
        raw_metadata = st.text_area(
            "Paste or edit metadata JSON",
            key="metadata_json",
            height=520,
            help="Paste once here. The UI keeps it for this session and updates it after each reply.",
        )
        parsed_metadata, metadata_error = _parse_json_metadata(raw_metadata)
        if metadata_error:
            st.error(metadata_error)
        else:
            filled = _filled_metadata(_merge_metadata(st.session_state.metadata, parsed_metadata))
            st.caption(f"{len(filled)} fields filled")
            st.json(filled or {})

    with chat_col:
        st.subheader("Chat")
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.write(message["content"])

        with st.form("chat_form", clear_on_submit=True):
            user_message = st.text_area(
                "Message",
                placeholder="Send metadata details or answer the next question",
                height=120,
            )
            submitted = st.form_submit_button("Send", use_container_width=True)

        if submitted and user_message.strip():
            parsed_metadata, metadata_error = _parse_json_metadata(st.session_state.metadata_json)
            if metadata_error:
                st.error(metadata_error)
            else:
                _run_chat(user_message.strip(), parsed_metadata or {}, documents)
                st.rerun()


if __name__ == "__main__":
    main()
