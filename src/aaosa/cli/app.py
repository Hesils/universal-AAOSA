"""CLI projet-wide `aaosa` — entrée unique des points d'exécution du projet.

Wiring console fin uniquement : la logique run/campaign vit dans
`aaosa.cli.incident_runs` (helpers purs, sans print).
"""

import typer

app = typer.Typer(no_args_is_help=True, add_completion=False)


@app.callback()
def main() -> None:
    """Runtime multi-agents AAOSA — CLI projet-wide."""


if __name__ == "__main__":
    app()
