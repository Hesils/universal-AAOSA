"""Tests des loaders du monde simulé — parse, cache, cohérence du monde."""

from aaosa.demo.incident.world import (
    load_access_logs,
    load_customers,
    load_cve_bulletins,
    load_db_schema,
    load_docs,
)


class TestLoaders:
    def test_access_logs_parse(self):
        logs = load_access_logs()
        assert isinstance(logs, list) and len(logs) > 300
        required = {"ts", "ip", "method", "path", "status", "user_agent", "token_sub", "bytes"}
        assert all(required <= set(e) for e in logs)

    def test_access_logs_cached(self):
        assert load_access_logs() is load_access_logs()

    def test_db_schema_is_text(self):
        schema = load_db_schema()
        assert "CREATE TABLE customers" in schema

    def test_customers_metadata(self):
        customers = load_customers()
        assert customers["total"] == 4217
        assert "email" in customers["pii_fields"]
        assert len(customers["sample"]) > 0

    def test_cve_bulletins(self):
        bulletins = load_cve_bulletins()
        assert len(bulletins) == 3
        assert {b["id"] for b in bulletins} >= {"CVE-2026-21804"}

    def test_docs_corpus(self):
        docs = load_docs()
        assert len(docs) == 5
        assert all(content.strip() for content in docs.values())
        assert "rgpd-art33-notification-cnil.md" in docs


class TestWorldCoherence:
    """La fuite doit être trouvable en croisant les sources — invariants du monde."""

    def test_attacker_has_42_export_requests(self):
        exports = [
            e for e in load_access_logs()
            if e["ip"] == "185.220.101.34" and "/api/v2/customers/export" in e["path"]
        ]
        assert len(exports) == 42
        assert all(e["status"] == 200 for e in exports)

    def test_export_pages_cover_1_to_42(self):
        exports = [e for e in load_access_logs() if "/api/v2/customers/export" in e["path"]]
        pages = {int(e["path"].split("page=")[1].split("&")[0]) for e in exports}
        assert pages == set(range(1, 43))

    def test_exfiltrated_volume_fits_customer_base(self):
        assert 42 * 100 <= load_customers()["total"]

    def test_relevant_cve_matches_stack(self):
        schema = load_db_schema()
        relevant = [b for b in load_cve_bulletins() if b["package"] == "fastjwt"]
        assert len(relevant) == 1
        assert relevant[0]["id"] == "CVE-2026-21804"
        assert "fastjwt 2.3.1" in schema
