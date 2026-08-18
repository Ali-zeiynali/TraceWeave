import pytest

from traceweave.models import ResearchSpec
from traceweave.planner import Planner


@pytest.mark.asyncio
async def test_fallback_planner_changes_between_rounds():
    planner = Planner(None)
    spec = ResearchSpec(topic="Example Corp", angle="technology", max_rounds=2)
    first = await planner.initial(spec)
    second = await planner.replan(
        spec,
        round_no=2,
        completed_queries=first.queries,
        sources=[],
    )
    assert first.queries
    assert second.queries
    assert set(first.queries).isdisjoint(set(second.queries))
