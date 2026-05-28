from aaosa.qa.health_check import HealthCheckReport
from aaosa.qa.test_set import TestCase, TestSet


def graduate(
    test_set: TestSet,
    report: HealthCheckReport,
    graduation_threshold: float = 0.8,
) -> TestSet:
    """Promote fix_target cases to regression_guard if pass_rate >= threshold.

    Args:
        test_set: Current test set
        report: Health check report with case results
        graduation_threshold: Pass rate threshold for promotion (default 0.8)

    Returns:
        New TestSet with promoted cases (does not mutate input)
    """
    # Build lookup of pass_rate and unstable status by task_id
    case_info_by_task = {c.task_id: (c.pass_rate, c.unstable) for c in report.case_results}

    new_cases: list[TestCase] = []
    for case in test_set.cases:
        pass_rate, is_unstable = case_info_by_task.get(case.task.id, (0.0, False))
        if (
            case.role == "fix_target"
            and not is_unstable
            and pass_rate >= graduation_threshold
        ):
            new_cases.append(case.model_copy(update={"role": "regression_guard"}))
        else:
            new_cases.append(case)

    return TestSet(cases=new_cases)
