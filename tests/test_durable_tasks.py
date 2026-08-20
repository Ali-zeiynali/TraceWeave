from __future__ import annotations

from pathlib import Path

from traceweave.models import ResearchSpec
from traceweave.storage import Storage


def _storage(tmp_path: Path) -> tuple[Storage, str]:
    storage = Storage(tmp_path / "db.sqlite", tmp_path / "data")
    storage.init()
    return storage, storage.create_run(ResearchSpec(topic="Durable investigation", mode="overnight"))


def test_task_dependencies_and_idempotency(tmp_path: Path) -> None:
    storage, run_id = _storage(tmp_path)
    first = storage.enqueue_task(run_id, "round", {"round": 1}, dedupe_key="round:1")
    assert storage.enqueue_task(run_id, "round", {"ignored": True}, dedupe_key="round:1") == first
    second = storage.enqueue_task(run_id, "round", {"round": 2}, dedupe_key="round:2", depends_on=[first])

    lease = storage.lease_tasks(run_id, "worker-a", limit=5)
    assert [row["id"] for row in lease] == [first]
    assert storage.complete_task(first, {"ok": True})

    lease = storage.lease_tasks(run_id, "worker-b", limit=5)
    assert [row["id"] for row in lease] == [second]
    assert lease[0]["payload"] == {"round": 2}


def test_task_retry_and_content_addressed_artifacts(tmp_path: Path) -> None:
    storage, run_id = _storage(tmp_path)
    task_id = storage.enqueue_task(run_id, "fetch", {}, dedupe_key="fetch:1", max_attempts=2)
    assert storage.lease_tasks(run_id, "worker")[0]["id"] == task_id
    assert storage.fail_task(task_id, "temporary", retry_delay_seconds=0) == "retry"
    assert storage.lease_tasks(run_id, "worker")[0]["attempt_count"] == 2
    assert storage.fail_task(task_id, "permanent", retry_delay_seconds=0) == "failed"

    paused = storage.enqueue_task(run_id, "round", {}, dedupe_key="paused")
    assert storage.lease_tasks(run_id, "worker")[0]["id"] == paused
    assert storage.release_task(paused)
    assert storage.lease_tasks(run_id, "worker")[0]["attempt_count"] == 1

    artifact_a = storage.save_artifact(run_id, b"same bytes", media_type="image/png")
    artifact_b = storage.save_artifact(run_id, b"same bytes", media_type="image/png")
    assert artifact_a == artifact_b
    observation_id = storage.add_observation(
        run_id,
        kind="ocr_text",
        value_text="Project Lantern",
        artifact_id=artifact_a,
        locator={"bbox": [10, 20, 100, 40], "page": 1},
        confidence=0.93,
        importance=91,
        rarity=88,
    )
    rows = storage.observations_for_run(run_id)
    assert rows[0]["id"] == observation_id
    assert rows[0]["importance"] == 91


def test_overnight_defaults_are_bounded() -> None:
    spec = ResearchSpec(topic="Overnight research", mode="overnight")
    assert spec.resolved_rounds() == 8
    assert spec.resolved_depth() == 4
    assert spec.resolved_frontier_pages() == 120
    assert spec.resolved_deadline_minutes() == 720
