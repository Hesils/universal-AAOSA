"""Tagger — description → ensemble de tags (≥1 garanti).

Génère les tags d'une tâche en fonction de sa description et du roster.
"""

from pydantic import BaseModel, ConfigDict, Field

from aaosa.core.agent import Agent
from aaosa.runtime.providers import LLMProvider


class TagSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tags: list[str] = Field(min_length=1)


class EmptyTaggingError(Exception):
    """Raised when tag generation fails or returns an empty set."""
    pass


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
        # Bundles par rôle (anonymes) plutôt que vocabulaire à plat : le filtre aval
        # est un AND strict, le LLM doit voir quelles co-occurrences existent pour
        # émettre un ensemble qu'un seul agent peut détenir.
        bundles = sorted({tuple(sorted(a.tags_with_elo)) for a in agents})
        bundle_lines = "\n".join(f"  - {', '.join(b)}" for b in bundles)
        return (
            "Available agent tags (reference vocabulary — not exhaustive), grouped\n"
            "by role — each line is the tag set of one existing role:\n"
            f"{bundle_lines}\n\n"
            "Name the capabilities (tags) this task requires to be done well.\n"
            "The tags are an AND-filter: a single agent must hold ALL of them to take\n"
            "the task. Pick the line above whose role is best suited to do the work and\n"
            "return its 1-2 most relevant tags. Never mix tags from different lines —\n"
            "not every capability the task touches, only what the doer must hold.\n"
            "If the truly required capability appears on no line, name it even though it\n"
            "is absent from the roster — do not force-fit. Return at least one tag.\n\n"
            f"Task: {description}"
        )

    def tag(self, description: str, agents: list[Agent], provider: LLMProvider, model: str | None = None) -> set[str]:
        """Génère un ensemble de tags pour la description.

        Retourne un ensemble vide si le LLM échoue ou ne peut pas parser.
        """
        prompt = self._build_prompt(description, agents)
        parsed = provider.parse(
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ],
            schema=TagSet,
            temperature=0.0,
            model=model,
        )
        if parsed is None:
            return set()
        return {t.strip() for t in parsed.tags if t.strip()}
