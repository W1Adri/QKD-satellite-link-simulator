// =====================================================
// ui/cesium/coords.js — coordinate helpers for the Cesium adapter
// Pure functions. Convert the simulator's frames into Cesium Cartesian3.
//  - Ground / satellite samples carry {lat, lon, alt(km)} computed in ECEF
//    by the backend  -> Cartesian3.fromDegrees(lon, lat, altMeters).
//  - Orbit-path samples carry {rEci(km), gmst} -> rotate ECI->ECEF by gmst.
// Cesium is passed in (window.Cesium) so this module has no hard dependency
// and can be imported before the library is loaded.
// =====================================================

const KM = 1000;

/** {lat,lon,alt(km)} -> Cesium.Cartesian3 (ECEF, metres). */
export function latLonAltToCartesian(Cesium, lat, lon, altKm = 0) {
  return Cesium.Cartesian3.fromDegrees(Number(lon) || 0, Number(lat) || 0, (Number(altKm) || 0) * KM);
}

/**
 * ECI [x,y,z] km + GMST (rad) -> ECEF Cartesian3 (metres).
 * ECEF = Rz(gmst) applied to ECI (rotate inertial into the rotating frame).
 */
export function eciToCartesian(Cesium, rEci, gmst = 0) {
  if (!rEci || rEci.length < 3) return null;
  const g = Number(gmst) || 0;
  const c = Math.cos(g);
  const s = Math.sin(g);
  const x = rEci[0];
  const y = rEci[1];
  const z = rEci[2];
  const xe = x * c + y * s;
  const ye = -x * s + y * c;
  const ze = z;
  return new Cesium.Cartesian3(xe * KM, ye * KM, ze * KM);
}

/**
 * Build a Cartesian3[] for an orbit/ground-track path.
 * Prefers lat/lon/alt (robust, already in ECEF); falls back to ECI+gmst.
 */
export function pathToCartesians(Cesium, points, { clampAlt = null } = {}) {
  const out = [];
  if (!Array.isArray(points)) return out;
  for (const p of points) {
    if (!p) continue;
    let c = null;
    if (Number.isFinite(p.lat) && Number.isFinite(p.lon)) {
      const alt = clampAlt != null ? clampAlt : (p.alt ?? 0);
      c = latLonAltToCartesian(Cesium, p.lat, p.lon, alt);
    } else if (p.rEci) {
      c = eciToCartesian(Cesium, p.rEci, p.gmst ?? 0);
    }
    if (c) out.push(c);
  }
  return out;
}

/** Single sample -> Cartesian3 (satellite position). */
export function sampleToCartesian(Cesium, p) {
  if (!p) return null;
  if (Number.isFinite(p.lat) && Number.isFinite(p.lon)) {
    return latLonAltToCartesian(Cesium, p.lat, p.lon, p.alt ?? 0);
  }
  if (p.rEci) return eciToCartesian(Cesium, p.rEci, p.gmst ?? 0);
  return null;
}
