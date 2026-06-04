"""Tagger — description → ensemble de tags (≥1 garanti).

Génère les tags d'une tâche en fonction de sa description et du roster.
"""

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field

from aaosa.core.agent import Agent


class TagSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tags: list[str] = Field(min_length=1)


class Tagger:
    """Génère un ensemble de tags pour une description donnée.

    Le Tagger ne cherche pas à assigner l'agent directement — il répond à la question
    « quelles sont les compétences requises pour accomplir cette tâche ? »
    indépendamment des agents disponibles. Le roster n'est consulté que comme
    vocabulaire de référence.
    """

    def __init__(self, system_prompt: str) -> None:
        self.system_prompt = system_prompt

    def _build_prompt(self, description: str, agents: list[Agent]) -> str:
        vocab = sorted({t for a in agents for t in a.tags_with_elo})
        return (
            "Available agent tags (reference vocabulary — not exhaustive):\n"
            f"  {', '.join(vocab)}\n\n"
            "Name the capabilities (tags) this task requires to be done well.\n"
            "Prefer the vocabulary above when it fits, but name a real capability even\n"
            "if it is absent from the roster — do not force-fit. Return at least one tag.\n\n"
            f"Task: {description}"
        )

    def tag(self, description: str, agents: list[Agent], client: OpenAI) -> set[str]:
        """Génère un ensemble de tags pour la description.

        Retourne un ensemble vide si le LLM échoue ou ne peut pas parser.
        """
        prompt = self._build_prompt(description, agents)
        try:
            response = client.beta.chat.completions.parse(
                model="gpt-4o-mini",
                temperature=0.0,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt},
                ],
                response_format=TagSet,
            )
            parsed = response.choices[0].message.parsed
        except Exception:
            parsed = None
        if parsed is None:
            return set()
        return {t.strip() for t in parsed.tags if t.strip()}
