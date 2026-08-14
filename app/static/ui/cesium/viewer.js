// =====================================================
// ui/cesium/viewer.js — single CesiumJS viewer (lazy singleton)
// Loads the Cesium library on first use (so the heavy bundle never loads on
// the legacy path), then builds ONE Cesium.Viewer that serves both the 3D
// globe and the 2D map (via SceneMode). Free base imagery, no Ion required;
// requestRenderMode + trimmed widgets for performance.
// =====================================================
import { config, loadRuntimeSettings } from '../../config.js';
import { showToast } from '../../toast.js';

let cesiumLib = null;       // window.Cesium once loaded
let loadPromise = null;     // de-dupes concurrent ensureCesium() calls
let viewer = null;          // the single Cesium.Viewer instance
let activeImagery = 'free'; // which backend actually loaded: 'ion' | 'free'
let esriLayer = null;       // ESRI overlay (free mode) — toggled by map-style btn
let currentStyle = 'satellite'; // active MAP_STYLES key
let currentLook = '3d';     // last look applied by applySceneLook ('3d' | '2d')

// Fase 4 — on-demand detail mode (World Terrain + OSM Buildings) state.
let detailState = 'low';    // 'low' (ellipsoid) | 'high' (terrain + buildings)
let detailBusy = false;     // guards concurrent async asset loads
let worldTerrain = null;    // cached CesiumTerrainProvider (Ion World Terrain)
let ellipsoidTerrain = null;// cached flat terrain to revert to
let osmBuildings = null;    // cached Cesium3DTileset (OSM Buildings)
let warnedNoToken = false;  // log the "set an Ion token" hint only once

/** Inject a <script>/<link> and resolve when loaded. */
function injectScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = src;
    s.async = true;
    s.onload = () => resolve();
    s.onerror = () => reject(new Error(`Failed to load ${src}`));
    document.head.appendChild(s);
  });
}
function injectCss(href) {
  if (document.querySelector(`link[href="${href}"]`)) return;
  const l = document.createElement('link');
  l.rel = 'stylesheet';
  l.href = href;
  document.head.appendChild(l);
}

/** Lazy-load the Cesium library exactly once. Returns window.Cesium. */
export function ensureCesium() {
  if (cesiumLib) return Promise.resolve(cesiumLib);
  if (loadPromise) return loadPromise;
  const c = config.cesium;
  // Cesium needs its asset base URL set before the script evaluates.
  window.CESIUM_BASE_URL = c.baseUrl;
  injectCss(c.cssUrl);
  loadPromise = injectScript(c.jsUrl).then(() => {
    cesiumLib = window.Cesium;
    if (!cesiumLib) throw new Error('Cesium global not present after load');
    // Ion token only matters for terrain/buildings (opt-in). Empty is fine for
    // the free OSM base map; set it so Ion assets work later if provided.
    cesiumLib.Ion.defaultAccessToken = c.ionToken || cesiumLib.Ion.defaultAccessToken;
    return cesiumLib;
  });
  return loadPromise;
}

// =====================================================
// Imagery selection — Ion (default) with automatic free fallback.
//   'ion'  : Cesium World Imagery (needs a valid token) + on-zoom terrain/buildings.
//   'free' : Blue Marble single tile (instant, never black) + ESRI overlay
//            (streams city detail only where you zoom). No token required.
// If Ion is requested but the token is missing or rejected, we fall back to
// 'free' and surface a toast pointing the user at Settings.
// =====================================================

