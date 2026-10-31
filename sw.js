// 앱 화면은 오프라인에서도 열리게, 지도 타일은 본 것만 캐시 (대량 다운로드 안 함)
const SHELL_CACHE = 'shell-v1';
const TILE_CACHE = 'tiles-v1';
const TILE_LIMIT = 3000;
const SHELL = [
  './', './index.html', './manifest.webmanifest', './icon-192.png', './icon-512.png',
  'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css',
  'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js',
];
const TILE_HOSTS = ['tile.opentopomap.org', 'tile.openstreetmap.org', 'server.arcgisonline.com', 'tile.waymarkedtrails.org'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(SHELL_CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then(keys => Promise.all(
    keys.filter(k => k !== SHELL_CACHE && k !== TILE_CACHE).map(k => caches.delete(k))
  )).then(() => self.clients.claim()));
});

async function trimTiles() {
  const cache = await caches.open(TILE_CACHE);
  const keys = await cache.keys();
  for (let i = 0; i < keys.length - TILE_LIMIT; i++) await cache.delete(keys[i]);
}

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  if (TILE_HOSTS.some(h => url.hostname.endsWith(h))) {
    e.respondWith(caches.open(TILE_CACHE).then(async cache => {
      const hit = await cache.match(req);
      if (hit) return hit;
      const res = await fetch(req);
      if (res.ok || res.type === 'opaque') { cache.put(req, res.clone()); trimTiles(); }
      return res;
    }));
    return;
  }

  const isShell = url.origin === location.origin || url.hostname === 'cdnjs.cloudflare.com';
  if (isShell) {
    // 네트워크 우선, 실패하면 캐시 (앱 업데이트가 바로 반영되도록)
    e.respondWith(fetch(req).then(res => {
      if (res.ok) caches.open(SHELL_CACHE).then(c => c.put(req, res.clone()));
      return res;
    }).catch(() => caches.match(req).then(r => r || caches.match('./index.html'))));
  }
  // 경로 탐색·검색 API는 그대로 네트워크로
});
