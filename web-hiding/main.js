import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import {
  sampleZone,
  filterFeaturesInBbox,
  bboxAround,
  RULE_M,
} from './pathProximity.js';

// ---------------------------------------------------------------------------
// Official Lifack radii
// ---------------------------------------------------------------------------
const METERS_PER_MILE = 1609.344;

const GAME_SIZES = {
  small: { id: 'small', label: 'Small', zoneMiles: 0.25, hideMinutes: 30, tentacles: false },
  medium: { id: 'medium', label: 'Medium', zoneMiles: 0.25, hideMinutes: 60, tentacles: true, tentacleMiles: 1 },
  large: { id: 'large', label: 'Large', zoneMiles: 0.5, hideMinutes: 180, tentacles: true, tentacleMiles: 1 },
};

const RADAR_MILES = [0.25, 0.5, 1, 3, 5, 10, 25, 50, 100];
const TENTACLE_MEDIUM_CATS = ['Museums', 'Libraries', 'Cinemas', 'Hospitals'];
const START = { lat: 47.6073, lng: -122.3381, name: 'Seattle Art Museum (start)' };

delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
});

const map = L.map('map').setView([47.61, -122.33], 11);

map.createPane('zones');
map.getPane('zones').style.zIndex = 350;
map.getPane('zones').style.pointerEvents = 'none';
map.createPane('radars');
map.getPane('radars').style.zIndex = 340;
map.getPane('radars').style.pointerEvents = 'none';
map.createPane('samples');
map.getPane('samples').style.zIndex = 450;
map.createPane('paths');
map.getPane('paths').style.zIndex = 330;
map.getPane('paths').style.pointerEvents = 'none';

let currentBasemap = null;
const basemaps = {
  colorful: L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap contributors',
  }),
  light: L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
    attribution: '&copy; OpenStreetMap &copy; CARTO',
  }),
};
function setBasemap(type) {
  if (currentBasemap) map.removeLayer(currentBasemap);
  currentBasemap = basemaps[type].addTo(map);
}
setBasemap('light');

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
let gameSize = GAME_SIZES.medium;
let bufferMode = 'practical'; // practical | strict
let stops = [];
let parks = [];
let tentaclePois = [];
let pathFeatures = []; // GeoJSON features
let hideableScores = null; // precomputed JSON
let hideableIndex = new Map(); // key lat,lng rounded -> score rec

let stopsLayer = null;
let routesLayer = null;
let startLayer = null;
let parksLayer = null;
let tentacleLayer = null;
let pathsLayer = null;
let samplesLayer = L.layerGroup().addTo(map);

let zoneOverlays = [];
let radarOverlays = [];
let selectedStop = null;
let armRadarClick = false;
let enabledModes = new Set(['Link', 'Monorail', 'RapidRide']);
let lastSampleResult = null;

// ---------------------------------------------------------------------------
// Geometry
// ---------------------------------------------------------------------------
function haversineMeters(a, b) {
  const R = 6371008.8;
  const toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const lat1 = toRad(a.lat);
  const lat2 = toRad(b.lat);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}

function milesToMeters(mi) {
  return mi * METERS_PER_MILE;
}

function zoneRadiusMeters() {
  return milesToMeters(gameSize.zoneMiles);
}

function zoneKeyForGameSize() {
  return gameSize.zoneMiles >= 0.5 ? 'large' : 'small_medium';
}

function updateZoneReadout() {
  const el = document.getElementById('zone-radius-readout');
  if (!el) return;
  const m = zoneRadiusMeters();
  el.textContent = `Zone radius: ${gameSize.zoneMiles} mi = ${m.toFixed(3)} m · hide ${gameSize.hideMinutes} min · buffer ${bufferMode}`;
}

function scoreKey(lat, lng) {
  return `${lat.toFixed(5)},${lng.toFixed(5)}`;
}

// ---------------------------------------------------------------------------
// Layers
// ---------------------------------------------------------------------------
function modeColor(mode) {
  if (mode === 'Link') return '#3b82f6';
  if (mode === 'RapidRide') return '#f59e0b';
  if (mode === 'Monorail') return '#10b981';
  return '#9ca3af';
}

