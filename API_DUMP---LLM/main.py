from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from conversation import ConversationStore
from llm import OpenAILLMClient
from routes import create_router


def create_app() -> FastAPI:
    app = FastAPI(
        title="OpenAI Metadata Prompt Autofill API",
        description="Backend-only API for conversational metadata extraction.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    llm_client = OpenAILLMClient()
    conversation_store = ConversationStore()
    app.include_router(create_router(llm_client, conversation_store))
    return app

app = create_app()