import json
import logging

from openai import OpenAI

from app.core.config import Settings
from app.models.state import ChatState

MODEL = "gpt-4.1-mini"
logger = logging.getLogger(__name__)


def _client() -> OpenAI:
    settings = Settings()
    timeout = float(settings.openai_timeout or 60)
    return OpenAI(api_key=settings.openai_api_key or None, timeout=timeout)


def generate_response(state: ChatState) -> str:
    next_action = state.get("next_action")

    if next_action == "ready":
        return "Your Form is ready, Please Click Next!! "

    question = state.get("pending_question") or state.get("bot_message") or ""
    if next_action != "ask_user" or not question:
        return question

    payload = {
        "pending_field": state.get("pending_field"),
        "question": question,
        "next_action": next_action,
        "metadata": state.get("metadata", {}),
        
    }

    try:
        response = _client().chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You rephrase deterministic form autofill prompts. "

                        "Keep the response short, friendly, and natural. "
                        "Use 1-2 lines only. Do not add facts, assumptions, or extra information."
                        "Only ask for the provided question."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(payload, ensure_ascii=True),
                },
            ],
            temperature=0.2,
            max_tokens=60,
        )
    except Exception as exc:
        logger.warning(
            "OpenAI prompt rephrase failed; using deterministic question | session_id=%s | pending_field=%s | error=%s",
            state.get("session_id"),
            state.get("pending_field"),
            exc,
        )
        return question

    message = response.choices[0].message.content
    return message.strip() if message else question