function rebuildStopsLayer() {
  if (stopsLayer) {
    map.removeLayer(stopsLayer);
    stopsLayer = null;
  }
  const visible = stops.filter((s) => enabledModes.has(s.mode));
  stopsLayer = L.layerGroup();
  visible.forEach((s) => {
    const marker = L.circleMarker(s.latlng, {
      radius: s.mode === 'Link' ? 7 : 5,
      fillColor: modeColor(s.mode),
      color: '#111827',
      weight: 1.2,
      fillOpacity: 0.92,
    });
    marker.bindPopup(`<strong>${s.name}</strong><br>${s.mode}${s.route ? ' — ' + s.route : ''}`);
    marker.on('click', (e) => {
      L.DomEvent.stopPropagation(e);
      selectStop(s);
    });
    stopsLayer.addLayer(marker);
  });
  if (document.getElementById('toggle-stops')?.checked) stopsLayer.addTo(map);
}

function selectStop(stop) {
  selectedStop = stop;
  drawZoneForStop(stop, { focus: true });
  renderStationDetail(stop);
  // Auto-sample path proximity when paths available
  if (pathFeatures.length) {
    runSampleForStop(stop);
  } else {
    setSampleStatus('Path data not loaded yet — run scripts/export_walkable_paths.py');
  }
  // On mobile, after picking from the list, close drawer so map + Menu FAB stay obvious
  if (isMobileLayout() && document.getElementById('sidebar')?.classList.contains('open')) {
    // keep open if user is still browsing list; only close when they sample/focus zone
    // Closing helps them see the zone they selected
    closeDrawer();
  }
}

function drawZoneForStop(stop, { focus = false } = {}) {
  zoneOverlays = zoneOverlays.filter((z) => {
    if (z.stopId === stop.id) {
      map.removeLayer(z.circle);
      if (z.labelMarker) map.removeLayer(z.labelMarker);
      return false;
    }
    return true;
  });

  const r = zoneRadiusMeters();
  const circle = L.circle(stop.latlng, {
    radius: r,
    color: '#22c55e',
    weight: 2.5,
    fillColor: '#22c55e',
    fillOpacity: 0.1,
    interactive: false,
    pane: 'zones',
  }).addTo(map);

  const labelMarker = L.marker(stop.latlng, {
    interactive: false,
    icon: L.divIcon({
      className: 'zone-label',
      html: `<div style="
        background:rgba(17,24,39,0.88);color:#86efac;border:1px solid #22c55e;
        padding:2px 6px;border-radius:4px;font-size:11px;white-space:nowrap;
        transform:translate(-50%,-120%);
      ">${stop.name} · ${gameSize.zoneMiles} mi</div>`,
    }),
  }).addTo(map);

  zoneOverlays.push({ stopId: stop.id, circle, labelMarker, stop });
  if (focus) map.fitBounds(circle.getBounds().pad(0.35));
}

function clearSamples() {
  samplesLayer.clearLayers();
  lastSampleResult = null;
  setSampleStatus('');
}

function clearZones() {
  zoneOverlays.forEach((z) => {
    map.removeLayer(z.circle);
    if (z.labelMarker) map.removeLayer(z.labelMarker);
  });
  zoneOverlays = [];
  selectedStop = null;
  clearSamples();
  document.getElementById('station-detail').innerHTML = '<p class="empty">No station selected</p>';
}

function clearRadars() {
  radarOverlays.forEach((r) => map.removeLayer(r));
  radarOverlays = [];
}

function addRadar(center, miles, label) {
  const circle = L.circle(center, {
    radius: milesToMeters(miles),
    color: '#38bdf8',
    weight: 1.5,
    fillColor: '#38bdf8',
    fillOpacity: 0.06,
    dashArray: '6 4',
    interactive: false,
    pane: 'radars',
  }).addTo(map);
  radarOverlays.push(circle);
}

