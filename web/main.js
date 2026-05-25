import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { Delaunay } from 'd3-delaunay';

// Mirror of CATEGORY_COLORS from jetlag/attractions.py
const CATEGORY_COLORS = {
  "Parks": "#2E8B57",
  "Museums": "#8B4513",
  "Zoos": "#556B2F",
  "Aquariums": "#4682B4",
  "Golf Courses": "#006400",
  "Cinemas": "#4B0082",
  "Libraries": "#DAA520",
  "Hospitals": "#DC143C",
  "Foreign Consulates": "#483D8B",
};

// Fix default marker icons for Vite
delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon-2x.png',
  iconUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-icon.png',
  shadowUrl: 'https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/images/marker-shadow.png',
});

const map = L.map('map').setView([47.61, -122.33], 11);

L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);

// Dedicated pane for non-interactive overlays (Voronoi, halos, geometric circles).
// We put it *below* the default overlayPane (z=400) so that transit stops and
// attraction markers are always on top and remain clickable even when circles
// are drawn near or over them.
map.createPane('nonInteractiveOverlays');
map.getPane('nonInteractiveOverlays').style.pointerEvents = 'none';
map.getPane('nonInteractiveOverlays').style.zIndex = 350;   // below default data layers


let stopsLayer = null;
let routesLayer = null;
let walkshedLayer = null;
const attractionLayers = {};

// Raw data for bulk selection
let allStopsFeatures = [];
let allAttractionsFeatures = [];

// Voronoi layers per category
const voronoiLayers = {};
const voronoiPoints = {};           // attraction categories

// Visual feedback for selections
let selectedHighlightGroup = L.layerGroup();
selectedHighlightGroup.addTo(map);  // children explicitly use nonInteractiveOverlays pane

// === Selection & Geometric Overlays ===
let selectedFeatures = [];           // [{id, name, latlng, properties, source: 'stop'|'attraction'}]
let geometricOverlays = [];          // [{id, type: 'circle', center, radiusMiles, radiusMeters, layer, label}]
let drawCircleMode = false;

let nextId = 1;

function selectFeature(feature, latlng, source, name) {
  const id = `${source}-${feature.properties.stop_name || feature.properties.name || nextId++}`;

  // Toggle: if already selected, deselect it
  const existingIndex = selectedFeatures.findIndex(f => f.id === id);
  if (existingIndex !== -1) {
    // Deselect
    selectedFeatures.splice(existingIndex, 1);
    // Remove highlight
    selectedHighlightGroup.eachLayer(l => {
      if (l.options._selectionId === id) {
        selectedHighlightGroup.removeLayer(l);
      }
    });
    updateSelectedUI();
    return;
  }

  // Select
  const displayName = name || feature.properties.stop_name || feature.properties.name || "Unnamed";

  selectedFeatures.push({
    id,
    name: displayName,
    latlng,
    properties: feature.properties,
    source
  });

  // Add visual feedback on the map (bright halo)
  const halo = L.circleMarker(latlng, {
    radius: 9,
    color: '#facc15',      // bright yellow
    weight: 3,
    fillColor: '#facc15',
    fillOpacity: 0.25,
    opacity: 0.9,
    interactive: false,
    pane: 'nonInteractiveOverlays'
  });
  halo.options._selectionId = id;   // for easy removal later
  halo.addTo(selectedHighlightGroup);

  // Force pointer-events none on the SVG path
  if (halo._path) {
    halo._path.style.pointerEvents = 'none';
  }

  updateSelectedUI();
}

function updateSelectedUI() {
  const container = document.getElementById('selected-features');
  container.innerHTML = '';

  if (selectedFeatures.length === 0) {
    container.innerHTML = '<p class="empty">Click points on the map to select them</p>';
    return;
  }

  // Minimal UI — just a count + clear button (user didn't like the long list)
  const summary = document.createElement('div');
  summary.innerHTML = `
    <strong>${selectedFeatures.length}</strong> point${selectedFeatures.length === 1 ? '' : 's'} selected
    <button class="small-btn" style="margin-left: 8px;">Clear</button>
  `;

  summary.querySelector('button').onclick = () => {
    // Clear all highlights
    selectedHighlightGroup.clearLayers();
    selectedFeatures = [];
    updateSelectedUI();
  };

  container.appendChild(summary);
}

