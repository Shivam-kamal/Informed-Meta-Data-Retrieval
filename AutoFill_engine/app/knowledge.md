# Conversational Metadata Backend Knowledge

This project is a FastAPI + LangGraph conversational autofill backend.

It is not a general chatbot. It receives user text, uploaded file names, and current frontend metadata, then returns an updated metadata JSON plus the next required question.

The system is deterministic-first:
- Business rules must stay in backend code.
- LLMs are allowed only for metadata extraction and friendly response phrasing.
- Dates, validation, file inference, merge priority, and chapter mapping must be deterministic.
- LLM output must be validated before it can affect metadata.
- Uploaded files are never opened or parsed. Only file names/extensions are used.

---

## API Contract

Endpoint:

```text
POST /chat
```

Request shape:

```json
{
  "message": "latest user message",
  "session_id": "optional-session-id",
  "documents": ["doc1.pdf", "cover.jpg", "intro.mp4"],
  "metadata": {}
}
```

Response shape:

```json
{
  "session_id": "session-id",
  "bot_message": "assistant response",
  "metadata": {},
  "missing_fields": [],
  "warnings": [],
  "pending_field": null,
  "question": null,
  "next_action": "ask_user"
}
```

`next_action` can be:
- `ask_user`
- `ready`
- `error`

---

## Request Lifecycle

File: `app/routes.py`

The `/chat` route:

1. Creates or reuses a `session_id`.
2. Loads previous in-memory session state from `_sessions`.
3. Adds the latest user message to `messages`.
4. Merges frontend `request.metadata` into previous session metadata.
5. Builds a `ChatState`.
6. Sends the state into `run_workflow()`.
7. Saves the result back into `_sessions`.
8. Returns a `ChatResponse`.

The frontend metadata is trusted as current progress, but backend deterministic inference can still refresh special file-derived fields.

---

## LangGraph Workflow

File: `app/workflow/graph.py`

Current graph:

```text
START
  -> apply_pending_field
  -> infer_metadata
  -> merge_metadata
  -> validate_required_fields
  -> decide_next_action
  -> generate_bot_response
  -> END
```

Node responsibilities:

- `apply_pending_field`
  - If the previous bot question set `pending_field`, the latest user reply is applied to that field first.
  - This makes pending-field answers highest priority.

- `infer_metadata`
  - Infers file metadata from uploaded document names.
  - Extracts metadata from the user message using deterministic regex/date parsing and validated LLM output.

- `merge_metadata`
  - Merges base metadata, deterministic inference, and extracted message metadata.
  - Prevents unwanted overwrites.

- `validate_required_fields`
  - Validates required user fields.
  - Validates `expDatetime` as ISO datetime.
  - Validates chapter titles when required.

- `decide_next_action`
  - If fields are missing, asks for the first missing field.
  - Otherwise marks the workflow `ready`.

- `generate_bot_response`
  - Returns final ready message or rephrases the deterministic question.
  - Must not contain business logic.

---

## Metadata Sources And Priority

Metadata enters from these places:

1. Previous session metadata.
2. Current frontend `request.metadata`.
3. Pending-field answer.
4. Deterministic file inference from `documents`.
5. Message extraction from regex/date parser.
6. Message extraction from LLM after validation.

Effective priority:

```text
pending field answer
existing metadata
deterministic file inference
validated LLM extraction
regex extraction
```

Important merge rule:

Existing non-empty values are not overwritten except for:

```text
fileType
formatType
file
officeFile
chapter
```

These fields are special because they are derived from the latest uploaded file names or require structured chapter merging.

---

## Field Configuration

File: `app/config/field_config.py`

Current required fields:
      
```python
FIELD_CONFIG = {
    "company": {"required": True, "source": "user"},
    "product": {"required": True, "source": "user"},
    "country": {"required": True, "source": "user"},
    "production": {"required": True, "source": "user"},
    "expDatetime": {"required": True, "source": "user"},
    "productionNotes": {"required": True, "source": "user"},
    "title": {"required": True, "source": "llm"},
    "keyAuthor": {"required": True, "source": "llm"},
    "fileType": {"required": True, "source": "inferred"},
}
```

Validation currently asks only for required fields where:

```text
source == "user"
```

So the bot asks for:
- `company`
- `product`
- `country`
- `production`
- `expDatetime`
- `productionNotes`

`title` and `keyAuthor` may be extracted by LLM/regex, but validation does not ask the user for them.

---

## File Format Inference

File: `app/services/inference.py`

File format is resolved only from uploaded document names/extensions.

Rules:

- one PDF -> `pdf`
- multiple PDFs -> `ebook`
- one video -> `video`
- multiple videos -> `ebook+ video`
- PDFs plus videos -> `ebook+ video`
- any Word, Excel, or PowerPoint file -> `MS Office`

Office files win over PDF/video combinations.

The inferred format is written to:

```text
fileType
formatType
```

Other file-derived fields:

- `file` gets the first uploaded document name.
- `officeFile` gets the first Office file name.
- `chapter` gets default rows for PDFs/videos.

