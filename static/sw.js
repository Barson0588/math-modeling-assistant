const CACHE_NAME = 'mma-v2';
const STATIC_ASSETS = [
  '/',
  '/static/style.css',
  '/static/script.js',
  '/static/manifest.json',
  '/static/offline.html',
];

// Install: pre-cache static assets
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
  );
  self.skipWaiting();
});

// Activate: clean old caches
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Fetch: cache-first for static, network-first for API data, network-only for generation
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET') return;

  // API data: network first, fallback to cache
  if (url.pathname.startsWith('/api/models') ||
      url.pathname.startsWith('/api/problems') ||
      url.pathname.startsWith('/api/guide') ||
      url.pathname.startsWith('/api/roles')) {
    event.respondWith(networkFirst(event.request));
    return;
  }

  // Generation endpoints: network only
  if (url.pathname.startsWith('/api/generate') ||
      url.pathname.startsWith('/api/explain') ||
      url.pathname.startsWith('/api/scholar') ||
      url.pathname.startsWith('/api/check') ||
      url.pathname.startsWith('/api/ai-report') ||
      url.pathname.startsWith('/api/latex') ||
      url.pathname.startsWith('/api/deduplicate') ||
      url.pathname.startsWith('/api/refine') ||
      url.pathname.startsWith('/api/verify') ||
      url.pathname.startsWith('/api/score') ||
      url.pathname.startsWith('/api/recommend') ||
      url.pathname.startsWith('/api/suggest') ||
      url.pathname.startsWith('/api/compare') ||
      url.pathname.startsWith('/api/mock') ||
      url.pathname.startsWith('/api/analyze') ||
      url.pathname.startsWith('/api/check-plagiarism') ||
      url.pathname.startsWith('/api/generate-sensitivity')) {
    return;
  }

  // Static assets + CDN: cache first
  if (url.pathname.startsWith('/static/') ||
      url.pathname === '/' ||
      url.hostname === 'cdn.jsdelivr.net' ||
      url.hostname === 'fonts.googleapis.com' ||
      url.hostname === 'fonts.gstatic.com') {
    event.respondWith(cacheFirst(event.request));
  }
});

async function cacheFirst(request) {
  const cached = await caches.match(request);
  if (cached) return cached;
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch (e) {
    if (request.destination === 'document') {
      const offlinePage = await caches.match('/static/offline.html');
      if (offlinePage) return offlinePage;
    }
    return new Response('Offline', { status: 503 });
  }
}

async function networkFirst(request) {
  try {
    const response = await fetch(request);
    if (response.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, response.clone());
    }
    return response;
  } catch (e) {
    const cached = await caches.match(request);
    if (cached) return cached;
    return new Response(JSON.stringify({ error: '离线状态，请连接网络后重试' }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' },
    });
  }
}
