from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def load_project_env(path: Path = Path(".env")) -> None:
    """Load simple dotenv assignments without overwriting the parent process environment.

    Provider presets intentionally use unprefixed variables (for example GROQ_API_KEY),
    which pydantic-settings does not expose as Settings fields. Loading them once here makes
    the documented `.env` workflow actually work while keeping values out of persistence/logs.
    """
    if not path.is_file():
        return
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or not key.replace("_", "a").isalnum() or key[0].isdigit():
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="TRACEWEAVE_", extra="ignore")

    data_dir: Path = Path(".traceweave")
    search_backend: Literal["auto", "searxng", "ddgs"] = "auto"
    searxng_url: str = "http://127.0.0.1:8080"
    search_timeout_seconds: float = 20.0

    fetch_timeout_seconds: float = 20.0
    fetch_max_bytes: int = 3_000_000
    fetch_concurrency: int = Field(default=4, ge=1, le=16)
    user_agent: str = "TraceWeave/1.0.2 (+https://github.com/traceweave/traceweave)"
    research_query_concurrency: int = Field(default=3, ge=1, le=8)
    respect_robots: bool = True

    provider_config: Path = Path("providers.toml")
    llm_timeout_seconds: float = 75.0
    llm_temperature: float = 0.15
    router_max_attempts: int = Field(default=6, ge=1, le=20)
    router_health_ttl_seconds: int = Field(default=900, ge=30, le=86_400)
    provider_catalog_ttl_seconds: int = Field(default=21_600, ge=300, le=604_800)
    provider_catalog_auto_sync: bool = True
    zero_cost_only: bool = True

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
    browser_backend: Literal["auto", "cloudflare", "local"] = "auto"
    browser_min_text_chars: int = Field(default=500, ge=0, le=10000)
    fetch_per_host_delay_seconds: float = Field(default=0.75, ge=0, le=30)
    fetch_retries: int = Field(default=2, ge=0, le=8)

    # Stage 4 specialist source adapters. All are passive/public-web only.
    archives_enabled: bool = True
    wayback_enabled: bool = True
    commoncrawl_enabled: bool = True
    academic_enabled: bool = True
    github_enabled: bool = True
    pdf_enabled: bool = True
    registry_sources_enabled: bool = True
    registry_queries_per_round: int = Field(default=1, ge=0, le=5)
    certificate_transparency_enabled: bool = True
    urlscan_enabled: bool = True
    sec_edgar_enabled: bool = True
    peeringdb_enabled: bool = True
    companies_house_enabled: bool = True
    public_social_enabled: bool = True
    bluesky_enabled: bool = True
    instagram_official_enabled: bool = False
    telegram_public_enabled: bool = False
    social_queries_per_round: int = Field(default=1, ge=0, le=5)
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

    # Public/passive collection policy. Authenticated scraping, access-control bypass,
    # active scanning, and raw model-authored shell commands are deliberately out of scope.
    public_data_only: bool = True
    allow_sensitive_public_data: bool = True
    exclude_minors: bool = True
    remote_vision_enabled: bool = False
    media_enabled: bool = True
    media_sources_per_round: int = Field(default=6, ge=0, le=50)
    media_assets_per_source: int = Field(default=4, ge=0, le=30)
    media_max_bytes: int = Field(default=8_000_000, ge=100_000, le=50_000_000)

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
        for name in ("sources", "exports", "cases", "sessions", "logs", "artifacts", "catalog"):
            (self.data_dir / name).mkdir(parents=True, exist_ok=True)
