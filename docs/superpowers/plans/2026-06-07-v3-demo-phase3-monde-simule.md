# V3 — Démo phase 3 : monde simulé + roster incident — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construire `src/aaosa/demo/incident/` — monde simulé fuite de données (fichiers data versionnés), 6 tools purs, roster 7 agents / 3 domaines, scénarios main + roster_gap, script de validation jetable.

**Architecture:** Le monde est un ensemble de fichiers data sous `world/` chargés par des loaders purs `lru_cache` (`world.py`). Les tools (`tools.py`) sont des fonctions pures sur le monde, exposées dans `TOOLBOX: dict[str, ToolDef]` au niveau module — même pattern que `demo/tools.py` (phase 2). Le roster se déclare dans `agents.yaml` (tools résolus par `load_agents(…, tool_registry=TOOLBOX)`). Les scénarios sont des données pures. La démo logicielle existante (`demo/agents.yaml`, `demo/tools.py`, `run_demo_v3.py`, `run_health_check_v3.py`) ne bouge pas.

**Tech Stack:** Python 3.14, Pydantic 2.13, pytest 9 (venv : `.venv\Scripts\python`), pattern `ToolDef`/`load_agents` existants. Spec : `docs/superpowers/specs/2026-06-07-v3-demo-phase3-monde-simule-design.md`.

**Conventions repo :** imports absolus uniquement · tests miroir sous `tests/demo/incident/` · commits fréquents préfixés `feat(demo-p3):` / `test(demo-p3):` · ne JAMAIS toucher `src/aaosa/` hors `demo/`.

**Cohérence du monde (invariants, à ne pas casser en éditant les data) :**
- L'IP attaquante `185.220.101.34` a exactement **42** requêtes `GET /api/v2/customers/export?page=N&size=100` (pages 1→42), nuit du 2026-06-06, 02:10→03:40 UTC.
- `customers.json` porte `total: 4217` → 42 × 100 = **4200** clients affectés (< 4217).
- La CVE pertinente est **CVE-2026-21804** sur `fastjwt` ; l'en-tête de `db_schema.sql` mentionne `fastjwt 2.3.1`. Les 2 autres bulletins concernent des libs absentes de la stack.
- Le corpus `world/docs/` contient 5 documents markdown, dont la fiche art. 33 (notification CNIL 72h) que `doc_search("notification CNIL")` doit remonter en premier.

---

### Task 1: Fichiers data du monde (`world/`)

Pas de TDD ici (données pures, pas de code) — les tests de cohérence arrivent en Task 2 avec les loaders.

**Files:**
- Create: `src/aaosa/demo/incident/__init__.py`
- Create: `src/aaosa/demo/incident/world/db_schema.sql`
- Create: `src/aaosa/demo/incident/world/customers.json`
- Create: `src/aaosa/demo/incident/world/cve_bulletins.json`
- Create: `src/aaosa/demo/incident/world/docs/incident-response-procedure.md`
- Create: `src/aaosa/demo/incident/world/docs/rgpd-art33-notification-cnil.md`
- Create: `src/aaosa/demo/incident/world/docs/rgpd-art34-information-personnes.md`
- Create: `src/aaosa/demo/incident/world/docs/registre-traitements.md`
- Create: `src/aaosa/demo/incident/world/docs/modele-notification-cnil.md`
- Create: `src/aaosa/demo/incident/world/access_logs.jsonl` (généré, puis versionné)

- [ ] **Step 1: Créer le package et `db_schema.sql`**

`src/aaosa/demo/incident/__init__.py` : fichier vide.

`src/aaosa/demo/incident/world/db_schema.sql` :

```sql
-- SaaS customer-management API - PostgreSQL 16
-- App stack: python 3.12 / fastapi 0.115 / fastjwt 2.3.1 / sqlalchemy 2.0
-- Dependency versions pinned in requirements.txt, mirrored here for ops.

CREATE TABLE customers (
    id            BIGSERIAL PRIMARY KEY,
    email         TEXT NOT NULL UNIQUE,
    full_name     TEXT NOT NULL,
    phone         TEXT,
    address       TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE users (
    id            BIGSERIAL PRIMARY KEY,
    username      TEXT NOT NULL UNIQUE,
    kind          TEXT NOT NULL CHECK (kind IN ('staff', 'service')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE api_tokens (
    id            BIGSERIAL PRIMARY KEY,
    user_id       BIGINT NOT NULL REFERENCES users(id),
    token_hash    TEXT NOT NULL,
    scopes        TEXT NOT NULL,
    expires_at    TIMESTAMPTZ
);

CREATE TABLE audit_log (
    id            BIGSERIAL PRIMARY KEY,
    user_id       BIGINT REFERENCES users(id),
    action        TEXT NOT NULL,
    target        TEXT,
    at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

- [ ] **Step 2: Créer `customers.json`**

```json
{
  "table": "customers",
  "total": 4217,
  "pii_fields": ["email", "full_name", "phone", "address"],
  "non_pii_fields": ["id", "created_at"],
  "note": "Sample of fictitious rows; the table holds 4217 records in total.",
  "sample": [
    {"id": 1, "email": "a.martin@example.com", "full_name": "Alice Martin", "phone": "+33 6 12 34 56 01", "address": "12 rue des Lilas, 69003 Lyon", "created_at": "2024-03-11T09:14:00Z"},
    {"id": 2, "email": "b.nguyen@example.com", "full_name": "Binh Nguyen", "phone": "+33 6 12 34 56 02", "address": "8 avenue Foch, 75116 Paris", "created_at": "2024-05-02T16:40:00Z"},
    {"id": 3, "email": "c.dubois@example.com", "full_name": "Camille Dubois", "phone": "+33 6 12 34 56 03", "address": "3 place Bellecour, 69002 Lyon", "created_at": "2024-07-19T11:05:00Z"},
    {"id": 4, "email": "d.silva@example.com", "full_name": "Diego Silva", "phone": "+33 6 12 34 56 04", "address": "27 quai de la Fosse, 44000 Nantes", "created_at": "2024-09-30T08:22:00Z"},
    {"id": 5, "email": "e.kaya@example.com", "full_name": "Elif Kaya", "phone": "+33 6 12 34 56 05", "address": "5 rue Nationale, 59000 Lille", "created_at": "2025-01-12T14:55:00Z"},
    {"id": 6, "email": "f.bernard@example.com", "full_name": "Fanny Bernard", "phone": "+33 6 12 34 56 06", "address": "41 cours Mirabeau, 13100 Aix-en-Provence", "created_at": "2025-04-26T10:31:00Z"}
  ]
}
```

- [ ] **Step 3: Créer `cve_bulletins.json`**

3 bulletins : le premier est pertinent (fastjwt, présent dans la stack), les deux autres sont du bruit (libs absentes).

```json
[
  {
    "id": "CVE-2026-21804",
    "package": "fastjwt",
    "affected_versions": ">=2.0.0, <2.4.0",
    "severity": "critical",
    "cvss": 9.1,
    "title": "fastjwt: authentication bypass via unverified service-token claims",
    "description": "fastjwt versions 2.0.0 through 2.3.x fail to re-verify the signature of service-account tokens when the 'svc' claim is present, allowing an attacker who obtains an expired or leaked service token to forge valid credentials and call any endpoint the service account is scoped for. Exploited in the wild since 2026-05-28. Fixed in 2.4.0.",
    "published": "2026-05-30"
  },
  {
    "id": "CVE-2026-11532",
    "package": "django-storages",
    "affected_versions": "<1.14.6",
    "severity": "high",
    "cvss": 7.5,
    "title": "django-storages: path traversal in S3 key normalization",
    "description": "Improper normalization of object keys allows reading files outside the configured bucket prefix when user-controlled filenames are used.",
    "published": "2026-04-17"
  },
  {
    "id": "CVE-2025-48891",
    "package": "redis-py",
    "affected_versions": "<5.2.2",
    "severity": "medium",
    "cvss": 5.3,
    "title": "redis-py: denial of service via unbounded RESP3 push buffer",
    "description": "A malicious Redis server can exhaust client memory through unbounded push message buffering.",
    "published": "2025-12-02"
  }
]
```

- [ ] **Step 4: Créer le corpus juriste (`world/docs/`, 5 fichiers)**

`incident-response-procedure.md` :

```markdown
# Procédure interne de réponse aux incidents de sécurité

