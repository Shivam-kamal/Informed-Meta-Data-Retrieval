# Knowledge Base

This file is the working memory for the `DUMP` folder. We should update it whenever we change behavior, schema rules, endpoints, or the chat flow.

## Goal

Build a chatbot-driven metadata assistant that:

- takes a natural-language user prompt,
- extracts structured metadata fields,
- asks follow-up questions only for missing required data,
- supports five production formats: `pdf`, `ebook`, `ebook+ video`, `video`, and `MS Office`,
- derives the final format from uploaded files in `main.py` for production integration,
- treats plain ebook uploads as multiple PDF chapter files that need chapter names.

## Current Required Metadata Rules

- `title` is required.
- `keyAuthor` is required and represents the author field.
- `fileType` is required and must be one of:
  - `pdf`
  - `ebook`
  - `ebook+ video`
  - `video`
  - `MS Office`
- `formatType` mirrors `fileType` so both stay aligned with downstream payload expectations.
- In production `main.py`, uploaded files override any LLM/prompt guess for `fileType` and `formatType`.
- If format is plain `ebook`, `chapter` is required.
- For ebook flows, the number of chapter names should match the number of uploaded PDF files.
- `ebook+ video` is not forced to require chapters because it can also represent multiple uploaded videos.
- `expDatetime` should use `YYYY-MM-DD HH:MM:SS`.
- If the user mentions an expiry datetime, we should use it.
- If the user mentions relative expiry like `2 years`, `6 months`, or `30 days`, we should calculate the final datetime from now.
- If the user does not mention expiry, default to one year from the prompt time.
- Only `title`, `keyAuthor`, and format (`fileType` / `formatType`) should trigger follow-up questions in the chatbot UI.
- Other missing fields can remain warnings and should not trigger a user prompt for now.

## File Map

### `main.py`

- FastAPI entrypoint.
- Endpoints:
  - `GET /health`: local LLM configuration/reachability check.
  - `POST /upload-and-analysis`: multipart file upload plus prompt analysis.
- Accepts:
  - `files`: list of uploaded files
  - `prompt`: user prompt
  - `existing_values`: optional JSON string of previously collected metadata
- Validates uploaded content types.
- Calls `LocalLLMClient.extract_fields`.
- Passes LLM output through `FormMatcher.post_process`.
- Resolves the final production format from uploaded files:
  - one PDF -> `pdf`
  - multiple PDFs -> `ebook`
  - one video -> `video`
  - multiple videos -> `ebook+ video`
  - PDFs plus videos -> `ebook+ video`
  - any Word, Excel, or PowerPoint file -> `MS Office`
- Writes the detected format into both `fileType` and `formatType`.
- Adds workflow warnings for:
  - non-single-PDF cases mapped as `pdf`
  - single/no-PDF cases mapped as `ebook`
  - non-single-video cases mapped as `video`

### `llm1.py`

- Contains `LocalLLMClient`.
- Sends prompt to local Ollama-style endpoint.
- System prompt instructs the model to return strict JSON only.
- Current target fields include:
  - `title`
  - `keyAuthor`
  - `fileType`
  - `formatType`
  - `chapter`
- Prompt guidance now includes all five production formats:
  - `pdf`
  - `ebook`
  - `ebook+ video`
  - `video`
  - `MS Office`
- Title extraction prompt is strict parser-style:
  - only `title 'X'`, `title "X"`, `title: X`, `titled X`, `named X`, or `called X`
  - preserves underscores, numbers, casing, punctuation, and special characters exactly
  - returns an empty string instead of guessing
- Author extraction prompt is strict parser-style:
  - only `author is X` or `by X`
  - stops at `and`, comma, `with`, `expiry`, or `date`
  - returns an empty string instead of guessing
- If full schema validation fails, partial extracted fields are still preserved so the chatbot can continue collecting only the missing inputs.
- Fallback extraction can infer:
  - `allowDownload`
  - `allowShare`
  - all five production format values from prompt text
  - chapter titles from prompt text
  - simple `title:` and `author:` style values

