// ---------------------------------------------------------------------------
// app/static/ui/map2d.js
// ---------------------------------------------------------------------------
// Purpose : Leaflet 2D map rendering — ground tracks, stations, footprints,
//           weather field overlay, station picker, constellation layers.
// Exports : map2d
// ---------------------------------------------------------------------------
import { clamp, formatDistanceKm } from '../utils.js';

let map;
let orbitLayer;
let satelliteMarker;
let footprintLayer;
let linkLayer;
const stationMarkers = new Map();
let stationsVisible = true;
const constellationLayers = new Map();
const constellationMarkers = new Map();
const constellationSatelliteMarkers = new Map(); // New: Specific markers for constellation satellites
const constellationOrbitLayers = new Map(); // New: For 2D ground tracks for each constellation satellite
let baseLayers;
let currentBase = 'standard';
const ORBIT_FIT_PADDING = [48, 48];
let stationPickerHandler = null;
let stationPickerMarker = null;
let weatherLayer = null;
let weatherLegend = null;

const TILE_STANDARD = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
const TILE_SATELLITE = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';

const WEATHER_COLOR_STOPS = [
  { stop: 0.0, r: 44, g: 123, b: 182 },
  { stop: 0.25, r: 171, g: 217, b: 233 },
  { stop: 0.5, r: 255, g: 255, b: 191 },
  { stop: 0.75, r: 253, g: 174, b: 97 },
  { stop: 1.0, r: 215, g: 25, b: 28 },
];

// Helper to create a specific marker for constellation satellites
function createConstellationSatelliteMarker(satellite, color, groupId) {
  const key = `${groupId}-${satellite.id}`;
  let marker = constellationSatelliteMarkers.get(key);
  if (!marker) {
    marker = L.circleMarker([satellite.lat, satellite.lon], {
      radius: 6,
      color: color,
      weight: 2,
      fillColor: color,
      fillOpacity: 0.9,
      interactive: false,
    });
    if (satellite?.name) {
      marker.bindTooltip(satellite.name, { sticky: false });
    }
    constellationSatelliteMarkers.set(key, marker);
  }
  marker.setLatLng([satellite.lat, satellite.lon]);
  marker.setStyle({ color, fillColor: color });
  return marker;
}

// Helper to update/create 2D ground tracks for constellation satellites
function updateConstellationGroundTrack2D(satelliteId, groundTrackPoints, color, groupId) {
  const key = `${groupId}-${satelliteId}-track`;
  let polyline = constellationOrbitLayers.get(key);
  if (!polyline) {
    polyline = L.polyline([], {
      color: color,
      weight: 1.5,
      opacity: 0.6,
      interactive: false,
    });
    constellationOrbitLayers.set(key, polyline);
    map.addLayer(polyline); // Add to map here
  }
  const segments = [];
  let current = [];
  let prevLon = null;

  groundTrackPoints.forEach((point) => {
    if (!Number.isFinite(point?.lat) || !Number.isFinite(point?.lon)) {
      return;
    }
    const lon = ((point.lon + 540) % 360) - 180;
    if (prevLon !== null) {
      const delta = Math.abs(lon - prevLon);
      if (delta > 180) { // Wrap around dateline
        if (current.length) {
          segments.push(current);
        }
        current = [];
      }
    }
    current.push([point.lat, lon]);
    prevLon = lon;
    
  });

  if (current.length) {
    segments.push(current);
  }
  polyline.setLatLngs(segments);
  polyline.setStyle({ color });
  return polyline;
}

function interpolateWeatherColor(t) {
  const value = clamp(t, 0, 1);
  let left = WEATHER_COLOR_STOPS[0];
  let right = WEATHER_COLOR_STOPS[WEATHER_COLOR_STOPS.length - 1];


  for (let idx = 1; idx < WEATHER_COLOR_STOPS.length; idx += 1) {
    const candidate = WEATHER_COLOR_STOPS[idx];
    if (value <= candidate.stop) {
      right = candidate;
      left = WEATHER_COLOR_STOPS[idx - 1];
      break;
    }
  }
  const span = Math.max(1e-6, right.stop - left.stop);
  const localT = (value - left.stop) / span;
  const r = Math.round(left.r + (right.r - left.r) * localT);
  const g = Math.round(left.g + (right.g - left.g) * localT);
  const b = Math.round(left.b + (right.b - left.b) * localT);
  return `rgba(${r}, ${g}, ${b}, 0.78)`;
}

