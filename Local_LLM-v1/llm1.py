from __future__ import annotations

import json
import os 
import re
import httpx
from urllib.parse import urlparse
from typing import Any , Dict, List, Optional
from schema1 import AutofillRequest
from schema1 import FormFieldUpdate  


class LocalLLMClient:
    def __init__(self ,base_url:str = None, model:str = "qwen2.5:7b"):
        resolved_base = (base_url or os.getenv("LOCAL_LLM_BASE_URL") or "http://localhost:11434").rstrip("/")
        self.base_url = self._validate_local_base_url(resolved_base)
        self.model = os.getenv("LLM_MODEL", model)
        self.timeout=60000.0

    @property
    def chat_url(self) -> str:
        return f"{self.base_url}/api/chat"

    def is_configured(self) -> bool:
        return bool(self.base_url and self.model)

    def is_reachable(self) -> bool:
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(f"{self.base_url}/api/tags")
                response.raise_for_status()
            return True
        except Exception:
            return False

    def _validate_local_base_url(self, url: str) -> str:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        allowed_hosts = {"localhost", "127.0.0.1", "::1"}
        if host not in allowed_hosts:
            raise ValueError(
                f"Only local Ollama is allowed. Invalid LOCAL_LLM_BASE_URL host: '{host}'"
            )
        return url
    

    async def extract_fields(self, payload:AutofillRequest)-> Dict[str , Any]:
        try: 
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                body = self._prepare_request_body(payload)

                response = await client.post(self.chat_url, json=body)
                response.raise_for_status()

                data = response.json()
                content = data.get("message", {}).get("content", "")

                print("\n===== LLM RAW RESPONSE =====")
                print(content)
                print("Done !!")
                parsed = self._parse_json(content)

                print("\n===== PARSED JSON =====")
                print(parsed)

                if parsed and isinstance(parsed.get("mapped_fields"), dict):
                    parsed_fields = parsed.get("mapped_fields", {})
                    try:
                        validated = FormFieldUpdate(**parsed_fields)

                        return {
                            "mapped_fields": validated.model_dump(),
                            "analysis_summary":parsed.get("analysis_summary", ""),
                            "raw_parsed": parsed
                            }
                    except Exception as e:
                        return {
                            "mapped_fields": parsed_fields,
                            "analysis_summary": str(e),
                            "raw_parsed": parsed if 'parsed' in locals() else {}
                        }
                return self._fallback_extract(payload.prompt)
            
           

        except Exception as e:
            import traceback
            print("\n LLM ERROR FULL TRACE:")
            traceback.print_exc()
            return self._fallback_extract(payload.prompt)   


    def _prepare_request_body(self, payload:AutofillRequest) -> Dict[str, Any]:
        return {
            "model": self.model,
            "stream" : False,
            "format" : "json",
            "messages":[
                {"role":"system", "content": self.system_prompt()},
                {"role":"user", "content":self._build_prompt(payload)}
            ]
        }
    

    def system_prompt(self) -> str:
        return (
            "You are a metadata extraction engine.\n"
            "Your job is to extract structured data from user input and return ONLY valid JSON.\n"
            "Do not explain anything. Do not add extra text.\n\n"

            "You MUST always return ALL fields in the schema.\n"
            "If a value is missing, use an empty string \"\" (NOT null).\n\n"

            "Output JSON schema:\n"
            "{\n"
            '  "title": string,\n'
            '  "keyAuthor": string,\n'
            '  "fileType": "pdf" | "ebook" | "ebook+ video" | "video" | "MS Office",\n'
            '  "formatType": "pdf" | "ebook" | "ebook+ video" | "video" | "MS Office",\n'
            '  "chapter": string[],\n'
            '  "expDatetime": string\n'
            "}\n\n"

            "Extraction rules:\n"

            "1. TITLE:\n"
            "- Behave like a strict parser, not a conversational assistant.\n"
            "- Extract title ONLY from these patterns:\n"
            "  title 'X'\n"
            "  title \"X\"\n"
            "  title: X\n"
            "  titled X\n"
            "  named X\n"
            "  called X\n"
            "- Extract the exact value inside quotes when quotes are present.\n"
            "- Preserve underscores, numbers, punctuation, casing, and special characters exactly.\n"
            "- Do NOT modify, summarize, translate, or rephrase the title.\n"
            "- Example: uploading file title 'arun_123' -> title is arun_123.\n"
            "- Example: document named Data Science Guide -> title is Data Science Guide.\n"
            "- If not found, return \"\".\n\n"

            "2. AUTHOR:\n"
            "- Extract keyAuthor ONLY from these patterns:\n"
            "  author is X\n"
            "  by X\n"
            "- Stop author extraction at the first occurrence of any of these words or separators:\n"
            "  and\n"
            "  ,\n"
            "  with\n"
            "  expiry\n"
            "  date\n"
            "- Extract ONLY the author name. Do NOT include trailing words.\n"
            "- Example: author is shivam and expiry next year -> keyAuthor is shivam.\n"
            "- Example: by Rahul Sharma, valid till tomorrow -> keyAuthor is Rahul Sharma.\n"
            "- If neither author pattern is clearly matched, return \"\".\n\n"

            "3. FILE TYPE:\n"
            "- 'pdf' → pdf\n"
            "- 'ebook', 'book', 'e-book' → ebook\n"
            "- 'video' → video\n"
            "- 'ebook with video' → ebook+ video\n"
            "- Word, Excel, PowerPoint, doc/docx/xls/xlsx/ppt/pptx → MS Office\n"
            "- If unclear, return \"\".\n\n"

            "4. FORMAT TYPE:\n"
            "- Must be EXACTLY the same as fileType.\n\n"

            "5. CHAPTER:\n"
            "- Only for ebooks.\n"
            "- If no chapters → return [].\n\n"

            "6. EXPIRY DATETIME:\n"
            "- Detect phrases:\n"
            "  'valid till', 'valid until', 'expires on', 'expiry date'\n"
            "- Convert to format: YYYY-MM-DD HH:MM:SS\n"
            
            "- Example: '17th September 2027' → 2027-09-17 00:00:00\n"
            "- If not found → return \"\".\n\n"

            "STRICT RULES:\n"
            "- NEVER omit fields\n"
            "- NEVER return null\n"
            "- NEVER add explanations\n"
            "- ALWAYS return valid JSON\n"
            "- If a title or author pattern is not clearly matched, return \"\" for that field.\n"
            "- Do NOT guess. Do NOT infer.\n"
            "- Prioritize correctness over completeness; an empty string is better than incorrect extraction.\n\n"

            "Example:\n"
            "Input: I am uploading a pdf titled VWD Journey. It is valid till 17th September 2027.\n"
            "Output:\n"
            "{\n"
            '  "title": "VWD Journey",\n'
            '  "keyAuthor": "",\n'
            '  "fileType": "pdf",\n'
            '  "formatType": "pdf",\n'
            '  "chapter": [],\n'
            '  "expDatetime": "2027-09-17 00:00:00"\n'
            "}\n"
        )  
        
    def _build_prompt(self, payload: AutofillRequest) -> str:
                return f"""
        Extract metadata fields from the user prompt.

        Important rule:
        - Required fields are `title`, `keyAuthor`, and `fileType`.
        - Behave like a strict parser, not a conversational AI.
        - For `title`, extract ONLY from: title 'X', title "X", title: X, titled X, named X, called X.
        - Preserve the title exactly, including underscores, numbers, casing, and special characters.
        - For `keyAuthor`, extract ONLY from: author is X, by X.
        - Stop author extraction at the first occurrence of: and, comma, with, expiry, date.
        - If a title or author pattern is not clearly matched, return an empty string for that field.
        - `fileType` must be one of `pdf`, `ebook`, `ebook+ video`, `video`, or `MS Office`.
        - Also copy the same value into `formatType`.
        - If the requested format is ebook/e-book, include `chapter` as a list of objects with `chapterTitle`.
        - If chapter names are not present in the prompt, keep `chapter` empty and add that requirement in `analysis_summary`.
        - If the prompt includes an expiry/expiration date, return it in `expDatetime` as `YYYY-MM-DD HH:MM:SS`.
        - If the prompt includes relative expiry like `2 years`, `6 months`, or `30 days`, calculate `expDatetime` from now.
        - Never invent a missing title, author, or chapter name.
        - Do not guess or infer. Prioritize correctness over completeness.

        Prompt:
        {payload.prompt}

        Return JSON:
        {{
        "mapped_fields": {{
            "title": "value",
            "keyAuthor": "value",
            "fileType": "pdf, ebook, ebook+ video, video, or MS Office",
            "formatType": "pdf, ebook, ebook+ video, video, or MS Office",
            "expDatetime": "YYYY-MM-DD HH:MM:SS",
            "chapter": [{{"chapterTitle": "Chapter name"}}]
        }},
        "analysis_summary": "short explanation"
        }}
        """

    def _parse_json(self, content: str) -> Optional[Dict[str, Any]]:
        try:
            if not content:
                return None
                                                                  
            text = content.strip()
            decoder = json.JSONDecoder()

            # Prefer fenced JSON blocks if present.
            fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
            if fenced:
                fenced_text = fenced.group(1).strip()
                obj, _ = decoder.raw_decode(fenced_text)
                return obj if isinstance(obj, dict) else None

            # Otherwise decode from first '{' and stop at end of first JSON object.
            start = text.find("{")
            if start != -1:
                obj, _ = decoder.raw_decode(text[start:])
                return obj if isinstance(obj, dict) else None

            return None
        except Exception as e:
            print("JSON PARSE ERROR:", e)
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
            for piece in re.split(r"[,\|;]", list_match.group(1)):
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
        res = {}

        # smarter boolean detection
        if "no download" in lowered or "without download" in lowered:
            res["allowDownload"] = False
        elif "download" in lowered:
            res["allowDownload"] = True

        if "do not share" in lowered or "don't share" in lowered:
            res["allowShare"] = False
        elif "share" in lowered:
            res["allowShare"] = True

        # formats
        if any(token in lowered for token in ("docx", "doc", "xlsx", "xls", "pptx", "ppt", "excel", "powerpoint", "ms office", "microsoft office")):
            res["fileType"] = "MS Office"
            res["formatType"] = "MS Office"
        elif ("ebook" in lowered or "e-book" in lowered or "e book" in lowered) and "video" in lowered:
            res["fileType"] = "ebook+ video"
            res["formatType"] = "ebook+ video"
            chapter_titles = self._extract_chapter_titles(prompt)
            if chapter_titles:
                res["chapter"] = [{"chapterTitle": title} for title in chapter_titles]
        elif "video" in lowered:
            res["fileType"] = "video"
            res["formatType"] = "video"
        elif "ebook" in lowered or "e-book" in lowered or "e book" in lowered:
            res["fileType"] = "ebook"
            res["formatType"] = "ebook"
            chapter_titles = self._extract_chapter_titles(prompt)
            if chapter_titles:
                res["chapter"] = [{"chapterTitle": title} for title in chapter_titles]
        elif "pdf" in lowered:
            res["fileType"] = "pdf"
            res["formatType"] = "pdf"

        title_match = re.search(
            r"title\s*(?:[:\-]|is|would be|will be|=)?\s*([^\n,;|]+)",
            prompt,
            flags=re.IGNORECASE,
        )
        if title_match:
            extracted_title = title_match.group(1).strip(" .-_")
            extracted_title = re.split(
                r"\b(?:author|by|expiry|expiration|format|pdf|ebook)\b",
                extracted_title,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].strip(" .-_")
            if extracted_title:
                res["title"] = extracted_title

        author_match = re.search(
            r"(?:author|written by|by)\s*(?:[:\-]|is|would be|will be|=)?\s*([^\n,;|]+)",
            prompt,
            flags=re.IGNORECASE,
        )
        if author_match:
            extracted_author = author_match.group(1).strip(" .-_")
            extracted_author = re.split(
                r"\b(?:title|expiry|expiration|format|pdf|ebook)\b",
                extracted_author,
                maxsplit=1,
                flags=re.IGNORECASE,
            )[0].strip(" .-_")
            if extracted_author:
                res["keyAuthor"] = extracted_author

        return {
            "mapped_fields": res,
            "analysis_summary": "fallback extraction used",
            "raw_parsed": {}
        }