function selectAllOfCategory(category, features) {
  features.forEach(f => {
    const name = f.properties.name || 'Unnamed';
    const coords = f.geometry.coordinates;
    const latlng = [coords[1], coords[0]];

    // Reuse selectFeature so we get proper toggle + highlight behavior
    // We create a minimal feature object for the id generation
    const fakeFeature = { properties: f.properties };
    selectFeature(fakeFeature, latlng, 'attraction', name);
  });
}

function selectAllByMode(mode) {
  if (!allStopsFeatures || allStopsFeatures.length === 0) return;

  allStopsFeatures.forEach(f => {
    if (f.properties.mode !== mode) return;

    const name = f.properties.stop_name;
    const coords = f.geometry.coordinates;
    const latlng = [coords[1], coords[0]];

    const fakeFeature = { properties: f.properties };
    selectFeature(fakeFeature, latlng, 'stop', name);
  });
}

function createGeometricCircle(centerInput, radiusMeters, label = '') {
  // Normalize center so it always works whether it's an array or a Leaflet LatLng object
  let lat, lng;

  if (Array.isArray(centerInput)) {
    [lat, lng] = centerInput;
  } else if (centerInput && typeof centerInput === 'object') {
    lat = centerInput.lat;
    lng = centerInput.lng;
  }

  if (lat == null || lng == null) {
    console.error("Invalid center passed to createGeometricCircle:", centerInput);
    return;
  }

  const radiusMiles = radiusMeters / 1609.34;

  const id = 'geo-' + Date.now();

  const layer = L.circle([lat, lng], {
    radius: radiusMeters,
    color: '#8b5cf6',
    weight: 2,
    fillColor: '#8b5cf6',
    fillOpacity: 0.15,
    interactive: false,
    pane: 'nonInteractiveOverlays'
  }).addTo(map);

  // Force pointer-events none on the actual SVG path so clicks pass through
  // even if the circle visually overlaps stops
  if (layer._path) {
    layer._path.style.pointerEvents = 'none';
  }

  const overlay = {
    id,
    type: 'circle',
    center: [lat, lng],
    radiusMeters: radiusMeters,
    radiusMiles: radiusMiles,
    layer,
    label: label || `${radiusMiles.toFixed(2)} mi circle`
  };

  geometricOverlays.push(overlay);
  renderGeometricOverlaysList();
}

function renderGeometricOverlaysList() {
  const container = document.getElementById('geometric-overlays-list');
  const clearBtn = document.getElementById('clear-all-overlays');
  if (!container) return;

  container.innerHTML = '';

  if (geometricOverlays.length === 0) {
    container.innerHTML = '<p class="empty">No geometric overlays yet.</p>';
    if (clearBtn) clearBtn.style.display = 'none';
    return;
  }

  if (clearBtn) clearBtn.style.display = 'block';

  geometricOverlays.forEach(overlay => {
    const div = document.createElement('div');
    div.className = 'overlay-item';
    div.innerHTML = `
      <div class="info">
        <strong>${overlay.label}</strong><br>
        <small>${overlay.radiusMiles.toFixed(2)} mi radius</small>
      </div>
      <button class="small-btn">×</button>
    `;

    div.querySelector('button').onclick = () => {
      map.removeLayer(overlay.layer);
      geometricOverlays = geometricOverlays.filter(o => o.id !== overlay.id);
      renderGeometricOverlaysList();
    };

    container.appendChild(div);
  });
}

