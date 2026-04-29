# Knowledge Base

This folder is a backend-only OpenAI replica of `Local_LLM-v1`. It intentionally excludes `app.py`.

## Goal

Build a FastAPI metadata assistant that:

- accepts uploaded files plus a natural-language prompt,
- extracts structured metadata through the OpenAI API,
- falls back to local regex parsing if the API is not configured or fails,
- keeps downstream field names compatible with the existing payload,
- derives production file format from uploaded files instead of trusting the prompt,
- returns one clean `CombinedResponse` from the backend.

## Environment

- `OPENAI_API_KEY` is required for OpenAI extraction.
- `OPENAI_MODEL` is optional and defaults to `gpt-4.1-mini`.
- `OPENAI_BASE_URL` is optional for compatible gateways.
- `OPENAI_TIMEOUT` is optional and defaults to `60` seconds.

## File Map

### `main.py`

- FastAPI entrypoint.
- Endpoints:
  - `GET /health`
  - `POST /upload-and-analysis`
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
