# Conversational Metadata Backend

## What We Are Building

We are building a production-ready FastAPI + LangGraph backend that converts user conversation and uploaded document context into a structured metadata JSON payload.

This is not a general chatbot.

This is a state-driven conversational form autofill engine.

---

## Core Idea

The system:
- receives user input and uploaded document references
- incrementally builds metadata
- keeps short-term conversation state
- asks follow-up questions for missing required fields
- returns structured JSON for frontend autofill or final POST submission

---

## Architecture

- `app/main.py` - FastAPI app entrypoint
- `app/routes.py` - API route layer
- `app/models/state.py` - `ChatState` workflow state
- `app/models/schemas.py` - request and response schemas
- `app/models/metadata.py` - structured metadata schema placeholder
- `app/services/llm.py` - extraction only, no business logic
- `app/services/validation.py` - required field checks
- `app/services/inference.py` - file type inference, pure logic
- `app/services/merge.py` - metadata merge logic
- `app/config/field_config.py` - required fields and follow-up questions
- `app/workflow/graph.py` - LangGraph setup
- `app/workflow/nodes/` - independent workflow nodes

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
  "message": "assistant message or follow-up question",
  "metadata": {},
  "missing_fields": [],
  "pending_field": null,
  "next_action": "ask_user"
}
```

---

## Current Required Fields

- `fullName`
- `email`
- `fileType`

These are currently minimal placeholder fields in `app/config/field_config.py`.

---

## Current Workflow

Implemented LangGraph skeleton:

1. `apply_pending_field`
2. `validate_required_fields`
3. `END`

Current behavior:
- If `pending_field` exists, the latest user message is saved into `metadata[pending_field]`.
- Required fields are checked deterministically.
- If fields are missing, the workflow asks one follow-up question.
- If no required fields are missing, the workflow returns `next_action = "ready"`.

---

## Important Rules

- LLM is only used for extraction.
- No business logic goes inside `llm.py`.
- Workflow behavior should be deterministic.
- State is the single source of truth.
- Each node should be independent and testable.
- Do not overwrite valid metadata unnecessarily.
- Keep implementation minimal until each layer is needed.

---

## Pending Field Logic

Implemented in `app/workflow/nodes/apply_pending.py`.

If `pending_field` exists:
- treat `user_message` as the answer
- update `metadata[pending_field]`
- clear `pending_field`
- clear `pending_question`
- continue workflow

---

## Validation Logic

Implemented in `app/services/validation.py`.

Current behavior:
- reads required fields from `FIELD_CONFIG["required"]`
- treats `None`, empty string, empty list, and empty dict as missing
- returns a list of missing required fields

---

## Short-Term State

Implemented in `app/routes.py` as temporary in-memory state:

```python
_sessions: dict[str, ChatState] = {}
```

This is acceptable for initial boilerplate only. Production should replace this with Redis, a database, or a LangGraph checkpoint store.

---

## Done So Far

- Created minimal FastAPI app in `app/main.py`
- Added single POST route in `app/routes.py`
- Added in-memory session handling
- Added request and response schemas in `app/models/schemas.py`
- Cleaned up `ChatState` in `app/models/state.py`
- Added placeholder required fields and questions in `app/config/field_config.py`
- Added required field validation service in `app/services/validation.py`
- Added LangGraph workflow skeleton in `app/workflow/graph.py`
- Added `apply_pending_field` node in `app/workflow/nodes/apply_pending.py`
- Verified Python compilation with `compileall`

---

## Not Done Yet

- LLM extraction node is not implemented
- Metadata merge node is not implemented
- File type inference node is not connected
- Validation node is still inside `graph.py`, not moved to `workflow/nodes/validate.py`
- `metadata.py` schema is still empty
- No persistence beyond in-memory sessions
- No tests yet
- Runtime smoke test could not run because local environment is missing `langgraph`

---

## What To Do Next

1. Install or fix `langgraph` in the active environment.
2. Move `validate_required_fields` into `app/workflow/nodes/validate.py`.
3. Implement basic metadata schema in `app/models/metadata.py`.
4. Add extraction node that calls `services/llm.py`.
5. Add merge node using `services/merge.py`.
6. Add file type inference node using `services/inference.py`.
7. Add focused tests for validation and `apply_pending_field`.
