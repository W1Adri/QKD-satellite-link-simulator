# Solar Illumination System — Architecture & Reference

## Overview

This document describes the realistic Sun + starfield implementation in the 3D
satellite view.  All astronomical calculations run on the **backend** (Python);
the **frontend** (Three.js) only renders pre-computed data.

---

## 1  Coordinate Frames

### 1.1  ECI J2000 (backend canonical frame)

| Axis | Direction |
|------|-----------|
| **+X** | Vernal equinox (First Point of Aries at J2000) |
| **+Z** | Celestial north pole (CIP) |
| **+Y** | Completes right-hand system |

This is the same frame used by `propagation.py` for satellite ECI positions
and velocities.

### 1.2  Three.js world (frontend)

The existing `toVector3()` in `ui.js` maps:

```
Three.x =  ECI.x · UNIT_SCALE
Three.y =  ECI.z · UNIT_SCALE      (north pole = up)
Three.z = −ECI.y · UNIT_SCALE
```

So Three.js **+Y is north**, **+X is vernal equinox**, **+Z is ≈ −ECI Y**.

> **No additional rotation is needed.**  `solar.js` applies the same
> `(x, z, −y)` mapping when placing the Sun and setting the light direction.

### 1.3  Earth rotation (GMST)

The Earth mesh (`earthGroup`) rotates about Three.js Y (= ECI Z = polar axis)
by the GMST angle, exactly as the existing `setEarthRotationFromTime(gmst)`
function does.  GMST is computed:

- Client-side in `simulation.js` → `computeGMST(julianDate)` for orbit points.
- Server-side in `physics/solar.py` → `_gmst_rad()` for validation.

Both use the IAU 1982/Meeus GMST formula for consistency.

---

## 2  Backend API

### `POST /api/solar`

| Field | Type | Description |
|-------|------|-------------|
| `epoch_iso` | `string` | ISO-8601 reference epoch |
| `t_offsets_s` | `float[]` | Seconds from epoch (same timeline as orbit) |

**Response** (all arrays aligned with `t_offsets_s`):

| Field | Type | Description |
|-------|------|-------------|
| `sun_dir_eci` | `[x,y,z][]` | Unit vector Earth→Sun in ECI J2000 |
| `gmst_rad` | `float[]` | GMST in radians (for cross-validation) |
| `subsolar_lat_lon` | `[lat,lon][]` | Sub-solar point in degrees |

### Computation details

- Uses **astronomy-engine** (`cosinekitty`) → `GeoVector(Body.Sun, t)` for
  J2000 equatorial position of the Sun, then normalises to unit vector.
- Sub-solar point derived from declination (→ latitude) and RA − GMST (→ longitude).
- A single-entry cache avoids recomputation when the user replays the same
  orbit without modifying epoch/timeline.

### Example request

```json
{
  "epoch_iso": "2025-03-20T12:00:00Z",
  "t_offsets_s": [0, 60, 120, 180]
}
```

---

## 3  Frontend Rendering

### 3.1  Starfield (`solar.js` → `_buildStarField`)

- 6 000 random points on a sphere of radius 160 scene-units.
- Slight colour variation (white / warm / blue-white) for realism.
- `PointsMaterial` with `sizeAttenuation`, `vertexColors`, `depthWrite: false`.
- Added to `scene` at `renderOrder = -1` (behind everything).
- Camera far plane extended to 400 to accommodate.

### 3.2  Sun sprite (`solar.js` → `_buildSunSprite`)

- Procedural radial-gradient canvas texture (256 × 256 px).
- `SpriteMaterial` with `AdditiveBlending` so it glows.
- Placed at `SUN_VISUAL_DISTANCE = 80` scene-units along the backend sun direction.
- Wrapped in a `Group` ("SunPivot") for clean positioning.

### 3.3  Directional light

- Existing `sunLight` (`DirectionalLight`) is repositioned each timestep to
  point from the sun direction towards the origin.
- The `earthUniforms.sunDirection` uniform is also updated so the day/night
  shader's terminator matches the Sun position.

### 3.4  Integration with playback loop

In `main.js → scheduleVisualUpdate()`:

1. Orbit data gives the current time index.
2. `getSolarData()` returns the cached backend response.
3. `updateSolarFromBackend(index, solarData)` sets:
   - Sun sprite position
   - `sunLight.position`
   - `earthUniforms.sunDirection`

Solar data is fetched **once per orbit recompute** (not per frame) and simply
indexed during playback.  The fetch is fire-and-forget — the scene works
without it (falls back to static sun position).

---

## 4  Validation

### Equinox check

At **2025-03-20T12:00:00 UTC** (vernal equinox):

- Sub-solar latitude should be ≈ 0°.
- The terminator should bisect the Earth roughly pole-to-pole.
- Sub-solar longitude should be ≈ 0° at ~12:00 UTC (Sun near Greenwich meridian).

The `/api/solar` response includes `subsolar_lat_lon` for programmatic verification.

### Solstice check

At **2025-06-21T00:00:00 UTC** (summer solstice):

- Sub-solar latitude should be ≈ +23.44°.
- Northern hemisphere should be predominantly lit.

---

## 5  Limitations

| Item | Status |
|------|--------|
| Sun visual scale | Artistic (sprite at 80 units). Not to scale. |
| Sun colour / spectrum | Static warm-white. No spectral rendering. |
| Moon | Not implemented. |
| Solar irradiance | Not computed yet. Only day/night terminator. |
| Light scattering | Atmosphere mesh is a simple translucent shell. |
| Eclipses / shadows | Not modelled. |
| Aberration | Included in `astronomy.GeoVector(..., aberration=True)`. |
| Nutation / precession | Handled internally by astronomy-engine (IAU 2000B). |

---

## 6  File Map

| File | Role |
|------|------|
| `app/physics/solar.py` | Solar ephemeris (backend) |
| `app/routers/solar.py` | REST endpoint `POST /api/solar` |
| `app/static/solar.js` | Starfield + Sun sprite + lighting (frontend) |
| `app/static/ui.js` | Scene init calls `initSolarScene()`; exports `updateSolarLighting` |
| `app/static/main.js` | Fetches solar data; applies per-timestep in `scheduleVisualUpdate` |
| `app/static/api.js` | `fetchSolar()` convenience wrapper |
| `docs/solar.md` | This document |
