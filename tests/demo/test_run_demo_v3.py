from aaosa.demo.run_demo_v3 import build_incident_task, run_demo_v3
from aaosa.schemas.task import Task


def test_build_incident_task_has_context_and_tags():
    task = build_incident_task()
    assert isinstance(task, Task)
    assert task.context
    assert task.required_tags  # non vide


def test_run_demo_v3_is_callable():
    assert callable(run_demo_v3)
