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
    #: Minimum occupancy confidence (0–1) to trigger TV handoff from POST /presence/occupancy.
    presence_handoff_min_confidence: float = 0.65
    debug: bool = False


settings = Settings()
