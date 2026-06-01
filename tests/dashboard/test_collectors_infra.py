from dashboard.collectors.infra import collect


def test_infra_counts(runs_root):
    stats = collect(runs_root)
    assert stats.session_count == 1
    assert stats.task_count == 2
    assert stats.run_count == 1            # un seul ExecutedEvent (t0)
    assert stats.agent_count == 4
    assert stats.qa_pass_rate == 1.0       # 1 QA event, success
    assert stats.total_tokens_in == 120
    assert stats.total_tokens_out == 80
    assert stats.latency.count == 1
    assert stats.latency.mean_ms == 350.0
    assert len(stats.pass_rate_over_time) == 1


def test_infra_empty(tmp_path):
    stats = collect(tmp_path)
    assert stats.session_count == 0
    assert stats.qa_pass_rate is None
    assert stats.latency.mean_ms is None
    assert stats.pass_rate_over_time == []


def test_infra_per_session(runs_root):
    stats = collect(runs_root)
    assert len(stats.per_session) == 1
    p = stats.per_session[0]
    assert p.run_count == 1
    assert p.tokens_in == 120
    assert p.tokens_out == 80
    assert p.latency_mean == 350.0


def test_infra_per_session_empty(tmp_path):
    assert collect(tmp_path).per_session == []
