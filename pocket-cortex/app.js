(() => {
  "use strict";

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("./sw.js").catch(() => {});
    });
  }

  /* ============================================================
     SCREEN 1 — AWAKENING
     ============================================================ */

  const awakening = document.getElementById("awakening");
  const introDelay = reducedMotion ? 500 : 3200;
  setTimeout(() => {
    awakening.classList.add("aw-hide");
  }, introDelay);

  /* ============================================================
     CONSTELLATION DATA
     ============================================================ */

  const CENTER = { x: 150, y: 150 };

  const NODES = [
    { id: "create",   label: "CREATE",   angle: -152, radius: 74 },
    { id: "analyze",  label: "ANALYZE",  angle: -98,  radius: 84 },
    { id: "discover", label: "DISCOVER", angle: -38,  radius: 78 },
    { id: "learn",    label: "LEARN",    angle: 14,   radius: 81 },
    { id: "design",   label: "DESIGN",   angle: 64,   radius: 72 },
    { id: "explain",  label: "EXPLAIN",  angle: 124,  radius: 83 },
    { id: "execute",  label: "EXECUTE",  angle: 178,  radius: 76 },
  ];

  const KEYWORD_MAP = {
    learn:    ["learn", "teach", "understand", "study", "explain to me", "how does", "what is", "curious", "tutorial"],
    explain:  ["explain", "clarify", "why", "meaning", "define", "breakdown", "walk me through", "understand"],
    analyze:  ["analyze", "solve", "problem", "evaluate", "compare", "diagnose", "investigate", "review", "assess", "debug"],
    discover: ["discover", "find", "search", "explore", "research", "identify", "uncover", "solve"],
    create:   ["create", "build", "make", "write", "generate", "compose", "draft", "produce"],
    design:   ["design", "image", "visual", "layout", "art", "style", "aesthetic", "mockup", "picture"],
    execute:  ["execute", "run", "do it", "solve", "perform", "automate", "ship", "deploy", "finish"],
  };

  function toXY(angleDeg, radius) {
    const rad = (angleDeg * Math.PI) / 180;
    return { x: CENTER.x + radius * Math.cos(rad), y: CENTER.y + radius * Math.sin(rad) };
  }

  function controlPoint(x1, y1, x2, y2, bend) {
    const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
    const dx = x2 - x1, dy = y2 - y1;
    const len = Math.hypot(dx, dy) || 1;
    const nx = -dy / len, ny = dx / len;
    return { x: mx + nx * bend, y: my + ny * bend };
  }

  function bezierPoint(t, p0, p1, p2) {
    const it = 1 - t;
    return {
      x: it * it * p0.x + 2 * it * t * p1.x + t * t * p2.x,
      y: it * it * p0.y + 2 * it * t * p1.y + t * t * p2.y,
    };
  }

  const svgNS = "http://www.w3.org/2000/svg";
  const el = (tag, attrs = {}) => {
    const node = document.createElementNS(svgNS, tag);
    for (const k in attrs) node.setAttribute(k, attrs[k]);
    return node;
  };

  const linksGroup = document.getElementById("links-group");
  const nodesGroup = document.getElementById("nodes-group");
  const secondaryGroup = document.getElementById("secondary-nodes");
  const pulseGroup = document.getElementById("pulse-group");
  const coreGroup = document.getElementById("core-group");

  const registry = {};

  NODES.forEach((n, i) => {
    const pos = toXY(n.angle, n.radius);
    const bend = (i % 2 === 0 ? 1 : -1) * (16 + (i % 3) * 7);
    const cp = controlPoint(CENTER.x, CENTER.y, pos.x, pos.y, bend);

    const path = el("path", {
      d: `M ${CENTER.x} ${CENTER.y} Q ${cp.x} ${cp.y} ${pos.x} ${pos.y}`,
      class: "link-path",
      id: `link-${n.id}`,
    });
    linksGroup.appendChild(path);

    const g = el("g", { class: "node-group", id: `node-${n.id}`, transform: `translate(${pos.x},${pos.y})` });
    g.appendChild(el("circle", { class: "node-halo", r: 9 }));
    g.appendChild(el("circle", { class: "node-dot", r: 4.2 }));
    const label = el("text", { class: "node-label", y: pos.y < CENTER.y ? -9 : 13 });
    label.textContent = n.label;
    g.appendChild(label);
    nodesGroup.appendChild(g);

    registry[n.id] = { def: n, pos, cp, pathEl: path, groupEl: g };
  });

  // secondary decorative nodes
  for (let i = 0; i < 9; i++) {
    const angle = i * 41 + 17;
    const radius = 52 + ((i % 3) * 24);
    const pos = toXY(angle, radius);
    const dot = el("circle", {
      class: "secondary-node",
      cx: pos.x, cy: pos.y, r: 0.9 + (i % 3) * 0.4,
      style: `animation-delay:${(i * 0.4).toFixed(1)}s`,
    });
    secondaryGroup.appendChild(dot);
  }

  const constellationSvg = document.getElementById("constellation");

  function setNodeActive(id, active) {
    const rec = registry[id];
    if (!rec) return;
    rec.groupEl.classList.toggle("node-active", active);
    rec.pathEl.classList.toggle("link-active", active);
  }

  function setRoutingActive(active) {
    constellationSvg.classList.toggle("routing-active", active);
  }

  function clearAllActive() {
    Object.keys(registry).forEach((id) => setNodeActive(id, false));
  }

  function firePulse(id, duration = 900) {
    const rec = registry[id];
    if (!rec || reducedMotion) return;
    const dot = el("circle", { class: "pulse-dot", r: 2.4 });
    pulseGroup.appendChild(dot);
    const start = performance.now();
    function step(now) {
      const t = Math.min(1, (now - start) / duration);
      const p = bezierPoint(t, CENTER, rec.cp, rec.pos);
      dot.setAttribute("cx", p.x);
      dot.setAttribute("cy", p.y);
      if (t < 1) requestAnimationFrame(step);
      else dot.remove();
    }
    requestAnimationFrame(step);
  }

  /* ambient signal pulses */
  let ambientTimer = null;
  function scheduleAmbientPulse() {
    if (reducedMotion) return;
    const delay = 4200 + Math.random() * 3200;
    ambientTimer = setTimeout(() => {
      const ids = Object.keys(registry);
      const id = ids[Math.floor(Math.random() * ids.length)];
      firePulse(id, 1000);
      setNodeActive(id, true);
      setTimeout(() => {
        if (!goalInput.value.trim()) setNodeActive(id, false);
      }, 700);
      scheduleAmbientPulse();
    }, delay);
  }
  scheduleAmbientPulse();

  /* ============================================================
     INTENT ROUTING
     ============================================================ */

  const goalInput = document.getElementById("goal-input");
  const intentReadout = document.getElementById("intent-readout");

  const PHRASE_RULES = [
    { test: (t) => t.includes("teach"), nodes: ["learn", "explain", "analyze"] },
    { test: (t) => t.includes("create") && /image|picture|art|visual|logo/.test(t), nodes: ["create", "design", "discover"] },
    { test: (t) => t.includes("solve") || t.includes("problem"), nodes: ["analyze", "discover", "execute"] },
  ];

  function scoreText(text) {
    const lower = text.toLowerCase();
    const scores = {};
    Object.keys(KEYWORD_MAP).forEach((id) => {
      scores[id] = KEYWORD_MAP[id].reduce((acc, kw) => acc + (lower.includes(kw) ? 1 : 0), 0);
    });
    return scores;
  }

  function matchNodes(text) {
    const lower = text.toLowerCase();
    const rule = PHRASE_RULES.find((r) => r.test(lower));
    if (rule) return rule.nodes;
    const scores = scoreText(lower);
    return Object.keys(scores)
      .filter((id) => scores[id] > 0)
      .sort((a, b) => scores[b] - scores[a])
      .slice(0, 3);
  }

  function applyIntentRouting() {
    const text = goalInput.value.trim();
    clearAllActive();
    if (!text) {
      setRoutingActive(false);
      intentReadout.textContent = " ";
      return;
    }
    const matched = matchNodes(text);

    if (!matched.length) {
      setRoutingActive(false);
      intentReadout.textContent = " ";
      return;
    }
    setRoutingActive(true);
    matched.forEach((id) => {
      setNodeActive(id, true);
      firePulse(id, 750);
    });
    intentReadout.textContent = "→ " + matched.map((id) => registry[id].def.label).join("  ·  ");
  }

  let routingTimer = null;
  goalInput.addEventListener("input", () => {
    clearTimeout(routingTimer);
    routingTimer = setTimeout(applyIntentRouting, 160);
  });

  /* ============================================================
     STATE STRIP (demonstration values)
     ============================================================ */

  const STATE_ITEMS = [
    { label: "KNOWLEDGE",  value: 0.72 },
    { label: "EVIDENCE",   value: 0.58 },
    { label: "CREATIVITY", value: 0.84 },
    { label: "EXECUTION",  value: 0.66 },
    { label: "CLARITY",    value: 0.91 },
  ];

  const stateWrap = document.getElementById("state-strip-items");
  const R = 13;
  const CIRC = 2 * Math.PI * R;

  STATE_ITEMS.forEach((item) => {
    const wrap = document.createElement("div");
    wrap.className = "state-item";
    const svg = document.createElementNS(svgNS, "svg");
    svg.setAttribute("viewBox", "0 0 30 30");
    const bg = el("circle", { class: "state-arc-bg", cx: 15, cy: 15, r: R });
    const fg = el("circle", {
      class: "state-arc-fg", cx: 15, cy: 15, r: R,
      "stroke-dasharray": CIRC.toFixed(2),
      "stroke-dashoffset": CIRC.toFixed(2),
    });
    svg.appendChild(bg);
    svg.appendChild(fg);
    const label = document.createElement("span");
    label.className = "state-item-label";
    label.textContent = item.label;
    wrap.appendChild(svg);
    wrap.appendChild(label);
    stateWrap.appendChild(wrap);

    requestAnimationFrame(() => {
      setTimeout(() => {
        fg.setAttribute("stroke-dashoffset", (CIRC * (1 - item.value)).toFixed(2));
      }, 400);
    });
  });

  /* ============================================================
     CONTROLS: EXPLORE / MISSION / DEMONSTRATE
     ============================================================ */

  const banner = document.getElementById("inline-banner");
  let bannerTimer = null;
  function showBanner(text, duration = 2400) {
    banner.textContent = text;
    banner.classList.add("show");
    clearTimeout(bannerTimer);
    bannerTimer = setTimeout(() => banner.classList.remove("show"), duration);
  }

  document.getElementById("btn-explore").addEventListener("click", () => {
    if (isDemoRunning) return;
    showBanner("SCANNING CAPABILITY FIELD");
    const ids = Object.keys(registry);
    ids.forEach((id, i) => {
      setTimeout(() => {
        firePulse(id, 700);
        setNodeActive(id, true);
        setTimeout(() => setNodeActive(id, !!goalInput.value.trim() && scoreText(goalInput.value)[id] > 0), 600);
      }, i * 130);
    });
    setTimeout(() => goalInput.focus({ preventScroll: true }), ids.length * 130 + 200);
  });

  document.getElementById("btn-mission").addEventListener("click", () => {
    if (isDemoRunning) return;
    showBanner("MISSION SEQUENCING — DEFINE OBJECTIVE ABOVE", 2800);
    goalInput.focus({ preventScroll: true });
  });

  /* ============================================================
     DEMONSTRATE MODE
     ============================================================ */

  const demoOverlay = document.getElementById("demo-overlay");
  const demoLine = document.getElementById("demo-line");
  const stage = document.getElementById("stage");
  const btnDemo = document.getElementById("btn-demonstrate");

  let isDemoRunning = false;
  let demoInterrupted = false;

  function wait(ms) {
    return new Promise((resolve) => {
      if (demoInterrupted) return resolve();
      setTimeout(resolve, reducedMotion ? Math.min(ms, 250) : ms);
    });
  }

  async function showLine(text, holdMs) {
    if (demoInterrupted) return;
    demoLine.textContent = text;
    demoLine.classList.add("show");
    await wait(holdMs);
    demoLine.classList.remove("show");
    await wait(280);
  }

  function typeInto(inputEl, text) {
    return new Promise((resolve) => {
      inputEl.value = "";
      let i = 0;
      const step = () => {
        if (demoInterrupted) return resolve();
        inputEl.value = text.slice(0, i);
        i++;
        if (i <= text.length) setTimeout(step, reducedMotion ? 5 : 32);
        else resolve();
      };
      step();
    });
  }

  function cleanupDemo() {
    if (!isDemoRunning) return;
    isDemoRunning = false;
    demoOverlay.hidden = true;
    demoOverlay.classList.remove("show");
    demoLine.classList.remove("show");
    coreGroup.classList.remove("core--intense");
    Object.values(registry).forEach((rec) => {
      rec.groupEl.classList.remove("node-converge");
      rec.groupEl.style.transform = `translate(${rec.pos.x}px,${rec.pos.y}px)`;
    });
    applyIntentRouting();
    btnDemo.textContent = "DEMONSTRATE";
  }

  function interruptDemo() {
    if (!isDemoRunning) return;
    demoInterrupted = true;
    cleanupDemo();
  }

  stage.addEventListener("pointerdown", (e) => {
    if (isDemoRunning) interruptDemo();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && isDemoRunning) interruptDemo();
  });

  async function runDemo() {
    if (isDemoRunning) return;
    isDemoRunning = true;
    demoInterrupted = false;
    btnDemo.textContent = "RUNNING…";
    clearAllActive();
    setRoutingActive(false);
    goalInput.blur();

    coreGroup.classList.add("core--intense");
    await wait(400);
    if (demoInterrupted) return;

    await typeInto(goalInput, "Teach me something I do not understand.");
    await wait(300);
    if (demoInterrupted) return;

    const target = ["learn", "explain", "analyze"];
    setRoutingActive(true);
    for (const id of target) {
      firePulse(id, 750);
      setNodeActive(id, true);
      await wait(260);
      if (demoInterrupted) return;
    }
    intentReadout.textContent = "→ " + target.map((id) => registry[id].def.label.toUpperCase()).join("  ·  ");

    await wait(700);
    if (demoInterrupted) return;

    // subtle convergence
    target.forEach((id) => {
      const rec = registry[id];
      rec.groupEl.classList.add("node-converge");
      const cx = rec.pos.x + (CENTER.x - rec.pos.x) * 0.22;
      const cy = rec.pos.y + (CENTER.y - rec.pos.y) * 0.22;
      rec.groupEl.style.transform = `translate(${cx}px,${cy}px)`;
    });
    await wait(1100);
    if (demoInterrupted) return;

    demoOverlay.hidden = false;

    await showLine("INTENT IDENTIFIED", 1700);
    if (demoInterrupted) return;
    await showLine("CAPABILITY ROUTE ESTABLISHED", 1700);
    if (demoInterrupted) return;
    await showLine("LEARN  +  EXPLAIN  +  ANALYZE", 1900);
    if (demoInterrupted) return;

    const chain = ["QUESTION", "CONTEXT", "MENTAL MODEL", "EXAMPLE", "UNDERSTANDING"];
    let built = "";
    for (let i = 0; i < chain.length; i++) {
      built = i === 0 ? chain[i] : built + "  →  " + chain[i];
      demoLine.textContent = built;
      demoLine.classList.add("show");
      await wait(1050);
      if (demoInterrupted) return;
    }
    demoLine.classList.remove("show");
    await wait(280);
    if (demoInterrupted) return;

    await showLine("HUMAN INTENT  +  MACHINE CAPABILITY  +  CONTROLLED EXECUTION", 2200);
    if (demoInterrupted) return;
    await showLine("FORGEWORLD", 1800);
    if (demoInterrupted) return;

    cleanupDemo();
  }

  btnDemo.addEventListener("click", runDemo);
})();
