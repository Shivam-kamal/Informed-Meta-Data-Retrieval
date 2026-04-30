from __future__ import annotations

from llm import OpenAILLMClient
from matcher import FormMatcher
from schema import AutofillRequest


class MetadataPipeline:
    """Coordinates model extraction and deterministic matcher cleanup."""

    def __init__(self, llm_client: OpenAILLMClient) -> None:
        self.llm_client = llm_client

    async def analyze_prompt(self, payload: AutofillRequest):
        raw_fields = await self.llm_client.extract_fields(payload)
        if not isinstance(raw_fields, dict) or not isinstance(raw_fields.get("mapped_fields"), dict):
            raw_fields = {
                "mapped_fields": {},
                "analysis_summary": None,
                "raw_parsed": raw_fields.get("raw_parsed", {}) if isinstance(raw_fields, dict) else {},
            }

        matcher = FormMatcher(payload.context)
        analysis = matcher.post_process(
            prompt=payload.prompt,
            llm_output=raw_fields,
            existing_values=payload.existing_values,
        )
        return raw_fields, analysis


def message_for_extraction(message: str, pending_field: str | None) -> str:
    clean = message.strip()
    if not pending_field or not clean:
        return message
    if pending_field == "title":
        return f"title: {clean}"
    if pending_field == "keyAuthor":
        return f"author is {clean}"
    if pending_field == "fileType":
        return clean
    if pending_field == "chapter":
        return f"chapters: {clean}"
    return message