## Déclenchement

Tout incident suspecté de toucher des données personnelles est qualifié dans
les 4 heures par l'équipe sécurité, avec information immédiate du DPO.

## Rôles

- Équipe ingénierie : investigation technique, containment, remédiation.
- DPO : qualification juridique de la violation, notification CNIL le cas échéant.
- Communication : information des clients, coordination avec le DPO.
- Support : prise en charge des demandes entrantes après communication.

## Étapes

1. Containment immédiat (révocation des accès compromis, blocage des sources).
2. Investigation : périmètre exact des données touchées, nombre de personnes concernées.
3. Qualification DPO : violation de données personnelles au sens du RGPD ou non.
4. Notification CNIL si requise (voir fiche art. 33) et information des personnes (fiche art. 34).
5. Post-mortem sous 15 jours.
```

`rgpd-art33-notification-cnil.md` :

```markdown
# Fiche pratique - Article 33 RGPD : notification d'une violation à la CNIL

## Principe

En cas de violation de données à caractère personnel, le responsable de
traitement notifie la violation à la CNIL dans les meilleurs délais et, si
possible, **72 heures au plus tard après en avoir pris connaissance**, à
moins que la violation ne soit pas susceptible d'engendrer un risque pour
les droits et libertés des personnes physiques.

## Point de départ du délai

Le délai de 72 heures court à partir du moment où l'entreprise a une
certitude raisonnable qu'une violation s'est produite — typiquement la
confirmation par l'investigation technique d'un accès non autorisé à des
données personnelles.

## Contenu de la notification

- Nature de la violation, catégories et nombre approximatif de personnes concernées.
- Catégories et volume approximatif d'enregistrements concernés.
- Conséquences probables de la violation.
- Mesures prises ou envisagées (remédiation, atténuation).
- Coordonnées du DPO.

## Notification tardive

Au-delà de 72 heures, la notification doit être accompagnée des motifs du retard.
```

`rgpd-art34-information-personnes.md` :

```markdown
# Fiche pratique - Article 34 RGPD : information des personnes concernées

## Principe

Lorsqu'une violation de données personnelles est susceptible d'engendrer un
**risque élevé** pour les droits et libertés d'une personne physique, le
responsable du traitement communique la violation à la personne concernée
dans les meilleurs délais.

## Critères du risque élevé

- Nature des données : identifiants de connexion, données financières,
  données sensibles → risque élevé probable.
- Données de contact (email, nom, téléphone, adresse postale) exposées en
  volume : risque de phishing ciblé et d'usurpation d'identité — l'analyse
  au cas par cas penche généralement vers l'information des personnes.

## Contenu de la communication

En des termes clairs et simples : nature de la violation, coordonnées du DPO,
conséquences probables, mesures prises. Pas de jargon juridique.

## Exceptions

L'information individuelle n'est pas requise si des mesures de protection
appropriées (ex. chiffrement) rendaient les données incompréhensibles, ou si
elle exigerait des efforts disproportionnés (communication publique alors admise).
```

`registre-traitements.md` :

```markdown
# Registre des traitements (extrait) - Gestion clients

## Traitement : gestion de la relation clients

- Responsable : la société, représentée par la direction générale.
- Finalités : gestion des comptes clients, facturation, support.
- Catégories de données : identité (nom), coordonnées (email, téléphone,
  adresse postale), historique de commandes.
- Catégories de personnes : clients actifs et anciens clients (< 3 ans).
- Destinataires : équipes internes (support, facturation) ; aucun transfert
  hors UE.
- Durée de conservation : 3 ans après la fin de la relation contractuelle.
- Mesures de sécurité : authentification par token, journalisation des accès,
  chiffrement en transit.
```

`modele-notification-cnil.md` :

```markdown
# Modèle interne - notification de violation à la CNIL

À adapter avant tout envoi ; à valider par le DPO.

## 1. Identification

- Responsable de traitement : [raison sociale, SIREN]
- DPO : [nom, email, téléphone]
- Date et heure de prise de connaissance de la violation : [date/heure UTC]

