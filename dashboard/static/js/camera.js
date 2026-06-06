// camera.js — caméra viewBox du graphe Sessions : zoom molette ancré au curseur,
// drag pan, follow-mode débrayable (auto-centrage ~250ms ease-out sur le jalon actif).
// Aucune lib : transform sur le viewBox SVG. Toute interaction manuelle suspend le follow.
const EASE = t => 1 - Math.pow(1 - t, 4);   // ease-out-quart

export function attachCamera(svg, { onManual } = {}) {
  let content = { width: 1, height: 1 };
  let vb = null;             // {x, y, w, h}
  let follow = true;
  let anim = null;

  const apply = () => svg.setAttribute("viewBox", `${vb.x} ${vb.y} ${vb.w} ${vb.h}`);

  function setContent(width, height) {
    content = { width, height };
    if (vb === null) reset();   // auto-fit au chargement
    else apply();               // re-render : cadrage courant conservé
  }

  function reset() {
    vb = { x: 0, y: 0, w: content.width, h: content.height };
    apply();
  }

  function svgPoint(ev) {
    const r = svg.getBoundingClientRect();
    return {
      x: vb.x + ((ev.clientX - r.left) / r.width) * vb.w,
      y: vb.y + ((ev.clientY - r.top) / r.height) * vb.h,
    };
  }

  function manual() {
    if (anim) { cancelAnimationFrame(anim); anim = null; }
    if (follow) { follow = false; if (onManual) onManual(); }
  }

  svg.addEventListener("wheel", (ev) => {
    ev.preventDefault();
    manual();
    const p = svgPoint(ev);
    const f = ev.deltaY > 0 ? 1.18 : 1 / 1.18;
    const w = Math.min(Math.max(vb.w * f, content.width * 0.08), content.width * 2.5);
    const h = w * (vb.h / vb.w);
    vb = { x: p.x - (p.x - vb.x) * (w / vb.w), y: p.y - (p.y - vb.y) * (h / vb.h), w, h };
    apply();
  }, { passive: false });

  let drag = null;
  svg.addEventListener("pointerdown", (ev) => {
    if (ev.target.closest(".node")) return;   // ne pas voler le clic des nœuds
    drag = { x: ev.clientX, y: ev.clientY, vb: { ...vb } };
    svg.setPointerCapture(ev.pointerId);
  });
  svg.addEventListener("pointermove", (ev) => {
    if (!drag) return;
    manual();
    const r = svg.getBoundingClientRect();
    vb.x = drag.vb.x - (ev.clientX - drag.x) * (vb.w / r.width);
    vb.y = drag.vb.y - (ev.clientY - drag.y) * (vb.h / r.height);
    apply();
  });
  ["pointerup", "pointercancel"].forEach(t => svg.addEventListener(t, () => { drag = null; }));

  function tween(target, ms = 250) {
    if (anim) cancelAnimationFrame(anim);
    const from = { ...vb }, t0 = performance.now();
    const stepFn = (now) => {
      const t = Math.min(1, (now - t0) / ms), k = EASE(t);
      vb = {
        x: from.x + (target.x - from.x) * k, y: from.y + (target.y - from.y) * k,
        w: from.w + (target.w - from.w) * k, h: from.h + (target.h - from.h) * k,
      };
      apply();
      anim = t < 1 ? requestAnimationFrame(stepFn) : null;
    };
    anim = requestAnimationFrame(stepFn);
  }

  function focusOn(bbox, { margin = 110 } = {}) {
    if (!follow || !bbox || vb === null) return;
    const ratio = vb.h / vb.w;
    let w = Math.max(bbox.w + margin * 2, content.width * 0.32);
    let h = Math.max(bbox.h + margin * 2, w * ratio);
    if (h / w > ratio) w = h / ratio; else h = w * ratio;
    tween({ x: bbox.x + bbox.w / 2 - w / 2, y: bbox.y + bbox.h / 2 - h / 2, w, h });
  }

  function setFollow(v) {
    follow = v;
  }

  return { setContent, reset, focusOn, setFollow, isFollowing: () => follow };
}
