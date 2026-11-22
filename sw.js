// Service worker: offline fallback only, never a faster or older page online.
//
// Every request it handles goes to the network first, exactly as without a
// service worker (the browser's HTTP cache still applies as usual). Only when
// the network request fails outright (offline, DNS error) does it answer from
// its cache. An HTTP error such as 404 is passed through, not replaced by an
// older copy. So while online a reader always gets the deployed page and the
// newest data; a reader who had a stale stylesheet in Safari was the reason to
// keep it this strict.
//
// Cached responses carry `x-sw-cached-at`, read by fetchData() in index.html
// to show "Offline – angezeigt wird der Stand vom …".
//
// One fixed cache name across deploys. The worker is network first, so the
// cache never decides what an online reader sees and needs no version; a name
// per deploy made every new worker delete the copy the reader had just filled
// under the old one, leaving nothing for the next offline open. Same-origin
// files are stored under their path without the query string (style.css?v=sha,
// shared links ?virus=…), so each file keeps exactly one entry and a deploy
// replaces it instead of adding another. Caches of other names (earlier
// per-deploy names) are deleted on activate.
const CACHE = 'virenradar-v1';

// Origins whose responses may be kept for offline use. jsDelivr: the page loads
// ECharts with crossorigin="anonymous", so the response is a CORS response (not
// opaque) and the browser checks its SRI hash again on the cached copy, which
// holds the same bytes. GoatCounter is deliberately absent: never intercepted.
const CACHEABLE_ORIGINS = new Set([
    self.location.origin,
    'https://raw.githubusercontent.com',
    'https://cdn.jsdelivr.net'
]);

// No skipWaiting(): a new worker waits until no tab uses the old one. Both are
// network first, so waiting never means an older page, and an open tab is never
// switched to another worker in the middle of its requests.

self.addEventListener('activate', event => {
    event.waitUntil((async () => {
        const names = await caches.keys();
        await Promise.all(names.filter(n => n.startsWith('virenradar-') && n !== CACHE).map(n => caches.delete(n)));
        await self.clients.claim();
    })());
});

function handled(request) {
    if (request.method !== 'GET') return false;
    const url = new URL(request.url);
    return CACHEABLE_ORIGINS.has(url.origin);
}

// Same-origin entries are keyed by path only (see CACHE); other origins by full URL
function cacheKey(request) {
    const url = new URL(request.url);
    if (url.origin !== self.location.origin) return request;
    url.search = '';
    url.hash = '';
    return url.href;
}

async function keep(request, response) {
    // Only complete, readable answers: no errors, no opaque or partial responses
    if (!response.ok || response.status !== 200 || (response.type !== 'basic' && response.type !== 'cors')) return;
    const cache = await caches.open(CACHE);
    // The SARI file alone is 16 MB unpacked: do not rewrite an unchanged copy
    // on every page load. Compared by content hash, since raw.githubusercontent
    // exposes neither ETag nor Last-Modified to a CORS request.
    const body = await response.arrayBuffer();
    const digest = await crypto.subtle.digest('SHA-256', body);
    const hash = Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, '0')).join('');
    const key = cacheKey(request);
    const old = await cache.match(key, { ignoreVary: true });
    if (old && old.headers.get('x-sw-sha256') === hash) return;
    const headers = new Headers(response.headers);
    // The stored body is already decoded: these two would describe the network copy
    headers.delete('content-encoding');
    headers.delete('content-length');
    headers.set('x-sw-cached-at', new Date().toISOString());
    headers.set('x-sw-sha256', hash);
    await cache.put(key, new Response(body, { status: response.status, statusText: response.statusText, headers }));
}

async function networkFirst(event) {
    const { request } = event;
    let response;
    try {
        response = await fetch(request);
    } catch (_) {
        // One retry before the cache: a single reset on a mobile connection should
        // not show old data with the offline note to a reader who is online
        try {
            response = await fetch(request);
        } catch (err) {
            const cache = await caches.open(CACHE);
            // ignoreVary: raw.githubusercontent varies on headers (Origin, encoding)
            // that differ between the page's request and the one that was cached
            const hit = await cache.match(cacheKey(request), { ignoreVary: true });
            if (hit) return hit;
            throw err;
        }
    }
    event.waitUntil(keep(request, response.clone()).catch(() => {}));
    return response;
}

self.addEventListener('fetch', event => {
    if (!handled(event.request)) return;
    event.respondWith(networkFirst(event));
});

// The first visit loads everything before this worker controls the page, so
// the page sends the URLs it used once the worker is ready; they are fetched
// (normally straight from the HTTP cache) and kept, so offline works from the
// second open on, not the third.
self.addEventListener('message', event => {
    const msg = event.data;
    if (!msg || msg.type !== 'keep-urls' || !Array.isArray(msg.urls)) return;
    event.waitUntil(Promise.all(msg.urls.slice(0, 50).map(async u => {
        try {
            const url = new URL(u, self.location.href);
            const request = new Request(url.href, { mode: url.origin === self.location.origin ? 'same-origin' : 'cors', credentials: 'omit' });
            if (!handled(request)) return;
            const cache = await caches.open(CACHE);
            if (await cache.match(cacheKey(request), { ignoreVary: true })) return;
            await keep(request, await fetch(request));
        } catch (_) { /* best effort */ }
    })));
});
