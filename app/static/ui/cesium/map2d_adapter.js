// =====================================================
// ui/cesium/map2d_adapter.js
// Re-implements the public `map2d` API on the SAME single Cesium viewer.
// Draws that overlap scene3d (ground track, satellite, link, stations,
// constellations) are NO-OPS here — scene3d_adapter owns those entities so we
// never double-render. This adapter does the map-only work: base-imagery
// toggle, camera focus/fly, and the on-globe station picker.
// Weather-field overlay is staged (safe no-op) for a follow-up increment.
// =====================================================
import { getViewer, getCesium, setBaseImagery, requestRender } from './viewer.js';

let currentBase = 'standard'; // 'standard'(osm) | 'satellite'(esri)
let pickHandler = null;
let pickEntity = null;
let weatherEntities = [];     // rectangle entities for the weather field
let footprintEntity = null;   // satellite ground-footprint ellipse

function C() { return getCesium(); }

// ── weather colour ramp (mirrors ui/map2d.js WEATHER_COLOR_STOPS) ──────────
const WEATHER_COLOR_STOPS = [
  { stop: 0.0, r: 44, g: 123, b: 182 },
  { stop: 0.25, r: 171, g: 217, b: 233 },
  { stop: 0.5, r: 255, g: 255, b: 191 },
  { stop: 0.75, r: 253, g: 174, b: 97 },
  { stop: 1.0, r: 215, g: 25, b: 28 },
];
function weatherRgb(t) {
  const value = Math.min(1, Math.max(0, t));
  let left = WEATHER_COLOR_STOPS[0];
  let right = WEATHER_COLOR_STOPS[WEATHER_COLOR_STOPS.length - 1];
  for (let i = 1; i < WEATHER_COLOR_STOPS.length; i += 1) {
    if (value <= WEATHER_COLOR_STOPS[i].stop) { right = WEATHER_COLOR_STOPS[i]; left = WEATHER_COLOR_STOPS[i - 1]; break; }
  }
  const span = Math.max(1e-6, right.stop - left.stop);
  const lt = (value - left.stop) / span;
  return [
    Math.round(left.r + (right.r - left.r) * lt),
    Math.round(left.g + (right.g - left.g) * lt),
    Math.round(left.b + (right.b - left.b) * lt),
  ];
}
// Cell boundaries from sample centres (mirrors ui/map2d.js computeEdges).
function computeEdges(samples) {
  if (!Array.isArray(samples) || samples.length === 0) return [];
  if (samples.length === 1) return [samples[0] - 1, samples[0] + 1];
  const edges = [];
  for (let i = 0; i < samples.length - 1; i += 1) edges.push((samples[i] + samples[i + 1]) / 2);
  edges.unshift(samples[0] - (samples[1] - samples[0]) / 2);
  edges.push(samples[samples.length - 1] + (samples[samples.length - 1] - samples[samples.length - 2]) / 2);
  return edges;
}

// initMap is called (sync) before scene3d.initScene; the viewer is created by
// initScene. We just return a truthy handle; methods guard on getViewer().
function initMap(_container) {
  return { __cesium: true };
}

function setBaseLayer(mode) {
  if (mode === currentBase) return;
  currentBase = mode === 'satellite' ? 'satellite' : 'standard';
  setBaseImagery(currentBase === 'satellite' ? 'esri' : 'osm');
}
function toggleBaseLayer() {
  setBaseLayer(currentBase === 'satellite' ? 'standard' : 'satellite');
  return currentBase;
}

function invalidateSize() { /* Cesium auto-resizes its canvas */ requestRender(); }

function focusOnStation(station) {
  const v = getViewer();
  if (!v || !station || station.lat == null) return;
  v.camera.flyTo({
    destination: C().Cartesian3.fromDegrees(station.lon, station.lat, 1.2e6),
    duration: 1.2,
  });
}

function flyToOrbit(points = [], _opts = {}) {
  const v = getViewer();
  if (!v || !Array.isArray(points) || points.length < 2) return;
  const cart = points
    .filter((p) => p && Number.isFinite(p.lat) && Number.isFinite(p.lon))
    .map((p) => C().Cartesian3.fromDegrees(p.lon, p.lat, (p.alt ?? 0) * 1000));
  if (cart.length < 2) return;
  v.camera.flyToBoundingSphere(C().BoundingSphere.fromPoints(cart), { duration: 0.8 });
}

// --- station picker (on-globe click -> {lat,lon}) --------------------------
function startStationPicker(onPick, initialPosition) {
  const v = getViewer();
  if (!v || typeof onPick !== 'function') return () => {};
  stopStationPicker();
  const handler = new (C().ScreenSpaceEventHandler)(v.scene.canvas);
  handler.setInputAction((movement) => {
    const cartesian = v.camera.pickEllipsoid(movement.position, v.scene.globe.ellipsoid);
    if (!cartesian) return;
    const carto = C().Cartographic.fromCartesian(cartesian);
    const lat = C().Math.toDegrees(carto.latitude);
    const lon = C().Math.toDegrees(carto.longitude);
    placePickMarker(lat, lon);
    onPick({ lat, lon });
  }, C().ScreenSpaceEventType.LEFT_CLICK);
  pickHandler = handler;
  if (initialPosition && initialPosition.lat != null) {
    placePickMarker(initialPosition.lat, initialPosition.lon);
  }
  return stopStationPicker;
}
function placePickMarker(lat, lon) {
  const v = getViewer();
  if (!v) return;
  const pos = C().Cartesian3.fromDegrees(lon, lat, 0);
  if (!pickEntity) {
    pickEntity = v.entities.add({
      point: { pixelSize: 12, color: C().Color.fromCssColorString('#5eead4'),
               outlineColor: C().Color.WHITE, outlineWidth: 2 },
    });
  }
  pickEntity.position = pos;
  requestRender();
}
function stopStationPicker() {
  if (pickHandler) { pickHandler.destroy(); pickHandler = null; }
  const v = getViewer();
  if (v && pickEntity) { v.entities.remove(pickEntity); pickEntity = null; }
  requestRender();
}