## 2. Nature de la violation

- Type : [accès non autorisé / exfiltration / perte / altération]
- Description factuelle : [vecteur, période, systèmes touchés]

## 3. Périmètre

- Catégories de personnes concernées : [clients, prospects...]
- Nombre approximatif de personnes : [N]
- Catégories de données : [email, nom, téléphone, adresse...]
- Volume approximatif d'enregistrements : [N]

## 4. Conséquences probables

[Risques pour les personnes : phishing, usurpation...]

## 5. Mesures

- Mesures de remédiation déjà prises : [révocation, patch, blocage...]
- Mesures d'atténuation pour les personnes : [information, recommandations...]
```

- [ ] **Step 5: Générer `access_logs.jsonl` (script temporaire, exécuté puis supprimé)**

Créer `tmp_gen_logs.py` **à la racine du repo** :

```python
"""Génère world/access_logs.jsonl — déterministe (Random(42)). Exécuté une fois puis supprimé."""
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

rng = random.Random(42)
out = []

BASE = datetime(2026, 6, 5, 0, 0, 0, tzinfo=timezone.utc)
SPAN_H = 48

NORMAL_IPS = [f"203.0.113.{i}" for i in range(2, 27)]
SCANNER_IPS = ["198.51.100.7", "198.51.100.23", "198.51.100.99"]
BROWSER_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
MOBILE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15"
SCANNER_UA = "zgrab/0.x"


def entry(ts, ip, method, path, status, ua, sub, nbytes):
    return {
        "ts": ts.strftime("%Y-%m-%dT%H:%M:%SZ"), "ip": ip, "method": method,
        "path": path, "status": status, "user_agent": ua, "token_sub": sub,
        "bytes": nbytes,
    }


# ~300 entrées de bruit réaliste sur 48 h
for _ in range(300):
    ts = BASE + timedelta(seconds=rng.randint(0, SPAN_H * 3600 - 1))
    kind = rng.random()
    ip = rng.choice(NORMAL_IPS)
    ua = rng.choice([BROWSER_UA, MOBILE_UA])
    if kind < 0.35:
        out.append(entry(ts, ip, "POST", "/api/v1/checkout",
                         500 if rng.random() < 0.02 else 200, ua,
                         f"user-{rng.randint(1000, 9999)}", rng.randint(900, 4200)))
    elif kind < 0.55:
        out.append(entry(ts, ip, "POST", "/api/v1/login",
                         401 if rng.random() < 0.1 else 200, ua,
                         f"user-{rng.randint(1000, 9999)}", rng.randint(300, 800)))
    elif kind < 0.75:
        out.append(entry(ts, ip, "GET", f"/api/v1/orders/{rng.randint(10000, 99999)}",
                         200, ua, f"user-{rng.randint(1000, 9999)}", rng.randint(700, 2600)))
    elif kind < 0.88:
        out.append(entry(ts, ip, "GET", f"/api/v2/customers/{rng.randint(1, 4217)}",
                         200, ua, f"staff-{rng.randint(10, 49)}", rng.randint(600, 1400)))
    elif kind < 0.95:
        out.append(entry(ts, ip, "GET", "/health", 200, "kube-probe/1.29", None, 120))
    else:
        out.append(entry(ts, rng.choice(SCANNER_IPS), "GET",
                         rng.choice(["/wp-admin", "/.env", "/admin/config.php"]),
                         404, SCANNER_UA, None, 240))

# 42 requêtes d'exfiltration — nuit du 2026-06-06, 02:10 -> 03:40 UTC, pages 1..42
EXFIL_START = datetime(2026, 6, 6, 2, 10, 0, tzinfo=timezone.utc)
for page in range(1, 43):
    ts = EXFIL_START + timedelta(seconds=(page - 1) * 128 + rng.randint(0, 20))
    out.append(entry(ts, "185.220.101.34", "GET",
                     f"/api/v2/customers/export?page={page}&size=100",
                     200, "python-requests/2.32", "svc-reporting",
                     rng.randint(88000, 99000)))

out.sort(key=lambda e: e["ts"])
dest = Path("src/aaosa/demo/incident/world/access_logs.jsonl")
dest.write_text("\n".join(json.dumps(e) for e in out) + "\n", encoding="utf-8")
print(f"{len(out)} entries -> {dest}")
```

Exécuter puis supprimer :

```powershell
.venv\Scripts\python tmp_gen_logs.py
Remove-Item tmp_gen_logs.py
```

Expected: `342 entries -> src\aaosa\demo\incident\world\access_logs.jsonl`

- [ ] **Step 6: Vérification rapide des invariants à la main**

```powershell
.venv\Scripts\python -c "import json; from pathlib import Path; logs=[json.loads(l) for l in Path('src/aaosa/demo/incident/world/access_logs.jsonl').read_text(encoding='utf-8').splitlines()]; ex=[e for e in logs if e['ip']=='185.220.101.34']; print(len(logs), len(ex), len({e['path'] for e in ex}))"
```

Expected: `342 42 42` (342 entrées, 42 exfil, 42 paths distincts).

- [ ] **Step 7: Commit**

```powershell
git add src/aaosa/demo/incident/
git commit -m "feat(demo-p3): monde simule incident - fichiers data world/"
```

---

### Task 2: Loaders du monde (`world.py`) — TDD

**Files:**
- Create: `src/aaosa/demo/incident/world.py`
- Create: `tests/demo/incident/__init__.py`
- Test: `tests/demo/incident/test_world.py`

- [ ] **Step 1: Écrire les tests qui échouent**

`tests/demo/incident/__init__.py` : vide.

`tests/demo/incident/test_world.py` :

```python
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
```

- [ ] **Step 2: Vérifier que les tests échouent**

```powershell
.venv\Scripts\python -m pytest tests/demo/incident/test_world.py -v
```

Expected: échec à l'import — `ModuleNotFoundError: No module named 'aaosa.demo.incident.world'`.

- [ ] **Step 3: Implémenter `world.py`**

```python
"""Loaders purs du monde simulé incident (lecture seule, lru_cache).

Le monde est immuable : les consommateurs ne mutent jamais les structures
retournées (elles sont partagées via le cache).
"""