function setSampleStatus(msg) {
  const el = document.getElementById('sample-status');
  if (el) el.textContent = msg || '';
  // Mirror a short line onto the fixed mobile chip (never pans with the map)
  const chip = document.getElementById('mobile-status-chip');
  if (chip) {
    if (!msg) {
      chip.hidden = true;
      chip.textContent = '';
    } else {
      chip.hidden = false;
      chip.textContent = String(msg).split('·')[0].trim().slice(0, 90);
    }
  }
}

function runSampleForStop(stop) {
  if (!pathFeatures.length) {
    setSampleStatus('No walkable path data. Export first.');
    return;
  }
  const n = Math.max(50, Math.min(50000, parseInt(document.getElementById('sample-n').value, 10) || 20000));
  const radiusM = zoneRadiusMeters();
  const bb = bboxAround(stop.lat, stop.lng, radiusM + 40);
  const localPaths = filterFeaturesInBbox(pathFeatures, bb.west, bb.south, bb.east, bb.north);

  setSampleStatus(`Sampling ${n} points against ${localPaths.length} nearby path segments…`);

  // yield to UI
  requestAnimationFrame(() => {
    const t0 = performance.now();
    const result = sampleZone({
      centerLat: stop.lat,
      centerLng: stop.lng,
      radiusM,
      pathFeatures: localPaths,
      mode: bufferMode,
      n,
      seed: Math.abs(hashStr(stop.id + bufferMode + gameSize.id)) || 1,
    });
    lastSampleResult = { stop, result };
    drawSamplePoints(result.points);
    const ms = (performance.now() - t0).toFixed(0);
    const ha = result.estimatedHideableAreaM2 / 10000;
    const drawn = result.drawnPoints != null ? result.drawnPoints : result.points.length;
    setSampleStatus(
      `${result.hits}/${result.n} near path (${(result.hitFrac * 100).toFixed(1)}%) · ` +
        `~${ha.toFixed(2)} ha · ${result.segmentCount} segs · draw ${drawn} · ${ms}ms · ${bufferMode}`
    );
    renderStationDetail(stop);
  });
}

function hashStr(s) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (Math.imul(31, h) + s.charCodeAt(i)) | 0;
  return h;
}

function drawSamplePoints(points) {
  samplesLayer.clearLayers();
  const show = document.getElementById('toggle-samples')?.checked !== false;
  points.forEach((p) => {
    const m = L.circleMarker([p.lat, p.lng], {
      radius: 3,
      color: p.ok ? '#14532d' : '#7f1d1d',
      weight: 0.5,
      fillColor: p.ok ? '#22c55e' : '#ef4444',
      fillOpacity: 0.85,
      pane: 'samples',
      interactive: false,
    });
    samplesLayer.addLayer(m);
  });
  if (!show) map.removeLayer(samplesLayer);
  else if (!map.hasLayer(samplesLayer)) samplesLayer.addTo(map);
}

// ---------------------------------------------------------------------------
// Analysis / ranking
// ---------------------------------------------------------------------------
function precomputedForStop(stop) {
  if (!hideableIndex.size) return null;
  // exact then fuzzy
  let rec = hideableIndex.get(scoreKey(stop.lat, stop.lng));
  if (rec) return rec;
  // nearest by name+mode within 30m
  let best = null;
  let bestD = Infinity;
  for (const s of hideableScores?.stops || []) {
    if (s.stop_name !== stop.name) continue;
    const d = haversineMeters(stop, { lat: s.lat, lng: s.lng });
    if (d < bestD) {
      bestD = d;
      best = s;
    }
  }
  return bestD < 40 ? best : null;
}

