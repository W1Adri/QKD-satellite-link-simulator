// ---------------------------------------------------------------------------
// app/static/api.js
// ---------------------------------------------------------------------------
// Purpose : Thin HTTP client for every backend endpoint.  All fetch() calls
//           in the frontend are consolidated here so that URL paths, error
//           handling and JSON serialisation live in one place.
//
// Usage  :  import { api } from './api.js';
//           const result = await api.solve({ semi_major_axis: 6771, … });
// ---------------------------------------------------------------------------

async function _post(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

async function _get(url) {
  const res = await fetch(url);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// ── Unified orbit solver ────────────────────────────────────────────────
export async function solve(payload) {
  return _post('/api/solve', payload);
}

// ── Atmosphere ──────────────────────────────────────────────────────────
export async function getAtmosphereProfile(params) {
  return _post('/api/get_atmosphere_profile', params);
}

export async function getWeatherField(params) {
  return _post('/api/get_weather_field', params);
}

// ── OGS CRUD ────────────────────────────────────────────────────────────
export async function listOGS() { return _get('/api/ogs'); }
export async function addOGS(station) { return _post('/api/ogs', station); }

export async function deleteOGS(id) {
  const res = await fetch(`/api/ogs/${encodeURIComponent(id)}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`Delete failed: ${res.status}`);
  return res.json();
}

export async function clearOGS() {
  const res = await fetch('/api/ogs', { method: 'DELETE' });
  if (!res.ok) throw new Error(`Clear failed: ${res.status}`);
  return res.json();
}

// ── TLE ─────────────────────────────────────────────────────────────────
export async function listTLEGroups() { return _get('/api/tles'); }

export async function fetchTLEGroup(groupId) {
  return _get(`/api/tles/${encodeURIComponent(groupId)}`);
}

// ── Constellation ───────────────────────────────────────────────────────
export async function analyzeConstellation(payload) {
  return _post('/api/constellation/analyze', payload);
}

export async function propagateConstellation(payload) {
  return _post('/api/constellation/propagate', payload);
}

export async function getConstellationCoverage(id, lat, lon, duration = 86400) {
  return _get(
    `/api/constellation/${encodeURIComponent(id)}/coverage?lat=${lat}&lon=${lon}&duration_seconds=${duration}`,
  );
}

// ── Orbital utilities ───────────────────────────────────────────────────
export async function getSunSynchronous(altitude, ecc = 0) {
  return _get(`/api/orbital/sun-synchronous?altitude_km=${altitude}&eccentricity=${ecc}`);
}

export async function designSSOOrbit(altitude, ecc = 0, ltanHours = 10.5, epoch = null) {
  let url = `/api/orbital/sun-synchronous-orbit?altitude_km=${altitude}&eccentricity=${ecc}&ltan_hours=${ltanHours}`;
  if (epoch) url += `&epoch=${encodeURIComponent(epoch)}`;
  return _get(url);
}

export async function getWalkerConstellation(T, P, F, alt, inc, ecc = 0) {
  return _get(
    `/api/orbital/walker-constellation?T=${T}&P=${P}&F=${F}&altitude_km=${alt}&inclination_deg=${inc}&eccentricity=${ecc}`,
  );
}

export async function getRepeatGroundTrack(revsPerDay) {
  return _get(`/api/orbital/repeat-ground-track?revolutions_per_day=${revsPerDay}`);
}

// ── Users / Auth ────────────────────────────────────────────────────────
export async function login(username, password) {
  return _post('/api/login', { username, password });
}

export async function logout() {
  return _post('/api/logout', {});
}

export async function getUserCount() { return _get('/api/users/count'); }

// ── Chats ───────────────────────────────────────────────────────────────
export async function listChats(limit = 50) {
  return _get(`/api/chats?limit=${limit}`);
}

export async function postChat(userId, message) {
  return _post('/api/chats', { user_id: userId, message });
}

// ── Irradiance ──────────────────────────────────────────────────────────
export async function getIrradiance(params) {
  return _post('/api/irradiance', params);
}

// ── Solar ephemeris ─────────────────────────────────────────────────────
export async function fetchSolar(epochIso, tOffsetsS) {
  return _post('/api/solar', { epoch_iso: epochIso, t_offsets_s: tOffsetsS });
}

// ── Scene timeline (heliocentric mode) ─────────────────────────────────
export async function fetchSceneTimeline(epochIso, intervalS, stepS) {
  return _post('/api/scene-timeline', {
    epoch_iso: epochIso,
    interval_s: intervalS,
    step_s: stepS,
  });
}

// ── Health ──────────────────────────────────────────────────────────────
export async function health() { return _get('/health'); }

// Bundle as single namespace for convenience
export const api = {
  solve, getAtmosphereProfile, getWeatherField,
  getIrradiance,
  listOGS, addOGS, deleteOGS, clearOGS,
  listTLEGroups, fetchTLEGroup,
  analyzeConstellation, propagateConstellation, getConstellationCoverage,
  getSunSynchronous, designSSOOrbit, getWalkerConstellation, getRepeatGroundTrack,
  fetchSolar,
  fetchSceneTimeline,
  login, logout, getUserCount,
  listChats, postChat, health,
};