/** Apply the chosen imagery; resolve once the globe has a working base layer. */
async function applyImagery(Cesium) {
  const c = config.cesium;
  if (c.imageryMode === 'ion') {
    if (!c.ionToken) {
      showToast('Sin token de Cesium Ion — usando mapa libre. Introduce tu token en Ajustes ⚙ para el mapa de alta resolución y los edificios 3D.', { type: 'info', duration: 7000 });
    } else {
      Cesium.Ion.defaultAccessToken = c.ionToken;
      try {
        const provider = await Cesium.createWorldImageryAsync();
        viewer.imageryLayers.removeAll();
        viewer.imageryLayers.add(new Cesium.ImageryLayer(provider));
        activeImagery = 'ion';
        return;
      } catch (e) {
        console.warn('[cesium] Ion imagery failed — falling back to free imagery:', e?.message || e);
        showToast('No se pudo cargar Cesium Ion (token inválido o sin conexión). Usando mapa libre. Revisa el token en Ajustes ⚙.', { type: 'warn', duration: 8000 });
      }
    }
  }
  await applyFreeImagery(Cesium);
}

/** Blue Marble single tile (base) + ESRI World Imagery overlay (free, no token). */
async function applyFreeImagery(Cesium) {
  const c = config.cesium;
  viewer.imageryLayers.removeAll();
  esriLayer = null;
  // Base: one static world image — loads in a single request, so the globe is
  // textured instantly and is never black even if ESRI is slow/unreachable.
  try {
    const bm = await Cesium.SingleTileImageryProvider.fromUrl(c.blueMarbleUrl);
    viewer.imageryLayers.add(new Cesium.ImageryLayer(bm));
  } catch (e) {
    console.warn('[cesium] Blue Marble base failed to load:', e?.message || e);
  }
  // Overlay: tiled satellite imagery. Cesium only fetches tiles for the current
  // view/LOD, so it stays light wide and sharpens to cities on zoom.
  try {
    const esri = await Cesium.ArcGisMapServerImageryProvider.fromUrl(c.esriUrl);
    esriLayer = new Cesium.ImageryLayer(esri);
    viewer.imageryLayers.add(esriLayer);
  } catch (e) {
    console.warn('[cesium] ESRI overlay failed to load:', e?.message || e);
  }
  activeImagery = 'free';
}

// =====================================================
// Map styles — cartographic basemaps for the flat (2D) view
// The satellite imagery above is built for the 3D globe; reprojected flat it
// reads as a dark, low-contrast mess and buries the ground track. These give
// the 2D map a proper cartographic base (the plate-carrée look used for
// ground-track figures in the literature). All are CORS-enabled, so the canvas
// stays untainted and `captureScenePng()` can read it back.
// =====================================================
export const MAP_STYLES = {
  satellite: { label: 'Satellite' },
  natgeo: {
    label: 'Natural Earth',
    esri: 'https://services.arcgisonline.com/ArcGIS/rest/services/NatGeo_World_Map/MapServer',
  },
  physical: {
    label: 'Physical relief',
    esri: 'https://services.arcgisonline.com/ArcGIS/rest/services/World_Physical_Map/MapServer',
  },
  light: {
    label: 'Light (print)',
    carto: 'light_all',
  },
  graticule: {
    label: 'Light + labels',
    carto: 'rastertiles/voyager',
  },
};

/**
 * Swap the basemap. 'satellite' restores the Ion/free imagery stack; every
 * other key installs a single cartographic raster layer. Also re-applies the
 * scene look, because atmosphere/lighting only make sense over satellite
 * imagery — over a printed-map basemap they just wash it out.
 */
export async function setMapStyle(key) {
  const Cesium = cesiumLib;
  if (!viewer || viewer.isDestroyed?.() || !Cesium) return currentStyle;
  const style = MAP_STYLES[key] ? key : 'satellite';
  if (style === 'satellite') {
    await applyImagery(Cesium);
  } else {
    const spec = MAP_STYLES[style];
    let provider = null;
    try {
      if (spec.carto) {
        provider = new Cesium.UrlTemplateImageryProvider({
          url: `https://{s}.basemaps.cartocdn.com/${spec.carto}/{z}/{x}/{y}.png`,
          subdomains: ['a', 'b', 'c', 'd'],
          credit: '© OpenStreetMap contributors © CARTO',
          maximumLevel: 18,
        });
      } else {
        provider = await Cesium.ArcGisMapServerImageryProvider.fromUrl(spec.esri, {
          enablePickFeatures: false,
        });
      }
    } catch (e) {
      console.warn(`[cesium] basemap "${style}" failed to load:`, e?.message || e);
      showToast(`No se pudo cargar el mapa "${spec.label}".`, { type: 'warn' });
      return currentStyle;
    }
    viewer.imageryLayers.removeAll();
    esriLayer = null;
    viewer.imageryLayers.add(new Cesium.ImageryLayer(provider));
    activeImagery = 'style';
  }
  currentStyle = style;
  applySceneLook();
  emitPalette();
  requestRender();
  return currentStyle;
}