function analyzeStop(stop) {
  // ONLY metric: hideable fraction of zone (path-adjacent sample hits)
  const pre = precomputedForStop(stop);
  const zkey = zoneKeyForGameSize();
  let hideableAreaM2 = null;
  let hideableFrac = null;
  let sampleN = null;
  let source = null;

  // Live sample for selected station wins if present
  if (lastSampleResult?.stop?.id === stop.id) {
    hideableFrac = lastSampleResult.result.hitFrac;
    hideableAreaM2 = lastSampleResult.result.estimatedHideableAreaM2;
    sampleN = lastSampleResult.result.n;
    source = 'live sample';
  } else if (pre?.zones?.[zkey]?.[bufferMode]) {
    hideableFrac = pre.zones[zkey][bufferMode].hideable_frac;
    hideableAreaM2 = pre.zones[zkey][bufferMode].hideable_area_m2;
    sampleN = pre.zones[zkey].n_samples || null;
    source = 'precomputed';
  }

  // Rank score = fraction only (0–100 display as percent)
  const score = hideableFrac != null ? hideableFrac * 100 : -1;

  return {
    stop,
    score,
    hideableAreaM2,
    hideableFrac,
    sampleN,
    source,
    zoneMiles: gameSize.zoneMiles,
  };
}

function renderStationDetail(stop) {
  const a = analyzeStop(stop);
  const el = document.getElementById('station-detail');
  const zoneArea = Math.PI * zoneRadiusMeters() ** 2;
  const fracLabel =
    a.hideableFrac != null ? `${(a.hideableFrac * 100).toFixed(1)}%` : '—';
  const areaLabel =
    a.hideableAreaM2 != null ? `${(a.hideableAreaM2 / 1e4).toFixed(3)} ha` : '—';

  el.innerHTML = `
    <div style="margin-bottom:6px">
      <strong>${stop.name}</strong><br>
      <span style="color:#9ca3af">${stop.mode}${stop.route ? ' · ' + stop.route : ''}</span>
    </div>
    <div class="metric"><span>Zone radius</span><span>${a.zoneMiles} mi (${zoneRadiusMeters().toFixed(1)} m)</span></div>
    <div class="metric"><span>Zone area</span><span>${(zoneArea / 1e4).toFixed(2)} ha</span></div>
    <div class="metric"><span><strong>Hideable fraction</strong></span><span><strong>${fracLabel}</strong></span></div>
    <div class="metric"><span>≈ hideable area</span><span>${areaLabel}</span></div>
    <div class="metric"><span>Buffer mode</span><span>${bufferMode}</span></div>
    <div class="metric"><span>Score source</span><span>${a.source || 'none yet'}${a.sampleN ? ` (n=${a.sampleN})` : ''}</span></div>
    <p style="margin:8px 0 0;font-size:0.72rem;color:#6b7280;line-height:1.35">
      <strong>Only metric:</strong> share of the zone disk near a marked path (green samples).
      Green = in path buffer · red = not. Not a stayability / public-access check.
    </p>
  `;
}

function recomputeScores() {
  const candidates = stops.filter((s) => enabledModes.has(s.mode));
  const ranked = candidates
    .map(analyzeStop)
    .sort((a, b) => {
      // Scored first (high → low); unscored at the bottom
      const af = a.hideableFrac;
      const bf = b.hideableFrac;
      if (af == null && bf == null) return a.stop.name.localeCompare(b.stop.name);
      if (af == null) return 1;
      if (bf == null) return -1;
      return bf - af;
    });
  const board = document.getElementById('scoreboard');
  const hint = document.getElementById('rank-hint');
  const nScored = ranked.filter((r) => r.hideableFrac != null).length;
  if (hint) {
    hint.textContent = hideableScores
      ? `All ${ranked.length} stops (${nScored} scored) · ${bufferMode} · ${zoneKeyForGameSize()} · best → worst.`
      : `All ${ranked.length} stops — no precomputed scores yet. Run score_hideable_fraction.py`;
  }

  if (!ranked.length) {
    board.innerHTML = '<p class="empty">No stations for selected modes</p>';
    return;
  }

  board.innerHTML = ranked
    .map((row, i) => {
      const s = row.stop;
      const has = row.hideableFrac != null;
      const frac = has ? `${(row.hideableFrac * 100).toFixed(1)}%` : '—';
      const area =
        row.hideableAreaM2 != null ? `≈${(row.hideableAreaM2 / 1e4).toFixed(2)} ha` : 'no score';
      const bad = has && row.hideableFrac < 0.1;
      return `
        <div class="score-row${bad ? ' score-bad' : ''}${!has ? ' score-missing' : ''}" data-id="${s.id}">
          <div class="rank">#${i + 1}</div>
          <div class="name" title="${s.name}">${s.name}</div>
          <div class="score">${frac}</div>
          <div class="meta">${s.mode} · ${area} · ${bufferMode}</div>
        </div>`;
    })
    .join('');

  board.querySelectorAll('.score-row').forEach((row) => {
    row.addEventListener('click', () => {
      const stop = stops.find((s) => s.id === row.dataset.id);
      if (stop) selectStop(stop);
    });
  });
}