function computeEdges(samples) {
  if (!Array.isArray(samples) || samples.length === 0) return [];
  if (samples.length === 1) {
    const value = samples[0];
    return [value - 1, value + 1];
  }
  const edges = [];
  for (let idx = 0; idx < samples.length - 1; idx += 1) {
    const current = samples[idx];
    const next = samples[idx + 1];
    edges.push((current + next) / 2);
  }
  const firstGap = samples[1] - samples[0];
  const lastGap = samples[samples.length - 1] - samples[samples.length - 2];
  edges.unshift(samples[0] - firstGap / 2);
  edges.push(samples[samples.length - 1] + lastGap / 2);
  return edges;
}

function ensureWeatherLayer() {
  if (!map) return null;
  if (!weatherLayer) {
    weatherLayer = L.layerGroup();
  }
  if (!map.hasLayer(weatherLayer)) {
    weatherLayer.addTo(map);
  }
  return weatherLayer;
}

function initMap(container) {
  if (!container) return null;
  
  // Check if Leaflet is available
  if (typeof L === 'undefined') {
    console.error('Leaflet library not loaded - 2D map unavailable');
    const fallback = container.querySelector('#mapFallback');
    if (fallback) {
      fallback.hidden = false;
      fallback.querySelector('.fallback-reason').textContent = 'Leaflet library failed to load. Check your internet connection and ensure third-party scripts are allowed.';
    }
    return null;
  }
  
  try {
    map = L.map(container, {
      zoomSnap: 0.25,
      zoomDelta: 0.5,
      minZoom: 0,
      maxZoom: 12,
      worldCopyJump: false,
      maxBounds: [
        [-85, -180],
        [85, 180],
      ],
    });

    const TRANSPARENT_PLACEHOLDER = 'data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=';
    // Allow horizontal wrapping to avoid requesting invalid tile indices
    baseLayers = {
      standard: L.tileLayer(TILE_STANDARD, {
        attribution: '© OpenStreetMap contributors',
        // noWrap: false by default — allow wrap for global maps
        errorTileUrl: TRANSPARENT_PLACEHOLDER,
      }),
      satellite: L.tileLayer(TILE_SATELLITE, {
        attribution: 'Imagery © Esri & the GIS User Community',
        errorTileUrl: TRANSPARENT_PLACEHOLDER,
      }),
    };

    baseLayers.standard.addTo(map);

    orbitLayer = L.polyline([], {
      color: '#7c3aed',
      weight: 2.5,
      opacity: 0.85,
    }).addTo(map);

    linkLayer = L.polyline([], {
      color: '#38bdf8',
      weight: 1.5,
      dashArray: '6 6',
    }).addTo(map);

    satelliteMarker = L.circleMarker([0, 0], {
      radius: 6,
      color: '#f97316',
      weight: 2,
      fillColor: '#fb923c',
    fillOpacity: 0.9,
  }).addTo(map);

  footprintLayer = L.circle([0, 0], {
    radius: 0,
    color: '#22c55e',
    fillColor: '#22c55e',
    fillOpacity: 0.08,
    weight: 1,
  }).addTo(map);

  map.fitWorld({ animate: false, maxZoom: 2 });
  setTimeout(() => map.invalidateSize(), 150);
  return map;
  } catch (error) {
    console.error('Failed to initialize 2D map:', error);
    const fallback = container.querySelector('#mapFallback');
    if (fallback) {
      fallback.hidden = false;
      const reason = fallback.querySelector('.fallback-reason');
      if (reason) {
        reason.textContent = `Map initialization error: ${error.message || 'Unknown error'}`;
      }
    }
    return null;
  }
}

function setBaseLayer(mode) {
  if (!map || !baseLayers || !baseLayers[mode]) return;
  if (currentBase === mode) return;
  baseLayers[currentBase]?.removeFrom(map);
  baseLayers[mode].addTo(map);
  currentBase = mode;
  map.invalidateSize();
}

