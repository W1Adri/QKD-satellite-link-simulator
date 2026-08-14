// =====================================================
// ui/cesium/scene3d_adapter.js
// Re-implements the public `scene3d` API (Three.js globe) on a single
// CesiumJS viewer. Owns ALL shared entities (orbit, satellite, ground track,
// LOS link, stations, constellations) so the map2d adapter no-ops on the
// overlapping draws — one viewer, one set of entities, morphed 2D<->3D.
//
// Core visuals are implemented; heliocentric mode + precise solar lighting are
// staged for a follow-up increment (safe no-ops here so nothing throws).
// =====================================================
import { ensureViewer, getViewer, getCesium, requestRender, destroyViewer, onPaletteChange } from './viewer.js';
import { pathToCartesians, sampleToCartesian, latLonAltToCartesian } from './coords.js';

let ready = false;

// Entity handles (single-satellite scene)
let orbitEntity = null;
let satEntity = null;
let groundTrackEntity = null;
let groundVectorEntity = null;
let linkEntity = null;
const stationEntities = new Map();      // id -> entity
const constellationGroups = new Map();  // groupId -> { entities: [] }
// Station display, driven from the Ground Stations panel:
//   mode 'all'      -> every station drawn
//   mode 'selected' -> only the active station (declutters a figure)
//   mode 'none'     -> stations hidden entirely
//   labels          -> name labels on/off, independent of the markers
const stationDisplay = { mode: 'all', labels: true, selectedId: null };

// Cached state for helio (staged)
let helioActive = false;
let lastGmst = 0;          // rad; cached from setEarthRotationFromTime for sun ECI→ECEF
let solarLight = null;     // Cesium.DirectionalLight driving the day/night terminator

// Earth-spin (inertial camera lock). The Cesium globe is rigidly ECEF, so the
// only way to make it visibly rotate is to express the camera in an inertial
// frame rotated by GMST: the Fixed-frame globe (and the ECEF orbit/stations
// attached to it) then appears to spin while the satellite moves along it.
let spinHooked = false;    // postUpdate listener installed once per viewer
let spinActive = false;    // a non-identity camera transform is currently set

// Two overlay palettes. DARK is the app's on-globe look over satellite
// imagery; LIGHT is for the cartographic basemaps used for figures, where the
// pale cyans vanish into a white page. Labels get a contrasting halo in both.
const PALETTES = {
  dark: {
    orbit: '#a78bfa',
    track: '#38bdf8',
    vector: '#2dd4bf',
    sat: '#f97316',
    station: '#38bdf8',
    stationSel: '#facc15',
    los: '#38bdf8',
    noLos: '#ef4444',
    label: '#cfeefb',
    labelHalo: '#04121a',
    markerEdge: '#04121a',
  },
  light: {
    orbit: '#6d28d9',
    track: '#0369a1',
    vector: '#0f766e',
    sat: '#ea580c',
    station: '#0369a1',
    stationSel: '#b45309',
    los: '#0369a1',
    noLos: '#b91c1c',
    label: '#0f172a',
    labelHalo: '#ffffff',
    markerEdge: '#ffffff',
  },
};
let COLORS = PALETTES.dark;

function C() { return getCesium(); }
function color(css, alpha = 1) {
  const k = C().Color.fromCssColorString(css);
  return alpha === 1 ? k : k.withAlpha(alpha);
}
function removeEntity(e) {
  const v = getViewer();
  if (v && e) v.entities.remove(e);
}

// --- lifecycle -------------------------------------------------------------
async function initScene(container) {
  await ensureViewer(container);
  ready = true;
  const v = getViewer();
  // Initial framing: whole globe.
  v.camera.flyHome(0);
  setupEarthSpin();
  requestRender();
  try { window.__scene3dReady = true; } catch (_) {}
  return v;
}

/**
 * Install the inertial camera lock that makes the globe visibly rotate.
 * Every rendered frame (3D mode only) we set the camera's reference frame to an
 * inertial frame rotated by the current GMST. The Fixed-frame globe + the ECEF
 * orbit/stations attached to it then spin together while the satellite tracks
 * along, and the user's zoom/orientation (the camera's offset within the frame)
 * is preserved across frames. In 2D / Columbus / morph we release the lock.
 * Driven by the sim's own GMST (lastGmst) so it stays in sync with the
 * day/night terminator computed in updateSolarLighting.
 */
