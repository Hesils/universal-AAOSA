import os

import pytest
from dotenv import load_dotenv

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_LLM_TESTS"), reason="set RUN_LLM_TESTS=1 to run real-LLM smoke tests"
)


def test_broad_task_recovers_by_division():
    load_dotenv()
    from aaosa.demo.agents import DEMO_AGENTS
    from aaosa.demo.tools import attach_tools
    from aaosa.runtime.aggregator import TaskAggregator
    from aaosa.runtime.context import RunContext
    from aaosa.runtime.divider import TaskDivider
    from aaosa.runtime.llm_client import create_client
    from aaosa.runtime.runner import run_recovery
    from aaosa.runtime.tagger import Tagger
    from aaosa.schemas.output import Output
    from aaosa.tracing.events import TaskDividedEvent
    from aaosa.tracing.tracer import Tracer

    client = create_client()
    agents = list(DEMO_AGENTS)
    attach_tools(agents)
    tracer = Tracer(session_id="llm-smoke")
    ctx = RunContext(
        agents=agents, client=client,
        divider=TaskDivider(system_prompt="Decompose only if the task bundles several capabilities; else mark atomic."),
        aggregator=TaskAggregator(system_prompt="Merge sub-results into one coherent answer."),
        tagger=Tagger(system_prompt="Tag the task with required capabilities; at least one."),
        tracer=tracer,
    )

    result = run_recovery(
        "Build a small REST API with a Python backend, a database layer, and a test suite.",
        ctx,
    )
    assert isinstance(result, Output)
    assert any(isinstance(e, TaskDividedEvent) for e in tracer.events), "expected at least one division"
