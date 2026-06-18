"""HITL (ipv) — tool ask_human callable par les agents.

ask_human est un ToolDef framework : son fn capture en closure un callback
question -> réponse fourni par l'invocateur (CC / opérateur). Le runtime ne
voit jamais le callback (fn(**args) -> str inchangé côté execute()). Sans
humain (night-run/batch), unattended_callback répond une chaîne non-bloquante.
"""

from typing import Callable

from aaosa.core.tool import ToolDef

HITLCallback = Callable[[str], str]   # question -> réponse

ASK_HUMAN_TOOL_NAME = "ask_human"


def unattended_callback(question: str) -> str:
    """Callback par défaut sans humain (night-run/batch). Non-bloquant."""
    return (
        "No human is available to answer in this run. "
        "Proceed with your best judgment and state any assumption you make."
    )


def make_ask_human_tool(callback: HITLCallback | None = None) -> ToolDef:
    """Construit le ToolDef ask_human. `callback` capturé en closure ;
    callback=None -> unattended_callback (dégradation sûre)."""
    cb = callback or unattended_callback

    def _fn(**kwargs: str) -> str:
        return cb(kwargs["question"])

    return ToolDef(
        name=ASK_HUMAN_TOOL_NAME,
        description=(
            "Ask the human operator a question when you lack a piece of "
            "information that is critical to complete the task and cannot be "
            "obtained otherwise. Returns the human's answer as text."
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The single, specific question to ask the human.",
                }
            },
            "required": ["question"],
        },
        fn=_fn,
    )


def build_builtin_tools(callback: HITLCallback | None = None) -> dict[str, ToolDef]:
    """Registre des tools framework injectables dans un roster (par nom)."""
    return {ASK_HUMAN_TOOL_NAME: make_ask_human_tool(callback)}
