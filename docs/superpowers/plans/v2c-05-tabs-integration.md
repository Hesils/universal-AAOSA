# V2c — Épique 05 — Tabs 1/2/3 + intégration finale — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construire les 3 tabs restants (Infra, Agents, Health checks) et câbler les 4 tabs en une app cohérente, après deux corrections backend que le cross-check aval a révélées (courbes ELO Tab 2 cassées multi-run, séries manquantes pour les charts Tab 1).

**Architecture:** Phase 0 corrige la couche data en TDD (fix matching ELO par nom ; enrichissement additif `InfraStats.per_session`). Phase 1 ajoute des helpers charts SVG maison (zéro dépendance, cohérents avec `graph.js`). Phase 2 monte les 3 tabs en vanilla JS, chacun sur le pattern « sélecteur en haut → vue pleine largeur qui se met à jour » (comme Tab 4). Tab 3 réutilise `graph.js`/`modal.js` tels quels (un `GraphModel` par cas, pas de stepping). Phase 3 câble et vérifie.

**Tech Stack:** Python 3.14 / Pydantic 2.13 / Flask 3.1 / pytest 9.0.3 (Phase 0) ; JavaScript ES modules + SVG, aucun build step (Phases 1-3).

---

## Prérequis (NE PAS commencer sans)

1. **Épiques 01→04 implémentées** : couche data, `build_graph`, collectors, API REST, frontend (shell + `graph.js` + `modal.js` + Tab 4). Vérifier : `git log --oneline` montre les commits v2c jusqu'au skin Tab 4.
2. **Au moins un run persisté** : `runs/sessions/<id>/{trace.jsonl,meta.json,agents.json}` existent. Sinon lancer la démo (`.venv\Scripts\python src\aaosa\demo\run_demo.py`, requiert `.env`).
3. Sanity : `.venv\Scripts\python -m dashboard` démarre, `GET /api/infra` renvoie `session_count >= 1`.

## Discipline d'exécution (toutes les tasks)

- **Phase 0 (Python) = TDD strict** : test rouge → impl minimale → test vert. **Garde anti-régression explicite** (demande utilisateur) : chaque task Phase 0 rejoue le fichier de test complet du collector touché avant commit ; Task 8 rejoue toute la suite.
- **Phases 1-3 (JS) hors TDD automatisé** (décision épique + CLAUDE.md projet) : pas de cycle pytest pour le JS. Chaque task se termine par une **vérification navigateur** explicite.
- **Skin minimal, pas de poli** (demande utilisateur) : réutiliser les tokens CSS existants (`--bg-*`, `--text-*`, `--accent`) et les classes `.field*`. Le vrai pass visuel sera un `/impeccable` ultérieur, hors de ce plan. Ne pas peaufiner.
- **Commit après reviews** : l'implémenteur ne commit qu'après spec-review + quality-review. La dernière étape de chaque task donne la commande exacte.
- Lancer l'app : `.venv\Scripts\python -m dashboard` puis `http://localhost:5000`.

## File Structure

| Fichier | Responsabilité | Action |
|---|---|---|
| `dashboard/collectors/agents.py` | `_elo_history` matche par `agent_name` (fix Finding 1) | Modifier |
| `tests/dashboard/test_collectors_agents.py` | test anti-régression matching par nom | Modifier |
| `dashboard/collectors/infra.py` | `SessionInfraPoint` + `InfraStats.per_session` (Finding 2) | Modifier |
| `tests/dashboard/test_collectors_infra.py` | tests `per_session` | Modifier |
| `dashboard/static/js/charts.js` | `lineChart` / `barChart` SVG maison + `PALETTE` | Créer |
| `dashboard/static/js/tabs/infra.js` | Tab 1 : cartes + charts | Créer |
| `dashboard/static/js/tabs/agents.js` | Tab 2 : sélecteur agent → plain view | Créer |
| `dashboard/static/js/tabs/health.js` | Tab 3 : sélecteur run → overview + TestSet + graphe par cas | Créer |
| `dashboard/static/js/app.js` | `MOUNTERS` += infra/agents/health | Modifier |
| `dashboard/static/css/style.css` | styles cards/charts/bars/case-row (minimal, tokens existants) | Modifier |

> `graph.js`, `modal.js`, `api.js` sont **réutilisés tels quels** (aucune modification). `api.js` porte déjà tous les wrappers (`infra`, `agents`, `agent`, `healthChecks`, `healthCheck`, `healthCheckGraph`).

**Commande de test (Windows, toujours le venv) :** `.venv\Scripts\python -m pytest <fichier> -v`
**Commande de lancement :** `.venv\Scripts\python -m dashboard`

---

# PHASE 0 — Corrections data (TDD)

## Task 1 : `_elo_history` matche par `agent_name` (fix Finding 1)

> **Provenance :** deep-dive Épique 05. `_elo_history` filtre les snapshots par `agent_id`, mais `Agent.id = uuid4()` est régénéré à chaque process (`src/aaosa/core/agent.py:16`) et `registry.json` est réécrit avec les ids du run courant. Conséquence : sur plusieurs runs réels, seul le dernier snapshot matche → la courbe ELO (feature phare du Tab 2) s'effondre en un point unique. Le snapshot porte déjà `agent_name` (stable) ; l'invariant CLAUDE.md impose « snapshot matche par agent name, pas UUID ». Le test fixture actuel masque le bug (mêmes ids dans un seul process).

**Files:**
- Modify: `dashboard/collectors/agents.py`
- Test: `tests/dashboard/test_collectors_agents.py`

- [ ] **Step 1 : Écrire le test qui expose le bug**

Ajouter à `tests/dashboard/test_collectors_agents.py` :

