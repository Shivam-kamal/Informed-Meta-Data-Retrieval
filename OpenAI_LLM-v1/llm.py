from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, List, Optional

try:
    from openai import AsyncOpenAI, OpenAI
except ImportError:  # Allows fallback extraction before dependencies are installed.
    AsyncOpenAI = None
    OpenAI = None

from schema import AutofillRequest, FormFieldUpdate


class OpenAILLMClient:
    """OpenAI-backed metadata extractor with a regex fallback."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL")
        self.timeout = float(os.getenv("OPENAI_TIMEOUT", "60"))

        client_kwargs: Dict[str, Any] = {"api_key": self.api_key, "timeout": self.timeout}
        if self.base_url:
            client_kwargs["base_url"] = self.base_url.rstrip("/")

        self.client = AsyncOpenAI(**client_kwargs) if self.api_key and AsyncOpenAI else None
        self.sync_client = OpenAI(**client_kwargs) if self.api_key and OpenAI else None

    def is_configured(self) -> bool:
        return bool(self.api_key and self.model and AsyncOpenAI)

    def is_reachable(self) -> bool:
        if not self.sync_client:
            return False
        try:
            self.sync_client.models.retrieve(self.model)
            return True
        except Exception:
            return False

    async def extract_fields(self, payload: AutofillRequest) -> Dict[str, Any]:
        if not self.client:
            return self._fallback_extract(payload.prompt)

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt()},
                    {"role": "user", "content": self._build_prompt(payload)},
                ],
                response_format={"type": "json_object"},
                temperature=0,
            )
            content = response.choices[0].message.content or ""
            parsed = self._parse_json(content)

            if parsed and isinstance(parsed.get("mapped_fields"), dict):
                parsed_fields = parsed["mapped_fields"]
                try:
                    validated = FormFieldUpdate(**parsed_fields)
                    mapped_fields = validated.model_dump()
                except Exception:
                    mapped_fields = parsed_fields

                return {
                    "mapped_fields": mapped_fields,
                    "analysis_summary": parsed.get("analysis_summary", ""),
                    "raw_parsed": parsed,
                }

            return self._fallback_extract(payload.prompt)
        except Exception as exc:
            fallback = self._fallback_extract(payload.prompt)
            fallback["analysis_summary"] = f"OpenAI extraction failed; fallback used: {exc}"
            return fallback

    def system_prompt(self) -> str:
        return (
            "You are a strict metadata extraction engine.\n"
            "Return only valid JSON. Do not add markdown or explanations.\n"
            "Never guess missing title, author, format, or chapter data.\n"
            "Use empty strings for missing scalar values and [] for missing lists.\n"
            "Supported formats are exactly: pdf, ebook, ebook+ video, video, MS Office.\n"
            "formatType must mirror fileType when fileType is known."
        )

    def _build_prompt(self, payload: AutofillRequest) -> str:
        return f"""
Extract metadata fields from the user prompt.

Rules:
- Required fields are title, keyAuthor, and fileType.
- Extract title only from: title 'X', title "X", title: X, titled X, named X, called X.
- Preserve title casing, punctuation, numbers, underscores, and special characters exactly.
- Extract keyAuthor only from: author is X, written by X, by X.
- Stop author extraction at: and, comma, with, expiry, expiration, date.
- fileType must be one of: pdf, ebook, ebook+ video, video, MS Office.
- Copy fileType into formatType.
- For ebook/e-book requests, return chapter as a list of objects with chapterTitle.
- If chapter names are missing, keep chapter empty and mention it in analysis_summary.
- Convert expiry dates to YYYY-MM-DD HH:MM:SS.
- For relative expiry like 2 years, 6 months, or 30 days, return the phrase or calculated date if clear.
- Do not infer values that are not stated.

Existing values:
{json.dumps(payload.existing_values, ensure_ascii=True)}

User prompt:
{payload.prompt}

