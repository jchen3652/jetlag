/**
 * Path-proximity sampling for hiding zones.
 * Fast path: local equirectangular meters + segment grid index.
 */

export const RULE_FT = 10;
export const RULE_M = RULE_FT * 0.3048;

const HALF_WIDTH_M = {
  trunk: 10,
  trunk_link: 7,
  primary: 8,
  primary_link: 6,
  secondary: 6,
  secondary_link: 5,
  tertiary: 5,
  tertiary_link: 4,
  residential: 4,
  living_street: 3,
  unclassified: 4,
  service: 3,
  road: 4,
  track: 2,
  pedestrian: 2,
  footway: 1,
  path: 1,
  steps: 1,
  cycleway: 1.5,
  bridleway: 1.5,
  corridor: 1,
  platform: 2,
  crossing: 1,
  busway: 4,
};

export function bufferMeters(highway, mode) {
  if (mode === 'strict') return RULE_M;
  return (HALF_WIDTH_M[highway] ?? 3) + RULE_M;
}

export function makeLocalProj(originLat, originLng) {
  const lat0 = (originLat * Math.PI) / 180;
  const mPerDegLat = 111320;
  const mPerDegLng = 111320 * Math.cos(lat0);
  return {
    toXY(lat, lng) {
      return [(lng - originLng) * mPerDegLng, (lat - originLat) * mPerDegLat];
    },
    toLatLng(x, y) {
      return [originLat + y / mPerDegLat, originLng + x / mPerDegLng];
    },
  };
}

function distPointToSeg2(px, py, ax, ay, bx, by) {
  const dx = bx - ax;
  const dy = by - ay;
  const len2 = dx * dx + dy * dy;
  if (len2 === 0) {
    const ex = px - ax;
    const ey = py - ay;
    return ex * ex + ey * ey;
  }
  let t = ((px - ax) * dx + (py - ay) * dy) / len2;
  if (t < 0) t = 0;
  else if (t > 1) t = 1;
  const qx = ax + t * dx;
  const qy = ay + t * dy;
  const ex = px - qx;
  const ey = py - qy;
  return ex * ex + ey * ey;
}

/** Build segments + uniform grid for O(1) candidate lookup. */
export function buildSegments(features, originLat, originLng, mode, cellSize = 40) {
  const proj = makeLocalProj(originLat, originLng);
  const segs = [];

  const addLine = (coords, highway) => {
    const buf = bufferMeters(highway, mode);
    for (let i = 0; i < coords.length - 1; i++) {
      const [lng1, lat1] = coords[i];
      const [lng2, lat2] = coords[i + 1];
      const [ax, ay] = proj.toXY(lat1, lng1);
      const [bx, by] = proj.toXY(lat2, lng2);
      segs.push({ ax, ay, bx, by, buf, buf2: buf * buf });
    }
  };

  for (const f of features) {
    const highway = f.properties?.highway || 'unknown';
    const g = f.geometry;
    if (!g) continue;
    if (g.type === 'LineString') addLine(g.coordinates, highway);
    else if (g.type === 'MultiLineString') {
      for (const line of g.coordinates) addLine(line, highway);
    }
  }

  // Grid index
  const grid = new Map();
  const key = (ix, iy) => ix + ',' + iy;
  for (let i = 0; i < segs.length; i++) {
    const s = segs[i];
    const minx = Math.min(s.ax, s.bx) - s.buf;
    const maxx = Math.max(s.ax, s.bx) + s.buf;
    const miny = Math.min(s.ay, s.by) - s.buf;
    const maxy = Math.max(s.ay, s.by) + s.buf;
    const x0 = Math.floor(minx / cellSize);
    const x1 = Math.floor(maxx / cellSize);
    const y0 = Math.floor(miny / cellSize);
    const y1 = Math.floor(maxy / cellSize);
    for (let ix = x0; ix <= x1; ix++) {
      for (let iy = y0; iy <= y1; iy++) {
        const k = key(ix, iy);
        let arr = grid.get(k);
        if (!arr) {
          arr = [];
          grid.set(k, arr);
        }
        arr.push(i);
      }
    }
  }

  return { segs, proj, grid, cellSize, key };
}

