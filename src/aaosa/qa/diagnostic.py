"""Diagnostic d'échec inline (D3) — chemin parallèle au triage batch B2/B3.

`diagnose_failure` classe un qa_fail live en agent / evaluator / task_spec /
unattributed et propose des consignes courtes pour un retry. Pur : prend des
données, retourne un DiagnosticResult (ou None sur échec LLM). Aucun accès au
runtime, au store, ni à l'historique. Indépendant de qa/triage.py (B2).
"""

import json
from typing import Literal

from openai import OpenAI
from pydantic import BaseModel, ConfigDict

from aaosa.qa.protocol import QAResult
from aaosa.schemas.output import Output
from aaosa.schemas.task import Task


class FailureContext(BaseModel):
    """Contexte d'un échec, passé au divider sur la route task_spec (D3)."""
    model_config = ConfigDict(extra="forbid")
    failed_output: Output
    qa_result: QAResult
    diagnostic_reason: str


class DiagnosticResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    attribution: Literal["agent", "evaluator", "task_spec", "unattributed"]
    consignes: str | None = None   # présent si l'agent peut réessayer avec des clarifications
    reason: str                    # alimente FailureContext.diagnostic_reason