// ---------------------------------------------------------------------------
// Load
// ---------------------------------------------------------------------------
async function loadData() {
  const base = import.meta.env.BASE_URL || '/';
  setSampleStatus('Loading transit + attractions…');

  const [stopsData, routesData, attractionsData] = await Promise.all([
    fetch(`${base}data/transit_stops.geojson`).then((r) => r.json()),
    fetch(`${base}data/transit_routes.geojson`).then((r) => r.json()),
    fetch(`${base}data/seattle_attractions.geojson`).then((r) => r.json()),
  ]);

  // Optional path / score assets (may not exist until export finishes)
  const [pathsRes, scoresRes] = await Promise.all([
    fetch(`${base}data/walkable_paths.geojson`).then((r) => (r.ok ? r.json() : null)).catch(() => null),
    fetch(`${base}data/zone_hideable_scores.json`).then((r) => (r.ok ? r.json() : null)).catch(() => null),
  ]);

  stops = stopsData.features.map((f, i) => {
    const [lng, lat] = f.geometry.coordinates;
    const name = f.properties.stop_name || 'Unnamed';
    const mode = f.properties.mode || 'Unknown';
    return {
      id: `${mode}:${name}:${lat.toFixed(5)},${lng.toFixed(5)}:${i}`,
      name,
      mode,
      route: f.properties.route || '',
      lat,
      lng,
      latlng: [lat, lng],
    };
  });

  const attractions = attractionsData.features.map((f) => {
    const [lng, lat] = f.geometry.coordinates;
    return {
      name: f.properties.name || 'Unnamed',
      category: f.properties.category,
      lat,
      lng,
      latlng: [lat, lng],
    };
  });
  parks = attractions.filter((a) => a.category === 'Parks');
  tentaclePois = attractions.filter((a) => TENTACLE_MEDIUM_CATS.includes(a.category));

  if (pathsRes?.features) {
    pathFeatures = pathsRes.features;
    pathsLayer = L.geoJSON(pathsRes, {
      style: { color: '#64748b', weight: 1.2, opacity: 0.55 },
      interactive: false,
      pane: 'paths',
    });
    setSampleStatus(`Loaded ${pathFeatures.length.toLocaleString()} walkable path features.`);
  } else {
    setSampleStatus('walkable_paths.geojson missing — export still running or not run.');
  }

  if (scoresRes?.stops) {
    hideableScores = scoresRes;
    hideableIndex = new Map();
    for (const s of scoresRes.stops) {
      hideableIndex.set(scoreKey(s.lat, s.lng), s);
    }
  }

  routesLayer = L.geoJSON(routesData, {
    style: { color: '#f59e0b', weight: 2, opacity: 0.55 },
    interactive: false,
  });

  startLayer = L.layerGroup([
    L.circleMarker(START, {
      radius: 9,
      color: '#7f1d1d',
      weight: 2,
      fillColor: '#ef4444',
      fillOpacity: 0.9,
    }).bindPopup(`<strong>${START.name}</strong>`),
  ]).addTo(map);

  parksLayer = L.layerGroup(
    parks.map((p) =>
      L.circleMarker(p.latlng, {
        radius: 3,
        fillColor: '#16a34a',
        color: '#052e16',
        weight: 0.5,
        fillOpacity: 0.7,
      }).bindPopup(`<strong>${p.name}</strong><br>Park`)
    )
  );

  tentacleLayer = L.layerGroup(
    tentaclePois.map((p) =>
      L.circleMarker(p.latlng, {
        radius: 5,
        fillColor: '#a855f7',
        color: '#111827',
        weight: 1,
        fillOpacity: 0.85,
      }).bindPopup(`<strong>${p.name}</strong><br>${p.category}`)
    )
  );

  rebuildStopsLayer();
  buildModeFilters();
  buildRadarButtons();
  updateZoneReadout();
  recomputeScores();
  wireUi();
}

