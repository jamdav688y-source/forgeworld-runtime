#!/usr/bin/env node
// Pocket Cortex server: zero external dependencies (no npm install step,
// deliberately, so Termux deployment never needs network access to
// node_modules registries), static file serving + JSON API over
// node:http, backed by node:sqlite.

import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { join, extname, dirname, normalize } from "node:path";
import { fileURLToPath } from "node:url";

import { openDatabase } from "./lib/db.js";
import * as api from "./lib/api.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = normalize(join(__dirname, ".."));
const PUBLIC_DIR = __dirname;
const DB_PATH = process.env.POCKET_CORTEX_DB || join(__dirname, "data", "pocket-cortex.db");
const PORT = Number(process.env.PORT || 8080);

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".webmanifest": "application/manifest+json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml",
};

function send(res, status, body, headers = {}) {
  const payload = typeof body === "string" ? body : JSON.stringify(body);
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8", ...headers });
  res.end(payload);
}

async function readBody(req) {
  const chunks = [];
  for await (const chunk of req) chunks.push(chunk);
  if (!chunks.length) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    return null; // malformed JSON, distinguished from "no body"
  }
}

// Exported separately from serveStatic so the containment guard can be
// unit-tested directly with a raw string. This matters because in normal
// operation, req.url is parsed with the WHATWG URL constructor first
// (see the `handler` function below), and that parser already collapses
// ".." dot-segments per the URL Standard before this function ever runs
// -- so an HTTP-level test can never actually exercise this guard
// (fetch("/../server.js") arrives here as pathname "/server.js", already
// normalized). This function is the defense-in-depth layer for any path
// that reaches it WITHOUT going through that upstream normalization --
// e.g. a future refactor that constructs `pathname` a different way.
export function resolveStaticPath(pathname, publicDir = PUBLIC_DIR) {
  const relPath = pathname === "/" ? "/index.html" : pathname;
  const filePath = normalize(join(publicDir, relPath));
  const contained = filePath === publicDir || filePath.startsWith(publicDir + "/");
  return { filePath, contained };
}

async function serveStatic(req, res, pathname) {
  const { filePath, contained } = resolveStaticPath(pathname);
  if (!contained) {
    send(res, 403, { error: "forbidden" });
    return;
  }
  if (!existsSync(filePath)) {
    res.writeHead(404, { "Content-Type": "text/plain" });
    res.end("Not found");
    return;
  }
  try {
    const data = await readFile(filePath);
    const ext = extname(filePath);
    res.writeHead(200, { "Content-Type": MIME[ext] || "application/octet-stream" });
    res.end(data);
  } catch {
    res.writeHead(500, { "Content-Type": "text/plain" });
    res.end("Internal error reading file");
  }
}

export function createApp({ dbPath = DB_PATH, repoRoot = REPO_ROOT } = {}) {
  const conn = openDatabase(dbPath);

  async function handler(req, res) {
    const url = new URL(req.url, `http://${req.headers.host || "localhost"}`);
    const pathname = url.pathname;

    if (!pathname.startsWith("/api/")) {
      return serveStatic(req, res, pathname);
    }

    // --- everything below is JSON API -----------------------------------
    if (pathname === "/api/health" && req.method === "GET") {
      return send(res, 200, { status: "ok", time: new Date().toISOString() });
    }

    if (pathname === "/api/capabilities" && req.method === "GET") {
      const r = api.listCapabilitiesHandler(conn, repoRoot);
      return send(res, r.status, r.body);
    }

    if (pathname === "/api/missions" && req.method === "GET") {
      const r = api.listMissionsHandler(conn);
      return send(res, r.status, r.body);
    }

    if (pathname === "/api/missions" && req.method === "POST") {
      const body = await readBody(req);
      if (body === null) return send(res, 400, { error: "malformed JSON body" });
      const r = api.createMissionHandler(conn, repoRoot, body);
      return send(res, r.status, r.body);
    }

    const missionMatch = pathname.match(/^\/api\/missions\/([^/]+)(\/(reroute|evidence|stage|execute))?$/);
    if (missionMatch) {
      const missionId = decodeURIComponent(missionMatch[1]);
      const action = missionMatch[3];

      if (!action && req.method === "GET") {
        const r = api.getMissionHandler(conn, missionId);
        return send(res, r.status, r.body);
      }
      if (action === "reroute" && req.method === "POST") {
        const body = await readBody(req);
        if (body === null) return send(res, 400, { error: "malformed JSON body" });
        const r = api.rerouteMissionHandler(conn, repoRoot, missionId, body);
        return send(res, r.status, r.body);
      }
      if (action === "evidence" && req.method === "POST") {
        const body = await readBody(req);
        if (body === null) return send(res, 400, { error: "malformed JSON body" });
        const r = api.recordEvidenceHandler(conn, missionId, body);
        return send(res, r.status, r.body);
      }
      if (action === "stage" && req.method === "POST") {
        const body = await readBody(req);
        if (body === null) return send(res, 400, { error: "malformed JSON body" });
        const r = api.advanceStageHandler(conn, missionId, body);
        return send(res, r.status, r.body);
      }
      if (action === "execute" && req.method === "POST") {
        const body = await readBody(req);
        if (body === null) return send(res, 400, { error: "malformed JSON body" });
        const r = api.executeCapabilityHandler(conn, repoRoot, missionId, body);
        return send(res, r.status, r.body);
      }
    }

    return send(res, 404, { error: "no such API route", pathname, method: req.method });
  }

  return { handler, conn };
}

function main() {
  const { handler } = createApp({});
  const server = createServer((req, res) => {
    handler(req, res).catch((err) => {
      // eslint-disable-next-line no-console
      console.error("Unhandled server error:", err);
      if (!res.headersSent) send(res, 500, { error: "internal server error" });
    });
  });
  server.listen(PORT, () => {
    // eslint-disable-next-line no-console
    console.log(`Pocket Cortex serving http://127.0.0.1:${PORT} (db: ${DB_PATH})`);
  });
}

// Only auto-start when run directly (`node server.js`), not when imported
// by tests.
if (import.meta.url === `file://${process.argv[1]}`) {
  main();
}
