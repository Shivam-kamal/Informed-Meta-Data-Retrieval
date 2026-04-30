from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, File, Form, UploadFile

from conversation import (
    ConversationStore,
    apply_pending_answer,
    build_bot_message,
    choose_next_field,
    merge_mapped_fields,
    merge_memory,
    missing_required_fields,
)
from documents import (
    add_upload_warnings,
    apply_file_overrides,
    collect_document_details,
    collect_file_details,
    document_info,
    safe_parse_existing_values,
    try_collect_document_details,
)
from llm import OpenAILLMClient
from pipeline import MetadataPipeline, message_for_extraction
from schema import (
    AutofillRequest,
    ChatbotMetadataRequest,
    ChatbotMetadataResponse,
    CombinedResponse,
    ConversationTurnRequest,
    ConversationTurnResponse,
    HealthResponse,
    PromptContext,
)


def create_router(
    llm_client: OpenAILLMClient,
    conversation_store: ConversationStore,
) -> APIRouter:
    router = APIRouter()
    pipeline = MetadataPipeline(llm_client)

    @router.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(
            llm_configured=llm_client.is_configured(),
            llm_endpoint=llm_client.base_url or "https://api.openai.com/v1",
            llm_endpoint_reachable=llm_client.is_reachable(),
        )

    @router.post("/upload-and-analysis", response_model=CombinedResponse)
    async def upload_and_analyze(
        files: Annotated[list[UploadFile], File(...)],
        prompt: str = Form(...),
        existing_values: Optional[str] = Form(None),
    ) -> CombinedResponse:
        file_details = await collect_file_details(files)
        past_metadata = safe_parse_existing_values(existing_values)
        payload = AutofillRequest(
            prompt=prompt,
            context=PromptContext(),
            existing_values=past_metadata,
        )

        try:
            raw_fields, analysis = await pipeline.analyze_prompt(payload)
        except Exception:
            raw_fields = {"raw_parsed": {}, "unresolved_fields": []}
            return _empty_upload_response(file_details, raw_fields, "Matcher failed")

        if not analysis:
            return _empty_upload_response(file_details, raw_fields, "Empty analysis")

        apply_file_overrides(analysis, file_details)
        add_upload_warnings(analysis, file_details)

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

    @router.post("/chatbot-analysis", response_model=ChatbotMetadataResponse)
    async def chatbot_analysis(request: ChatbotMetadataRequest) -> ChatbotMetadataResponse:
        document_details = collect_document_details(request.document_names)
        payload = AutofillRequest(
            prompt=request.prompt,
            context=request.context,
            existing_values=request.existing_values,
            account_id=request.account_id,
            strict_mode=request.strict_mode,
        )

        try:
            raw_fields, analysis = await pipeline.analyze_prompt(payload)
        except Exception:
            raw_fields = {"raw_parsed": {}, "unresolved_fields": []}
            return _empty_chatbot_response(document_details, raw_fields, "Matcher failed")

        if not analysis:
            return _empty_chatbot_response(document_details, raw_fields, "Empty analysis")

        apply_file_overrides(analysis, document_details)
        add_upload_warnings(analysis, document_details)

        for detail in document_details:
            detail["status"] = f"Received {len(document_details)} document name(s)"

        return ChatbotMetadataResponse(
            document_info=document_info(document_details),
            comments=getattr(analysis, "comments", []),
            mapped_fields=getattr(analysis, "mapped_fields", {}),
            unresolved_fields=getattr(analysis, "unresolved_fields", []),
            warnings=getattr(analysis, "warnings", []),
            confidence=getattr(analysis, "confidence", 0.0),
            raw_parsed=raw_fields.get("raw_parsed", {}),
        )

    @router.post("/conversation/turn", response_model=ConversationTurnResponse)
    async def conversation_turn(request: ConversationTurnRequest) -> ConversationTurnResponse:
        session_id, stored_memory = conversation_store.get(request.session_id)
        memory = merge_memory(
            stored_memory=stored_memory,
            request_memory=request.memory,
            existing_values=request.existing_values,
            document_names=request.document_names,
        )

        apply_pending_answer(memory, request.message)

        document_details = try_collect_document_details(memory.document_names)
        extraction_message = message_for_extraction(request.message, memory.pending_field)
        payload = AutofillRequest(
            prompt=extraction_message,
            context=request.context,
            existing_values=memory.metadata,
            account_id=request.account_id,
            strict_mode=request.strict_mode,
        )

        try:
            raw_fields, analysis = await pipeline.analyze_prompt(payload)
        except Exception:
            memory.turn_count += 1
            conversation_store.save(session_id, memory)
            return ConversationTurnResponse(
                session_id=session_id,
                bot_message="I could not process that message. Please try again.",
                next_action="error",
                pending_field=memory.pending_field,
                missing_fields=[],
                memory=memory,
                document_info=document_info(document_details),
                mapped_fields=memory.metadata,
                warnings=["Matcher failed"],
                confidence=0.0,
                raw_parsed={},
            )

        if analysis and document_details:
            apply_file_overrides(analysis, document_details)
            add_upload_warnings(analysis, document_details)

        mapped_fields = getattr(analysis, "mapped_fields", {}) if analysis else {}
        merge_mapped_fields(memory, mapped_fields)

        missing_fields = missing_required_fields(memory.metadata, memory.document_names)
        next_field = choose_next_field(missing_fields, memory.asked_fields)
        bot_message = build_bot_message(next_field)

        memory.pending_field = next_field
        if next_field and next_field not in memory.asked_fields:
            memory.asked_fields.append(next_field)
        if not next_field:
            memory.pending_field = None
        memory.turn_count += 1

        for detail in document_details:
            detail["status"] = f"Received {len(document_details)} document name(s)"

        conversation_store.save(session_id, memory)

        return ConversationTurnResponse(
            session_id=session_id,
            bot_message=bot_message,
            next_action="ask_user" if next_field else "ready",
            pending_field=memory.pending_field,
            missing_fields=missing_fields,
            memory=memory,
            document_info=document_info(document_details),
            mapped_fields=memory.metadata,
            warnings=getattr(analysis, "warnings", []) if analysis else [],
            confidence=getattr(analysis, "confidence", 0.0) if analysis else 0.0,
            raw_parsed=raw_fields.get("raw_parsed", {}),
        )

    return router


def _empty_upload_response(file_details: list[dict], raw_fields: dict, warning: str) -> CombinedResponse:
    return CombinedResponse(
        file_info=file_details[0],
        files_info=file_details,
        comments=[],
        mapped_fields={},
        unresolved_fields=raw_fields.get("unresolved_fields", []),
        warnings=[warning],
        confidence=0.0,
        raw_parsed=raw_fields.get("raw_parsed", {}),
    )


def _empty_chatbot_response(
    document_details: list[dict],
    raw_fields: dict,
    warning: str,
) -> ChatbotMetadataResponse:
    return ChatbotMetadataResponse(
        document_info=document_info(document_details),
        comments=[],
        mapped_fields={},
        unresolved_fields=raw_fields.get("unresolved_fields", []),
        warnings=[warning],
        confidence=0.0,
        raw_parsed=raw_fields.get("raw_parsed", {}),
    )
