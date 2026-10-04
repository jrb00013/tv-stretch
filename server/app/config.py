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
    #: Seconds of continuous above-threshold occupancy before a handoff fires.
    #: Defaults to 0 (off) so a single reading keeps handing off immediately; raise it
    #: to stop sensor noise / passers-by from thrashing the TVs.
    presence_dwell_seconds: float = 0.0
    #: A reporting gap longer than this restarts the dwell timer.
    presence_dwell_max_gap_seconds: float = 30.0
    #: Seconds of sustained below-threshold reporting in the active room before the
    #: TVs are told to stand by (0 = off).
    presence_release_seconds: float = 0.0
    mqtt_broker_url: str = "localhost"
    mqtt_broker_port: int = 1883
    mqtt_enabled: bool = True
    mqtt_prefix: str = "tvstretch"
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

    @field_validator(
        "presence_dwell_seconds", "presence_dwell_max_gap_seconds", "presence_release_seconds"
    )
    @classmethod
    def validate_non_negative_seconds(cls, v: float) -> float:
        if v < 0:
            raise ValueError("presence timing settings must be >= 0 seconds")
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

    @property
    def is_testing(self) -> bool:
        return os.getenv("TV_STRETCH_ENV") == "testing"


settings = Settings()
