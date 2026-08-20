from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass, field

from traceweave.providers.types import CredentialConfig, ModelConfig, ProviderConfig


@dataclass(frozen=True, slots=True)
class PresetModel:
    name: str
    tier: str
    tasks: tuple[str, ...]
    priority: int
    capabilities: tuple[str, ...] = ("text", "json")
    free: bool | None = None


@dataclass(frozen=True, slots=True)
class ProviderPreset:
    id: str
    base_url: str
    env_prefix: str
    models: tuple[PresetModel, ...] = ()
    dynamic_catalog: bool = True
    free_only_catalog: bool = False
    headers: dict[str, str] = field(default_factory=dict)
    warning: str = ""
    free_tier: bool = False


# Curated fallbacks are intentionally small. Dynamic model discovery augments these where safe.
# The routing task names are TraceWeave task classes, not provider-native tool calls.
PRESETS: dict[str, ProviderPreset] = {
    "agentrouter": ProviderPreset(
        id="agentrouter",
        base_url="https://co.agentrouter.org/v1",
        env_prefix="AGENTROUTER",
        models=(
            PresetModel("gpt-5.5", "strong", ("planning", "replanning", "verification", "synthesis"), 8),
            PresetModel("kimi-k2.6", "strong", ("planning", "replanning", "synthesis", "triage"), 12),
            PresetModel("glm-5.2", "strong", ("planning", "replanning", "synthesis", "triage"), 14),
            PresetModel("glm-5.1", "balanced", ("triage", "claim_extraction", "entity_extraction"), 28),
            PresetModel("step3p5-code-alpha", "specialist", ("github_analysis", "document_analysis"), 35),
        ),
        dynamic_catalog=True,
    ),
    "seekrouter": ProviderPreset(
        id="seekrouter",
        base_url="http://www.seekrouter.com/api/v1",
        env_prefix="SEEKROUTER",
        models=(),
        dynamic_catalog=True,
        warning="SeekRouter's documented API base is HTTP. Override SEEKROUTER_BASE_URL with HTTPS if available.",
    ),
    "zenmux": ProviderPreset(
        id="zenmux",
        base_url="https://zenmux.ai/api/v1",
        env_prefix="ZENMUX",
        models=(
            PresetModel(
                "z-ai/glm-5.3-free",
                "strong",
                ("planning", "replanning", "verification", "synthesis"),
                18,
                free=True,
            ),
            PresetModel(
                "z-ai/glm-4.7-flash-free",
                "fast",
                ("triage", "claim_extraction", "entity_extraction"),
                38,
                free=True,
            ),
            PresetModel(
                "z-ai/glm-4.6v-flash-free", "vision", ("vision",), 42, ("text", "json", "vision"), True
            ),
        ),
        dynamic_catalog=True,
        free_only_catalog=True,
    ),
    "openrouter": ProviderPreset(
        id="openrouter",
        base_url="https://openrouter.ai/api/v1",
        env_prefix="OPENROUTER",
        models=(PresetModel("openrouter/free", "auto-free", ("*",), 24, free=True),),
        dynamic_catalog=True,
        free_only_catalog=True,
        headers={"X-Title": "TraceWeave"},
    ),
    "mistral": ProviderPreset(
        id="mistral",
        base_url="https://api.mistral.ai/v1",
        env_prefix="MISTRAL",
        models=(PresetModel("mistral-small-latest", "balanced", ("*",), 34, free=True),),
        dynamic_catalog=True,
        free_tier=True,
    ),
    "gemini": ProviderPreset(
        id="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        env_prefix="GEMINI",
        models=(
            PresetModel(
                "gemini-3.7-flash",
                "strong",
                ("planning", "replanning", "verification", "synthesis", "document_analysis"),
                10,
                ("text", "json", "vision", "long_context"),
                True,
            ),
            PresetModel(
                "gemini-3.6-flash",
                "strong",
                ("planning", "replanning", "verification", "synthesis"),
                13,
                ("text", "json", "vision", "long_context"),
                True,
            ),
            PresetModel(
                "gemini-3.5-flash",
                "balanced",
                ("triage", "claim_extraction", "entity_extraction", "synthesis"),
                25,
                ("text", "json", "vision"),
                True,
            ),
            PresetModel(
                "gemini-3.5-flash-lite",
                "fast",
                ("triage", "claim_extraction", "entity_extraction"),
                40,
                ("text", "json", "vision"),
                True,
            ),
            PresetModel(
                "gemini-3.1-flash-lite",
                "fast",
                ("triage", "claim_extraction", "entity_extraction"),
                46,
                ("text", "json", "vision"),
                True,
            ),
        ),
        dynamic_catalog=False,
    ),
    "groq": ProviderPreset(
        id="groq",
        base_url="https://api.groq.com/openai/v1",
        env_prefix="GROQ",
        models=(
            PresetModel(
                "openai/gpt-oss-120b",
                "strong",
                ("planning", "replanning", "verification", "synthesis"),
                16,
                free=True,
            ),
            PresetModel(
                "openai/gpt-oss-20b",
                "fast",
                ("triage", "claim_extraction", "entity_extraction"),
                36,
                free=True,
            ),
            PresetModel(
                "qwen/qwen3.6-27b",
                "balanced",
                ("triage", "claim_extraction", "entity_extraction", "replanning"),
                30,
                free=True,
            ),
        ),
        dynamic_catalog=False,
        free_tier=True,
    ),
    "cerebras": ProviderPreset(
        id="cerebras",
        base_url="https://api.cerebras.ai/v1",
        env_prefix="CEREBRAS",
        models=(
            PresetModel("gpt-oss-120b", "strong", ("*",), 12, free=True),
            PresetModel(
                "zai-glm-4.7",
                "balanced",
                ("triage", "claim_extraction", "entity_extraction", "replanning"),
                26,
                free=True,
            ),
        ),
        dynamic_catalog=True,
        free_tier=True,
    ),
    "sambanova": ProviderPreset(
        id="sambanova",
        base_url="https://api.sambanova.ai/v1",
        env_prefix="SAMBANOVA",
        models=(PresetModel("Meta-Llama-3.3-70B-Instruct", "balanced", ("*",), 31, free=True),),
        dynamic_catalog=True,
        free_tier=True,
    ),
    "cloudflare": ProviderPreset(
        id="cloudflare",
        base_url="https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1",
        env_prefix="CLOUDFLARE",
        models=(
            PresetModel(
                "@cf/openai/gpt-oss-120b",
                "strong",
                ("planning", "replanning", "verification", "synthesis"),
                20,
                free=True,
            ),
            PresetModel(
                "@cf/openai/gpt-oss-20b",
                "fast",
                ("triage", "claim_extraction", "entity_extraction"),
                39,
                free=True,
            ),
            PresetModel(
                "@cf/google/gemma-4-26b-a4b-it",
                "vision",
                ("vision", "document_analysis"),
                32,
                ("text", "json", "vision", "long_context"),
                True,
            ),
        ),
        dynamic_catalog=False,
        free_tier=True,
        warning="Workers AI has a free daily allocation; third-party AI Gateway models are billable and are not configured here.",
    ),
    "nvidia-text": ProviderPreset(
        id="nvidia-text",
        base_url="https://integrate.api.nvidia.com/v1",
        env_prefix="NVIDIA_TEXT",
        models=(),
        dynamic_catalog=True,
        free_tier=True,
        warning="NVIDIA hosted API catalog and free credits can change; TraceWeave discovers models per key.",
    ),
    "nvidia-vision": ProviderPreset(
        id="nvidia-vision",
        base_url="https://integrate.api.nvidia.com/v1",
        env_prefix="NVIDIA_VISION",
        models=(),
        dynamic_catalog=True,
        free_tier=True,
        warning="Only catalog models classified as vision-capable are selected for image analysis.",
    ),
    "nararouter": ProviderPreset(
        id="nararouter",
        base_url="https://router.bynara.id/v1",
        env_prefix="NARAROUTER",
        models=(),
        dynamic_catalog=True,
        free_only_catalog=False,
        free_tier=True,
        warning="The live /models catalog is entitlement-scoped; free-plan quotas are isolated per token and model.",
    ),
    "aigate": ProviderPreset(
        id="aigate",
        base_url="https://api.aigate.shop/v1",
        env_prefix="AIGATE",
        models=(),
        dynamic_catalog=True,
        free_only_catalog=False,
        free_tier=True,
        warning="AIGate is treated as an unstable operator-provided gateway; catalog and route health are isolated per token.",
    ),
}


