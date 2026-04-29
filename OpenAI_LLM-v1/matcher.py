from __future__ import annotations

from difflib import SequenceMatcher, get_close_matches
from statistics import mean
from typing import Any, Dict, Iterable, List, Optional, Tuple
import re
from datetime import datetime
from dateutil.relativedelta import relativedelta
from dateutil.parser import isoparse

from schema import ExtractionResult, FieldEvidence, FormFieldUpdate, PromptContext
import json
import os
from dateutil import parser
try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

# ---------------------------------------------------------------------------
# LLM client wrapper used by the optional extract_metadata helper.
def _llm_chat(messages: list[dict], model: str | None = None) -> str:
    """Send a chat request through the OpenAI API."""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")
    if not OpenAI:
        raise RuntimeError("openai package is not installed")

    client_kwargs: Dict[str, Any] = {"api_key": api_key}
    base_url = os.getenv("OPENAI_BASE_URL")
    if base_url:
        client_kwargs["base_url"] = base_url.rstrip("/")

    client = OpenAI(**client_kwargs)
    response = client.chat.completions.create(
        model=model or os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        messages=messages,
        response_format={"type": "json_object"},
        temperature=0,
    )
    return response.choices[0].message.content or ""

BOOLEAN_HINTS = {
    "allowShare": [("do not share", False), ("don't share", False), ("share", True)],
    "allowDownload": [("no download", False), ("without download", False), ("download", True)],
    "allowPrint": [("no print", False), ("without print", False), ("print", True)],
    "allowVideo": [("embed video", True), ("video", True)],
    "allowDraft": [("draft", True)],
    "allowOneSource": [("onesource", True), ("one source", True)],
    "allowRequest": [("request", True), ("quote", True)],
    "request_quote": [("request quote", True), ("quotation", True)],
    "sync_onesource": [("sync onesource", True)],
    "pushed_vwdJourney": [("vwd", True), ("journey", True)],
    "pushed_usa_flag": [("usa", True)],
    "hideHCP": [("hide hcp", True)],
    "femaleOriented": [("female", True)],
    "medical": [("medical", True)],
    "mandatory": [("mandatory", True)],
}

FORMAT_ALIASES = {
    "pdf": "pdf",
    "ebook": "ebook",
    "e-book": "ebook",
    "e book": "ebook",
    "book": "ebook",
    "video": "video",
    "ebook video": "ebook+ video",
    "ebook+video": "ebook+ video",
    "ebook + video": "ebook+ video",
    "ebook+ video": "ebook+ video",
    "e-book video": "ebook+ video",
    "office": "MS Office",
    "ms office": "MS Office",
    "msoffice": "MS Office",
    "word": "MS Office",
    "document": "MS Office",
    "doc": "MS Office",
    "docx": "MS Office",
    "excel": "MS Office",
    "xls": "MS Office",
    "xlsx": "MS Office",
    "powerpoint": "MS Office",
    "ppt": "MS Office",
    "pptx": "MS Office",
}

SUPPORTED_FORMATS = set(FORMAT_ALIASES.values())