// --- weather field overlay (grid cells -> rectangle entities) --------------
function clearWeatherField() {
  const v = getViewer();
  if (v) weatherEntities.forEach((e) => v.entities.remove(e));
  weatherEntities = [];
  requestRender();
}
function renderWeatherField(payload) {
  const v = getViewer();
  clearWeatherField();
  if (!v || !payload || !payload.grid) return;
  const { latitudes, longitudes, values, min, max } = payload.grid;
  if (!Array.isArray(latitudes) || !Array.isArray(longitudes) || !Array.isArray(values)) return;
  const minV = Number(min);
  const maxV = Number(max);
  if (!Number.isFinite(minV) || !Number.isFinite(maxV)) return;
  const latEdges = computeEdges(latitudes);
  const lonEdges = computeEdges(longitudes);
  for (let row = 0; row < values.length; row += 1) {
    const rv = values[row];
    if (!Array.isArray(rv)) continue;
    for (let col = 0; col < rv.length; col += 1) {
      const val = rv[col];
      if (!Number.isFinite(val)) continue;
      const t = minV === maxV ? 0.5 : (val - minV) / (maxV - minV);
      const [r, g, b] = weatherRgb(t);
      const west = Math.min(lonEdges[col], lonEdges[col + 1]);
      const east = Math.max(lonEdges[col], lonEdges[col + 1]);
      const south = Math.min(latEdges[row], latEdges[row + 1]);
      const north = Math.max(latEdges[row], latEdges[row + 1]);
      weatherEntities.push(v.entities.add({
        rectangle: {
          coordinates: C().Rectangle.fromDegrees(west, south, east, north),
          material: C().Color.fromBytes(r, g, b, 200),
          height: 0,
        },
      }));
    }
  }
  requestRender();
}

// --- satellite ground footprint (map2d owns it; scene3d owns the sat point) -
function ensureFootprint() {
  const v = getViewer();
  if (!v) return null;
  if (!footprintEntity) {
    footprintEntity = v.entities.add({
      ellipse: {
        semiMajorAxis: 1, semiMinorAxis: 1, height: 0,
        material: C().Color.fromCssColorString('#38bdf8').withAlpha(0.10),
        outline: true, outlineColor: C().Color.fromCssColorString('#38bdf8').withAlpha(0.5),
      },
    });
  }
  return footprintEntity;
}
function updateSatellitePosition(point, footprintKm = 0) {
  const v = getViewer();
  if (!v) return;
  const radiusM = (Number(footprintKm) || 0) * 1000;
  if (!point || !Number.isFinite(point.lat) || !Number.isFinite(point.lon) || radiusM <= 0) {
    if (footprintEntity) footprintEntity.show = false;
    requestRender();
    return;
  }
  const e = ensureFootprint();
  if (e) {
    e.show = true;
    e.position = C().Cartesian3.fromDegrees(point.lon, point.lat, 0);
    e.ellipse.semiMajorAxis = radiusM;
    e.ellipse.semiMinorAxis = radiusM;
  }
  requestRender();
}
function updateFootprint(distanceKm) {
  const radiusM = (Number(distanceKm) || 0) * 1000;
  if (!footprintEntity) return;
  footprintEntity.show = radiusM > 0;
  if (radiusM > 0) {
    footprintEntity.ellipse.semiMajorAxis = radiusM;
    footprintEntity.ellipse.semiMinorAxis = radiusM;
  }
  requestRender();
}

// --- duplicates owned by scene3d_adapter -> no-op --------------------------
function updateGroundTrack(_points) {}
function updateLinkLine(_satPoint, _station) {}
function renderStations(_stations, _selectedId) {}
// Stations live on the single globe (scene3d_adapter owns visibility).
function setStationsVisible(_visible) {}
function setStationDisplay(_opts) {}
// Hover tooltip is low-value on the globe (station labels already show name);
// left as a no-op under the Cesium engine.
function annotateStationTooltip(_station, _metrics) {}
function renderConstellations(_groupId, _sats, _opts) {}
function clearConstellationGroup(_groupId) {}

export const map2d = {
  initMap,
  setBaseLayer,
  toggleBaseLayer,
  invalidateSize,
  focusOnStation,
  flyToOrbit,
  startStationPicker,
  stopStationPicker,
  renderWeatherField,
  clearWeatherField,
  updateGroundTrack,
  updateSatellitePosition,
  updateLinkLine,
  renderStations,
  setStationsVisible,
  setStationDisplay,
  updateFootprint,
  annotateStationTooltip,
  renderConstellations,
  clearConstellationGroup,
};

export default map2d;