### `matcher1.py`

- Contains `FormMatcher`.
- Extracts core conversational fields directly from the raw prompt for reliability:
  - `title`
  - `keyAuthor`
  - `fileType` / `formatType`
- Normalizes LLM output into allowed schema fields.
- Applies fuzzy matching using `PromptContext`.
- Applies boolean hint extraction.
- Normalizes format values to `pdf`, `ebook`, `ebook+ video`, `video`, or `MS Office`.
- Maps common Office terms and extensions such as Word, Excel, PowerPoint, `docx`, `xlsx`, and `pptx` to `MS Office`.
- Sets `allowVideo = 1` when the resolved format contains video behavior (`video` or `ebook+ video`).
- Marks unresolved required fields.
- For plain ebook requests:
  - tries to extract chapter names from the prompt,
  - stores them as `chapter = [{"chapterTitle": "..."}]`,
  - warns if chapter data is still missing.
- Normalizes `expDatetime` to `YYYY-MM-DD HH:MM:SS`.
- Uses the user-mentioned expiry datetime when present.
- Calculates relative expiry phrases like `2 years` or `6 months` into a final datetime.
- Defaults `expDatetime` to one year from prompt time if no expiry is mentioned.

### `schema1.py`

- Pydantic models for request and response shapes.
- `ChapterInfo` now models ebook chapter entries.
- `FormFieldUpdate` enforces required conversational metadata:
  - `title`
  - `keyAuthor`
  - format (`fileType` / `formatType`)
  - `chapter` for plain `ebook`
- Allowed formats are `pdf`, `ebook`, `ebook+ video`, `video`, and `MS Office`.

### `app.py`

- Streamlit prototype UI.
- Accepts multiple uploaded files.
- Uses `extract_metadata()` from `matcher1.py`.
- Tracks chat history and previously extracted values in session state.
- Generates targeted follow-up questions for:
  - title
  - author
  - format
- Mirrors the five-format upload detection from `main.py` for prototype/local testing.
- Does not ask follow-up questions for other missing fields; those remain warnings.
- If the bot is waiting for one field and the user replies with a full sentence containing multiple fields, the app should re-parse the whole sentence instead of forcing that entire reply into just one pending field.
- Adds UI warnings when:
  - `pdf` does not have exactly one PDF
  - `ebook` does not have multiple PDFs or matching chapter names for uploaded PDFs
  - `video` does not have exactly one video

## Known Workflow Intent

The intended chatbot behavior is:

1. User uploads file(s) and writes a prompt.
2. System extracts metadata from the prompt.
3. If `title`, `author`, or `format` is missing, chatbot asks for the missing field.
4. If format is `pdf`, normal single-file upload flow is fine.
5. If format is `ebook`, user should upload multiple PDFs and provide one chapter name for each PDF.
6. If format is `video`, user should upload exactly one video.
7. If format is `ebook+ video`, user can upload PDFs plus videos or multiple videos.
8. If any uploaded file is Word, Excel, or PowerPoint, format should be `MS Office`.
9. Final mapped output should stay compatible with downstream metadata payload usage.

## Known Gaps / Next Checks

- `frontend_live.jsx` has not yet been checked/aligned with the updated five-format workflow.
- `main.py` still returns a single `file_info` object even when multiple files are uploaded; this is okay for now but may need a richer response model.
- There are no automated tests yet for the five-format file detection and required-field rules.
- `POST.txt` shows downstream payload expectations, but chapter-to-file binding is still only name-level, not actual file mapping.
- The fallback extractor is still regex-based, so more natural phrasing variants may need to be added over time.

## Update Rule

Whenever we change any of these files:

- `main.py`
- `llm1.py`
- `matcher1.py`
- `schema1.py`
- `app.py`

we should also update `knowledge.md` so the current behavior stays documented in one place.
