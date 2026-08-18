/*
 * The service worker, and what it deliberately does not do.
 *
 * It caches the build's static assets and one offline page. It never caches an
 * API response, and it never caches a rendered page.
 *
 * That is a privacy decision, not a lazy one. This platform stores per-value
 * provenance but refuses to keep whole raw provider payloads, because holding
 * special-category health data is the operator's decision and changes what the
 * privacy policy has to say (AGENTS.md rule 19). A service-worker cache of
 * `/api/**` would reintroduce exactly that: a copy of somebody's sleep, location
 * and nutrition history sitting in Cache Storage on a possibly shared device,
 * outliving their sign-out, declared nowhere.
 *
 * It would also be wrong on its own terms. Every data response here is
 * cookie-authenticated and tenant-scoped; serving a stale one after a session
 * ends or a workspace switches is a correctness bug, not a convenience.
 *
 * So "offline" means the app opens and says it is offline. It does not mean the
 * data is still there.
 */

const VERSION = "v1";
const SHELL_CACHE = `qs-shell-${VERSION}`;
const OFFLINE_URL = "/offline.html";

const PRECACHE = [OFFLINE_URL, "/icons/icon-192.png", "/icons/icon-512.png"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches
      .open(SHELL_CACHE)
      .then((cache) => cache.addAll(PRECACHE))
      // Take over without waiting for every old tab to close. Safe here because
      // nothing this worker serves is user data — the worst case of a mixed
      // version is an asset fetched from the network instead of the cache.
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(keys.filter((key) => key !== SHELL_CACHE).map((key) => caches.delete(key))),
      )
      .then(() => self.clients.claim()),
  );
});

/** Immutable build output, safe to serve from cache without revalidating. */
function isBuildAsset(url) {
  return url.pathname.startsWith("/_next/static/") || url.pathname.startsWith("/icons/");
}

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Untouched, on purpose. Not "network-first" — not handled at all, so nothing
  // here can ever hold a tenant's data or a stale authenticated response.
  if (url.pathname.startsWith("/api/")) return;

  if (isBuildAsset(url)) {
    event.respondWith(
      caches.match(request).then(
        (hit) =>
          hit ||
          fetch(request).then((response) => {
            if (response.ok) {
              const copy = response.clone();
              caches.open(SHELL_CACHE).then((cache) => cache.put(request, copy));
            }
            return response;
          }),
      ),
    );
    return;
  }

  // Navigations: always the network, and the offline page when there is none.
  // Never a cached render — a previously visited page holds the data of whoever
  // was signed in when it was visited.
  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(() => caches.match(OFFLINE_URL)));
  }
});
