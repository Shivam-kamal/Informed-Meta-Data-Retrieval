# Metadata AI Chatbot Knowledge

## Use Case

We are building a production-ready conversational metadata assistant.

The frontend sends:
- user message
- document names
- optional session id
- optional existing metadata

The backend should:
- remember short-term conversation state
- extract metadata using OpenAI
- infer file type from document names
- ask follow-up questions for missing required fields
- update metadata when user answers a pending question
- return a clean JSON response for frontend

## Required Fields

Required:
- documents
- title
- keyAuthor
- fileType

Derived:
- formatType mirrors fileType

Conditional:
- chapter is required when fileType is ebook

Optional:
- expDatetime
- allowDownload
- allowShare
- other downstream metadata fields

## Main Chat Flow

1. Receive user message.
2. Load or initialize conversation state.
3. If pending_field exists, treat the new message as an answer to that field.
4. Extract metadata from the message using LLM.
5. Merge extracted metadata into existing metadata.
6. Infer fileType and formatType from document names.
7. Validate required fields.
8. If something is missing, return a bot question.
9. If everything required is present, return next_action = ready.

## Planned Architecture

FastAPI API layer:
- app/main.py
- app/routes.py

Config:
- app/config.py

Schemas:
- app/schemas.py

LangGraph state:
- app/state.py

LLM extraction:
- app/llm.py

Workflow graph:
- app/workflow.py

Memory:
- short-term: LangGraph checkpointer
- local/dev: SQLite or in-memory
- production: Postgres/Redis checkpointer later

## Graph Nodes

Planned nodes:
- normalize_input
- apply_pending_answer
- extract_metadata
- merge_metadata
- infer_document_format
- validate_required_fields
- decide_next_action

## Current Status

Done:
- project folder setup
- config.py setup
- state.py planned

In Progress:
- LangGraph state design

Left:
- schemas.py
- llm.py
- workflow.py graph nodes
- routes.py
- tests
- production memory/checkpointer