function toggleBaseLayer() {
  const next = currentBase === 'standard' ? 'satellite' : 'standard';
  setBaseLayer(next);
  return next;
}

function invalidateSize() {
  if (!map) return;
  map.invalidateSize();
}

function updateGroundTrack(points) {
  if (!orbitLayer) return;
  if (!Array.isArray(points) || points.length === 0) {
    orbitLayer.setLatLngs([]);
    return;
  }

  const segments = [];
  let current = [];
  let prevLon = null;

  points.forEach((point) => {
    if (!Number.isFinite(point?.lat) || !Number.isFinite(point?.lon)) {
      return;
    }
    const lon = ((point.lon + 540) % 360) - 180;
    if (prevLon !== null) {
      const delta = Math.abs(lon - prevLon);
      if (delta > 180) {
        if (current.length) {
          segments.push(current);
        }
        current = [];
      }
    }
    current.push([point.lat, lon]);
    prevLon = lon;
  });

  if (current.length) {
    segments.push(current);
  }

  const latLngs = segments.length > 1 ? segments : segments[0];
  orbitLayer.setLatLngs(latLngs ?? []);
}

function updateSatellitePosition(point, footprintKm = 0) {
  if (!map || !satelliteMarker || !footprintLayer) return;
  if (!point) {
    if (map.hasLayer(satelliteMarker)) satelliteMarker.removeFrom(map);
    if (map.hasLayer(footprintLayer)) footprintLayer.removeFrom(map);
    return;
  }
  if (!map.hasLayer(satelliteMarker)) satelliteMarker.addTo(map);
  if (!map.hasLayer(footprintLayer)) footprintLayer.addTo(map);
  satelliteMarker.setLatLng([point.lat, point.lon]);
  footprintLayer.setLatLng([point.lat, point.lon]);
  footprintLayer.setRadius(footprintKm * 1000);
}

function updateLinkLine(satPoint, station) {
  if (!linkLayer) return;
  if (!station) {
    linkLayer.setLatLngs([]);
    return;
  }
  linkLayer.setLatLngs([
    [station.lat, station.lon],
    [satPoint.lat, satPoint.lon],
  ]);
}

function renderStations(stations, selectedId) {
  if (!map) return;
  const newIds = new Set();
  stations.forEach((station) => {
    newIds.add(station.id);
    if (!stationMarkers.has(station.id)) {
      const marker = L.circleMarker([station.lat, station.lon], {
        radius: 5,
        color: '#0ea5e9',
        weight: 2,
        fillColor: '#38bdf8',
        fillOpacity: 0.85,
      });
      if (stationsVisible) marker.addTo(map);
      marker.bindTooltip(`${station.name}<br>${station.lat.toFixed(2)}°, ${station.lon.toFixed(2)}°`);
      stationMarkers.set(station.id, marker);
    }
    const marker = stationMarkers.get(station.id);
    marker.setStyle({
      color: station.id === selectedId ? '#facc15' : '#0ea5e9',
      fillColor: station.id === selectedId ? '#fde68a' : '#38bdf8',
    });
  });

  Array.from(stationMarkers.keys()).forEach((id) => {
    if (!newIds.has(id)) {
      const marker = stationMarkers.get(id);
      map.removeLayer(marker);
      stationMarkers.delete(id);
    }
  });

  if (selectedId != null) stationDisplay.selectedId = selectedId;
  applyStationDisplay();
}

/** Show/hide all ground-station markers on the 2D map. */
function setStationsVisible(visible) {
  return setStationDisplay({ mode: visible ? 'all' : 'none' }).mode !== 'none';
}

// Station display state — same contract as the Cesium adapter so the Ground
// Stations panel drives either engine. Names here are Leaflet tooltips, so
// `labels: false` disables the tooltip rather than hiding a rendered label.
const stationDisplay = { mode: 'all', labels: true, selectedId: null };