```python
def test_elo_history_matches_by_name_not_id(tmp_path):
    # Simule deux runs (process différents) : même agent_name, agent_id distincts.
    from datetime import datetime, timedelta, timezone

    from aaosa.elo.persistence import AgentEloSnapshot, EloSnapshot
    from aaosa.tracing.store import save_agent_registry

    root = tmp_path / "runs"
    root.mkdir()
    save_agent_registry(DEMO_AGENTS, root / "agents" / "registry.json")  # ids du run courant
    snap_dir = root / "elo_snapshots"
    snap_dir.mkdir()
    a0 = DEMO_AGENTS[0]
    base = datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc)
    for i, ts in enumerate([base, base + timedelta(hours=1)]):
        snap = EloSnapshot(
            timestamp=ts,
            agents=[AgentEloSnapshot(
                agent_name=a0.name,            # nom stable
                agent_id=f"stale-uuid-{i}",    # id != registry (run antérieur)
                tags_with_elo={"css": 90 + i},
            )],
        )
        (snap_dir / (ts.strftime("%Y-%m-%dT%H-%M-%S") + ".json")).write_text(
            snap.model_dump_json(), encoding="utf-8"
        )

    view = agent_detail(root, a0.id)
    assert view is not None
    css_series = next((s for s in view.elo_history if s.tag == "css"), None)
    assert css_series is not None and len(css_series.points) == 2  # matché par nom
```

- [ ] **Step 2 : Lancer le test, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_collectors_agents.py::test_elo_history_matches_by_name_not_id -v`
Expected: FAIL — `css_series is None` (les snapshots à id `stale-uuid-*` ne matchent pas `a0.id`).

- [ ] **Step 3 : Matcher par nom**

Dans `dashboard/collectors/agents.py`, modifier `_elo_history` (signature + condition) :

```python
def _elo_history(runs_root: Path, agent_name: str) -> list[TagEloSeries]:
    snap_dir = runs_root / "elo_snapshots"
    if not snap_dir.exists():
        return []
    series: dict[str, list[EloPoint]] = {}
    for f in sorted(snap_dir.glob("*.json")):
        if f.name == "latest.json":
            continue
        snap = EloSnapshot.model_validate_json(f.read_text(encoding="utf-8"))
        for a in snap.agents:
            if a.agent_name != agent_name:  # nom stable, pas l'UUID régénéré (invariant CLAUDE.md)
                continue
            for tag, elo in a.tags_with_elo.items():
                series.setdefault(tag, []).append(EloPoint(timestamp=snap.timestamp, elo=elo))
    return [TagEloSeries(tag=tag, points=pts) for tag, pts in sorted(series.items())]
```

Et dans `agent_detail`, passer le nom :

```python
        elo_history=_elo_history(runs_root, entry.name),
```

- [ ] **Step 4 : Lancer toute la suite agents (garde anti-régression)**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_collectors_agents.py -v`
Expected: PASS — le nouveau test + `test_agent_detail` (le fixture a `agent_name == registry name`, donc le match par nom résout les 2 points comme avant) + `test_list_agents` + `test_agent_detail_not_found`.

- [ ] **Step 5 : Commit (après reviews)**

```bash
git add dashboard/collectors/agents.py tests/dashboard/test_collectors_agents.py
git commit -m "fix(v2c): historique ELO matche par agent_name (Tab 2 courbes multi-run)"
```

---

## Task 2 : `InfraStats.per_session` (enrichissement additif — Finding 2)

> **Provenance :** deep-dive Épique 05. Le Tab 1 annonce 4 charts ; seul `pass_rate_over_time` est une série. `runs/session`, `tokens in/out`, `latence dans le temps` n'ont que des agrégats globaux. Un `per_session` additif les débloque d'un coup. **Additif/backward compat** : champ calculé dans la boucle sessions existante, aucune assertion `InfraStats` actuelle modifiée (`test_infra_counts` reste vert sans changement).

**Files:**
- Modify: `dashboard/collectors/infra.py`
- Test: `tests/dashboard/test_collectors_infra.py`

- [ ] **Step 1 : Écrire les tests**

Ajouter à `tests/dashboard/test_collectors_infra.py` :

```python
def test_infra_per_session(runs_root):
    stats = collect(runs_root)
    assert len(stats.per_session) == 1
    p = stats.per_session[0]
    assert p.run_count == 1
    assert p.tokens_in == 120
    assert p.tokens_out == 80
    assert p.latency_mean == 350.0


def test_infra_per_session_empty(tmp_path):
    assert collect(tmp_path).per_session == []
```

- [ ] **Step 2 : Lancer les tests, vérifier l'échec**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_collectors_infra.py::test_infra_per_session -v`
Expected: FAIL — `AttributeError: 'InfraStats' object has no attribute 'per_session'`.

- [ ] **Step 3 : Ajouter le modèle + le champ + le calcul**

Dans `dashboard/collectors/infra.py`, ajouter le modèle (après `PassRatePoint`) :

```python
class SessionInfraPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    started_at: datetime
    run_count: int
    tokens_in: int
    tokens_out: int
    latency_mean: float | None
```

Ajouter le champ à `InfraStats` (dernier champ) :

```python
    pass_rate_over_time: list[PassRatePoint]
    per_session: list[SessionInfraPoint]
```

Remplacer le corps de `collect` par cette version (ajoute les accumulateurs par session) :

