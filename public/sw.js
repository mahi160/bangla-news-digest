// Network-first for pages (always try for the latest edition; only fall back
// to whatever's cached when offline), cache-first for everything else
// (style/icon/manifest/fonts -- rarely change, no reason to hit the network
// for them every visit). Cache grows as-you-go, unbounded for now -- add
// pruning if that ever becomes a real problem.
//
// CACHE version bumps when this *strategy* changes, not per digest -- that's
// what the update badge (index page's inline script) is watching for.
var CACHE = 'nd-v1';

self.addEventListener('install', function(e){ self.skipWaiting(); });
self.addEventListener('activate', function(e){ e.waitUntil(self.clients.claim()); });

self.addEventListener('fetch', function(e){
  if (e.request.method !== 'GET') return;
  // Only handle same-origin requests -- third-party scripts (Mixpanel's
  // CDN) and browser-extension-injected requests (chrome-extension://)
  // aren't ours to cache, and Cache.put() throws on non-http(s) schemes.
  // Let the browser handle those natively.
  if (e.request.url.indexOf(self.location.origin) !== 0) return;
  if (e.request.mode === 'navigate') {
    e.respondWith(
      fetch(e.request).then(function(res){
        var copy = res.clone();
        caches.open(CACHE).then(function(c){ c.put(e.request, copy); });
        return res;
      }).catch(function(){ return caches.match(e.request); })
    );
    return;
  }
  e.respondWith(
    caches.match(e.request).then(function(cached){
      return cached || fetch(e.request).then(function(res){
        var copy = res.clone();
        caches.open(CACHE).then(function(c){ c.put(e.request, copy); });
        return res;
      });
    }).catch(function(){ /* offline and not cached -- nothing we can do */ })
  );
});
