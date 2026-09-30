/* Azadexa service worker: static assets only.
 *
 * The previous version cached every same-origin GET, navigations included, and
 * answered from the cache before the network. Three consequences, all of them
 * real rather than theoretical:
 *
 *   - a user editing a record navigated back and was shown the cached page,
 *     because the cached copy always won;
 *   - authenticated HTML stayed in the cache after logout, so on a shared
 *     device the next person to open the application could be served the
 *     previous user's pages;
 *   - the cache name never changed, so a new worker re-populated the same
 *     cache and the stale entries survived every deployment.
 *
 * Documents are now always network-first and never stored. Only versioned
 * static assets are cached, and only after a successful response.
 */

const CACHE = 'azadexa-static-v2';

const PRECACHE = [
  '/static/css/custom.css',
  '/static/css/utilities.css',
  '/static/css/layout.css',
  '/static/js/app.js',
  '/static/js/theme.js',
  '/static/js/share.js',
  '/static/js/admin-fields.js',
  '/static/js/main.js',
  '/static/js/profile.js',
  '/static/manifest.json',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE)
      .then((cache) => cache.addAll(PRECACHE))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(
        keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))
      ))
      .then(() => self.clients.claim())
  );
});

function isStaticAsset(url) {
  return url.pathname.startsWith('/static/')
    || url.pathname.startsWith('/uploads/branding/');
}

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === 'navigate') {
    event.respondWith(fetch(request));
    return;
  }

  if (!isStaticAsset(url)) return;

  event.respondWith(
    caches.match(request).then((cached) => {
      const network = fetch(request).then((response) => {
        if (response.ok) {
          const copy = response.clone();
          caches.open(CACHE).then((cache) => cache.put(request, copy));
        }
        return response;
      });
      return cached || network;
    })
  );
});