```python
def collect(runs_root: Path) -> InfraStats:
    session_count = task_count = run_count = 0
    tokens_in = tokens_out = 0
    latencies: list[float] = []
    qa_total = qa_pass = 0
    pass_rate_over_time: list[PassRatePoint] = []
    per_session: list[SessionInfraPoint] = []
    agent_ids: set[str] = set()

    sdir = runs_root / "sessions"
    if sdir.exists():
        for d in sorted(sdir.iterdir()):
            meta_path, trace_path = d / "meta.json", d / "trace.jsonl"
            if not meta_path.exists() or not trace_path.exists():
                continue
            session_count += 1
            meta = SessionMeta.model_validate_json(meta_path.read_text(encoding="utf-8"))
            task_count += len(meta.tasks)
            agent_ids.update(meta.agent_ids)

            s_run_count = s_tokens_in = s_tokens_out = 0
            s_latencies: list[float] = []
            s_qa_total = s_qa_pass = 0
            for e in load_trace(trace_path):
                if isinstance(e, ExecutedEvent):
                    run_count += 1
                    s_run_count += 1
                    if e.llm_metadata is not None:  # nullable -> skip si absent (S5)
                        tokens_in += e.llm_metadata.tokens_in
                        tokens_out += e.llm_metadata.tokens_out
                        latencies.append(e.llm_metadata.latency_ms)
                        s_tokens_in += e.llm_metadata.tokens_in
                        s_tokens_out += e.llm_metadata.tokens_out
                        s_latencies.append(e.llm_metadata.latency_ms)
                elif isinstance(e, QAEvaluatedEvent):
                    s_qa_total += 1
                    if e.success:
                        s_qa_pass += 1
            qa_total += s_qa_total
            qa_pass += s_qa_pass
            if s_qa_total > 0:
                pass_rate_over_time.append(PassRatePoint(timestamp=meta.started_at, pass_rate=s_qa_pass / s_qa_total))
            per_session.append(SessionInfraPoint(
                session_id=meta.session_id,
                started_at=meta.started_at,
                run_count=s_run_count,
                tokens_in=s_tokens_in,
                tokens_out=s_tokens_out,
                latency_mean=(sum(s_latencies) / len(s_latencies)) if s_latencies else None,
            ))

    pass_rate_over_time.sort(key=lambda p: p.timestamp)
    per_session.sort(key=lambda p: p.started_at)

    reg_path = runs_root / "agents" / "registry.json"
    if reg_path.exists():
        reg = AgentRegistry.model_validate_json(reg_path.read_text(encoding="utf-8"))
        agent_ids.update(e.agent_id for e in reg.agents)

    return InfraStats(
        session_count=session_count,
        task_count=task_count,
        agent_count=len(agent_ids),
        run_count=run_count,
        qa_pass_rate=(qa_pass / qa_total) if qa_total > 0 else None,
        total_tokens_in=tokens_in,
        total_tokens_out=tokens_out,
        latency=LatencyStats(
            count=len(latencies),
            mean_ms=(sum(latencies) / len(latencies)) if latencies else None,
            min_ms=min(latencies) if latencies else None,
            max_ms=max(latencies) if latencies else None,
        ),
        pass_rate_over_time=pass_rate_over_time,
        per_session=per_session,
    )
```

- [ ] **Step 4 : Lancer toute la suite infra + l'API infra (garde anti-régression)**

Run: `.venv\Scripts\python -m pytest tests/dashboard/test_collectors_infra.py tests/dashboard/test_api.py::test_infra_endpoint -v`
Expected: PASS — `test_infra_counts` (inchangé), `test_infra_empty` (inchangé), les 2 nouveaux, et l'endpoint API (le champ additif sérialise sans casser `session_count == 1`).

- [ ] **Step 5 : Commit (après reviews)**

```bash
git add dashboard/collectors/infra.py tests/dashboard/test_collectors_infra.py
git commit -m "feat(v2c): InfraStats.per_session (series runs/tokens/latence par session, additif)"
```

---

# PHASE 1 — Helpers charts SVG maison

## Task 3 : `charts.js` — `lineChart` / `barChart`

> Décision épique (cross-check) : pas de lib externe, helpers SVG maison cohérents avec `graph.js`. Hors TDD auto → vérif navigateur via un harnais temporaire dans `tabs/infra.js` (remplacé en Task 4).

**Files:**
- Create: `dashboard/static/js/charts.js`
- Modify: `dashboard/static/css/style.css`

- [ ] **Step 1 : Créer `charts.js`**

```js
const SVG_NS = "http://www.w3.org/2000/svg";

// Palette partagée (légende des tabs alignée sur l'ordre des séries).
export const PALETTE = ["#10b981", "#a78bfa", "#f59e0b", "#38bdf8", "#f472b6", "#84cc16"];

function el(name, attrs = {}) {
  const e = document.createElementNS(SVG_NS, name);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  return e;
}

function fmt(n) {
  return Number.isInteger(n) ? String(n) : n.toFixed(2);
}

function reset(svg, width, height) {
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  svg.setAttribute("class", "chart");
  svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
}

function empty(svg, width, height) {
  const t = el("text", { x: width / 2, y: height / 2, "text-anchor": "middle", class: "chart-empty" });
  t.textContent = "no data";
  svg.appendChild(t);
}

// series = [{ name, color?, points: [{x:number, y:number}] }]
export function lineChart(svg, series, { width = 520, height = 200, pad = 30 } = {}) {
  reset(svg, width, height);
  const all = series.flatMap(s => s.points);
  if (!all.length) { empty(svg, width, height); return; }

  const xs = all.map(p => p.x), ys = all.map(p => p.y);
  const xMin = Math.min(...xs), xMax = Math.max(...xs);
  const yMin = Math.min(...ys), yMax = Math.max(...ys);
  const sx = x => pad + (xMax === xMin ? 0.5 : (x - xMin) / (xMax - xMin)) * (width - 2 * pad);
  const sy = y => height - pad - (yMax === yMin ? 0.5 : (y - yMin) / (yMax - yMin)) * (height - 2 * pad);

  for (const [val, yy] of [[yMax, yMax], [yMin, yMin]]) {
    const lbl = el("text", { x: 4, y: sy(yy) + 4, class: "chart-axis" });
    lbl.textContent = fmt(val);
    svg.appendChild(lbl);
  }

  series.forEach((s, i) => {
    const color = s.color || PALETTE[i % PALETTE.length];
    if (s.points.length > 1) {
      const pts = s.points.map(p => `${sx(p.x)},${sy(p.y)}`).join(" ");
      svg.appendChild(el("polyline", { points: pts, fill: "none", stroke: color, "stroke-width": 2 }));
    }
    for (const p of s.points) svg.appendChild(el("circle", { cx: sx(p.x), cy: sy(p.y), r: 2.5, fill: color }));
  });
}

// bars = [{ label, value }]
export function barChart(svg, bars, { width = 520, height = 200, pad = 30 } = {}) {
  reset(svg, width, height);
  if (!bars.length) { empty(svg, width, height); return; }

  const max = Math.max(...bars.map(b => b.value), 1);
  const slot = (width - 2 * pad) / bars.length;
  const bw = Math.min(slot * 0.6, 48);
  bars.forEach((b, i) => {
    const x = pad + i * slot + (slot - bw) / 2;
    const h = (b.value / max) * (height - 2 * pad);
    const y = height - pad - h;
    svg.appendChild(el("rect", { x, y, width: bw, height: h, rx: 3, class: "chart-bar" }));
    const val = el("text", { x: x + bw / 2, y: y - 4, "text-anchor": "middle", class: "chart-axis" });
    val.textContent = fmt(b.value);
    svg.appendChild(val);
    const lbl = el("text", { x: x + bw / 2, y: height - pad + 12, "text-anchor": "middle", class: "chart-axis" });
    lbl.textContent = b.label;
    svg.appendChild(lbl);
  });
}
```

