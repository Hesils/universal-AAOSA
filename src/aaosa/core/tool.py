"""ToolDef (A5) — outil attachable à un agent.

Dataclass (pas Pydantic) : les callables ne sont pas sérialisables. Agent porte
déjà arbitrary_types_allowed=True. Framework-agnostic ; to_openai() encapsule le
formatage OpenAI.
"""

from dataclasses import dataclass
from typing import Callable

MAX_TOOL_ROUNDS = 20


@dataclass
class ToolDef:
    name: str
    description: str
    parameters: dict          # JSON Schema "object" — passé tel quel à l'API OpenAI
    fn: Callable[..., str]    # implémentation ; retourne toujours str

    def to_openai(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
