# Spec `v1m` — Sécurité Monde B : sandbox FS par run + plancher de non-destruction + lecteur fs réel

> Statut : **implémentée (suite verte)** — smoke LLM-réel à valider par Quentin.
> Ticket : `v1m` (P2, épique `aaosa-subbrain`, gate-INDÉPENDANT).
> Source de vérité du cadrage : `seconde_brain/raw/brainstorms/2026-06-17-aaosa-subbrain-agentic.md` (pilier sécurité Monde B, Q8 + open-flags) + décisions de la session `/ticket v1m` (2026-06-19, ci-dessous §9).
> Précédent d'architecture directement réutilisé : `ipv` (`docs/superpowers/specs/2026-06-18-ipv-hitl-tool-design.md`) — tool framework par builder-closure, registre built-in fusionné par nom, runtime synchrone non touché.

## 1. Objectif

Poser le **substrat de sécurité de Monde B** — l'état où AAOSA n'analyse plus seulement mais **agit** via les tools de ses agents — **avant** d'ouvrir le moindre tool destructif. Deux garanties, plus le premier vrai tool exécuteur qui les rend concrètes :

1. **Isolation FS par run** : un agent ne peut lire/écrire qu'**à l'intérieur d'une racine déclarée** (path jail). Aucune fuite vers le reste du disque (`/etc/passwd`, le vault, le repo entier).
2. **Plancher de non-destruction** : par défaut, **aucune écriture/destruction n'est possible** (posture read-only). Une opération destructive exige une racine explicitement marquée inscriptible. « Enforce > instruct » : l'interdit est **structurel**, pas une consigne au prompt — doctrine reprise de l'AIOS `night-guard-destructive-floor` (`AIOS/scripts/night/night-guard.ps1` : marker + deny déterministe au choke point).
3. **Premier vrai tool exécuteur** : `fetch_file` **réel** (lit le vrai FS sous la racine jailée), qui clôt la dette laissée par `cnq` (« cnq n'injecte que des chemins, aucun lecteur fs réel »). Nommé `fetch_file` (pas `read_file`) pour éviter toute collision avec le stub `read_file` de la démo (décision §9).

Côté **gate-INDÉPENDANT** de l'épique subbrain : utilisable seul, fait avancer le North Star « AAOSA pilotable et sûr ». Aucun roster réel adossé à un ministère ici (parqué derrière T4).

## 2. Décisions de forme (tranchées — ne pas re-litiger)

### 2.1 Périmètre = substrat + lecteur fs réel (décision §9)
On livre l'isolation + le plancher de non-destruction **et** le `read_file` réel. Les tools **write/run** ne sont **pas** livrés dans `v1m` (différés) — mais le substrat est conçu et **prouvé** pour qu'ils s'y branchent sans réécriture (un tool destructif **d'échantillon**, uniquement dans les tests, valide le chemin de refus).

### 2.2 Isolation = sandbox dir générique, pas git worktree (décision §9)
Le mot « worktree » de la carte est traduit en **racine FS générique par run** (path jail), **pas** un `git worktree` littéral. Motif : AAOSA est **roster-agnostique** et la cible n'est pas forcément un repo git. Une racine + jail couvre l'isolation de lecture immédiate ; pour les écritures futures la même abstraction crée une racine *isolée* (copie/tmp) sans dépendre de git.

### 2.3 La Sandbox est l'unique porte FS — enforce par construction (pas d'interception dans `execute`)
À l'image d'`ipv` qui **n'a pas touché** `execute()`/`run_task` (callback closuré dans le `fn`), la garantie de non-destruction vit **dans l'objet `Sandbox`**, pas dans un intercepteur central du dispatch de tool :

- Tout accès FS d'un tool passe **obligatoirement** par les méthodes de la `Sandbox` qu'il capture en closure.
- `Sandbox.read_text` est jailé ; `Sandbox.write_text` est jailé **et** lève si la sandbox n'est pas `writable`.
- Un tool ne *peut pas* écrire sans la sandbox, et la sandbox **refuse** sur une racine read-only. L'interdit est donc structurel — pas une politique que le runtime applique ni une discipline que l'auteur du tool doit se rappeler.

