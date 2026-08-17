(() => {
  "use strict";

  const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("./sw.js").catch(() => {});
    });
  }

  /* ============================================================
     API CLIENT — every network call funnels through here so
     offline/failure handling lives in exactly one place.
     ============================================================ */

  const API_BASE = "/api";
  let serverReachable = true;
  let offlineRetryTimer = null;

  const offlineBanner = document.getElementById("offline-banner");

  function setServerReachable(reachable) {
    if (reachable === serverReachable) return;
    serverReachable = reachable;
    offlineBanner.hidden = reachable;
    offlineBanner.classList.toggle("show", !reachable);
    if (!reachable) {
      scheduleReachabilityRetry();
    } else {
      clearTimeout(offlineRetryTimer);
    }
  }

  function scheduleReachabilityRetry() {
    clearTimeout(offlineRetryTimer);
    offlineRetryTimer = setTimeout(async () => {
      try {
        const res = await fetch(`${API_BASE}/health`, { cache: "no-store" });
        if (res.ok) {
          setServerReachable(true);
          return;
        }
      } catch {
        /* still unreachable */
      }
      scheduleReachabilityRetry();
    }, 6000);
  }

  window.addEventListener("online", () => {
    if (!serverReachable) scheduleReachabilityRetry();
  });

  /**
   * Every API call goes through here. Returns { ok, status, data } and
   * NEVER throws -- a network failure or a non-2xx response both come
   * back as ok:false with as much detail as is available, so callers can
   * always show an honest failure state instead of crashing or silently
   * pretending nothing happened.
   */
  async function apiFetch(path, options = {}) {
    let res;
    try {
      res = await fetch(`${API_BASE}${path}`, {
        headers: { "Content-Type": "application/json" },
        ...options,
      });
    } catch (err) {
      setServerReachable(false);
      return { ok: false, status: 0, data: null, networkError: true, error: String(err) };
    }
    setServerReachable(true);
    let data = null;
    try {
      data = await res.json();
    } catch {
      /* empty or non-JSON body */
    }
    return { ok: res.ok, status: res.status, data, networkError: false };
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

  // NOTE: this client-side copy exists ONLY for instant as-you-type visual
  // feedback on the constellation -- recomputing routing over a network
  // round-trip on every keystroke would feel laggy and burn battery/data
  // for no benefit on a phone. The routing decision that actually gets
  // PERSISTED (and the rationale shown in the ROUTE panel) always comes
  // from the server (pocket-cortex/lib/routing.js), which is the single
  // source of truth. If the two ever disagree, the server wins -- see
  // handleGoalSubmit(), which replaces this client guess with the server
  // response as soon as it arrives.

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

  /* ambient signal pulses -- paused while the app is backgrounded, so a
     phone tab sitting behind the lock screen isn't burning CPU/battery
     animating a constellation nobody can see. */
  let ambientTimer = null;
  function scheduleAmbientPulse() {
    if (reducedMotion || document.hidden) return;
    const delay = 4200 + Math.random() * 3200;
    ambientTimer = setTimeout(() => {
      if (document.hidden) return;
      if (state.mode === "ACTIVE" || state.mode === "EDITING") {
        if (state.route.length) {
          const id = state.route[Math.floor(Math.random() * state.route.length)];
          firePulse(id, 1000);
        }
      } else {
        const ids = Object.keys(registry);
        const id = ids[Math.floor(Math.random() * ids.length)];
        firePulse(id, 1000);
        setNodeActive(id, true);
        setTimeout(() => {
          if (!goalInput.value.trim()) setNodeActive(id, false);
        }, 700);
      }
      scheduleAmbientPulse();
    }, delay);
  }

  document.addEventListener("visibilitychange", () => {
    if (document.hidden) {
      clearTimeout(ambientTimer);
    } else {
      scheduleAmbientPulse();
    }
  });

  /* ============================================================
     INTENT ROUTING (client-side preview only -- see note above)
     ============================================================ */

  const goalInput = document.getElementById("goal-input");
  const intentReadout = document.getElementById("intent-readout");

  const PHRASE_RULES = [
    { test: (t) => t.includes("teach"), nodes: ["learn", "explain", "analyze"] },
    { test: (t) => t.includes("create") && /image|picture|art|visual|logo/.test(t), nodes: ["create", "design", "discover"] },
    { test: (t) => t.includes("design") && /interface|screen|layout|\bui\b|workspace/.test(t), nodes: ["create", "design", "discover"] },
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
      intentReadout.textContent = " ";
      return;
    }
    const matched = matchNodes(text);

    if (!matched.length) {
      setRoutingActive(false);
      intentReadout.textContent = " ";
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
     STATE STRIP — truthful indicators
     Before any mission exists, there is nothing to measure, so the
     strip shows neutral placeholders rather than invented numbers.
     ============================================================ */

  const INDICATOR_ORDER = ["knowledge", "evidence", "creativity", "execution", "clarity"];

  const stateWrap = document.getElementById("state-strip-items");
  const R = 13;
  const CIRC = 2 * Math.PI * R;

  const indicatorEls = {};

  INDICATOR_ORDER.forEach((key) => {
    const wrap = document.createElement("div");
    wrap.className = "state-item";
    wrap.setAttribute("tabindex", "0");
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
    label.textContent = key.toUpperCase();
    wrap.appendChild(svg);
    wrap.appendChild(label);
    wrap.title = "No mission yet — nothing to measure.";
    stateWrap.appendChild(wrap);
    indicatorEls[key] = { wrap, fg };
  });

  function renderIndicators(indicators) {
    INDICATOR_ORDER.forEach((key) => {
      const { fg, wrap } = indicatorEls[key];
      const ind = indicators && indicators[key];
      const value = ind ? ind.value : 0;
      requestAnimationFrame(() => {
        fg.setAttribute("stroke-dashoffset", (CIRC * (1 - value)).toFixed(2));
      });
      wrap.title = ind ? `${Math.round(value * 100)}% — ${ind.basis}` : "No mission yet — nothing to measure.";
    });
  }

  renderIndicators(null);

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
     Privacy-safe by construction: everything below is scripted,
     canned text. This function never calls apiFetch/fetch, never
     creates a real mission, and never reads or writes anything the
     server persists. Nothing typed or shown during a demo touches
     pocket-cortex/data/pocket-cortex.db.
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

  stage.addEventListener("pointerdown", () => {
    if (isDemoRunning) interruptDemo();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && isDemoRunning) interruptDemo();
  });

  async function runDemo() {
    if (isDemoRunning || isGoalSubmitting) return;
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
    await showLine("NOTHING IN THIS DEMONSTRATION WAS SAVED", 2000);
    if (demoInterrupted) return;
    await showLine("FORGEWORLD", 1800);
    if (demoInterrupted) return;

    cleanupDemo();
  }

  btnDemo.addEventListener("click", runDemo);

  /* ============================================================
     GOAL SUBMIT — ROUTE (persistent, server-backed)
     ============================================================ */

  const goalForm = document.getElementById("goal-form");
  let isGoalSubmitting = false;
  let shakeTimer = null;

  function shakeAndWarn(formEl) {
    clearTimeout(shakeTimer);
    formEl.classList.remove("shake");
    void formEl.offsetWidth;
    formEl.classList.add("shake");
    shakeTimer = setTimeout(() => formEl.classList.remove("shake"), 420);
    showBanner("ENTER A GOAL TO ROUTE", 1800);
  }

  function autoGrow(textarea) {
    textarea.style.height = "auto";
    textarea.style.height = Math.min(textarea.scrollHeight, 130) + "px";
  }

  function wireEnterSubmit(textarea, formEl) {
    textarea.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        formEl.requestSubmit();
      }
    });
    textarea.addEventListener("input", () => autoGrow(textarea));
  }

  async function handleGoalSubmit(e) {
    if (e) e.preventDefault();
    if (isDemoRunning || isGoalSubmitting) return;

    const text = goalInput.value.trim();
    if (!text) {
      shakeAndWarn(goalForm);
      return;
    }

    isGoalSubmitting = true;
    clearTimeout(routingTimer);

    // Instant local preview while the persistence round-trip is in flight.
    const localGuess = matchNodes(text);
    energizeRoute(localGuess, 800);

    const result = await apiFetch("/missions", { method: "POST", body: JSON.stringify({ goalText: text }) });

    if (!result.ok) {
      isGoalSubmitting = false;
      if (result.networkError || result.status === 0) {
        showBanner("POCKET CORTEX SERVER UNREACHABLE — TRY AGAIN", 3200);
      } else {
        showBanner("COULD NOT CREATE MISSION — TRY AGAIN", 2800);
      }
      return;
    }

    enterActiveMode(result.data);
    isGoalSubmitting = false;
  }

  goalForm.addEventListener("submit", handleGoalSubmit);
  wireEnterSubmit(goalInput, goalForm);

  /* ============================================================
     ACTIVE CORTEX — dynamic workspace, server-backed
     ============================================================ */

  const STAGES = ["INTENT", "ROUTE", "WORK", "REVIEW", "NEXT"];

  const state = {
    mode: "TITLE", // TITLE | ROUTING | ACTIVE | EDITING
    missionId: null,
    goal: "",
    route: [],
    workspace: "work", // work | route | evidence | execute | history
    stage: 0,
    snapshot: null, // last full mission snapshot from the server
  };

  const CAPABILITY_BLURB = {
    create:   "Generates new material from the objective.",
    design:   "Shapes structure, layout, and visual form.",
    discover: "Surfaces options and unexplored directions.",
    learn:    "Builds understanding of the subject.",
    explain:  "Translates the concept into plain terms.",
    analyze:  "Breaks the problem into its parts.",
    execute:  "Moves from decision into action.",
  };

  const workspaceLayer = document.getElementById("workspace-layer");
  const uiLayer = document.querySelector(".ui-layer");
  const awRouteLabel = document.getElementById("aw-route-label");
  const awGoalSummary = document.getElementById("aw-goal-summary");
  const awGoalText = document.getElementById("aw-goal-text");
  const btnEditIntent = document.getElementById("btn-edit-intent");
  const awEditForm = document.getElementById("aw-edit-form");
  const awEditInput = document.getElementById("aw-edit-input");
  const btnEditCancel = document.getElementById("btn-edit-cancel");
  const execStrip = document.getElementById("exec-strip");
  const nextMoveBanner = document.getElementById("next-move-banner");
  const wwTabs = Array.from(document.querySelectorAll(".ww-tab"));
  const panelWork = document.getElementById("panel-work");
  const panelRoute = document.getElementById("panel-route");
  const panelEvidence = document.getElementById("panel-evidence");
  const panelExecute = document.getElementById("panel-execute");
  const panelHistory = document.getElementById("panel-history");
  const btnBack = document.getElementById("btn-back");
  const btnRefine = document.getElementById("btn-refine");
  const btnNext = document.getElementById("btn-next");

  const panels = { work: panelWork, route: panelRoute, evidence: panelEvidence, execute: panelExecute, history: panelHistory };

  function routeKey(route) {
    return route.slice().sort().join("+");
  }

  const ROUTE_TEMPLATES = {
    "create+design+discover": (goal) => ({
      blocks: [
        { label: "INTERPRETED OBJECTIVE", text: goal },
        { label: "CONCEPT DIRECTIONS", list: [
          "A constellation-first layout that keeps routing visible at all times.",
          "A card-based modular layout for scannable workspace content.",
          "A minimal single-column layout optimized for one-hand use.",
        ] },
        { label: "DESIGN OPTIONS", list: [
          "Option A — compact routing header, full-height workspace.",
          "Option B — tabbed workspace with expandable detail panels.",
          "Option C — timeline-style stage progression.",
        ] },
        { label: "EXPANDED DETAIL", expand: true, list: [
          "Motion budget: keep all transitions under ~900ms to stay responsive on-device.",
          "Color budget: one hot accent reserved for the active route only.",
        ] },
      ],
      next: "Select a design option to refine, or expand for detail.",
    }),
    "analyze+explain+learn": (goal) => ({
      blocks: [
        { label: "WHAT ARE WE LEARNING?", text: goal },
        { label: "CURRENT MENTAL MODEL", text: "A baseline understanding assembled from the stated goal — treat this as a starting model, not a conclusion." },
        { label: "EXPLANATION", text: "Illustrative explanation: the system breaks the goal into a concept, a mechanism, and a worked example." },
        { label: "EXAMPLE", text: "Illustrative example: applying the same reasoning to a smaller, concrete case." },
        { label: "DEEPER QUESTION", text: "What part of this still feels uncertain?" },
      ],
      next: "Continue learning to go one level deeper.",
    }),
    "analyze+discover+execute": (goal) => ({
      blocks: [
        { label: "PROBLEM STATEMENT", text: goal },
        { label: "OBSERVATIONS", list: [
          "The objective has a clear actor and a clear outcome.",
          "No blocking constraints were stated.",
        ] },
        { label: "ASSUMPTIONS", list: [
          "The goal reflects the actual priority.",
          "Existing routing logic remains the source of truth.",
        ] },
        { label: "CANDIDATE ACTIONS", list: [
          "Break the goal into two smaller executable steps.",
          "Route directly to execution.",
          "Gather more evidence before acting.",
        ] },
      ],
      next: "Selected next action: break the goal into two executable steps.",
    }),
  };

  function buildGenericTemplate(goal, route) {
    const labels = route.map((id) => registry[id].def.label);
    return {
      blocks: [
        { label: "OBJECTIVE", text: goal },
        { label: "ACTIVE CAPABILITIES", list: labels.length ? labels : ["No capability matched — try different wording."] },
        { label: "WORKING NOTES", list: labels.length
          ? labels.map((l) => `Apply ${l} to advance the objective. (illustrative — not machine-generated content)`)
          : ["No illustrative content available without a matched capability."] },
      ],
      next: "Continue refining with the active capabilities.",
    };
  }

  function getWorkspaceContent(goal, route) {
    const builder = ROUTE_TEMPLATES[routeKey(route)];
    return builder ? builder(goal) : buildGenericTemplate(goal, route);
  }

  function renderWorkBlock(block) {
    const wrap = document.createElement("div");
    wrap.className = "ww-block" + (block.expand ? " ww-expand-extra" : "");
    const h = document.createElement("h3");
    h.textContent = block.label;
    wrap.appendChild(h);
    if (block.text) {
      const p = document.createElement("p");
      p.textContent = block.text;
      wrap.appendChild(p);
    }
    if (block.list) {
      const ul = document.createElement("ul");
      block.list.forEach((item) => {
        const li = document.createElement("li");
        li.textContent = item;
        ul.appendChild(li);
      });
      wrap.appendChild(ul);
    }
    return wrap;
  }

  function updateContextualControls() {
    if (routeKey(state.route) === "create+design+discover") {
      btnRefine.textContent = "EXPAND";
      btnNext.textContent = "EXECUTE";
    } else {
      btnRefine.textContent = "REFINE";
      btnNext.textContent = "NEXT";
    }
  }

  function renderExecStrip() {
    execStrip.innerHTML = "";
    STAGES.forEach((label, i) => {
      const step = document.createElement("span");
      step.className = "exec-step" + (i === state.stage ? " exec-step-current" : i < state.stage ? " exec-step-done" : "");
      step.textContent = label;
      execStrip.appendChild(step);
      if (i < STAGES.length - 1) {
        const sep = document.createElement("span");
        sep.className = "exec-sep";
        sep.textContent = "›";
        execStrip.appendChild(sep);
      }
    });
  }

  function renderNextMoveBanner(nextMove) {
    if (!nextMove) {
      nextMoveBanner.hidden = true;
      return;
    }
    nextMoveBanner.hidden = false;
    nextMoveBanner.innerHTML = "";
    const tag = document.createElement("span");
    tag.className = "nmb-tag";
    tag.textContent = "NEXT RIGHT MOVE";
    const text = document.createElement("p");
    text.className = "nmb-text";
    text.textContent = nextMove.text;
    const basis = document.createElement("p");
    basis.className = "nmb-basis";
    basis.textContent = nextMove.basis;
    nextMoveBanner.appendChild(tag);
    nextMoveBanner.appendChild(text);
    nextMoveBanner.appendChild(basis);
  }

  async function renderHistory() {
    panelHistory.innerHTML = "";
    const loading = document.createElement("p");
    loading.className = "ww-empty";
    loading.textContent = "Loading mission history…";
    panelHistory.appendChild(loading);

    const result = await apiFetch("/missions");
    panelHistory.innerHTML = "";

    if (!result.ok) {
      const p = document.createElement("p");
      p.className = "ww-empty";
      p.textContent = result.networkError
        ? "Pocket Cortex server unreachable — execution memory cannot be read right now."
        : "Could not load mission history.";
      panelHistory.appendChild(p);
      return;
    }

    const missions = result.data.missions || [];
    if (!missions.length) {
      const p = document.createElement("p");
      p.className = "ww-empty";
      p.textContent = "No missions recorded yet.";
      panelHistory.appendChild(p);
      return;
    }

    missions.forEach((m) => {
      const item = document.createElement("button");
      item.type = "button";
      item.className = "ww-history-item";
      const g = document.createElement("span");
      g.className = "ww-history-goal";
      g.textContent = m.goal_text;
      const r = document.createElement("span");
      r.className = "ww-history-route";
      r.textContent = (m.route.map((id) => registry[id]?.def.label).filter(Boolean).join("  ·  ") || "NO ROUTE MATCHED") + `  ·  ${m.stage}`;
      item.appendChild(g);
      item.appendChild(r);
      item.addEventListener("click", async () => {
        const full = await apiFetch(`/missions/${encodeURIComponent(m.id)}`);
        if (full.ok) enterActiveMode(full.data);
      });
      panelHistory.appendChild(item);
    });
  }

  function renderEvidencePanel(snapshot) {
    panelEvidence.innerHTML = "";

    const indicatorTag = document.createElement("p");
    indicatorTag.className = "ww-demo-tag";
    indicatorTag.textContent = "MEASURED, NOT ASSUMED";
    panelEvidence.appendChild(indicatorTag);

    Object.entries(snapshot.indicators).forEach(([key, ind]) => {
      const row = document.createElement("div");
      row.className = "ww-evidence-row";
      const label = document.createElement("span");
      label.textContent = ind.label;
      const bar = document.createElement("div");
      bar.className = "ww-evidence-bar";
      const fill = document.createElement("div");
      fill.className = "ww-evidence-fill";
      fill.style.width = Math.round(ind.value * 100) + "%";
      bar.appendChild(fill);
      row.appendChild(label);
      row.appendChild(bar);
      const basis = document.createElement("p");
      basis.className = "ww-evidence-basis";
      basis.textContent = ind.basis + (ind.isProxy ? " (proxy metric)" : "");
      row.appendChild(basis);
      panelEvidence.appendChild(row);
    });

    const feedbackWrap = document.createElement("div");
    feedbackWrap.className = "ww-feedback";
    const feedbackQ = document.createElement("p");
    feedbackQ.textContent = "Does the current route actually match your intent?";
    feedbackWrap.appendChild(feedbackQ);
    const yesBtn = document.createElement("button");
    yesBtn.type = "button";
    yesBtn.className = "ww-feedback-btn";
    yesBtn.textContent = "YES — RECORD AS OBSERVED";
    const noBtn = document.createElement("button");
    noBtn.type = "button";
    noBtn.className = "ww-feedback-btn ww-feedback-no";
    noBtn.textContent = "NO — RECORD AS OBSERVED";
    async function submitFeedback(matched) {
      yesBtn.disabled = true;
      noBtn.disabled = true;
      const result = await apiFetch(`/missions/${encodeURIComponent(state.missionId)}/evidence`, {
        method: "POST",
        body: JSON.stringify({
          subject: "routing-feedback",
          state: "OBSERVED",
          observation: matched ? "User confirmed the routing matched their intent." : "User indicated the routing did NOT match their intent.",
          source: "user",
        }),
      });
      if (result.ok) {
        showBanner(matched ? "RECORDED — ROUTE CONFIRMED" : "RECORDED — ROUTE FLAGGED", 2000);
        refreshSnapshot();
      } else {
        showBanner("COULD NOT RECORD EVIDENCE", 2000);
        yesBtn.disabled = false;
        noBtn.disabled = false;
      }
    }
    yesBtn.addEventListener("click", () => submitFeedback(true));
    noBtn.addEventListener("click", () => submitFeedback(false));
    feedbackWrap.appendChild(yesBtn);
    feedbackWrap.appendChild(noBtn);
    panelEvidence.appendChild(feedbackWrap);

    if (snapshot.evidence.length) {
      const log = document.createElement("div");
      log.className = "ww-evidence-log";
      const h = document.createElement("h3");
      h.textContent = "EVIDENCE LOG";
      log.appendChild(h);
      snapshot.evidence.slice().reverse().forEach((e) => {
        const row = document.createElement("p");
        row.className = "ww-evidence-log-row";
        row.textContent = `[${e.state}] ${e.observation} — ${e.source}`;
        log.appendChild(row);
      });
      panelEvidence.appendChild(log);
    }
  }

  async function renderExecutePanel(snapshot) {
    panelExecute.innerHTML = "";
    const loading = document.createElement("p");
    loading.className = "ww-empty";
    loading.textContent = "Loading capability/authority gates…";
    panelExecute.appendChild(loading);

    const result = await apiFetch("/capabilities");
    panelExecute.innerHTML = "";

    if (!result.ok) {
      const p = document.createElement("p");
      p.className = "ww-empty";
      p.textContent = "Pocket Cortex server unreachable — gates cannot be read right now.";
      panelExecute.appendChild(p);
      return;
    }

    const tag = document.createElement("p");
    tag.className = "ww-demo-tag";
    tag.textContent = "CAPABILITY ≠ AUTHORITY";
    panelExecute.appendChild(tag);

    result.data.capabilities.forEach(({ name, capability, authority }) => {
      const row = document.createElement("div");
      row.className = "ww-gate-row";

      const head = document.createElement("div");
      head.className = "ww-gate-head";
      const nameEl = document.createElement("span");
      nameEl.className = "ww-gate-name";
      nameEl.textContent = name;
      const capBadge = document.createElement("span");
      capBadge.className = "ww-gate-badge " + (capability.available ? "ww-gate-badge-ok" : "ww-gate-badge-bad");
      capBadge.textContent = "CAPABILITY: " + (capability.available ? "AVAILABLE" : "UNAVAILABLE");
      const authBadge = document.createElement("span");
      const authOk = authority.decision === "ALLOWED" || authority.decision === "ALLOWED_LOCAL" || authority.decision === "ALLOWED_BOUNDED";
      authBadge.className = "ww-gate-badge " + (authOk ? "ww-gate-badge-ok" : authority.decision === "REQUIRES_APPROVAL" ? "ww-gate-badge-warn" : "ww-gate-badge-bad");
      authBadge.textContent = "AUTHORITY: " + authority.decision;
      head.appendChild(nameEl);
      head.appendChild(capBadge);
      head.appendChild(authBadge);
      row.appendChild(head);

      const reason = document.createElement("p");
      reason.className = "ww-gate-reason";
      reason.textContent = authority.reason;
      row.appendChild(reason);

      if (authOk && capability.available) {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "ww-gate-run";
        btn.textContent = "RUN";
        btn.addEventListener("click", async () => {
          btn.disabled = true;
          btn.textContent = "RUNNING…";
          const execResult = await apiFetch(`/missions/${encodeURIComponent(state.missionId)}/execute`, {
            method: "POST",
            body: JSON.stringify({ capability: name }),
          });
          if (execResult.ok) {
            showBanner(`${name} SUCCEEDED`, 2200);
          } else if (execResult.status === 202) {
            showBanner(`${name} AWAITING APPROVAL`, 2200);
          } else {
            showBanner(`${name} BLOCKED`, 2200);
          }
          refreshSnapshot();
        });
        row.appendChild(btn);
      }

      panelExecute.appendChild(row);
    });

    if (snapshot.execution.length) {
      const log = document.createElement("div");
      log.className = "ww-evidence-log";
      const h = document.createElement("h3");
      h.textContent = "EXECUTION MEMORY";
      log.appendChild(h);
      snapshot.execution.slice().reverse().forEach((e) => {
        const row = document.createElement("p");
        row.className = "ww-evidence-log-row";
        row.textContent = `[${e.outcome}] ${e.capability} (${e.authorityDecision})`;
        log.appendChild(row);
      });
      panelExecute.appendChild(log);
    }
  }

  function renderRoutePanel(snapshot) {
    panelRoute.innerHTML = "";
    if (!state.route.length) {
      const p = document.createElement("p");
      p.className = "ww-empty";
      p.textContent = "No capability matched this goal.";
      panelRoute.appendChild(p);
      return;
    }
    state.route.forEach((id) => {
      const row = document.createElement("div");
      row.className = "ww-route-row";
      const name = document.createElement("span");
      name.className = "ww-route-name";
      name.textContent = registry[id]?.def.label || id;
      const desc = document.createElement("span");
      desc.className = "ww-route-desc";
      desc.textContent = CAPABILITY_BLURB[id] || "";
      row.appendChild(name);
      row.appendChild(desc);
      panelRoute.appendChild(row);
    });

    const latestRouting = snapshot.routing[snapshot.routing.length - 1];
    if (latestRouting) {
      const rationale = document.createElement("p");
      rationale.className = "ww-route-rationale";
      rationale.textContent = "ROUTING RATIONALE: " + latestRouting.rationale;
      panelRoute.appendChild(rationale);
    }
  }

  function renderWorkspace(snapshot) {
    const content = getWorkspaceContent(state.goal, state.route);

    panelWork.innerHTML = "";
    panelWork.classList.remove("ww-expanded");
    const demoTag = document.createElement("p");
    demoTag.className = "ww-demo-tag";
    demoTag.textContent = "ILLUSTRATIVE CONTENT — NOT MACHINE-GENERATED";
    panelWork.appendChild(demoTag);
    content.blocks.forEach((b) => panelWork.appendChild(renderWorkBlock(b)));
    const nextP = document.createElement("p");
    nextP.className = "ww-next-action";
    nextP.textContent = content.next;
    panelWork.appendChild(nextP);

    renderRoutePanel(snapshot);
    renderEvidencePanel(snapshot);
    renderExecutePanel(snapshot);
    renderNextMoveBanner(snapshot.nextMove);
    renderIndicators(snapshot.indicators);

    renderExecStrip();
    updateContextualControls();

    awRouteLabel.textContent = state.route.length
      ? state.route.map((id) => registry[id]?.def.label || id).join("  ·  ")
      : "NO CAPABILITY MATCHED";
    awGoalText.textContent = state.goal;
  }

  async function refreshSnapshot() {
    if (!state.missionId) return;
    const result = await apiFetch(`/missions/${encodeURIComponent(state.missionId)}`);
    if (result.ok) {
      state.snapshot = result.data;
      state.route = result.data.mission.route;
      renderWorkspace(result.data);
    }
  }

  function setWorkspaceTab(name) {
    state.workspace = name;
    wwTabs.forEach((t) => {
      const active = t.dataset.panel === name;
      t.classList.toggle("ww-tab-active", active);
      t.setAttribute("aria-current", active ? "true" : "false");
    });
    Object.entries(panels).forEach(([key, panelEl]) => { panelEl.hidden = key !== name; });
    if (name === "history") renderHistory();
  }

  wwTabs.forEach((t) => t.addEventListener("click", () => setWorkspaceTab(t.dataset.panel)));

  function exitEditingSubpanel() {
    awEditForm.hidden = true;
    awGoalSummary.hidden = false;
  }

  let morphTimer = null;

  function energizeRoute(matched, pulseDuration) {
    clearAllActive();
    setRoutingActive(matched.length > 0);
    matched.forEach((id) => {
      setNodeActive(id, true);
      firePulse(id, pulseDuration);
    });
  }

  function enterActiveMode(snapshot) {
    state.mode = "ACTIVE";
    state.missionId = snapshot.mission.id;
    state.goal = snapshot.mission.goal_text;
    state.route = snapshot.mission.route;
    state.stage = STAGES.indexOf(snapshot.mission.stage);
    if (state.stage < 0) state.stage = 0;
    state.snapshot = snapshot;

    energizeRoute(state.route, 800);
    renderWorkspace(snapshot);
    setWorkspaceTab("work");

    stage.dataset.mode = "active";
    coreGroup.classList.add("core--intense");
    workspaceLayer.hidden = false;
    requestAnimationFrame(() => workspaceLayer.classList.add("show"));

    clearTimeout(morphTimer);
    morphTimer = setTimeout(() => {
      uiLayer.hidden = true;
      coreGroup.classList.remove("core--intense");
    }, reducedMotion ? 60 : 780);
  }

  async function updateActiveRoute(goalText) {
    const text = goalText.trim();
    if (!text || !state.missionId) return false;

    const result = await apiFetch(`/missions/${encodeURIComponent(state.missionId)}/reroute`, {
      method: "POST",
      body: JSON.stringify({ goalText: text }),
    });
    if (!result.ok) {
      showBanner(result.networkError ? "POCKET CORTEX SERVER UNREACHABLE" : "COULD NOT RE-ROUTE", 2800);
      return false;
    }

    state.goal = text;
    state.route = result.data.mission.route;
    state.stage = STAGES.indexOf(result.data.mission.stage);
    state.snapshot = result.data;

    energizeRoute(state.route, 700);
    renderWorkspace(result.data);
    setWorkspaceTab("work");
    state.mode = "ACTIVE";
    exitEditingSubpanel();
    return true;
  }

  function exitActiveMode() {
    state.mode = "TITLE";
    exitEditingSubpanel();
    goalInput.value = state.goal;
    autoGrow(goalInput);
    clearTimeout(routingTimer);
    applyIntentRouting();
    uiLayer.hidden = false;
    requestAnimationFrame(() => {
      stage.dataset.mode = "title";
    });
    workspaceLayer.classList.remove("show");
    clearTimeout(morphTimer);
    morphTimer = setTimeout(() => {
      workspaceLayer.hidden = true;
    }, reducedMotion ? 60 : 550);
  }

  function openEditIntent() {
    state.mode = "EDITING";
    stage.dataset.mode = "editing";
    awEditInput.value = state.goal;
    awGoalSummary.hidden = true;
    awEditForm.hidden = false;
    autoGrow(awEditInput);
    awEditInput.focus({ preventScroll: true });
  }

  btnEditIntent.addEventListener("click", openEditIntent);
  btnEditCancel.addEventListener("click", () => {
    state.mode = "ACTIVE";
    stage.dataset.mode = "active";
    exitEditingSubpanel();
  });

  awEditForm.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = awEditInput.value.trim();
    if (!text) {
      shakeAndWarn(awEditForm);
      return;
    }
    updateActiveRoute(text);
  });
  wireEnterSubmit(awEditInput, awEditForm);

  btnBack.addEventListener("click", () => {
    if (isDemoRunning) return;
    exitActiveMode();
  });

  btnRefine.addEventListener("click", () => {
    if (routeKey(state.route) === "create+design+discover") {
      const expanded = panelWork.classList.toggle("ww-expanded");
      showBanner(expanded ? "SHOWING EXPANDED DETAIL" : "DETAIL COLLAPSED", 1600);
    } else {
      setWorkspaceTab("work");
      showBanner("REFINING WORKING DIRECTIONS", 1600);
    }
  });

  btnNext.addEventListener("click", async () => {
    if (!state.missionId) return;
    const targetStage = routeKey(state.route) === "create+design+discover"
      ? STAGES[STAGES.length - 1]
      : STAGES[Math.min(state.stage + 1, STAGES.length - 1)];
    const result = await apiFetch(`/missions/${encodeURIComponent(state.missionId)}/stage`, {
      method: "POST",
      body: JSON.stringify({ stage: targetStage }),
    });
    if (result.ok) {
      state.stage = STAGES.indexOf(targetStage);
      state.snapshot = result.data;
      renderExecStrip();
      renderNextMoveBanner(result.data.nextMove);
      showBanner(targetStage + " STAGE", 1400);
    } else {
      showBanner(result.networkError ? "POCKET CORTEX SERVER UNREACHABLE" : "COULD NOT ADVANCE STAGE", 2400);
    }
  });

  // Initial reachability probe so an offline launch shows the banner
  // immediately instead of waiting for the first user action to fail.
  apiFetch("/health");
})();