function setupEarthSpin() {
  if (spinHooked) return;
  const v = getViewer();
  const Cs = C();
  if (!v || !Cs) return;
  v.scene.postUpdate.addEventListener(() => {
    if (!v || v.isDestroyed?.()) return;
    const C2 = C();
    if (v.scene.mode === C2.SceneMode.SCENE3D) {
      // ECI→ECEF for the sim is Rz(-gmst) (see coords.eciToCartesian); using it
      // as the camera frame rotation makes the globe spin prograde (eastward).
      const rot = C2.Matrix3.fromRotationZ(-lastGmst);
      const m = C2.Matrix4.fromRotationTranslation(rot, C2.Cartesian3.ZERO);
      const offset = C2.Cartesian3.clone(v.camera.position);
      v.camera.lookAtTransform(m, offset);
      spinActive = true;
    } else if (spinActive) {
      // Release the lock so the 2D map / morph uses the normal world frame.
      v.camera.lookAtTransform(C2.Matrix4.IDENTITY);
      spinActive = false;
    }
  });
  spinHooked = true;
}

function disposeScene() {
  ready = false;
  spinHooked = false;
  spinActive = false;
  orbitEntity = satEntity = groundTrackEntity = groundVectorEntity = linkEntity = null;
  stationEntities.clear();
  constellationGroups.clear();
  destroyViewer();
}

// --- single-satellite draws ------------------------------------------------
function updateOrbitPath(points, _opts = {}) {
  if (!ready) return;
  const v = getViewer();
  removeEntity(orbitEntity);
  orbitEntity = null;
  const positions = pathToCartesians(C(), points);
  if (positions.length < 2) { requestRender(); return; }
  orbitEntity = v.entities.add({
    polyline: { positions, width: 2, material: color(COLORS.orbit), arcType: C().ArcType.NONE },
  });
  requestRender();
}

function updateSatellite(point) {
  if (!ready) return;
  const v = getViewer();
  const pos = sampleToCartesian(C(), point);
  if (!pos) { if (satEntity) satEntity.show = false; requestRender(); return; }
  if (!satEntity) {
    satEntity = v.entities.add({
      point: { pixelSize: 11, color: color(COLORS.sat), outlineColor: color('#fff', 0.85), outlineWidth: 1.5 },
    });
  }
  satEntity.show = true;
  satEntity.position = pos;
  requestRender();
}

function updateGroundTrackSurface(points) {
  if (!ready) return;
  const v = getViewer();
  removeEntity(groundTrackEntity);
  groundTrackEntity = null;
  const positions = pathToCartesians(C(), points, { clampAlt: 0 });
  if (positions.length < 2) { requestRender(); return; }
  groundTrackEntity = v.entities.add({
    polyline: { positions, width: 2, material: color(COLORS.track), clampToGround: true },
  });
  requestRender();
}

function updateGroundTrackVector(point) {
  if (!ready) return;
  const v = getViewer();
  removeEntity(groundVectorEntity);
  groundVectorEntity = null;
  if (!point || !Number.isFinite(point.lat) || !Number.isFinite(point.lon)) { requestRender(); return; }
  const top = latLonAltToCartesian(C(), point.lat, point.lon, point.alt ?? 0);
  const base = latLonAltToCartesian(C(), point.lat, point.lon, 0);
  groundVectorEntity = v.entities.add({
    polyline: { positions: [base, top], width: 1.5, material: new (C().PolylineDashMaterialProperty)({ color: color(COLORS.vector) }), arcType: C().ArcType.NONE },
  });
  requestRender();
}

function renderStations3D(list = [], selectedId = null) {
  if (!ready) return;
  const v = getViewer();
  if (selectedId != null) stationDisplay.selectedId = selectedId;
  const seen = new Set();
  for (const st of list) {
    if (!st || st.lat == null || st.lon == null) continue;
    seen.add(st.id);
    const selected = st.id === selectedId;
    const pos = latLonAltToCartesian(C(), st.lat, st.lon, (st.altitude ?? 0) / 1000);
    let e = stationEntities.get(st.id);
    if (!e) {
      e = v.entities.add({
        point: { pixelSize: 9, outlineColor: color(COLORS.markerEdge, 0.9), outlineWidth: 1.5 },
        // FILL_AND_OUTLINE gives the name a halo, so it stays readable over a
        // bright coastline as well as over dark ocean.
        label: { text: st.name || '', font: '11px Inter, sans-serif',
                 fillColor: color(COLORS.label), outlineColor: color(COLORS.labelHalo),
                 outlineWidth: 3, style: C().LabelStyle.FILL_AND_OUTLINE,
                 showBackground: false, pixelOffset: new (C().Cartesian2)(0, -16),
                 scale: 0.85, translucencyByDistance: undefined },
      });
      stationEntities.set(st.id, e);
    }
    e.position = pos;
    e.point.color = color(selected ? COLORS.stationSel : COLORS.station);
    e.point.pixelSize = selected ? 13 : 9;
    if (e.label) e.label.text = st.name || '';
  }
  // remove stale
  for (const [id, e] of stationEntities) {
    if (!seen.has(id)) { removeEntity(e); stationEntities.delete(id); }
  }
  applyStationDisplay();
}