function applyStationDisplay() {
  const { mode, labels, selectedId } = stationDisplay;
  stationsVisible = mode !== 'none';
  if (!map) return;
  stationMarkers.forEach((marker, id) => {
    const visible = mode === 'all' || (mode === 'selected' && id === selectedId);
    if (visible) { if (!map.hasLayer(marker)) marker.addTo(map); }
    else if (map.hasLayer(marker)) map.removeLayer(marker);
    // Names are hover tooltips on this backend: stash the content when hiding
    // so it can be restored, since Leaflet drops it on unbind.
    const tooltip = marker.getTooltip?.();
    if (!labels && tooltip) {
      marker._savedTooltip = tooltip.getContent();
      marker.unbindTooltip();
    } else if (labels && !tooltip && marker._savedTooltip) {
      marker.bindTooltip(marker._savedTooltip);
    }
  });
}

function setStationDisplay(opts = {}) {
  if (opts.mode === 'all' || opts.mode === 'selected' || opts.mode === 'none') {
    stationDisplay.mode = opts.mode;
  }
  if (typeof opts.labels === 'boolean') stationDisplay.labels = opts.labels;
  if (opts.selectedId !== undefined) stationDisplay.selectedId = opts.selectedId;
  applyStationDisplay();
  return { ...stationDisplay };
}

function focusOnStation(station) {
  if (!map || !station) return;
  map.flyTo([station.lat, station.lon], Math.max(map.getZoom(), 5), {
    duration: 1.5,
  });
}

function flyToOrbit(points, options = {}) {
  if (!map) return;
  const {
    animate = true,
    padding = ORBIT_FIT_PADDING,
    maxZoom = 7,
  } = options;

  const resolvedPadding = Array.isArray(padding) && padding.length === 2
    ? padding
    : ORBIT_FIT_PADDING;

  const fallback = () => {
    map.fitWorld({
      animate,
      maxZoom: Math.min(maxZoom, typeof map.getMaxZoom === 'function' ? map.getMaxZoom() : maxZoom),
    });
  };

  if (!Array.isArray(points) || points.length === 0) {
    fallback();
    return;
  }

  const latLngs = points
    .filter((p) => Number.isFinite(p?.lat) && Number.isFinite(p?.lon))
    .map((p) => L.latLng(p.lat, p.lon));

  if (!latLngs.length) {
    fallback();
    return;
  }

  const bounds = L.latLngBounds(latLngs);
  if (!bounds.isValid()) {
    fallback();
    return;
  }

  const zoomCap = Math.min(maxZoom, typeof map.getMaxZoom === 'function' ? map.getMaxZoom() : maxZoom);
  map.flyToBounds(bounds, {
    padding: resolvedPadding,
    maxZoom: zoomCap,
    animate,
    duration: animate ? 1.2 : 0,
  });
}

function updateFootprint(distanceKm) {
  if (!footprintLayer) return;
  footprintLayer.setRadius(distanceKm * 1000);
}

function annotateStationTooltip(station, metrics) {
  if (!stationMarkers.has(station.id)) return;
  if (!stationDisplay.labels) return; // names are hidden by the panel toggle
  const marker = stationMarkers.get(station.id);
  marker.bindTooltip(
    `${station.name}<br>${station.lat.toFixed(2)}°, ${station.lon.toFixed(2)}°<br>${formatDistanceKm(metrics.distanceKm)}`,
    { sticky: true },
  );
}

function ensureStationPickerMarker() {
  if (!map) return null;
  if (!stationPickerMarker) {
    stationPickerMarker = L.marker([0, 0], {
      draggable: false,
      keyboard: false,
      interactive: false,
      zIndexOffset: 1000,
      icon: L.divIcon({
        className: 'station-picker-marker',
        html: '<div class="station-picker-marker-dot"></div>',
        iconSize: [16, 16],
        iconAnchor: [8, 8],
      }),
    });
  }
  if (!map.hasLayer(stationPickerMarker)) {
    stationPickerMarker.addTo(map);
  }
  return stationPickerMarker;
}

function removeStationPickerMarker() {
  if (stationPickerMarker && map && map.hasLayer(stationPickerMarker)) {
    map.removeLayer(stationPickerMarker);
  }
  stationPickerMarker = null;
}

