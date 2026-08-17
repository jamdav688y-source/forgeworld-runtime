// Pocket Cortex service worker.
//
// v2 change from the original static-PWA version: this app now has a
// real backend (/api/*), and API responses must NEVER be served from
// cache -- a cached POST-created-mission response, or stale mission
// state, would be actively misleading (a user editing a "current"
// mission that's actually days old). Only the static app shell
// (HTML/CSS/JS/manifest/icons) is cache-first; every /api/ request goes
// straight to the network, full stop, with no cache fallback -- a
// failed API request should surface as the app's own explicit
// "server unreachable" banner (see app.js apiFetch), not a silently
// stale cached JSON blob standing in for it.

const CACHE = "pocket-cortex-v2";
const ASSETS = [
  "./",
  "./index.html",
  "./styles.css",
  "./app.js",
  "./manifest.webmanifest",
  "./icons/icon-192.png",
  "./icons/icon-512.png",
];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(ASSETS)));
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
  );
  self.clients.claim();
});

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);

  if (url.pathname.startsWith("/api/")) {
    // Never intercept API traffic -- always hit the network directly, no
    // cache read, no cache write. Let it fail naturally if the server is
    // unreachable; app.js's apiFetch() is what turns that into an
    // explicit UI state.
    return;
  }

  if (event.request.method !== "GET") {
    return;
  }

  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request))
  );
});
