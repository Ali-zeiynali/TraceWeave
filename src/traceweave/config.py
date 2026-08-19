from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="TRACEWEAVE_", extra="ignore")

    data_dir: Path = Path(".traceweave")
    search_backend: Literal["auto", "searxng", "ddgs"] = "auto"
    searxng_url: str = "http://127.0.0.1:8080"
    search_timeout_seconds: float = 20.0

    fetch_timeout_seconds: float = 20.0
    fetch_max_bytes: int = 3_000_000
    fetch_concurrency: int = Field(default=4, ge=1, le=16)
    user_agent: str = "TraceWeave/0.5 (+https://github.com/traceweave/traceweave)"
    respect_robots: bool = True

    provider_config: Path = Path("providers.toml")
    llm_timeout_seconds: float = 75.0
    llm_temperature: float = 0.15
    router_max_attempts: int = Field(default=6, ge=1, le=20)
    router_health_ttl_seconds: int = Field(default=900, ge=30, le=86_400)
    provider_catalog_ttl_seconds: int = Field(default=21_600, ge=300, le=604_800)
    provider_catalog_auto_sync: bool = True

    # Legacy single OpenAI-compatible endpoint; automatically converted to one router deployment.
    api_base: str = ""
    api_key: str = ""
    model: str = ""

    triage_enabled: bool = True
    claims_enabled: bool = True
    claims_max_sources_per_round: int = Field(default=8, ge=0, le=50)
    claim_min_relevance: float = Field(default=55, ge=0, le=100)

    frontier_enabled: bool = True
    frontier_min_score: float = Field(default=0.16, ge=0, le=1)
    frontier_per_domain_limit: int = Field(default=8, ge=1, le=50)
    sitemap_enabled: bool = True
    browser_fallback: bool = False
    browser_min_text_chars: int = Field(default=500, ge=0, le=10000)

    # Stage 4 specialist source adapters. All are passive/public-web only.
    archives_enabled: bool = True
    wayback_enabled: bool = True
    commoncrawl_enabled: bool = True
    academic_enabled: bool = True
    github_enabled: bool = True
    pdf_enabled: bool = True
    specialist_queries_per_round: int = Field(default=3, ge=0, le=12)
    specialist_results_per_query: int = Field(default=5, ge=1, le=20)
    archive_sources_per_round: int = Field(default=4, ge=0, le=20)
    archive_captures_per_source: int = Field(default=3, ge=1, le=10)
    pdf_max_bytes: int = Field(default=20_000_000, ge=1_000_000, le=100_000_000)
    github_token: str = ""
    openalex_mailto: str = ""

    # Stage 5 foundation.
    entity_graph_enabled: bool = True
    entity_sources_per_round: int = Field(default=10, ge=0, le=50)

    shell_enabled: bool = False
    shell_timeout_seconds: float = Field(default=30.0, ge=1, le=300)
    shell_max_output_chars: int = Field(default=20_000, ge=1000, le=200_000)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "traceweave.db"

    @property
    def llm_configured(self) -> bool:
        return self.provider_config.exists() or bool(self.api_base and self.api_key and self.model)

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        for name in ("sources", "exports", "sessions", "logs", "artifacts", "catalog"):
            (self.data_dir / name).mkdir(parents=True, exist_ok=True)
