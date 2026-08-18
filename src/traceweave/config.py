from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="TRACEWEAVE_",
        extra="ignore",
    )

    data_dir: Path = Path(".traceweave")
    search_backend: Literal["auto", "searxng", "ddgs"] = "auto"
    searxng_url: str = "http://127.0.0.1:8080"
    search_timeout_seconds: float = 20.0
    fetch_timeout_seconds: float = 20.0
    fetch_max_bytes: int = 2_000_000
    fetch_concurrency: int = Field(default=3, ge=1, le=12)
    user_agent: str = "TraceWeave/0.1"

    api_base: str = ""
    api_key: str = ""
    model: str = ""
    llm_timeout_seconds: float = 60.0
    llm_temperature: float = 0.2

    @property
    def db_path(self) -> Path:
        return self.data_dir / "traceweave.db"

    @property
    def llm_configured(self) -> bool:
        return bool(self.api_base and self.api_key and self.model)

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        (self.data_dir / "sources").mkdir(parents=True, exist_ok=True)
        (self.data_dir / "exports").mkdir(parents=True, exist_ok=True)
