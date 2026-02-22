// ---------------------------------------------------------------------------
// app/static/solar.js
// ---------------------------------------------------------------------------
// Purpose : Frontend module for solar-system rendering in the 3D scene.
//           Creates a procedural starfield skybox, a Sun sprite with glow,
//           and manages the DirectionalLight direction from backend data.
//           All astronomical calculations come from the backend — this module
//           only consumes pre-computed arrays and applies them to Three.js.
//
// Main exports:
//   initSolarScene(THREE, scene, sunLight, earthUniforms)
//       Set up skybox + Sun sprite.  Call once after initScene().
//   updateSolarFromBackend(index, solarData)
//       Per-timestep update: move Sun sprite, set light direction, update
//       the earth shader sunDirection uniform.
//   fetchSolarData(epochIso, tOffsetsS)
//       Fetch solar ephemeris from POST /api/solar.
//   getSolarData() → cached data or null
//
// Coordinate convention  (matches ui.js toVector3):
//   ECI [x,y,z] → Three.js (x·S, z·S, −y·S)  where S = UNIT_SCALE
//   +X = vernal equinox, +Y(Three) = north pole, +Z(Three) = −ECI Y
// ---------------------------------------------------------------------------

/* ── Module state ──────────────────────────────────────────────────────── */
let _THREE = null;
let _scene = null;
let _sunLight = null;
let _earthUniforms = null;

let _starField = null;
let _sunSprite = null;
let _sunPivot = null;             // Group that holds the sprite (for easy positioning)

let _solarData = null;            // cached SolarResponse from backend
let _isInitialised = false;

const SUN_VISUAL_DISTANCE = 60;   // scene units (well inside camera.far)
const SUN_SPRITE_SIZE = 6;        // visual size of the Sun sprite
const STAR_COUNT = 4000;
const STAR_SPHERE_RADIUS = 180;   // large sphere; renders behind everything

let _helioMode = false;           // true when Sun is at origin

/* ── Public API ────────────────────────────────────────────────────────── */

/**
 * Initialise solar scene objects (starfield + Sun sprite).
 * Call once after Three.js scene is ready.
 *
 * @param {object} THREE           – Three.js namespace
 * @param {THREE.Scene} scene
 * @param {THREE.DirectionalLight} sunLight
 * @param {object} earthUniforms   – earth shader uniforms (has .sunDirection)
 */
export function initSolarScene(THREE, scene, sunLight, earthUniforms) {
  _THREE = THREE;
  _scene = scene;
  _sunLight = sunLight;
  _earthUniforms = earthUniforms;

  _buildStarField();
  _buildSunSprite();

  _isInitialised = true;
}

/**
 * Apply the solar ephemeris for a given time index.
 * Moves the Sun sprite & light, updates the earth shader uniform.
 *
 * @param {number} index       – timestep index into solarData arrays
 * @param {object} solarData   – object with { sun_dir_eci[], ... }
 */
export function updateSolarFromBackend(index, solarData) {
  if (!_isInitialised || !solarData?.sun_dir_eci) return;

  const dirs = solarData.sun_dir_eci;
  const i = Math.min(index, dirs.length - 1);
  if (i < 0) return;

  const [ex, ey, ez] = dirs[i];        // ECI unit vector Earth→Sun

  // ── Convert ECI → Three.js world coords ──────────────────────────────
  // toVector3 mapping:  Three.x = ECI.x,  Three.y = ECI.z,  Three.z = −ECI.y
  const tx = ex;
  const ty = ez;
  const tz = -ey;

  // ── Sun sprite position ──────────────────────────────────────────────
  if (_sunPivot) {
    if (_helioMode) {
      // Sun at scene origin
      _sunPivot.position.set(0, 0, 0);
    } else {
      // Sun at visual distance from Earth (which is at origin)
      _sunPivot.position.set(
        tx * SUN_VISUAL_DISTANCE,
        ty * SUN_VISUAL_DISTANCE,
        tz * SUN_VISUAL_DISTANCE,
      );
    }
  }

  // ── DirectionalLight direction ───────────────────────────────────────
  // In orbit mode: light comes from Sun direction toward Earth (at origin).
  // In helio mode: light comes from origin (Sun) toward earthSystemGroup
  //   — handled by ui.js updateSolarLighting, so we just skip here.
  if (_sunLight && !_helioMode) {
    _sunLight.position.set(tx * 10, ty * 10, tz * 10);
  }

  // ── Earth shader uniform ─────────────────────────────────────────────
  if (_earthUniforms?.sunDirection) {
    _earthUniforms.sunDirection.value.set(tx, ty, tz).normalize();
  }
}

/**
 * Fetch solar ephemeris from the backend.
 * Caches the result internally.
 *
 * @param {string}   epochIso    – ISO-8601 epoch
 * @param {number[]} tOffsetsS   – seconds offsets array
 * @returns {Promise<object>}    – SolarResponse
 */