export function getMapStyle() { return currentStyle; }

// Overlay palette signalling. Entities (orbit, ground track, station markers and
// labels) are coloured for a dark globe; on a light cartographic basemap they
// have to flip or the figure comes out with invisible labels. The adapters
// subscribe here rather than polling the style.
const paletteListeners = [];
/** @param {(light: boolean) => void} fn — called with true on a light basemap. */
export function onPaletteChange(fn) {
  if (typeof fn !== 'function') return;
  paletteListeners.push(fn);
  fn(isLightBasemap());
}
export function isLightBasemap() { return currentStyle !== 'satellite'; }
function emitPalette() {
  const light = isLightBasemap();
  paletteListeners.forEach((fn) => {
    try { fn(light); } catch (e) { console.warn('[cesium] palette listener failed:', e?.message || e); }
  });
}

/**
 * Apply the visual treatment for the current scene mode / basemap.
 * The flat map wants none of the globe's atmospheric dressing: sky atmosphere,
 * ground atmosphere, fog, star box and the day/night terminator all reduce
 * contrast on a projected map and make an exported figure unusable. Same for a
 * cartographic basemap in 3D — a printed map shaded by a terminator is noise.
 * @param {'2d'|'3d'} [mode] defaults to the last mode applied.
 */
export function applySceneLook(mode) {
  if (!viewer || viewer.isDestroyed?.() || !cesiumLib) return;
  if (mode === '2d' || mode === '3d') currentLook = mode;
  const Cesium = cesiumLib;
  const s = viewer.scene;
  const flat = currentLook === '2d';
  const cartographic = currentStyle !== 'satellite';
  const dressed = !flat && !cartographic;

  s.skyAtmosphere.show = dressed;
  s.globe.showGroundAtmosphere = dressed;
  s.fog.enabled = dressed;
  s.globe.enableLighting = dressed;
  if (s.skyBox) s.skyBox.show = !flat;
  if (s.sun) s.sun.show = !flat;
  if (s.moon) s.moon.show = !flat;
  // Outside the map sheet in 2D: a white margin, so an exported PNG drops
  // straight into a paper without a black band around it.
  s.backgroundColor = flat
    ? Cesium.Color.WHITE
    : Cesium.Color.fromCssColorString('#02050c');
  s.globe.baseColor = flat
    ? Cesium.Color.WHITE
    : Cesium.Color.fromCssColorString('#0b2035');
  requestRender();
}

/**
 * Render the scene off-screen at `scale`× the on-screen resolution and return a
 * PNG data URL of just the viewport — no control panels, no timeline, no
 * browser chrome. Cesium scales point/label/line sizes with the pixel ratio, so
 * a 3× capture is a true high-DPI render, not an upscale.
 * @returns {Promise<{dataUrl: string, width: number, height: number}>}
 */
