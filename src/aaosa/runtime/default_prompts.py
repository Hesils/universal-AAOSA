"""Prompts système génériques (domain-agnostic) pour `aaosa solve`.

Repris de demo/incident/prompts.py avec « incident » -> « task ». Run-level (1 par
run). Override par fichier custom = YAGNI (sous-ticket si besoin). La démo garde ses
propres prompts « incident » dans demo/incident/prompts.py (inchangé).
"""

DIVIDER_PROMPT = (
    "You are a task decomposer. Break the task into the minimal set of "
    "sub-tasks needed to fully resolve it. Express a dependency between two "
    "sub-tasks only when one genuinely needs the other's output. Prefer few, "
    "well-scoped sub-tasks."
)

AGGREGATOR_PROMPT = (
    "You are a synthesizer. Merge the sub-task results into one coherent, complete "
    "answer to the original task."
)

TAGGER_PROMPT = (
    "You assign capability tags to a task description. Use the roster vocabulary "
    "when it fits; name a real capability even if absent. Return at least one tag."
)
