// =====================================================
// SimulCTTC — Frontend runtime configuration
// Single source of truth for the viewer-engine migration
// (Three.js/Leaflet  ->  CesiumJS). Pure data + tiny helpers,
// no DOM side effects so it can be imported anywhere.
// =====================================================

/**
 * Resolve the active viewer engine.
 * Priority: URL ?engine=  >  localStorage  >  default ('cesium').
 *  - 'cesium' : single CesiumJS viewer (3D + 2D via SceneMode) — the default.
 *  - 'legacy' : retired Three.js (3D) + Leaflet (2D) viewers, kept as a
 *    rollback reachable via ?engine=legacy while Cesium is validated in real use.
 * This lets us roll back instantly if a Cesium parity gap surfaces.
 */
function resolveEngine() {
  try {
    const fromUrl = new URLSearchParams(window.location.search).get('engine');
    if (fromUrl === 'cesium' || fromUrl === 'legacy') {
      window.localStorage?.setItem('viewerEngine', fromUrl);
      return fromUrl;
    }
    const stored = window.localStorage?.getItem('viewerEngine');
    if (stored === 'cesium' || stored === 'legacy') return stored;
  } catch (_) { /* SSR / privacy mode: fall through to default */ }
  return 'cesium';
}

export const VIEWER_ENGINE = resolveEngine();

export const config = {
  viewerEngine: VIEWER_ENGINE,

  cesium: {
    // CesiumJS library (ESM build) — lazy-loaded only when engine === 'cesium'
    // so the heavy bundle never loads for the legacy path.
    version: '1.122',
    jsUrl: 'https://cdn.jsdelivr.net/npm/cesium@1.122/Build/Cesium/Cesium.js',
    cssUrl: 'https://cdn.jsdelivr.net/npm/cesium@1.122/Build/Cesium/Widgets/widgets.css',
    // CESIUM_BASE_URL must point at the static asset root of the same build.
    baseUrl: 'https://cdn.jsdelivr.net/npm/cesium@1.122/Build/Cesium/',

    // Cesium Ion access token. Empty here by default; the REAL value is loaded
    // at startup from the gitignored `ion_token.json` (see loadRuntimeSettings).
    // With a valid token the viewer uses Cesium World Imagery + on-zoom World
    // Terrain & OSM Buildings. Without one it falls back to free imagery.
    ionToken: '',

    // Imagery backend selector (persisted in ion_token.json via the Settings
    // dialog). 'ion' = Cesium Ion (default; needs token). 'free' = Blue Marble
    // single-tile base + ESRI World Imagery overlay (no token, always works).
    imageryMode: 'ion', // 'ion' | 'free'

    // Free-imagery sources (used by the 'free' mode and the Ion fallback).
    // Blue Marble: one static tile -> instant, never a black globe. ESRI World
    // Imagery: tiled satellite -> streams city detail only where you zoom.
    blueMarbleUrl: 'https://cdn.jsdelivr.net/npm/three-globe@2.30.0/example/img/earth-blue-marble.jpg',
    esriUrl: 'https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer',

    // Performance: render only when the scene changes (a mostly-static orbit
    // viewer barely needs continuous draw). Big GPU/CPU saving.
    requestRenderMode: true,
    maximumScreenSpaceError: 8,   // higher = fewer tiles = lighter
    resolutionScale: 1.0,         // cap to <1 on weak GPUs

    // Heavy assets stay OFF until the camera drops below this height (m) over a
    // station — then we stream World Terrain + OSM Buildings (Ion free tier).
    detailModeHeightM: 250000,
    enableTerrainOnZoom: true,
    enableBuildingsOnZoom: true,
  },
};

export function isCesium() {
  return VIEWER_ENGINE === 'cesium';
}

// =====================================================
// Runtime settings (Ion token + imagery mode)
// Persisted server-side in the gitignored ion_token.json and exposed via
// /api/settings. Loaded ONCE at startup so the viewer can pick its imagery
// backend before the first frame. Cached so repeated calls are free.
// =====================================================
let _settingsLoaded = null; // de-dupes concurrent loads

/** Fetch persisted settings from the backend and merge into config (once). */
export function loadRuntimeSettings() {
  if (_settingsLoaded) return _settingsLoaded;
  _settingsLoaded = fetch('/api/settings')
    .then((r) => (r.ok ? r.json() : null))
    .then((s) => {
      if (s && typeof s === 'object') {
        config.cesium.ionToken = String(s.ionToken || '');
        if (s.imageryMode === 'ion' || s.imageryMode === 'free') {
          config.cesium.imageryMode = s.imageryMode;
        }
      }
      return config.cesium;
    })
    .catch(() => config.cesium); // offline / no backend: keep defaults
  return _settingsLoaded;
}

/** Persist settings to the backend (and update the in-memory config). */
export async function saveRuntimeSettings({ ionToken, imageryMode }) {
  const body = {
    ionToken: String(ionToken ?? config.cesium.ionToken ?? ''),
    imageryMode: imageryMode === 'free' ? 'free' : 'ion',
  };
  const r = await fetch('/api/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`Failed to save settings (${r.status})`);
  const saved = await r.json();
  config.cesium.ionToken = String(saved.ionToken || '');
  config.cesium.imageryMode = saved.imageryMode === 'free' ? 'free' : 'ion';
  return saved;
}

export default config;