class FormMatcher:

    def __init__(self, context: Optional[PromptContext] = None):
        self.context = context or PromptContext()

    # ---------------- NORMALIZATION ----------------
    def _normalize_llm_output(self, llm_output: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(llm_output, dict):
            return {}
        mapped = llm_output.get("mapped_fields", {})
        return mapped if isinstance(mapped, dict) else {}

    def _norm(self, value: str) -> str:
        return " ".join(value.lower().strip().split())

    # ---------------- FUZZY MATCH ----------------
    def _best_match(self, value: Optional[str], choices: Iterable[str], threshold=0.80):
        if not value:
            return None, 0.0

        clean = self._norm(value)
        normalized_choices = {self._norm(c): c for c in choices if c}

        if clean in normalized_choices:
            return normalized_choices[clean], 1.0

        possible = get_close_matches(clean, list(normalized_choices.keys()), n=1, cutoff=threshold)

        if possible:
            match = possible[0]
            score = SequenceMatcher(a=clean, b=match).ratio()
            return normalized_choices[match], round(score, 2)

        return None, 0.0

    def _match_or_passthrough(self, value: Optional[str], choices: Iterable[str], label: str):
        """Use fuzzy matching when choices exist; otherwise keep user value."""
        if value is None:
            return None, 0.0, f"missing-{label}"
        choice_list = [c for c in choices if c]
        if not choice_list:
            return str(value).strip(), 0.85, f"passthrough-{label}-no-context"
        m, s = self._best_match(value, choice_list)
        return m, s, f"fuzzy-{label}"

    # ---------------- BOOLEAN ----------------
    def _coerce_bool(self, value):
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            v = value.strip().lower()
            if v in {"true", "yes", "1"}:
                return True
            if v in {"false", "no", "0"}:
                return False
        return None

    def _extract_boolean_hints(self, prompt: str):
        found = {}
        p = self._norm(prompt)

        for field, hints in BOOLEAN_HINTS.items():
            for phrase, val in hints:
                # Prevent substring collisions like "don't share" -> "share".
                if re.search(rf"\b{re.escape(phrase)}\b", p):
                    found[field] = val
                    break
        return found

    def _extract_chapter_titles_from_prompt(self, prompt: str) -> List[str]:
        """Extract chapter titles from free-form prompt text."""
        titles: List[str] = []
        text = prompt.strip()
        if not text:
            return titles

        # Pattern 1: "chapter 1: Intro", "chapter 2 - Basics"
        chapter_pattern = re.compile(
            r"chapter\s*\d*\s*[:\-]\s*([^\n,;|]+)",
            flags=re.IGNORECASE,
        )
        for match in chapter_pattern.findall(text):
            cleaned = match.strip(" .-_")
            if cleaned:
                titles.append(cleaned)

        # Pattern 2: "chapters: Intro, Basics, Conclusion"
        list_pattern = re.search(
            r"chapters?\s*[:\-]\s*([^\n]+)",
            text,
            flags=re.IGNORECASE,
        )
        if list_pattern:
            raw_list = list_pattern.group(1)
            for part in re.split(r"[,\|;]", raw_list):
                cleaned = part.strip(" .-_")
                if cleaned and cleaned.lower() not in {"and"}:
                    titles.append(cleaned)

        deduped: List[str] = []
        seen = set()
        for t in titles:
            key = self._norm(t)
            if key and key not in seen:
                deduped.append(t)
                seen.add(key)
        return deduped

    def _normalize_format_value(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        normalized = self._norm(str(value))
        compact = normalized.replace(" + ", "+").replace("+ ", "+").replace(" +", "+")
        if normalized in FORMAT_ALIASES:
            return FORMAT_ALIASES[normalized]
        if compact in FORMAT_ALIASES:
            return FORMAT_ALIASES[compact]
        if "ms office" in normalized or "microsoft office" in normalized:
            return "MS Office"
        if any(token in normalized for token in ("docx", "doc", "xlsx", "xls", "pptx", "ppt", "excel", "powerpoint")):
            return "MS Office"
        if "ebook" in normalized and "video" in normalized:
            return "ebook+ video"
        if "video" in normalized:
            return "video"
        if "ebook" in normalized or "e-book" in normalized or "e book" in normalized:
            return "ebook"
        if "pdf" in normalized:
            return "pdf"
        return str(value).strip() or None

    def _extract_core_fields_from_prompt(self, prompt: str) -> Dict[str, Any]:
        extracted: Dict[str, Any] = {}

        normalized_format = self._normalize_format_value(prompt)
        if normalized_format in SUPPORTED_FORMATS:
            extracted["fileType"] = normalized_format
            extracted["formatType"] = normalized_format

        title_patterns = [
            r"(?:titled|title\s*(?:is|=|:)?|named|called)\s*[\"']?([^\n,;|]+?)[\"']?(?=\s+\b(?:author|written by|by|expiry|expiration|format|pdf|ebook)\b|$)"
        ]
        for pattern in title_patterns:
            match = re.search(pattern, prompt, flags=re.IGNORECASE)
            if match:
                title = match.group(1).strip(" .-_\"'")
                if title:
                    extracted["title"] = title
                    break

        author_patterns = [
            r"author\s*(?:[:=\-]|is|would be|will be)?\s*[\"']?([^\n,;|]+?)[\"']?(?=\s+\b(?:title|expiry|expiration|format|pdf|ebook)\b|$)",
            r"written by\s*[\"']?([^\n,;|]+?)[\"']?(?=\s+\b(?:title|expiry|expiration|format|pdf|ebook)\b|$)",
            r"\bby\s+[\"']?([^\n,;|]+?)[\"']?(?=\s+\b(?:title|expiry|expiration|format|pdf|ebook)\b|$)",
        ]
        for pattern in author_patterns:
            match = re.search(pattern, prompt, flags=re.IGNORECASE)
            if match:
                author = match.group(1).strip(" .-_\"'")
                if author:
                    extracted["keyAuthor"] = author
                    break

        return extracted

    def _chapter_titles_from_value(self, value: Any) -> List[str]:
        if not isinstance(value, list):
            return []
        names: List[str] = []
        for item in value:
            if isinstance(item, dict):
                name = item.get("chapterTitle")
                if isinstance(name, str) and name.strip():
                    names.append(name.strip())
        return names

    def _format_expiry_datetime(self, value: datetime) -> str:
        return value.strftime("%Y-%m-%d %H:%M:%S")

    

    def _parse_explicit_expiry_from_prompt(self, prompt: str) -> Optional[datetime]:
        # First try your strict regex (keep it)
        patterns = [
            r"(?:expire|expires|expiry|expiration|exp date|valid till|valid until)\D+(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2})",
            r"(?:expire|expires|expiry|expiration|exp date|valid till|valid until)\D+(\d{4}-\d{2}-\d{2})",
        ]   

        for pattern in patterns:
            match = re.search(pattern, prompt, flags=re.IGNORECASE)
            if match:
                raw_value = match.group(1).strip().replace("T", " ")
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                    try:
                        parsed = datetime.strptime(raw_value, fmt)
                        if fmt == "%Y-%m-%d":
                            parsed = parsed.replace(hour=0, minute=0, second=0)
                        return parsed
                    except ValueError:
                        continue

        #  fallback to fuzzy natural date parsing
        try:
            # claening the extra chracters while user typed the details 
            cleaned = re.sub(r"[^a-zA-Z0-9\s:/-]", " ", prompt.lower())

            dt = parser.parse(cleaned, fuzzy=True)

            # Optional: avoid picking random numbers as dates
            if dt.year > 2000:
                return dt.replace(hour=0, minute=0, second=0)

        except Exception:
            pass

        return None

    def _parse_relative_expiry(self, text: str) -> Optional[datetime]:
        patterns = [
            r"(\d+)\s+(year|years|month|months|day|days)\s+(?:of\s+)?(?:expiry|expiration|validity)",
            r"(?:expiry|expiration|validity)\s+(?:for|of|is|will be|would be|in)?\s*(\d+)\s+(year|years|month|months|day|days)",
            r"(?:expire|expires|expiring)\s+in\s+(\d+)\s+(year|years|month|months|day|days)",
            r"valid\s+(?:for|till|until)\s+(\d+)\s+(year|years|month|months|day|days)",
        ]

        lowered = text.lower()
        for pattern in patterns:
            match = re.search(pattern, lowered, flags=re.IGNORECASE)
            if not match:
                continue

            amount = int(match.group(1))
            unit = match.group(2).lower()
            now = datetime.now()

            if "year" in unit:
                return now + relativedelta(years=amount)
            if "month" in unit:
                return now + relativedelta(months=amount)
            if "day" in unit:
                return now + relativedelta(days=amount)

        return None

    def _resolve_expiry_datetime(self, prompt: str, raw_value: Any) -> tuple[str, str]:
        if raw_value not in (None, ""):
            raw_str = str(raw_value).strip().replace("T", " ")
            try:
                parsed = isoparse(str(raw_value).strip())
                return self._format_expiry_datetime(parsed.replace(tzinfo=None)), "normalized explicit expiry datetime"
            except Exception:
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                    try:
                        parsed = datetime.strptime(raw_str, fmt)
                        if fmt == "%Y-%m-%d":
                            parsed = parsed.replace(hour=0, minute=0, second=0)
                        return self._format_expiry_datetime(parsed), "normalized explicit expiry datetime"
                    except ValueError:
                        continue

                relative_expiry = self._parse_relative_expiry(raw_str)
                if relative_expiry:
                    return self._format_expiry_datetime(relative_expiry), f"calculated relative expiry from '{raw_value}'"

        prompt_expiry = self._parse_explicit_expiry_from_prompt(prompt)
        if prompt_expiry:
            return self._format_expiry_datetime(prompt_expiry), "expiry datetime extracted from prompt"

        prompt_relative_expiry = self._parse_relative_expiry(prompt)
        if prompt_relative_expiry:
            return self._format_expiry_datetime(prompt_relative_expiry), "calculated relative expiry from prompt"

        fallback = datetime.now() + relativedelta(years=1)
        return self._format_expiry_datetime(fallback), "defaulted to 1 year from prompt time"

    # ---------------- FIELD MATCH ----------------
    def _match_field(self, field_name, value): 

        if value is None:
            return None, 0.0, "missing"

        if field_name == "country":
            return self._match_or_passthrough(value, self.context.countries, "country")

        if field_name == "product":
            return self._match_or_passthrough(value, self.context.products, "product")

        if field_name == "category":
            return self._match_or_passthrough(value, self.context.categories, "category")

        if field_name == "language":
            return self._match_or_passthrough(value, self.context.languages, "language")

        if field_name in {"fileType", "formatType"}:
            normalized_value = self._normalize_format_value(value)
            if normalized_value in SUPPORTED_FORMATS:
                return normalized_value, 1.0, "normalized format"
            return self._match_or_passthrough(normalized_value, self.context.formats, "format")

        if field_name == "limit" and "unlimited" in self._norm(str(value)):
            return "unlimited", 1.0, "keyword match"

        if field_name == "productionNotes" or field_name == "notes":
            return value, 1.0, "direct mapping"

        bool_val = self._coerce_bool(value)
        if bool_val is not None:
            return bool_val, 0.9, "bool coercion"

        return value, 0.7, "fallback"

    # ---------------- RULE ENGINE ----------------
    def _apply_rules(self, result: ExtractionResult):

        mapped = result.mapped_fields

        if mapped.get("fileType") in {"ebookVideo", "ebook+ video", "video"}:
            mapped["allowVideo"] = 1
            result.evidence["allowVideo"] = FieldEvidence(
                value=1,
                confidence=0.98,
                source="rule",
                reasoning="video format implies video"
            )

        if mapped.get("request_quote") and not mapped.get("allowRequest"):
            mapped["allowRequest"] = True

    def _is_ebook_request(self, merged: Dict[str, Any], prompt: str) -> bool:
        candidates = [
            str(merged.get("formatType") or ""),
            str(merged.get("fileType") or ""),
            str(merged.get("docintelFormat") or ""),
            prompt,
        ]
        text = self._norm(" ".join(candidates))
        if "ebook+ video" in text or "ebook+video" in text:
            return False
        return "ebook" in text or "e-book" in text

    # ---------------- MAIN ----------------
    def post_process(self, prompt, llm_output, existing_values=None):

        existing_values = dict(existing_values or {})

        result = ExtractionResult(
            raw_llm_output=llm_output,
            comments=llm_output.get("analysis_summary")
        )

        # 1. normalize
        llm_fields = self._normalize_llm_output(llm_output)

        # 2. merge existing values (LOW priority)
        # Also handle alias mapping for incoming fields like 'notes'
        if "notes" in llm_fields:
            llm_fields["productionNotes"] = llm_fields.pop("notes")
        if "notes" in existing_values:
            existing_values["productionNotes"] = existing_values.pop("notes")
            
        prompt_fields = self._extract_core_fields_from_prompt(prompt)
        merged = {**existing_values, **llm_fields, **prompt_fields}

        normalized_format = self._normalize_format_value(
            merged.get("fileType") or merged.get("formatType")
        )
        if normalized_format:
            merged["fileType"] = normalized_format
            merged["formatType"] = normalized_format

        # 3. boolean hints override
        merged.update(self._extract_boolean_hints(prompt))

        allowed_fields = set(FormFieldUpdate.model_fields.keys())

        # 4. matching
        for field, value in merged.items():

            if field not in allowed_fields:
                result.warnings.append(f"Ignored unsupported field '{field}'")
                continue 

            val, conf, reason = self._match_field(field, value)

            if val is None:
                result.unresolved_fields.append(field)
                continue

            result.mapped_fields[field] = val
            result.evidence[field] = FieldEvidence(
                value=val,
                confidence=conf,
                source="matcher" if conf >= 0.9 else "llm",
                reasoning=reason
            )

        # 5. rules
        self._apply_rules(result)

        # 6. validation  
        required_fields = ["title", "keyAuthor", "fileType"]
        for field in required_fields:
            if not result.mapped_fields.get(field):
                result.unresolved_fields.append(field)
                result.warnings.append(f"{field} is required !")

        if result.mapped_fields.get("fileType") and not result.mapped_fields.get("formatType"):
            result.mapped_fields["formatType"] = result.mapped_fields["fileType"]
            result.evidence["formatType"] = FieldEvidence(
                value=result.mapped_fields["formatType"],
                confidence=result.evidence.get("fileType", FieldEvidence()).confidence or 0.9,
                source="rule",
                reasoning="formatType mirrored from fileType",
            )

        # For eBook workflows, chapter titles are mandatory.
        if self._is_ebook_request(merged, prompt):
            chapter_titles = self._chapter_titles_from_value(result.mapped_fields.get("chapter"))
            if not chapter_titles:
                chapter_titles = self._extract_chapter_titles_from_prompt(prompt)
                if chapter_titles:
                    result.mapped_fields["chapter"] = [
                        {"chapterTitle": chapter_title} for chapter_title in chapter_titles
                    ]
                    result.evidence["chapter"] = FieldEvidence(
                        value=result.mapped_fields["chapter"],
                        confidence=0.9,
                        source="rule",
                        reasoning="chapter names extracted from prompt for ebook request",
                    )
            if not self._chapter_titles_from_value(result.mapped_fields.get("chapter")):
                result.unresolved_fields.append("chapter")
                result.warnings.append(
                    "Please mention the chapter names of the eBook in the next message (for each uploaded document)."
                )

        # Keep unresolved/warnings stable and avoid repetitive user prompting loops.
        result.unresolved_fields = list(dict.fromkeys(result.unresolved_fields))
        result.warnings = list(dict.fromkeys(result.warnings))

        # Handle expiry datetime using explicit user value when present,
        # otherwise default to one year from the prompt time.
        formatted_date, reason = self._resolve_expiry_datetime(
            prompt,
            result.mapped_fields.get("expDatetime"),
        )
        result.mapped_fields["expDatetime"] = formatted_date
        result.evidence["expDatetime"] = FieldEvidence(
            value=formatted_date,
            confidence=0.95,
            source="rule",
            reasoning=reason
        )

        try:
            FormFieldUpdate(**result.mapped_fields)
        except Exception as e:
            # Don't double-add if already in warnings, but good for other validation errors
            msg = str(e)
            if msg not in result.warnings:
                result.warnings.append(msg)

        # 7. confidence
        confidences = [e.confidence for e in result.evidence.values()]
        result.confidence = round(mean(confidences), 2) if confidences else 0.0

        # 8. Ensure full schema output with None for missing fields
        full_mapped = {}
        for f in FormFieldUpdate.model_fields.keys():
            full_mapped[f] = result.mapped_fields.get(f)
        result.mapped_fields = full_mapped

        return result

# ---------------------------------------------------------------------------
# Public helper used by the Streamlit app to extract metadata via LLM
def extract_metadata(user_prompt: str, existing_values: dict | None = None) -> dict:
    """Run the LLM (Gemma-4 via HTTP endpoint) and post‑process with FormMatcher.
    Returns: `mapped_fields`, `unresolved_fields`, `warnings`.
    """ 
    
    existing_values = existing_values or {}
    
    # System prompt describing the extraction task
    system_msg = {
        "role": "system",
        "content": (
            "You are a metadata extraction assistant. Given a user prompt and any already "
            "known fields, return a JSON object with the fields you can fill. If a required "
            "field (title, keyAuthor, fileType) is missing, do NOT guess – instead ask a short "
            "question for that field."
        ),
    }
    
    # Provide current known fields to the model for context
    context_msg = {
        "role": "assistant",
        "content": f"Current known fields: {json.dumps(existing_values)}",
    }
    
    user_msg = {"role": "user", "content": user_prompt}
    messages = [system_msg, context_msg, user_msg]
    
    raw_output = _llm_chat(messages)
    
    # Expect the model to output a JSON block; try to parse it
    try:
        # LLM can emit JSON plus trailing text; decode first valid object only.
        clean_json = raw_output.replace("```json", "").replace("```", "").strip()
        start = clean_json.find("{")
        if start == -1:
            raise ValueError("No JSON object found in model output")
        llm_json, _ = json.JSONDecoder().raw_decode(clean_json[start:])
    except Exception as e:
        # If parsing fails, treat the whole output as a question string
        llm_json = {"question": raw_output.strip()}
        
    # Post‑process with the existing FormMatcher logic
    matcher = FormMatcher()
    result = matcher.post_process(user_prompt, llm_json, existing_values)
    
    return {
        "mapped_fields": result.mapped_fields,
        "unresolved_fields": result.unresolved_fields,
        "confidence": result.confidence,
        "warnings": result.warnings,
    }
