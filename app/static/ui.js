// ---------------------------------------------------------------------------
// app/static/ui.js — rendering-layer barrel + viewer-engine selector
// ---------------------------------------------------------------------------
// Exposes `map2d` / `scene3d` with a stable public API. Which backend they
// resolve to is decided at load by config.viewerEngine:
//   'legacy' -> Three.js globe (ui/scene3d.js) + Leaflet map (ui/map2d.js)
//   'cesium' -> single CesiumJS viewer (ui/cesium/*) implementing the same API
// Cesium is the default engine and is imported statically. The legacy
// Three.js/Leaflet backend is now loaded ONLY on the ?engine=legacy rollback
// path, via a dynamic import — so the default Cesium path never parses it.
// Top-level await keeps main.js's synchronous `scene3d`/`map2d` destructure
// working: this module (and its importers) resolve only once the chosen
// backend is ready.
// ---------------------------------------------------------------------------
import { config } from './config.js';
import { scene3d as scene3dCesium } from './ui/cesium/scene3d_adapter.js';
import { map2d as map2dCesium } from './ui/cesium/map2d_adapter.js';
import {
  getViewer, applySceneLook, setMapStyle as setCesiumMapStyle,
  getMapStyle as getCesiumMapStyle, captureScenePng, MAP_STYLES,
} from './ui/cesium/viewer.js';

const useCesium = config.viewerEngine === 'cesium';

let scene3dImpl = scene3dCesium;
let map2dImpl = map2dCesium;
if (!useCesium) {
  const [legacyScene, legacyMap] = await Promise.all([
    import('./ui/scene3d.js'),
    import('./ui/map2d.js'),
  ]);
  scene3dImpl = legacyScene.scene3d;
  map2dImpl = legacyMap.map2d;
}

export const scene3d = scene3dImpl;
export const map2d = map2dImpl;

export { earthTexture } from './ui/earthTexture.js';
export { initSliders, createPanelAccordions } from './ui/panels.js';

// ---------------------------------------------------------------------------
// Engine-agnostic basemap + figure-export surface used by the topbar.
// Cesium owns both projections, so it can list real cartographic basemaps and
// read its own canvas back. The legacy Leaflet backend only ever had the
// standard/satellite pair and no canvas capture.
// ---------------------------------------------------------------------------
const LEGACY_STYLES = {
  satellite: { label: 'Satellite' },
  standard: { label: 'Standard (OSM)' },
};

export function getMapStyles() {
  return useCesium ? MAP_STYLES : LEGACY_STYLES;
}

export function getMapStyle() {
  return useCesium ? getCesiumMapStyle() : 'satellite';
}

export async function setMapStyle(key) {
  if (useCesium) return setCesiumMapStyle(key);
  map2dImpl.setBaseLayer?.(key === 'satellite' ? 'satellite' : 'standard');
  return key;
}

/** PNG of the current viewport only (no panels). Cesium engine only. */
export async function captureViewportPng(options) {
  if (!useCesium) {
    throw new Error('La exportación de imagen requiere el motor Cesium (quita ?engine=legacy).');
  }
  return captureScenePng(options);
}

if (useCesium) {
  try { document.body.dataset.engine = 'cesium'; } catch (_) { /* body not ready */ }
  // One Cesium viewer, two looks: the view toggle drives SceneMode
  // (3d -> globe, 2d -> flat plate-carrée map) and the matching visual
  // treatment (applySceneLook drops atmosphere/terminator/star box in 2D).
  // We use a 0-duration (instant) morph: the ANIMATED transition (duration > 0)
  // relies on a per-frame tween that never advances under requestRenderMode, so
  // it gets stuck in SceneMode.MORPHING — leaving a blank 2D screen and a
  // half-morphed "sliced" globe when switching back to 3D. A 0-duration morph
  // switches SceneMode synchronously; we then request one frame to draw it.
  const morph = (mode) => {
    const v = getViewer();
    if (!v) return;
    const s = v.scene;
    // Render continuously through the switch: the animated morph tween never
    // advances under requestRenderMode (it sticks in SceneMode.MORPHING), so we
    // use an instant (0-duration) morph and drive frames ourselves.
    s.requestRenderMode = false;
    if (mode === '2d') s.morphTo2D(0);
    else s.morphTo3D(0);
    applySceneLook(mode === '2d' ? '2d' : '3d');
    clearTimeout(morph._frame);
    clearTimeout(morph._restore);
    // Re-frame one tick later: the camera pose carried over from the other
    // SceneMode can leave the flat 2D map entirely outside the viewport (blank
    // screen), and calling flyHome synchronously right after the mode swap is
    // too early — the 2D frustum swap hasn't applied yet, so the map stays
    // unrendered. Defer it. 2D re-frames to the whole map; 3D keeps the camera.
    morph._frame = setTimeout(() => {
      if (mode === '2d') v.camera.flyHome(0);
      s.requestRender();
    }, 80);
    // Keep rendering while the imagery re-projects, then restore on-demand mode.
    morph._restore = setTimeout(() => {
      s.requestRenderMode = config.cesium.requestRenderMode;
      s.requestRender();
    }, 1200);
  };
  const wire = () => {
    document.querySelectorAll('[data-view]').forEach((btn) => {
      // Only the projection buttons morph the scene — "fullscreen" is a layout
      // toggle and must keep whichever projection is currently shown.
      const view = btn.dataset.view;
      if (view !== '2d' && view !== '3d') return;
      btn.addEventListener('click', () => morph(view));
    });
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', wire);
  else wire();
}