function wireUi() {
  document.querySelectorAll('input[name="basemap"]').forEach((radio) => {
    radio.addEventListener('change', () => {
      if (radio.checked) setBasemap(radio.value);
    });
  });

  document.querySelectorAll('input[name="game-size"]').forEach((radio) => {
    radio.addEventListener('change', () => {
      if (!radio.checked) return;
      gameSize = GAME_SIZES[radio.value];
      updateZoneReadout();
      const kept = zoneOverlays.map((z) => z.stop);
      clearZones();
      kept.forEach((s) => {
        drawZoneForStop(s, { focus: false });
      });
      if (kept.length) {
        selectedStop = kept[kept.length - 1];
        selectStop(selectedStop);
      }
      recomputeScores();
    });
  });

  document.querySelectorAll('input[name="buffer-mode"]').forEach((radio) => {
    radio.addEventListener('change', () => {
      if (!radio.checked) return;
      bufferMode = radio.value;
      updateZoneReadout();
      if (selectedStop && pathFeatures.length) runSampleForStop(selectedStop);
      recomputeScores();
    });
  });

  document.getElementById('toggle-stops').onchange = (e) => {
    e.target.checked ? stopsLayer.addTo(map) : map.removeLayer(stopsLayer);
  };
  document.getElementById('toggle-routes').onchange = (e) => {
    e.target.checked ? routesLayer.addTo(map) : map.removeLayer(routesLayer);
  };
  document.getElementById('toggle-start').onchange = (e) => {
    e.target.checked ? startLayer.addTo(map) : map.removeLayer(startLayer);
  };
  document.getElementById('toggle-parks').onchange = (e) => {
    e.target.checked ? parksLayer.addTo(map) : map.removeLayer(parksLayer);
  };
  document.getElementById('toggle-tentacle-pois').onchange = (e) => {
    e.target.checked ? tentacleLayer.addTo(map) : map.removeLayer(tentacleLayer);
  };
  document.getElementById('toggle-paths').onchange = (e) => {
    if (!pathsLayer) return;
    e.target.checked ? pathsLayer.addTo(map) : map.removeLayer(pathsLayer);
  };
  document.getElementById('toggle-samples').onchange = (e) => {
    e.target.checked ? samplesLayer.addTo(map) : map.removeLayer(samplesLayer);
  };

  document.getElementById('clear-zones').onclick = clearZones;
  document.getElementById('clear-radars').onclick = clearRadars;
  document.getElementById('clear-samples').onclick = clearSamples;
  document.getElementById('recompute-scores').onclick = recomputeScores;
  document.getElementById('sample-selected').onclick = () => {
    if (!selectedStop) {
      alert('Select a station first');
      return;
    }
    runSampleForStop(selectedStop);
  };

  const armBtn = document.getElementById('arm-radar-map-click');
  armBtn.onclick = () => {
    armRadarClick = !armRadarClick;
    armBtn.classList.toggle('active', armRadarClick);
    map.getContainer().style.cursor = armRadarClick ? 'crosshair' : '';
  };
  map.on('click', (e) => {
    if (!armRadarClick) return;
    addRadar(e.latlng, 1, '1 mi radar');
  });
}

function buildModeFilters() {
  const box = document.getElementById('mode-filters');
  const modes = [...new Set(stops.map((s) => s.mode))].sort();
  box.innerHTML = '';
  modes.forEach((mode) => {
    const count = stops.filter((s) => s.mode === mode).length;
    const btn = document.createElement('button');
    btn.textContent = `${mode} (${count})`;
    btn.className = enabledModes.has(mode) ? '' : 'off';
    btn.onclick = () => {
      if (enabledModes.has(mode)) enabledModes.delete(mode);
      else enabledModes.add(mode);
      btn.className = enabledModes.has(mode) ? '' : 'off';
      rebuildStopsLayer();
      recomputeScores();
    };
    box.appendChild(btn);
  });
}