export async function captureScenePng({ scale = 3 } = {}) {
  const v = viewer;
  if (!v || v.isDestroyed?.()) throw new Error('El visor 3D todavía no está listo.');
  const s = v.scene;
  // NOTE: the drawing buffer is resized through Viewer/CesiumWidget
  // `resolutionScale`. `scene.resolutionScale` is NOT a Cesium property —
  // assigning it just parks a value on the object and changes nothing.
  const prevScale = v.resolutionScale;
  const prevRequestRenderMode = s.requestRenderMode;
  // Chrome refuses canvases beyond ~16k px per side; clamp so a 4× on a HiDPI
  // display degrades to the largest capture that still renders.
  const canvas = s.canvas;
  const maxSide = 16000;
  const cap = Math.min(maxSide / Math.max(1, canvas.width), maxSide / Math.max(1, canvas.height));
  const factor = Math.max(1, Math.min(4, (Number(scale) || 1), prevScale * cap));
  try {
    s.requestRenderMode = false;
    v.resolutionScale = factor;
    // Two frames: the first resizes the drawing buffer and kicks off imagery
    // requests at the new LOD, the second draws what came back.
    await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    v.render();
    await new Promise((r) => setTimeout(r, 350)); // let the finer tiles arrive
    v.render();
    return { dataUrl: canvas.toDataURL('image/png'), width: canvas.width, height: canvas.height };
  } catch (e) {
    if (e?.name === 'SecurityError') {
      throw new Error('El lienzo está "tainted" por imágenes sin CORS; prueba con otro estilo de mapa.');
    }
    throw e;
  } finally {
    v.resolutionScale = prevScale;
    s.requestRenderMode = prevRequestRenderMode;
    v.render();
  }
}

/**
 * Create (idempotent) the single viewer mounted in `container`.
 * Safe to call from both scene3d.initScene and map2d.initMap.
 */
export async function ensureViewer(container) {
  if (viewer) return viewer;
  // Pull the persisted Ion token / imagery mode before we build the scene so
  // the very first frame already uses the right imagery backend.
  await loadRuntimeSettings();
  const Cesium = await ensureCesium();
  const c = config.cesium;

  viewer = new Cesium.Viewer(container, {
    baseLayer: false,            // we add free imagery manually
    baseLayerPicker: false,
    geocoder: false,
    homeButton: false,
    sceneModePicker: false,
    navigationHelpButton: false,
    animation: false,
    timeline: false,
    fullscreenButton: false,
    infoBox: false,
    selectionIndicator: false,
    requestRenderMode: c.requestRenderMode,
    maximumRenderTimeChange: c.requestRenderMode ? Infinity : 0.0,
    terrainProvider: new Cesium.EllipsoidTerrainProvider(),
    // preserveDrawingBuffer keeps the colour buffer readable after the frame is
    // composited, which is what lets `captureScenePng()` call canvas.toDataURL()
    // outside the render callback. Slight memory/bandwidth cost, no visible FPS
    // impact for this scene — and figure export for the paper needs it.
    contextOptions: { webgl: { powerPreference: 'high-performance', preserveDrawingBuffer: true } },
  });

  await applyImagery(Cesium);

  const scene = viewer.scene;
  scene.globe.maximumScreenSpaceError = c.maximumScreenSpaceError;
  // resolutionScale lives on the Viewer/CesiumWidget, not on Scene — the old
  // `scene.resolutionScale = …` silently did nothing.
  viewer.resolutionScale = c.resolutionScale;
  // Atmosphere / lighting / background are owned by applySceneLook so the 3D
  // globe and the flat 2D map each get the treatment that suits them.
  applySceneLook('3d');
  // Under requestRenderMode the globe can stop drawing before all imagery tiles
  // for the current view have streamed in, leaving a partially-tiled sphere.
  // Keep requesting frames while tiles are still loading so it always completes.
  scene.globe.tileLoadProgressEvent.addEventListener((queued) => {
    if (queued > 0) scene.requestRender();
  });
  // Hide the Cesium credit overlay clutter (keep attributions minimal).
  viewer.cesiumWidget.creditContainer.style.display = 'none';

  setupDetailWatcher(Cesium);

  try { window.__cesiumViewer = viewer; } catch (_) { /* debug handle */ }
  return viewer;
}

// =====================================================
// Fase 4 — on-demand detail mode (terrain + OSM buildings)
// When the camera drops below `detailModeHeightM` over the globe we stream
// Cesium World Terrain + OSM Buildings (Ion free tier); above a hysteresis
// height we revert to the flat ellipsoid to keep the wide view light.
// Fully wired but a SAFE NO-OP until `config.cesium.ionToken` is set — those
// Ion assets require a token, so without one we only log a one-time hint.
// =====================================================

