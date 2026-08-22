from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from traceweave import __version__
from traceweave.identity import IdentityResolver
from traceweave.mcp import MCPServer, StreamableHTTPMCPClient, load_mcp_servers
from traceweave.models import ResearchSpec, SearchResult
from traceweave.sources.registries import RegistrySources
from traceweave.storage import Storage
from traceweave.verification import ClaimVerifier


def _storage(tmp_path: Path) -> tuple[Storage, str]:
    storage = Storage(tmp_path / "db.sqlite", tmp_path / "data")
    storage.init()
    return storage, storage.create_run(ResearchSpec(topic="Example investigation", mode="deep"))


def test_public_version_and_v102_schema(tmp_path: Path) -> None:
    storage, run_id = _storage(tmp_path)
    assert __version__ == "1.0.2"
    assert storage.claim_assessments_for_run(run_id) == []
    assert storage.identity_hypotheses_for_run(run_id) == []
    assert storage.artifact_matches_for_run(run_id) == []


@pytest.mark.asyncio
async def test_dns_adapter_collects_multiple_record_types(monkeypatch: pytest.MonkeyPatch) -> None:
    source = RegistrySources()

    async def fake_get(url: str, *, params=None, headers=None):
        del url, headers
        record_type = params["type"]
        if record_type in {"A", "MX", "TXT"}:
            return {"Answer": [{"data": f"value-{record_type}"}]}
        return {}

    monkeypatch.setattr(source, "_get", fake_get)
    rows = await source._dns("example.com")
    assert {row.title for row in rows} == {
        "DNS A: example.com",
        "DNS MX: example.com",
        "DNS TXT: example.com",
    }
    assert all(row.engine == "dns-over-https" for row in rows)


@pytest.mark.asyncio
async def test_peeringdb_uses_supported_filter_and_deduplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = RegistrySources()
    params_seen: list[dict[str, str]] = []

    async def fake_get(url: str, *, params=None, headers=None):
        del url, headers
        params_seen.append(params)
        return {"data": [{"id": 42, "name": "Cloudflare, Inc."}]}

    monkeypatch.setattr(source, "_get", fake_get)
    rows = await source._peeringdb("Cloudflare cloudflare.com", 5)
    assert all("name__contains" in params for params in params_seen)
    assert all("name__icontains" not in params for params in params_seen)
    assert [row.url for row in rows] == ["https://www.peeringdb.com/org/42"]


@pytest.mark.asyncio
async def test_verifier_requires_independent_domains_for_corroboration(tmp_path: Path) -> None:
    storage, run_id = _storage(tmp_path)
    for index, domain in enumerate(("a.example", "b.example"), 1):
        source_id = storage.add_search_result(
            run_id,
            "query",
            index,
            SearchResult(url=f"https://{domain}/report", title=domain),
        )
        storage.save_snapshot(
            source_id=source_id,
            final_url=f"https://{domain}/report",
            status_code=200,
            content_type="text/plain",
            content_hash=f"hash-{index}",
            raw=b"Acme launched Project North in 2026.",
            text="Acme launched Project North in 2026.",
            extracted_title=domain,
        )
        storage.add_claim(
            run_id,
            source_id,
            claim_text="Acme launched Project North in 2026.",
            quote="Acme launched Project North in 2026.",
            subject="Acme",
            predicate="launched",
            object_text="Project North",
            observed_at="2026",
            confidence=0.9,
            char_start=0,
            char_end=36,
            verified_span=True,
        )
    counts = await ClaimVerifier(storage, None).assess(
        run_id, ResearchSpec(topic="Example investigation", mode="deep")
    )
    assert counts == {"corroborated": 2}


def test_identity_media_matching_is_not_face_identification(tmp_path: Path) -> None:
    storage, run_id = _storage(tmp_path)
    first = storage.save_artifact(run_id, b"first", media_type="image/png")
    second = storage.save_artifact(run_id, b"second", media_type="image/png")
    storage.add_observation(run_id, kind="media:phash", value_text="0000000000000000", artifact_id=first)
    storage.add_observation(run_id, kind="media:phash", value_text="0000000000000001", artifact_id=second)
    saved = IdentityResolver(storage, None)._match_media(run_id)
    matches = storage.artifact_matches_for_run(run_id)
    assert saved == 1
    assert matches[0]["verdict"] == "near_duplicate"
    assert matches[0]["distance"] == 1


def test_verifier_rejects_different_event_dates_as_a_contradiction() -> None:
    claims = {
        1: {
            "id": 1,
            "subject": "Zone Settings Batch API",
            "predicate": "deprecated",
            "object_text": "end of life on March 31, 2027",
            "domain": "developers.cloudflare.com",
        },
        2: {
            "id": 2,
            "subject": "Zone Settings Batch API",
            "predicate": "deprecation date",
            "object_text": "April 23, 2025",
            "domain": "developers.cloudflare.com",
        },
    }
    fallback = {
        claim_id: {
            "verdict": "single_source",
            "confidence": 0.55,
            "supporting_claim_ids": [claim_id],
            "conflicting_claim_ids": [],
            "rationale": "fixture",
        }
        for claim_id in claims
    }
    result = ClaimVerifier._validate_model(
        {
            "assessments": [
                {
                    "claim_id": 2,
                    "verdict": "contested",
                    "supporting_claim_ids": [2],
                    "conflicting_claim_ids": [1],
                    "confidence": 0.8,
                    "rationale": "different dates",
                }
            ]
        },
        claims,
        fallback,
    )
    assert result[2]["verdict"] == "single_source"
    assert result[2]["conflicting_claim_ids"] == []


@pytest.mark.asyncio
async def test_streamable_http_mcp_discovery_uses_lifecycle_and_headers() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        method = payload["method"]
        methods.append(method)
        assert request.headers["mcp-method"] == method
        if method == "initialize":
            return httpx.Response(
                200,
                headers={"Mcp-Session-Id": "session-1"},
                json={
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": {
                        "protocolVersion": "2025-11-25",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "mock", "version": "1"},
                    },
                },
            )
        if method == "notifications/initialized":
            assert request.headers["mcp-session-id"] == "session-1"
            return httpx.Response(202)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {"tools": [{"name": "search", "inputSchema": {"type": "object"}}]},
            },
        )

    client = StreamableHTTPMCPClient(
        MCPServer("mock", "https://mcp.example/mcp", allowed_tools=("search",)),
        transport=httpx.MockTransport(handler),
    )
    tools = await client.list_tools()
    assert [tool["name"] for tool in tools] == ["search"]
    assert methods == ["initialize", "notifications/initialized", "tools/list"]


def test_mcp_config_rejects_non_loopback_plain_http(tmp_path: Path) -> None:
    config = tmp_path / "mcp.toml"
    config.write_text('[[servers]]\nname="bad"\nurl="http://example.com/mcp"\n', encoding="utf-8")
    with pytest.raises(Exception, match="HTTPS or loopback"):
        load_mcp_servers(config)
