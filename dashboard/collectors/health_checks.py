from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from aaosa.qa.health_check import HealthCheckReport
from aaosa.qa.spec import EvaluatorSpec
from aaosa.qa.test_set import TestSet
from aaosa.tracing.store import SessionMeta, SessionTaskRecord, load_trace
from dashboard.graph_model import GraphModel, build_graph


class HealthCheckListItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    timestamp: datetime
    n_runs: int
    total_cases: int
    fix_target_pass_rate: float
    regression_guard_pass_rate: float
    unstable_count: int
    quarantined_count: int


class HealthCheckList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runs: list[HealthCheckListItem]


class CaseMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pass_rate: float
    pass_count: int
    n_runs: int
    unstable: bool


class HealthCheckCaseView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str
    description: str
    required_tags: dict[str, int]
    role: str
    attribution: str
    origin: str
    reference: str | None
    evaluator_spec: EvaluatorSpec
    graphable: bool
    result: CaseMetrics | None


class HealthCheckView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    timestamp: datetime
    n_runs: int
    total_cases: int
    fix_target_pass_rate: float
    regression_guard_pass_rate: float
    unstable_cases: list[str]
    task_spec_quarantined: list[str]
    evaluator_quarantined: list[str]
    unattributed: list[str]
    cases: list[HealthCheckCaseView]


def _hc_dir(runs_root: Path) -> Path:
    return runs_root / "health_checks"


def _load_report(run_dir: Path) -> HealthCheckReport:
    return HealthCheckReport.model_validate_json((run_dir / "report.json").read_text(encoding="utf-8"))


def list_runs(runs_root: Path) -> HealthCheckList:
    hdir = _hc_dir(runs_root)
    items: list[HealthCheckListItem] = []
    if hdir.exists():
        for d in sorted(hdir.iterdir()):
            if not (d / "report.json").exists():
                continue
            r = _load_report(d)
            quarantined = len(r.task_spec_quarantined) + len(r.evaluator_quarantined) + len(r.unattributed)
            items.append(HealthCheckListItem(
                id=d.name,
                timestamp=r.timestamp,
                n_runs=r.n_runs,
                total_cases=r.total_cases,
                fix_target_pass_rate=r.fix_target_pass_rate,
                regression_guard_pass_rate=r.regression_guard_pass_rate,
                unstable_count=len(r.unstable_cases),
                quarantined_count=quarantined,
            ))
    items.sort(key=lambda x: x.timestamp, reverse=True)
    return HealthCheckList(runs=items)


def _load_test_set(run_dir: Path) -> TestSet:
    return TestSet.model_validate_json((run_dir / "test_set.json").read_text(encoding="utf-8"))


def run_detail(runs_root: Path, run_id: str) -> HealthCheckView | None:
    d = _hc_dir(runs_root) / run_id
    if not (d / "report.json").exists() or not (d / "test_set.json").exists():
        return None
    report = _load_report(d)
    test_set = _load_test_set(d)
    by_task = {cr.task_id: cr for cr in report.case_results}
    cases: list[HealthCheckCaseView] = []
    for c in test_set.cases:
        cr = by_task.get(c.task.id)
        cases.append(HealthCheckCaseView(
            task_id=c.task.id,
            description=c.task.description,
            required_tags=c.task.required_tags,
            role=c.role,
            attribution=c.attribution,
            origin=c.origin,
            reference=c.reference,
            evaluator_spec=c.evaluator_spec,
            graphable=cr is not None,
            result=CaseMetrics(
                pass_rate=cr.pass_rate,
                pass_count=cr.pass_count,
                n_runs=cr.n_runs,
                unstable=cr.unstable,
            ) if cr is not None else None,
        ))
    return HealthCheckView(
        id=run_id,
        timestamp=report.timestamp,
        n_runs=report.n_runs,
        total_cases=report.total_cases,
        fix_target_pass_rate=report.fix_target_pass_rate,
        regression_guard_pass_rate=report.regression_guard_pass_rate,
        unstable_cases=report.unstable_cases,
        task_spec_quarantined=report.task_spec_quarantined,
        evaluator_quarantined=report.evaluator_quarantined,
        unattributed=report.unattributed,
        cases=cases,
    )


def _synth_meta(test_set: TestSet, report: HealthCheckReport, run_id: str) -> SessionMeta:
    """Synthétise un SessionMeta depuis le TestSet pour nourrir build_graph.

    winner_agent_id/outcome sont des placeholders ignorés par build_graph
    (il dérive winner/outcome des events) ; seuls description/required_tags servent.
    """
    return SessionMeta(
        session_id=run_id,
        started_at=report.timestamp,
        ended_at=report.timestamp,
        tasks=[
            SessionTaskRecord(
                id=c.task.id,
                description=c.task.description,
                required_tags=c.task.required_tags,
                winner_agent_id=None,
                outcome="no_qa",
            )
            for c in test_set.cases
        ],
        agent_ids=[],
    )


def case_graph(runs_root: Path, run_id: str, task_id: str) -> GraphModel | None:
    d = _hc_dir(runs_root) / run_id
    if not all((d / f).exists() for f in ("report.json", "test_set.json", "trace.jsonl")):
        return None
    report = _load_report(d)
    test_set = _load_test_set(d)
    events = [e for e in load_trace(d / "trace.jsonl") if e.task_id == task_id]
    if not events:
        return None  # cas non graphable (quarantaine ou absent de la trace)
    return build_graph(events, _synth_meta(test_set, report, run_id))