export function isNearPath(x, y, index) {
  const { segs, grid, cellSize, key } = index;
  if (!segs.length) return false;
  const ix = Math.floor(x / cellSize);
  const iy = Math.floor(y / cellSize);
  const cand = grid.get(key(ix, iy));
  if (!cand || !cand.length) return false;
  for (let c = 0; c < cand.length; c++) {
    const s = segs[cand[c]];
    if (x < Math.min(s.ax, s.bx) - s.buf || x > Math.max(s.ax, s.bx) + s.buf) continue;
    if (y < Math.min(s.ay, s.by) - s.buf || y > Math.max(s.ay, s.by) + s.buf) continue;
    if (distPointToSeg2(x, y, s.ax, s.ay, s.bx, s.by) <= s.buf2) return true;
  }
  return false;
}

export function sampleZone({
  centerLat,
  centerLng,
  radiusM,
  pathFeatures,
  mode = 'practical',
  n = 5000,
  seed = 1,
}) {
  const index = buildSegments(pathFeatures, centerLat, centerLng, mode);
  const { proj, segs } = index;

  let t = seed >>> 0;
  const rand = () => {
    t += 0x6d2b79f5;
    let r = Math.imul(t ^ (t >>> 15), 1 | t);
    r ^= r + Math.imul(r ^ (r >>> 7), 61 | r);
    return ((r ^ (r >>> 14)) >>> 0) / 4294967296;
  };

  const points = [];
  let hits = 0;
  // For large n, only store every k-th point for viz (cap markers)
  const maxDraw = 2500;
  const drawEvery = n > maxDraw ? Math.ceil(n / maxDraw) : 1;

  for (let i = 0; i < n; i++) {
    const rr = radiusM * Math.sqrt(rand());
    const th = rand() * Math.PI * 2;
    const x = rr * Math.cos(th);
    const y = rr * Math.sin(th);
    const ok = segs.length ? isNearPath(x, y, index) : false;
    if (ok) hits++;
    if (i % drawEvery === 0) {
      const [lat, lng] = proj.toLatLng(x, y);
      points.push({ lat, lng, ok });
    }
  }

  const zoneAreaM2 = Math.PI * radiusM * radiusM;
  const hitFrac = hits / n;
  return {
    points,
    hits,
    n,
    hitFrac,
    estimatedHideableAreaM2: hitFrac * zoneAreaM2,
    zoneAreaM2,
    segmentCount: segs.length,
    mode,
    bufferNote: mode === 'strict' ? `${RULE_FT} ft from centerline` : 'half-width + 10 ft',
    drawnPoints: points.length,
  };
}

export function filterFeaturesInBbox(features, west, south, east, north) {
  const out = [];
  for (const f of features) {
    const g = f.geometry;
    if (!g) continue;
    const coordsLists =
      g.type === 'LineString' ? [g.coordinates] : g.type === 'MultiLineString' ? g.coordinates : [];
    let keep = false;
    for (const line of coordsLists) {
      for (let i = 0; i < line.length; i++) {
        const lng = line[i][0];
        const lat = line[i][1];
        if (lng >= west && lng <= east && lat >= south && lat <= north) {
          keep = true;
          break;
        }
      }
      if (keep) break;
    }
    if (keep) out.push(f);
  }
  return out;
}

export function bboxAround(lat, lng, radiusM) {
  const dLat = radiusM / 111320;
  const dLng = radiusM / (111320 * Math.cos((lat * Math.PI) / 180));
  const pad = 1.15;
  return {
    west: lng - dLng * pad,
    south: lat - dLat * pad,
    east: lng + dLng * pad,
    north: lat + dLat * pad,
  };
}
