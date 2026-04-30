# Knowledge Base

This folder is a backend-only OpenAI replica of `Local_LLM-v1`. It intentionally excludes `app.py`.

## Goal

Build a FastAPI metadata assistant that:

- accepts uploaded files plus a natural-language prompt,
- accepts chatbot JSON payloads with a prompt plus document-name arrays,
- extracts structured metadata through the OpenAI API,
- falls back to local regex parsing if the API is not configured or fails,
- keeps downstream field names compatible with the existing payload,
- derives production file format from uploaded files instead of trusting the prompt,
- returns one clean `CombinedResponse` from the backend.

## Environment

- `OPENAI_API_KEY` is required for OpenAI extraction.
- `OpenAI_LLM-v1/.env` is loaded automatically if present.
- `OPENAI_MODEL` is optional and defaults to `gpt-4.1-mini`.
- `OPENAI_BASE_URL` is optional for compatible gateways.
- `OPENAI_TIMEOUT` is optional and defaults to `60` seconds.

## File Map

### `main.py`

- FastAPI app factory only.
- Wires CORS, `OpenAILLMClient`, `ConversationStore`, and the API router.
- Does not contain business workflow logic.

### `routes.py`

- Defines the HTTP routes.
- Endpoints:
  - `GET /health`
  - `POST /upload-and-analysis`
  - `POST /chatbot-analysis`
  - `POST /conversation/turn`
- Accepts:
  - `files`: list of uploaded files
  - `prompt`: user prompt
  - `existing_values`: optional JSON string
- Workflow:
  - validate uploaded files,
  - parse previous metadata,
  - call `OpenAILLMClient.extract_fields`,
  - post-process with `FormMatcher`,
  - override `fileType` and `formatType` from uploaded files,
  - build chapter file entries for `ebook` and `ebook+ video`,
  - return `CombinedResponse`.
- The chatbot endpoint accepts JSON:
  - `prompt`: natural-language user message
  - `document_names`: list of document names
  - aliases also accepted: `documentNames`, `documents`, `docs`, `file_names`, `fileNames`, `files`
  - `existing_values`: optional previously collected metadata
- The chatbot endpoint infers document kinds from file extensions and returns `ChatbotMetadataResponse`.
- The conversation endpoint is the preferred chatbot API. It behaves like a small graph:
  - merge server/client memory,
  - apply pending answer,
  - extract metadata,
  - apply document-derived format rules,
  - decide the next missing field,
  - return bot message plus updated memory.

### `documents.py`

- Owns file/document extension detection.
- Resolves production format from document names or uploaded files.
- Applies deterministic file overrides and upload warnings.

### `pipeline.py`

- Owns the extraction pipeline.
- Calls `OpenAILLMClient`.
- Runs `FormMatcher`.
- Converts pending-field answers into extraction-friendly text.

### `conversation.py`

- Owns short-term memory and next-action decisions.
- Tracks `metadata`, `document_names`, `pending_field`, `asked_fields`, and `turn_count`.

### `POST /conversation/turn`

Frontend request:

```json
{
  "session_id": "optional-existing-session-id",
  "message": "Create a pdf titled VWD Journey valid for 1 year",
  "documents": ["vwd.pdf"],
  "existing_values": {}
}
```

Frontend response:

```json
{
  "session_id": "server-session-id",
  "bot_message": "Please enter the author of the document.",
  "next_action": "ask_user",
  "pending_field": "keyAuthor",
  "missing_fields": ["keyAuthor"],
  "memory": {
    "metadata": {
      "title": "VWD Journey",
      "fileType": "pdf",
      "formatType": "pdf"
    },
    "document_names": ["vwd.pdf"],
    "pending_field": "keyAuthor",
    "asked_fields": ["keyAuthor"],
    "turn_count": 1
  },
  "mapped_fields": {
    "title": "VWD Journey",
    "fileType": "pdf",
    "formatType": "pdf"
  }
}
```

On the next user answer, frontend sends:

```json
{
  "session_id": "server-session-id",
  "message": "Shivam Kamal"
}
```

Because `pending_field` is `keyAuthor`, backend treats the plain answer as the author and updates memory. When all required fields are present, `next_action` becomes `ready`.

### `llm.py`

- Contains `OpenAILLMClient`.
- Uses the official OpenAI Python SDK.
- Requests JSON output with `response_format={"type": "json_object"}`.
- Keeps the strict extraction behavior from the local version:
  - strict title patterns,
  - strict author patterns,
  - supported formats: `pdf`, `ebook`, `ebook+ video`, `video`, `MS Office`,
  - `formatType` mirrors `fileType`,
  - chapter names are only returned when present.
- Falls back to regex extraction if OpenAI is unavailable, unconfigured, or returns invalid JSON.

### `matcher.py`

- Contains `FormMatcher`.
- Preserves the post-processing behavior from `Local_LLM-v1`.
- Uses OpenAI in the optional `extract_metadata()` helper instead of local Ollama.
- Normalizes formats, boolean hints, chapter names, and expiry datetime.
- Defaults `expDatetime` to one year from the prompt time when no expiry is present.

### `schema.py`

- Pydantic request and response models.
- Keeps the downstream form field surface compatible with the local version.

### `POST.txt`

- Example downstream payload reference retained from the original folder.

## Production Format Rules

- one PDF -> `pdf`
- multiple PDFs -> `ebook`
- one video -> `video`
- multiple videos -> `ebook+ video`
- PDFs plus videos -> `ebook+ video`
- any Word, Excel, or PowerPoint upload -> `MS Office`

The detected format is always written to both `fileType` and `formatType`.