Return this JSON shape:
{{
  "mapped_fields": {{
    "title": "",
    "keyAuthor": "",
    "fileType": "",
    "formatType": "",
    "expDatetime": "",
    "chapter": []
  }},
  "analysis_summary": ""
}}
"""

    def _parse_json(self, content: str) -> Optional[Dict[str, Any]]:
        if not content:
            return None

        text = content.strip()
        decoder = json.JSONDecoder()
        try:
            fenced = re.search(
                r"```(?:json)?\s*(\{.*?\})\s*```",
                text,
                flags=re.DOTALL | re.IGNORECASE,
            )
            if fenced:
                obj, _ = decoder.raw_decode(fenced.group(1).strip())
                return obj if isinstance(obj, dict) else None

            start = text.find("{")
            if start == -1:
                return None

            obj, _ = decoder.raw_decode(text[start:])
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None

    def _extract_chapter_titles(self, prompt: str) -> List[str]:
        titles: List[str] = []
        numbered_matches = re.findall(
            r"chapter\s*\d*\s*[:\-]\s*([^\n,;|]+)",
            prompt,
            flags=re.IGNORECASE,
        )
        titles.extend(match.strip(" .-_") for match in numbered_matches if match.strip())

        list_match = re.search(r"chapters?\s*[:\-]\s*([^\n]+)", prompt, flags=re.IGNORECASE)
        if list_match:
            for piece in re.split(r"[,|;]", list_match.group(1)):
                cleaned = piece.strip(" .-_")
                if cleaned:
                    titles.append(cleaned)

        deduped: List[str] = []
        seen = set()
        for title in titles:
            key = title.lower()
            if key not in seen:
                deduped.append(title)
                seen.add(key)
        return deduped

    def _fallback_extract(self, prompt: str) -> Dict[str, Any]:
        lowered = prompt.lower()
        mapped_fields: Dict[str, Any] = {}

        if "no download" in lowered or "without download" in lowered:
            mapped_fields["allowDownload"] = False
        elif "download" in lowered:
            mapped_fields["allowDownload"] = True

        if "do not share" in lowered or "don't share" in lowered:
            mapped_fields["allowShare"] = False
        elif "share" in lowered:
            mapped_fields["allowShare"] = True

        if any(
            token in lowered
            for token in (
                "docx",
                "doc",
                "xlsx",
                "xls",
                "pptx",
                "ppt",
                "excel",
                "powerpoint",
                "ms office",
                "microsoft office",
            )
        ):
            mapped_fields["fileType"] = "MS Office"
        elif ("ebook" in lowered or "e-book" in lowered or "e book" in lowered) and "video" in lowered:
            mapped_fields["fileType"] = "ebook+ video"
        elif "video" in lowered:
            mapped_fields["fileType"] = "video"
        elif "ebook" in lowered or "e-book" in lowered or "e book" in lowered:
            mapped_fields["fileType"] = "ebook"
        elif "pdf" in lowered:
            mapped_fields["fileType"] = "pdf"

        if "fileType" in mapped_fields:
            mapped_fields["formatType"] = mapped_fields["fileType"]

        chapter_titles = self._extract_chapter_titles(prompt)
        if chapter_titles:
            mapped_fields["chapter"] = [{"chapterTitle": title} for title in chapter_titles]

        title_match = re.search(
            r"(?:titled|title\s*(?:[:=\-]|is)?|named|called)\s*[\"']?([^\n,;|]+)",
            prompt,
            flags=re.IGNORECASE,
        )
        if title_match:
            title = title_match.group(1).strip(" .-_\"'")
            if title:
                mapped_fields["title"] = title

        author_match = re.search(
            r"(?:author\s*(?:[:=\-]|is)?|written by|by)\s*[\"']?([^\n,;|]+)",
            prompt,
            flags=re.IGNORECASE,
        )
        if author_match:
            author = re.split(
                r"\b(?:and|with|expiry|expiration|date|title|format|pdf|ebook)\b",
                author_match.group(1),
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].strip(" .-_\"'")
            if author:
                mapped_fields["keyAuthor"] = author

        return {
            "mapped_fields": mapped_fields,
            "analysis_summary": "fallback extraction used",
            "raw_parsed": {},
        }
