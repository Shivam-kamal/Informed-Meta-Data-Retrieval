from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field , model_validator


class ChapterInfo(BaseModel):
    chapterTitle: str = ""
    uploadFile: Optional[str] = ""
    fileValue: Optional[str] = ""
    selectedVideo: Optional[str] = ""


class PromptContext(BaseModel):
    countries: List[str] = Field(default_factory=list)
    products: List[str] = Field(default_factory=list)
    categories: List[str] = Field(default_factory=list)
    languages: List[str] = Field(default_factory=list)
    formats: List[str] = Field(default_factory=list)
    ibu_options: List[str] = Field(default_factory=list)
    tags: List[str] = Field(default_factory=list)
    functional_tags: List[str] = Field(default_factory=list)
    trials: List[str] = Field(default_factory=list)
    blind_types: List[str] = Field(default_factory=list)
    marketing_folders: List[str] = Field(default_factory=list)

class AutofillRequest(BaseModel):
    prompt: str = Field(..., min_length=3, description="Natural language prompt from user")
    context: PromptContext = Field(default_factory=PromptContext)
    existing_values: Dict[str, Any] = Field(default_factory=dict)
    account_id: Optional[str] = None
    strict_mode: bool = True

class FormFieldUpdate(BaseModel):
    title: Optional[str] = None  # formerly contentTitle
    keyAuthor: Optional[str] = None
    company: Optional[str] = None
    country: Optional[str] = None
    pdfSubTitle: Optional[str] = None  # formerly journalTitle
    allowShare: Optional[bool] = None
    allowDownload: Optional[bool] = None
    allowPrint: Optional[bool] = None
    product: Optional[str] = None
    fileType: Optional[str] = None  # formerly docintelFormat
    specialRequirment: Optional[str] = None
    productionNotes: Optional[str] = None
    category: Optional[str] = None
    language: Optional[str] = None
    newLanguageCode: Optional[str] = None
    formatType: Optional[str] = None  # formerly format
    ibu: Optional[str] = None
    allowOneSource: Optional[bool] = None
    allowRequest: Optional[bool] = None
    allowDraft: Optional[bool] = None
    allowVideo: Optional[int] = None  # POST shows 0
    comDatetime: Optional[str] = None
    expDatetime: Optional[str] = None
    cpdValue: Optional[str] = None
    request_quote: Optional[bool] = None
    pharmaArr: Optional[str] = None
    associatedAge: Optional[List[str]] = None
    associatedTouchpoint: Optional[List[str]] = None
    hideHCP: Optional[bool] = None
    femaleOriented: Optional[bool] = None
    creation_date: Optional[str] = None
    pushed_usa_flag: Optional[bool] = None
    pushed_vwdJourney: Optional[bool] = None
    sync_onesource: Optional[bool] = None
    marketing_folder_name: Optional[str] = None
    trial: Optional[str] = None
    blindType: Optional[str] = None
    mandatory: Optional[bool] = None
    medical: Optional[bool] = None
    trail_user_type: Optional[List[str]] = None
    tags: Optional[List[str]] = None  # formerly selectedClinicalTopic
    functional_tags: Optional[List[str]] = None  # formerly selectedFunctionTopic
    
    production: Optional[int] = None
    sales: Optional[int] = None
    costCenter: Optional[str] = None
    limit: Optional[str] = None
    multiplePublisher: Optional[List[str]] = None
    chapter: Optional[List[ChapterInfo]] = None
    allowLibrary: Optional[int] = None
    createdBy: Optional[str] = None
    officeFile: Optional[str] = None

    @model_validator(mode="after")
    def validate_required_fields(self):
        errors = []

        if not self.title or not self.title.strip():
            errors.append("title is required!")

        if not self.keyAuthor or not self.keyAuthor.strip():
            errors.append("keyAuthor is required!")

        normalized_file_type = (self.fileType or "").strip().lower()
        normalized_format_type = (self.formatType or "").strip().lower()

        if not normalized_file_type and not normalized_format_type:
            errors.append("format is required!")

        normalized_format = normalized_file_type or normalized_format_type
        allowed_formats = {"pdf", "ebook", "e-book", "video", "ebook+ video", "ms office"}
        if normalized_format not in allowed_formats:
            errors.append("format must be pdf, ebook, ebook+ video, video, or MS Office!")

        if normalized_format and not self.fileType:
            self.fileType = normalized_format

        if normalized_format and not self.formatType:
            self.formatType = normalized_format

        if errors:
            raise ValueError(" | ".join(errors))

        return self

class FieldEvidence(BaseModel):
    value: Any = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source: Literal["llm", "matcher", "existing_values", "default", "rule"] = "llm"
    reasoning: Optional[str] = None

class ExtractionResult(BaseModel):
    mapped_fields: Dict[str, Any] = Field(default_factory=dict)
    evidence: Dict[str, FieldEvidence] = Field(default_factory=dict)
    unresolved_fields: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    comments: Optional[str] = Field(None, description="LLM logic and analysis summary")
    raw_llm_output: Optional[Dict[str, Any]] = None
    

class FileInfo(BaseModel):
    file_name: str
    content_type: str
    status: str

class CombinedResponse(BaseModel):
    file_info: FileInfo
    files_info: List[FileInfo] = Field(default_factory=list)
    comments: Optional[str] = None
    mapped_fields: Dict[str, Any] = Field(default_factory=dict)
    unresolved_fields: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    confidence: float
    raw_parsed: Optional[Dict[str, Any]] = Field(default_factory=dict)


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    llm_configured: bool
    llm_endpoint: str
    llm_endpoint_reachable: bool
