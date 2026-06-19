"""Tools FS framework (v1m). fetch_file réel, jalé par une Sandbox closurée.

Built-in injecté UNIQUEMENT quand une sandbox existe (donc --context-dir
fourni). La racine de lecture = la racine de la sandbox = le --context-dir
dont cnq a déjà injecté l'arborescence. Plafond de taille (refus dur, pas de
troncature) pour ne pas noyer le thread tool-use. make_write_file_tool prouve
le contrat de plancher que les futurs tools write/run devront honorer.
"""

from aaosa.core.sandbox import Sandbox, SandboxViolation
from aaosa.core.tool import ToolDef

FETCH_FILE_TOOL_NAME = "fetch_file"
WRITE_FILE_TOOL_NAME = "write_file"
DEFAULT_FETCH_MAX_CHARS = 50_000


def make_fetch_file_tool(
    sandbox: Sandbox, max_chars: int = DEFAULT_FETCH_MAX_CHARS
) -> ToolDef:
    def _fn(**kwargs: str) -> str:
        path = kwargs["path"]
        try:
            content = sandbox.read_text(path)
        except SandboxViolation as exc:
            return f"[refused: {exc}]"
        except FileNotFoundError:
            return f"[file not found: {path}]"
        except (IsADirectoryError, UnicodeDecodeError, OSError) as exc:
            return f"[cannot read {path}: {exc}]"
        if len(content) > max_chars:
            return (
                f"[file too large: {len(content)} chars > limit {max_chars}. "
                f"Refusing (no truncation). Narrow your request.]"
            )
        return content

    return ToolDef(
        name=FETCH_FILE_TOOL_NAME,
        description=(
            "Fetch the full UTF-8 contents of a file by its path, relative to "
            "the provided context directory. Use the paths listed in the "
            "context tree. Returns the file contents, or a clear error string "
            "if the file is missing, too large, binary, or outside the "
            "allowed directory."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path relative to the context directory root.",
                }
            },
            "required": ["path"],
        },
        fn=_fn,
    )


def make_write_file_tool(sandbox: Sandbox) -> ToolDef:
    """Tool write gardé par le plancher. NON câblé en v1m (pas de --allow-write) ;
    sert à prouver que write_text refuse sur sandbox read-only."""

    def _fn(**kwargs: str) -> str:
        path = kwargs["path"]
        try:
            sandbox.write_text(path, kwargs["content"])
        except SandboxViolation as exc:
            return f"[refused: {exc}]"
        except OSError as exc:
            return f"[cannot write {path}: {exc}]"
        return f"[wrote {path}]"

    return ToolDef(
        name=WRITE_FILE_TOOL_NAME,
        description="Write UTF-8 content to a file path under the context directory.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        fn=_fn,
    )
