"""Tests des tools incident — fonctions pures sur le monde, jamais d'exception."""

from aaosa.demo.incident.tools import (
    get_incident_report,
    inspect_schema,
    query_logs,
)


class TestQueryLogs:
    def test_filters_by_ip(self):
        result = query_logs("185.220.101.34")
        assert "42 matching entries" in result
        assert "/api/v2/customers/export" in result

    def test_no_match_is_graceful(self):
        result = query_logs("no-such-thing-xyz")
        assert result == "no entries match 'no-such-thing-xyz'"

    def test_output_capped_at_50_lines(self):
        result = query_logs("GET")  # matche des centaines d'entrées
        lines = result.splitlines()
        assert len(lines) <= 51  # 1 ligne d'en-tête + 50 entrées max
        assert "showing first 50" in lines[0]

    def test_filter_matches_any_field(self):
        # token_sub du compte service compromis
        result = query_logs("svc-reporting")
        assert "42 matching entries" in result


class TestInspectSchema:
    def test_known_table_returns_ddl(self):
        result = inspect_schema("customers")
        assert "CREATE TABLE customers" in result
        assert "email" in result

    def test_unknown_table_lists_tables(self):
        result = inspect_schema("nope")
        assert "customers" in result and "api_tokens" in result
        assert "fastjwt 2.3.1" in result  # l'en-tête stack est exposé

    def test_star_lists_tables(self):
        result = inspect_schema("*")
        assert "customers" in result and "users" in result


class TestGetIncidentReport:
    def test_report_mentions_endpoint_and_window(self):
        report = get_incident_report()
        assert "/api/v2/customers/export" in report
        assert "2026-06-06" in report