// Load all data
async function loadData() {
  // Use Vite's BASE_URL so it works both locally ("/") and on GitHub Pages ("/jetlag/")
  const base = import.meta.env.BASE_URL || '/';

  const [attractionsData, stopsData, routesData, walkshedData] = await Promise.all([
    fetch(`${base}data/seattle_attractions.geojson`).then(r => r.json()),
    fetch(`${base}data/transit_stops.geojson`).then(r => r.json()),
    fetch(`${base}data/transit_routes.geojson`).then(r => r.json()),
    fetch(`${base}data/transit_walkshed.geojson`).then(r => r.json()),
  ]);

  // === Transit Layers ===
  allStopsFeatures = stopsData.features;   // store for bulk selection by mode

  stopsLayer = L.geoJSON(stopsData, {
    pointToLayer: (feature, latlng) => {
      const mode = feature.properties.mode;
      const color = mode === 'Link' ? '#3b82f6' : mode === 'RapidRide' ? '#f59e0b' : '#10b981';
      return L.circleMarker(latlng, {
        radius: 6,                    // slightly larger for easier clicking
        fillColor: color,
        color: '#111827',
        weight: 1.5,
        fillOpacity: 0.95
      });
    },
    onEachFeature: (feature, layer) => {
      const p = feature.properties;
      const name = p.stop_name;
      layer.bindPopup(`<strong>${name}</strong><br>${p.mode} — ${p.route}`);

      // Make transit stops selectable for circle drawing
      layer.on('click', (e) => {
        L.DomEvent.stopPropagation(e);   // prevent map click from firing at the same time
        selectFeature(feature, layer.getLatLng(), 'stop', name);
      });
    }
  });

  routesLayer = L.geoJSON(routesData, {
    style: { color: '#f59e0b', weight: 2.5, opacity: 0.75 },
    interactive: false   // prevent thick lines from blocking clicks on stops
  });

  walkshedLayer = L.geoJSON(walkshedData, {
    style: {
      color: '#3b82f6',
      weight: 1.5,
      fillColor: '#3b82f6',
      fillOpacity: 0.12
    },
    interactive: false   // prevent the shaded walkshed polygon from stealing clicks
  });

  // Add by default (matching the checkboxes)
  stopsLayer.addTo(map);
  routesLayer.addTo(map);
  walkshedLayer.addTo(map);

  // Build "Select All by Mode" buttons for transit
  const modeContainer = document.getElementById('transit-mode-selectors');
  if (modeContainer && allStopsFeatures.length > 0) {
    const modes = [...new Set(allStopsFeatures.map(f => f.properties.mode))].sort();

    modes.forEach(mode => {
      const count = allStopsFeatures.filter(f => f.properties.mode === mode).length;
      const btn = document.createElement('button');
      btn.textContent = `Select All ${mode} (${count})`;
      btn.style.fontSize = '0.75em';
      btn.style.padding = '2px 6px';
      btn.style.margin = '2px 4px 2px 0';
      btn.onclick = () => selectAllByMode(mode);
      modeContainer.appendChild(btn);
    });
  }

  // === Attraction Categories ===
  allAttractionsFeatures = attractionsData.features;   // store for bulk selection
  console.log("[DEBUG] Attractions categories loaded:", [...new Set(attractionsData.features.map(f => f.properties.category))]);

  // Prepare points per category for Voronoi
  const byCat = {};
  attractionsData.features.forEach(f => {
    const cat = f.properties.category;
    if (!byCat[cat]) byCat[cat] = [];
    const [lng, lat] = f.geometry.coordinates;
    byCat[cat].push([lng, lat]);
  });
  Object.assign(voronoiPoints, byCat);

  const byCategory = {};
  attractionsData.features.forEach(f => {
    const cat = f.properties.category;
    (byCategory[cat] ||= []).push(f);
  });

  const colors = {
    'Libraries': '#d97706',
    'Museums': '#7c3aed',
    'Cinemas': '#dc2626',
    'Golf Courses': '#059669',
    'Zoos': '#0891b2',
    'Aquariums': '#0ea5e9',
    'Parks': '#16a34a',
    'Hospitals': '#e11d48',
    'Foreign Consulates': '#6366f1'
  };

  const container = document.getElementById('attraction-filters');

  Object.keys(byCategory).sort().forEach(cat => {
    const features = byCategory[cat];
    const color = colors[cat] || '#6b7280';

    const layer = L.geoJSON({ type: 'FeatureCollection', features }, {
      pointToLayer: (feature, latlng) => L.circleMarker(latlng, {
        radius: 5,
        fillColor: color,
        color: '#111827',
        weight: 1,
        fillOpacity: 0.85
      }),
      onEachFeature: (feature, layer) => {
        const name = feature.properties.name;
        layer.bindPopup(`<strong>${name}</strong><br>${cat}`);

        layer.on('click', () => {
          selectFeature(feature, layer.getLatLng(), 'attraction', name);
        });
      }
    });

    attractionLayers[cat] = layer;

    const label = document.createElement('label');
    label.style.display = 'flex';
    label.style.alignItems = 'center';
    label.style.gap = '6px';

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = false;

    checkbox.onchange = () => {
      if (checkbox.checked) layer.addTo(map);
      else map.removeLayer(layer);
    };

    // Visibility toggle
    label.appendChild(checkbox);

    // Category name
    const nameSpan = document.createElement('span');
    nameSpan.textContent = ` ${cat} (${features.length})`;
    label.appendChild(nameSpan);

    // Select All button for this category
    const selectAllBtn = document.createElement('button');
    selectAllBtn.textContent = 'Select All';
    selectAllBtn.style.fontSize = '0.7em';
    selectAllBtn.style.padding = '1px 6px';
    selectAllBtn.style.marginLeft = 'auto';
    selectAllBtn.onclick = (e) => {
      e.preventDefault();
      selectAllOfCategory(cat, features);
    };
    label.appendChild(selectAllBtn);

    container.appendChild(label);

    // Do not add by default — user wants attractions hidden on load
    // layer.addTo(map);
  });

  // === Voronoi Diagrams UI (per category) ===
  const voronoiContainer = document.getElementById('voronoi-filters');
  if (voronoiContainer) {
    Object.keys(voronoiPoints).sort().forEach(cat => {
      const points = voronoiPoints[cat];
      if (!points || points.length < 2) return; // Need at least 2 points for a meaningful Voronoi

      const label = document.createElement('label');
      label.style.display = 'flex';
      label.style.alignItems = 'center';
      label.style.gap = '6px';

      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.checked = false;

      const color = CATEGORY_COLORS[cat] || '#6b7280';
      const nameSpan = document.createElement('span');
      nameSpan.textContent = `${cat} Voronoi (${points.length})`;

      checkbox.onchange = () => {
        if (checkbox.checked) {
          showVoronoiForCategory(cat, points, color);
        } else {
          hideVoronoiForCategory(cat);
        }
      };

      label.appendChild(checkbox);
      label.appendChild(nameSpan);
      voronoiContainer.appendChild(label);
    });
  }

  // Wire up "Hide All Attractions" button (controls the visibility checkboxes)
  const deselectAllAttrBtn = document.getElementById('deselect-all-attractions');
  if (deselectAllAttrBtn) {
    deselectAllAttrBtn.onclick = () => {
      const filtersContainer = document.getElementById('attraction-filters');
      if (!filtersContainer) return;

      // Uncheck all visibility checkboxes
      const checkboxes = filtersContainer.querySelectorAll('input[type="checkbox"]');
      checkboxes.forEach(checkbox => {
        if (checkbox.checked) {
          checkbox.checked = false;
          // Trigger the existing onchange logic so layers are removed
          checkbox.dispatchEvent(new Event('change'));
        }
      });

      // Also clear any yellow selection highlights for attractions
      const beforeCount = selectedFeatures.length;
      selectedFeatures = selectedFeatures.filter(f => f.source !== 'attraction');

      selectedHighlightGroup.eachLayer(l => {
        if (l.options._selectionId && l.options._selectionId.startsWith('attraction-')) {
          selectedHighlightGroup.removeLayer(l);
        }
      });

      if (selectedFeatures.length !== beforeCount) {
        updateSelectedUI();
      }
    };
  }

  // Transit toggles
  document.getElementById('toggle-stops').onchange = (e) => {
    e.target.checked ? stopsLayer.addTo(map) : map.removeLayer(stopsLayer);
  };
  document.getElementById('toggle-routes').onchange = (e) => {
    e.target.checked ? routesLayer.addTo(map) : map.removeLayer(routesLayer);
  };
  document.getElementById('toggle-walkshed').onchange = (e) => {
    e.target.checked ? walkshedLayer.addTo(map) : map.removeLayer(walkshedLayer);
  };

  // Set initial state for walkshed checkbox (since we added it by default)
  document.getElementById('toggle-walkshed').checked = true;

  // ==================== GEOMETRIC OVERLAYS UI (CLEAN) ====================
  const clearSelBtn = document.getElementById('clear-selection');
  if (clearSelBtn) clearSelBtn.onclick = () => {
    selectedFeatures = [];
    updateSelectedUI();
  };

  const createFromSel = document.getElementById('create-circle-from-selection');
  if (createFromSel) createFromSel.onclick = () => {
    if (selectedFeatures.length === 0) {
      alert("Select at least one point first by clicking on dots.");
      return;
    }
    const radiusMiles = parseFloat(document.getElementById('circle-radius').value) || 0.25;
    const radiusMeters = radiusMiles * 1609.34;

    // Create a circle for EVERY selected point (multi-select support)
    selectedFeatures.forEach(feat => {
      createGeometricCircle(feat.latlng, radiusMeters, `${feat.name} (${radiusMiles.toFixed(2)} mi)`);
    });

    // Optional: clear selection after creating circles
    // selectedFeatures = [];
    // selectedHighlightGroup.clearLayers();
    // updateSelectedUI();
  };

  const drawBtn = document.getElementById('draw-circle-mode');
  if (drawBtn) drawBtn.onclick = () => {
    drawCircleMode = true;
    map.getContainer().style.cursor = 'crosshair';
  };

  // New: Create circle at manually entered lat/lng
  const createAtLatLon = document.getElementById('create-circle-at-latlon');
  if (createAtLatLon) {
    createAtLatLon.onclick = () => {
      const lat = parseFloat(document.getElementById('circle-lat').value);
      const lng = parseFloat(document.getElementById('circle-lng').value);
      const radiusMiles = parseFloat(document.getElementById('circle-radius').value) || 0.25;
      const radiusMeters = radiusMiles * 1609.34;

      if (isNaN(lat) || isNaN(lng)) {
        alert("Please enter valid Latitude and Longitude values.");
        return;
      }

      createGeometricCircle([lat, lng], radiusMeters, `Manual circle at ${lat.toFixed(4)}, ${lng.toFixed(4)}`);
    };
  }

  // New: "Use my current location" button
  const useMyLocationBtn = document.getElementById('use-my-location');
  const locationStatus = document.getElementById('location-status');

  if (useMyLocationBtn && locationStatus) {
    useMyLocationBtn.onclick = () => {
      if (!navigator.geolocation) {
        locationStatus.textContent = "Geolocation not supported by your browser.";
        locationStatus.style.color = "#f87171";
        return;
      }

      locationStatus.textContent = "Getting your location...";
      locationStatus.style.color = "#9ca3af";
      useMyLocationBtn.disabled = true;

      navigator.geolocation.getCurrentPosition(
        (position) => {
          const lat = position.coords.latitude;
          const lng = position.coords.longitude;

          document.getElementById('circle-lat').value = lat.toFixed(6);
          document.getElementById('circle-lng').value = lng.toFixed(6);

          locationStatus.textContent = `Location set! (${lat.toFixed(4)}, ${lng.toFixed(4)})`;
          locationStatus.style.color = "#4ade80";
          useMyLocationBtn.disabled = false;

          // Clear the message after a few seconds
          setTimeout(() => {
            if (locationStatus.textContent.includes("Location set")) {
              locationStatus.textContent = "";
            }
          }, 4000);
        },
        (error) => {
          let msg = "Could not get location.";
          if (error.code === error.PERMISSION_DENIED) msg = "Location permission denied.";
          if (error.code === error.POSITION_UNAVAILABLE) msg = "Location information unavailable.";
          if (error.code === error.TIMEOUT) msg = "Location request timed out.";

          locationStatus.textContent = msg;
          locationStatus.style.color = "#f87171";
          useMyLocationBtn.disabled = false;
        },
        {
          enableHighAccuracy: true,
          timeout: 10000,
          maximumAge: 0
        }
      );
    };
  }

  // Prominent "Clear All Overlays" button at the top of the section (no scrolling needed)
  const clearAllBtn = document.getElementById('clear-all-overlays');
  if (clearAllBtn) {
    clearAllBtn.onclick = () => {
      geometricOverlays.forEach(o => {
        if (o.layer) map.removeLayer(o.layer);
      });
      geometricOverlays = [];
      renderGeometricOverlaysList();
    };
  }

  // Map click handler for draw mode
  map.on('click', (e) => {
    if (drawCircleMode) {
      drawCircleMode = false;
      map.getContainer().style.cursor = '';
      const radiusMiles = parseFloat(document.getElementById('circle-radius').value) || 0.25;
      const radiusMeters = radiusMiles * 1609.34;
      createGeometricCircle([e.latlng.lat, e.latlng.lng], radiusMeters, `${radiusMiles.toFixed(2)} mi circle`);
    }
  });

  // Initial render of the list
  renderGeometricOverlaysList();

  // ==================== BASEMAP SWITCHING ====================
  let currentBasemap = null;

  const basemaps = {
    colorful: L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap contributors'
    }),
    light: L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
      attribution: '&copy; OpenStreetMap contributors &copy; CARTO'
    })
  };

  function setBasemap(type) {
    if (currentBasemap) {
      map.removeLayer(currentBasemap);
    }
    currentBasemap = basemaps[type];
    currentBasemap.addTo(map);
  }

  // Initial basemap (light/grayscale by default so colors pop)
  setBasemap('light');

  // Wire up basemap radio buttons
  const basemapRadios = document.querySelectorAll('input[name="basemap"]');
  basemapRadios.forEach(radio => {
    radio.addEventListener('change', () => {
      if (radio.checked) {
        setBasemap(radio.value);
      }
    });
  });

  // Make sure the geometric overlays list is rendered
  renderGeometricOverlaysList();
}

