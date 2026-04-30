from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field 
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    app_name: str ="MetaData Retreival Open Ai Version"
    environment: str =Field(default="local")

    openai_api_key:str = Field(default="", validation_alias="OPENAI_API_KEY")
    openai_model: str= Field(default="gpt-4.1-mini", validation_alias="OPENAI_MODEL")
    openai_timeout:str= Field(default="60", validation_alias="OPENAI_TIMEOUT")

    cors_allow_origins:list[str]= ["*"]
    model_config = SettingsConfigDict(
    env_file= str(Path(__file__).resolve().parents[2] / ".env"),
    env_file_encoding="utf-8",
    extra="ignore",
    )