/**
 * Re-colour the live entities for the active basemap. Called whenever the
 * basemap changes, so a figure exported over a light base never carries the
 * dark-globe palette.
 */
function applyPalette(light) {
  COLORS = light ? PALETTES.light : PALETTES.dark;
  if (!ready || !getCesium()) return;
  const line = (entity, key) => {
    if (entity?.polyline) entity.polyline.material = color(COLORS[key]);
  };
  line(orbitEntity, 'orbit');
  line(groundTrackEntity, 'track');
  if (groundVectorEntity?.polyline) {
    groundVectorEntity.polyline.material = new (C().PolylineDashMaterialProperty)({ color: color(COLORS.vector) });
  }
  if (satEntity?.point) satEntity.point.color = color(COLORS.sat);
  for (const [id, e] of stationEntities) {
    const selected = id === stationDisplay.selectedId;
    if (e.point) {
      e.point.color = color(selected ? COLORS.stationSel : COLORS.station);
      e.point.outlineColor = color(COLORS.markerEdge, 0.9);
    }
    if (e.label) {
      e.label.fillColor = color(COLORS.label);
      e.label.outlineColor = color(COLORS.labelHalo);
    }
  }
  requestRender();
}
onPaletteChange(applyPalette);

/** Push the current display mode onto the existing station entities. */
function applyStationDisplay() {
  const { mode, labels, selectedId } = stationDisplay;
  for (const [id, e] of stationEntities) {
    const visible = mode === 'all' || (mode === 'selected' && id === selectedId);
    e.show = visible;
    if (e.label) e.label.show = visible && labels;
  }
  requestRender();
}

/**
 * Ground-station display control (Ground Stations panel).
 * @param {{mode?: 'all'|'selected'|'none', labels?: boolean, selectedId?: *}} opts
 */
function setStationDisplay(opts = {}) {
  if (opts.mode === 'all' || opts.mode === 'selected' || opts.mode === 'none') {
    stationDisplay.mode = opts.mode;
  }
  if (typeof opts.labels === 'boolean') stationDisplay.labels = opts.labels;
  if (opts.selectedId !== undefined) stationDisplay.selectedId = opts.selectedId;
  applyStationDisplay();
  return { ...stationDisplay };
}

/** Back-compat boolean toggle: all stations on/off. */
function setStationsVisible(visible) {
  return setStationDisplay({ mode: visible ? 'all' : 'none' }).mode !== 'none';
}

function updateLink3D(point, station, elevationDeg) {
  if (!ready) return;
  const v = getViewer();
  removeEntity(linkEntity);
  linkEntity = null;
  if (!point || !station || station.lat == null) { requestRender(); return; }
  const a = sampleToCartesian(C(), point);
  const b = latLonAltToCartesian(C(), station.lat, station.lon, (station.altitude ?? 0) / 1000);
  if (!a || !b) { requestRender(); return; }
  const los = Number(elevationDeg) > 0;
  linkEntity = v.entities.add({
    polyline: {
      positions: [a, b], width: 1.6, arcType: C().ArcType.NONE,
      material: new (C().PolylineDashMaterialProperty)({ color: color(los ? COLORS.los : COLORS.noLos) }),
    },
  });
  requestRender();
}

function frameOrbitView(points, _opts = {}) {
  if (!ready) return;
  const v = getViewer();
  const positions = pathToCartesians(C(), points);
  if (positions.length < 2) return;
  const sphere = C().BoundingSphere.fromPoints(positions);
  v.camera.flyToBoundingSphere(sphere, { duration: 0.6 });
  requestRender();
}