def _token_envs(prefix: str) -> Iterable[tuple[str, str]]:
    # Accept PREFIX_API_KEY as token 1 and also PREFIX_API_KEY_1 for users who prefer explicit numbering.
    first = os.getenv(f"{prefix}_API_KEY", "").strip() or os.getenv(f"{prefix}_API_KEY_1", "").strip()
    if first:
        yield (
            "token-1",
            f"{prefix}_API_KEY" if os.getenv(f"{prefix}_API_KEY", "").strip() else f"{prefix}_API_KEY_1",
        )
    for idx in range(2, 6):
        env = f"{prefix}_API_KEY_{idx}"
        if os.getenv(env, "").strip():
            yield f"token-{idx}", env


def providers_from_env(
    *, catalog_models: dict[str, dict[str, list[dict]]] | None = None
) -> list[ProviderConfig]:
    catalog_models = catalog_models or {}
    out: list[ProviderConfig] = []
    _install_credential_aliases()
    for pid, preset in PRESETS.items():
        token_specs = list(_token_envs(preset.env_prefix))
        creds = []
        for cid, env in token_specs:
            base_override = ""
            if pid == "cloudflare":
                idx = cid.rsplit("-", 1)[-1]
                account_env = "CLOUDFLARE_ACCOUNT_ID" if idx == "1" else f"CLOUDFLARE_ACCOUNT_ID_{idx}"
                account_id = os.getenv(account_env, "").strip()
                if not account_id:
                    continue
                base_override = preset.base_url.replace("{account_id}", account_id)
            creds.append(CredentialConfig(id=cid, token_env=env, base_url=base_override))
        if not creds:
            continue
        base_url = os.getenv(f"{preset.env_prefix}_BASE_URL", "").strip() or preset.base_url
        if "{account_id}" in base_url and pid != "cloudflare":
            continue
        models: list[ModelConfig] = []
        # Model availability is credential-scoped. Once a token has a successful catalog, only catalog models
        # (plus the universal OpenRouter free router) are bound to that token. Before first sync, curated fallbacks apply.
        provider_catalog = (
            catalog_models.get(pid, {}) if isinstance(catalog_models.get(pid, {}), dict) else {}
        )
        for credential in creds:
            discovered = (
                provider_catalog.get(credential.id, [])
                if isinstance(provider_catalog.get(credential.id, []), list)
                else []
            )
            seen: set[str] = set()
            if discovered:
                for item in discovered:
                    name = str(item.get("id") or item.get("name") or "").strip()
                    if not name or name in seen or not is_research_chat_model(name, item):
                        continue
                    if preset.free_only_catalog and item.get("is_free") is not True:
                        continue
                    tier, priority, tasks, capabilities = classify_model(pid, name, item)
                    if pid == "nvidia-vision" and "vision" not in capabilities:
                        continue
                    if pid == "nvidia-text" and "vision" in capabilities:
                        continue
                    models.append(
                        ModelConfig(
                            id=name,
                            name=name,
                            tasks=tasks,
                            capabilities=capabilities,
                            credentials={credential.id},
                            priority=priority,
                            extra={
                                "tier": tier,
                                "free": bool(item.get("is_free")) or preset.free_tier,
                                "discovered": True,
                            },
                        )
                    )
                    seen.add(name)
            else:
                for item in preset.models:
                    models.append(
                        ModelConfig(
                            id=item.name,
                            name=item.name,
                            tasks=set(item.tasks),
                            capabilities=set(item.capabilities),
                            credentials={credential.id},
                            priority=item.priority,
                            extra={"tier": item.tier, "free": item.free, "preset": True},
                        )
                    )
                    seen.add(item.name)
            if pid == "openrouter" and "openrouter/free" not in seen:
                models.append(
                    ModelConfig(
                        id="openrouter/free",
                        name="openrouter/free",
                        tasks={"*"},
                        capabilities={"text", "json"},
                        credentials={credential.id},
                        priority=24,
                        extra={"tier": "auto-free", "free": True, "preset": True},
                    )
                )
        if not models:
            continue
        out.append(
            ProviderConfig(
                id=pid,
                driver="openai_compat",
                base_url=base_url.rstrip("/"),
                enabled=True,
                credentials=creds,
                models=models,
                headers=dict(preset.headers),
            )
        )
    return out


