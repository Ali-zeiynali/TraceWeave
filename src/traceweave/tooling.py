from __future__ import annotations

import importlib.util
import os
import shutil
from dataclasses import asdict, dataclass
from typing import Literal

Stability = Literal["stable", "conditional", "unstable", "import-only"]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    id: str
    category: str
    stability: Stability
    access: str
    cost: str = "free"
    env_vars: tuple[str, ...] = ()
    executable: str = ""
    python_module: str = ""
    passive: bool = True
    integrated: bool = True
    notes: str = ""

    def status(self) -> str:
        if not self.integrated:
            return "catalog-only"
        if self.python_module:
            return "ready" if importlib.util.find_spec(self.python_module) else "missing"
        if self.executable:
            return "ready" if shutil.which(self.executable) else "missing"
        if self.env_vars:
            return "ready" if all(os.getenv(name, "").strip() for name in self.env_vars) else "token-needed"
        return "built-in"

    def as_row(self) -> dict[str, str | bool]:
        return {**asdict(self), "env_vars": ",".join(self.env_vars), "status": self.status()}


# This catalog is also the policy boundary: only typed, passive actions are exposed to
# the autonomous engine. A user-triggered shell remains separate and fetched content/models
# can never turn arbitrary text into a command.
TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec("searxng", "search", "stable", "self-hosted HTTP API", notes="Primary zero-cost metasearch."),
    ToolSpec("ddgs", "search", "unstable", "public web", notes="Fallback; upstream markup can change."),
    ToolSpec("gdelt", "search", "stable", "public API", notes="No-key multilingual news discovery."),
    ToolSpec("mediawiki", "search", "stable", "public API", notes="No-key entity/reference discovery."),
    ToolSpec("hackernews", "search", "stable", "public Algolia API", notes="Technical community leads."),
    ToolSpec("rdap", "network", "stable", "public API", notes="Domain/IP registration data via RDAP."),
    ToolSpec(
        "dns-over-https",
        "network",
        "stable",
        "public API",
        notes="Passive DNS resolution, not port scanning.",
    ),
    ToolSpec("ripestat", "network", "stable", "public API", notes="ASN, prefix and routing context."),
    ToolSpec("peeringdb", "network", "stable", "public API", notes="Network/operator relationships."),
    ToolSpec(
        "urlscan",
        "web-intel",
        "conditional",
        "API",
        env_vars=("URLSCAN_API_KEY",),
        notes="Existing scans only; TraceWeave does not submit active scans.",
    ),
    ToolSpec("gleif", "corporate", "stable", "public API", notes="LEI and legal-entity records."),
    ToolSpec(
        "sec-edgar",
        "corporate",
        "stable",
        "public API",
        env_vars=("SEC_USER_AGENT",),
        notes="Public filer index; SEC-compliant contact-bearing User-Agent is required.",
    ),
    ToolSpec("companies-house", "corporate", "stable", "API", env_vars=("COMPANIES_HOUSE_API_KEY",)),
    ToolSpec("ror", "research", "stable", "public API", notes="Research organizations."),
    ToolSpec(
        "orcid",
        "research",
        "stable",
        "public API",
        notes="Candidate discovery only; name-only matches are never auto-merged.",
    ),
    ToolSpec("openalex", "research", "stable", "public API"),
    ToolSpec("crossref", "research", "stable", "public API"),
    ToolSpec("github", "code", "stable", "public API", env_vars=("TRACEWEAVE_GITHUB_TOKEN",)),
    ToolSpec(
        "telegram-public",
        "social",
        "conditional",
        "official user API",
        env_vars=("TELEGRAM_API_ID", "TELEGRAM_API_HASH"),
        notes="Public channels/messages only; no private groups or access bypass.",
    ),
    ToolSpec("bluesky", "social", "stable", "public AppView API"),
    ToolSpec(
        "instagram-official",
        "social",
        "conditional",
        "official Graph API",
        env_vars=("INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_USER_ID"),
        notes="Professional-account hashtag discovery; no login scraping.",
    ),
    ToolSpec(
        "mastodon",
        "social",
        "conditional",
        "public instance APIs",
        integrated=False,
        notes="Coverage depends on instance federation.",
    ),
    ToolSpec(
        "linkedin-official",
        "social",
        "conditional",
        "restricted official API",
        env_vars=("LINKEDIN_ACCESS_TOKEN",),
        integrated=False,
        notes="Limited by LinkedIn product approval.",
    ),
    ToolSpec(
        "linkedin-indexed",
        "social",
        "unstable",
        "public search/indexed pages",
        notes="No authenticated scraping, fake accounts, or access-control bypass.",
    ),
    ToolSpec(
        "linkedin-import",
        "social",
        "import-only",
        "user-provided export",
        integrated=False,
        notes="Recommended for complete account-owned data.",
    ),
    ToolSpec(
        "sherlock",
        "username",
        "conditional",
        "local CLI",
        executable="sherlock",
        integrated=False,
        notes="Public username existence checks.",
    ),
    ToolSpec(
        "maigret",
        "username",
        "conditional",
        "local CLI",
        executable="maigret",
        integrated=False,
        notes="Public profile discovery with false-positive validation.",
    ),
    ToolSpec(
        "spiderfoot-passive",
        "multi-source",
        "conditional",
        "local CLI",
        executable="spiderfoot",
        integrated=False,
        notes="Passive modules and existing public records only; no active target scans.",
    ),
    ToolSpec(
        "theharvester",
        "multi-source",
        "conditional",
        "local CLI",
        executable="theHarvester",
        integrated=False,
        notes="Passive search-engine and public API sources only.",
    ),
    ToolSpec(
        "amass-passive",
        "network",
        "conditional",
        "local CLI",
        executable="amass",
        integrated=False,
        notes="Only the passive subcommand/profile is allowed.",
    ),
    ToolSpec(
        "subfinder",
        "network",
        "conditional",
        "local CLI",
        executable="subfinder",
        integrated=False,
        notes="Passive data-source mode only.",
    ),
    ToolSpec(
        "whois",
        "network",
        "conditional",
        "local CLI fallback",
        executable="whois",
        integrated=False,
        notes="RDAP is preferred.",
    ),
    ToolSpec("dig", "network", "conditional", "local CLI", executable="dig", integrated=False),
    ToolSpec(
        "crtsh",
        "network",
        "conditional",
        "public certificate-transparency index",
        notes="Passive certificate-name discovery; availability is best effort.",
    ),
    ToolSpec(
        "tesseract",
        "media",
        "stable",
        "local deterministic CLI",
        executable="tesseract",
        notes="Multilingual OCR before optional model vision.",
    ),
    ToolSpec(
        "imagehash",
        "media",
        "stable",
        "local Python library",
        python_module="imagehash",
        notes="Perceptual fingerprints for deduplication and cross-source comparison.",
    ),
    ToolSpec(
        "opencv",
        "media",
        "conditional",
        "local Python library",
        python_module="cv2",
        notes="Optional deterministic image segmentation and quality analysis.",
    ),
    ToolSpec(
        "exiftool",
        "media",
        "stable",
        "local deterministic CLI",
        executable="exiftool",
        notes="Metadata only; no local ML.",
    ),
    ToolSpec(
        "ffprobe",
        "media",
        "stable",
        "local deterministic CLI",
        executable="ffprobe",
        notes="Media structure only; no local ML.",
    ),
    ToolSpec(
        "remote-vision",
        "media",
        "conditional",
        "configured free provider",
        notes="Explicit opt-in, strict call budget, region-level evidence.",
    ),
    ToolSpec(
        "reverse-image-results",
        "media",
        "import-only",
        "user-provided result",
        integrated=False,
        notes="No stable unrestricted zero-cost reverse-image API exists.",
    ),
)


def tool_status_rows() -> list[dict[str, str | bool]]:
    return [spec.as_row() for spec in TOOL_SPECS]


def tool_spec(tool_id: str) -> ToolSpec:
    for spec in TOOL_SPECS:
        if spec.id == tool_id:
            return spec
    raise KeyError(tool_id)