import json
from functools import lru_cache
from pathlib import Path

_WORLD = Path(__file__).parent / "world"


@lru_cache(maxsize=1)
def load_access_logs() -> list[dict]:
    lines = (_WORLD / "access_logs.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines if line.strip()]


@lru_cache(maxsize=1)
def load_db_schema() -> str:
    return (_WORLD / "db_schema.sql").read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def load_customers() -> dict:
    return json.loads((_WORLD / "customers.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_cve_bulletins() -> list[dict]:
    return json.loads((_WORLD / "cve_bulletins.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_docs() -> dict[str, str]:
    return {
        p.name: p.read_text(encoding="utf-8")
        for p in sorted((_WORLD / "docs").glob("*.md"))
    }
```

- [ ] **Step 4: Vérifier que les tests passent**

```powershell
.venv\Scripts\python -m pytest tests/demo/incident/test_world.py -v
```

Expected: 10 passed.

- [ ] **Step 5: Commit**

```powershell
git add src/aaosa/demo/incident/world.py tests/demo/incident/
git commit -m "feat(demo-p3): loaders world.py (lru_cache) + tests coherence du monde"
```

---

### Task 3: Tools d'investigation — `query_logs`, `inspect_schema`, `get_incident_report` (TDD)

**Files:**
- Create: `src/aaosa/demo/incident/tools.py`
- Test: `tests/demo/incident/test_tools.py`

- [ ] **Step 1: Écrire les tests qui échouent**

`tests/demo/incident/test_tools.py` :

```python
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
```

- [ ] **Step 2: Vérifier que les tests échouent**

```powershell
.venv\Scripts\python -m pytest tests/demo/incident/test_tools.py -v
```

Expected: `ModuleNotFoundError: No module named 'aaosa.demo.incident.tools'`.

- [ ] **Step 3: Implémenter les 3 premiers tools**

`src/aaosa/demo/incident/tools.py` :

```python
"""Tools de la démo incident — fonctions pures sur le monde simulé.

Contrat : retour str, jamais d'exception (une entrée non matchée retourne un
message explicite — un tool qui lève casserait la boucle tool-use pour rien).
TOOLBOX sert de tool_registry à load_agents (pattern phase 2).
"""

import json
import re

from aaosa.core.tool import ToolDef
from aaosa.demo.incident.world import (
    load_access_logs,
    load_customers,
    load_cve_bulletins,
    load_db_schema,
    load_docs,
)

_MAX_LOG_LINES = 50

_INCIDENT_REPORT = """\
INCIDENT TICKET #2026-0606-01 - opened 2026-06-06 06:30 UTC by monitoring
Severity: to be assessed

Anomalous traffic detected on the customer-management API during the night
of 2026-06-05 to 2026-06-06: unusual volume of requests on
/api/v2/customers/export between roughly 02:00 and 04:00 UTC, originating
from outside our usual office/VPN ranges. This endpoint normally serves a
handful of requests per week from the internal reporting job.

Open questions: was data actually exfiltrated, by whom and how, how many
customers and which fields are affected, what are our regulatory
obligations, and what do we tell affected customers?

Access logs, DB schema and the internal document base are available
through your tools.
"""


def query_logs(filter: str) -> str:
    needle = filter.lower()
    matches = [
        e for e in load_access_logs()
        if any(needle in str(v).lower() for v in e.values())
    ]
    if not matches:
        return f"no entries match {filter!r}"
    shown = matches[:_MAX_LOG_LINES]
    header = f"{len(matches)} matching entries (showing first {len(shown)}):"
    return "\n".join([header, *(json.dumps(e) for e in shown)])


_TABLE_RE = re.compile(r"CREATE TABLE (\w+) \([^;]*?\);", re.DOTALL)


def inspect_schema(table: str) -> str:
    schema = load_db_schema()
    tables = {m.group(1): m.group(0) for m in _TABLE_RE.finditer(schema)}
    if table in tables:
        return tables[table]
    header = "\n".join(line for line in schema.splitlines() if line.startswith("--"))
    return f"{header}\nTables: {', '.join(sorted(tables))}"


def get_incident_report() -> str:
    return _INCIDENT_REPORT
```

- [ ] **Step 4: Vérifier que les tests passent**

```powershell
.venv\Scripts\python -m pytest tests/demo/incident/test_tools.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```powershell
git add src/aaosa/demo/incident/tools.py tests/demo/incident/test_tools.py
git commit -m "feat(demo-p3): tools investigation - query_logs, inspect_schema, get_incident_report"
```

---

### Task 4: Tools d'analyse — `lookup_cve`, `count_affected_users`, `doc_search` + `TOOLBOX` (TDD)

**Files:**
- Modify: `src/aaosa/demo/incident/tools.py` (ajout en fin de fichier)
- Test: `tests/demo/incident/test_tools.py` (ajout des classes)

- [ ] **Step 1: Ajouter les tests qui échouent**

Ajouter à `tests/demo/incident/test_tools.py` (imports à compléter en tête de fichier : `count_affected_users`, `doc_search`, `lookup_cve`, `TOOLBOX`, et `from aaosa.core.tool import ToolDef`) :

```python
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
```

- [ ] **Step 2: Vérifier que les nouveaux tests échouent**

```powershell
.venv\Scripts\python -m pytest tests/demo/incident/test_tools.py -v
```

Expected: `ImportError: cannot import name 'lookup_cve'`.

- [ ] **Step 3: Implémenter les 3 tools restants + TOOLBOX**

Ajouter à `src/aaosa/demo/incident/tools.py` (après `get_incident_report` ; ajouter `from urllib.parse import parse_qs, urlparse` aux imports) :

```python
def lookup_cve(query: str) -> str:
    needle = query.lower()
    matches = [
        b for b in load_cve_bulletins()
        if any(needle in str(v).lower() for v in b.values())
    ]
    if not matches:
        return f"no CVE bulletin matches {query!r}"
    return "\n\n".join(json.dumps(b, indent=2) for b in matches)


def count_affected_users(criteria: str) -> str:
    exports = [
        e for e in load_access_logs()
        if "/api/v2/customers/export" in e["path"]
    ]
    if not exports:
        return "no export requests found in access logs"
    pages: set[int] = set()
    size = 0
    for e in exports:
        params = parse_qs(urlparse(e["path"]).query)
        pages.add(int(params.get("page", ["0"])[0]))
        size = max(size, int(params.get("size", ["0"])[0]))
    customers = load_customers()
    affected = min(len(pages) * size, customers["total"])
    return (
        f"Criteria: {criteria}\n"
        f"Export requests found: {len(exports)} (pages {min(pages)}-{max(pages)}, size {size})\n"
        f"Estimated affected customers: {affected} of {customers['total']} total\n"
        f"Exposed PII fields: {', '.join(customers['pii_fields'])}"
    )


def doc_search(query: str) -> str:
    terms = [t for t in re.findall(r"\w+", query.lower()) if len(t) > 2]
    if not terms:
        return f"no usable search terms in {query!r}"
    scored = []
    for name, content in load_docs().items():
        lower = content.lower()
        title = lower.splitlines()[0] if lower else ""
        score = sum(lower.count(t) + 2 * title.count(t) for t in terms)
        if score > 0:
            scored.append((score, name, content))
    if not scored:
        return f"no documents match {query!r}"
    scored.sort(key=lambda s: (-s[0], s[1]))
    parts = []
    for score, name, content in scored[:2]:
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
        hits = [p for p in paragraphs if any(t in p.lower() for t in terms)][:2]
        excerpt = "\n\n".join(hits) if hits else paragraphs[0]
        parts.append(f"--- {name} (score {score}) ---\n{excerpt}")
    return "\n\n".join(parts)


def _tool(name: str, description: str, props: dict, fn) -> ToolDef:
    return ToolDef(
        name=name,
        description=description,
        parameters={"type": "object", "properties": props, "required": list(props)},
        fn=fn,
    )


TOOLBOX: dict[str, ToolDef] = {
    "query_logs": _tool(
        "query_logs",
        "Search the API access logs. Returns entries where any field (ip, path, "
        "status, user_agent, token_sub...) contains the filter substring. "
        "Output is capped at 50 entries.",
        {"filter": {"type": "string"}}, query_logs),
    "inspect_schema": _tool(
        "inspect_schema",
        "Return the DDL of a database table by name. Pass '*' or an unknown "
        "name to list all tables and the application stack.",
        {"table": {"type": "string"}}, inspect_schema),
    "count_affected_users": _tool(
        "count_affected_users",
        "Quantify the data exposure: cross-references customer-export requests "
        "found in the access logs with the customers table to estimate how many "
        "customers and which fields are affected.",
        {"criteria": {"type": "string"}}, count_affected_users),
    "lookup_cve": _tool(
        "lookup_cve",
        "Search known CVE bulletins by package name, CVE id or keyword.",
        {"query": {"type": "string"}}, lookup_cve),
    "doc_search": _tool(
        "doc_search",
        "Search the internal document base (incident procedures, GDPR guidance, "
        "notification templates). Returns the 2 most relevant documents with "
        "matching excerpts.",
        {"query": {"type": "string"}}, doc_search),
    "get_incident_report": _tool(
        "get_incident_report",
        "Return the initial incident ticket as raised by monitoring.",
        {}, get_incident_report),
}
```

- [ ] **Step 4: Vérifier que tous les tests tools passent**

```powershell
.venv\Scripts\python -m pytest tests/demo/incident/test_tools.py -v
```

Expected: 19 passed.

- [ ] **Step 5: Commit**

```powershell
git add src/aaosa/demo/incident/tools.py tests/demo/incident/test_tools.py
git commit -m "feat(demo-p3): tools analyse - lookup_cve, count_affected_users, doc_search + TOOLBOX"
```

---

### Task 5: Roster (`agents.yaml` + `agents.py`) — TDD

**Files:**
- Create: `src/aaosa/demo/incident/agents.yaml`
- Create: `src/aaosa/demo/incident/agents.py`
- Test: `tests/demo/incident/test_agents.py`

- [ ] **Step 1: Écrire les tests qui échouent**

`tests/demo/incident/test_agents.py` :

```python
"""Tests du roster incident — 7 agents / 3 domaines, tools résolus du YAML."""

from aaosa.core.agent import Agent
from aaosa.core.tool import ToolDef
from aaosa.demo.incident.agents import INCIDENT_AGENTS

_by_name = {a.name: a for a in INCIDENT_AGENTS}

EXPECTED_NAMES = {
    "backend-dev", "sre", "security-analyst", "dpo-jurist",
    "client-comm", "support-lead", "data-analyst",
}

EXPECTED_TOOLS = {
    "backend-dev": ["query_logs", "inspect_schema", "get_incident_report"],
    "sre": ["query_logs", "get_incident_report"],
    "security-analyst": ["query_logs", "lookup_cve", "get_incident_report"],
    "dpo-jurist": ["doc_search", "get_incident_report"],
    "client-comm": ["get_incident_report"],
    "support-lead": ["get_incident_report"],
    "data-analyst": ["count_affected_users", "query_logs", "inspect_schema"],
}


class TestRosterStructure:
    def test_seven_agents(self):
        assert len(INCIDENT_AGENTS) == 7

    def test_names(self):
        assert set(_by_name) == EXPECTED_NAMES

    def test_all_agent_instances_with_unique_ids(self):
        assert all(isinstance(a, Agent) for a in INCIDENT_AGENTS)
        ids = [a.id for a in INCIDENT_AGENTS]
        assert len(ids) == len(set(ids))

    def test_non_empty_system_prompts(self):
        assert all(a.system_prompt.strip() for a in INCIDENT_AGENTS)


class TestRosterTools:
    def test_tools_resolved_from_yaml(self):
        for name, expected in EXPECTED_TOOLS.items():
            tools = _by_name[name].tools
            assert all(isinstance(t, ToolDef) for t in tools)
            assert [t.name for t in tools] == expected


class TestRosterTags:
    def test_gdpr_monopoly(self):
        """Le dpo-jurist est seul sur les tags réglementaires → roster_gap quand absent."""
        for tag in ("gdpr", "legal", "compliance"):
            holders = [a.name for a in INCIDENT_AGENTS if tag in a.tags_with_elo]
            assert holders == ["dpo-jurist"], f"tag {tag} held by {holders}"

    def test_logs_competition(self):
        """Compétition intra-domaine : 3 agents d'ingénierie se disputent les logs."""
        holders = {a.name for a in INCIDENT_AGENTS if "logs" in a.tags_with_elo}
        assert holders == {"backend-dev", "sre", "security-analyst"}

    def test_communication_competition(self):
        holders = {a.name for a in INCIDENT_AGENTS if "communication" in a.tags_with_elo}
        assert holders == {"client-comm", "support-lead"}

    def test_database_overlap(self):
        holders = {a.name for a in INCIDENT_AGENTS if "database" in a.tags_with_elo}
        assert holders == {"backend-dev", "data-analyst"}
```

- [ ] **Step 2: Vérifier que les tests échouent**

```powershell
.venv\Scripts\python -m pytest tests/demo/incident/test_agents.py -v
```

Expected: `ModuleNotFoundError: No module named 'aaosa.demo.incident.agents'`.

- [ ] **Step 3: Créer `agents.yaml`**

`src/aaosa/demo/incident/agents.yaml` :

```yaml
# Roster de la démo incident AAOSA — 7 agents / 3 domaines.
# Chargé par aaosa.config.loader.load_agents ; tools résolus via TOOLBOX (tools.py).
# Les ELO de ce fichier SONT le snapshot de départ versionné (rejouer depuis
# zéro = recharger ce YAML). Compétition intra-domaine voulue : logs
# (backend-dev/sre/security-analyst), communication (client-comm/support-lead),
# database (backend-dev/data-analyst). Monopole réglementaire : dpo-jurist.

- name: backend-dev
  tags_with_elo:
    backend: 85
    logs: 70
    database: 80
    investigation: 65
  tools: [query_logs, inspect_schema, get_incident_report]
  system_prompt: >-
    You are the backend developer on call for the customer-management API.
    You know the codebase and its database. Investigate with your tools before
    answering: read the incident report, query the access logs and inspect the
    DB schema to understand what the suspicious requests touched. Then give a
    complete, factual response: what happened at the application level, which
    endpoint and data were involved, quote the relevant log entries, and
    propose immediate technical remediation steps.

- name: sre
  tags_with_elo:
    infrastructure: 85
    logs: 75
    access_control: 70
    investigation: 60
  tools: [query_logs, get_incident_report]
  system_prompt: >-
    You are the site reliability engineer on call. You own infrastructure,
    access control and traffic patterns. Investigate with your tools before
    answering: read the incident report and query the access logs for unusual
    sources, volumes and time windows. Then give a complete, factual response:
    characterize the anomalous traffic (source IPs, timing, volume), how access
    was likely obtained, and propose containment measures such as token
    revocation, IP blocking and rate limiting.

- name: security-analyst
  tags_with_elo:
    security: 90
    vulnerability: 85
    logs: 72
    investigation: 75
  tools: [query_logs, lookup_cve, get_incident_report]
  system_prompt: >-
    You are the security analyst. Investigate with your tools before answering:
    read the incident report, query the access logs for attack patterns and
    look up known CVEs for the components of our stack. Then give a complete,
    factual response: confirm or refute the data exfiltration, identify the
    likely attack vector citing the CVE if applicable, the compromised
    credential, and the exposed data perimeter.

- name: dpo-jurist
  tags_with_elo:
    gdpr: 90
    legal: 85
    compliance: 88
  tools: [doc_search, get_incident_report]
  system_prompt: >-
    You are the data protection officer (DPO). You qualify incidents under
    GDPR and prepare regulatory steps. Search the internal document base with
    doc_search before answering: notification obligations, deadlines and
    templates. Then give a complete, sourced response: whether this is a
    personal-data breach, whether the CNIL must be notified and within what
    deadline, whether affected individuals must be informed, citing the
    internal documents you used.

- name: client-comm
  tags_with_elo:
    communication: 88
    writing: 85
    customer_relations: 80
  tools: [get_incident_report]
  system_prompt: >-
    You are the client communications manager. You turn incident facts into
    clear, honest customer-facing messaging. Base yourself strictly on the
    facts established by the investigation (scope, data involved, remediation
    steps) — never invent facts. Produce ready-to-send content: a customer
    notification email and a short public holding statement, with brief tone
    guidance.

- name: support-lead
  tags_with_elo:
    customer_relations: 85
    communication: 70
    support: 90
  tools: [get_incident_report]
  system_prompt: >-
    You are the customer support lead. You prepare the support team for
    incident fallout. Based on the established facts, produce a support brief:
    an internal FAQ covering the questions customers are likely to ask with
    approved answers, escalation rules for unhappy or high-value customers,
    and explicit guidance on what support must not say or promise.

- name: data-analyst
  tags_with_elo:
    data_analysis: 88
    database: 70
    reporting: 75
  tools: [count_affected_users, query_logs, inspect_schema]
  system_prompt: >-
    You are the data analyst. You quantify incident impact. Use your tools
    before answering: count affected customers from the export requests found
    in the logs and inspect the schema to identify the exposed fields. Then
    give a precise, numeric response: how many customers are affected out of
    the total customer base, which fields were exposed, and any segmentation
    useful for the legal and communication teams.
```

- [ ] **Step 4: Créer `agents.py`**

`src/aaosa/demo/incident/agents.py` :

```python
from pathlib import Path

from aaosa.config.loader import load_agents
from aaosa.demo.incident.tools import TOOLBOX

INCIDENT_AGENTS = load_agents(Path(__file__).parent / "agents.yaml", tool_registry=TOOLBOX)
```

- [ ] **Step 5: Vérifier que les tests passent**

```powershell
.venv\Scripts\python -m pytest tests/demo/incident/test_agents.py -v
```

Expected: 9 passed.

- [ ] **Step 6: Commit**

```powershell
git add src/aaosa/demo/incident/agents.yaml src/aaosa/demo/incident/agents.py tests/demo/incident/test_agents.py
git commit -m "feat(demo-p3): roster incident 7 agents / 3 domaines, tools YAML"
```

---

### Task 6: Scénarios (`scenarios.py`) — TDD

**Files:**
- Create: `src/aaosa/demo/incident/scenarios.py`
- Test: `tests/demo/incident/test_scenarios.py`

- [ ] **Step 1: Écrire les tests qui échouent**

`tests/demo/incident/test_scenarios.py` :

```python
"""Tests des scénarios incident — données pures, zéro runtime."""

from aaosa.demo.incident.agents import INCIDENT_AGENTS
from aaosa.demo.incident.scenarios import (
    build_data_leak_task,
    full_roster,
    roster_gap_roster,
)
from aaosa.schemas.task import Task


class TestDataLeakTask:
    def test_task_well_formed(self):
        task = build_data_leak_task()
        assert isinstance(task, Task)
        assert task.required_tags == {"security": 70, "gdpr": 70, "communication": 65}
        assert task.context and task.context.strip()

    def test_fresh_task_each_call(self):
        assert build_data_leak_task().id != build_data_leak_task().id


class TestRosters:
    def test_full_roster_has_seven(self):
        roster = full_roster()
        assert len(roster) == 7
        assert set(a.name for a in roster) == set(a.name for a in INCIDENT_AGENTS)

    def test_full_roster_is_a_copy(self):
        roster = full_roster()
        assert roster is not INCIDENT_AGENTS
        roster.clear()
        assert len(INCIDENT_AGENTS) == 7

    def test_roster_gap_drops_only_dpo_jurist(self):
        gap = roster_gap_roster()
        assert len(gap) == 6
        assert "dpo-jurist" not in {a.name for a in gap}
        assert {a.name for a in full_roster()} - {a.name for a in gap} == {"dpo-jurist"}
```

- [ ] **Step 2: Vérifier que les tests échouent**

```powershell
.venv\Scripts\python -m pytest tests/demo/incident/test_scenarios.py -v
```

Expected: `ModuleNotFoundError: No module named 'aaosa.demo.incident.scenarios'`.

- [ ] **Step 3: Implémenter `scenarios.py`**

```python
"""Scénarios de la démo incident — données pures, zéro runtime.

main : tâche fuite de données, roster complet (7 agents).
roster_gap : même tâche, roster privé du dpo-jurist — le gap émerge du
claiming (sous-tâche réglementaire unclaimable), jamais du scénario.
"""

from aaosa.core.agent import Agent
from aaosa.demo.incident.agents import INCIDENT_AGENTS
from aaosa.schemas.task import Task

_ALERT_CONTEXT = (
    "Monitoring alert 2026-06-06 06:30 UTC: anomalous nighttime traffic on "
    "/api/v2/customers/export. Full ticket available via the "
    "get_incident_report tool."
)


def build_data_leak_task() -> Task:
    return Task(
        description=(
            "Anomalous traffic was detected on the customers API last night. "
            "Determine whether customer data was leaked, assess the scope of "
            "the breach, qualify our regulatory obligations, and prepare the "
            "customer communication."
        ),
        required_tags={"security": 70, "gdpr": 70, "communication": 65},
        context=_ALERT_CONTEXT,
    )


def full_roster() -> list[Agent]:
    return list(INCIDENT_AGENTS)


def roster_gap_roster() -> list[Agent]:
    return [a for a in INCIDENT_AGENTS if a.name != "dpo-jurist"]
```

- [ ] **Step 4: Vérifier que les tests passent**

```powershell
.venv\Scripts\python -m pytest tests/demo/incident/test_scenarios.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Suite complète (non-régression)**

```powershell
.venv\Scripts\python -m pytest -q
```

Expected: tous verts (883 existants + les nouveaux ; 1 skip LLM possible).

- [ ] **Step 6: Commit**

```powershell
git add src/aaosa/demo/incident/scenarios.py tests/demo/incident/test_scenarios.py
git commit -m "feat(demo-p3): scenarios main + roster_gap (donnees pures)"
```

---

### Task 7: Script de validation (`run_incident.py`)

Jetable (remplacé par le CLI phase 4) — wiring only, pas de tests dédiés : les briques (scenarios, agents, tools) sont testées, le script est validé par le DoD réel (Task 8).

**Files:**
- Create: `src/aaosa/demo/incident/run_incident.py`

- [ ] **Step 1: Implémenter le script**

```python
"""Script de validation jetable — démo incident phase 3 (remplacé par le CLI phase 4).

Lancer : .venv\\Scripts\\python src\\aaosa\\demo\\incident\\run_incident.py [main|roster_gap]
(requiert OPENAI_API_KEY dans .env)
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from aaosa.demo.incident.scenarios import (
    build_data_leak_task,
    full_roster,
    roster_gap_roster,
)
from aaosa.elo.persistence import save_snapshot
from aaosa.qa.spec_evaluator import AdaptiveSpecEvaluator
from aaosa.runtime.aggregator import TaskAggregator
from aaosa.runtime.context import RunContext
from aaosa.runtime.divider import TaskDivider
from aaosa.runtime.llm_client import create_client
from aaosa.runtime.runner import run_with_recovery
from aaosa.runtime.tagger import Tagger
from aaosa.schemas.output import Output
from aaosa.tracing.formatter import print_timeline
from aaosa.tracing.store import (
    SessionMeta,
    SessionTaskRecord,
    new_session_id,
    save_agent_registry,
    save_session,
)
from aaosa.tracing.tracer import Tracer

_ROSTERS = {"main": full_roster, "roster_gap": roster_gap_roster}


def run_incident(scenario: str) -> None:
    load_dotenv()
    client = create_client()
    runs_root = Path("runs")
    session_id = new_session_id()
    tracer = Tracer(session_id=session_id)
    started_at = datetime.now(timezone.utc)

    agents = _ROSTERS[scenario]()
    evaluator = AdaptiveSpecEvaluator(client)

    divider = TaskDivider(system_prompt=(
        "You are a task decomposer. Break the task into the minimal set of ordered "
        "sub-tasks needed to fully resolve it. Express dependencies between sub-tasks. "
        "Prefer few, well-scoped sub-tasks, and include a final synthesis sub-task."
    ))
    aggregator = TaskAggregator(system_prompt=(
        "You are a synthesizer. Merge the sub-task results into one coherent, complete "
        "answer to the original incident."
    ))
    tagger = Tagger(system_prompt=(
        "You assign capability tags to a task description. Use the roster vocabulary "
        "when it fits; name a real capability even if absent. Return at least one tag."
    ))
    ctx = RunContext(
        agents=agents, client=client, divider=divider, aggregator=aggregator,
        tagger=tagger, tracer=tracer, evaluator=evaluator,
    )

    task = build_data_leak_task()
    print(f"=== AAOSA incident demo — scenario: {scenario} ({len(agents)} agents) ===\n")
    print(f"Input: {task.description}\n")

    # run_with_recovery directement : jamais de division forcée (thèse D1),
    # et la Task du meta EST la racine de la trace.
    result = run_with_recovery(task, ctx)
    outcome = "divided" if isinstance(result, Output) else "unassigned"
    print(f"  -> {outcome}\n")

    print("=== Timeline ===")
    print_timeline(tracer.events)

    print("\n=== Persistence ===")
    save_agent_registry(agents, runs_root / "agents" / "registry.json")
    meta = SessionMeta(
        session_id=session_id,
        started_at=started_at,
        ended_at=datetime.now(timezone.utc),
        tasks=[SessionTaskRecord(
            id=task.id, description=task.description,
            winner_agent_id=None, outcome=outcome,
            required_tags=task.required_tags, context=task.context,
        )],
        agent_ids=[a.id for a in agents],
    )
    session_dir = save_session(tracer, meta, runs_root, agents=agents)
    print(f"Session saved to {session_dir}")

    snapshot_dir = runs_root / "elo_snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    path = save_snapshot(agents, snapshot_dir)
    print(f"ELO snapshot saved to {path}")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "main"
    if arg not in _ROSTERS:
        sys.exit(f"Usage: run_incident.py [main|roster_gap] (got {arg!r})")
    run_incident(arg)
```

Note : `outcome` est un label de scénario contraint par `TaskOutcome` (`"divided"`/`"unassigned"`), pas le chemin runtime réel — la trace est la vérité (convention établie phase 2).

- [ ] **Step 2: Vérifier que le script s'importe sans erreur (sans clé API)**

```powershell
.venv\Scripts\python -c "import aaosa.demo.incident.run_incident as m; print(sorted(m._ROSTERS))"
```

Expected: `['main', 'roster_gap']`

- [ ] **Step 3: Suite complète**

```powershell
.venv\Scripts\python -m pytest -q
```

Expected: tous verts.

- [ ] **Step 4: Commit**

```powershell
git add src/aaosa/demo/incident/run_incident.py
git commit -m "feat(demo-p3): run_incident.py - script de validation jetable (main|roster_gap)"
```

---

### Task 8: DoD réel LLM + CLAUDE.md — CHECKPOINT HUMAIN

**Files:**
- Modify: `CLAUDE.md` (état courant + arborescence demo/)

⚠️ Cette task consomme l'API OpenAI (gpt-4o-mini) et requiert `.env` avec `OPENAI_API_KEY`. **Demander le go à Quentin avant de lancer les runs réels.**

- [ ] **Step 1: Run réel scénario main**

```powershell
.venv\Scripts\python src\aaosa\demo\incident\run_incident.py main
```

Expected (DoD 1) : la tâche **aboutit** — un `Output` final (QA pass), graphe émergent (simple ou divisé, peu importe : zéro division forcée). Session persistée sous `runs/sessions/<id>/`. Si le run échoue au QA, relancer une fois ; si l'échec persiste, STOP — analyser les `reason` QA réelles avant de tuner quoi que ce soit (leçon seed-tuning 2026-06-03 : capturer les raisons avant de toucher prompts ou monde).

- [ ] **Step 2: Run réel scénario roster_gap**

```powershell
.venv\Scripts\python src\aaosa\demo\incident\run_incident.py roster_gap
```

Expected (DoD 2) : un `RosterGapEvent` dans la timeline (tags réglementaires sans porteur). Vérifier dans la trace persistée :

```powershell
Select-String -Path "runs\sessions\<session_id>\trace.jsonl" -Pattern "roster_gap"
```

Expected: au moins une ligne.

- [ ] **Step 3: Vérification dashboard (DoD 3)**

```powershell
.venv\Scripts\python -m dashboard
```

Ouvrir http://localhost:5000 → tab Sessions : les deux sessions (main, roster_gap) se chargent et leur graphe se rend sans erreur console. **Sign-off Quentin.**

- [ ] **Step 4: Mettre à jour CLAUDE.md**

Dans `CLAUDE.md` : ajouter un bloc d'état « V3 — démo phase 3 » (pattern des blocs existants : nombre de tests, contenu livré, DoD validé, prochaine étape = phase 4 CLI) et compléter l'arborescence `demo/` avec `incident/` (world/ + world.py + tools.py + agents.yaml + agents.py + scenarios.py + run_incident.py).

- [ ] **Step 5: Commit final**

```powershell
git add CLAUDE.md
git commit -m "docs(demo-p3): CLAUDE.md - phase 3 monde simule + roster incident, DoD LLM reel"
```

---

## Self-review (fait à l'écriture du plan)

- **Spec coverage** : §3 layout → Tasks 1-7 · §4 narrative/cohérence → Task 1 + tests Task 2 · §5 loaders → Task 2 · §6 tools → Tasks 3-4 · §7 roster → Task 5 · §8 scénarios → Task 6 · §9 script → Task 7 · §10 tests → Tasks 2-6 · §11 DoD → Task 8 · §12 hors scope respecté (aucune modif hors `demo/` + `CLAUDE.md`).
- **Placeholders** : aucun — chaque fichier data et chaque module a son contenu complet.
- **Type consistency** : `TOOLBOX: dict[str, ToolDef]` (Task 4) consommé par `agents.py` (Task 5) ; `INCIDENT_AGENTS` (Task 5) consommé par `scenarios.py` (Task 6) ; `full_roster`/`roster_gap_roster`/`build_data_leak_task` (Task 6) consommés par `run_incident.py` (Task 7) ; signatures `load_*` (Task 2) utilisées par `tools.py` (Tasks 3-4).
