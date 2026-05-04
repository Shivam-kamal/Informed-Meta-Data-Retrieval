# AutoFill Engine Workflow Memory

This file captures the current backend workflow so future prompts can reference one place instead of re-explaining context.

## 1) Entry Points

- API app entry: `app/main.py`
- Chat route: `app/routes.py` (`POST /chat`)
- Optional local UI: `app/streamlit_app.py`

## 2) Request -> State Build (`/chat`)

`app/routes.py` does the following for each request:

1. Create/reuse `session_id`.
2. Load previous in-memory state from `_sessions`.
3. Append latest user message to short history (`messages[-5:]`).
4. Merge previous metadata + request metadata (`_merge_metadata`).
5. Build `ChatState`.
6. Run `run_workflow(state)`.
7. Append bot reply to history (if present).
8. Persist result in `_sessions[session_id]`.
9. Return `ChatResponse`.

## 3) LangGraph Workflow Order

Defined in `app/workflow/graph.py`:

`START -> apply_pending_field -> infer_metadata -> merge_metadata -> validate_required_fields -> decide_next_action -> generate_bot_response -> END`

### Node roles

- `apply_pending_field`
  - If `pending_field` exists, treats new user message as answer for that field and clears pending state.
- `infer_metadata`
  - Infers file-derived metadata from document names.
  - Extracts message metadata with deterministic heuristics + optional validated OpenAI extraction.
- `merge_metadata`
  - Merges base metadata + inferred metadata + extracted metadata with overwrite safeguards.
- `validate_required_fields`
  - Checks required user fields and ISO datetime format for `expDatetime`.
  - Enforces chapter titles when format requires chapters.
- `decide_next_action`
  - If missing fields exist: `next_action = "ask_user"` and sets `pending_field` + `pending_question`.
  - Else: `next_action = "ready"`.
- `generate_bot_response`
  - Returns ready message or a friendly rephrase of deterministic question.

## 4) Metadata Priority and Merge Behavior

Implemented mainly in `app/services/merge.py` and route preprocessing:

- Existing non-empty values are generally preserved.
- File-structure fields can be refreshed/overwritten by inference:
  - `fileType`, `formatType`, `file`, `officeFile`, `chapter`
- Chapter merge is identity-based (`uploadFile` or `selectedVideo`):
  - Inference can create rows.
  - Extracted/LLM data fills missing chapter titles on matching rows.

## 5) Inference Rules (file names only)

From `app/services/inference.py`:

- Uses extensions only, no file content parsing.
- Format mapping:
  - one PDF -> `pdf`
  - many PDFs -> `ebook`
  - one video -> `video`
  - mixed or many videos -> `ebook+ video`
  - any Office document -> `MS Office` (takes precedence)
- Also sets:
  - `file` = first document
  - `officeFile` = first Office file
  - default `chapter` rows for PDF/video files
- Produces warnings when mapped format conflicts with uploaded docs.

## 6) LLM and Deterministic Extraction

From `app/services/llm.py`:

- Deterministic layer first (regex + date intent parsing + chapter hints).
- OpenAI layer is optional (requires `OPENAI_API_KEY`).
- LLM output is heavily validated:
  - only allowed keys
  - no empty values
  - `expDatetime` must be valid ISO datetime
  - `coverPhoto` must match uploaded image file names
  - `chapter` rows must reference uploaded PDF/video names
- If OpenAI fails, flow still works via deterministic extraction.

## 7) Required Field Logic

From `app/config/field_config.py` + `app/services/validation.py`:

- Required fields currently configured:
  - `company`, `product`, `country`, `production`, `expDatetime`, `productionNotes`, `title`, `keyAuthor`, `fileType`
- Active user questioning currently focuses on required fields where source is user-originated (plus chapter-title checks when needed).
- If validation fails, workflow asks the next missing field using `QUESTIONS`.

## 8) Session Model

- Sessions are in-memory only (`_sessions` dict in `app/routes.py`).
- Server restart clears sessions.
- Recent message history is trimmed to last 5 messages.

## 9) Response Contract

`ChatResponse` includes:

- `session_id`
- `bot_message`
- `metadata` (full template keys)
- `missing_fields`
- `warnings`
- `pending_field`
- `question`
- `next_action` (`ask_user` | `ready` | `error`)

## 10) Important Constraints

- Business logic is deterministic-first.
- Uploaded documents are treated as filenames/extensions only.
- LLM is helper-only for extraction and phrasing.
- LLM data must be validated before merge.
- Date parsing should remain deterministic.