function buildWeatherLegend(variable) {
  if (!map) return null;
  const legendControl = L.control({ position: 'bottomleft' });
  legendControl.onAdd = () => {
    const container = L.DomUtil.create('div', 'weather-legend');
    const title = L.DomUtil.create('div', 'weather-legend__title', container);
    title.textContent = `${variable?.label ?? 'Field'} (${variable?.units ?? ''})`;
    const gradient = L.DomUtil.create('div', 'weather-legend__gradient', container);
    gradient.style.background = `linear-gradient(90deg, ${WEATHER_GRADIENT_CSS})`;
    const scale = L.DomUtil.create('div', 'weather-legend__scale', container);
    scale.innerHTML = `
      <span>${variable?.minLabel ?? 'min'}</span>
      <span>${variable?.maxLabel ?? 'max'}</span>
    `;
    return container;
  };
  return legendControl;
}

function clearWeatherField() {
  if (weatherLayer && map) {
    weatherLayer.clearLayers();
    map.removeLayer(weatherLayer);
  }
  weatherLayer = null;
  if (weatherLegend) {
    weatherLegend.remove();
    weatherLegend = null;
  }
}

function renderWeatherField(fieldPayload) {
  if (!map || !fieldPayload || !fieldPayload.grid) {
    clearWeatherField();
    return;
  }

  const layerGroup = ensureWeatherLayer();
  if (!layerGroup) return;
  layerGroup.clearLayers();

  if (weatherLegend) {
    weatherLegend.remove();
    weatherLegend = null;
  }

  const { grid, variable } = fieldPayload;
  const { latitudes, longitudes, values, min, max } = grid;
  if (!Array.isArray(latitudes) || !Array.isArray(longitudes) || !Array.isArray(values)) {
    clearWeatherField();
    return;
  }

  const minValue = Number(min);
  const maxValue = Number(max);
  const latEdges = computeEdges(latitudes);
  const lonEdges = computeEdges(longitudes);

  // Render each lat/lon cell as a filled rectangle to approximate a smooth colour field.
  for (let row = 0; row < values.length; row += 1) {
    const rowValues = values[row];
    if (!Array.isArray(rowValues)) continue;
    for (let col = 0; col < rowValues.length; col += 1) {
      const cellValue = rowValues[col];
      const bounds = [
        [latEdges[row], lonEdges[col]],
        [latEdges[row + 1], lonEdges[col + 1]],
      ];
      if (!Number.isFinite(minValue) || !Number.isFinite(maxValue) || !Number.isFinite(cellValue)) {
        const emptyRect = L.rectangle(bounds, {
          weight: 0,
          fillOpacity: 0,
          interactive: false,
        });
        layerGroup.addLayer(emptyRect);
        continue;
      }
      const normalized = minValue === maxValue ? 0.5 : (cellValue - minValue) / (maxValue - minValue);
      const color = interpolateWeatherColor(normalized);
      const rect = L.rectangle(bounds, {
        weight: 0,
        fillColor: color,
        fillOpacity: 0.72,
        interactive: false,
      });
      layerGroup.addLayer(rect);
    }
  }

  weatherLegend = buildWeatherLegend({
    label: variable?.label,
    units: variable?.units,
    minLabel: Number.isFinite(minValue) ? minValue.toFixed(1) : 'min',
    maxLabel: Number.isFinite(maxValue) ? maxValue.toFixed(1) : 'max',
  });
  if (weatherLegend) {
    weatherLegend.addTo(map);
  }
}

function startStationPicker(onPick, initialPosition) {
  if (!map || typeof onPick !== 'function') return () => {};

  stopStationPicker();

  const container = map.getContainer();
  container.classList.add('station-pick-mode');

  if (initialPosition && Number.isFinite(initialPosition.lat) && Number.isFinite(initialPosition.lon)) {
    const marker = ensureStationPickerMarker();
    if (marker) marker.setLatLng([initialPosition.lat, initialPosition.lon]);
  }

  stationPickerHandler = (event) => {
    const { lat, lng } = event.latlng;
    const marker = ensureStationPickerMarker();
    if (marker) marker.setLatLng([lat, lng]);
    onPick({ lat, lon: lng });
  };

  map.on('click', stationPickerHandler);

  return () => stopStationPicker();
}