// --- constellations --------------------------------------------------------
function renderConstellations3D(groupId, satellites = [], options = {}) {
  if (!ready) return;
  const v = getViewer();
  clearConstellation(groupId);
  const css = options.color || COLORS.track;
  const entities = [];
  for (const sat of satellites) {
    if (!sat) continue;
    const pos = sampleToCartesian(C(), sat);
    if (pos) {
      entities.push(v.entities.add({ position: pos,
        point: { pixelSize: 7, color: color(css), outlineColor: color('#04121a', 0.8), outlineWidth: 1 } }));
    }
    if (Array.isArray(sat.orbitPath) && sat.orbitPath.length > 1) {
      const op = pathToCartesians(C(), sat.orbitPath);
      if (op.length > 1) entities.push(v.entities.add({
        polyline: { positions: op, width: 1.2, material: color(css, 0.5), arcType: C().ArcType.NONE } }));
    }
    if (Array.isArray(sat.groundTrack) && sat.groundTrack.length > 1) {
      const gt = pathToCartesians(C(), sat.groundTrack, { clampAlt: 0 });
      if (gt.length > 1) entities.push(v.entities.add({
        polyline: { positions: gt, width: 1.2, material: color(css, 0.4), clampToGround: true } }));
    }
  }
  constellationGroups.set(groupId, { entities });
  requestRender();
}

function clearConstellation(groupId) {
  const grp = constellationGroups.get(groupId);
  if (grp) { grp.entities.forEach(removeEntity); constellationGroups.delete(groupId); }
  requestRender();
}

// --- Earth rotation + precise solar lighting -------------------------------
function setEarthRotationFromTime(gmst) {
  // Entity positions are already in ECEF (rotation baked into sample coords).
  // GMST drives BOTH the sun ECI→ECEF rotate (updateSolarLighting) and the
  // inertial camera lock (setupEarthSpin) that makes the globe visibly rotate.
  if (!Number.isFinite(gmst)) return;
  const g = Number(gmst);
  if (g !== lastGmst) {
    lastGmst = g;
    requestRender(); // advance the spin under requestRenderMode (e.g. scrubbing)
  }
}

/**
 * Sync the globe's day/night terminator to the simulator's Sun.
 * main.js passes the Three.js axis-mapped direction (tx = x_eci, ty = z_eci,
 * tz = −y_eci). We invert that back to ECI, rotate to ECEF by the cached GMST,
 * and drive a DirectionalLight so the lit hemisphere matches the simulation.
 */
function updateSolarLighting(tx, ty, tz) {
  if (!ready) return;
  const v = getViewer();
  const Cs = C();
  if (!v || !Cs) return;
  // invert the Three.js axis mapping → ECI unit vector (earth → sun)
  const xi = Number(tx) || 0;
  const yi = -(Number(tz) || 0);
  const zi = Number(ty) || 0;
  // ECI → ECEF: Rz(gmst)  (matches coords.eciToCartesian)
  const cs = Math.cos(lastGmst);
  const sn = Math.sin(lastGmst);
  let x = xi * cs + yi * sn;
  let y = -xi * sn + yi * cs;
  let z = zi;
  const n = Math.hypot(x, y, z) || 1;
  x /= n; y /= n; z /= n;
  // DirectionalLight.direction is the direction the light travels (sun → earth),
  // i.e. the negative of the earth→sun unit vector.
  const lightDir = new Cs.Cartesian3(-x, -y, -z);
  if (!solarLight) solarLight = new Cs.DirectionalLight({ direction: lightDir });
  else solarLight.direction = lightDir;
  v.scene.light = solarLight;
  v.scene.globe.enableLighting = true;
  requestRender();
}

function setTheme(theme) {
  const v = getViewer();
  if (!v) return;
  const light = theme === 'light';
  // Subtle: lift the atmosphere/globe a touch in light mode; leave geometry alone.
  try { v.scene.globe.atmosphereBrightnessShift = light ? 0.25 : 0.0; } catch (_) {}
  try { v.scene.skyAtmosphere.brightnessShift = light ? 0.2 : 0.0; } catch (_) {}
  requestRender();
}

// --- heliocentric mode (deferred) ------------------------------------------
// Cesium is a geocentric globe renderer; a Sun-centred scene is a different
// camera/scene paradigm than the Three.js viewer's. Left as safe no-ops — the
// helio UI simply has no effect under the Cesium engine for now.
function setHelioMode(active) { helioActive = Boolean(active); }
function setEarthHelioPosition(_posAU) { /* deferred: geocentric viewer */ }
function updateEarthOrbitPath(_positionsAU) { /* deferred: geocentric viewer */ }

export const scene3d = {
  initScene,
  disposeScene,
  updateOrbitPath,
  updateSatellite,
  renderStations: renderStations3D,
  setStationsVisible,
  setStationDisplay,
  updateLink: updateLink3D,
  setEarthRotationFromTime,
  setTheme,
  frameOrbitView,
  updateGroundTrackSurface,
  updateGroundTrackVector,
  renderConstellations: renderConstellations3D,
  clearConstellation,
  setHelioMode,
  setEarthHelioPosition,
  updateEarthOrbitPath,
  updateSolarLighting,
};

export default scene3d;
