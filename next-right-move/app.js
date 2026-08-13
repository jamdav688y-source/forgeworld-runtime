/*
 * Next Right Move — application logic.
 * No network calls. No analytics. State lives only in sessionStorage
 * (cleared automatically when the browser tab/app closes, and
 * immediately on "Clear session").
 */
(function () {
  "use strict";

  var STORAGE_KEY = "nrm_state_v1";
  var SCREEN_KEY = "nrm_screen_v1";

  var STEP_SCREENS = ["fact", "story", "urge", "knowledge", "options", "cost", "nextmove"];
  var ALL_SCREENS = ["intro"].concat(STEP_SCREENS, ["summary", "friend", "compare"]);

  var STEP_LABELS = {
    fact: "What happened?",
    story: "What am I thinking or feeling?",
    urge: "What am I tempted to do?",
    knowledge: "What do I actually know?",
    options: "What options do I have?",
    cost: "Which option makes tomorrow easier?",
    nextmove: "What is my next right move?"
  };

  var defaultState = function () {
    return {
      fact: "",
      story: "",
      urge: "",
      knowledge: "",
      options: [],
      costOptionIndex: null,
      costNote: "",
      nextMove: "",
      friendAdvice: ""
    };
  };

  var state = loadState();
  var currentScreen = loadScreen();

  // ---------- persistence ----------

  function loadState() {
    try {
      var raw = sessionStorage.getItem(STORAGE_KEY);
      if (!raw) return defaultState();
      var parsed = JSON.parse(raw);
      var merged = defaultState();
      for (var k in merged) {
        if (parsed.hasOwnProperty(k)) merged[k] = parsed[k];
      }
      return merged;
    } catch (e) {
      return defaultState();
    }
  }

  function saveState() {
    try {
      sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch (e) {
      /* storage unavailable (e.g. private mode) — app still works in-memory for this load */
    }
  }

  function loadScreen() {
    try {
      var s = sessionStorage.getItem(SCREEN_KEY);
      return ALL_SCREENS.indexOf(s) !== -1 ? s : "intro";
    } catch (e) {
      return "intro";
    }
  }

  function saveScreen() {
    try {
      sessionStorage.setItem(SCREEN_KEY, currentScreen);
    } catch (e) {}
  }

  // ---------- DOM helpers ----------

  function $(sel) { return document.querySelector(sel); }
  function $all(sel) { return Array.prototype.slice.call(document.querySelectorAll(sel)); }

  var stepNav = $("#step-nav");
  var navBack = $("#nav-back");
  var navSkip = $("#nav-skip");
  var navNext = $("#nav-next");

  var fieldForScreen = {
    fact: $("#input-fact"),
    story: $("#input-story"),
    urge: $("#input-urge"),
    knowledge: $("#input-knowledge"),
    cost: $("#input-cost"),
    nextmove: $("#input-nextmove")
  };

  var stateKeyForScreen = {
    fact: "fact",
    story: "story",
    urge: "urge",
    knowledge: "knowledge",
    cost: "costNote",
    nextmove: "nextMove"
  };

  // ---------- screen rendering ----------

  function showScreen(name) {
    currentScreen = name;
    saveScreen();

    ALL_SCREENS.forEach(function (s) {
      var el = document.querySelector('.screen[data-screen="' + s + '"]');
      if (!el) return;
      if (s === name) {
        el.classList.add("active");
      } else {
        el.classList.remove("active");
      }
    });

    var isStep = STEP_SCREENS.indexOf(name) !== -1;
    stepNav.hidden = !isStep;

    if (isStep) {
      var idx = STEP_SCREENS.indexOf(name);
      navBack.disabled = idx === 0 && false; // back from first step returns to intro, always enabled
      navNext.textContent = idx === STEP_SCREENS.length - 1 ? "Finish" : "Next";
      loadFieldFromState(name);
    }

    if (name === "options") renderOptionList();
    if (name === "cost") renderCostPicker();
    if (name === "summary") renderSummary();
    if (name === "compare") renderCompare();

    // move focus to heading for screen-reader / keyboard users
    var heading = document.querySelector('.screen[data-screen="' + name + '"] h1');
    if (heading) {
      heading.setAttribute("tabindex", "-1");
      heading.focus();
    }
    window.scrollTo(0, 0);
  }

  function loadFieldFromState(screen) {
    var field = fieldForScreen[screen];
    var key = stateKeyForScreen[screen];
    if (field && key) field.value = state[key] || "";
  }

  function saveFieldToState(screen) {
    var field = fieldForScreen[screen];
    var key = stateKeyForScreen[screen];
    if (field && key) {
      state[key] = field.value;
      saveState();
    }
  }

  // ---------- navigation ----------

  function goNext() {
    if (STEP_SCREENS.indexOf(currentScreen) !== -1) {
      saveFieldToState(currentScreen);
    }
    var idx = STEP_SCREENS.indexOf(currentScreen);
    if (idx === -1) return;
    if (idx === STEP_SCREENS.length - 1) {
      showScreen("summary");
    } else {
      showScreen(STEP_SCREENS[idx + 1]);
    }
  }

  function goBack() {
    if (STEP_SCREENS.indexOf(currentScreen) !== -1) {
      saveFieldToState(currentScreen);
    }
    var idx = STEP_SCREENS.indexOf(currentScreen);
    if (idx <= 0) {
      showScreen("intro");
    } else {
      showScreen(STEP_SCREENS[idx - 1]);
    }
  }

  function goSkip() {
    var field = fieldForScreen[currentScreen];
    var key = stateKeyForScreen[currentScreen];
    if (field && key) {
      field.value = "";
      state[key] = "";
      saveState();
    }
    var idx = STEP_SCREENS.indexOf(currentScreen);
    if (idx === STEP_SCREENS.length - 1) {
      showScreen("summary");
    } else {
      showScreen(STEP_SCREENS[idx + 1]);
    }
  }

  navNext.addEventListener("click", goNext);
  navBack.addEventListener("click", goBack);
  navSkip.addEventListener("click", goSkip);

  $('[data-action="start"]').addEventListener("click", function () {
    showScreen("fact");
  });

  // live-save text fields as the user types, so a refresh never loses work
  Object.keys(fieldForScreen).forEach(function (screen) {
    var field = fieldForScreen[screen];
    if (!field) return;
    field.addEventListener("input", function () {
      saveFieldToState(screen);
      if (screen === "fact") updateCharNote();
    });
  });

  function updateCharNote() {
    var note = $("#fact-charnote");
    if (!note) return;
    var len = fieldForScreen.fact.value.length;
    note.textContent = len > 0 ? len + " / 2000" : "";
  }

  // ---------- options screen ----------

  var optionInput = $("#option-input");
  var optionAddBtn = $("#option-add-btn");
  var optionList = $("#option-list");

  function addOption(text) {
    var trimmed = (text || "").trim();
    if (!trimmed) return;
    state.options.push(trimmed);
    saveState();
    optionInput.value = "";
    renderOptionList();
    optionInput.focus();
  }

  optionAddBtn.addEventListener("click", function () {
    addOption(optionInput.value);
  });
  optionInput.addEventListener("keydown", function (e) {
    if (e.key === "Enter") {
      e.preventDefault();
      addOption(optionInput.value);
    }
  });

  $all(".example-btn").forEach(function (btn) {
    btn.addEventListener("click", function () {
      addOption(btn.textContent);
    });
  });

  function renderOptionList() {
    optionList.innerHTML = "";
    if (state.options.length === 0) {
      var li = document.createElement("li");
      li.className = "empty-note";
      li.textContent = "No options added yet.";
      li.style.background = "transparent";
      li.style.border = "none";
      optionList.appendChild(li);
      return;
    }
    state.options.forEach(function (opt, i) {
      var li = document.createElement("li");

      var span = document.createElement("span");
      span.className = "option-text";
      span.textContent = opt;

      var removeBtn = document.createElement("button");
      removeBtn.type = "button";
      removeBtn.className = "remove-option";
      removeBtn.textContent = "Remove";
      removeBtn.setAttribute("aria-label", "Remove option: " + opt);
      removeBtn.addEventListener("click", function () {
        state.options.splice(i, 1);
        if (state.costOptionIndex === i) state.costOptionIndex = null;
        else if (state.costOptionIndex > i) state.costOptionIndex -= 1;
        saveState();
        renderOptionList();
      });

      li.appendChild(span);
      li.appendChild(removeBtn);
      optionList.appendChild(li);
    });
  }

  // ---------- cost / picker screen ----------

  var costPicker = $("#cost-option-picker");

  function renderCostPicker() {
    costPicker.innerHTML = "";
    if (state.options.length === 0) {
      var p = document.createElement("p");
      p.className = "empty-note";
      p.textContent = "You didn't add any options, so just write freely below.";
      costPicker.appendChild(p);
      return;
    }
    state.options.forEach(function (opt, i) {
      var label = document.createElement("label");
      var input = document.createElement("input");
      input.type = "radio";
      input.name = "cost-option";
      input.value = String(i);
      input.checked = state.costOptionIndex === i;
      input.addEventListener("change", function () {
        state.costOptionIndex = i;
        saveState();
      });
      var span = document.createElement("span");
      span.textContent = opt;
      label.appendChild(input);
      label.appendChild(span);
      costPicker.appendChild(label);
    });
  }

  // ---------- summary ----------

  function summaryFields() {
    return [
      { label: "What happened", value: state.fact },
      { label: "What I'm thinking or feeling", value: state.story },
      { label: "What I'm tempted to do", value: state.urge },
      { label: "What I actually know", value: state.knowledge },
      { label: "Options", value: state.options.length ? state.options.map(function (o) { return "• " + o; }).join("\n") : "" },
      { label: "Makes tomorrow easier", value: costSummaryText() },
      { label: "My next right move", value: state.nextMove }
    ];
  }

  function costSummaryText() {
    var parts = [];
    if (state.costOptionIndex !== null && state.options[state.costOptionIndex]) {
      parts.push(state.options[state.costOptionIndex]);
    }
    if (state.costNote) parts.push(state.costNote);
    return parts.join(" — ");
  }

  function renderSummary() {
    var container = $("#summary-content");
    container.innerHTML = "";
    summaryFields().forEach(function (f) {
      var block = document.createElement("div");
      block.className = "summary-block";
      var h = document.createElement("h2");
      h.textContent = f.label;
      var p = document.createElement("p");
      if (f.value) {
        p.textContent = f.value;
      } else {
        p.textContent = "(skipped)";
        p.className = "empty-note";
      }
      block.appendChild(h);
      block.appendChild(p);
      container.appendChild(block);
    });
  }

  // ---------- run it again / friend perspective ----------

  $("#run-it-again-btn").addEventListener("click", function () {
    $("#input-friend").value = state.friendAdvice || "";
    showScreen("friend");
  });

  $("#input-friend").addEventListener("input", function () {
    state.friendAdvice = $("#input-friend").value;
    saveState();
  });

  $("#friend-compare-btn").addEventListener("click", function () {
    state.friendAdvice = $("#input-friend").value;
    saveState();
    showScreen("compare");
  });

  $("#back-to-summary-btn").addEventListener("click", function () {
    showScreen("summary");
  });

  function renderCompare() {
    var selfVoice = [state.story, state.urge, state.nextMove].filter(Boolean).join("\n\n");
    $("#compare-self").textContent = selfVoice || "(nothing entered yet)";
    $("#compare-friend").textContent = state.friendAdvice || "(nothing entered yet)";
  }

  // ---------- export ----------

  $("#export-btn").addEventListener("click", function () {
    var lines = ["Next Right Move — session export", "Generated on-device: " + new Date().toString(), ""];
    summaryFields().forEach(function (f) {
      lines.push(f.label + ":");
      lines.push(f.value || "(skipped)");
      lines.push("");
    });
    if (state.friendAdvice) {
      lines.push("What I'd tell a friend:");
      lines.push(state.friendAdvice);
      lines.push("");
    }
    var blob = new Blob([lines.join("\n")], { type: "text/plain" });
    var url = URL.createObjectURL(blob);
    var a = document.createElement("a");
    a.href = url;
    a.download = "next-right-move-" + Date.now() + ".txt";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    showToast("Exported. Nothing was sent anywhere — the file saved locally.");
  });

  // ---------- restart ----------

  $("#restart-btn").addEventListener("click", function () {
    state = defaultState();
    saveState();
    showScreen("intro");
  });

  // ---------- clear session ----------

  var clearBackdrop = $("#clear-dialog-backdrop");

  $("#clear-session-btn").addEventListener("click", function () {
    clearBackdrop.hidden = false;
    $("#clear-cancel-btn").focus();
  });
  $("#clear-cancel-btn").addEventListener("click", function () {
    clearBackdrop.hidden = true;
  });
  clearBackdrop.addEventListener("click", function (e) {
    if (e.target === clearBackdrop) clearBackdrop.hidden = true;
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !clearBackdrop.hidden) clearBackdrop.hidden = true;
  });
  $("#clear-confirm-btn").addEventListener("click", function () {
    state = defaultState();
    clearBackdrop.hidden = true;
    showScreen("intro");
    // showScreen("intro") re-saves "intro" as the current screen, which is
    // the safe default and contains no user content — but Clear Session
    // means what it says, so explicitly drop both keys afterward too.
    try { sessionStorage.removeItem(STORAGE_KEY); } catch (e) {}
    try { sessionStorage.removeItem(SCREEN_KEY); } catch (e) {}
    showToast("Session cleared.");
  });

  // ---------- toast ----------

  var toastTimer = null;
  function showToast(msg) {
    var toast = $("#toast");
    toast.textContent = msg;
    toast.hidden = false;
    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toast.hidden = true; }, 3200);
  }

  // ---------- service worker (offline support) ----------

  if ("serviceWorker" in navigator) {
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("./service-worker.js").catch(function () {
        /* offline-first still works for this load without a controlling worker */
      });
    });
  }

  // ---------- initial render ----------

  updateCharNote();
  showScreen(currentScreen);
})();