// ==================== VORONOI HELPERS ====================

function showVoronoiForCategory(category, points, color) {
  if (voronoiLayers[category]) {
    hideVoronoiForCategory(category);
  }

  try {
    const delaunay = Delaunay.from(points);
    const voronoi = delaunay.voronoi([-180, -90, 180, 90]);

    const group = L.layerGroup();

    for (let i = 0; i < points.length; i++) {
      const poly = voronoi.cellPolygon(i);
      if (poly && poly.length > 2) {
        // d3-delaunay gives [x, y] = [lng, lat] → Leaflet wants [lat, lng]
        const leafletCoords = poly.map(([x, y]) => [y, x]);
        const cell = L.polygon(leafletCoords, {
          color: color,
          weight: 1,
          fillColor: color,
          fillOpacity: 0.18,
          interactive: false,
          pane: 'nonInteractiveOverlays'
        });
        group.addLayer(cell);

        // Force pointer-events none on the SVG path
        if (cell._path) {
          cell._path.style.pointerEvents = 'none';
        }
      }
    }

    group.addTo(map);
    voronoiLayers[category] = group;

  } catch (err) {
    console.error(`Voronoi computation failed for ${category}:`, err);
    alert(`Could not compute Voronoi for ${category}.`);
  }
}

function hideVoronoiForCategory(category) {
  if (voronoiLayers[category]) {
    map.removeLayer(voronoiLayers[category]);
    delete voronoiLayers[category];
  }
}

