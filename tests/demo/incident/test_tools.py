"""Tests des tools incident — fonctions pures sur le monde, jamais d'exception."""

from aaosa.core.tool import ToolDef
from aaosa.demo.incident.tools import (
    TOOLBOX,
    count_affected_users,
    doc_search,
    get_incident_report,
    inspect_schema,
    lookup_cve,
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


class TestLookupCve:
    def test_finds_fastjwt_cve(self):
        result = lookup_cve("fastjwt")
        assert "CVE-2026-21804" in result
        assert "authentication bypass" in result

    def test_finds_by_id(self):
        assert "fastjwt" in lookup_cve("CVE-2026-21804")

    def test_no_match_is_graceful(self):
        assert lookup_cve("left-pad") == "no CVE bulletin matches 'left-pad'"


class TestCountAffectedUsers:
    def test_counts_from_export_requests(self):
        result = count_affected_users("export requests last night")
        assert "4200" in result
        assert "4217" in result
        assert "email" in result and "address" in result

    def test_mentions_page_range(self):
        result = count_affected_users("scope")
        assert "pages 1-42" in result


class TestDocSearch:
    def test_cnil_query_finds_art33(self):
        result = doc_search("notification CNIL 72 heures")
        # la fiche art. 33 doit être le premier document remonté
        first_doc = result.split("---")[1]
        assert "rgpd-art33-notification-cnil.md" in first_doc

    def test_information_personnes_finds_art34(self):
        result = doc_search("information des personnes concernées risque élevé")
        assert "rgpd-art34-information-personnes.md" in result

    def test_no_match_is_graceful(self):
        assert doc_search("zzzqqqxxx") == "no documents match 'zzzqqqxxx'"

    def test_returns_at_most_two_documents(self):
        result = doc_search("notification violation données personnelles")
        assert result.count("--- ") <= 2


class TestToolbox:
    def test_six_tools_registered(self):
        expected = {
            "query_logs", "inspect_schema", "count_affected_users",
            "lookup_cve", "doc_search", "get_incident_report",
        }
        assert set(TOOLBOX) == expected

    def test_all_tooldefs_with_matching_names(self):
        for name, tool in TOOLBOX.items():
            assert isinstance(tool, ToolDef)
            assert tool.name == name
