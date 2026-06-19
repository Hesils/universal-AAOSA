# Spec `cnq` — `aaosa solve --context-dir` (arborescence injectée)

> Statut : **proposée** (à valider par Quentin avant plan TDD).
> Ticket : `cnq` (P2, épique `aaosa-subbrain`, `blocked_by: erd` — **levé**, erd mergé master 2026-06-18).
> Décisions de cadrage (session 2026-06-19) : **scope = injection seule** (pas de tool lecteur fs) ; **walk filtré** (skip dotfiles + `.git/`, respecte `.gitignore`).
> Socle : prolonge la commande `solve` livrée par `erd` (`docs/superpowers/specs/2026-06-17-erd-cli-solve.md`).

## 1. Objectif

Donner à `aaosa solve` une 3ᵉ source de contexte : `--context-dir <dir>`. Au lieu d'injecter du **contenu** (`--context-text` / `--context-file`), on injecte l'**arborescence seule** — une liste de chemins relatifs des fichiers sous `<dir>`. Les agents découvrent ainsi *quels* fichiers existent et fetchent *tel ou tel* fichier via leurs propres tools lecteurs (Monde B), au lieu de noyer le prompt avec tout le contenu.

C'est la brique qui rend AAOSA utilisable sur un sub-brain réel (vault AIOS, repo de code) : l'agent reçoit la carte, pas le territoire.

## 2. Périmètre

**Dans `cnq`** :
1. Nouveau flag `--context-dir <dir>` (optionnel, single ; cumulable avec `--context-text` / `--context-file`).
2. Walk **filtré** de `<dir>` → liste triée de chemins relatifs POSIX → injectée dans `Task.context` sous un en-tête de provenance.
3. Filtrage : skip tout nom commençant par `.` (dotfiles/dot-dirs, dont `.git/`, `.obsidian/`, `.venv/`) + respect du `.gitignore` racine si présent.
4. **Budget réutilisé** : l'arbo rendue rejoint `parts`, soumise au même `--context-max`. Refus dur sur overflow, **jamais de troncature**.
5. Erreurs claires + `Exit(code=1)` : dir absent / pas un dossier / aucun fichier après filtrage.

