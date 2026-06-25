from pydantic import BaseModel, ConfigDict, Field, model_validator

from aaosa.runtime.providers import LLMProvider

from aaosa.qa.diagnostic import FailureContext
from aaosa.schemas.task import Task


class SubTaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: str
    depends_on_indices: list[int] = Field(default_factory=list)
    context: str | None = None  # D3 — contexte distillé pour CETTE sous-tâche


class DivisionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    is_atomic: bool = False
    sub_tasks: list[SubTaskSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def atomic_xor_subtasks(self) -> "DivisionResult":
        if self.is_atomic and self.sub_tasks:
            raise ValueError("atomic division cannot have sub_tasks")
        if not self.is_atomic and not self.sub_tasks:
            raise ValueError("non-atomic division must have sub_tasks")
        return self


def find_cycle_indices(division: "DivisionResult") -> list[int] | None:
    """Détecte un défaut de DAG sur les `depends_on_indices` BRUTS du divider, avant
    toute construction de Task. Pur, sans LLM. Retourne les indices des sous-tâches
    impliquées (triés) si le graphe n'est pas un DAG valide, sinon None.

    Couvre les trois modes observables d'un produit LLM structurellement valide mais
    sémantiquement invalide pour le consommateur aval (Kahn) :
    auto-référence (i→i), cycle (i↔j, i→j→k→i), et indice hors bornes/négatif (qui
    ferait planter build_sub_tasks à la résolution indices→IDs).

    Le payload brut est rendu nommable dans le prompt de retry et traçable. Ne MUTE
    jamais la division — c'est un détecteur."""
    if division.is_atomic:
        return None

    n = len(division.sub_tasks)
    deps = [spec.depends_on_indices for spec in division.sub_tasks]

    # Indices hors bornes / négatifs : invalides pour la résolution aval.
    invalid = [i for i, d in enumerate(deps) if any(j < 0 or j >= n for j in d)]
    if invalid:
        return sorted(invalid)

    # Auto-référence = cycle trivial.
    self_ref = [i for i, d in enumerate(deps) if i in d]
    if self_ref:
        return sorted(self_ref)

    # Kahn : arête j -> i si i dépend de j. in_degree[i] = nb de deps de i. Les nœuds
    # à degré entrant résiduel > 0 après le tri forment (ou alimentent) le cycle.
    in_degree = [len(d) for d in deps]
    adjacency: list[list[int]] = [[] for _ in range(n)]
    for i, d in enumerate(deps):
        for j in d:
            adjacency[j].append(i)

    queue = [i for i in range(n) if in_degree[i] == 0]
    visited = 0
    while queue:
        cur = queue.pop(0)
        visited += 1
        for nxt in adjacency[cur]:
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                queue.append(nxt)

    if visited == n:
        return None
    # Les nœuds à degré entrant résiduel > 0 sont coincés dans/derrière le cycle.
    return sorted(i for i in range(n) if in_degree[i] > 0)


class TaskDivider:
    def __init__(self, system_prompt: str) -> None:
        self.system_prompt = system_prompt

    def _build_divide_prompt(
        self,
        task: Task,
        chained_context: list[Task] | None,
        failure_context: FailureContext | None,
        cycle_context: list[int] | None = None,
    ) -> str:
        inherited = ""
        if chained_context:
            ancestors = "\n".join(f"- {t.description}" for t in chained_context)
            inherited = f"\n\nContexte hérité (tâches ancêtres, racine → parent):\n{ancestors}"

        own_context = f"\n\nContexte domaine de cette tâche:\n{task.context}" if task.context else ""

        failure = ""
        if failure_context is not None:
            failure = (
                "\n\nÉchec précédent à clarifier (la tâche a été jugée ambiguë):\n"
                f"- Diagnostic: {failure_context.diagnostic_reason}\n"
                f"- Verdict QA: {failure_context.qa_result.reason}\n"
                f"- Réponse produite (à désambiguïser):\n{failure_context.failed_output.content}"
            )

        cycle = ""
        if cycle_context:
            named = ", ".join(str(i) for i in cycle_context)
            cycle = (
                "\n\nATTENTION — ta découpe précédente formait un cycle de dépendances "
                f"(les sous-tâches d'indices {named} se dépendent mutuellement, "
                "directement ou en boucle). Une telle découpe est inexécutable. "
                "Reproduis le travail mais émets des `depends_on_indices` qui forment un "
                "DAG acyclique : aucune sous-tâche ne doit dépendre (même indirectement) "
                "d'une sous-tâche qui dépend d'elle, et aucune ne se référence elle-même."
            )

        return (
            "A task is atomic ONLY when it is a single capability producing a single\n"
            "deliverable. If it chains multiple distinct deliverables or capabilities\n"
            "(e.g. write code AND then document it, implement a feature AND test it),\n"
            "it is NOT atomic, even when phrased as one sentence.\n"
            "If the task is atomic, set is_atomic=true and return no sub-tasks.\n"
            "Otherwise set is_atomic=false and decompose it into ordered sub-tasks, each\n"
            "a single capability one specialist role can own, with dependencies\n"
            "(0-based indices into your sub_tasks list).\n"
            "Do NOT assign tags — only describe the work and its ordering.\n"
            "For each sub-task, set `context`: the distilled domain context that THIS "
            "sub-task needs (from the inherited context below), focused — not a copy of "
            "the parent. Leave context null if nothing domain-specific applies.\n\n"
            f"Task: {task.description}"
            f"{own_context}"
            f"{inherited}"
            f"{failure}"
            f"{cycle}"
        )

    def divide(
        self,
        task: Task,
        provider: LLMProvider,
        chained_context: list[Task] | None = None,
        failure_context: FailureContext | None = None,
        cycle_context: list[int] | None = None,
        model: str | None = None,
    ) -> "DivisionResult":
        """LLM call → DivisionResult (structurel, sans tags). Ne construit pas de Task,
        ne résout pas les deps, n'émet aucun event — c'est le runner (build_sub_tasks).

        chained_context / failure_context (D3) enrichissent le prompt et orientent la
        génération du `context` par sous-tâche. cycle_context (signal distinct, non-QA)
        nomme les indices d'un cycle détecté à la découpe précédente pour orienter un
        unique retry. Le divider reste pur : il ne sait pas d'où viennent ces données
        ni qui les consomme."""
        parsed = provider.parse(
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": self._build_divide_prompt(
                    task, chained_context, failure_context, cycle_context)},
            ],
            schema=DivisionResult,
            temperature=0.0,
            model=model,
        )
        if parsed is None:
            raise ValueError("divider returned no parsed DivisionResult")
        return parsed