/** Detail streaming is only possible with an Ion token + at least one opt-in. */
function detailEnabled() {
  const c = config.cesium;
  return Boolean(c.ionToken) && (c.enableTerrainOnZoom || c.enableBuildingsOnZoom);
}

async function enterDetailMode(Cesium) {
  if (detailState === 'high' || detailBusy || !viewer) return;
  detailBusy = true;
  try {
    const c = config.cesium;
    if (c.enableTerrainOnZoom && typeof Cesium.createWorldTerrainAsync === 'function') {
      if (!worldTerrain) worldTerrain = await Cesium.createWorldTerrainAsync();
      if (viewer && !viewer.isDestroyed?.()) viewer.terrainProvider = worldTerrain;
    }
    if (c.enableBuildingsOnZoom && typeof Cesium.createOsmBuildingsAsync === 'function') {
      if (!osmBuildings) {
        osmBuildings = await Cesium.createOsmBuildingsAsync();
        if (viewer && !viewer.isDestroyed?.()) viewer.scene.primitives.add(osmBuildings);
      } else {
        osmBuildings.show = true;
      }
    }
    detailState = 'high';
    requestRender();
  } catch (e) {
    console.warn('[cesium] detail-mode asset load failed:', e?.message || e);
  } finally {
    detailBusy = false;
  }
}

function exitDetailMode() {
  if (detailState === 'low' || !viewer || viewer.isDestroyed?.()) return;
  if (!ellipsoidTerrain) ellipsoidTerrain = new cesiumLib.EllipsoidTerrainProvider();
  viewer.terrainProvider = ellipsoidTerrain;
  if (osmBuildings) osmBuildings.show = false;
  detailState = 'low';
  requestRender();
}

/** Attach a camera-height watcher that toggles detail mode (fires on moveEnd). */
function setupDetailWatcher(Cesium) {
  const c = config.cesium;
  const enterH = Number(c.detailModeHeightM) || 250000;
  const exitH = enterH * 1.6; // hysteresis so we don't thrash at the boundary
  viewer.camera.moveEnd.addEventListener(() => {
    if (!viewer || viewer.isDestroyed?.()) return;
    const h = viewer.camera.positionCartographic?.height;
    if (!Number.isFinite(h)) return; // 2D/Columbus morph etc.
    if (h < enterH) {
      if (!detailEnabled()) {
        if (!warnedNoToken) {
          warnedNoToken = true;
          console.info('[cesium] Zoomed below the detail threshold — set config.cesium.ionToken to stream World Terrain + OSM Buildings on zoom.');
        }
        return;
      }
      enterDetailMode(Cesium);
    } else if (h > exitH) {
      exitDetailMode();
    }
  });
}

/**
 * Map-style toggle ('esri' = satellite detail, 'osm' = plain base).
 * In free mode this just shows/hides the ESRI overlay over Blue Marble. Under
 * Ion the world imagery is already satellite, so there is nothing to toggle.
 */
export function setBaseImagery(which) {
  if (!viewer || activeImagery !== 'free' || !esriLayer) return;
  esriLayer.show = which === 'esri';
  requestRender();
}

export function getViewer() { return viewer; }
export function getCesium() { return cesiumLib; }
export function isReady() { return Boolean(viewer); }

/** With requestRenderMode on, force a redraw after entity/camera mutations. */
export function requestRender() {
  if (viewer && !viewer.isDestroyed?.()) viewer.scene.requestRender();
}

export function destroyViewer() {
  if (viewer && !viewer.isDestroyed?.()) viewer.destroy();
  viewer = null;
  esriLayer = null;
  // Primitives/terrain are owned by the viewer; drop our handles so a new
  // viewer re-streams them cleanly.
  osmBuildings = null;
  worldTerrain = null;
  ellipsoidTerrain = null;
  detailState = 'low';
  detailBusy = false;
}
