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
  { id: 'tenerife', name: 'Teide Observatory (ES)', lat: 28.3, lon: -16.509, aperture: 1.0 },
  { id: 'matera', name: 'Matera Laser Ranging (IT)', lat: 40.649, lon: 16.704, aperture: 1.5 },
  { id: 'grasse', name: "Observatoire de la Côte d'Azur (FR)", lat: 43.754, lon: 6.920, aperture: 1.54 },
  { id: 'toulouse', name: 'Toulouse Space Centre (FR)', lat: 43.604, lon: 1.444, aperture: 1.0 },
  { id: 'vienna', name: 'Vienna Observatory (AT)', lat: 48.248, lon: 16.357, aperture: 0.8 },
  { id: 'sodankyla', name: 'Sodankylä Geophysical (FI)', lat: 67.366, lon: 26.633, aperture: 1.0 },
  { id: 'matera2', name: 'Matera Secondary (IT)', lat: 40.64, lon: 16.7, aperture: 1.2 },
  { id: 'tenerife2', name: 'La Palma Roque (ES)', lat: 28.761, lon: -17.89, aperture: 2.0 },
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
          aperture: item.aperture_m ?? 1.0,
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
        aperture_m: station.aperture,
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
