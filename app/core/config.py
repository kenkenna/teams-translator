from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    anthropic_api_key: str = Field(..., env="ANTHROPIC_API_KEY")
    whisper_realtime_model: str = Field(default="base", env="WHISPER_REALTIME_MODEL")
    whisper_batch_model: str = Field(default="large-v3", env="WHISPER_BATCH_MODEL")
    translation_model: str = Field(default="claude-haiku-4-5-20251001", env="TRANSLATION_MODEL")
    summary_model: str = Field(default="claude-sonnet-4-6", env="SUMMARY_MODEL")
    recordings_dir: str = Field(default="recordings", env="RECORDINGS_DIR")
    db_path: str = Field(default="meetings.db", env="DB_PATH")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