**Conséquence directe** : `core/tool.py`, `core/agent.py`, `runtime/runner.py`, `runtime/dispatch.py` restent **inchangés**. Rétrocompat triviale : un run sans sandbox (démo incident, V1/V2/V3) ne voit aucune différence.

> Hypothèse assumée (cohérente avec `roster.py` : « rosters de confiance ») : les tools built-in framework honorent la Sandbox par construction. Un intercepteur central au dispatch (pour gater aussi des tools roster *non-confiance* qui contourneraient la Sandbox) est une **durcissement différé** (§7), pas un besoin de `v1m`.

### 2.4 La racine de lecture = le `--context-dir` de cnq
`cnq` injecte déjà l'**arborescence** (chemins) d'un `--context-dir` dans `Task.context` ; les agents « fetchent via leurs tools ». `v1m` ferme la boucle : le `fetch_file` réel lit **sous cette même racine**. L'agent voit l'arbre (cnq) **et** récupère les contenus réels sous la racine exacte (v1m). Le `fetch_file` built-in n'est donc injecté **que** si `--context-dir` est fourni (sa racine).

## 3. Périmètre

**Dans `v1m`** :
1. `core/sandbox.py` (nouveau) : `Sandbox` (racine + `writable`), `SandboxViolation`, path jail, `read_text` / `write_text` jalés.
2. `core/fs_tools.py` (nouveau) : `make_fetch_file_tool(sandbox, max_chars) -> ToolDef` (closure sur la sandbox + plafond de taille), `FETCH_FILE_TOOL_NAME = "fetch_file"`.
3. Assemblage du `fetch_file` built-in dans `solve_once` **conditionné à la présence d'une sandbox** (donc d'un `--context-dir`), fusionné par nom au registre du roster (mécanique `_merge_builtins` existante, erd).
4. Champ `sandbox: Sandbox | None = None` sur `RunContext` (forward-looking, parallèle exact à `hitl_callback` ; non consommé par le runtime en V1 — porté pour les tools et les évolutions §7).
5. Wiring CLI : `solve_once` reçoit `context_dir: Path | None` + `fetch_max: int` ; `app.py solve` ajoute l'option `--fetch-max` (défaut 50000 chars, miroir de `--context-max`) et passe `context_dir`. Sandbox read-only (`writable=False`) toujours en `v1m` (aucun flag d'écriture livré).
6. **Plafond de taille `fetch_file`** : refus dur si le fichier dépasse `max_chars` (pas de troncature — cohérent avec le refus dur d'overflow de cnq). Décision §9.
7. **Sample destructif (tests only)** : un `make_write_file_tool(sandbox)` minimal **dans la suite de tests** (ou exposé mais non câblé) pour prouver que `write_text` refuse sur sandbox read-only et réussit sur sandbox writable — atteste le contrat que les futurs tools write/run devront honorer.

**Hors `v1m`** (différé, noté pour la suite) :
- Tools **write / run_command** réels câblés à un run (exigent un flag `--allow-write` + une racine isolée par copie, et touchent au DoD LLM-réel). Le substrat les rend faisables sans réécriture.
- **Intercepteur central** au dispatch de tool (gater des tools roster non-confiance qui n'utiliseraient pas la Sandbox). Cf. §7.
- Racine **copiée/tmp** par run pour les écritures (worktree-like). `v1m` ne fait que jailer la lecture sur la racine source ; la création d'une racine isolée inscriptible vient avec les tools write.
- Quotas (taille/temps), limite de concurrence N runs parallèles (open-flags brainstorm, « à mesurer plus tard »).

## 4. Changements — par module

### 4.1 `src/aaosa/core/sandbox.py` (nouveau) — l'unique porte FS

```python
"""Sandbox (v1m) — isolation FS par run + plancher de non-destruction.

Unique porte d'accès FS pour les tools d'agent (Monde B). Path jail : aucun
chemin ne sort de `root`. Plancher de non-destruction : `writable=False` par
défaut -> toute écriture lève SandboxViolation (enforce par construction, pas
une consigne au prompt). Doctrine reprise de night-guard-destructive-floor.
"""

from dataclasses import dataclass
from pathlib import Path


class SandboxViolation(Exception):
    """Tentative d'accès hors racine, ou écriture sur une sandbox read-only."""


@dataclass(frozen=True)
class Sandbox:
    root: Path            # racine absolue, résolue (realpath)
    writable: bool = False

    @classmethod
    def for_reading(cls, root: Path) -> "Sandbox":
        """Sandbox read-only jalée sur `root` (cas v1m : lecture sous --context-dir)."""
        resolved = Path(root).resolve(strict=True)
        if not resolved.is_dir():
            raise SandboxViolation(f"sandbox root is not a directory: {root}")
        return cls(root=resolved, writable=False)

    def resolve(self, rel_path: str) -> Path:
        """Résout `rel_path` SOUS la racine. Lève SandboxViolation sur toute
        évasion (chemin absolu, traversée `..`, symlink pointant hors racine)."""
        candidate = (self.root / rel_path).resolve()  # résout aussi les symlinks
        try:
            candidate.relative_to(self.root)
        except ValueError:
            raise SandboxViolation(f"path escapes sandbox root: {rel_path!r}")
        return candidate

    def read_text(self, rel_path: str) -> str:
        """Lecture jalée. Lève SandboxViolation (évasion) / FileNotFoundError /
        IsADirectoryError, propagées au tool qui les traduit en str claire."""
        return self.resolve(rel_path).read_text(encoding="utf-8")

    def write_text(self, rel_path: str, data: str) -> None:
        """Écriture jalée ET gardée par le plancher : lève SandboxViolation si
        `not writable`. C'est le coeur du plancher de non-destruction."""
        if not self.writable:
            raise SandboxViolation("sandbox is read-only: writes are disabled")
        target = self.resolve(rel_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(data, encoding="utf-8")
```

Invariants :
- `resolve` résout les symlinks (`Path.resolve()`) **avant** le test `relative_to` → un symlink interne pointant dehors est rejeté.
- `root` est résolu une fois (`for_reading`) → pas de TOCTOU sur la racine elle-même.
- Aucune dépendance à git ni à `cli/context_dir.py` (Sandbox est pure, réutilisable hors solve).

### 4.2 `src/aaosa/core/fs_tools.py` (nouveau) — `fetch_file` réel

```python
"""Tools FS framework (v1m). fetch_file réel, jalé par une Sandbox closurée.

Built-in injecté UNIQUEMENT quand une sandbox existe (donc --context-dir
fourni). La racine de lecture = la racine de la sandbox = le --context-dir
dont cnq a déjà injecté l'arborescence. Plafond de taille (refus dur, pas de
troncature) pour ne pas noyer le thread tool-use.
"""

from aaosa.core.sandbox import Sandbox, SandboxViolation
from aaosa.core.tool import ToolDef

FETCH_FILE_TOOL_NAME = "fetch_file"
DEFAULT_FETCH_MAX_CHARS = 50_000


def make_fetch_file_tool(sandbox: Sandbox, max_chars: int = DEFAULT_FETCH_MAX_CHARS) -> ToolDef:
    """ToolDef fetch_file jalé sur `sandbox`, plafonné à `max_chars`. fn
    retourne toujours str : contenu, ou message d'erreur clair (jamais
    d'exception qui casse la boucle tool-use de execute())."""

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
```

Décisions §9 incorporées : binaire/non-UTF-8 → message clair `[cannot read ...: UnicodeDecodeError]` (pas de mode bytes) ; dépassement de `max_chars` → **refus dur** (pas de troncature).

> Note `ToolDef` : **inchangé** (pas de champ `destructive`). Le plancher vit dans la Sandbox, pas dans une métadonnée de tool — cohérent avec §2.3.

### 4.3 `src/aaosa/runtime/context.py` — champ `sandbox`

Ajouter un champ optionnel, strictement parallèle à `hitl_callback` :

```python
from aaosa.core.sandbox import Sandbox
# ...
@dataclass(frozen=True)
class RunContext:
    # ... champs existants ...
    hitl_callback: "HITLCallback | None" = None
    sandbox: "Sandbox | None" = None        # v1m — racine FS jalée du run
    roles: RoleProviders = field(default_factory=RoleProviders)
```

Non consommé par le runtime en V1 (les tools portent la sandbox via closure). Porté pour l'observabilité/évolutions §7 et pour rester l'objet de vérité du run.

### 4.4 `src/aaosa/cli/solve_runs.py` — assemblage conditionnel + wiring

```python
from aaosa.core.fs_tools import (
    DEFAULT_FETCH_MAX_CHARS, FETCH_FILE_TOOL_NAME, make_fetch_file_tool,
)
from aaosa.core.sandbox import Sandbox

def solve_once(
    roster_dirs: list[Path],
    task_text: str,
    context: str | None,
    runs_root: Path,
    provider_name: str = "ollama",
    roles_path: Path | None = None,
    hitl_callback: HITLCallback | None = None,
    context_dir: Path | None = None,          # v1m — racine de la sandbox de lecture
    fetch_max: int = DEFAULT_FETCH_MAX_CHARS,  # v1m — plafond de fetch_file
) -> SolveOutcome:
    builtin_tools = build_builtin_tools(hitl_callback)   # ask_human (ipv)
    sandbox = Sandbox.for_reading(context_dir) if context_dir is not None else None
    if sandbox is not None:
        builtin_tools[FETCH_FILE_TOOL_NAME] = make_fetch_file_tool(sandbox, fetch_max)
    agents = load_rosters(roster_dirs, builtin_tools=builtin_tools)
    # ... suite inchangée ...
    # RunContext(..., hitl_callback=hitl_callback, sandbox=sandbox, roles=roles)
```

- `Sandbox.for_reading` lève `SandboxViolation` si la racine n'existe pas / n'est pas un dossier → traduit en `Exit 1` côté `app.py` (même classe d'erreur de chargement que les autres).
- **Pas de collision** : `fetch_file` est un nom neuf, distinct du stub `read_file` de la démo. Un roster reste libre de définir son propre `read_file` sans heurter le built-in.

### 4.5 `src/aaosa/cli/app.py` — passer `context_dir` à `solve_once`

`app.py` construit déjà `tree = build_context_tree(context_dir)` (cnq) ; il ajoute l'option `--fetch-max` et passe le `context_dir` brut + `fetch_max` :

```python
fetch_max: int = typer.Option(
    50000, "--fetch-max",
    help="Refus dur si un fichier fetché dépasse (caractères)",
),
# ...
outcome = solve_once(
    roster, task, context, runs_root, provider,
    roles_path=roles,
    hitl_callback=_stdin_hitl if hitl else None,
    context_dir=context_dir,          # v1m
    fetch_max=fetch_max,              # v1m
)
```

Et il faut attraper `SandboxViolation` dans le bloc `except` du `solve` (Exit 1, message clair).

## 5. Invariants & séparations (à ne pas briser)

- **Runtime synchrone intouché** (comme ipv) : `tool.py`, `agent.py`, `runner.py`, `dispatch.py` = 0 diff. Toute la sécurité est dans `Sandbox` + l'assemblage des tools.
- **Rétrocompat stricte** : `sandbox=None` ⇒ aucun `fetch_file` built-in, runtime identique à aujourd'hui. La démo incident (stub `read_file` dans `demo/tools.py`) reste verte et **intouchée** : `fetch_file` est un nom distinct, pas de collision.
- **Tools retournent toujours `str`** : `fetch_file` traduit toute exception et tout dépassement de taille en message `[...]` ; il ne lève jamais dans la boucle tool-use.
- **Enforce > instruct** : la non-destruction est structurelle (la Sandbox refuse), jamais une simple phrase dans le system prompt.
- **Sandbox pure et découplée** : aucune dépendance à Typer/CLI/git ; testable isolément ; réutilisable par tout futur invocateur (pas que `solve`).
- **Path jail réel** : test obligatoire d'évasion par `..`, par chemin absolu, et par **symlink** interne pointant dehors.

## 6. Tests (TDD — détail des cas dans le plan)

`tests/core/test_sandbox.py` :
- `read_text` d'un fichier sous la racine → contenu exact.
- `..` / chemin absolu / symlink-vers-dehors → `SandboxViolation`.
- `write_text` sur `writable=False` → `SandboxViolation` (plancher).
- `write_text` sur `writable=True` → écrit, relisible, jalé (un `..` lève toujours).
- `for_reading` sur racine inexistante / fichier → `SandboxViolation`.

`tests/core/test_fs_tools.py` :
- `fetch_file` fn retourne le contenu pour un path valide.
- fichier absent → `[file not found: ...]` ; évasion → `[refused: ...]` ; binaire/non-UTF-8 → `[cannot read ...]` ; jamais d'exception propagée.
- **plafond** : fichier > `max_chars` → `[file too large: ...]` (refus dur, pas de troncature) ; fichier ≤ `max_chars` → contenu complet.
- **sample destructif** : `make_write_file_tool(sandbox_readonly).fn(...)` → string de refus ; `make_write_file_tool(sandbox_writable).fn(...)` → écrit (prouve le contrat futur).

`tests/cli/test_solve_runs.py` (ou existant) :
- `context_dir` fourni → `fetch_file` built-in présent dans les tools fusionnés, jalé sur la racine.
- `context_dir=None` → pas de `fetch_file` built-in (rétrocompat).
- `fetch_max` propagé au tool (un fichier au-dessus est refusé).
- racine inexistante → `SandboxViolation`.

Suite complète verte (1215 actuellement) + nouveaux tests. Backend pur ⇒ **nuit-compatible** (TDD, aucun appel LLM requis pour la DoD).

## 7. Évolutions anticipées (hors v1m, rendues faisables sans réécriture)

- **Tools write/run réels** : `make_write_file_tool` (promu de fixture de test à built-in) / `make_run_command_tool` closurés sur une `Sandbox(writable=True)` créée par **copie isolée** de la source (racine worktree-like). Flag CLI `--allow-write`. Le plancher existant (`write_text` gardé) s'applique tel quel.
- **Intercepteur central** au dispatch (`execute`/`run_task`) pour gater des tools roster **non-confiance** qui contourneraient la Sandbox — utile si AAOSA exécute un jour des rosters non audités. Le champ `RunContext.sandbox` est déjà là pour l'alimenter.
- **Observabilité** : émettre un event (ou un flag sur `ToolCalledEvent`) quand un accès est refusé par la Sandbox, pour rendre les blocages visibles au dashboard.
- **Quotas & concurrence** : taille/temps par tool, limite de runs parallèles (open-flags brainstorm).

## 8. Definition of Done

- `core/sandbox.py` + `core/fs_tools.py` créés ; `RunContext.sandbox` ajouté ; `solve_once`/`app.py` câblés (`--context-dir` → sandbox, `--fetch-max`).
- Tous les cas §6 verts ; suite globale verte (≥ 1215 + nouveaux, 0 régression).
- Démo incident inchangée (run offline toujours vert, stub `read_file` intact — nom distinct de `fetch_file`).
- Rétrocompat prouvée par test (`context_dir=None` ⇒ runtime identique).
- **Nuit-compatible** : DoD = tests verts. La validation LLM-réelle (un agent qui fetch un vrai fichier sous `--context-dir` via le `fetch_file` réel, et un refus d'évasion observé) = **smoke matinal Quentin**, pas la nuit.

## 9. Décisions de la session `/ticket v1m` (2026-06-19)

- **Périmètre** : substrat de sécurité **+ lecteur fs réel** (pas les tools write/run — différés). Le substrat est prouvé contre un destructif d'échantillon (tests).
- **Isolation** : **sandbox dir générique** (racine + path jail), agnostique au git — pas de `git worktree` littéral.
- **Mode** : **spec d'abord** (ce document) → validation Quentin → plan TDD bite-sized → exécution subagent-driven.
- **Encodage/binaires** (Q1) : UTF-8 seul, binaire → message d'erreur clair, **pas** de mode bytes/base64.
- **Plafond de taille** (Q2) : **borné dès v1m** via `--fetch-max` (défaut 50000 chars), refus dur sans troncature (cohérent cnq).
- **Nom du built-in** (Q3) : **`fetch_file`** (pas `read_file`) → évite toute collision avec le stub démo, aucune contrainte sur les rosters.