function buildRadarButtons() {
  const box = document.getElementById('radar-buttons');
  box.innerHTML = '';
  RADAR_MILES.forEach((mi) => {
    const btn = document.createElement('button');
    btn.textContent = `${mi} mi`;
    btn.onclick = () => {
      if (selectedStop) addRadar(selectedStop.latlng, mi, `${selectedStop.name} · ${mi} mi`);
      else alert('Select a station first');
    };
    box.appendChild(btn);
  });
}

// ---------------------------------------------------------------------------
// Mobile chrome — fixed FAB always reachable while panning the map
// ---------------------------------------------------------------------------
function isMobileLayout() {
  return window.matchMedia('(max-width: 768px)').matches;
}

function setDrawerOpen(open) {
  const sidebar = document.getElementById('sidebar');
  const backdrop = document.getElementById('sidebar-backdrop');
  const toggle = document.getElementById('mobile-menu-toggle');
  if (!sidebar) return;

  sidebar.classList.toggle('open', open);
  document.body.classList.toggle('drawer-open', open);

  if (backdrop) {
    backdrop.hidden = !open;
    backdrop.setAttribute('aria-hidden', open ? 'false' : 'true');
  }
  if (toggle) {
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    toggle.setAttribute('aria-label', open ? 'Close menu' : 'Open menu');
  }

  // Block map interaction under the drawer on mobile
  const mapEl = document.getElementById('map');
  if (mapEl && isMobileLayout()) {
    mapEl.style.pointerEvents = open ? 'none' : '';
  }
}

function closeDrawer() {
  setDrawerOpen(false);
}

function openDrawer() {
  setDrawerOpen(true);
}

function initMobileMenu() {
  const sidebar = document.getElementById('sidebar');
  const toggle = document.getElementById('mobile-menu-toggle');
  const closeBtn = document.getElementById('mobile-menu-close');
  const doneBtn = document.getElementById('mobile-menu-done');
  const backdrop = document.getElementById('sidebar-backdrop');
  if (!toggle || !sidebar) return;

  toggle.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    const open = !sidebar.classList.contains('open');
    setDrawerOpen(open);
  });

  const closer = (e) => {
    e?.preventDefault?.();
    e?.stopPropagation?.();
    closeDrawer();
  };
  closeBtn?.addEventListener('click', closer);
  doneBtn?.addEventListener('click', closer);
  backdrop?.addEventListener('click', closer);

  // Escape closes drawer
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && sidebar.classList.contains('open')) closeDrawer();
  });

  // After picking a station from the scoreboard on mobile, keep drawer open
  // briefly is fine; user closes with Done. Don't auto-close on map pan.

  // If user rotates to desktop, force drawer closed and restore map events
  window.matchMedia('(max-width: 768px)').addEventListener('change', (ev) => {
    if (!ev.matches) {
      setDrawerOpen(false);
      const mapEl = document.getElementById('map');
      if (mapEl) mapEl.style.pointerEvents = '';
    }
  });

  // Lighter default sample count on phones (still editable)
  if (isMobileLayout()) {
    const sn = document.getElementById('sample-n');
    if (sn && Number(sn.value) > 3000) sn.value = '3000';
  }
}

initMobileMenu();

// Move Leaflet zoom control after map exists (called from loadData)
function placeLeafletControlsForMobile() {
  if (!isMobileLayout()) return;
  try {
    // Zoom already top-left by default; CSS moves it. Ensure attribution is compact.
    map.attributionControl?.setPrefix?.(false);
  } catch (_) {
    /* ignore */
  }
}

loadData()
  .then(() => {
    placeLeafletControlsForMobile();
    // Invalidate size after layout (mobile absolute map)
    setTimeout(() => map.invalidateSize(), 100);
    window.addEventListener('resize', () => {
      map.invalidateSize();
    });
  })
  .catch((err) => {
    console.error(err);
    document.getElementById('sidebar').insertAdjacentHTML(
      'beforeend',
      `<p style="color:#f87171">Failed to load data: ${err.message}</p>`
    );
  });