export async function fetchSolarData(epochIso, tOffsetsS) {
  try {
    const res = await fetch('/api/solar', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ epoch_iso: epochIso, t_offsets_s: tOffsetsS }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Solar API HTTP ${res.status}`);
    }
    _solarData = await res.json();
    return _solarData;
  } catch (e) {
    console.error('[solar] Failed to fetch solar data:', e);
    return null;
  }
}

/** Return the cached solar data, or null. */
export function getSolarData() {
  return _solarData;
}

/** Clear cached solar data (e.g. on orbit recompute). */
export function clearSolarData() {
  _solarData = null;
}

/** Set heliocentric mode (Sun at origin). */
export function setSolarHelioMode(active) {
  _helioMode = Boolean(active);
  if (_helioMode && _sunPivot) {
    _sunPivot.position.set(0, 0, 0);
  }
}

/* ── Star field ────────────────────────────────────────────────────────── */

function _buildStarField() {
  const positions = new Float32Array(STAR_COUNT * 3);
  const sizes = new Float32Array(STAR_COUNT);
  const colors = new Float32Array(STAR_COUNT * 3);

  for (let i = 0; i < STAR_COUNT; i++) {
    // Uniform random point on sphere (Marsaglia method)
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(2 * Math.random() - 1);
    const r = STAR_SPHERE_RADIUS;
    positions[i * 3] = r * Math.sin(phi) * Math.cos(theta);
    positions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
    positions[i * 3 + 2] = r * Math.cos(phi);

    // Vary size for depth illusion
    sizes[i] = 0.15 + Math.random() * 0.45;

    // Slight colour variation (white to warm-white to blue-white)
    const temp = Math.random();
    if (temp < 0.7) {
      colors[i * 3] = 0.95 + Math.random() * 0.05;
      colors[i * 3 + 1] = 0.92 + Math.random() * 0.08;
      colors[i * 3 + 2] = 0.88 + Math.random() * 0.12;
    } else if (temp < 0.85) {
      // Warm / orange
      colors[i * 3] = 1.0;
      colors[i * 3 + 1] = 0.85 + Math.random() * 0.1;
      colors[i * 3 + 2] = 0.7 + Math.random() * 0.15;
    } else {
      // Blue-white
      colors[i * 3] = 0.8 + Math.random() * 0.15;
      colors[i * 3 + 1] = 0.85 + Math.random() * 0.1;
      colors[i * 3 + 2] = 1.0;
    }
  }

  const geometry = new _THREE.BufferGeometry();
  geometry.setAttribute('position', new _THREE.BufferAttribute(positions, 3));
  geometry.setAttribute('size', new _THREE.BufferAttribute(sizes, 1));
  geometry.setAttribute('color', new _THREE.BufferAttribute(colors, 3));

  const material = new _THREE.PointsMaterial({
    size: 1.5,
    sizeAttenuation: false,      // constant screen-space size — always visible
    vertexColors: true,
    transparent: true,
    opacity: 0.85,
    depthWrite: false,
    depthTest: true,               // respect depth buffer so Earth occludes stars behind it
  });

  _starField = new _THREE.Points(geometry, material);
  _starField.name = 'StarField';
  _starField.renderOrder = -100;     // render first (behind everything)
  _starField.frustumCulled = false;  // always render, never frustum-cull
  _scene.add(_starField);
}

/* ── Sun sprite ────────────────────────────────────────────────────────── */

function _buildSunSprite() {
  // Procedural glow texture on an off-screen canvas
  const size = 256;
  const canvas = document.createElement('canvas');
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext('2d');

  const cx = size / 2;
  const cy = size / 2;

  // Outer soft glow
  const g1 = ctx.createRadialGradient(cx, cy, 0, cx, cy, cx);
  g1.addColorStop(0.0, 'rgba(255, 255, 240, 1.0)');
  g1.addColorStop(0.08, 'rgba(255, 245, 200, 0.95)');
  g1.addColorStop(0.25, 'rgba(255, 210, 80, 0.5)');
  g1.addColorStop(0.50, 'rgba(255, 160, 20, 0.15)');
  g1.addColorStop(0.75, 'rgba(255, 120, 0, 0.04)');
  g1.addColorStop(1.0, 'rgba(255, 80, 0, 0.0)');
  ctx.fillStyle = g1;
  ctx.fillRect(0, 0, size, size);

  const texture = new _THREE.CanvasTexture(canvas);
  texture.needsUpdate = true;

  const material = new _THREE.SpriteMaterial({
    map: texture,
    blending: _THREE.AdditiveBlending,
    transparent: true,
    depthWrite: false,
    depthTest: true,               // respect depth buffer so Earth occludes the Sun
  });

  _sunSprite = new _THREE.Sprite(material);
  _sunSprite.scale.set(SUN_SPRITE_SIZE, SUN_SPRITE_SIZE, 1);
  _sunSprite.name = 'SunSprite';
  _sunSprite.renderOrder = -50;      // behind solid objects, in front of stars

  // Wrap in a group for easy positioning
  _sunPivot = new _THREE.Group();
  _sunPivot.name = 'SunPivot';
  _sunPivot.add(_sunSprite);

  // Default position (will be overridden on first solar update)
  _sunPivot.position.set(
    SUN_VISUAL_DISTANCE,
    SUN_VISUAL_DISTANCE * 0.4,
    SUN_VISUAL_DISTANCE * 0.2,
  );
  _scene.add(_sunPivot);
}