- [ ] **Step 2 : Styles charts (minimal, tokens existants)**

Ajouter à `dashboard/static/css/style.css` :

```css
/* ─── Charts ─── */
svg.chart { width: 100%; height: auto; display: block; background: var(--bg-1); border: 1px solid var(--border-0); border-radius: 8px; }
.chart-axis { fill: var(--text-2); font-size: 9px; font-family: "SF Mono", ui-monospace, monospace; }
.chart-empty { fill: var(--text-2); font-size: 11px; }
.chart-bar { fill: var(--accent); }
```

- [ ] **Step 3 : Vérification navigateur (harnais temporaire)**

Créer temporairement `dashboard/static/js/tabs/infra.js` pour vérifier les helpers isolément (remplacé en Task 4), puis brancher `infra` dans `MOUNTERS` (voir Task 7 ; pour ce step, ajouter juste `import { mountInfra } from "./tabs/infra.js";` et `infra: mountInfra` dans `app.js`) :

```js
import { lineChart, barChart } from "../charts.js";

export function mountInfra(panel) {
  panel.innerHTML = `<svg id="t-line"></svg><svg id="t-bar"></svg>`;
  lineChart(panel.querySelector("#t-line"), [
    { name: "a", points: [{ x: 0, y: 1 }, { x: 1, y: 3 }, { x: 2, y: 2 }] },
    { name: "b", points: [{ x: 0, y: 2 }, { x: 1, y: 1 }, { x: 2, y: 4 }] },
  ]);
  barChart(panel.querySelector("#t-bar"), [{ label: "s1", value: 3 }, { label: "s2", value: 5 }, { label: "s3", value: 1 }]);
}
```

Lancer l'app, onglet Infra. Attendu : 2 courbes (émeraude + violet) avec points et labels min/max ; 3 barres violettes avec valeurs au-dessus et labels en bas. Console sans erreur.

- [ ] **Step 4 : Commit (après reviews)**

```bash
git add dashboard/static/js/charts.js dashboard/static/css/style.css dashboard/static/js/app.js dashboard/static/js/tabs/infra.js
git commit -m "feat(v2c): helpers charts SVG maison (lineChart, barChart, palette partagee)"
```

---

# PHASE 2 — Les 3 tabs

## Task 4 : `tabs/infra.js` — cartes + charts (Tab 1)

