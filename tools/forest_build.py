# 산림청 등산로 API(trailInfoService) → 산별 등산로 zip(shp) → 앱용 JSON (forest/)
# 사용: python -I build.py <키파일> <zip 캐시 폴더> <출력 폴더>
import sys, os, json, math, struct, zipfile, urllib.request, urllib.parse, re, xml.etree.ElementTree as ET

key_file, cache, out = sys.argv[1:4]
key = open(key_file, encoding='utf-8').read().strip()
os.makedirs(cache, exist_ok=True); os.makedirs(out, exist_ok=True)

def get(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'hiking-course-maker build'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()

# 1) 산 목록
items = []
for page in range(1, 10):
    q = urllib.parse.urlencode({'serviceKey': key, 'pageNo': page, 'numOfRows': 100})
    root = ET.fromstring(get('https://apis.data.go.kr/1400000/trailInfoService/getforestspatialdataservice?' + q))
    got = [{c.tag: (c.text or '').strip() for c in it} for it in root.iter('item')]
    items += got
    total = int(root.findtext('.//totalCount') or 0)
    if len(items) >= total or not got: break
print('mountains', len(items), 'total', total)

# 2) GRS80 TM(중부원점, 원점 38N 127E, 가산 200000/600000 = EPSG:5186) → WGS84
A, F = 6378137.0, 1 / 298.257222101
E2 = F * (2 - F); EP2 = E2 / (1 - E2)
def M(phi):
    e4, e6 = E2 * E2, E2 ** 3
    return A * ((1 - E2/4 - 3*e4/64 - 5*e6/256) * phi - (3*E2/8 + 3*e4/32 + 45*e6/1024) * math.sin(2*phi)
                + (15*e4/256 + 45*e6/1024) * math.sin(4*phi) - (35*e6/3072) * math.sin(6*phi))
LAT0, LON0 = math.radians(38), math.radians(127)
M0 = M(LAT0)
def tm2wgs(x, y, fe=200000.0, fn=600000.0):
    m = M0 + (y - fn)
    mu = m / (A * (1 - E2/4 - 3*E2**2/64 - 5*E2**3/256))
    e1 = (1 - math.sqrt(1 - E2)) / (1 + math.sqrt(1 - E2))
    p1 = mu + (3*e1/2 - 27*e1**3/32) * math.sin(2*mu) + (21*e1**2/16 - 55*e1**4/32) * math.sin(4*mu) \
        + (151*e1**3/96) * math.sin(6*mu) + (1097*e1**4/512) * math.sin(8*mu)
    c1 = EP2 * math.cos(p1)**2; t1 = math.tan(p1)**2
    n1 = A / math.sqrt(1 - E2 * math.sin(p1)**2); r1 = A * (1 - E2) / (1 - E2 * math.sin(p1)**2) ** 1.5
    d = (x - fe) / n1
    lat = p1 - (n1 * math.tan(p1) / r1) * (d*d/2 - (5 + 3*t1 + 10*c1 - 4*c1*c1 - 9*EP2) * d**4/24
                                           + (61 + 90*t1 + 298*c1 + 45*t1*t1 - 252*EP2 - 3*c1*c1) * d**6/720)
    lon = LON0 + (d - (1 + 2*t1 + c1) * d**3/6 + (5 - 2*c1 + 28*t1 - 3*c1*c1 + 8*EP2 + 24*t1*t1) * d**5/120) / math.cos(p1)
    return math.degrees(lat), math.degrees(lon)

def dbf(b):
    n, hlen, rlen = struct.unpack('<xxxxIHH', b[:12])
    fields, p = [], 32
    while b[p] != 0x0D:
        fields.append((b[p:p+11].split(b'\0')[0].decode('ascii', 'replace'), b[p+16])); p += 32
    rows = []
    for i in range(n):
        r = b[hlen + i*rlen: hlen + (i+1)*rlen]; o, row = 1, {}
        for name, ln in fields:
            row[name] = r[o:o+ln].decode('cp949', 'replace').strip(); o += ln
        rows.append(row)
    return rows

def shp(b):
    p, recs = 100, []
    while p + 8 <= len(b):
        _, clen = struct.unpack('>ii', b[p:p+8]); p += 8
        c = b[p:p+clen*2]; p += clen*2
        t = struct.unpack('<i', c[:4])[0] if len(c) >= 4 else 0
        if t == 1:
            recs.append([struct.unpack('<2d', c[4:20])])
        elif t in (3, 13, 23):
            np_, npt = struct.unpack('<ii', c[36:44]); base = 44 + 4*np_
            recs.append([struct.unpack('<2d', c[base+16*k: base+16*k+16]) for k in range(npt)])
        else:
            recs.append([])
    return recs

def simplify(pts, tol):  # Douglas-Peucker (미터 좌표)
    if len(pts) < 3: return pts
    keep = [False] * len(pts); keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        (x1, y1), (x2, y2) = pts[i], pts[j]
        dx, dy = x2 - x1, y2 - y1; L2 = dx*dx + dy*dy
        best, bi = 0, -1
        for k in range(i + 1, j):
            x, y = pts[k]
            if L2 == 0: d = math.hypot(x - x1, y - y1)
            else:
                t = max(0, min(1, ((x - x1)*dx + (y - y1)*dy) / L2))
                d = math.hypot(x - x1 - t*dx, y - y1 - t*dy)
            if d > best: best, bi = d, k
        if best > tol:
            keep[bi] = True; stack += [(i, bi), (bi, j)]
    return [p for p, k in zip(pts, keep) if k]

num = lambda s: float(s) if s and re.match(r'^-?[\d.eE+-]+$', s) else None
index, bad = [], []
for it in items:
    url = it.get('mntnfile', ''); name = it.get('mntnnm', '')
    m = re.search(r'/(\d+)\.zip$', url)
    if not m: bad.append((name, 'no file')); continue
    code = m.group(1)
    zp = os.path.join(cache, code + '.zip')
    if not os.path.exists(zp):
        try: data = get(url.replace('http://', 'https://'))
        except Exception as e: bad.append((name, f'download {e}')); continue
        open(zp, 'wb').write(data)
    try: z = zipfile.ZipFile(zp)
    except Exception as e: bad.append((name, f'zip {e}')); continue
    files = {n.rsplit('.', 1)[-1].lower() + ('W' if 'MT_WAY' in n.upper() else 'P' if 'WAY_POINT' in n.upper() else '?'): n for n in z.namelist()}
    if 'shpW' not in files or 'dbfW' not in files: bad.append((name, 'no trail shp: ' + ','.join(z.namelist())[:200])); continue
    lines, rows = shp(z.read(files['shpW'])), dbf(z.read(files['dbfW']))
    # 좌표계 확인: API의 지도 좌표(가산 500000 기준)와 등산로 중심이 20 km 안이어야 함
    allp = [p for l in lines for p in l]
    if not allp: bad.append((name, 'empty')); continue
    cx = sum(p[0] for p in allp) / len(allp); cy = sum(p[1] for p in allp) / len(allp)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(it.get('mntninfourl', '')).query)
    fn = 600000.0
    try:
        ax, ay = float(q['longitude'][0]), float(q['latitude'][0])
        if abs(cy - ay) > 50000 and abs(cy - (ay + 100000)) > 20000: bad.append((name, f'coord mismatch {cx:.0f},{cy:.0f} vs {ax:.0f},{ay:.0f}')); continue
        if abs(cy - ay) < 20000: fn = 500000.0  # 이 산은 500000 기준으로 저장됨
    except (KeyError, ValueError):
        pass
    segs = []
    for l, r in zip(lines, rows):
        if len(l) < 2: continue
        sl = simplify(l, 2.0)
        pts = [[round(a, 5) for a in tm2wgs(x, y, fn=fn)] for x, y in sl]
        d = num(r.get('SECTN_DSTN')) or num(r.get('Shape_Leng')) or 0
        segs.append({'p': pts, 'd': round(d), 'u': round(num(r.get('SECTN_UPLN')) or 0), 'w': round(num(r.get('SECTN_GNGD')) or 0),
                     'g': int(r.get('SECTN_DGDF') or 0) if (r.get('SECTN_DGDF') or '').isdigit() else 0})
    # 표지: 쓸모 있는 종류만 (앞에 있는 종류가 우선). 분기·시종점·계단·벤치 같은 건 너무 많아서 뺌
    CATS = [('PEAK', ('정상', '삼각점')), ('SIGN', ('이정표',)), ('DANGER', ('위험',)), ('TOILET', ('화장실',)),
            ('WATER', ('약수', '음수', '샘')), ('VIEW', ('조망', '전망')), ('REST', ('쉼터', '정자', '대피소')),
            ('PARK', ('주차장',)), ('HELI', ('헬기장',))]
    marks, seen = [], set()
    if 'shpP' in files and 'dbfP' in files:
        for pt, r in zip(shp(z.read(files['shpP'])), dbf(z.read(files['dbfP']))):
            if not pt: continue
            words = r.get('SYM_NAM2', '') + ',' + r.get('SYM_NAM', '')
            cat = next((c for c, ks in CATS if any(k in words for k in ks)), None)
            if not cat: continue
            lat, lng = tm2wgs(*pt[0], fn=fn)
            p = [round(lat, 5), round(lng, 5)]
            if (cat, round(p[0], 4), round(p[1], 4)) in seen: continue
            seen.add((cat, round(p[0], 4), round(p[1], 4)))
            nm = r.get('SYM_NAM', '').strip()
            mk = {'p': p, 'c': cat}
            if nm and nm not in ('기타', cat): mk['n'] = nm
            if r.get('SYM_TXT', '').strip(): mk['x'] = r['SYM_TXT'].strip()[:60]
            marks.append(mk)
    lats = [p[0] for s in segs for p in s['p']]; lngs = [p[1] for s in segs for p in s['p']]
    if not (33 < min(lats) and max(lats) < 39 and 124 < min(lngs) and max(lngs) < 132):
        bad.append((name, f'outside korea {min(lats)},{min(lngs)}')); continue
    json.dump({'m': name, 'code': code, 'segs': segs, 'marks': marks}, open(os.path.join(out, code + '.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, separators=(',', ':'))
    index.append({'m': name, 'code': code, 'b': [min(lats), min(lngs), max(lats), max(lngs)],
                  'km': round(sum(s['d'] for s in segs) / 1000, 1), 'n': len(segs), 'fn': int(fn)})
json.dump({'source': '산림청 등산로 정보 (공공데이터포털 trailInfoService)', 'mountains': index},
          open(os.path.join(out, 'index.json'), 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
print('ok', len(index), 'bad', len(bad))
for b in bad: print('BAD', b)
