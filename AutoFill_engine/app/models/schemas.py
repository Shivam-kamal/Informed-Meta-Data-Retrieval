from typing import Any, Literal

from pydantic import BaseModel, Field


FRONTEND_METADATA_TEMPLATE: dict[str, Any] = {
    "productionNotes": None,
    "production": None,
    "sales": None,
    "costCenter": None,
    "limit": None,
    "file": None,
    "officeFile": None,
    "title": None,
    "expDatetime": None,
    "company": None,
    "country": None,
    "pdfSubTitle": None,
    "keyAuthor": None,
    "multiplePublisher": None,
    "allowShare": None,
    "allowDownload": None,
    "associatedAge": None,
    "associatedTouchpoint": None,
    "femaleOriented": None,
    "pushed_vwdJourney": None,
    "hideHCP": None,
    "creation_date": None,
    "marketing_folder_name": None,
    "allowPrint": None,
    "product": None,
    "fileType": None,
    "coverPhoto": None,
    "chapter": None,
    "specialRequirment": None,
    "createdBy": None,
    "category": None,
    "formatType": None,
    "ibu": None,
    "allowOneSource": None,
    "allowLibrary": None,
    "allowRequest": None,
    "allowDraft": None,
    "allowVideo": None,
    "comDatetime": None,
    "cpdValue": None,
    "tags": None,
    "functional_tags": None,
    "pushed_usa_flag": None,
}


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None
    documents: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None


class ChatResponse(BaseModel):
    session_id: str
    bot_message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    pending_field: str | None = None
    question: str | None = None
    next_action: Literal["ask_user", "ready", "error"]