> Remplace le harnais temporaire par la version finale. Le chart « distribution latence » de la spec est rendu comme **latence moyenne par session** (la latence brute par run n'est pas persistée ; `per_session.latency_mean` est la granularité disponible). Substitution justifiée par les données — notée en self-review.

**Files:**
- Modify: `dashboard/static/js/tabs/infra.js`
- Modify: `dashboard/static/css/style.css`

- [ ] **Step 1 : Version finale de `tabs/infra.js`**

Remplacer intégralement `dashboard/static/js/tabs/infra.js` par :

```js
import { api } from "../api.js";
import { lineChart, barChart } from "../charts.js";

function card(label, value) {
  return `<div class="card"><div class="card-value">${value}</div><div class="card-label">${label}</div></div>`;
}

export async function mountInfra(panel) {
  const s = await api.infra();
  const pct = s.qa_pass_rate == null ? "—" : `${Math.round(s.qa_pass_rate * 100)}%`;
  const lat = s.latency.mean_ms == null ? "—" : `${Math.round(s.latency.mean_ms)} ms`;

  panel.innerHTML = `
    <div class="cards">
      ${card("Sessions", s.session_count)}
      ${card("Runs", s.run_count)}
      ${card("Agents", s.agent_count)}
      ${card("Tasks", s.task_count)}
      ${card("QA pass", pct)}
      ${card("Tokens in", s.total_tokens_in)}
      ${card("Tokens out", s.total_tokens_out)}
      ${card("Latence moy.", lat)}
    </div>
    <div class="charts">
      <figure><figcaption>QA pass rate dans le temps</figcaption><svg data-c="passrate"></svg></figure>
      <figure><figcaption>Runs par session</figcaption><svg data-c="runs"></svg></figure>
      <figure><figcaption>Tokens in / out par session</figcaption><svg data-c="tokens"></svg></figure>
      <figure><figcaption>Latence moyenne par session</figcaption><svg data-c="latency"></svg></figure>
    </div>`;

  const svg = c => panel.querySelector(`svg[data-c="${c}"]`);

  lineChart(svg("passrate"), [{
    name: "pass rate",
    points: s.pass_rate_over_time.map((p, i) => ({ x: i, y: p.pass_rate })),
  }]);

  barChart(svg("runs"), s.per_session.map((p, i) => ({ label: `#${i + 1}`, value: p.run_count })));

  lineChart(svg("tokens"), [
    { name: "in", points: s.per_session.map((p, i) => ({ x: i, y: p.tokens_in })) },
    { name: "out", points: s.per_session.map((p, i) => ({ x: i, y: p.tokens_out })) },
  ]);

  lineChart(svg("latency"), [{
    name: "latency",
    points: s.per_session
      .map((p, i) => ({ x: i, y: p.latency_mean }))
      .filter(pt => pt.y != null),
  }]);
}
```

- [ ] **Step 2 : Styles cartes + grille charts (minimal, tokens existants)**

Ajouter à `dashboard/static/css/style.css` :

```css
/* ─── Cards + charts grid ─── */
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(140px, 1fr)); gap: 12px; margin-bottom: 20px; }
.card { background: var(--bg-1); border: 1px solid var(--border-0); border-radius: 8px; padding: 14px 16px; }
.card-value { font-size: 22px; font-weight: 600; color: var(--text-0); font-variant-numeric: tabular-nums; }
.card-label { font-size: 11px; color: var(--text-2); margin-top: 4px; letter-spacing: 0.03em; }
.charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }
.charts figure { margin: 0; }
.charts figcaption { font-size: 11px; color: var(--text-2); margin-bottom: 6px; letter-spacing: 0.03em; }
```

- [ ] **Step 3 : Vérification navigateur**

Lancer l'app, onglet Infra. Attendu :
- 8 cartes chiffrées (sessions/runs/agents/tasks/QA pass/tokens in/out/latence).
- 4 charts : pass rate (line), runs/session (bars), tokens in/out (2 séries line), latence/session (line). « no data » lisible si une série est vide (ex. une seule session → courbes à 1 point).
- Console sans erreur.

- [ ] **Step 4 : Commit (après reviews)**

```bash
git add dashboard/static/js/tabs/infra.js dashboard/static/css/style.css
git commit -m "feat(v2c): Tab 1 Infra (8 cartes + 4 charts depuis /api/infra)"
```

---

## Task 5 : `tabs/agents.js` — sélecteur agent → plain view (Tab 2)

> Pattern « sélecteur en haut → vue pleine largeur qui se met à jour » (comme Tab 4). **Pas de modale, pas de master-detail.** Réutilise `charts.js` (courbes ELO) + classes `.field*`.

**Files:**
- Create: `dashboard/static/js/tabs/agents.js`
- Modify: `dashboard/static/css/style.css`

- [ ] **Step 1 : Créer `tabs/agents.js`**

```js
import { api } from "../api.js";
import { lineChart, PALETTE } from "../charts.js";

function eloBars(tags) {
  return Object.entries(tags)
    .sort((a, b) => b[1] - a[1])
    .map(([tag, elo]) =>
      `<div class="bar-row">
         <span class="bar-label">${tag}</span>
         <span class="bar-track"><span class="bar-fill" style="width:${elo}%"></span></span>
         <span class="bar-val">${elo}</span>
       </div>`)
    .join("");
}

