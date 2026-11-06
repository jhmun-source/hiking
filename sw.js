// 앱 화면은 오프라인에서도 열리게, 지도 타일은 본 것만 캐시 (대량 다운로드 안 함)
const SHELL_CACHE = 'shell-v16';
const TILE_CACHE = 'tiles-v1';
const SAVED_TILES = 'tiles-saved'; // 계획 탭 "이 코스 지도 저장"으로 받은 지도 (자동으로 지우지 않음)
const TILE_LIMIT = 3000;
const SHELL = [
  './', './index.html', './manifest.webmanifest', './icon-192.png', './icon-512.png',
  './courses/index.json', // 산별 코스 파일은 한 번 열어 본 것만 저장돼서 산에서도 다시 열 수 있음
  './trails/index.json',  // 트레킹 목록 (구간 파일도 열어 본 것만 저장)
  './forest/index.json',  // 산림청 등산로 목록 (산별 파일은 열어 본 것만 저장)
  'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css',
  'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js',
];
const TILE_HOSTS = ['tile.opentopomap.org', 'tile.openstreetmap.org', 'server.arcgisonline.com', 'tile.waymarkedtrails.org'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(SHELL_CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(caches.keys().then(keys => Promise.all(
    keys.filter(k => k !== SHELL_CACHE && k !== TILE_CACHE && k !== SAVED_TILES && k !== 'shared').map(k => caches.delete(k))
  )).then(() => self.clients.claim()));
});

async function trimTiles() {
  const cache = await caches.open(TILE_CACHE);
  const keys = await cache.keys();
  for (let i = 0; i < keys.length - TILE_LIMIT; i++) await cache.delete(keys[i]);
}

// 다른 앱의 공유 메뉴에서 코스 파일(GPX·KML·KMZ·TCX·FIT)을 보내면(manifest share_target) 파일을 잠시 보관하고 앱을 ?shared=1 로 엶
async function receiveShare(req) {
  try {
    const form = await req.formData();
    const file = form.getAll('gpx').find(f => f && typeof f.text === 'function');
    if (file) {
      const cache = await caches.open('shared');
      await cache.put('shared-gpx', new Response(file, { // FIT은 이진 파일이라 글자로 바꾸지 않고 그대로
        headers: { 'content-type': 'application/octet-stream', 'x-filename': encodeURIComponent(file.name || 'shared.gpx') },
      }));
    }
  } catch (err) {}
  return Response.redirect('./?shared=1', 303);
}

self.addEventListener('fetch', (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method === 'POST' && url.origin === location.origin && url.pathname.endsWith('/share-target')) {
    e.respondWith(receiveShare(req));
    return;
  }
  if (req.method !== 'GET') return;

  // 브이월드는 지도 그림(WMTS·WMS)만 캐시하고 검색 API는 제외
  const isVworldTile = url.hostname === 'api.vworld.kr' && /^\/req\/(wmts|wms)/.test(url.pathname);
  if (isVworldTile || TILE_HOSTS.some(h => url.hostname.endsWith(h))) {
    e.respondWith(caches.open(TILE_CACHE).then(async cache => {
      const hit = await (await caches.open(SAVED_TILES)).match(req) || await cache.match(req);
      // 지도 화면이 받아 둔 타일(opaque)은 "지도 저장"의 cors 요청에 줄 수 없어서 새로 받음
      if (hit && !(req.mode === 'cors' && hit.type === 'opaque')) return hit;
      const res = await fetch(req);
      // 브이월드는 키 오류도 200(XML)으로 돌려줘서 이미지일 때만 저장
      const isImage = (res.headers.get('content-type') || '').startsWith('image/');
      if ((res.ok && (!isVworldTile || isImage)) || res.type === 'opaque') { cache.put(req, res.clone()); trimTiles(); }
      return res;
    }));
    return;
  }

  const isShell = url.origin === location.origin || url.hostname === 'cdnjs.cloudflare.com';
  if (isShell) {
    // 네트워크 우선, 실패하면 캐시 (앱 업데이트가 바로 반영되도록)
    // no-cache: 브라우저 HTTP 캐시에 남은 옛 버전 대신 서버에 새 버전이 있는지 확인
    e.respondWith(fetch(req, { cache: 'no-cache' }).then(res => {
      if (res.ok) caches.open(SHELL_CACHE).then(c => c.put(req, res.clone()));
      return res;
    }).catch(() => caches.match(req).then(r => r || caches.match('./index.html'))));
  }
  // 경로 탐색·검색 API는 그대로 네트워크로
});