loadData().catch(err => {
  console.error(err);
  document.getElementById('sidebar').innerHTML += `<p style="color:#f87171">Failed to load data. Run the export script first.</p>`;
});

/* ========================================
   Mobile menu (hamburger)
   ======================================== */
function initMobileMenu() {
  const sidebar = document.getElementById('sidebar');
  const toggle = document.getElementById('mobile-menu-toggle');
  const closeBtn = document.getElementById('mobile-menu-close');

  if (!toggle || !sidebar) return;

  const openMenu = () => sidebar.classList.add('open');
  const closeMenu = () => sidebar.classList.remove('open');

  toggle.addEventListener('click', () => {
    if (sidebar.classList.contains('open')) {
      closeMenu();
    } else {
      openMenu();
    }
  });

  if (closeBtn) {
    closeBtn.addEventListener('click', closeMenu);
  }

  // Close when clicking on the map (on mobile)
  const mapEl = document.getElementById('map');
  if (mapEl) {
    mapEl.addEventListener('click', () => {
      if (window.innerWidth <= 768 && sidebar.classList.contains('open')) {
        closeMenu();
      }
    });
  }

  // Close on escape key
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && sidebar.classList.contains('open')) {
      closeMenu();
    }
  });
}

// Initialize after DOM is ready (in case)
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initMobileMenu);
} else {
  initMobileMenu();
}