export async function mountAgents(panel) {
  panel.innerHTML = `
    <div class="toolbar"><select class="agent-select"></select></div>
    <div class="agent-view"></div>`;
  const select = panel.querySelector(".agent-select");
  const view = panel.querySelector(".agent-view");

  const list = await api.agents();
  if (!list.agents.length) { panel.innerHTML = '<p class="placeholder">Aucun agent.</p>'; return; }
  for (const a of list.agents) {
    const opt = document.createElement("option");
    opt.value = a.agent_id;
    opt.textContent = a.name;
    select.appendChild(opt);
  }

  async function load(aid) {
    const d = await api.agent(aid);
    const legend = d.elo_history
      .map((s, i) => `<span class="legend"><i style="background:${PALETTE[i % PALETTE.length]}"></i>${s.tag}</span>`)
      .join("");
    view.innerHTML = `
      <div class="field"><div class="field-label">System prompt</div><div class="field-value">${d.system_prompt}</div></div>
      <div class="field"><div class="field-label">Tags · ELO courant</div><div class="bars">${eloBars(d.tags_with_elo)}</div></div>
      <div class="field"><div class="field-label">Historique ELO par tag</div><div class="legend-row">${legend}</div><svg class="elo-curve"></svg></div>
      <div class="field"><div class="field-label">Activity (cumul tous runs)</div>
        <div class="chips">claims ${d.activity.claims} · wins ${d.activity.wins} · success ${d.activity.successes} · fail ${d.activity.failures}</div></div>`;
    lineChart(view.querySelector(".elo-curve"), d.elo_history.map(s => ({
      name: s.tag,
      points: s.points.map((pt, i) => ({ x: i, y: pt.elo })),
    })));
  }

  select.addEventListener("change", () => load(select.value));
  await load(list.agents[0].agent_id);
}
```

- [ ] **Step 2 : Styles barres + légende (minimal, tokens existants)**

Ajouter à `dashboard/static/css/style.css` :

```css
/* ─── Tab 2 Agents ─── */
.agent-view { display: flex; flex-direction: column; gap: 14px; max-width: 760px; }
.bars { display: flex; flex-direction: column; gap: 6px; }
.bar-row { display: grid; grid-template-columns: 110px 1fr 36px; align-items: center; gap: 10px; font-size: 12px; }
.bar-label { color: var(--text-1); }
.bar-track { background: var(--bg-0); border: 1px solid var(--border-0); border-radius: 4px; height: 12px; overflow: hidden; }
.bar-fill { display: block; height: 100%; background: var(--accent); }
.bar-val { color: var(--text-1); text-align: right; font-variant-numeric: tabular-nums; }
.legend-row { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 6px; }
.legend { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; color: var(--text-2); }
.legend i { width: 9px; height: 9px; border-radius: 2px; display: inline-block; }
.agent-select { background: var(--bg-2); color: var(--text-0); border: 1px solid var(--border-1); border-radius: 6px; padding: 6px 10px; font-size: 13px; cursor: pointer; font-family: inherit; }
```

- [ ] **Step 3 : Brancher `agents` dans `MOUNTERS`**

Dans `dashboard/static/js/app.js`, ajouter l'import et l'entrée (intégration complète en Task 7, mais nécessaire pour vérifier ce tab) :

```js
import { mountAgents } from "./tabs/agents.js";
```

et dans l'objet `MOUNTERS` : `agents: mountAgents,`.

- [ ] **Step 4 : Vérification navigateur**

Lancer l'app, onglet Agents. Attendu :
- Sélecteur listant les 4 agents démo (Frontend/Backend/DevOps/Fullstack).
- Vue : system prompt, barres ELO triées décroissant (largeur ∝ valeur), courbe ELO multi-tags avec légende colorée, ligne activity.
- Changer d'agent met à jour toute la vue. Console sans erreur.
- (Courbes plates/à 1 point si un seul snapshot ELO — lancer la démo ≥2 fois pour des courbes réelles.)

- [ ] **Step 5 : Commit (après reviews)**

```bash
git add dashboard/static/js/tabs/agents.js dashboard/static/css/style.css dashboard/static/js/app.js
git commit -m "feat(v2c): Tab 2 Agents (selecteur + prompt + barres ELO + courbes ELO/tag + activity)"
```

---

## Task 6 : `tabs/health.js` — sélecteur run → overview + TestSet + graphe par cas (Tab 3)

> Réutilise `graph.js` + `modal.js` **tels quels**. Un `GraphModel` par cas, **pas de stepping** (décision #5 : `renderGraph(svg, graph, 0, ...)`). Le sélecteur de cas ne liste que les cas `graphable`. Split train/test = label sur `role` (`fix_target`/`regression_guard`).

**Files:**
- Create: `dashboard/static/js/tabs/health.js`
- Modify: `dashboard/static/css/style.css`

- [ ] **Step 1 : Créer `tabs/health.js`**

```js
import { api } from "../api.js";
import { renderGraph } from "../graph.js";
import { openNodeModal } from "../modal.js";

const ROLE_LABEL = { fix_target: "train · fix_target", regression_guard: "test · regression_guard" };

function evalSummary(spec) {
  const crit = spec.criteria.map(c => c.name + (c.gate ? " [gate]" : "") + ` ×${c.weight}`).join(", ");
  const judge = spec.judge ? ` · judge ${spec.judge.mode} ×${spec.judge.weight}` : "";
  return `seuil ${spec.success_threshold} · ${crit}${judge}`;
}

function pct(x) { return `${Math.round(x * 100)}%`; }

