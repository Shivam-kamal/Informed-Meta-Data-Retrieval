# Conversational Metadata Backend

## What We Are Building

This backend is a FastAPI + LangGraph conversational autofill engine.

It receives a frontend payload containing:
- the latest user message
- the session id
- uploaded document names
- the current metadata JSON progress from the frontend

It returns:
- the updated metadata JSON
- missing required fields
- the next bot question, if any
- detected workflow warnings
- the current workflow action

This is not a general chatbot and it does not parse uploaded files.

---

## Payload Contract

The frontend sends document names only. The backend uses those names/extensions for format classification.

Example request:

```json
{
  "message": "uploading a document title is Diet Coke and author is Shivam Kamal and i have doc1.pdf which is first chapter and their thumbnail is roz.jpg, company name is shivam",
  "session_id": "string",
  "documents": ["doc1.pdf", "roz.jpg", "doc2.pdf", "doc3.mp4"],
  "metadata": {
    "title": "Diet Coke",
    "keyAuthor": "Shivam Kamal",
    "company": "shivam"
  }
}
```

Important:
- `documents` contains names like `doc1.pdf`, `roz.jpg`, `doc3.mp4`.
- The backend does not open, download, or parse those files.
- The frontend sends the current metadata progress on each request.
- The backend merges the request metadata with previous session metadata.
- If the bot asked for a field, the next user message is applied to that pending field.
- The backend also tries to extract obvious metadata from the English `message`.

---

## Current API

POST `/chat`

Request:

```json
{
  "message": "user message",
  "session_id": "optional-session-id",
  "documents": [],
  "metadata": {}
}
```

Response:

```json
{
  "session_id": "session-id",
  "bot_message": "assistant message or follow-up question",
  "metadata": {},
  "missing_fields": [],
  "warnings": [],
  "pending_field": null,
  "question": null,
  "next_action": "ask_user"
}
```

---

## Production Format Rules

Production format is resolved only from uploaded document names:

- one PDF -> `pdf`
- multiple PDFs -> `ebook`
- one video -> `video`
- multiple videos -> `ebook+ video`
- PDFs plus videos -> `ebook+ video`
- any Word, Excel, or PowerPoint file -> `MS Office`

The detected format is written into both:
- `fileType`
- `formatType`

Office files win over other uploaded names. For example, `deck.pptx` plus `doc1.pdf` resolves to `MS Office`.

---

## Workflow Warnings

Warnings are added when existing or requested metadata conflicts with uploaded file names:

- non-single-PDF cases mapped as `pdf`
- single/no-PDF cases mapped as `ebook`
- non-single-video cases mapped as `video`

Warnings are returned in `ChatResponse.warnings`.

---

## Current Workflow

The active LangGraph workflow is:

1. `apply_pending_field`
2. `infer_metadata`
3. `merge_metadata`
4. `validate_required_fields`
5. `decide_next_action`
6. `generate_bot_response`
7. `END`

Behavior:
- `apply_pending_field` saves the meaning of the latest user reply into the previous `pending_field`.
- `infer_metadata` classifies the production format from `documents` and extracts obvious fields from `message`.
- `merge_metadata` writes inferred fields into metadata, including `fileType` and `formatType`.
- `validate_required_fields` checks required fields from `FIELD_CONFIG`.
- `decide_next_action` asks for the first missing required field or marks the form ready.
- `generate_bot_response` returns the final bot message or follow-up question.

---

## Metadata Flow

Metadata has three sources:

1. Previous session metadata stored in memory.
2. Current request metadata sent by the frontend.
3. Inferred metadata from uploaded document names.
4. Extracted metadata from the latest English user message.

Merge behavior:
- Request metadata updates previous session metadata.
- Inferred `fileType`, `formatType`, `file`, and `officeFile` can overwrite stale values because they are derived from the latest uploaded names.
- Message-extracted values can fill fields such as `title`, `keyAuthor`, `company`, `product`, `country`, `coverPhoto`, and `chapter`.
- Chapter rows are merged by `uploadFile` or `selectedVideo`, so a title for `doc1.pdf` updates the `doc1.pdf` row without deleting blank rows for other files.
- Other filled metadata should not be overwritten unnecessarily.

---

## Message Extraction

The backend can map natural language replies into metadata fields.

Examples:

- `the name of the company is DietCoke` -> `company: "DietCoke"`
- `title is Diet Coke` -> `title: "Diet Coke"`
- `author is Shivam Kamal` -> `keyAuthor: "Shivam Kamal"`
- `thumbnail is roz.jpg` -> `coverPhoto: "roz.jpg"` when `roz.jpg` is in `documents`
- `doc1.pdf is chapter 1 titled Introduction to LLM` -> updates the `chapter` row for `doc1.pdf`

OpenAI can be used for message extraction when configured. A deterministic fallback handles common phrases so the workflow still works when OpenAI is unavailable.

---

## Chapter Flow

For uploaded PDFs/videos, the backend creates chapter rows in this shape:

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
- If the user gives chapter info in the message, the matching row is filled.
- If any required chapter row has a blank `chapterTitle`, validation adds `chapter` to `missing_fields`.
- The bot asks the user to list chapter titles in order or with file names.

---

## Architecture

- `app/main.py` - FastAPI app entrypoint
- `app/routes.py` - API route layer and in-memory session handling
- `app/models/schemas.py` - request and response schemas
- `app/models/state.py` - workflow state
- `app/config/field_config.py` - required fields and follow-up questions
- `app/services/inference.py` - filename-based format classification and warnings
- `app/services/merge.py` - metadata merge logic
- `app/services/validation.py` - required field validation
- `app/services/response_generator.py` - bot response generation
- `app/services/llm.py` - English message metadata extraction; no document parsing
- `app/workflow/graph.py` - LangGraph workflow wiring
- `app/workflow/nodes/` - workflow node functions

---

## Current Required Fields

Configured in `app/config/field_config.py`.

Current required user fields:
- `company`
- `product`
- `country`
- `production`
- `expDatetime`
- `productionNotes`

Current required inferred field:
- `fileType`

Required LLM/source fields may exist in config, but validation currently asks only for required user fields and inferred fields handled by the workflow.

---

## Done So Far

- Created FastAPI `/chat` endpoint.
- Added in-memory session state.
- Added request/response schemas.
- Added pending-field follow-up handling.
- Added frontend metadata progress merging.
- Added filename-based production format inference.
- Added `fileType` and `formatType` population.
- Added workflow warnings for conflicting format mappings.
- Added English message extraction for pending answers and obvious metadata.
- Added default chapter rows for uploaded PDFs/videos.
- Added chapter-title validation and chapter follow-up question.
- Added chapter merge by `uploadFile`/`selectedVideo`.
- Added deterministic required-field validation.
- Wired inference and merge into LangGraph workflow.
- Disabled document parsing and LLM extraction for uploaded files.
- Verified compilation with `python -m compileall app`.

---

## Not Done Yet

- Define final structured metadata schema in `app/models/metadata.py`.
- Move `validate_required_fields` from `graph.py` into `workflow/nodes/validate.py`.
- Add tests for format inference, warnings, metadata merge, and pending-field flow.
- Replace in-memory sessions with persistent storage for production.

---

## Key Alignment Rule

The backend should stay aligned to this model:

Frontend sends current state plus document names. Backend updates metadata deterministically, classifies upload format from filenames, asks for missing required fields, and returns the updated JSON progress.