Warnings are generated when existing/requested format metadata conflicts with uploaded document names.

---

## Date Handling

File: `app/utils/date_parser.py`

Date parsing is deterministic. LLM must not compute relative dates.

Supported examples:

- `in 9 months`
- `after 2 weeks`
- `valid for 9 months`
- `from now 15 months`
- `from now is 15 months`
- `after nine months`
- `today`
- `tomorrow`
- `next week`
- `next year`
- `next month`
- `31/12/2026`
- extracted phrase like `15 months`

Implementation rules:

- Uses the backend's current UTC datetime plus `relativedelta`.
- `parse_expiry_datetime()` is the deterministic expiry tool: pass the user's expiry intent, and it returns an ISO datetime or `None`.
- Returns ISO format.
- Returns `None` when parsing fails.
- Supports number words.

Extraction flow for expiry:

1. Regex extracts a date candidate phrase from the user message.
2. Candidate/user intent is passed to `parse_expiry_datetime()`.
3. If parsing succeeds, backend writes `expDatetime`.
4. If parsing fails, LLM may only provide `expDatetime` when the user gave an explicit valid ISO datetime.
5. Invalid/non-ISO LLM dates are discarded.
6. If `expDatetime` is missing or invalid, validation asks the user again.

Do not parse arbitrary full messages as dates. Extract a candidate phrase first.

---

## Message Extraction

File: `app/services/llm.py`

Message extraction has two layers:

1. Deterministic regex extraction.
2. OpenAI extraction if configured.

Regex extracts obvious fields such as:

- `company`
- `title`
- `keyAuthor`
- `product`
- `country`
- `production`
- `productionNotes`
- `coverPhoto`
- `chapter`
- date candidates for `expDatetime`

LLM extraction is optional. If no OpenAI API key is configured or the call fails, deterministic extraction still works.

Allowed LLM output keys:

```text
company
product
country
expDatetime
productionNotes
title
keyAuthor
coverPhoto
chapter
```

LLM extraction rules:

- Return only JSON.
- Temperature is `0`.
- Do not invent values.
- Do not compute relative dates.
- Use uploaded document names only.
- `chapter` must be a list of objects with `chapterTitle`, `uploadFile`, `fileValue`, `selectedVideo`.

Before merging LLM output:

- Unknown keys are discarded.
- Empty values are discarded.
- `expDatetime` must be valid ISO.
- `coverPhoto` must match an uploaded image document.
- `chapter` rows must reference uploaded PDF/video file names.
- Strings are cleaned and normalized.

---

## Normalization

File: `app/services/llm.py`

String cleanup removes wrapper phrases such as:

- `company name is`
- `name of the company is`
- `this is`
- `it is`

Values are stripped, quote-trimmed, whitespace-normalized, and split away from obvious following field phrases.

Examples:

```text
company name is Acme
-> Acme

this is Acme
-> Acme
```

---

## Pending Field Flow

File: `app/workflow/nodes/apply_pending.py`

When the bot asks for a field, that field is stored as `pending_field`.

On the next user message:

1. `apply_pending_field` runs before inference.
2. The latest message is interpreted as the answer to `pending_field`.
3. The answer is written into `metadata[pending_field]`.
4. `pending_field` and `pending_question` are cleared.
5. `is_followup` is set to `True`.

For example:

```text
pending_field = "company"
message = "Acme Pharma"
-> metadata["company"] = "Acme Pharma"
```

For `expDatetime`, the reply must parse deterministically or be a valid ISO datetime. Otherwise validation asks again.

---

## Chapter Structure

Chapter row shape must not change:

```json
{
  "chapterTitle": "",
  "uploadFile": "doc1.pdf",
  "fileValue": "doc1.pdf",
  "selectedVideo": ""
}
```

Rules:

- PDF rows use `uploadFile` and `fileValue`.
- Video rows use `selectedVideo`.
- Never mix PDF and video identity in the same row.

PDF row:

```json
{
  "chapterTitle": "",
  "uploadFile": "doc1.pdf",
  "fileValue": "doc1.pdf",
  "selectedVideo": ""
}
```

Video row:

```json
{
  "chapterTitle": "",
  "uploadFile": "",
  "fileValue": "",
  "selectedVideo": "intro.mp4"
}
```

---

## Chapter Creation

File: `app/services/inference.py`

Default chapter rows are created from uploaded PDF/video document names:

- multiple PDFs -> multiple PDF rows
- multiple videos -> multiple video rows
- mixed PDFs/videos -> combined rows

This happens deterministically from `documents`.

---

## Chapter Extraction

File: `app/services/llm.py`

Supported message examples:

```text
doc1.pdf is chapter 1 titled Introduction
chapter 2 is doc2.pdf called Basics
intro.mp4 is chapter 1 Welcome
```

Extracted fields:

- file name
- chapter title

The extractor only returns chapter rows for files that appear in `documents`.

---

## Chapter Merge

File: `app/services/merge.py`

Chapter identity is:

```text
uploadFile OR selectedVideo
```