export async function mountHealth(panel) {
  panel.innerHTML = `
    <div class="toolbar"><select class="hc-select"></select></div>
    <div class="hc-overview"></div>
    <div class="hc-testset"></div>
    <div class="toolbar"><span class="hc-case-label">Cas :</span><select class="case-select"></select><span class="hc-passrate chips"></span></div>
    <div class="graph-wrap"><svg></svg></div>`;

  const hcSelect = panel.querySelector(".hc-select");
  const caseSelect = panel.querySelector(".case-select");
  const svg = panel.querySelector(".graph-wrap svg");
  const passrate = panel.querySelector(".hc-passrate");

  const list = await api.healthChecks();
  if (!list.runs.length) { panel.innerHTML = '<p class="placeholder">Aucun health check.</p>'; return; }
  for (const r of list.runs) {
    const opt = document.createElement("option");
    opt.value = r.id;
    opt.textContent = r.id;
    hcSelect.appendChild(opt);
  }

  let detail = null;

  function renderOverview() {
    const quarantine = detail.task_spec_quarantined.length + detail.evaluator_quarantined.length + detail.unattributed.length;
    panel.querySelector(".hc-overview").innerHTML = `
      <div class="cards">
        <div class="card"><div class="card-value">${pct(detail.fix_target_pass_rate)}</div><div class="card-label">fix_target pass</div></div>
        <div class="card"><div class="card-value">${pct(detail.regression_guard_pass_rate)}</div><div class="card-label">regression_guard pass</div></div>
        <div class="card"><div class="card-value">${detail.unstable_cases.length}</div><div class="card-label">unstable</div></div>
        <div class="card"><div class="card-value">${quarantine}</div><div class="card-label">quarantaine</div></div>
      </div>`;
  }

  function renderTestSet() {
    panel.querySelector(".hc-testset").innerHTML =
      `<div class="field-label">TestSet — ${detail.cases.length} cas</div>` +
      detail.cases.map(c => {
        const role = ROLE_LABEL[c.role] || c.role;
        const pr = c.result ? `${c.result.pass_count}/${c.result.n_runs}` : "—";
        return `<div class="case-row${c.graphable ? "" : " case-quarantined"}">
          <span class="case-id">${c.task_id}</span>
          <span class="case-role">${role}</span>
          <span class="case-attr">${c.attribution}</span>
          <span class="case-eval">${evalSummary(c.evaluator_spec)}</span>
          <span class="case-pr">${pr}</span>
        </div>`;
      }).join("");
  }

  function renderCaseOptions() {
    caseSelect.innerHTML = "";
    for (const c of detail.cases.filter(x => x.graphable)) {
      const opt = document.createElement("option");
      opt.value = c.task_id;
      opt.textContent = `${c.task_id} (${c.result.pass_count}/${c.result.n_runs})`;
      caseSelect.appendChild(opt);
    }
  }

  async function loadGraph(taskId) {
    const c = detail.cases.find(x => x.task_id === taskId);
    passrate.textContent = c && c.result ? `pass_rate ${pct(c.result.pass_rate)} (${c.result.pass_count}/${c.result.n_runs})` : "";
    const graph = await api.healthCheckGraph(detail.id, taskId);
    renderGraph(svg, graph, 0, (node, step) => openNodeModal(node, step, detail.agents));
  }

  async function load(rid) {
    detail = await api.healthCheck(rid);
    renderOverview();
    renderTestSet();
    renderCaseOptions();
    if (caseSelect.options.length) {
      await loadGraph(caseSelect.value);
    } else {
      while (svg.firstChild) svg.removeChild(svg.firstChild);
      passrate.textContent = "aucun cas graphable";
    }
  }

  hcSelect.addEventListener("change", () => load(hcSelect.value));
  caseSelect.addEventListener("change", () => loadGraph(caseSelect.value));
  await load(list.runs[0].id);
}
```

- [ ] **Step 2 : Styles TestSet (minimal, tokens existants)**

Ajouter à `dashboard/static/css/style.css` :

```css
/* ─── Tab 3 Health checks ─── */
.hc-select, .case-select { background: var(--bg-2); color: var(--text-0); border: 1px solid var(--border-1); border-radius: 6px; padding: 6px 10px; font-size: 13px; cursor: pointer; font-family: inherit; }
.hc-overview { margin: 14px 0; }
.hc-testset { margin-bottom: 16px; display: flex; flex-direction: column; gap: 4px; }
.case-row { display: grid; grid-template-columns: 1fr 150px 110px 2fr 60px; gap: 10px; align-items: center; padding: 7px 10px; background: var(--bg-1); border: 1px solid var(--border-0); border-radius: 6px; font-size: 11.5px; color: var(--text-1); }
.case-row.case-quarantined { opacity: 0.55; }
.case-id { color: var(--text-0); font-family: "SF Mono", ui-monospace, monospace; }
.case-role { color: var(--accent); }
.case-attr, .case-eval { color: var(--text-2); }
.case-pr { text-align: right; font-variant-numeric: tabular-nums; color: var(--text-1); }
.hc-case-label { color: var(--text-2); font-size: 12px; }
```

- [ ] **Step 3 : Brancher `health` dans `MOUNTERS`**

Dans `dashboard/static/js/app.js`, ajouter :

```js
import { mountHealth } from "./tabs/health.js";
```

et dans `MOUNTERS` : `health: mountHealth,`.

- [ ] **Step 4 : Vérification navigateur**

Lancer l'app, onglet Health checks. Attendu :
- Sélecteur de run ; overview (4 cartes : fix_target/regression_guard pass, unstable, quarantaine).
- TestSet : une ligne par cas avec id, label train/test, attribution, résumé evaluator, pass count ; cas non graphable (quarantaine) estompé.
- Sélecteur de cas (graphable uniquement) → bascule le graphe ; annotation `pass_rate X% (k/n)`.
- Clic sur un nœud du graphe → modale correcte (réutilise `modal.js`). Console sans erreur.

- [ ] **Step 5 : Commit (après reviews)**

```bash
git add dashboard/static/js/tabs/health.js dashboard/static/css/style.css dashboard/static/js/app.js
git commit -m "feat(v2c): Tab 3 Health checks (overview + TestSet + graphe par cas, reuse graph/modal)"
```

---

# PHASE 3 — Intégration + vérification

## Task 7 : Câblage final des 4 tabs

> Les Tasks 4-6 ont déjà ajouté les imports/entrées dans `app.js`. Ce step vérifie l'état final et nettoie le harnais temporaire de la Task 3 si présent.

**Files:**
- Modify: `dashboard/static/js/app.js`

- [ ] **Step 1 : État final de `app.js`**

S'assurer que `dashboard/static/js/app.js` est exactement :

```js
import { mountSessions } from "./tabs/sessions.js";
import { mountInfra } from "./tabs/infra.js";
import { mountAgents } from "./tabs/agents.js";
import { mountHealth } from "./tabs/health.js";

const MOUNTERS = { sessions: mountSessions, infra: mountInfra, agents: mountAgents, health: mountHealth };
const mounted = new Set();

function showTab(name) {
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.toggle("is-active", b.dataset.tab === name));
  document.querySelectorAll(".tab-panel").forEach(p => { p.hidden = p.dataset.tab !== name; });
  const panel = document.querySelector(`.tab-panel[data-tab="${name}"]`);
  if (panel && MOUNTERS[name] && !mounted.has(name)) {
    MOUNTERS[name](panel);
    mounted.add(name);
  }
}

document.querySelectorAll(".tab-btn").forEach(btn => {
  btn.addEventListener("click", () => showTab(btn.dataset.tab));
});

