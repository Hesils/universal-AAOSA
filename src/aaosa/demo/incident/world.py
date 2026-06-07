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
