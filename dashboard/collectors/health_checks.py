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
