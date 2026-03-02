// ---------------------------------------------------------------------------
// app/static/state.js
// ---------------------------------------------------------------------------
// Purpose : Centralized state management for the QKD Satellite Link Simulator.
//           Implements a simple pub/sub pattern with immutable default state,
//           mutation helpers, and domain-specific setters for stations,
//           constellations, timeline, and playback.
//
// Exports : state, defaultState, CONSTELLATION_GROUPS,
//           subscribe, emit, mutate, resetComputed,
//           setTheme, setVariant, ensureStationSelected,
//           upsertStation, removeStation, removeStations, selectStation,
//           setTimeline, setComputed, togglePlay, setTimeIndex, setTimeWarp,
//           setSceneMode, setHelioInterval, setHelioStep,
//           withConstellationGroup, setConstellationEnabled,
//           setConstellationLoading, setConstellationMetadata,
//           setConstellationError, createDefaultConstellationState
// ---------------------------------------------------------------------------
import { isoNowLocal } from './utils.js';

// ─────────────────────────────────────────────────────────────────────────────
// Constellation Groups Configuration
// ─────────────────────────────────────────────────────────────────────────────
export const CONSTELLATION_GROUPS = [
  { id: 'starlink', label: 'Starlink', color: '#38bdf8' },
  { id: 'oneweb', label: 'OneWeb', color: '#f97316' },
  { id: 'gps', label: 'GPS', color: '#a855f7' },
  { id: 'galileo', label: 'Galileo', color: '#22c55e' },
  { id: 'glonass', label: 'GLONASS', color: '#ef4444' },
];

