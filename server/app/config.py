import os
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TV_STRETCH_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./tv_stretch.db"
    api_title: str = "tv-stretch coordinator"
    api_version: str = "0.6.1"
    cors_origins: str = "*"
    public_base_url: str = "http://127.0.0.1:8000"
    ota_firmware_path: str = ""
    ota_firmware_version: str = "0.6.1"
    presence_handoff_min_confidence: float = 0.65
    debug: bool = False
    log_level: str = "INFO"
    max_nodes_per_home: int = 20
    max_rooms_per_home: int = 50

    @field_validator("presence_handoff_min_confidence")
    @classmethod
    def validate_confidence(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("presence_handoff_min_confidence must be between 0 and 1")
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in valid_levels:
            raise ValueError(f"log_level must be one of: {valid_levels}")
        return v.upper()

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        if not v:
            raise ValueError("database_url cannot be empty")
        if v.startswith("sqlite") and ":///" not in v:
            raise ValueError("sqlite URL must include :///")
        return v

    @field_validator("ota_firmware_path")
    @classmethod
    def validate_ota_path(cls, v: str) -> str:
        if v and not Path(v).exists():
            raise ValueError(f"OTA firmware path does not exist: {v}")
        return v

    @property
    def is_production(self) -> bool:
        return os.getenv("TV_STRETCH_ENV") == "production"

    @property
    def is_development(self) -> bool:
        return os.getenv("TV_STRETCH_ENV") == "development"


settings = Settings()