**Hors `cnq`** (siblings) :
- Tool lecteur **filesystem réel** (aujourd'hui `demo/tools.py::read_file` lit un dict en mémoire) → responsabilité du roster + sécurité Monde B = ticket **`v1m`** (worktree par run + non-destruction). `cnq` injecte la carte ; lire le territoire en sûreté est le job de `v1m`.
- `--context-dir` **répétable** / multi-dir → YAGNI (un sub-brain = une racine). Single pour l'instant.
- `.gitignore` **imbriqués** (sous-dossiers), git global excludes, négations héritées hiérarchiquement → hors scope. On lit le `.gitignore` **racine** uniquement (limitation documentée).

## 3. Décision ouverte — dépendance `pathspec`

« Respecte `.gitignore` » correctement implique la sémantique gitignore réelle (`**`, négations `!`, ancrage `/`, classes). Trois options :

| Option | Verdict |
|---|---|
| **A. `pathspec>=1.1.1`** (lib gitignore standard : black, pre-commit) — `GitIgnoreSpec.from_lines` sur le `.gitignore` racine | **VALIDÉE** (2026-06-19). Correct, ~tiny, pure-Python. API 1.1.1 vérifiée. |
| B. shell-out `git ls-files` | Rejetée : ne marche que si `<dir>` est un repo git (un vault ne l'est pas forcément). |
| C. parser maison fnmatch ligne-à-ligne | Rejetée : mishandle `**`/négation/ancrage silencieusement = « résolution défaillante silencieuse », pire qu'un refus (invariant erd §4). |

**Validé (2026-06-19)** : ajout de `pathspec>=1.1.1` (dernière version PyPI) dans `pyproject.toml [dependencies]` (+ décision à logger dans `decisions.md`). API 1.1.1 vérifiée : `GitIgnoreSpec.from_lines(...).match_file(p)` → `True` si ignoré, négations `!` et dossiers `build/` OK.

## 4. Contrat CLI — ajout à `aaosa solve`

```
aaosa solve
  … (flags erd inchangés) …
  --context-dir <dir>     # optionnel, single ; arborescence (chemins relatifs) injectée, PAS le contenu
```

- **Provenance** : l'arbo est préfixée `# context: tree of <dir>` (parallèle aux en-têtes `# context: inline` / `# context: <path>` existants).
- **Ordre de concat** dans `parts` : `text` → `file` → `dir` (ordre de déclaration des flags).
- **Format de l'arbo** : liste **plate**, **triée**, de chemins relatifs en séparateurs POSIX (`/`), un par ligne. Pas d'art ASCII (`├──`) : une liste plate est plus parseable par le LLM et déterministe cross-platform. Exemple :
  ```
  # context: tree of ./mon-vault
  notes/decisions.md
  notes/roadmap.md
  src/agent.py
  ```
- **Overflow** : `len(context) > context_max` → message clair + `Exit(1)` (mécanisme erd inchangé, l'arbo ne fait que contribuer à `parts`).
- **Erreurs `--context-dir`** : dir absent / pas un dossier → `Exit(1)` « context-dir not found or not a directory ». Zéro fichier après filtrage → `Exit(1)` « no files under <dir> after filtering » (injecter une arbo vide est silencieusement inutile → fail loud).

## 5. Changements par module

### 5.1 `src/aaosa/cli/context_dir.py` (nouveau — pur, zéro print/Typer)

Convention de pureté du repo (`incident_runs.py` / `solve_runs.py` : helpers purs ; `app.py` = seul à printer).

```python
def build_context_tree(root: Path) -> str:
    """Walk `root`, retourne la liste triée (newline-join) des chemins relatifs
    POSIX des fichiers, en filtrant dotfiles + `.git/` + matches `.gitignore`
    racine. Pur. Lève ValueError si `root` n'est pas un dossier ou si aucun
    fichier ne subsiste après filtrage."""
```

Logique :
1. `root.is_dir()` faux → `ValueError("context-dir not found or not a directory: <root>")`.
2. Charger `root/.gitignore` si présent → `pathspec.GitIgnoreSpec.from_lines(lines)` (sinon spec vide).
3. `os.walk(root)` : à chaque niveau, **pruner** les dirs dont le nom commence par `.` (coupe la descente dans `.git/`, `.obsidian/`, `.venv/`). Pour chaque fichier : skip si nom commence par `.` ; calculer le chemin relatif POSIX ; skip si la spec gitignore le matche.
4. Trier les chemins survivants. Vide → `ValueError("no files under <root> after filtering")`.
5. Retourner `"\n".join(sorted_paths)`.

### 5.2 `src/aaosa/cli/app.py` — commande `solve`

- Ajouter le paramètre `context_dir: Path | None = typer.Option(None, "--context-dir", help="Arborescence (chemins relatifs) injectée dans le contexte ; les agents fetchent les fichiers via leurs tools. Filtré (dotfiles + .gitignore).")`.
- Dans le bloc d'assemblage `parts` (après le bloc `context_file`), avant le calcul de `context` :
  ```python
  if context_dir is not None:
      try:
          tree = build_context_tree(context_dir)
      except ValueError as exc:
          typer.echo(str(exc))
          raise typer.Exit(code=1)
      parts.append(f"# context: tree of {context_dir}\n{tree}")
  ```
- Le reste (calcul `context`, check `context_max`, appel `solve_once`) **inchangé**. `solve_once` et `Task.context` ne bougent pas (rétrocompat stricte).

### 5.3 `pyproject.toml`

- `dependencies` : `+ "pathspec>=1.1.1"` (validé §3).

## 6. Tests (TDD — détaillés dans le plan)

Backend pur → **pleinement nuit-compatible**, suite verte avant de clore. Cibles :

**`tests/cli/test_context_dir.py`** (helper pur, zéro LLM) :
- arbo plate triée de chemins relatifs POSIX (fixture `tmp_path` avec sous-dossiers).
- dotfiles & dot-dirs exclus (`.git/`, `.obsidian/note.md`, `.env`).
- `.gitignore` racine honoré (`*.log`, `build/`, négation `!keep.log`).
- séparateurs POSIX même sous Windows (`a/b.md`, jamais `a\b.md`).
- `root` inexistant / fichier → `ValueError`.
- dir vide après filtrage → `ValueError`.

**`tests/cli/test_solve_context_dir.py`** (intégration CLI via `CliRunner`, mock `solve_once`) :
- `--context-dir` injecte l'en-tête `# context: tree of …` + l'arbo dans le `context` passé à `solve_once`.
- cumul `--context-text` + `--context-dir` : les deux parts présentes, bon ordre.
- overflow (`--context-max` petit) → `Exit(1)`, `solve_once` non appelé.
- dir invalide → `Exit(1)`, message clair.

## 7. Invariants respectés

- `Task.context` reste `str | None`, lu sans mutation — **aucun** changement de schéma ni de `solve_once`.
- `app.py` reste le seul à printer ; le walk vit dans un helper **pur** testable sans Typer.
- Rétrocompat stricte : sans `--context-dir`, comportement `solve` identique à erd.
- Fail loud, jamais de troncature silencieuse (invariant erd §4 sur l'overflow étendu au filtrage vide).
- `cnq` n'empiète pas sur Monde B : il injecte des **chemins**, ne lit aucun contenu de fichier, ne livre aucun tool lecteur (frontière avec `v1m`).

## 8. DoD

- [ ] `tests/cli/test_context_dir.py` + `tests/cli/test_solve_context_dir.py` verts.
- [ ] Suite complète verte (`.venv\Scripts\python -m pytest`).
- [ ] `pathspec` ajouté à `pyproject.toml` (si §3 validé) + décision loggée.
- [ ] Smoke manuel (jour, Quentin) : `aaosa solve --roster … --task … --context-dir <repo>` → l'arbo apparaît dans le `Task.context` de la trace, refus propre sur overflow. **Validation LLM-réel = matin, pas la nuit** (convention projet).