export function createDefaultConstellationState() {
  const registry = CONSTELLATION_GROUPS.reduce((acc, item) => {
    acc[item.id] = {
      id: item.id,
      label: item.label,
      color: item.color,
      enabled: false,
      loading: false,
      error: null,
      hasData: false,
      count: 0,
      fetchedAt: null,
    };
    return acc;
  }, {});
  return {
    registry,
    order: CONSTELLATION_GROUPS.map((item) => item.id),
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Default State Shape
// ─────────────────────────────────────────────────────────────────────────────
export const defaultState = {
  variant: document.body?.dataset?.variant ?? 'compact',
  mode: 'individual',
  theme: 'light',
  satelliteName: 'Sat-QKD',
  epoch: isoNowLocal(),
  viewMode: 'dual',
  orbital: {
    semiMajor: 6771,
    eccentricity: 0.001,
    inclination: 53,
    raan: 0,
    argPerigee: 0,
    meanAnomaly: 0,
    j2Enabled: true,
  },
  resonance: {
    enabled: true,
    orbits: 1,
    rotations: 1,
  },
  optical: {
    satAperture: 0.6,
    groundAperture: 1.0,
    wavelength: 810,
    groundCn2Day: 5e-14,
    groundCn2Night: 5e-15,
  },
  linkBudget: {
    atmZenithAod: 0.5,
    atmZenithAbs: 0.3,
    pointingErrorUrad: 2.0,
    fixedOpticsLoss: 3.0,
    scintillationEnabled: false,
    scintillationP0: 0.01,
    backgroundEnabled: false,
    bgRadiance: 10,
    bgFovMrad: 0.1,
    bgDeltaLambda: 1.0,
  },
  atmosphere: {
    model: 'hufnagel-valley',
    modelParams: {},
  },
  weather: {
    active: false,
    variable: 'wind_speed',
    level_hpa: 200,
    samples: 120,
    time: isoNowLocal(),
    data: null,
    status: 'idle',
  },
  samplesPerOrbit: 180,
  sceneMode: 'orbit',            // 'orbit' (Earth-centred) | 'helio' (Sun-centred annual)
  helio: {
    interval: 86400,             // total interval in seconds (default 1 day)
    step: 3600,                  // step size in seconds (default 1 hour)
  },
  time: {
    playing: false,
    timeWarp: 60,
    index: 0,
    totalSeconds: 5400,
    timeline: [],
  },
  stations: {
    list: [],
    selectedId: null,
  },
  optimizationPoints: [],
  constellations: createDefaultConstellationState(),
  computed: {
    semiMajor: null,
    orbitPeriod: null,
    dataPoints: [],
    groundTrack: [],
    constellationPositions: {},
    metrics: {
      distanceKm: [],
      elevationDeg: [],
      lossDb: [],
      doppler: [],
      azimuthDeg: [],
      r0_array: [],
      fG_array: [],
      theta0_array: [],
      wind_array: [],
      loss_aod_array: [],
      loss_abs_array: [],
      r0_zenith: null,
      fG_zenith: null,
      theta0_zenith: null,
      wind_rms: null,
      loss_aod_db: null,
      loss_abs_db: null,
      atmosphereProfile: null,
    },
    resonance: {
      requested: false,
      applied: false,
      ratio: null,
      warnings: [],
      semiMajorKm: null,
      deltaKm: null,
      targetPeriodSeconds: null,
      periodSeconds: null,
      perigeeKm: null,
      apogeeKm: null,
      closureSurfaceKm: null,
      closureCartesianKm: null,
      latDriftDeg: null,
      lonDriftDeg: null,
      closed: false,
    },
  },
};

// ─────────────────────────────────────────────────────────────────────────────
// Reactive State + Pub/Sub
// ─────────────────────────────────────────────────────────────────────────────
const listeners = new Set();
export const state = structuredClone(defaultState);

export function subscribe(listener, invokeImmediately = true) {
  if (typeof listener !== 'function') return () => {};
  listeners.add(listener);
  if (invokeImmediately) {
    listener(state);
  }
  return () => listeners.delete(listener);
}

export function emit() {
  listeners.forEach((listener) => {
    try {
      listener(state);
    } catch (err) {
      console.error('State subscriber error', err);
    }
  });
}

export function mutate(mutator) {
  if (typeof mutator !== 'function') return;
  mutator(state);
  emit();
}

export function resetComputed() {
  state.computed = structuredClone(defaultState.computed);
  emit();
}

// ─────────────────────────────────────────────────────────────────────────────
// Theme / Variant
// ─────────────────────────────────────────────────────────────────────────────
export function setTheme(theme) {
  mutate((draft) => {
    draft.theme = theme;
  });
}

export function setVariant(variant) {
  mutate((draft) => {
    draft.variant = variant;
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Station State Helpers
// ─────────────────────────────────────────────────────────────────────────────
export function ensureStationSelected() {
  const { list, selectedId } = state.stations;
  if (list.length === 0) {
    state.stations.selectedId = null;
    return;
  }
  const exists = list.some((item) => item.id === selectedId);
  if (!exists) {
    state.stations.selectedId = list[0].id;
  }
}

export function upsertStation(station) {
  mutate((draft) => {
    const idx = draft.stations.list.findIndex((item) => item.id === station.id);
    if (idx >= 0) {
      draft.stations.list[idx] = station;
    } else {
      draft.stations.list.push(station);
    }
    draft.stations.selectedId = station.id;
  });
}

export function removeStations() {
  mutate((draft) => {
    draft.stations.list = [];
    draft.stations.selectedId = null;
  });
}

export function removeStation(id) {
  if (!id) return;
  mutate((draft) => {
    const filtered = draft.stations.list.filter((item) => item.id !== id);
    draft.stations.list = filtered;
    if (draft.stations.selectedId === id) {
      draft.stations.selectedId = filtered.length ? filtered[0].id : null;
    }
  });
}

export function selectStation(id) {
  mutate((draft) => {
    draft.stations.selectedId = id;
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Timeline / Playback
// ─────────────────────────────────────────────────────────────────────────────
export function setTimeline(data) {
  mutate((draft) => {
    draft.time.timeline = data.timeline;
    draft.time.totalSeconds = data.totalSeconds;
    draft.time.index = Math.min(draft.time.index, data.timeline.length - 1);
  });
}

export function setComputed(payload) {
  mutate((draft) => {
    draft.computed = payload;
  });
}

export function togglePlay(play) {
  mutate((draft) => {
    draft.time.playing = play;
  });
}

export function setTimeIndex(index) {
  mutate((draft) => {
    draft.time.index = index;
  });
}

export function setTimeWarp(value) {
  mutate((draft) => {
    draft.time.timeWarp = value;
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Heliocentric mode helpers
// ─────────────────────────────────────────────────────────────────────────────
export function setSceneMode(mode) {
  mutate((draft) => {
    draft.sceneMode = mode;  // 'orbit' | 'helio'
  });
}

export function setHelioInterval(intervalS) {
  mutate((draft) => {
    draft.helio.interval = intervalS;
  });
}

export function setHelioStep(stepS) {
  mutate((draft) => {
    draft.helio.step = stepS;
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Constellation State Helpers
// ─────────────────────────────────────────────────────────────────────────────
export function withConstellationGroup(groupId, updater) {
  if (!groupId || typeof updater !== 'function') return;
  mutate((draft) => {
    const registry = draft.constellations?.registry;
    if (!registry || !registry[groupId]) return;
    updater(registry[groupId]);
  });
}

export function setConstellationEnabled(groupId, enabled) {
  withConstellationGroup(groupId, (group) => {
    group.enabled = Boolean(enabled);
  });
}

export function setConstellationLoading(groupId, loading) {
  withConstellationGroup(groupId, (group) => {
    group.loading = Boolean(loading);
    if (loading) {
      group.error = null;
    }
  });
}

export function setConstellationMetadata(groupId, metadata = {}) {
  withConstellationGroup(groupId, (group) => {
    if (Object.prototype.hasOwnProperty.call(metadata, 'hasData')) {
      group.hasData = Boolean(metadata.hasData);
    }
    if (Object.prototype.hasOwnProperty.call(metadata, 'count')) {
      group.count = Number(metadata.count) || 0;
    }
    if (Object.prototype.hasOwnProperty.call(metadata, 'fetchedAt')) {
      group.fetchedAt = metadata.fetchedAt ?? null;
    }
  });
}

export function setConstellationError(groupId, message) {
  withConstellationGroup(groupId, (group) => {
    group.error = message || null;
  });
}