def _install_credential_aliases() -> None:
    """Normalize user-facing aliases without logging or persisting credential values."""
    if os.getenv("AIGATEAPI_KEY", "").strip():
        os.environ.setdefault("AIGATE_API_KEY", os.environ["AIGATEAPI_KEY"])
    generic_nvidia = os.getenv("NVIDIA_API_KEY", "").strip()
    text = os.getenv("NVIDIA_TEXT_API_KEY", "").strip()
    vision = os.getenv("NVIDIA_VISION_API_KEY", "").strip()
    shared = generic_nvidia or text or vision
    if shared:
        os.environ.setdefault("NVIDIA_TEXT_API_KEY", shared)
        os.environ.setdefault("NVIDIA_VISION_API_KEY", shared)


def classify_model(provider: str, model: str, raw: dict | None = None) -> tuple[str, int, set[str], set[str]]:
    low = model.casefold()
    capabilities = {"text", "json"}
    provider_penalty = 45 if provider == "aigate" else 0
    if any(x in low for x in ("vision", "vl", "omni", "4.6v", "gemma-4")):
        capabilities.add("vision")
    if any(x in low for x in ("nano", "tiny", "mini", "lite", "flash", "20b", "8b", "7b")):
        return (
            "fast",
            48 + provider_penalty,
            {"intent", "triage", "claim_extraction", "entity_extraction"},
            capabilities,
        )
    if any(x in low for x in ("120b", "ultra", "pro", "medium", "large", "5.3", "opus", "k2.6", "gpt-5")):
        return (
            "strong",
            22 + provider_penalty,
            {"intent", "planning", "replanning", "verification", "synthesis", "document_analysis"},
            capabilities,
        )
    if provider == "openrouter" and model == "openrouter/free":
        return "auto-free", 24, {"*"}, capabilities
    return (
        "balanced",
        35 + provider_penalty,
        {"intent", "triage", "claim_extraction", "entity_extraction", "replanning"},
        capabilities,
    )


def preset_warnings() -> list[str]:
    warnings: list[str] = []
    for preset in PRESETS.values():
        if preset.warning and any(True for _ in _token_envs(preset.env_prefix)):
            warnings.append(f"{preset.id}: {preset.warning}")
    return warnings


def has_env_credentials() -> bool:
    return any(any(True for _ in _token_envs(p.env_prefix)) for p in PRESETS.values())


def is_research_chat_model(name: str, raw: dict | None = None) -> bool:
    low = name.casefold()
    if any(
        x in low
        for x in (
            "embedding",
            "embed",
            "moderation",
            "rerank",
            "tts",
            "speech",
            "transcribe",
            "whisper",
            "image-generation",
            "image_generation",
        )
    ):
        return False
    meta = (raw or {}).get("raw") if isinstance(raw, dict) else None
    if isinstance(meta, dict):
        output = meta.get("output_modalities") or (meta.get("architecture") or {}).get("output_modalities")
        if isinstance(output, list) and output and "text" not in {str(x).casefold() for x in output}:
            return False
    return True
