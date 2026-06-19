"""Helper pur de `aaosa solve --context-dir` : walk filtré -> arbo de chemins.

Zéro print, zéro Typer (convention de pureté CLI du repo). app.py câble + printe.
Injecte l'ARBORESCENCE seule (chemins relatifs), jamais le contenu : les agents
fetchent les fichiers via leurs tools (Monde B).
"""

import os
from pathlib import Path

from pathspec import GitIgnoreSpec


def build_context_tree(root: Path) -> str:
    """Walk `root`, retourne la liste triée (newline-join) des chemins relatifs
    POSIX des fichiers, en filtrant dotfiles/dot-dirs + matches `.gitignore`
    racine. Pur. Lève ValueError si `root` n'est pas un dossier ou si aucun
    fichier ne subsiste après filtrage."""
    if not root.is_dir():
        raise ValueError(f"context-dir not found or not a directory: {root}")

    gitignore = root / ".gitignore"
    lines = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.is_file() else []
    spec = GitIgnoreSpec.from_lines(lines)

    rels: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # pruner les dot-dirs (.git, .obsidian, .venv) ET les dirs gitignorés
        kept_dirs = []
        for d in dirnames:
            if d.startswith("."):
                continue
            drel = (Path(dirpath) / d).relative_to(root).as_posix() + "/"
            if spec.match_file(drel):
                continue
            kept_dirs.append(d)
        dirnames[:] = kept_dirs

        for fn in filenames:
            if fn.startswith("."):
                continue
            rel = (Path(dirpath) / fn).relative_to(root).as_posix()
            if spec.match_file(rel):
                continue
            rels.append(rel)

    if not rels:
        raise ValueError(f"no files under {root} after filtering")

    return "\n".join(sorted(rels))