Merge rules:

1. Inferred chapter rows from uploaded documents may create rows.
2. Extracted/LLM chapter rows may not create new rows.
3. Extracted/LLM chapter rows can only update a matching existing row.
4. Existing chapter titles are not overwritten.
5. Only missing `chapterTitle` values are filled.

Example:

Existing:

```json
[
  {
    "chapterTitle": "",
    "uploadFile": "doc1.pdf",
    "fileValue": "doc1.pdf",
    "selectedVideo": ""
  }
]
```

Extracted:

```json
[
  {
    "chapterTitle": "Introduction",
    "uploadFile": "doc1.pdf",
    "fileValue": "doc1.pdf",
    "selectedVideo": ""
  }
]
```

Result:

```json
[
  {
    "chapterTitle": "Introduction",
    "uploadFile": "doc1.pdf",
    "fileValue": "doc1.pdf",
    "selectedVideo": ""
  }
]
```

If extracted row references `missing.pdf`, it is ignored.

---

## Chapter Validation

File: `app/services/validation.py`

If `fileType` is one of:

```text
pdf
ebook
ebook+ video
```

Then every chapter row must have a non-empty `chapterTitle`.

If any title is missing, validation adds:

```text
chapter
```

to `missing_fields`.

Question:

```text
Please provide chapter titles for all uploaded files in order or with file names.
```

---

## Merge Logic

File: `app/services/merge.py`

General rule:

```text
Do not overwrite existing non-empty metadata.
```

Overwrite exceptions:

```text
fileType
formatType
file
officeFile
chapter
```

`chapter` is not overwritten wholesale. It is structurally merged by file identity.

The backend should never let LLM output replace confirmed user/frontend values unless the target field is one of the explicit overwrite exceptions.

---

## Validation Logic

File: `app/services/validation.py`

Validation checks:

1. Required fields where `source == "user"`.
2. `expDatetime` must be valid ISO datetime.
3. Chapter titles are required for PDF/ebook flows.

Validation does not ask for LLM-sourced fields like `title` or `keyAuthor`.

If `expDatetime` is missing or invalid, ask the user again. Do not trust LLM relative-date guesses.

---

## Response Generation

File: `app/services/response_generator.py`

Response generation has no business logic.

Behavior:

- If `next_action == "ready"`, return:

```text
Everything looks good, your form is ready.
```

- If `next_action == "ask_user"`, use the deterministic question from `QUESTIONS`.
- OpenAI may rephrase the question in a short friendly way.
- If OpenAI fails, return the deterministic question unchanged.

---

## Important Files

- `app/main.py`
  - FastAPI app entrypoint.

- `app/routes.py`
  - `/chat` endpoint.
  - Session handling.
  - Frontend metadata merge.
  - Response shaping.

- `app/models/schemas.py`
  - `ChatRequest`.
  - `ChatResponse`.
  - `FRONTEND_METADATA_TEMPLATE`.

- `app/models/state.py`
  - LangGraph `ChatState`.

- `app/config/field_config.py`
  - Required field configuration.
  - Follow-up questions.

- `app/utils/date_parser.py`
  - Deterministic relative date parser.

- `app/services/inference.py`
  - File format inference from document names.
  - Default chapter row creation.
  - Format warnings.

- `app/services/llm.py`
  - Regex extraction.
  - Date candidate extraction.
  - OpenAI metadata extraction.
  - LLM output validation.
  - Chapter extraction from message.

- `app/services/merge.py`
  - Metadata merge priority.
  - Chapter merge rules.

- `app/services/validation.py`
  - Required user-field validation.
  - ISO datetime validation.
  - Chapter-title validation.

- `app/services/response_generator.py`
  - Final bot response / rephrasing.

- `app/workflow/graph.py`
  - LangGraph wiring.

- `app/workflow/nodes/`
  - Workflow node implementations.

---

## Non-Goals

Do not add these unless explicitly requested:

- Uploaded file parsing.
- LLM-based business decisions.
- LLM-based date calculation.
- Rewriting the architecture.
- Replacing LangGraph.
- Replacing in-memory session storage without a clear storage requirement.

---

## Development Rules For Future LLMs

When modifying this project:

1. Preserve the FastAPI + LangGraph architecture.
2. Keep business logic deterministic.
3. Treat backend as source of truth.
4. Validate all LLM output.
5. Do not let LLM compute dates.
6. Do not parse uploaded files.
7. Do not overwrite existing metadata except explicit overwrite fields.
8. Keep chapter row structure unchanged.
9. Keep changes small and focused.
10. Run at least:

```text
python -m compileall app
```

---

## Mental Model

The frontend sends current form state plus latest user text and uploaded file names.

The backend:

1. Applies pending answers.
2. Infers file metadata from names.
3. Extracts obvious metadata from text.
4. Uses LLM only as an extraction helper.
5. Validates LLM output.
6. Merges without overwriting confirmed values.
7. Validates required fields.
8. Asks the next deterministic question or marks the form ready.

This is the core alignment rule for the whole codebase.
