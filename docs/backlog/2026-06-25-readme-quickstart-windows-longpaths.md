# Backlog — Quickstart README : `git clone` échoue à froid sous Windows (`Filename too long`)

**Découvert** : 2026-06-25, validation à froid du quickstart README (ticket 28d, DoD k99 §5).
**Constat** : reproductible, bloquant pour un nouvel arrivant **Windows**. Un `git clone https://github.com/Hesils/universal-AAOSA.git` propre échoue au checkout :

```
error: unable to create file docs/superpowers/specs/2026-06-06-v3-demo-phase1-observabilite-serie-d-design.md: Filename too long
fatal: unable to checkout working tree
warning: Clone succeeded, but checkout failed.
```

La démo elle-même est saine : `uv sync` → `.env` → `uv run aaosa run` tourne end-to-end (verdict `success`, chaîne claiming→execute→evaluate→ELO + émergence V3) **une fois le checkout réussi**. Le seul accroc est le clone.

## Diagnostic

- Cause : limite Windows `MAX_PATH` (260) sur le chemin complet `<racine clone>\docs\superpowers\specs\<nom long>.md`. Le coupable principal est le nom de spec le plus long combiné à la profondeur `docs/superpowers/specs/` (ex. `2026-06-06-v3-demo-phase1-observabilite-serie-d-design.md`).
- Contournement validé : `git clone -c core.longpaths=true https://github.com/Hesils/universal-AAOSA.git` (checkout OK, démo nominale ensuite).
- macOS/Linux non concernés.

## Fix proposé

Trancher entre (non exclusifs) :

- **(a) — recommandé, peu invasif** : note Windows dans le quickstart README. Soit `git config --global core.longpaths true` avant clone, soit cloner avec `-c core.longpaths=true`. Une ou deux lignes sous le bloc `git clone`.
- **(b) — corrige la cause** : raccourcir les noms de fichiers les plus longs sous `docs/superpowers/specs/` (touche l'historique de naming des specs).
- **(c)** : (a) + (b).

## Critères d'acceptation

- [ ] Quickstart README mentionne le cas Windows (option a), OU noms de specs raccourcis sous le seuil (option b).
- [ ] Vérifié : `git clone` propre réussit à froid sous Windows en suivant le README à la lettre (sans flag manuel implicite).
- [ ] Le reste du quickstart (`uv sync` → `aaosa run`) reste inchangé.

## Pointeurs

- README : section `## Quickstart` (bloc `git clone`).
- Fichier déclencheur : `docs/superpowers/specs/2026-06-06-v3-demo-phase1-observabilite-serie-d-design.md` (et voisins longs du même dossier).
- Contexte : ticket 28d, spec hygiène `docs/superpowers/specs/2026-06-24-hygiene-prod-grade-design.md` §5.