function stopStationPicker() {
  if (!map) return;
  const container = map.getContainer();
  container.classList.remove('station-pick-mode');
  if (stationPickerHandler) {
    map.off('click', stationPickerHandler);
    stationPickerHandler = null;
  }
  removeStationPickerMarker();
}

function ensureConstellationLayer(groupId) {
  if (!map) return null;
  let layer = constellationLayers.get(groupId);
  if (!layer) {
    layer = L.layerGroup();
    constellationLayers.set(groupId, layer);
  }
  if (!map.hasLayer(layer)) {
    layer.addTo(map);
  }
  return layer;
}

function renderConstellations2D(groupId, satellites, options = {}) {
  if (!map) return;
  if (!Array.isArray(satellites) || satellites.length === 0) {
    clearConstellationGroup(groupId);
    return;
  }
  const layer = ensureConstellationLayer(groupId);
  if (!layer) return;
  const color = options.color || '#38bdf8';
  
  const currentMarkers = new Set();
  const currentTracks = new Set();

  satellites.forEach((satellite, idx) => {
    if (!Number.isFinite(satellite?.lat) || !Number.isFinite(satellite?.lon)) return;
    const key = satellite.id || satellite.name || `${groupId}-${idx}`;
    
    // Update satellite marker
    const marker = createConstellationSatelliteMarker(satellite, color, groupId);
    if (!layer.hasLayer(marker)) {
      layer.addLayer(marker);
    }
    currentMarkers.add(key);

    // Update ground track for this satellite
    if (satellite.groundTrack && satellite.groundTrack.length > 0) {
      const track = updateConstellationGroundTrack2D(satellite.id, satellite.groundTrack, color, groupId);
      if (!layer.hasLayer(track)) {
        layer.addLayer(track);
      }
      currentTracks.add(`${groupId}-${satellite.id}-track`);
    }
  });

  // Cleanup old markers
  Array.from(constellationSatelliteMarkers.keys()).forEach((key) => {
    if (key.startsWith(`${groupId}-`) && !currentMarkers.has(key)) {
      const marker = constellationSatelliteMarkers.get(key);
      if (marker) {
        map.removeLayer(marker);
        constellationSatelliteMarkers.delete(key);
      }
    }
  });

  // Cleanup old ground tracks
  Array.from(constellationOrbitLayers.keys()).forEach((key) => {
    if (key.startsWith(`${groupId}-`) && !currentTracks.has(key)) {
      const polyline = constellationOrbitLayers.get(key);
      if (polyline) {
        map.removeLayer(polyline);
        constellationOrbitLayers.delete(key);
      }
    }
  });
}

function clearConstellationGroup(groupId) {
  const layer = constellationLayers.get(groupId);
  if (layer && map) {
    layer.clearLayers();
    map.removeLayer(layer);
  }
  constellationLayers.delete(groupId);
  // Also clear individual markers and tracks
  Array.from(constellationSatelliteMarkers.keys()).forEach(key => {
    if (key.startsWith(`${groupId}-`)) {
      const marker = constellationSatelliteMarkers.get(key);
      if (marker) map.removeLayer(marker);
      constellationSatelliteMarkers.delete(key);
    }
  });
  Array.from(constellationOrbitLayers.keys()).forEach(key => {
    if (key.startsWith(`${groupId}-`)) {
      const polyline = constellationOrbitLayers.get(key);
      if (polyline) map.removeLayer(polyline);
      constellationOrbitLayers.delete(key);
    }
  });
}

export const map2d = {
  initMap,
  setBaseLayer,
  toggleBaseLayer,
  invalidateSize,
  updateGroundTrack,
  updateSatellitePosition,
  updateLinkLine,
  renderStations,
  setStationsVisible,
  setStationDisplay,
  focusOnStation,
  flyToOrbit,
  updateFootprint,
  annotateStationTooltip,
  clearWeatherField,
  renderWeatherField,
  startStationPicker,
  stopStationPicker,
  renderConstellations: renderConstellations2D,
  clearConstellationGroup,
};
