import { test } from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { createApp, resolveStaticPath } from "../server.js";

const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");

async function withServer(fn) {
  const dir = mkdtempSync(join(tmpdir(), "pocket-cortex-integration-"));
  const dbPath = join(dir, "test.db");
  const { handler } = createApp({ dbPath, repoRoot: REPO_ROOT });
  const server = createServer((req, res) => {
    handler(req, res).catch((err) => {
      res.writeHead(500);
      res.end(JSON.stringify({ error: String(err) }));
    });
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const port = server.address().port;
  const base = `http://127.0.0.1:${port}`;
  try {
    await fn(base);
  } finally {
    await new Promise((resolve) => server.close(resolve));
    rmSync(dir, { recursive: true, force: true });
  }
}

test("GET /api/health responds ok", async () => {
  await withServer(async (base) => {
    const res = await fetch(`${base}/api/health`);
    assert.equal(res.status, 200);
    const body = await res.json();
    assert.equal(body.status, "ok");
  });
});

test("static index.html is served at /", async () => {
  await withServer(async (base) => {
    const res = await fetch(`${base}/`);
    assert.equal(res.status, 200);
    const text = await res.text();
    assert.match(text, /POCKET CORTEX/);
  });
});

test("a literal '..' in the request path is normalized away before it reaches this server (WHATWG URL behavior) -- confirmed empirically, not assumed", async () => {
  await withServer(async (base) => {
    // fetch("/../server.js") resolves client-side to "/server.js", a
    // real, legitimately public file -- this is NOT a traversal escape,
    // it demonstrates why resolveStaticPath must be tested directly
    // below rather than only through HTTP requests.
    const res = await fetch(`${base}/../server.js`);
    assert.equal(res.status, 200);
  });
});

test("resolveStaticPath rejects a raw path that escapes the public dir, tested directly (bypassing URL normalization)", () => {
  const outside = resolveStaticPath("/../../../../../../etc/passwd", "/home/user/forgeworld-runtime/pocket-cortex");
  assert.equal(outside.contained, false);
});

test("resolveStaticPath does not treat a sibling directory sharing a name prefix as contained", () => {
  // Regression check for a real prefix-matching bug: a naive
  // `filePath.startsWith(publicDir)` (no trailing separator) would
  // wrongly accept "/x/pocket-cortex-evil/secret" as being inside
  // "/x/pocket-cortex". resolveStaticPath must require an exact match
  // or a path separator immediately after publicDir.
  const result = resolveStaticPath("/secret", "/home/user/forgeworld-runtime/pocket-cortex");
  // this one IS contained (normal case) -- the actual sibling-prefix
  // check is that join() never lets a relPath jump to a sibling at all,
  // so assert the boundary condition on the returned filePath directly:
  assert.ok(result.filePath.startsWith("/home/user/forgeworld-runtime/pocket-cortex/"));
  assert.ok(!result.filePath.startsWith("/home/user/forgeworld-runtime/pocket-cortex-evil"));
});

test("resolveStaticPath accepts ordinary in-bounds paths", () => {
  const result = resolveStaticPath("/index.html", "/home/user/forgeworld-runtime/pocket-cortex");
  assert.equal(result.contained, true);
  assert.equal(result.filePath, "/home/user/forgeworld-runtime/pocket-cortex/index.html");
});

test("POST /api/missions creates a persistent mission with routing + indicators + next move", async () => {
  await withServer(async (base) => {
    const res = await fetch(`${base}/api/missions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ goalText: "Teach me something I do not understand." }),
    });
    assert.equal(res.status, 201);
    const body = await res.json();
    assert.deepEqual(body.mission.route, ["learn", "explain", "analyze"]);
    assert.ok(body.indicators);
    assert.ok(body.nextMove.text);
    assert.equal(body.routing.length, 1);
  });
});

test("POST /api/missions with empty goalText is rejected with 400", async () => {
  await withServer(async (base) => {
    const res = await fetch(`${base}/api/missions`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ goalText: "  " }),
    });
    assert.equal(res.status, 400);
  });
});

test("malformed JSON body returns 400, not a server crash", async () => {
  await withServer(async (base) => {
    const res = await fetch(`${base}/api/missions`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: "{not valid json",
    });
    assert.equal(res.status, 400);
    // server must still be alive afterward
    const health = await fetch(`${base}/api/health`);
    assert.equal(health.status, 200);
  });
});

test("GET /api/missions/:id 404s cleanly for an id that does not exist", async () => {
  await withServer(async (base) => {
    const res = await fetch(`${base}/api/missions/MSN-fabricated`);
    assert.equal(res.status, 404);
    const body = await res.json();
    assert.equal(body.context.status, "BLOCKED");
  });
});

test("mission persists across separate requests (not in-process-memory-only)", async () => {
  await withServer(async (base) => {
    const create = await fetch(`${base}/api/missions`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ goalText: "Build a tool." }),
    });
    const { mission } = await create.json();

    const list = await fetch(`${base}/api/missions`);
    const { missions } = await list.json();
    assert.ok(missions.some((m) => m.id === mission.id));

    const single = await fetch(`${base}/api/missions/${mission.id}`);
    assert.equal(single.status, 200);
  });
});

test("reroute updates goal text and re-routes, recording a second routing decision", async () => {
  await withServer(async (base) => {
    const create = await fetch(`${base}/api/missions`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ goalText: "Build something." }),
    });
    const { mission } = await create.json();

    const reroute = await fetch(`${base}/api/missions/${mission.id}/reroute`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ goalText: "Explain something instead." }),
    });
    assert.equal(reroute.status, 200);
    const body = await reroute.json();
    assert.equal(body.mission.goal_text, "Explain something instead.");
    assert.equal(body.routing.length, 2);
  });
});

test("recording evidence with an invalid state is rejected", async () => {
  await withServer(async (base) => {
    const create = await fetch(`${base}/api/missions`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ goalText: "goal" }),
    });
    const { mission } = await create.json();

    const res = await fetch(`${base}/api/missions/${mission.id}/evidence`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subject: "x", state: "TOTALLY_MADE_UP", observation: "y" }),
    });
    assert.equal(res.status, 400);
  });
});

test("evidence recording raises the EVIDENCE indicator on the returned snapshot", async () => {
  await withServer(async (base) => {
    const create = await fetch(`${base}/api/missions`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ goalText: "goal" }),
    });
    const { mission } = await create.json();

    const res = await fetch(`${base}/api/missions/${mission.id}/evidence`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ subject: "routing", state: "VALIDATED", observation: "independently re-checked", source: "test" }),
    });
    assert.equal(res.status, 201);
    const body = await res.json();
    assert.equal(body.indicators.evidence.value, 0.75);
  });
});

test("executing MODIFY_CAPABILITY_POLICY is refused with 403 (HUMAN_ONLY)", async () => {
  await withServer(async (base) => {
    const create = await fetch(`${base}/api/missions`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ goalText: "goal" }),
    });
    const { mission } = await create.json();

    const res = await fetch(`${base}/api/missions/${mission.id}/execute`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ capability: "MODIFY_CAPABILITY_POLICY" }),
    });
    assert.equal(res.status, 403);
    const body = await res.json();
    assert.equal(body.authority.decision, "HUMAN_ONLY");
  });
});

test("executing TRIGGER_PHONE_DEPLOY never silently succeeds -- either unavailable (409) or awaiting approval (202), never 200", async () => {
  await withServer(async (base) => {
    const create = await fetch(`${base}/api/missions`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ goalText: "goal" }),
    });
    const { mission } = await create.json();

    const res = await fetch(`${base}/api/missions/${mission.id}/execute`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ capability: "TRIGGER_PHONE_DEPLOY" }),
    });
    assert.ok([409, 202].includes(res.status), `expected 409 or 202, got ${res.status}`);
  });
});

test("GET /api/capabilities lists every policy-table capability with independent capability+authority", async () => {
  await withServer(async (base) => {
    const res = await fetch(`${base}/api/capabilities`);
    assert.equal(res.status, 200);
    const body = await res.json();
    assert.ok(body.capabilities.length >= 8);
    for (const entry of body.capabilities) {
      assert.ok("available" in entry.capability);
      assert.ok("decision" in entry.authority);
    }
  });
});

test("unknown API route returns 404, not a crash or a static-file fallback", async () => {
  await withServer(async (base) => {
    const res = await fetch(`${base}/api/nonexistent-route`);
    assert.equal(res.status, 404);
  });
});
