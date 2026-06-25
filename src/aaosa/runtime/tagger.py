"""Tagger — description → ensemble de tags (≥1 garanti).

Génère les tags d'une tâche en fonction de sa description et du roster.
"""

import re

from pydantic import BaseModel, ConfigDict, Field

from aaosa.core.agent import Agent
from aaosa.runtime.providers import LLMProvider

# Le LLM recopie parfois une ligne-bundle entière comme un seul tag composé
# ("coding, python"). Le matcher aval est un AND-filter ATOMIQUE : un tag composé
# ne matche aucun agent → roster_gap fantôme. Les tags légitimes sont des tokens
# sans espace ni ponctuation de séparation, donc on atomise sur toute cette classe —
# robuste quel que soit le séparateur choisi par le LLM, sans rester couplé au seul
# format ", " du prompt bundle (_build_prompt).
_TAG_SEPARATORS = re.compile(r"[\s,;/|]+")


class TagSet(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tags: list[str] = Field(min_length=1)


class EmptyTaggingError(Exception):
    """Raised when tag generation fails or returns an empty set."""
    pass


class UnsatisfiableTagSetError(Exception):
    """Re-tag d'une sous-spec cross-rôle resté cross-rôle (aucun agent unique ne le
    couvre). Clean-crash géré par _divide_and_recover (comme EmptyTaggingError)."""

    def __init__(self, description: str, tags: set[str]) -> None:
        super().__init__(f"unsatisfiable cross-role tag set for: {description!r} -> {sorted(tags)}")
        self.description = description
        self.tags = tags


class Tagger:
    """Génère un ensemble de tags pour une description donnée.

    Le Tagger ne cherche pas à assigner l'agent directement — il répond à la question
    « quelles sont les compétences requises pour accomplir cette tâche ? »
    indépendamment des agents disponibles. Le roster n'est consulté que comme
    vocabulaire de référence.
    """

    def __init__(self, system_prompt: str) -> None:
        self.system_prompt = system_prompt

    def _build_prompt(
        self, description: str, agents: list[Agent], unsatisfiable_hint: set[str] | None = None
    ) -> str:
        # Bundles par rôle (anonymes) plutôt que vocabulaire à plat : le filtre aval
        # est un AND strict, le LLM doit voir quelles co-occurrences existent pour
        # émettre un ensemble qu'un seul agent peut détenir.
        bundles = sorted({tuple(sorted(a.tags_with_elo)) for a in agents})
        bundle_lines = "\n".join(f"  - {', '.join(b)}" for b in bundles)
        hint = ""
        if unsatisfiable_hint:
            named = ", ".join(sorted(unsatisfiable_hint))
            hint = (
                f"\n\nATTENTION — your previous tag set ({named}) spanned MULTIPLE role "
                "lines, so no single agent can hold it and the task is unassignable. "
                "Return a subset that belongs to EXACTLY ONE role line above. Producing "
                "code is one role; describing or documenting code is a different role — "
                "never combine them."
            )
        return (
            "Available agent tags (reference vocabulary — not exhaustive), grouped\n"
            "by role — each line is the tag set of one existing role:\n"
            f"{bundle_lines}\n\n"
            "Name the capabilities (tags) this task requires to be done well.\n"
            "The tags are an AND-filter: a single agent must hold ALL of them to take\n"
            "the task. Pick the line above whose role is best suited to do the work and\n"
            "return its 1-2 most relevant tags. Return tags from a SINGLE role line —\n"
            "never mix lines. Writing or implementing code is one role; describing or\n"
            "documenting it is another — a task that produces a deliverable needs only\n"
            "the doer's role, not every capability it touches.\n"
            "If the truly required capability appears on no line, name it even though it\n"
            "is absent from the roster — do not force-fit. Return at least one tag.\n\n"
            f"Task: {description}"
            f"{hint}"
        )

    def tag(self, description: str, agents: list[Agent], provider: LLMProvider,
            model: str | None = None, unsatisfiable_hint: set[str] | None = None) -> set[str]:
        """Génère un ensemble de tags pour la description.

        Retourne un ensemble vide si le LLM échoue ou ne peut pas parser.
        """
        prompt = self._build_prompt(description, agents, unsatisfiable_hint)
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
        return {
            piece
            for t in parsed.tags
            for piece in _TAG_SEPARATORS.split(t.strip())
            if piece
        }