showTab("sessions"); // tab par défaut
```

- [ ] **Step 2 : Vérification navigateur — navigation 4 tabs**

Lancer l'app. Attendu :
- Les 4 boutons basculent leur panneau ; bouton actif suit (soulignement violet).
- Chaque tab monte une fois (lazy) et garde son état au re-clic.
- Aucun placeholder « Épique 05 » résiduel (chaque mounter remplace le contenu du panneau).
- Console sans erreur sur l'ensemble.

- [ ] **Step 3 : Commit (après reviews)**

```bash
git add dashboard/static/js/app.js
git commit -m "feat(v2c): cablage final des 4 tabs (MOUNTERS infra/agents/health/sessions)"
```

---

## Task 8 : Vérification navigateur edge cases + non-régression

**Files:** aucun (vérification ; corrections éventuelles dans les modules concernés)

> Données de couverture : lancer la démo ≥2-3 fois pour des séries/courbes non triviales (`.venv\Scripts\python src\aaosa\demo\run_demo.py`). Un run health check pour le Tab 3 (`.venv\Scripts\python src\aaosa\demo\run_health_check.py`).

- [ ] **Step 1 : Tab 1 sur plusieurs runs** — `runs/session`, `tokens in/out`, `latence/session` montrent ≥2 points/barres ; `pass rate` non vide ; cartes cohérentes.

- [ ] **Step 2 : Tab 2 courbes multi-run** — après ≥2 démos, les courbes ELO ont ≥2 points par tag (valide le fix Task 1) ; barres ELO courant correctes ; changer d'agent met tout à jour.

- [ ] **Step 3 : Tab 3 bascule cas + quarantaine** — sélecteur de cas bascule le graphe + annotation `pass_rate` ; cas quarantaine estompé dans le TestSet et absent du sélecteur ; clic nœud → modale.

- [ ] **Step 4 : Navigation + console propre** — 4 tabs navigables, aucune erreur JS sur le parcours complet.

- [ ] **Step 5 : Non-régression Python (garde Phase 0)**

Run: `.venv\Scripts\python -m pytest -q`
Expected: tout vert (suite existante + nouveaux tests Tasks 1-2), 0 échec.

- [ ] **Step 6 : Imports + artefacts runtime non suivis**

Run: `.venv\Scripts\python -c "import dashboard.app, dashboard.collectors.infra, dashboard.collectors.agents; print('imports ok')"`
Run: `git status --short`
Expected: `imports ok` ; aucun fichier sous `runs/` listé.

- [ ] **Step 7 : Commit final éventuel**

```bash
git add -A
git commit -m "fix(v2c): corrections edge cases tabs 1/2/3 (verif navigateur)"
```

> Si aucune correction n'a été nécessaire, ne rien committer ici.

---

## Self-review (effectuée à l'écriture)

**Couverture spec (Section 3 — Tabs 1/2/3 + épique 05) :**
- Tab 1 cartes (sessions/runs/agents/tasks/QA%/tokens/latence) → Task 4 (8 cartes depuis `InfraStats`) ✓.
- Tab 1 charts : pass rate dans le temps (`pass_rate_over_time`), runs/session + tokens in/out (`per_session`, Task 2) → Task 4 ✓. **Distribution latence** rendue comme **latence moyenne/session** (latence brute par run non persistée) — substitution justifiée par les données disponibles, notée ici.
- Tab 2 prompt + tags/ELO barres + **courbes ELO/tag** + activity → Task 5 ; courbes correctes multi-run grâce au fix matching par nom (Task 1) ✓. Modèle « sélecteur → plain view » (pas de modale, décision utilisateur) ✓.
- Tab 3 overview + TestSet (split `role` train/test, evaluator + attribution) + graphe sélecteur de cas + `pass_rate` → Task 6 ✓. Réutilise `graph.js`/`modal.js`, pas de stepping (décision #5) ✓.
- Intégration 4 tabs → Task 7 (`MOUNTERS` complet) ✓.
- Skin minimal tokens existants, poli reporté à `/impeccable` (demande utilisateur) — pas de task de polish ✓.

**Findings du deep-dive traités :**
- Finding 1 (courbes ELO cassées multi-run) → Task 1, fix chirurgical + test anti-régression exposant le bug ✓.
- Finding 2 (séries Tab 1 manquantes) → Task 2, `per_session` additif + garde anti-régression explicite (Step 4 rejoue infra + API) ✓.

**Cohérence des types (collectors + API, `model_dump(by_alias=True)`) :**
- `api.infra()` → `InfraStats{session_count, run_count, agent_count, task_count, qa_pass_rate, total_tokens_in/out, latency{mean_ms}, pass_rate_over_time[{pass_rate}], per_session[{run_count, tokens_in, tokens_out, latency_mean}]}` consommés tels quels (Task 4) ✓.
- `api.agents()` → `{agents:[{agent_id, name, tags_with_elo}]}` ; `api.agent(id)` → `{system_prompt, tags_with_elo, elo_history:[{tag, points:[{elo}]}], activity:{claims, wins, successes, failures}}` (Task 5) ✓.
- `api.healthChecks()` → `{runs:[{id}]}` ; `api.healthCheck(id)` → `{id, fix_target_pass_rate, regression_guard_pass_rate, unstable_cases[], task_spec_quarantined[], evaluator_quarantined[], unattributed[], cases:[{task_id, role, attribution, evaluator_spec{criteria[{name,gate,weight}], judge{mode,weight}|null, success_threshold}, graphable, result{pass_rate,pass_count,n_runs}|null}], agents}` ; `api.healthCheckGraph(id, taskId)` → `GraphModel` (Task 6) ✓.
- `renderGraph(svg, graph, 0, onNodeClick)` + `openNodeModal(node, step, runAgents=detail.agents)` : signatures inchangées (Épique 04), réutilisées sans modification ✓.
- `charts.js` : `lineChart(svg, series=[{name, points:[{x,y}]}])`, `barChart(svg, bars=[{label,value}])`, `PALETTE` exporté pour aligner légende (Task 5) ↔ couleurs des séries ✓.

**Note d'exécution :** Task 3 utilise un harnais temporaire dans `tabs/infra.js`, remplacé par la version finale en Task 4 — chaque task reste vérifiable au navigateur isolément. Les imports `app.js` sont ajoutés au fil des Tasks 4-6 puis figés en Task 7. Pas de placeholder, pas de référence à une fonction non définie.
```
