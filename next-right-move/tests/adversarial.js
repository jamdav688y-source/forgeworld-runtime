/*
 * Adversarial test script for Next Right Move.
 * Run against a local static server (see docs/TEST_REPORT.md).
 * Usage: node tests/adversarial.js http://localhost:8080
 */
const path = require("path");
process.env.NODE_PATH = require("child_process").execSync("npm root -g").toString().trim();
require("module")._initPaths();
const { chromium } = require("playwright");

const BASE = process.argv[2] || "http://localhost:8080";

function log(name, ok, detail) {
  console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${detail ? " — " + detail : ""}`);
  if (!ok) process.exitCode = 1;
}

(async () => {
  const browser = await chromium.launch({ executablePath: "/opt/pw-browsers/chromium/chrome-linux/chrome" }).catch(async () => {
    return chromium.launch();
  });

  // --- Test 1: small screen load, no horizontal scroll ---
  {
    const context = await browser.newContext({ viewport: { width: 360, height: 740 } });
    const page = await context.newPage();
    const requests = [];
    page.on("request", (r) => requests.push(r.url()));
    await page.goto(BASE + "/index.html", { waitUntil: "networkidle" });

    const externalReqs = requests.filter((u) => !u.startsWith(BASE) && !u.startsWith("http://localhost"));
    log("360px load: no external network requests", externalReqs.length === 0, JSON.stringify(externalReqs));

    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
    log("360px load: no horizontal overflow", scrollWidth <= clientWidth + 1, `scrollWidth=${scrollWidth} clientWidth=${clientWidth}`);

    await context.close();
  }

  // --- Test 2: full flow with empty inputs (skip everything) ---
  {
    const context = await browser.newContext({ viewport: { width: 360, height: 740 } });
    const page = await context.newPage();
    await page.goto(BASE + "/index.html");
    await page.click('[data-action="start"]');
    for (let i = 0; i < 7; i++) {
      await page.click("#nav-skip");
    }
    const heading = await page.textContent("h1#summary-title");
    log("empty-input flow: reaches summary via Skip x7", heading.includes("separated"), heading);

    const emptyNotes = await page.locator(".empty-note").count();
    log("empty-input flow: skipped fields show '(skipped)'", emptyNotes >= 6, `count=${emptyNotes}`);
    await context.close();
  }

  // --- Test 3: very long input does not break layout or truncate silently ---
  {
    const context = await browser.newContext({ viewport: { width: 360, height: 740 } });
    const page = await context.newPage();
    await page.goto(BASE + "/index.html");
    await page.click('[data-action="start"]');
    const longText = "A".repeat(5000); // exceeds maxlength=2000
    await page.fill("#input-fact", longText);
    const actualLen = await page.inputValue("#input-fact").then((v) => v.length);
    log("long input: respects maxlength=2000", actualLen === 2000, `len=${actualLen}`);
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
    log("long input: no horizontal overflow", scrollWidth <= clientWidth + 1, `scrollWidth=${scrollWidth}`);
    await context.close();
  }

  // --- Test 4: unexpected characters (XSS attempt, emoji, newlines) ---
  {
    const context = await browser.newContext({ viewport: { width: 360, height: 740 } });
    const page = await context.newPage();
    await page.goto(BASE + "/index.html");
    await page.click('[data-action="start"]');
    const payload = '<script>window.__xss=true;<' + '/script> 🔥emoji\nmultiline\t"quotes" & ampersand';
    await page.fill("#input-fact", payload);
    await page.click("#nav-next");
    for (let i = 0; i < 6; i++) await page.click("#nav-skip");
    // now on summary
    const xssRan = await page.evaluate(() => window.__xss === true);
    log("unexpected chars: no script injection executed", !xssRan);
    const summaryText = await page.textContent("#summary-content");
    log("unexpected chars: content rendered as text, not stripped", summaryText.includes("emoji"));
    await context.close();
  }

  // --- Test 5: refresh mid-flow preserves progress (sessionStorage) ---
  {
    const context = await browser.newContext({ viewport: { width: 360, height: 740 } });
    const page = await context.newPage();
    await page.goto(BASE + "/index.html");
    await page.click('[data-action="start"]');
    await page.fill("#input-fact", "test fact before refresh");
    await page.click("#nav-next");
    await page.fill("#input-story", "test story before refresh");
    await page.reload();
    const screenAfterReload = await page.evaluate(() => document.querySelector(".screen.active").dataset.screen);
    log("refresh mid-flow: resumes on same screen", screenAfterReload === "story", screenAfterReload);
    const storyVal = await page.inputValue("#input-story");
    log("refresh mid-flow: field data survived", storyVal === "test story before refresh", storyVal);
    await context.close();
  }

  // --- Test 6: back navigation preserves data ---
  {
    const context = await browser.newContext({ viewport: { width: 360, height: 740 } });
    const page = await context.newPage();
    await page.goto(BASE + "/index.html");
    await page.click('[data-action="start"]');
    await page.fill("#input-fact", "fact for back-nav test");
    await page.click("#nav-next");
    await page.click("#nav-back");
    const factVal = await page.inputValue("#input-fact");
    log("back navigation: preserves prior field", factVal === "fact for back-nav test", factVal);
    await context.close();
  }

  // --- Test 7: rapid tapping (double-submit / race conditions) ---
  {
    const context = await browser.newContext({ viewport: { width: 360, height: 740 } });
    const page = await context.newPage();
    await page.goto(BASE + "/index.html");
    await page.click('[data-action="start"]');
    for (let i = 0; i < 15; i++) {
      await page.click("#nav-next", { delay: 0, timeout: 1000, force: true }).catch(() => {});
    }
    const screen = await page.evaluate(() => document.querySelector(".screen.active").dataset.screen);
    log("rapid tapping: lands on a valid known screen, no crash", ["summary", "nextmove"].includes(screen), screen);
    await context.close();
  }

  // --- Test 8: options list add/remove, including empty and whitespace-only ---
  {
    const context = await browser.newContext({ viewport: { width: 360, height: 740 } });
    const page = await context.newPage();
    await page.goto(BASE + "/index.html");
    await page.click('[data-action="start"]');
    await page.click("#nav-skip");
    await page.click("#nav-skip");
    await page.click("#nav-skip");
    await page.click("#nav-skip");
    // now on options screen
    await page.fill("#option-input", "   ");
    await page.click("#option-add-btn");
    let count = await page.locator("#option-list li").count();
    log("options: whitespace-only input is not added", count === 1 && (await page.textContent("#option-list")).includes("No options"), `count=${count}`);

    await page.fill("#option-input", "Call somebody");
    await page.click("#option-add-btn");
    await page.fill("#option-input", "Wait before deciding");
    await page.click("#option-add-btn");
    count = await page.locator("#option-list li").count();
    log("options: two valid options added", count === 2, `count=${count}`);

    await page.locator(".remove-option").first().click();
    count = await page.locator("#option-list li").count();
    log("options: remove works", count === 1, `count=${count}`);
    await context.close();
  }

  // --- Test 9: Clear session actually clears storage and returns to intro ---
  {
    const context = await browser.newContext({ viewport: { width: 360, height: 740 } });
    const page = await context.newPage();
    await page.goto(BASE + "/index.html");
    await page.click('[data-action="start"]');
    await page.fill("#input-fact", "sensitive test data");
    await page.click("#clear-session-btn");
    await page.click("#clear-confirm-btn");
    const screen = await page.evaluate(() => document.querySelector(".screen.active").dataset.screen);
    log("clear session: returns to intro", screen === "intro", screen);
    const storageState = await page.evaluate(() => ({
      state: sessionStorage.getItem("nrm_state_v1"),
      screen: sessionStorage.getItem("nrm_screen_v1"),
    }));
    log("clear session: sessionStorage keys removed", storageState.state === null && storageState.screen === null, JSON.stringify(storageState));

    // reload to make sure nothing resurrects
    await page.reload();
    const factAfter = await page.evaluate(() => {
      const el = document.querySelector("#input-fact");
      return el ? el.value : null;
    });
    log("clear session: data does not resurrect after reload", factAfter === "" || factAfter === null, String(factAfter));
    await context.close();
  }

  // --- Test 10: Run it again / friend comparison ---
  {
    const context = await browser.newContext({ viewport: { width: 360, height: 740 } });
    const page = await context.newPage();
    await page.goto(BASE + "/index.html");
    await page.click('[data-action="start"]');
    await page.fill("#input-fact", "F");
    await page.click("#nav-next");
    await page.fill("#input-story", "I always fail");
    await page.click("#nav-next");
    for (let i = 0; i < 5; i++) await page.click("#nav-skip");
    await page.click("#run-it-again-btn");
    await page.fill("#input-friend", "You're doing your best, it's okay");
    await page.click("#friend-compare-btn");
    const selfText = await page.textContent("#compare-self");
    const friendText = await page.textContent("#compare-friend");
    log("run it again: shows self voice", selfText.includes("I always fail"), selfText);
    log("run it again: shows friend voice", friendText.includes("doing your best"), friendText);
    await context.close();
  }

  // --- Test 11: orientation change (viewport swap) doesn't break layout ---
  {
    const context = await browser.newContext({ viewport: { width: 360, height: 740 } });
    const page = await context.newPage();
    await page.goto(BASE + "/index.html");
    await page.click('[data-action="start"]');
    await page.setViewportSize({ width: 740, height: 360 }); // landscape
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
    log("orientation change: no horizontal overflow in landscape", scrollWidth <= clientWidth + 1, `sw=${scrollWidth} cw=${clientWidth}`);
    await context.close();
  }

  // --- Test 12: offline operation after first load (service worker) ---
  {
    const context = await browser.newContext({ viewport: { width: 360, height: 740 } });
    const page = await context.newPage();
    await page.goto(BASE + "/index.html");
    // wait for SW to be ready and controlling
    await page.waitForFunction(() => navigator.serviceWorker.ready.then(() => true), { timeout: 5000 }).catch(() => {});
    await page.evaluate(async () => {
      const reg = await navigator.serviceWorker.ready;
      return !!reg.active;
    });
    await context.setOffline(true);
    const reloadResult = await page.reload({ waitUntil: "load" }).then(() => "ok").catch((e) => "fail:" + e.message);
    const heading = await page.textContent("h1#intro-title").catch(() => null);
    log("offline: page reloads successfully while offline", reloadResult === "ok" && !!heading, `${reloadResult} heading=${heading}`);
    await context.setOffline(false);
    await context.close();
  }

  // --- Test 13: accessibility — focus moves to h1 on screen change ---
  {
    const context = await browser.newContext({ viewport: { width: 360, height: 740 } });
    const page = await context.newPage();
    await page.goto(BASE + "/index.html");
    await page.click('[data-action="start"]');
    const focused = await page.evaluate(() => document.activeElement.id);
    log("accessibility: focus moves to step heading", focused === "fact-title", focused);
    await context.close();
  }

  await browser.close();
  console.log("\nDone.");
})().catch((e) => {
  console.error("FATAL:", e);
  process.exit(1);
});
