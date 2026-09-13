var staticCacheName = "dnd-pwa-v2";

self.addEventListener("install", function (event) {
  // Take over immediately on next load instead of waiting for every open tab running the
  // previous version to close - otherwise a browser that already has the old, cache-first
  // service worker installed would keep the stale (wrong-language) cached page indefinitely.
  self.skipWaiting();
  event.waitUntil(
    caches.open(staticCacheName).then(function (cache) {
      return cache.addAll(["/"]);
    })
  );
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    Promise.all([
      self.clients.claim(),
      // Drop caches from older versions so a stale cached page can't linger indefinitely.
      caches.keys().then(function (keys) {
        return Promise.all(
          keys
            .filter(function (key) {
              return key !== staticCacheName;
            })
            .map(function (key) {
              return caches.delete(key);
            })
        );
      }),
    ])
  );
});

self.addEventListener("fetch", function (event) {
  var requestUrl = new URL(event.request.url);

  // Never cache the API - the frontend button is only useful with live data.
  if (requestUrl.pathname.startsWith("/api/")) {
    return;
  }

  if (requestUrl.origin === location.origin) {
    // Network-first: every page here can depend on the language cookie/session, so a cached
    // response would silently ignore a language switch (this is exactly what happened when
    // "/" was served cache-first with no network fallback at all). The cache is only a
    // fallback for when the network is unreachable (offline), populated opportunistically
    // from whatever was last successfully fetched.
    event.respondWith(
      fetch(event.request)
        .then(function (response) {
          var responseCopy = response.clone();
          caches.open(staticCacheName).then(function (cache) {
            cache.put(event.request, responseCopy);
          });
          return response;
        })
        .catch(function () {
          return caches.match(event.request);
        })
    );
    return;
  }

  event.respondWith(
    caches.match(event.request).then(function (response) {
      return response || fetch(event.request);
    })
  );
});
