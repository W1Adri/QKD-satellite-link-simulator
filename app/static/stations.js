// ---------------------------------------------------------------------------
// app/static/stations.js
// ---------------------------------------------------------------------------
// Purpose : Ground station (OGS) management - API operations for loading,
//           persisting, and deleting stations via the backend.  Works in
//           conjunction with state.js for local state updates.
//
// Exports : builtinStations, loadStationsFromServer, persistStation,
//           clearStations, deleteStationRemote, getBuiltinStations
// ---------------------------------------------------------------------------
import { upsertStation, removeStations, removeStation } from './state.js';

// ─────────────────────────────────────────────────────────────────────────────
// Built-in Default Stations
// ─────────────────────────────────────────────────────────────────────────────
let builtinStations = [
  { id: 'tenerife', name: 'Teide Observatory (ES)', lat: 28.3, lon: -16.509, altitude: 2390, aperture: 1.0, builtin: true },
  { id: 'matera', name: 'Matera Laser Ranging (IT)', lat: 40.649, lon: 16.704, altitude: 537, aperture: 1.5, builtin: true },
  { id: 'grasse', name: "Observatoire de la Côte d'Azur (FR)", lat: 43.754, lon: 6.920, altitude: 1270, aperture: 1.54, builtin: true },
  { id: 'toulouse', name: 'Toulouse Space Centre (FR)', lat: 43.604, lon: 1.444, altitude: 150, aperture: 1.0, builtin: true },
  { id: 'vienna', name: 'Vienna Observatory (AT)', lat: 48.248, lon: 16.357, altitude: 240, aperture: 0.8, builtin: true },
  { id: 'sodankyla', name: 'Sodankylä Geophysical (FI)', lat: 67.366, lon: 26.633, altitude: 180, aperture: 1.0, builtin: true },
  { id: 'matera2', name: 'Matera Secondary (IT)', lat: 40.64, lon: 16.7, altitude: 537, aperture: 1.2, builtin: true },
  { id: 'tenerife2', name: 'La Palma Roque (ES)', lat: 28.761, lon: -17.89, altitude: 2326, aperture: 2.0, builtin: true },
  { id: 'nict-koganei', name: 'NICT OGS Koganei (JP)', lat: 35.710, lon: 139.489, altitude: 80, aperture: 1.5, builtin: true },
  { id: 'dlr-oberpfaffenhofen', name: 'DLR OGS Oberpfaffenhofen (DE)', lat: 48.084, lon: 11.280, altitude: 600, aperture: 0.4, builtin: true },
  { id: 'mount-stromlo', name: 'ANU Mount Stromlo QOGS (AU)', lat: -35.316, lon: 149.010, altitude: 770, aperture: 0.7, builtin: true },
  { id: 'table-mountain', name: 'NASA/JPL OCTL Table Mountain (US)', lat: 34.382, lon: -117.682, altitude: 2286, aperture: 1.0, builtin: true },
  { id: 'haleakala', name: 'NASA LCRD OGS-2 Haleakalā (US)', lat: 20.708, lon: -156.257, altitude: 3055, aperture: 0.6, builtin: true },
  { id: 'kasi-gamak', name: 'KASI Gamak Station (KR)', lat: 35.595, lon: 127.920, altitude: 120, aperture: 1.0, builtin: true },
  { id: 'lijiang-gaomeigu', name: 'Lijiang Gaomeigu Observatory (CN)', lat: 26.697, lon: 100.030, altitude: 3200, aperture: 1.2, builtin: true },
  { id: 'dlr-calar-alto', name: 'DLR Calar Alto OGS (ES)', lat: 37.224, lon: -2.546, altitude: 2168, aperture: 1.0, builtin: true },
];

/**
 * Get the current list of built-in stations.
 */
export function getBuiltinStations() {
  return builtinStations;
}

/**
 * Load stations from the backend API. Falls back to built-in list if unavailable.
 */
export async function loadStationsFromServer() {
  let loadedFromServer = false;
  try {
    const response = await fetch('/api/ogs');
    if (response.ok) {
      const data = await response.json();
      if (Array.isArray(data) && data.length) {
        builtinStations = data.map((item, idx) => ({
          id: item.id ?? `${item.name.replace(/\s+/g, '-').toLowerCase()}-${idx}`,
          name: item.name,
          lat: item.lat,
          lon: item.lon,
          altitude: item.altitude_m ?? 0,
          aperture: item.aperture_m ?? 1.0,
          builtin: item.builtin ?? false,
        }));
        loadedFromServer = true;
      }
    }
  } catch (error) {
    console.warn('Remote stations could not be loaded, falling back to built-in list.', error);
  }

  // If not loaded from server, persist built-in stations to backend
  if (!loadedFromServer) {
    for (const station of builtinStations) {
      await persistStation(station);
    }
  }
  
  // Update local state with all stations
  builtinStations.forEach((station) => upsertStation(station));
}

/**
 * Persist a single station to the backend.
 */
export async function persistStation(station) {
  try {
    const response = await fetch('/api/ogs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        id: station.id,
        name: station.name,
        lat: station.lat,
        lon: station.lon,
        altitude_m: station.altitude ?? 0,
        aperture_m: station.aperture,
        builtin: station.builtin ?? false,
      }),
    });
    if (!response.ok) {
      throw new Error(`Error ${response.status}`);
    }
  } catch (error) {
    console.warn('Station could not be persisted on the backend; keeping it in memory only.', error);
  }
}

/**
 * Clear all stations from backend and local state.
 */
export async function clearStations() {
  try {
    await fetch('/api/ogs', { method: 'DELETE' });
  } catch (error) {
    console.warn('Remote station records could not be cleared.', error);
  }
  removeStations();
}

/**
 * Delete a specific station from backend and local state.
 */
export async function deleteStationRemote(stationId) {
  if (!stationId) return;
  const station = builtinStations.find((s) => s.id === stationId);
  if (station?.builtin) {
    console.warn('Built-in stations cannot be deleted.');
    return;
  }
  try {
    const response = await fetch(`/api/ogs/${encodeURIComponent(stationId)}`, { method: 'DELETE' });
    if (!response.ok && response.status !== 404) {
      throw new Error(`Error ${response.status}`);
    }
  } catch (error) {
    console.warn('Station could not be removed on the backend; removing it locally only.', error);
  }
  builtinStations = builtinStations.filter((station) => station.id !== stationId);
  removeStation(stationId);
}
