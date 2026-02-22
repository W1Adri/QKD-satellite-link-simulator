// ---------------------------------------------------------------------------
// app/static/main.js
// ---------------------------------------------------------------------------
// Purpose : Application entry point and coordinator.  Owns DOM caching,
//           event binding, orbit computation lifecycle, playback loop,
//           chart rendering, and station / constellation management.
//           Delegates rendering to ui.js and physics to simulation.js/api.js.
//
// Modular Structure (extracted modules):
//   - state.js       : Reactive state management (pub/sub, mutations)
//   - stations.js    : OGS API operations (load, persist, delete)
//   - formatters.js  : Domain-specific value formatters
//   - tooltips.js    : Info tooltip management
//   - weather.js     : Weather field configuration and helpers
//
// NOTE    : Further decomposition of event binding and chart rendering
//           is planned for future iterations.
// ---------------------------------------------------------------------------
import { isoNowLocal, clamp, formatAngle, formatDistanceKm, formatLoss, formatDoppler, formatDuration, findClosestRational } from './utils.js';

// Re-export from extracted modules for this file's internal use
// (keeping local references for backward compatibility with existing code)
import {
  state, defaultState, CONSTELLATION_GROUPS,
  subscribe, emit, mutate, resetComputed,
  setTheme, setVariant, ensureStationSelected,
  upsertStation, removeStation, removeStations, selectStation,
  setTimeline, setComputed, togglePlay, setTimeIndex, setTimeWarp,
  setSceneMode, setHelioInterval, setHelioStep,
  withConstellationGroup, setConstellationEnabled,
  setConstellationLoading, setConstellationMetadata, setConstellationError,
  createDefaultConstellationState
} from './state.js';

import {
  loadStationsFromServer, persistStation, clearStations, deleteStationRemote
} from './stations.js';

import {
  firstFiniteValue, valueFromSeries, formatR0Meters, formatGreenwoodHz,
  formatThetaArcsec, formatWindMps, normalizeLongitude
} from './formatters.js';
// formatKm, formatDecimal, normalizeInt, normalizeTolerance kept local (custom behavior)

import { initInfoButtons } from './tooltips.js';

import {
  WEATHER_FIELDS, setWeatherElements, populateWeatherFieldOptions,
  populateWeatherLevelOptions, sanitizeWeatherSamples, syncWeatherSamplesInputs,
  setWeatherStatus, toWeatherIso
} from './weather.js';
import { orbit, resonanceSolver, walkerGenerator, qkdCalculations } from './simulation.js';
import { map2d, scene3d, initSliders, createPanelAccordions } from './ui.js';
import { fetchSolarData, updateSolarFromBackend, getSolarData, clearSolarData, setSolarHelioMode } from './solar.js';
import { fetchSceneTimeline } from './api.js';

const { constants: orbitConstants } = orbit;
const { searchResonances, periodFromA, aFromPeriod } = resonanceSolver;
const { generateWalkerConstellation } = walkerGenerator;
const { calculateQKDPerformance } = qkdCalculations;

const {
  initMap,
  updateGroundTrack,
  updateSatellitePosition,
  renderStations: renderStations2D,
  updateLinkLine,
  focusOnStation,
  flyToOrbit,
  annotateStationTooltip,
  toggleBaseLayer,
  setBaseLayer,
  invalidateSize: invalidateMap,
  startStationPicker,
  stopStationPicker,
  renderWeatherField,
  clearWeatherField,
  renderConstellations: renderConstellations2D,
  clearConstellationGroup: clearConstellation2D,
} = map2d;
const {
  initScene,
  updateOrbitPath,
  updateSatellite,
  renderStations: renderStations3D,
  updateLink: updateLink3D,
  setEarthRotationFromTime,
  setTheme: setSceneTheme,
  frameOrbitView,
  updateGroundTrackSurface,
  updateGroundTrackVector,
  renderConstellations: renderConstellations3D,
  clearConstellation: clearConstellation3D,
  // Heliocentric mode
  setHelioMode: setSceneHelioMode,
  setEarthHelioPosition,
  updateEarthOrbitPath,
  updateSolarLighting,
} = scene3d;

const { EARTH_RADIUS_KM, MIN_SEMI_MAJOR, MAX_SEMI_MAJOR } = orbitConstants;

const elements = {};
const DRAFT_SAMPLES_PER_ORBIT = 36;

let orbitSamplesOverride = null;
let mapInstance;
let currentMapStyle = 'standard';
let lastOrbitSignature = '';
let lastMetricsSignature = '';
let lastWeatherSignature = '';
let playingRaf = null;
let panelWidth = 360;
let lastExpandedPanelWidth = 360;
let hasMapBeenFramed = false;
let hasSceneBeenFramed = false;
let modalChartInstance = null;
let stationPickCleanup = null;
let _sceneTimelineData = null;     // cached scene-timeline response for helio mode
const stationDialogDragState = {
  active: false,
  startX: 0,
  startY: 0,
  dialogX: 0,
  dialogY: 0,
};

const optimizerState = {
  results: [],
  query: null,
};

const constellationStore = new Map();
let lastConstellationIndex = -1;

const PANEL_MIN_WIDTH = 240;
const PANEL_MAX_WIDTH = 520;
const PANEL_COLLAPSE_THRESHOLD = 280;

function updateStationPickHint(lat = null, lon = null, awaiting = false) {
  const hintEl = elements.stationPickHint;
  if (!hintEl) return;

  if (awaiting) {
    hintEl.hidden = false;
    hintEl.classList.add('is-active');
    hintEl.textContent = 'Click the map to set the location.';
    return;
  }

  if (Number.isFinite(lat) && Number.isFinite(lon)) {
    hintEl.hidden = false;
    hintEl.classList.add('is-active');
    hintEl.textContent = `Selected location: ${lat.toFixed(4)}Â°, ${lon.toFixed(4)}Â°`;
    return;
  }

  hintEl.hidden = true;
  hintEl.classList.remove('is-active');
  hintEl.textContent = 'Click the map to set the location.';
}

function setStationPickMode(active) {
  if (!elements.stationPickOnMap) return;
  if (active && !mapInstance) {
    console.warn('Map is not ready yet to pick stations.');
    return;
  }
  const currentlyActive = Boolean(stationPickCleanup);
  if (active && !currentlyActive) {
    const lat = Number(elements.stationLat?.value);
    const lon = Number(elements.stationLon?.value);
    const normalizedInitialLon = Number.isFinite(lon) ? normalizeLongitude(lon) : undefined;
    const initial = Number.isFinite(lat) && normalizedInitialLon !== undefined
      ? { lat, lon: normalizedInitialLon }
      : undefined;

    stationPickCleanup = startStationPicker(({ lat: pickedLat, lon: pickedLon }) => {
      const normalizedLon = normalizeLongitude(pickedLon);
      if (elements.stationLat) {
        elements.stationLat.value = pickedLat.toFixed(4);
      }
      if (elements.stationLon) {
        elements.stationLon.value = normalizedLon.toFixed(4);
      }
      updateStationPickHint(pickedLat, normalizedLon, false);
    }, initial);

    elements.stationPickOnMap.dataset.active = 'true';
    elements.stationPickOnMap.textContent = 'Cancel selection';
    if (initial) {
      updateStationPickHint(initial.lat, initial.lon, false);
    } else {
      updateStationPickHint(null, null, true);
    }
    return;
  }

  if (!active && currentlyActive) {
    stationPickCleanup?.();
    stationPickCleanup = null;
    stopStationPicker();
    elements.stationPickOnMap.dataset.active = 'false';
  elements.stationPickOnMap.textContent = 'Pick on map';
    updateStationPickHint();
  }
}

function syncStationPickHintFromInputs() {
  if (stationPickCleanup) return;
  const lat = Number(elements.stationLat?.value);
  const lon = Number(elements.stationLon?.value);
  if (Number.isFinite(lat) && Number.isFinite(lon)) {
    updateStationPickHint(lat, normalizeLongitude(lon), false);
  } else {
    updateStationPickHint();
  }
}

async function saveStationFromDialog() {
  const name = elements.stationName?.value.trim() ?? '';
  const lat = Number(elements.stationLat?.value);
  const lon = Number(elements.stationLon?.value);
  const aperture = Number(elements.stationAperture?.value ?? 1.0);

  if (!name) {
    elements.stationName?.focus();
    return;
  }
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    updateStationPickHint(null, null, true);
    elements.stationLat?.focus();
    return;
  }

  const normalizedLon = normalizeLongitude(lon);
  if (elements.stationLon) {
    elements.stationLon.value = normalizedLon.toFixed(4);
  }

  const id = `${name.replace(/\s+/g, '-').toLowerCase()}-${Date.now()}`;
  const station = { id, name, lat, lon: normalizedLon, aperture };
  upsertStation(station);
  persistStation(station);
  setStationPickMode(false);
  updateStationPickHint();
  elements.stationDialog?.close('saved');
  refreshStationSelect();
  await recomputeMetricsOnly(true);
}

function resetStationDialogPosition() {
  if (!elements.stationDialog) return;
  elements.stationDialog.style.left = '50%';
  elements.stationDialog.style.top = '50%';
  elements.stationDialog.style.transform = 'translate(-50%, -50%)';
}

function setStationDialogPosition(x, y) {
  if (!elements.stationDialog) return;
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;
  const rect = elements.stationDialog.getBoundingClientRect();
  const clampedX = clamp(x, 8, viewportWidth - rect.width - 8);
  const clampedY = clamp(y, 8, viewportHeight - rect.height - 8);
  elements.stationDialog.style.left = `${clampedX}px`;
  elements.stationDialog.style.top = `${clampedY}px`;
  elements.stationDialog.style.transform = 'translate(0, 0)';
}

function beginStationDialogDrag(event) {
  if (!elements.stationDialog) return;
  event.preventDefault();
  stationDialogDragState.active = true;
  stationDialogDragState.startX = event.clientX;
  stationDialogDragState.startY = event.clientY;
  const rect = elements.stationDialog.getBoundingClientRect();
  stationDialogDragState.dialogX = rect.left;
  stationDialogDragState.dialogY = rect.top;
  elements.stationDialog.classList.add('is-dragging');
  window.addEventListener('pointermove', handleStationDialogDragMove);
  window.addEventListener('pointerup', endStationDialogDrag, { once: true });
  window.addEventListener('pointercancel', endStationDialogDrag, { once: true });
}

function handleStationDialogDragMove(event) {
  if (!stationDialogDragState.active) return;
  const deltaX = event.clientX - stationDialogDragState.startX;
  const deltaY = event.clientY - stationDialogDragState.startY;
  setStationDialogPosition(stationDialogDragState.dialogX + deltaX, stationDialogDragState.dialogY + deltaY);
}

function endStationDialogDrag() {
  if (!stationDialogDragState.active) {
    window.removeEventListener('pointermove', handleStationDialogDragMove);
    window.removeEventListener('pointerup', endStationDialogDrag);
    window.removeEventListener('pointercancel', endStationDialogDrag);
    elements.stationDialog?.classList.remove('is-dragging');
    return;
  }
  stationDialogDragState.active = false;
  elements.stationDialog?.classList.remove('is-dragging');
  window.removeEventListener('pointermove', handleStationDialogDragMove);
  window.removeEventListener('pointerup', endStationDialogDrag);
  window.removeEventListener('pointercancel', endStationDialogDrag);
}

function openStationDialog() {
  if (!elements.stationDialog) return;
  resetStationDialogPosition();
  endStationDialogDrag();
  if (!elements.stationDialog.open) {
    try {
      elements.stationDialog.show();
    } catch (error) {
      console.warn('Could not open the station dialog', error);
    }
  }
  elements.stationName?.focus();
}

function cacheElements() {
  const ids = [
    'satelliteName', 'epochInput', 'semiMajor', 'semiMajorSlider', 'optToleranceA', 'optToleranceSlider',
    'optMinRot', 'optMinRotSlider', 'optMaxRot', 'optMaxRotSlider', 'optMinOrb', 'optMinOrbSlider', 'optMaxOrb', 'optMaxOrbSlider',
    'eccentricity', 'eccentricitySlider', 'inclination', 'inclinationSlider', 'raan', 'raanSlider', 'argPerigee', 'argPerigeeSlider',
    'meanAnomaly', 'meanAnomalySlider',
    'satAperture', 'satApertureSlider', 'groundAperture', 'groundApertureSlider', 'wavelength',
    'wavelengthSlider', 'samplesPerOrbit', 'samplesPerOrbitSlider', 'timeSlider', 'btnPlay', 'btnPause',
    'btnStepBack', 'btnStepForward', 'btnResetTime', 'timeWarp', 'btnTheme', 'btnPanelToggle',
  'btnMapStyle', 'panelResizer', 'stationSelect', 'btnAddStation', 'btnDeleteStation', 'btnFocusStation', 'timeLabel', 'totalDurationLabel', 'btnMenuToggle',
    'elevationLabel', 'lossLabel', 'distanceMetric', 'elevationMetric', 'zenithMetric', 'lossMetric',
    'dopplerMetric', 'threeContainer', 'mapContainer', 'orbitMessages',
    'stationDialog', 'stationName', 'stationLat', 'stationLon', 'stationAperture', 'stationSave', 'stationCancel',
    'optimizerForm', 'optSearchBtn', 'optSummary', 'optResults',
    'graphModal', 'graphModalTitle', 'modalChartCanvas', 'closeGraphModal',
    'groundCn2Day', 'groundCn2Night', 'r0Metric', 'fGMetric', 'theta0Metric', 'windMetric',
    'stationPickOnMap', 'stationPickHint', 'optDiagnostics', 'resonanceGraph',
    'weatherFieldSelect', 'weatherLevelSelect', 'weatherSamples', 'weatherSamplesSlider',
    'weatherTime', 'weatherFetchBtn', 'weatherClearBtn', 'weatherStatus',
    'constellationList', 'constellationStatus',
    'walkerPanel', 'walkerT', 'walkerP', 'walkerF', 'walkerA', 'walkerI', 'btnPlotConstellation', 'btnClearOrbit', 'btnClearConstellation',
    'btnDefinePoints', 'btnOptimize', 'btnCancelOptimize', 'simDuration', 'pointsCount', 'optStatus', 'optProgress', 'workerToggle', 'workerCount',
    // QKD elements
    'qkdProtocol', 'photonRate', 'photonRateSlider', 'detectorEfficiency', 'detectorEfficiencySlider',
    'darkCountRate', 'darkCountRateSlider', 'opticalFilterBandwidth', 'opticalFilterBandwidthSlider',
    'btnCalculateQKD', 'qkdStatus', 'qberMetric', 'rawKeyRateMetric', 'secureKeyRateMetric', 'channelTransmittanceMetric',
    'j2Toggle',
    // Heliocentric mode controls
    'sceneModeSelect', 'helioControls', 'helioInterval', 'helioStep', 'helioSampleCount',
  ];
  ids.forEach((id) => {
    elements[id] = document.getElementById(id);
  });
  elements.workspace = document.querySelector('.workspace');
  elements.controlPanel = document.getElementById('controlPanel');
  elements.panelTitle = document.querySelector('.panel-header .panel-title');
  elements.panelTabs = document.querySelectorAll('.panel-tabs [data-section-target]');
  elements.panelSections = document.querySelectorAll('.panel-section');
  elements.viewTabs = document.querySelectorAll('[data-view]');
  elements.viewGrid = document.getElementById('viewGrid');
  elements.resonanceHint = document.querySelector('[data-resonance-hint]');
  elements.atmosModelInputs = document.querySelectorAll('input[name="atmosModel"]');
}

function getConstellationConfig(groupId) {
  return CONSTELLATION_GROUPS.find((group) => group.id === groupId) ?? null;
}

function setConstellationStatusMessage(message = '', status = 'idle') {
  if (!elements.constellationStatus) return;
  if (!message) {
    elements.constellationStatus.hidden = true;
    elements.constellationStatus.textContent = '';
    elements.constellationStatus.dataset.status = 'idle';
    return;
  }
  elements.constellationStatus.textContent = message;
  elements.constellationStatus.dataset.status = status;
  elements.constellationStatus.hidden = false;
}

function renderConstellationControls() {
  if (!elements.constellationList) return;
  elements.constellationList.innerHTML = '';
  CONSTELLATION_GROUPS.forEach((group) => {
    const label = document.createElement('label');
    label.className = 'constellation-toggle';
    label.dataset.constellation = group.id;
    label.style.setProperty('--constellation-color', group.color);

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.dataset.constellation = group.id;
    checkbox.disabled = !window.satellite;
    label.appendChild(checkbox);

    const name = document.createElement('span');
    name.className = 'constellation-name';
    name.textContent = group.label;
    label.appendChild(name);

    const count = document.createElement('span');
    count.className = 'constellation-count';
    count.hidden = true;
    label.appendChild(count);

    elements.constellationList.appendChild(label);
  });

  if (!window.satellite) {
    setConstellationStatusMessage('satellite.js failed to load; constellation overlays are unavailable.', 'error');
  } else {
    setConstellationStatusMessage('Select constellations to overlay on the map and globe.', 'idle');
  }

  updateConstellationToggleStates();
}

function updateConstellationToggleStates(snapshot = state) {
  if (!elements.constellationList) return;
  const registry = snapshot.constellations?.registry ?? {};
  CONSTELLATION_GROUPS.forEach((group) => {
    const selector = `.constellation-toggle[data-constellation="${group.id}"]`;
    const label = elements.constellationList.querySelector(selector);
    if (!label) return;
    const checkbox = label.querySelector('input[type="checkbox"][data-constellation]');
    const groupState = registry[group.id] ?? {};
    if (checkbox && !checkbox.matches(':focus')) {
      checkbox.checked = Boolean(groupState.enabled);
      checkbox.disabled = Boolean(groupState.loading) || !window.satellite;
    }
    label.dataset.active = groupState.enabled ? 'true' : 'false';
    label.dataset.loading = groupState.loading ? 'true' : 'false';
    label.dataset.error = groupState.error ? 'true' : 'false';
    const countEl = label.querySelector('.constellation-count');
    if (countEl) {
      if (groupState.count) {
        countEl.hidden = false;
        countEl.textContent = String(groupState.count);
      } else {
        countEl.hidden = true;
        countEl.textContent = '';
      }
    }
  });
}

function hasActiveConstellations(snapshot = state) {
  const registry = snapshot.constellations?.registry;
  if (!registry) return false;
  return Object.values(registry).some((group) => group?.enabled);
}

function getActiveConstellationDatasets() {
  const registry = state.constellations?.registry ?? {};
  return CONSTELLATION_GROUPS.map((group) => {
    if (!registry[group.id]?.enabled) return null;
    const storeEntry = constellationStore.get(group.id);
    if (!storeEntry || !Array.isArray(storeEntry.entries) || !storeEntry.entries.length) {
      return null;
    }
    return {
      id: group.id,
      color: storeEntry.color ?? group.color,
      entries: storeEntry.entries,
    };
  }).filter(Boolean);
}

function computeConstellationPositions(timeline, epochIso, datasets) {
  if (!Array.isArray(timeline) || !timeline.length) return {};
  if (!Array.isArray(datasets) || !datasets.length) return {};
  const satLib = window.satellite;
  if (!satLib) return {};

  const epochDate = new Date(epochIso);
  const epochMs = epochDate.getTime();
  if (Number.isNaN(epochMs)) return {};

  const sampleDates = timeline.map((seconds) => new Date(epochMs + seconds * 1000));
  
  const result = {};

  datasets.forEach((dataset) => {
    if (!dataset) return;
    const satellites = [];
    dataset.entries.forEach((entry) => {
      if (!entry?.satrec) return;

      const satTimeline = [];
      const groundTrack = [];
      const orbitPath = [];

      sampleDates.forEach(date => {
          const posVel = satLib.propagate(entry.satrec, date);
          const posEci = posVel.position;
          if (!posEci) return;
          
          const gmst = satLib.gstime(date);
          const geo = satLib.eciToGeodetic(posEci, gmst);

          const point = {
              lat: satLib.degreesLat(geo.latitude),
              lon: satLib.degreesLong(geo.longitude),
              alt: geo.height,
              rEci: [posEci.x, posEci.y, posEci.z],
              gmst,
          };
          
          satTimeline.push(point);
          const dataPoint = { ...point, rEci: { x: posEci.x, y: posEci.y, z: posEci.z }};
          orbitPath.push(dataPoint);
          groundTrack.push({ lat: point.lat, lon: point.lon });
      });

      satellites.push({
        id: entry.id,
        name: entry.name,
        timeline: satTimeline,
        groundTrack: groundTrack,
        orbitPath: orbitPath,
      });
    });
    if (satellites.length) {
      result[dataset.id] = {
        color: dataset.color,
        satellites,
      };
    }
  });

  return result;
}

function refreshConstellationPositions({ force = false } = {}) {
  if (!hasActiveConstellations()) {
    mutate((draft) => {
      draft.computed.constellationPositions = {};
    });
    lastConstellationIndex = -1;
    return;
  }
  if (!window.satellite) {
    setConstellationStatusMessage('satellite.js is required to enable constellation overlays.', 'error');
    return;
  }
  const timeline = state.time.timeline ?? [];
  if (!timeline.length) return;
  const datasets = getActiveConstellationDatasets();
  if (!datasets.length) {
    mutate((draft) => {
      draft.computed.constellationPositions = {};
    });
    lastConstellationIndex = -1;
    return;
  }

  if (!force) {
    const currentMap = state.computed?.constellationPositions ?? {};
    const hasAllGroups = datasets.every((dataset) => currentMap[dataset.id]);
    if (hasAllGroups && Object.keys(currentMap).length === datasets.length) {
      return;
    }
  }

  const positions = computeConstellationPositions(timeline, state.epoch, datasets);
  mutate((draft) => {
    draft.computed.constellationPositions = positions;
  });
  lastConstellationIndex = -1;
}

function clearAllConstellations() {
  CONSTELLATION_GROUPS.forEach((group) => {
    clearConstellation2D(group.id);
    clearConstellation3D(group.id);
  });
  lastConstellationIndex = -1;
}

function activatePanelSection(sectionId) {
  setPanelCollapsed(false);
  if (!elements.panelSections?.length) return;
  const target = sectionId || elements.panelSections[0]?.dataset.section;
  elements.panelSections.forEach((section) => {
    const active = section.dataset.section === target;
    section.classList.toggle('is-active', active);
    section.classList.toggle('active', active);
    section.hidden = !active;
  });
  elements.panelTabs?.forEach((tab) => {
    const active = tab.dataset.sectionTarget === target;
    tab.classList.toggle('is-active', active);
    tab.setAttribute('aria-pressed', active ? 'true' : 'false');
  });

  // Update panel title based on active section
  const activeNavItem = document.querySelector(`.sidebar .nav-item[data-section="${target}"]`);
  if (elements.panelTitle && activeNavItem) {
    elements.panelTitle.textContent = activeNavItem.dataset.title || '';
  }
}

function setPanelCollapsed(collapsed) {
  if (!elements.controlPanel || !elements.workspace) return;
  const isAlreadyCollapsed = elements.controlPanel.dataset.collapsed === 'true';
  if (collapsed && !isAlreadyCollapsed) {
    const rect = elements.controlPanel.getBoundingClientRect();
    panelWidth = rect.width;
    if (panelWidth >= PANEL_COLLAPSE_THRESHOLD) {
      lastExpandedPanelWidth = panelWidth;
    }
  }
  if (!collapsed && isAlreadyCollapsed) {
    applyPanelWidth(lastExpandedPanelWidth || panelWidth || 360);
  }
  elements.controlPanel.dataset.collapsed = collapsed ? 'true' : 'false';
  elements.workspace.classList.toggle('panel-collapsed', collapsed);
  if (elements.btnPanelToggle) {
    elements.btnPanelToggle.textContent = 'Hide';
    elements.btnPanelToggle.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
  }
  if (elements.panelResizer) {
    elements.panelResizer.setAttribute('aria-hidden', collapsed ? 'true' : 'false');
    elements.panelResizer.tabIndex = collapsed ? -1 : 0;
  }
  setTimeout(() => invalidateMap(), 250);
}

function applyPanelWidth(width) {
  panelWidth = clamp(width, PANEL_MIN_WIDTH, PANEL_MAX_WIDTH);
  if (elements.controlPanel) {
    elements.controlPanel.style.setProperty('--panel-width', `${panelWidth}px`);
  }
}

function normalizeInt(value, min, max) {
  const numeric = Math.round(Number(value) || 0);
  return clamp(numeric, min, max);
}

function normalizeTolerance(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric) || numeric < 0) {
    return 0;
  }
  const snapped = Math.round(numeric * 2) / 2;
  return clamp(snapped, 0, 1000);
}

function formatDecimal(value, decimals = 3) {
  if (!Number.isFinite(value)) return '';
  const fixed = Number(value).toFixed(decimals);
  return fixed
    .replace(/\.(\d*?[1-9])0+$/, '.$1')
    .replace(/\.0+$/, '')
    .replace(/\.$/, '');
}

function syncPairValue(inputId, sliderId, value, spanId = null) {
  const numeric = Number(value);
  if (elements[inputId]) {
    if (Number.isFinite(numeric)) {
      if (inputId === 'semiMajor' || inputId === 'optToleranceA') {
        elements[inputId].value = numeric.toFixed(0); // Remove decimals for semiMajor and optToleranceA
      } else {
        elements[inputId].value = String(numeric);
      }
    } else {
      elements[inputId].value = String(value);
    }
  }
  if (elements[sliderId]) {
    if (Number.isFinite(numeric) && sliderId === 'semiMajorSlider') {
      elements[sliderId].value = String(numeric);
    } else {
      elements[sliderId].value = Number.isFinite(numeric) ? String(numeric) : String(value);
    }
  }
  if (spanId && elements[spanId]) {
      elements[spanId].textContent = String(numeric);
  }
}

function ensureOrderedIntRange(minId, minSliderId, maxId, maxSliderId, minLimit, maxLimit) {
  const minValue = normalizeInt(elements[minId]?.value, minLimit, maxLimit);
  let maxValue = normalizeInt(elements[maxId]?.value, minLimit, maxLimit);
  let adjustedMin = minValue;
  if (maxValue < minValue) {
    maxValue = minValue;
  }
  if (adjustedMin > maxLimit) {
    adjustedMin = maxLimit;
  }
  syncPairValue(minId, minSliderId, adjustedMin);
  syncPairValue(maxId, maxSliderId, maxValue);
  return { min: adjustedMin, max: maxValue };
}

function formatKm(value, fractionDigits = 3, useGrouping = true) {
  if (!Number.isFinite(value)) return '--';
  return Number(value).toLocaleString('en-US', {
    useGrouping,
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  });
}

function renderOptimizerResults(partial = false) {
  if (!elements.optResults) return;
  const { results, query } = optimizerState;
  if (elements.optDiagnostics) {
    elements.optDiagnostics.innerHTML = '';
  }

  if (!query) {
    if (elements.optSummary) elements.optSummary.textContent = '';
    elements.optResults.innerHTML = '<p class="hint">Enter a target and press "Search resonances".</p>';
    return;
  }

  const { targetA, toleranceKm, minRotations, maxRotations, minOrbits, maxOrbits } = query;
  const toleranceText = `${formatKm(toleranceKm, 0)} km`; // Removed decimals for tolerance
  const summaryPrefix = partial ? 'Partially Resonant: ' : 'Result: ';

  if (elements.optSummary) {
    elements.optSummary.textContent = `${summaryPrefix}${results.length} match(es) for aâ‚€ = ${formatKm(
      targetA,
      0, // Removed decimals for semiMajor in summary
    )} km Â± ${toleranceText}, j âˆˆ [${minRotations}, ${maxRotations}], k âˆˆ [${minOrbits}, ${maxOrbits}].`;
  }

  if (!results.length) {
    elements.optResults.innerHTML =
      '<p class="hint">No exact resonances found. See diagnostics below for suggestions.</p>';
    diagnoseAndSuggestResonances(query);
    return;
  }

  const table = document.createElement('table');
  table.className = 'resonance-table';
  table.innerHTML =
    '<thead><tr><th>j</th><th>k</th><th>j/k</th><th>a (km)</th><th>Î”a (km)</th><th>Period</th><th></th></tr></thead>';
  const tbody = document.createElement('tbody');
  const maxRows = Math.min(results.length, 200);
  for (let idx = 0; idx < maxRows; idx += 1) {
    const hit = results[idx];
    const delta = hit.deltaKm;
    const deltaText = `${delta >= 0 ? '+' : ''}${formatKm(delta, 0)}`; // Removed decimals for deltaKm
    const row = document.createElement('tr');
    row.innerHTML = `
      <td>${hit.j}</td>
      <td>${hit.k}</td>
  <td>${formatKm(hit.ratio, 6, false)}</td>
      <td>${formatKm(hit.semiMajorKm, 0)}</td>
      <td>${deltaText}</td>
      <td>${formatDuration(hit.periodSec)}</td>
      <td><button type="button" class="apply-btn" data-index="${idx}">âœ“</button></td>
    `;
    tbody.appendChild(row);
  }
  table.appendChild(tbody);
  elements.optResults.innerHTML = '';
  elements.optResults.appendChild(table);

  if (results.length > maxRows) {
    const note = document.createElement('p');
    note.className = 'hint';
    note.textContent = `Showing ${maxRows} of ${results.length} results. Adjust the tolerance to narrow the search.`;
    elements.optResults.appendChild(note);
  }
}

const NORMAL_TOLERANCE_PERCENT = 2;
const PARTIAL_TOLERANCE_MULTIPLIER = 5;

function runResonanceSearch() {
  if (!elements.semiMajor || !elements.optResults) return;
  const rawTarget = Number(elements.semiMajor.value);
  if (!Number.isFinite(rawTarget) || rawTarget <= 0) {
    optimizerState.results = [];
    optimizerState.query = null;
    elements.optResults.innerHTML = '<p class="hint">Set a valid target semi-major axis (&gt; 0 km).</p>';
    if (elements.optSummary) elements.optSummary.textContent = '';
    return;
  }

  const targetA = clamp(rawTarget, MIN_SEMI_MAJOR, MAX_SEMI_MAJOR);
  const sanitizedTarget = Number(targetA.toFixed(3));
  syncPairValue('semiMajor', 'semiMajorSlider', sanitizedTarget);
  if (Math.abs((state.orbital.semiMajor ?? 0) - sanitizedTarget) > 1e-3) {
    mutate((draft) => {
      draft.orbital.semiMajor = sanitizedTarget;
    });
  }

  const toleranceKm = targetA * (NORMAL_TOLERANCE_PERCENT / 100);
  syncPairValue('optToleranceA', 'optToleranceSlider', toleranceKm);

  const rotationBounds = ensureOrderedIntRange('optMinRot', 'optMinRotSlider', 'optMaxRot', 'optMaxRotSlider', 1, 500);
  const orbitBounds = ensureOrderedIntRange('optMinOrb', 'optMinOrbSlider', 'optMaxOrb', 'optMaxOrbSlider', 1, 500);
  
  const query = {
    targetA: sanitizedTarget,
    toleranceKm,
    minRotations: rotationBounds.min,
    maxRotations: rotationBounds.max,
    minOrbits: orbitBounds.min,
    maxOrbits: orbitBounds.max,
  };

  let results = searchResonances(query);
  let partial = false;

  if (results.length === 0) {
    const partialQuery = { ...query, toleranceKm: query.toleranceKm * PARTIAL_TOLERANCE_MULTIPLIER };
    results = searchResonances(partialQuery);
    if (results.length > 0) {
      partial = true;
    }
  }

  optimizerState.results = results;
  optimizerState.query = query; // Still store original query for diagnostics

  renderOptimizerResults(partial);
  renderResonanceGraph(query);
}

function diagnoseAndSuggestResonances(query) {
  if (!elements.optDiagnostics) return;

  const { targetA, minRotations, maxRotations, minOrbits, maxOrbits } = query;
  const physicalPeriod = periodFromA(targetA);
  // physicalRatio is j/k. period = (j/k) * sidereal_day. So physicalRatio = period / sidereal_day.
  const physicalRatio = physicalPeriod / resonanceSolver.SIDEREAL_DAY;

  const midJ = Math.round((minRotations + maxRotations) / 2);
  const midK = Math.round((minOrbits + maxOrbits) / 2);
  const requestedRatio = midJ / midK; // j/k

  const lines = ['<div class="diagnostic-message">'];
  lines.push('<h4>The Proactive Assistant</h4>');

  // 1. Intelligent Error Diagnosis
  // physical period is T_phys = 2pi * sqrt(a^3/mu)
  // requested period is T_req = (j/k) * T_sidereal
  // if T_phys < T_req, satellite is too fast for the requested slow resonance.
  // if T_phys > T_req, satellite is too slow for the requested fast resonance.
  const physicalPeriodHours = physicalPeriod / 3600;
  const requestedPeriodHours = (midJ / midK) * (resonanceSolver.SIDEREAL_DAY / 3600);

  if (physicalPeriod < requestedPeriodHours * 3600 * 0.9) { // Scenario A: Low altitude (fast) but slow resonance
      const requiredAltitude = aFromPeriod((midJ / midK) * resonanceSolver.SIDEREAL_DAY) - EARTH_RADIUS_KM;
      const fasterResonance = findClosestRational(physicalRatio, 30);
      lines.push('<p><strong>Physical Conflict:</strong> At this altitude ('+formatKm(targetA - EARTH_RADIUS_KM, 0)+' km), the satellite travels too fast for the slow resonance you are requesting ('+midJ+':'+midK+').</p>');
      lines.push(`<p><strong>Suggestion:</strong> You would need to raise the altitude to ${formatKm(requiredAltitude, 0)} km or change the resonance to something faster (e.g., ${fasterResonance.j}:${fasterResonance.k}).</p>`);

  } else if (physicalPeriod > requestedPeriodHours * 3600 * 1.1) { // Scenario B: High altitude (slow) but fast resonance
      const requiredAltitude = aFromPeriod((midJ / midK) * resonanceSolver.SIDEREAL_DAY) - EARTH_RADIUS_KM;
      lines.push('<p><strong>Physical Conflict:</strong> At this altitude, the satellite is too slow for the fast resonance you are requesting.</p>');
      lines.push(`<p><strong>Suggestion:</strong> You need to lower the altitude to ${formatKm(requiredAltitude,0)} km or request fewer orbits per day.</p>`);
  }

  lines.push('<hr>');
  lines.push('<h4>The Navigator</h4>');

  // 2. Automatic Suggestions
  // Keep Altitude, find Resonance
  const closestNatural = findClosestRational(physicalRatio, 50);
  if (closestNatural.j > 0 && closestNatural.k > 0) {
      const closestNatural2 = findClosestRational(physicalRatio, 50, [closestNatural]);
      lines.push(`<p><strong>For your altitude of ${formatKm(targetA - EARTH_RADIUS_KM, 0)} km:</strong> The closest natural resonance is ${closestNatural.j}:${closestNatural.k} or ${closestNatural2.j}:${closestNatural2.k}.</p>`);
  }

  // Keep Resonance, find Altitude
  const targetAltitude = aFromPeriod((midJ / midK) * resonanceSolver.SIDEREAL_DAY);
  if (isFinite(targetAltitude)) {
    lines.push(`<p><strong>To maintain the ${midJ}:${midK} resonance:</strong> You would have to move the satellite to ${formatKm(targetAltitude - EARTH_RADIUS_KM, 0)} km altitude.</p>`);
  }

  // Suggest closest options if no exact matches were found in the search
  if (!optimizerState.results || optimizerState.results.length === 0) {
    lines.push('<hr>');
    lines.push('<h4>Closest Resonance Options for Current Semi-Major Axis</h4>');

    let bestClosest = null;
    let minDeltaA = Infinity;

    // Iterate through all possible j and k within bounds
    for (let j = query.minRotations; j <= query.maxRotations; j++) {
      for (let k = query.minOrbits; k <= query.maxOrbits; k++) {
        // Skip trivial or invalid ratios (e.g., 0:0, 1:0)
        if (j === 0 || k === 0) continue;

        const period = (j / k) * resonanceSolver.SIDEREAL_DAY;
        const currentSemiMajor = aFromPeriod(period);
        const deltaA = Math.abs(currentSemiMajor - targetA);

        if (deltaA < minDeltaA) {
          minDeltaA = deltaA;
          bestClosest = { j, k, semiMajorKm: currentSemiMajor };
        }
      }
    }

    if (bestClosest) {
      const deltaAFromTarget = bestClosest.semiMajorKm - targetA;
      lines.push(`<p>The closest resonance for aâ‚€ = ${formatKm(targetA, 0)} km is <strong>${bestClosest.j}:${bestClosest.k}</strong>.`);
      lines.push(`<p>This resonance implies a semi-major axis of ${formatKm(bestClosest.semiMajorKm, 0)} km, which is ${formatKm(deltaAFromTarget, 0)} km from your target.</p>`);
      lines.push(`<p>Consider increasing your search tolerance to include this option.</p>`);
    } else {
      lines.push('<p>No close resonance options found within the given rotation and orbit bounds.</p>');
    }
  }

  lines.push('</div>');
  elements.optDiagnostics.innerHTML = lines.join('');
}

function renderResonanceGraph(query) {
  const canvas = elements.resonanceGraph;
  if (!canvas || !query) return;

  canvas.style.display = 'block';
  const ctx = canvas.getContext('2d');
  const width = canvas.width;
  const height = canvas.height;

  const padding = { top: 20, right: 20, bottom: 40, left: 50 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;

  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = getComputedStyle(document.body).getPropertyValue('--text').trim();
  ctx.strokeStyle = getComputedStyle(document.body).getPropertyValue('--border').trim();
  ctx.font = '10px Inter';

  // Find altitude range for graph
  const minAlt = MIN_SEMI_MAJOR - EARTH_RADIUS_KM;
  const maxAlt = MAX_SEMI_MAJOR - EARTH_RADIUS_KM;

  // Find k/j range
  const minKj = (resonanceSolver.SIDEREAL_DAY / periodFromA(MAX_SEMI_MAJOR));
  const maxKj = (resonanceSolver.SIDEREAL_DAY / periodFromA(MIN_SEMI_MAJOR));
  
  const altToX = (alt) => padding.left + ((alt - minAlt) / (maxAlt - minAlt)) * plotWidth;
  const kjToY = (kj) => padding.top + plotHeight - ((kj - minKj) / (maxKj - minKj)) * plotHeight;

  // Draw axes
  ctx.beginPath();
  ctx.moveTo(padding.left, padding.top);
  ctx.lineTo(padding.left, height - padding.bottom);
  ctx.lineTo(width - padding.right, height - padding.bottom);
  ctx.stroke();

  // Y-axis labels (k/j)
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  for (let i = 0; i <= 5; i++) {
    const kj = minKj + (i / 5) * (maxKj - minKj);
    const y = kjToY(kj);
    ctx.fillText(kj.toFixed(1), padding.left - 5, y);
    ctx.beginPath();
    ctx.moveTo(padding.left - 2, y);
    ctx.lineTo(padding.left, y);
    ctx.stroke();
  }
  ctx.save();
  ctx.translate(15, height / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.textAlign = 'center';
  ctx.fillText('Resonance Ratio (k/j)', 0, 0);
  ctx.restore();

  // X-axis labels (Altitude)
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  for (let i = 0; i <= 5; i++) {
    const alt = minAlt + (i / 5) * (maxAlt - minAlt);
    const x = altToX(alt);
    ctx.fillText((alt / 1000).toFixed(0) + 'k', x, height - padding.bottom + 5);
    ctx.beginPath();
    ctx.moveTo(x, height - padding.bottom);
    ctx.lineTo(x, height - padding.bottom + 2);
    ctx.stroke();
  }
  ctx.fillText('Altitude (km)', padding.left + plotWidth / 2, height - 15);

  // Draw Kepler's Law curve
  ctx.beginPath();
  ctx.strokeStyle = '#0ea5e9';
  let firstPoint = true;
  for (let px = 0; px <= plotWidth; px++) {
    const alt = minAlt + (px / plotWidth) * (maxAlt - minAlt);
    const a = alt + EARTH_RADIUS_KM;
    const period = periodFromA(a);
    const kj = resonanceSolver.SIDEREAL_DAY / period;
    const x = altToX(alt);
    const y = kjToY(kj);
    if (firstPoint) {
      ctx.moveTo(x, y);
      firstPoint = false;
    } else {
      ctx.lineTo(x, y);
    }
  }
  ctx.stroke();

  // Draw user's point
  const userAlt = query.targetA - EARTH_RADIUS_KM;
  const userKj = (query.minOrbits + query.maxOrbits) / 2 / ((query.minRotations + query.maxRotations) / 2);
  const userX = altToX(userAlt);
  const userY = kjToY(userKj);
  
  ctx.fillStyle = '#ef4444';
  ctx.beginPath();
  ctx.arc(userX, userY, 4, 0, 2 * Math.PI);
  ctx.fill();
}


async function applyResonanceCandidate(hit) {
  if (!hit) return;

  mutate((draft) => {
    draft.resonance.enabled = true;
    draft.resonance.orbits = hit.k;
    draft.resonance.rotations = hit.j;
    draft.orbital.semiMajor = Number(hit.semiMajorKm.toFixed(3));
  });
  if (elements.semiMajor && !elements.semiMajor.matches(':focus')) {
    elements.semiMajor.value = formatDecimal(Number(hit.semiMajorKm));
  }
  if (elements.semiMajorSlider) {
    elements.semiMajorSlider.value = String(Number(hit.semiMajorKm));
  }

  if (elements.optSummary) {
    elements.optSummary.textContent = `Applied resonance ${hit.j}:${hit.k} with a â‰ˆ ${formatKm(hit.semiMajorKm, 3)} km.`;
  }

  // Recompute the orbit with the new parameters
  await recomputeOrbit(true);
}

function handleOptimizerResultClick(event) {
  const target = event.target;
  if (!(target instanceof HTMLElement)) return;
  if (!target.matches('button.apply-btn[data-index]')) return;
  const idx = Number(target.dataset.index);
  if (!Number.isInteger(idx) || idx < 0 || idx >= optimizerState.results.length) return;
  void applyResonanceCandidate(optimizerState.results[idx]);
}

function applyTheme(theme) {
  if (theme === 'dark') {
    document.body.dataset.theme = 'dark';
  } else {
    delete document.body.dataset.theme;
  }
  setSceneTheme?.(theme);
  updateChartTheme();
  if (elements.btnTheme) {
    const pressed = theme === 'dark';
    elements.btnTheme.setAttribute('aria-pressed', pressed ? 'true' : 'false');
    elements.btnTheme.textContent = pressed ? 'Light mode' : 'Dark mode';
  }
}

function updateViewMode(mode) {
  const target = mode || 'dual';
  elements.viewTabs?.forEach((tab) => {
    const active = tab.dataset.view === target;
    tab.classList.toggle('is-active', active);
    tab.classList.toggle('active', active);
    tab.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  if (elements.viewGrid) {
    elements.viewGrid.dataset.activeView = target;
  }
  
  // Handle fullscreen mode
  const vizContainer = document.querySelector('.visualization-container');
  if (vizContainer) {
    if (target === 'fullscreen') {
      vizContainer.setAttribute('data-fullscreen', 'true');
      // Hide sidebar and panel for fullscreen
      const sidebar = document.getElementById('sidebar');
      const panel = document.getElementById('controlPanel');
      if (sidebar) sidebar.style.display = 'none';
      if (panel) panel.style.display = 'none';
      
      // Actually enter fullscreen
      if (vizContainer.requestFullscreen) {
        vizContainer.requestFullscreen().catch(err => {
          console.warn('Could not enter fullscreen:', err);
        });
      } else if (vizContainer.webkitRequestFullscreen) {
        vizContainer.webkitRequestFullscreen();
      } else if (vizContainer.msRequestFullscreen) {
        vizContainer.msRequestFullscreen();
      }
    } else {
      vizContainer.setAttribute('data-fullscreen', 'false');
      // Show sidebar and panel
      const sidebar = document.getElementById('sidebar');
      const panel = document.getElementById('controlPanel');
      if (sidebar) sidebar.style.display = '';
      if (panel) panel.style.display = '';
      
      // Exit fullscreen if active
      if (document.fullscreenElement) {
        document.exitFullscreen();
      }
    }
  }
  
  setTimeout(() => invalidateMap(), 250);
}

function updateMapStyleButton(style) {
  if (!elements.btnMapStyle) return;
  if (style === 'satellite') {
    elements.btnMapStyle.textContent = 'Standard map';
  } else {
    elements.btnMapStyle.textContent = 'Satellite map';
  }
}

function initDefaults() {
  if (elements.epochInput) {
    const preset = isoNowLocal();
    elements.epochInput.value = preset;
    mutate((draft) => {
      draft.epoch = preset;
    });
  }
  if (elements.controlPanel) {
    const rect = elements.controlPanel.getBoundingClientRect();
    panelWidth = rect.width;
    lastExpandedPanelWidth = rect.width;
    applyPanelWidth(rect.width);
  }
  if (elements.semiMajor) {
    elements.semiMajor.min = MIN_SEMI_MAJOR.toFixed(3);
    elements.semiMajor.max = MAX_SEMI_MAJOR.toFixed(3);
    elements.semiMajor.step = 'any';
  }
  if (elements.semiMajorSlider) {
    elements.semiMajorSlider.min = MIN_SEMI_MAJOR.toFixed(3);
    elements.semiMajorSlider.max = MAX_SEMI_MAJOR.toFixed(3);
    elements.semiMajorSlider.step = '0.1';
  }
  const initialSemiMajor = clamp(state.orbital.semiMajor ?? MIN_SEMI_MAJOR, MIN_SEMI_MAJOR, MAX_SEMI_MAJOR);
  syncPairValue('semiMajor', 'semiMajorSlider', initialSemiMajor);
  if (elements.timeSlider) {
    elements.timeSlider.min = 0;
    elements.timeSlider.max = 1;
    elements.timeSlider.value = 0;
  }
  if (elements.timeWarp) {
    elements.timeWarp.value = String(state.time.timeWarp);
  }
  if (elements.optToleranceA && !elements.optToleranceA.value) {
    elements.optToleranceA.value = '0';
  }
  const initialTolerance = normalizeTolerance(elements.optToleranceA?.value);
  syncPairValue('optToleranceA', 'optToleranceSlider', initialTolerance);
  ensureOrderedIntRange('optMinRot', 'optMinRotSlider', 'optMaxRot', 'optMaxRotSlider', 1, 500);
  ensureOrderedIntRange('optMinOrb', 'optMinOrbSlider', 'optMaxOrb', 'optMaxOrbSlider', 1, 500);
  if (elements.groundCn2Day) {
    elements.groundCn2Day.value = String(state.optical.groundCn2Day ?? 5e-14);
  }
  if (elements.groundCn2Night) {
    elements.groundCn2Night.value = String(state.optical.groundCn2Night ?? 5e-15);
  }
  const savedTheme = localStorage.getItem('qkd-theme');
  if (savedTheme) {
    setTheme(savedTheme);
  }
  applyTheme(state.theme);
  updateViewMode(state.viewMode ?? 'dual');
  updateMapStyleButton(currentMapStyle);
  activatePanelSection('orbit');
  setPanelCollapsed(false);
  if (elements.panelReveal) {
    elements.panelReveal.hidden = true;
  }
  const initialWeatherField = state.weather?.variable ?? 'wind_speed';
  populateWeatherFieldOptions(initialWeatherField);
  const initialLevel = state.weather?.level_hpa ?? WEATHER_FIELDS[initialWeatherField].levels[0];
  populateWeatherLevelOptions(initialWeatherField, initialLevel);
  syncWeatherSamplesInputs(state.weather?.samples ?? 120);
  if (elements.weatherTime) {
    elements.weatherTime.value = (state.weather?.time ?? isoNowLocal()).slice(0, 16);
  }
  setWeatherStatus('');
  renderConstellationControls();
  renderOptimizerResults();
  if (elements.stationPickOnMap) {
    elements.stationPickOnMap.dataset.active = 'false';
    elements.stationPickOnMap.textContent = 'Pick on map';
  }
  updateStationPickHint();
  if (elements.atmosModelInputs?.length) {
    const selectedModel = state.atmosphere?.model ?? 'hufnagel-valley';
    elements.atmosModelInputs.forEach((input) => {
      const model = input.dataset.atmosModel || input.value;
      input.checked = model === selectedModel;
    });
  }
}

function bindEvents() {
  initSliders();
  createPanelAccordions();
  const parseSemiMajor = (value) => {
    const numeric = Number(value);
    if (!Number.isFinite(numeric)) {
      return clamp(state.orbital.semiMajor ?? MIN_SEMI_MAJOR, MIN_SEMI_MAJOR, MAX_SEMI_MAJOR);
    }
    const clamped = clamp(numeric, MIN_SEMI_MAJOR, MAX_SEMI_MAJOR);
    return Number(clamped.toFixed(3));
  };

  const sliderPairs = [
    ['semiMajor', 'semiMajorSlider', parseSemiMajor, 'orbital.semiMajor'],
    ['eccentricity', 'eccentricitySlider', (value) => clamp(Number(value), 0, 0.2), 'orbital.eccentricity'],
    ['inclination', 'inclinationSlider', (value) => clamp(Number(value), 0, 180), 'orbital.inclination'],
    ['raan', 'raanSlider', (value) => clamp(Number(value), 0, 360), 'orbital.raan'],
    ['argPerigee', 'argPerigeeSlider', (value) => clamp(Number(value), 0, 360), 'orbital.argPerigee'],
    ['meanAnomaly', 'meanAnomalySlider', (value) => clamp(Number(value), 0, 360), 'orbital.meanAnomaly'],
    ['satAperture', 'satApertureSlider', (value) => clamp(Number(value), 0.1, 3), 'optical.satAperture'],
    ['groundAperture', 'groundApertureSlider', (value) => clamp(Number(value), 0.1, 5), 'optical.groundAperture'],
    ['wavelength', 'wavelengthSlider', (value) => clamp(Number(value), 600, 1700), 'optical.wavelength'],
    ['samplesPerOrbit', 'samplesPerOrbitSlider', (value) => clamp(Number(value), 60, 720), 'samplesPerOrbit'],
  ];

  sliderPairs.forEach(([inputId, sliderId, normalize, path, spanId = null]) => {
    const inputEl = elements[inputId];
    const sliderEl = elements[sliderId];
    if (!inputEl || !sliderEl) return;
    const isOrbitalField = path.startsWith('orbital.');
    const updateStateFromValue = (value) => {
      const normalized = normalize(value);
      const numericValue = Number(normalized);
      syncPairValue(inputId, sliderId, numericValue, spanId);

      mutate((draft) => {
        const [section, field] = path.split('.');
        const valueToAssign = Number.isFinite(numericValue) ? numericValue : normalized;
        if (section === 'orbital') draft.orbital[field] = valueToAssign;
        else if (section === 'optical') draft.optical[field] = valueToAssign;
        else if (section === 'resonance') draft.resonance[field] = valueToAssign;
        else draft[field] = valueToAssign;
      });
    };
    inputEl.addEventListener('change', (event) => {
      if (isOrbitalField) {
        orbitSamplesOverride = null;
      }
      updateStateFromValue(event.target.value);
    });
    sliderEl.addEventListener('input', (event) => {
      if (isOrbitalField) {
        orbitSamplesOverride = DRAFT_SAMPLES_PER_ORBIT;
      }
      updateStateFromValue(event.target.value);
    });
    sliderEl.addEventListener('change', async (event) => {
      if (isOrbitalField) {
        orbitSamplesOverride = null;
      }
      updateStateFromValue(event.target.value);
      if (isOrbitalField) {
        await recomputeOrbit(true);
      }
    });
  });

  elements.j2Toggle?.addEventListener('change', async (event) => {
    mutate((draft) => {
      draft.orbital.j2Enabled = event.target.checked;
    });
    await recomputeOrbit(true);
  });

  const bindOpticalTurbulenceInput = (inputId, key) => {
    const inputEl = elements[inputId];
    if (!inputEl) return;
    const applyValue = (raw) => {
      const numeric = Number(raw);
      if (Number.isFinite(numeric) && numeric > 0) {
        inputEl.value = String(numeric);
        mutate((draft) => {
          draft.optical[key] = numeric;
        });
      } else {
        inputEl.value = String(state.optical[key]);
      }
    };
    inputEl.addEventListener('blur', (event) => applyValue(event.target.value));
    inputEl.addEventListener('change', async (event) => {
      applyValue(event.target.value);
      await recomputeMetricsOnly(true);
    });
  };

  bindOpticalTurbulenceInput('groundCn2Day', 'groundCn2Day');
  bindOpticalTurbulenceInput('groundCn2Night', 'groundCn2Night');

  const bindOptimizerPair = (inputId, sliderId, normalize, afterChange) => {
    const inputEl = elements[inputId];
    const sliderEl = elements[sliderId];
    if (!inputEl || !sliderEl) return;
    const apply = (raw) => {
      const normalized = normalize(raw);
      inputEl.value = String(normalized);
      sliderEl.value = String(normalized);
      afterChange?.();
    };
    inputEl.addEventListener('change', (event) => apply(event.target.value));
    sliderEl.addEventListener('input', (event) => apply(event.target.value));
  };

  bindOptimizerPair('optToleranceA', 'optToleranceSlider', normalizeTolerance);

  const syncRotBounds = () => ensureOrderedIntRange('optMinRot', 'optMinRotSlider', 'optMaxRot', 'optMaxRotSlider', 1, 500);
  const syncOrbBounds = () => ensureOrderedIntRange('optMinOrb', 'optMinOrbSlider', 'optMaxOrb', 'optMaxOrbSlider', 1, 500);

  bindOptimizerPair('optMinRot', 'optMinRotSlider', (value) => normalizeInt(value, 1, 500), syncRotBounds);
  bindOptimizerPair('optMaxRot', 'optMaxRotSlider', (value) => normalizeInt(value, 1, 500), syncRotBounds);
  bindOptimizerPair('optMinOrb', 'optMinOrbSlider', (value) => normalizeInt(value, 1, 500), syncOrbBounds);
  bindOptimizerPair('optMaxOrb', 'optMaxOrbSlider', (value) => normalizeInt(value, 1, 500), syncOrbBounds);

  syncRotBounds();
  syncOrbBounds();

  elements.panelTabs?.forEach((tab) => {
    tab.addEventListener('click', () => {
      activatePanelSection(tab.dataset.sectionTarget);
    });
  });

  // New sidebar navigation handling
  const sidebarNavItems = document.querySelectorAll('.sidebar .nav-item[data-section]');
  sidebarNavItems.forEach((item) => {
    item.addEventListener('click', () => {
      const section = item.dataset.section;
      const title = item.dataset.title; // Get the title from data-title
      if (section) {
        // Update active nav item
        sidebarNavItems.forEach(nav => nav.classList.remove('active'));
        item.classList.add('active');
        // Switch panel section
        activatePanelSection(section);
        // Update panel title
        if (elements.panelTitle && title) {
          elements.panelTitle.textContent = title;
        }
      }
    });
  });

  


  // Wire help nav buttons (show corresponding help article)
  try {
    const helpButtons = document.querySelectorAll('.help-nav [data-help-topic]');
    helpButtons.forEach((btn) => {
      btn.addEventListener('click', () => {
        const topic = btn.dataset.helpTopic;
        if (!topic) return;
        activatePanelSection('help');
        // ensure panel is visible when opening help
        setPanelCollapsed(false);
        const articles = document.querySelectorAll('.help-content article');
        articles.forEach((a) => { a.hidden = true; });
        const sel = document.getElementById(`help-${topic}`);
        if (sel) sel.hidden = false;
      });
    });
  } catch (e) { /* ignore if elements not present */ }

  elements.btnMenuToggle?.addEventListener('click', () => {
    document.getElementById('sidebar')?.classList.toggle('hidden');
  });

  elements.btnPanelToggle?.addEventListener('click', () => {
    setPanelCollapsed(true);
  });

  elements.panelResizer?.addEventListener('pointerdown', (event) => {
    if (!elements.controlPanel) return;
    if (elements.controlPanel.dataset.collapsed === 'true') {
      setPanelCollapsed(false);
      return;
    }
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = elements.controlPanel.getBoundingClientRect().width;
    const handleMove = (moveEvent) => {
      const width = startWidth + (moveEvent.clientX - startX);
      applyPanelWidth(width);
    };
    const handleUp = () => {
      document.removeEventListener('pointermove', handleMove);
      if (panelWidth < PANEL_COLLAPSE_THRESHOLD) {
        lastExpandedPanelWidth = Math.max(startWidth, PANEL_MIN_WIDTH);
        setPanelCollapsed(true);
      } else {
        lastExpandedPanelWidth = panelWidth;
      }
    };
    document.addEventListener('pointermove', handleMove);
    document.addEventListener('pointerup', handleUp, { once: true });
    document.addEventListener('pointercancel', handleUp, { once: true });
  });

  

  // Define control points (click-to-add on map) - stored in global state: state.optimizationPoints
  if (elements.btnDefinePoints) {
    // Toggle pick-mode: click map to add points, markers are draggable and removable
    let pointPickingActive = false;
    const optimizationMarkers = [];

    function renderPointsList() {
      if (!elements.pointsList) return;
      elements.pointsList.innerHTML = '';
      state.optimizationPoints.forEach((pt, idx) => {
        const row = document.createElement('div');
        row.style.display = 'flex';
        row.style.justifyContent = 'space-between';
        row.style.alignItems = 'center';
        row.style.padding = '2px 4px';
        const label = document.createElement('div');
        label.textContent = `${pt.lat.toFixed(4)}, ${pt.lon.toFixed(4)}`;
        const actions = document.createElement('div');
        const btnCenter = document.createElement('button');
        btnCenter.textContent = 'â†’';
        btnCenter.title = 'Centrar mapa';
        btnCenter.style.marginRight = '6px';
        btnCenter.addEventListener('click', () => {
          if (map) map.setView([pt.lat, pt.lon], Math.max(map.getZoom(), 4));
        });
        const btnRemove = document.createElement('button');
        btnRemove.textContent = 'âœ–';
        btnRemove.title = 'Eliminar punto';
        btnRemove.addEventListener('click', () => {
          // remove marker on map and from state
          const m = optimizationMarkers[idx];
          try { if (m && map) map.removeLayer(m); } catch (e) {}
          optimizationMarkers.splice(idx, 1);
          mutate((draft) => { draft.optimizationPoints.splice(idx, 1); });
          renderPointsList();
          if (elements.pointsCount) elements.pointsCount.textContent = `${state.optimizationPoints.length} puntos`;
        });
        actions.appendChild(btnCenter);
        actions.appendChild(btnRemove);
        row.appendChild(label);
        row.appendChild(actions);
        elements.pointsList.appendChild(row);
      });
      if (elements.pointsCount) elements.pointsCount.textContent = `${state.optimizationPoints.length} puntos`;
    }

    // expose helper functions so initialize() can restore markers after map init
    elements.addOptimizationMarker = addOptimizationMarker;
    elements.renderPointsList = renderPointsList;

    function addOptimizationMarker(lat, lon) {
      if (!map) return;
      const marker = L.marker([lat, lon], { draggable: true }).addTo(map);
      const idx = optimizationMarkers.length;
      marker.bindPopup(`<div style="font-size:0.9em">${lat.toFixed(4)}, ${lon.toFixed(4)}<br/><button data-action="remove">Eliminar</button></div>`);
      marker.on('popupopen', (e) => {
        const btn = e.popup._contentNode.querySelector('[data-action="remove"]');
        if (btn) btn.addEventListener('click', () => {
          marker.remove();
          const i = optimizationMarkers.indexOf(marker);
            if (i >= 0) {
            optimizationMarkers.splice(i, 1);
            mutate((draft) => { draft.optimizationPoints.splice(i, 1); });
            renderPointsList();
          }
        });
      });
      marker.on('dragend', () => {
        const pos = marker.getLatLng();
        const i = optimizationMarkers.indexOf(marker);
        if (i >= 0) {
          mutate((draft) => { draft.optimizationPoints[i] = { lat: pos.lat, lon: pos.lng }; });
          renderPointsList();
        }
      });
      optimizationMarkers.push(marker);
    }

    elements.btnDefinePoints.addEventListener('click', () => {
      pointPickingActive = !pointPickingActive;
      elements.btnDefinePoints.textContent = pointPickingActive ? 'Picking: Haz click en el mapa' : 'Definir puntos de control';
      // Toggle visual state
      if (pointPickingActive) elements.btnDefinePoints.classList.add('btn-picking'); else elements.btnDefinePoints.classList.remove('btn-picking');
      if (pointPickingActive) {
        // temporary hint
        if (map && map._container) map._container.style.cursor = 'crosshair';
      } else if (map && map._container) {
        map._container.style.cursor = '';
      }
    });

    // map click handler - add point when pick mode active
    if (typeof map !== 'undefined' && map) {
      map.on('click', (ev) => {
        if (!pointPickingActive) return;
        const { lat, lng } = ev.latlng;
        mutate((draft) => { draft.optimizationPoints.push({ lat, lon: lng }); });
        addOptimizationMarker(lat, lng);
        renderPointsList();
      });
    }
    // initial render if any
    renderPointsList();
  }

  // Optimize design
  if (elements.btnOptimize) {
    elements.btnOptimize.addEventListener('click', async () => {
      try {
        if (!Array.isArray(state.time.timeline) || !state.time.timeline.length) {
          await recomputeOrbit(true);
        }
        const timelineSeconds = state.time.timeline.slice();
        const simDuration = Number(elements.simDuration?.value) || timelineSeconds[timelineSeconds.length - 1] || 3600;

        const walker = walkerGenerator;
        const engine = optimizationEngine;
        const settings = state;

        // Build initial constellation
        let initialConstellation = [];
        if (state.mode === 'constellation') {
          const T = Number(elements.walkerT?.value) || 24;
          const P = Number(elements.walkerP?.value) || 6;
          const F = Number(elements.walkerF?.value) || 1;
          const a = Number(state.orbital.semiMajor) || 6771;
          const i = Number(state.orbital.inclination) || 53;
          initialConstellation = walker.generateWalkerConstellation(T, P, F, a, i, Number(state.orbital.eccentricity) || 0);
        } else {
          // single satellite uses the current orbital element as a single-entry constellation
          initialConstellation = [{
            semiMajor: state.orbital.semiMajor,
            eccentricity: state.orbital.eccentricity,
            inclination: state.orbital.inclination,
            raan: state.orbital.raan,
            argPerigee: state.orbital.argPerigee,
            meanAnomaly: state.orbital.meanAnomaly,
          }];
        }

        // factory to compute positions for a candidate constellation
        const constellationPositionsFactory = (constellation) => {
          const result = { design: { satellites: [] } };
          for (let s = 0; s < constellation.length; s += 1) {
            const sat = constellation[s];
            // build settings to propagate this satellite
            const satSettings = {
              orbital: {
                semiMajor: sat.semiMajor,
                eccentricity: sat.eccentricity,
                inclination: sat.inclination,
                raan: sat.raan,
                argPerigee: sat.argPerigee,
                meanAnomaly: sat.meanAnomaly,
              },
              resonance: { enabled: false },
              samplesPerOrbit: state.samplesPerOrbit,
              time: { timeline: timelineSeconds },
              epoch: state.epoch,
            };
            const orbitRes = orbit.propagateOrbit(satSettings);
            const timeline = orbitRes.dataPoints || [];
            const satTimeline = timeline.map((pt) => ({ lat: pt.lat, lon: pt.lon, alt: pt.alt }));
            result.design.satellites.push({ id: `s-${s}`, name: `sat-${s}`, timeline: satTimeline });
          }
          return result;
        };

        // non-blocking optimizer with progress and optional worker
        if (elements.optStatus) elements.optStatus.textContent = 'Optimizandoâ€¦';
        if (elements.optProgress) { elements.optProgress.max = 1; elements.optProgress.value = 0; }
        if (elements.btnCancelOptimize) { elements.btnCancelOptimize.style.display = 'inline-block'; }
        let cancelRequested = false;
        if (elements.btnCancelOptimize) elements.btnCancelOptimize.onclick = () => { cancelRequested = true; elements.optStatus.textContent = 'Cancelandoâ€¦'; };

        const useWorker = elements.workerToggle?.checked === true;
        // helper to compute positions for a candidate constellation. If worker enabled, use worker; otherwise compute on main thread
        async function positionsFactoryAsync(constellation) {
          if (useWorker && window.Worker) {
            // create worker and propagate satellites serially
            return new Promise((resolve, reject) => {
                const workerCount = Math.max(1, Number(elements.workerCount?.value) || 1);
                const results = { design: { satellites: [] } };
                let completed = 0;
                // create layer for partial results
                let partialLayer = null;
                if (map) {
                  try { partialLayer = L.layerGroup().addTo(map); } catch (e) { partialLayer = null; }
                }
                if (workerCount <= 1) {
                  const worker = new Worker('/static/propagateWorker.js');
                  worker.onmessage = (ev) => {
                    const msg = ev.data || {};
                    if (msg.type === 'progress') {
                      if (elements.optProgress && msg.total) elements.optProgress.value = msg.done / msg.total;
                      if (elements.optStatus) elements.optStatus.textContent = `Propagando sat ${msg.done}/${msg.total}`;
                      return;
                    }
                    if (msg.type === 'result') {
                      results.design.satellites.push({ id: msg.id, name: msg.name, timeline: msg.timeline });
                      completed += 1;
                      if (elements.optProgress && msg.total) elements.optProgress.value = completed / msg.total;
                      // render partial result on map
                      try {
                        if (partialLayer && Array.isArray(msg.timeline) && msg.timeline.length) {
                          const latlngs = msg.timeline.map((p) => [p.lat, p.lon]);
                          const poly = L.polyline(latlngs, { color: '#7c3aed', weight: 1, opacity: 0.7 }).addTo(partialLayer);
                          L.circleMarker(latlngs[0], { radius: 2, color: '#fff', fillColor: '#7c3aed', fillOpacity: 1 }).addTo(partialLayer);
                        }
                      } catch (e) { /* ignore rendering errors */ }
                      if (completed >= (msg.total || constellation.length)) {
                        worker.terminate();
                        resolve(results);
                      }
                    }
                    if (msg.type === 'error') {
                      worker.terminate();
                      if (partialLayer) partialLayer.clearLayers();
                      reject(new Error(msg.message || 'Worker error'));
                    }
                  };
                  worker.onerror = (err) => { worker.terminate(); if (partialLayer) partialLayer.clearLayers(); reject(err); };
                  worker.postMessage({ type: 'propagateBatch', payload: { constellation, timeline: timelineSeconds, epoch: state.epoch, j2Enabled: state.orbital.j2Enabled } });
                } else {
                  // split constellation into roughly equal chunks and spawn multiple workers
                  const n = Math.min(workerCount, constellation.length);
                  const chunkSize = Math.ceil(constellation.length / n);
                  const workers = [];
                  let pending = 0;
                  for (let w = 0; w < n; w += 1) {
                    const start = w * chunkSize;
                    const end = Math.min(start + chunkSize, constellation.length);
                    if (start >= end) continue;
                    const subset = constellation.slice(start, end);
                    pending += subset.length;
                    const wk = new Worker('/static/propagateWorker.js');
                    workers.push(wk);
                    wk.onmessage = (ev) => {
                      const msg = ev.data || {};
                      if (msg.type === 'progress') {
                        // aggregate progress crudely
                        if (elements.optStatus) elements.optStatus.textContent = `Propagando sat ${msg.done}/${msg.total}`;
                        return;
                      }
                      if (msg.type === 'result') {
                        results.design.satellites.push({ id: msg.id, name: msg.name, timeline: msg.timeline });
                        completed += 1;
                        if (elements.optProgress && constellation.length) elements.optProgress.value = completed / constellation.length;
                        // render partial
                        try {
                          if (partialLayer && Array.isArray(msg.timeline) && msg.timeline.length) {
                            const latlngs = msg.timeline.map((p) => [p.lat, p.lon]);
                            const poly = L.polyline(latlngs, { color: '#7c3aed', weight: 1, opacity: 0.65 }).addTo(partialLayer);
                          }
                        } catch (e) {}
                        if (completed >= constellation.length) {
                          // terminate all workers
                          workers.forEach((x) => { try { x.terminate(); } catch (e) {} });
                          resolve(results);
                        }
                      }
                      if (msg.type === 'error') {
                        workers.forEach((x) => { try { x.terminate(); } catch (e) {} });
                        if (partialLayer) partialLayer.clearLayers();
                        reject(new Error(msg.message || 'Worker error'));
                      }
                    };
                    wk.onerror = (err) => { workers.forEach((x) => { try { x.terminate(); } catch (e) {} }); if (partialLayer) partialLayer.clearLayers(); reject(err); };
                    wk.postMessage({ type: 'propagateBatch', payload: { constellation: subset, timeline: timelineSeconds, epoch: state.epoch, j2Enabled: state.orbital.j2Enabled } });
                  }
                }
            });
          }
          // fallback: synchronous factory
          return new Promise((resolve) => {
            const result = { design: { satellites: [] } };
            for (let s = 0; s < constellation.length; s += 1) {
              if (cancelRequested) break;
              const sat = constellation[s];
              const satSettings = {
                orbital: {
                  semiMajor: sat.semiMajor,
                  eccentricity: sat.eccentricity,
                  inclination: sat.inclination,
                  raan: sat.raan,
                  argPerigee: sat.argPerigee,
                  meanAnomaly: sat.meanAnomaly,
                  j2Enabled: state.orbital.j2Enabled,
                },
                resonance: { enabled: false },
                samplesPerOrbit: state.samplesPerOrbit,
                time: { timeline: timelineSeconds },
                epoch: state.epoch,
              };
              const orbitRes = orbit.propagateOrbit(satSettings);
              const tl = (orbitRes.dataPoints || []).map((pt) => ({ lat: pt.lat, lon: pt.lon, alt: pt.alt }));
              result.design.satellites.push({ id: `s-${s}`, name: `sat-${s}`, timeline: tl });
              if (elements.optProgress) elements.optProgress.value = (s + 1) / constellation.length;
            }
            resolve(result);
          });
        }

        // batched iterative optimizer on main thread, yielding to UI every few iterations
        const iterations = 80;
        const batchSize = 5;
        let best = initialConstellation.map((s) => ({ ...s }));
        let bestPositions = await positionsFactoryAsync(best);
        let bestScoreObj = engine.computeRevisitTime(bestPositions, state.optimizationPoints.length ? state.optimizationPoints : [{ lat: 0, lon: 0 }], timelineSeconds);
        let bestScore = bestScoreObj.max;

        for (let it = 0; it < iterations; it += 1) {
          if (cancelRequested) break;
          // mutate copy
          const candidate = optimizationEngine.mutateConstellation(best, Math.max(0.1, 5 * (1 - it / iterations)));
          const candidatePositions = await positionsFactoryAsync(candidate);
          const scoreObj = engine.computeRevisitTime(candidatePositions, state.optimizationPoints.length ? state.optimizationPoints : [{ lat: 0, lon: 0 }], timelineSeconds);
          const score = scoreObj.max;
          if (Number.isFinite(score) && score < bestScore) {
            best = candidate;
            bestPositions = candidatePositions;
            bestScoreObj = scoreObj;
            bestScore = score;
          }
          if (elements.optProgress) elements.optProgress.value = (it + 1) / iterations;
          if (elements.optStatus) elements.optStatus.textContent = `Iter ${it + 1}/${iterations} â€” best ${Math.round(bestScore)} s`;
          // yield occasionally
          if ((it % batchSize) === 0) await new Promise((r) => setTimeout(r, 10));
        }

        if (elements.btnCancelOptimize) elements.btnCancelOptimize.style.display = 'none';
        if (cancelRequested) {
          if (elements.optStatus) elements.optStatus.textContent = 'OptimizaciÃ³n cancelada';
          if (elements.optProgress) elements.optProgress.value = 0;
          return;
        }

        // apply best constellation by visualizing its first satellite orbit and placing markers for each sat
        if (Array.isArray(best) && best.length) {
          const primary = best[0];
          mutate((draft) => {
            draft.orbital.semiMajor = primary.semiMajor;
            draft.orbital.eccentricity = primary.eccentricity;
            draft.orbital.inclination = primary.inclination;
            draft.orbital.raan = primary.raan;
            draft.orbital.argPerigee = primary.argPerigee;
            draft.orbital.meanAnomaly = primary.meanAnomaly;
          });
          await recomputeOrbit(true);
        }
        if (elements.optStatus) elements.optStatus.textContent = `Done â€” max revisit ${Number.isFinite(bestScoreObj.max) ? Math.round(bestScoreObj.max) : 'âˆž'} s, mean ${Number.isFinite(bestScoreObj.mean) ? Math.round(bestScoreObj.mean) : 'âˆž'} s`;
      } catch (err) {
        console.error('Optimization failed', err);
        if (elements.optStatus) elements.optStatus.textContent = 'Error during optimization';
      }
    });
  }

  elements.panelResizer?.addEventListener('dblclick', () => {
    const collapsed = elements.controlPanel?.dataset.collapsed === 'true';
    setPanelCollapsed(!collapsed);
  });

  elements.panelResizer?.addEventListener('keydown', (event) => {
    if (!elements.controlPanel) return;
    const collapsed = elements.controlPanel.dataset.collapsed === 'true';
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      setPanelCollapsed(!collapsed);
      return;
    }
    if (collapsed) return;
    if (event.key === 'ArrowLeft') {
      event.preventDefault();
      applyPanelWidth(panelWidth - 20);
      lastExpandedPanelWidth = panelWidth;
    } else if (event.key === 'ArrowRight') {
      event.preventDefault();
      applyPanelWidth(panelWidth + 20);
      lastExpandedPanelWidth = panelWidth;
    }
  });

  elements.btnMapStyle?.addEventListener('click', () => {
    const next = toggleBaseLayer();
    currentMapStyle = next || (currentMapStyle === 'standard' ? 'satellite' : 'standard');
    updateMapStyleButton(currentMapStyle);
  });

  elements.satelliteName?.addEventListener('input', (event) => {
    mutate((draft) => {
      draft.satelliteName = event.target.value;
    });
  });

  elements.epochInput?.addEventListener('change', (event) => {
    mutate((draft) => {
      draft.epoch = event.target.value;
    });
  });

  elements.optimizerForm?.addEventListener('submit', (event) => {
    event.preventDefault();
    runResonanceSearch();
  });

  elements.optResults?.addEventListener('click', handleOptimizerResultClick);

  if (elements.weatherFieldSelect) {
    elements.weatherFieldSelect.addEventListener('change', (event) => {
      const key = event.target.value;
  const normalized = Object.prototype.hasOwnProperty.call(WEATHER_FIELDS, key) ? key : 'wind_speed';
      const candidateLevel = state.weather?.level_hpa ?? WEATHER_FIELDS[normalized].levels[0];
      const nextLevel = WEATHER_FIELDS[normalized].levels.includes(candidateLevel)
        ? candidateLevel
        : WEATHER_FIELDS[normalized].levels[0];
      populateWeatherLevelOptions(normalized, nextLevel);
      mutate((draft) => {
        draft.weather.variable = normalized;
        draft.weather.level_hpa = nextLevel;
      });
    });
  }

  if (elements.weatherLevelSelect) {
    elements.weatherLevelSelect.addEventListener('change', (event) => {
      const level = Number(event.target.value);
      mutate((draft) => {
        draft.weather.level_hpa = level;
      });
    });
  }

  const applyWeatherSamples = (raw) => {
    const sanitized = syncWeatherSamplesInputs(raw);
    mutate((draft) => {
      draft.weather.samples = sanitized;
    });
  };

  elements.weatherSamples?.addEventListener('change', (event) => applyWeatherSamples(event.target.value));
  elements.weatherSamplesSlider?.addEventListener('input', (event) => applyWeatherSamples(event.target.value));
  elements.weatherSamplesSlider?.addEventListener('change', (event) => applyWeatherSamples(event.target.value));

  elements.weatherTime?.addEventListener('change', (event) => {
    const value = event.target.value || isoNowLocal();
    const truncated = value.slice(0, 16);
    mutate((draft) => {
      draft.weather.time = truncated;
    });
  });

  elements.weatherFetchBtn?.addEventListener('click', () => {
    void fetchWeatherFieldData();
  });

  elements.weatherClearBtn?.addEventListener('click', () => {
    mutate((draft) => {
      draft.weather.data = null;
      draft.weather.active = false;
      draft.weather.status = 'idle';
    });
    clearWeatherField();
    lastWeatherSignature = '';
    setWeatherStatus('Overlay cleared');
  });

  // QKD Calculate button handler
  elements.btnCalculateQKD?.addEventListener('click', () => {
    logCheckpoint('QKD Calculate button clicked');
    try {
      const { logInfo, validateNumber } = require('utils');
      
      // Get current link loss from computed metrics
      const currentLoss = state.computed?.linkLoss || 0;
      
      // Get QKD parameters from UI
      const protocol = elements.qkdProtocol?.value || 'bb84';
      const photonRate = validateNumber(elements.photonRate?.value, 1, 1000, 'photonRate') * 1e6 || 100e6; // Convert MHz to Hz
      const detectorEfficiency = validateNumber(elements.detectorEfficiency?.value, 0, 1, 'detectorEfficiency') || 0.65;
      const darkCountRate = validateNumber(elements.darkCountRate?.value, 0, 10000, 'darkCountRate') || 100;
      
      if (!photonRate || !detectorEfficiency || darkCountRate === null) {
        const statusEl = document.getElementById('qkdStatus');
        if (statusEl) statusEl.textContent = 'Error: Invalid input parameters';
        logError('QKD calculation', new Error('Invalid parameters'));
        return;
      }
      
      logInfo('QKD parameters collected', { protocol, photonRate, detectorEfficiency, darkCountRate, currentLoss });
      
      // Calculate QKD performance
      const results = calculateQKDPerformance(protocol, {
        photonRate: photonRate,
        channelLossdB: currentLoss,
        detectorEfficiency: detectorEfficiency,
        darkCountRate: darkCountRate
      });
      
      logCheckpoint('QKD results calculated', results);
      
      // Update UI with results
      const qberEl = document.getElementById('qberMetric');
      const rawKeyRateEl = document.getElementById('rawKeyRateMetric');
      const secureKeyRateEl = document.getElementById('secureKeyRateMetric');
      const channelTransEl = document.getElementById('channelTransmittanceMetric');
      
      if (results.error) {
        const statusEl = document.getElementById('qkdStatus');
        if (statusEl) statusEl.textContent = `Error: ${results.error}`;
        if (qberEl) qberEl.textContent = '--';
        if (rawKeyRateEl) rawKeyRateEl.textContent = '--';
        if (secureKeyRateEl) secureKeyRateEl.textContent = '--';
        if (channelTransEl) channelTransEl.textContent = '--';
        return;
      }
      
      // Format and display results
      if (qberEl) qberEl.textContent = results.qber !== null ? results.qber.toFixed(2) + '%' : '--';
      if (rawKeyRateEl) rawKeyRateEl.textContent = results.rawKeyRate !== null ? results.rawKeyRate.toFixed(2) + ' kbps' : '--';
      if (secureKeyRateEl) {
        const rateText = results.secureKeyRate !== null ? results.secureKeyRate.toFixed(2) : '--';
        secureKeyRateEl.textContent = rateText + ' kbps';
        // Color code based on performance
        if (results.secureKeyRate > 0) {
          secureKeyRateEl.style.color = 'var(--accent-tertiary)';
        } else {
          secureKeyRateEl.style.color = 'var(--text-muted)';
        }
      }
      if (channelTransEl) {
        const transText = results.channelTransmittance !== null ? 
          (results.channelTransmittance * 100).toFixed(4) + '%' : '--';
        channelTransEl.textContent = transText;
      }
      
      // Update status
      const statusEl = document.getElementById('qkdStatus');
      if (statusEl) {
        if (results.secureKeyRate > 0) {
          statusEl.textContent = `âœ“ QKD link established with ${results.protocol} protocol`;
          statusEl.style.color = 'var(--accent-tertiary)';
        } else {
          statusEl.textContent = `âœ— QBER too high for secure key generation (${results.qber.toFixed(2)}%)`;
          statusEl.style.color = 'var(--text-muted)';
        }
      }
      
      logInfo('QKD UI updated successfully', results);
    } catch (error) {
      logError('QKD calculation failed', error);
      const statusEl = document.getElementById('qkdStatus');
      if (statusEl) statusEl.textContent = 'Calculation error - check console for details';
    }
  });

  elements.constellationList?.addEventListener('change', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLInputElement)) return;
    if (target.type !== 'checkbox' || !target.dataset.constellation) return;
    const groupId = target.dataset.constellation;
    const enabled = target.checked;
    void handleConstellationToggle(groupId, enabled);
  });

  elements.btnPlay?.addEventListener('click', () => {
    playbackLoop.lastTimestamp = null;
    togglePlay(true);
  });
  elements.btnPause?.addEventListener('click', () => togglePlay(false));
  elements.btnResetTime?.addEventListener('click', () => setTimeIndex(0));
  elements.btnStepBack?.addEventListener('click', () => setTimeIndex(Math.max(0, state.time.index - 1)));
  elements.btnStepForward?.addEventListener('click', () => setTimeIndex(Math.min(state.time.timeline.length - 1, state.time.index + 1)));

  elements.timeSlider?.addEventListener('input', (event) => setTimeIndex(Number(event.target.value)));
  elements.timeWarp?.addEventListener('change', (event) => setTimeWarp(Number(event.target.value)));

  // ── Heliocentric mode controls ──────────────────────────────────────
  elements.sceneModeSelect?.addEventListener('change', (e) => {
    const mode = e.target.value;  // 'orbit' | 'helio'
    setSceneMode(mode);
  });
  elements.helioInterval?.addEventListener('change', (e) => {
    setHelioInterval(Number(e.target.value));
    updateHelioSampleHint();
    recomputeHelioTimeline();
  });
  elements.helioStep?.addEventListener('change', (e) => {
    setHelioStep(Number(e.target.value));
    updateHelioSampleHint();
    recomputeHelioTimeline();
  });

  elements.viewTabs?.forEach((tab) => {
    tab.addEventListener('click', () => {
      const mode = tab.dataset.view;
      mutate((draft) => {
        draft.viewMode = mode;
      });
      updateViewMode(mode);
    });
  });

  elements.btnTheme?.addEventListener('click', () => {
    const next = state.theme === 'dark' ? 'light' : 'dark';
    setTheme(next);
    applyTheme(next);
    localStorage.setItem('qkd-theme', next);
  });

  elements.atmosModelInputs?.forEach((input) => {
    input.addEventListener('change', async () => {
      if (!input.checked) return;
      const model = input.dataset.atmosModel || input.value;
      mutate((draft) => {
        draft.atmosphere = draft.atmosphere || { model: 'hufnagel-valley', modelParams: {} };
        draft.atmosphere.model = model;
      });
      await recomputeMetricsOnly(true);
    });
  });

  elements.btnPlotConstellation?.addEventListener('click', () => {
    void plotWalkerConstellation();
  });

  elements.btnClearOrbit?.addEventListener('click', () => {
    clearSingleOrbit();
  });

  elements.btnClearConstellation?.addEventListener('click', () => {
    clearTleConstellations();
    clearCustomConstellation();
  });

  elements.controlPanel?.addEventListener('click', (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    if (target.matches('.btn-show-graph')) {
      event.preventDefault();
      showModalGraph(target.dataset.graphId);
    }
  });

  // Robust panel-toggle wiring: ensure the toggle works even if parts of
  // the UI overlay it or if child elements swallow the events. Attach
  // capture-phase handlers, keyboard support, and a document-level
  // fallback.
  // Robust toggle helper: try the app's setPanelCollapsed if available,
  // otherwise directly mutate DOM attributes so the UI responds.
  function robustTogglePanel(forceValue) {
    try {
      if (typeof setPanelCollapsed === 'function') {
        // prefer the app's implementation
        // compute desired next state (respect forceValue when provided)
        try {
          const panelEl = elements.controlPanel || document.getElementById('controlPanel');
          const currently = panelEl?.dataset?.collapsed === 'true';
          const next = typeof forceValue === 'boolean' ? Boolean(forceValue) : !currently;
          return setPanelCollapsed(Boolean(next));
        } catch (callErr) {
          // if any error when reading DOM, fall back to calling without args
          return setPanelCollapsed();
        }
      }
    } catch (err) {
      // fall through to manual DOM toggle
      console.debug('setPanelCollapsed call failed, falling back to DOM toggle', err);
    }

    try {
      const panel = elements.controlPanel || document.getElementById('controlPanel');
      const workspace = document.querySelector('.workspace') || document.body;
      if (!panel) return;
      const currently = panel.dataset?.collapsed === 'true';
      const next = typeof forceValue === 'boolean' ? forceValue : !currently;
      console.log('robustTogglePanel: before', { currently, forceValue });
      // update dataset / aria
      panel.dataset.collapsed = next ? 'true' : 'false';
      panel.setAttribute('aria-expanded', next ? 'false' : 'true');
      // ensure workspace class mirrors state
      if (next) workspace.classList.add('panel-collapsed'); else workspace.classList.remove('panel-collapsed');
      // DIRECT STYLE fallback: hide the panel element if collapsed to guarantee effect
      try {
        panel.style.display = next ? 'none' : '';
      } catch (e) { console.warn('Could not set panel.style.display', e); }
      // quick visual flash to help debugging
      try {
        panel.style.outline = '3px solid rgba(124,58,237,0.9)';
        setTimeout(() => { panel.style.outline = ''; }, 450);
      } catch (e) {}
      console.log('robustTogglePanel: after', { next, collapsed: panel.dataset?.collapsed });
      // show/hide panel reveal affordance if present
      const reveal = elements.panelReveal || document.getElementById('panelReveal');
      if (reveal) reveal.hidden = !next;
      // if a map exists, invalidate size to avoid layout glitches
      try { if (typeof invalidateMap === 'function') invalidateMap(); } catch (e) {}
    } catch (err) {
      console.warn('robustTogglePanel failed', err);
    }
  }

  // expose for manual debugging in the console
  try { window.robustTogglePanel = robustTogglePanel; } catch (e) {}

  if (elements.btnPanelToggle) {
    try {
      elements.btnPanelToggle.style.pointerEvents = elements.btnPanelToggle.style.pointerEvents || 'auto';

      elements.btnPanelToggle.addEventListener('click', (evt) => {
        evt.preventDefault();
        evt.stopPropagation();
        robustTogglePanel();
      }, { capture: true });

      elements.btnPanelToggle.addEventListener('keydown', (evt) => {
        if (evt.key === 'Enter' || evt.key === ' ') {
          evt.preventDefault();
          evt.stopPropagation();
          elements.btnPanelToggle.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
        }
      }, { capture: true });

      elements.btnPanelToggle.addEventListener('pointerdown', (evt) => {
        evt.stopPropagation();
      }, { capture: true });
    } catch (err) {
      console.warn('panel toggle listener setup failed', err);
    }
  }

  // Document-level capture fallback to ensure clicks are handled even
  // if something intercepts the event earlier in the tree.
  document.addEventListener('click', (evt) => {
    try {
      const btn = evt.target && evt.target.closest && evt.target.closest('#btnPanelToggle');
      if (btn) {
        evt.preventDefault();
        evt.stopPropagation();
        robustTogglePanel();
      }
    } catch (err) {
      // swallow errors
    }
  }, { capture: true });

  elements.closeGraphModal?.addEventListener('click', () => {
    elements.graphModal?.close();
  });

  if (elements.stationDialog) {
    const dragHandle = elements.stationDialog.querySelector('.dialog-drag-handle');
    dragHandle?.addEventListener('pointerdown', (event) => {
      if (event.button !== 0) return;
      beginStationDialogDrag(event);
    });
    elements.stationDialog.addEventListener('submit', async (event) => {
      event.preventDefault();
      await saveStationFromDialog();
    });
  }

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && elements.stationDialog?.open) {
      event.preventDefault();
      elements.stationDialog.close('cancelled');
    }
  });

  elements.btnAddStation?.addEventListener('click', () => {
    setStationPickMode(false);
    updateStationPickHint();
    openStationDialog();
  });

  elements.btnDeleteStation?.addEventListener('click', async () => {
    const station = getSelectedStation();
    if (!station) return;
    const confirmed = window.confirm(`Remove the station "${station.name}"?`);
    if (!confirmed) return;
    await deleteStationRemote(station.id);
  });

  if (elements.stationDialog && elements.stationSave) {
    elements.stationDialog.addEventListener('close', () => {
      setStationPickMode(false);
      if (elements.stationName) elements.stationName.value = '';
      if (elements.stationLat) elements.stationLat.value = '';
      if (elements.stationLon) elements.stationLon.value = '';
      resetStationDialogPosition();
      updateStationPickHint();
      endStationDialogDrag();
    });

    elements.stationCancel?.addEventListener('click', () => {
      elements.stationDialog.close('cancelled');
    });

    elements.stationPickOnMap?.addEventListener('click', () => {
      const isActive = elements.stationPickOnMap.dataset.active === 'true';
      setStationPickMode(!isActive);
    });

    elements.stationLat?.addEventListener('input', syncStationPickHintFromInputs);
    elements.stationLon?.addEventListener('input', syncStationPickHintFromInputs);

    elements.stationSave.addEventListener('click', async (event) => {
      event.preventDefault();
      await saveStationFromDialog();
    });
  }

  elements.stationSelect?.addEventListener('change', async (event) => {
    selectStation(event.target.value || null);
    await recomputeMetricsOnly(true);
  });

  elements.btnFocusStation?.addEventListener('click', () => {
    const station = getSelectedStation();
    focusOnStation(station);
  });
}

function getSelectedStation() {
  const { list, selectedId } = state.stations;
  return list.find((item) => item.id === selectedId) ?? null;
}

function refreshStationSelect() {
  if (!elements.stationSelect) return;
  const { list, selectedId } = state.stations;
  elements.stationSelect.innerHTML = '';
  list.forEach((station) => {
    const option = document.createElement('option');
    option.value = station.id;
    option.textContent = station.name;
    option.selected = station.id === selectedId;
    elements.stationSelect.appendChild(option);
  });
  if (selectedId) {
    elements.stationSelect.value = selectedId;
  }
  const hasStations = list.length > 0;
  const hasSelection = hasStations && Boolean(selectedId);
  elements.stationSelect.disabled = !hasStations;
  if (elements.btnDeleteStation) {
    elements.btnDeleteStation.disabled = !hasSelection;
  }
  if (elements.btnFocusStation) {
    elements.btnFocusStation.disabled = !hasSelection;
  }
}

function orbitSignature(snapshot) {
  return JSON.stringify({
    orbital: snapshot.orbital,
    resonance: snapshot.resonance,
    samplesPerOrbit: snapshot.samplesPerOrbit,
  });
}

function metricsSignature(snapshot) {
  return JSON.stringify({
    optical: snapshot.optical,
    station: snapshot.stations.selectedId,
    stations: snapshot.stations.list.map((s) => s.id),
    atmosphere: snapshot.atmosphere?.model ?? 'hufnagel-valley',
  });
}

async function loadConstellationGroup(groupId) {
  const config = getConstellationConfig(groupId);
  if (!config) {
    throw new Error(`Unknown constellation group: ${groupId}`);
  }
  if (!window.satellite) {
    throw new Error('satellite.js is required to enable constellation overlays.');
  }

  const registryEntry = state.constellations?.registry?.[groupId];
  const existing = constellationStore.get(groupId);
  if (existing && registryEntry?.hasData && Array.isArray(existing.entries) && existing.entries.length) {
    return existing;
  }

  setConstellationLoading(groupId, true);
  setConstellationStatusMessage(`Loading ${config.label}â€¦`, 'loading');

  try {
    const response = await fetch(`/api/tles/${encodeURIComponent(groupId)}`);
    if (!response.ok) {
      let detail = response.statusText || `HTTP ${response.status}`;
      try {
        const errorPayload = await response.json();
        if (errorPayload?.detail) {
          detail = errorPayload.detail;
        }
      } catch (error) {
        /* ignore parse errors */
      }
      throw new Error(detail);
    }

    const payload = await response.json();
    const satLib = window.satellite;
    const entries = [];
    const seen = new Set();
    if (Array.isArray(payload?.tles)) {
      payload.tles.forEach((tle, idx) => {
        try {
          const satrec = satLib.twoline2satrec(tle.line1, tle.line2);
          if (!satrec) return;
          const satId = String(tle.norad_id ?? satrec.satnum ?? `${groupId}-${idx}`);
          if (seen.has(satId)) return;
          seen.add(satId);
          entries.push({
            id: satId,
            name: tle.name || satId,
            satrec,
            line1: tle.line1,
            line2: tle.line2,
          });
        } catch (error) {
          console.warn('Skipped invalid TLE record', error);
        }
      });
    }

    const fetchedAt = payload?.fetched_at ?? new Date().toISOString();
    constellationStore.set(groupId, {
      id: groupId,
      label: config.label,
      color: config.color,
      entries,
      fetchedAt,
    });

    setConstellationMetadata(groupId, {
      hasData: entries.length > 0,
      count: entries.length,
      fetchedAt,
    });
    setConstellationError(groupId, null);
    setConstellationStatusMessage(`Loaded ${entries.length} satellites for ${config.label}. Overlay active.`, 'ready');
    return constellationStore.get(groupId);
  } catch (error) {
    setConstellationError(groupId, error?.message ?? 'Unknown error');
    setConstellationStatusMessage(`Failed to load ${config.label}: ${error?.message ?? error}`, 'error');
    throw error;
  } finally {
    setConstellationLoading(groupId, false);
    updateConstellationToggleStates();
  }
}

function activeConstellationLabels(snapshot = state) {
  const registry = snapshot.constellations?.registry ?? {};
  return CONSTELLATION_GROUPS.filter((group) => registry[group.id]?.enabled).map((group) => group.label);
}

function forceConstellationRefresh() {
  if (!hasActiveConstellations()) {
    clearAllConstellations();
    return;
  }
  if (!Array.isArray(state.computed?.dataPoints) || !state.computed.dataPoints.length) {
    return;
  }
  const index = clamp(state.time.index, 0, state.computed.dataPoints.length - 1);
  if (!Object.keys(state.computed?.constellationPositions ?? {}).length) {
    refreshConstellationPositions();
  }
  updateConstellationVisuals(index);
  lastConstellationIndex = index;
}

async function handleConstellationToggle(groupId, enabled) {
  const config = getConstellationConfig(groupId);
  if (!config) return;
  if (!window.satellite) {
    setConstellationStatusMessage('satellite.js is required to enable constellation overlays.', 'error');
    updateConstellationToggleStates();
    return;
  }

  if (enabled) {
    try {
      const dataset = await loadConstellationGroup(groupId);
      setConstellationEnabled(groupId, true);
      refreshConstellationPositions({ force: true });
      updateConstellationToggleStates();
      const count = dataset?.entries?.length ?? state.constellations?.registry?.[groupId]?.count ?? 0;
      const labels = activeConstellationLabels();
      const suffix = labels.length > 1 ? `Active overlays: ${labels.join(', ')}.` : `${config.label} overlay active.`;
      setConstellationStatusMessage(`Loaded ${count} satellites for ${config.label}. ${suffix}`, 'ready');
      forceConstellationRefresh();
    } catch (error) {
      console.error('Constellation enable failed', error);
      setConstellationEnabled(groupId, false);
      const checkbox = elements.constellationList?.querySelector(`input[data-constellation="${groupId}"]`);
      if (checkbox) checkbox.checked = false;
    } finally {
      updateConstellationToggleStates();
    }
  } else {
    setConstellationEnabled(groupId, false);
    clearConstellation2D(groupId);
    clearConstellation3D(groupId);
    refreshConstellationPositions({ force: true });
    updateConstellationToggleStates();
    if (!hasActiveConstellations()) {
      setConstellationStatusMessage('Select constellations to overlay on the map and globe.', 'idle');
      lastConstellationIndex = -1;
    } else {
      const labels = activeConstellationLabels();
      setConstellationStatusMessage(`Overlay active: ${labels.join(', ')}`, 'ready');
    }
    forceConstellationRefresh();
  }
}

async function fetchWeatherFieldData() {
  if (!elements.weatherFetchBtn) return;
  const variableKey = elements.weatherFieldSelect?.value || state.weather?.variable || 'wind_speed';
  const normalizedKey = Object.prototype.hasOwnProperty.call(WEATHER_FIELDS, variableKey) ? variableKey : 'wind_speed';
  const meta = WEATHER_FIELDS[normalizedKey];
  const levelCandidate = Number(elements.weatherLevelSelect?.value || state.weather?.level_hpa || meta.levels[0]);
  const level = meta.levels.includes(levelCandidate) ? levelCandidate : meta.levels[0];
  const samples = sanitizeWeatherSamples(elements.weatherSamples?.value ?? state.weather?.samples ?? 120);
  const timeLocal = elements.weatherTime?.value || state.weather?.time || isoNowLocal();
  const isoTime = toWeatherIso(timeLocal);

  syncWeatherSamplesInputs(samples);
  const button = elements.weatherFetchBtn;
  button.disabled = true;
  setWeatherStatus('Fetching weather fieldâ€¦');

  mutate((draft) => {
    draft.weather.variable = normalizedKey;
    draft.weather.level_hpa = level;
    draft.weather.samples = samples;
    draft.weather.time = timeLocal.slice(0, 16);
    draft.weather.status = 'loading';
  });

  const payload = {
    variable: normalizedKey,
    level_hpa: level,
    samples,
    time: isoTime,
  };

  try {
    const response = await fetch('/api/get_weather_field', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      let detail = response.statusText;
      try {
        const errorPayload = await response.json();
        if (errorPayload && typeof errorPayload === 'object' && 'detail' in errorPayload) {
          detail = errorPayload.detail;
        } else if (errorPayload) {
          detail = JSON.stringify(errorPayload);
        }
      } catch (err) {
        const text = await response.text();
        if (text) detail = text;
      }
      throw new Error(detail || `HTTP ${response.status}`);
    }
    const data = await response.json();
    lastWeatherSignature = '';
    mutate((draft) => {
      draft.weather.data = data;
      draft.weather.status = 'ready';
      draft.weather.active = true;
    });
    const label = data?.variable?.label ?? meta.label;
    const levelLabel = data?.variable?.pressure_hpa ?? level;
    setWeatherStatus(`Field loaded: ${label} @ ${levelLabel} hPa`);
  } catch (err) {
    console.error('Weather field fetch failed', err);
    mutate((draft) => {
      draft.weather.status = 'error';
    });
    setWeatherStatus(`Failed to fetch field: ${err.message}`);
    clearWeatherField();
    lastWeatherSignature = '';
  } finally {
    button.disabled = false;
  }
}

// ── Heliocentric mode helpers ─────────────────────────────────────────────

/** Update the "N samples" hint next to the helio controls. */
function updateHelioSampleHint() {
  const el = elements.helioSampleCount;
  if (!el) return;
  const interval = state.helio.interval;
  const step = state.helio.step;
  const n = Math.min(10000, Math.floor(interval / step) + 1);
  el.textContent = `(${n} samples)`;
}

/** Fetch the heliocentric scene timeline from the backend and apply it. */
async function recomputeHelioTimeline() {
  try {
    const data = await fetchSceneTimeline(
      state.epoch,
      state.helio.interval,
      state.helio.step,
    );
    if (!data) return;
    _sceneTimelineData = data;

    // Build a compatible timeline array (seconds offsets)
    const offsets = data.t_offsets_s;
    const totalSeconds = offsets.length > 0 ? offsets[offsets.length - 1] : 0;
    setTimeline({ timeline: offsets, totalSeconds });

    // Build Earth orbit path visualisation
    updateEarthOrbitPath(data.earth_pos_eci_au);

    // Also fetch solar data for lighting
    clearSolarData();
    const solarData = await fetchSolarData(state.epoch, offsets);
    if (solarData) scheduleVisualUpdate();
  } catch (err) {
    console.error('[helio] Failed to fetch scene timeline:', err);
  }
}

/** Called when switching to/from heliocentric mode. */
function applySceneModeChange(mode) {
  const isHelio = mode === 'helio';

  // Toggle UI visibility
  if (elements.helioControls) {
    elements.helioControls.style.display = isHelio ? 'flex' : 'none';
  }

  // Toggle scene graph mode
  setSceneHelioMode(isHelio);
  setSolarHelioMode(isHelio);

  if (isHelio) {
    updateHelioSampleHint();
    recomputeHelioTimeline();
  } else {
    // Reset earth system position to origin
    setEarthHelioPosition([0, 0, 0]);
    _sceneTimelineData = null;
    // Recompute normal orbit
    recomputeOrbit(true);
  }
}

async function recomputeOrbit(force = false) {
  // In helio mode, skip orbit propagation and use scene timeline instead
  if (state.sceneMode === 'helio') {
    await recomputeHelioTimeline();
    return;
  }
  const signature = orbitSignature(state);
  if (!force && signature === lastOrbitSignature) return;
  lastOrbitSignature = signature;

  const propagateOptions = orbitSamplesOverride != null
    ? { samplesPerOrbit: orbitSamplesOverride }
    : undefined;
  const orbitData = orbit.propagateOrbit(state, propagateOptions);
  setTimeline({ timeline: orbitData.timeline, totalSeconds: orbitData.totalTime });
  let constellationPositions = {};
  if (hasActiveConstellations() && window.satellite) {
    const datasets = getActiveConstellationDatasets();
    if (datasets.length) {
      constellationPositions = computeConstellationPositions(
        orbitData.timeline,
        state.epoch,
        datasets,
      );
    }
  }
  const metrics = orbit.computeStationMetrics(
    orbitData.dataPoints,
    getSelectedStation(),
    state.optical,
    state,
    null,
  );
  setComputed({
    semiMajor: orbitData.semiMajor,
    orbitPeriod: orbitData.orbitPeriod,
    dataPoints: orbitData.dataPoints,
    groundTrack: orbitData.groundTrack,
    metrics,
    resonance: orbitData.resonance,
    constellationPositions,
  });
  updateOrbitPath(orbitData.dataPoints);
  updateGroundTrackSurface(orbitData.groundTrack);
  frameOrbitView(orbitData.dataPoints, { force: !hasSceneBeenFramed });
  if (!hasSceneBeenFramed && orbitData.dataPoints.length) {
    hasSceneBeenFramed = true;
  }
  lastMetricsSignature = metricsSignature(state);
  flyToOrbit(orbitData.groundTrack, {
    animate: hasMapBeenFramed,
  });
  if (!hasMapBeenFramed && Array.isArray(orbitData.groundTrack) && orbitData.groundTrack.length) {
    hasMapBeenFramed = true;
  }
  await recomputeMetricsOnly(true);
  lastConstellationIndex = -1;
  if (hasActiveConstellations()) {
    forceConstellationRefresh();
  }

  // ── Fetch solar ephemeris for the new orbit timeline ──────────────────
  if (Array.isArray(orbitData.timeline) && orbitData.timeline.length) {
    clearSolarData();
    fetchSolarData(state.epoch, orbitData.timeline).then((sd) => {
      if (sd) scheduleVisualUpdate();   // re-paint with solar data
    });
  }
}

async function recomputeMetricsOnly(force = false) {
  if (!state.computed.dataPoints.length) return;
  const signature = metricsSignature(state);
  if (!force && signature === lastMetricsSignature) return;
  lastMetricsSignature = signature;

  const station = getSelectedStation();
  const optical = state.optical;
  let atmosphereMetrics = null;
  if (station && Array.isArray(state.time.timeline) && state.time.timeline.length) {
    try {
      const midIndex = Math.floor(state.time.timeline.length / 2);
      const midTimeSeconds = state.time.timeline[midIndex] ?? 0;
      const epochMs = new Date(state.epoch).getTime();
      const midTimestamp = new Date(epochMs + midTimeSeconds * 1000).toISOString();

      const response = await fetch('/api/get_atmosphere_profile', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          lat: station.lat,
          lon: station.lon,
          time: midTimestamp,
          ground_cn2_day: state.optical.groundCn2Day,
          ground_cn2_night: state.optical.groundCn2Night,
          model: state.atmosphere?.model ?? 'hufnagel-valley',
          wavelength_nm: state.optical.wavelength,
        }),
      });

      if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.detail || 'Server error');
      }

      atmosphereMetrics = await response.json();
    } catch (error) {
      console.error('Failed to load atmospheric profile:', error);
    }
  }

  const metrics = orbit.computeStationMetrics(
    state.computed.dataPoints,
    station,
    optical,
    state,
    atmosphereMetrics,
  );

  const metricsPayload = {
    ...metrics,
    atmosphereProfile: atmosphereMetrics,
    r0_zenith: atmosphereMetrics?.r0_zenith ?? null,
    fG_zenith: atmosphereMetrics?.fG_zenith ?? null,
    theta0_zenith: atmosphereMetrics?.theta0_zenith ?? null,
    wind_rms: atmosphereMetrics?.wind_rms ?? null,
    loss_aod_db: atmosphereMetrics?.loss_aod_db ?? null,
    loss_abs_db: atmosphereMetrics?.loss_abs_db ?? null,
  };

  setComputed({
    ...state.computed,
    metrics: metricsPayload,
  });

  renderOrbitMessages();
  scheduleVisualUpdate();
}

function scheduleVisualUpdate() {
  const { dataPoints, groundTrack, customConstellation } = state.computed;
  const index = clamp(state.time.index, 0, state.time.timeline.length - 1);

  // ── Heliocentric mode: update Earth position + solar lighting ────────
  if (state.sceneMode === 'helio' && _sceneTimelineData) {
    const stl = _sceneTimelineData;
    const hi = Math.min(index, (stl.earth_pos_eci_au?.length ?? 1) - 1);
    if (stl.earth_pos_eci_au?.[hi]) {
      setEarthHelioPosition(stl.earth_pos_eci_au[hi]);
    }
    if (stl.gmst_rad?.[hi] != null) {
      setEarthRotationFromTime(stl.gmst_rad[hi]);
    }
    const solarData = getSolarData();
    if (solarData) {
      updateSolarFromBackend(hi, solarData);
      // Update directional light for helio mode (sun at origin)
      if (solarData.sun_dir_eci?.[hi]) {
        const [ex, ey, ez] = solarData.sun_dir_eci[hi];
        updateSolarLighting(ex, ez, -ey);  // ECI→Three.js axis mapping
      }
    }
    updateMetricsUI(index);
    return;  // helio mode doesn't render orbit/satellite/link per-step
  }

  // Single orbit
  if (dataPoints && dataPoints.length > 0) {
    const current = dataPoints[index];
    setEarthRotationFromTime(current.gmst ?? 0);

    // ── Solar lighting update (from backend data) ────────────────────────
    const solarData = getSolarData();
    if (solarData) {
      updateSolarFromBackend(index, solarData);
    }

    updateGroundTrack(groundTrack);
    updateGroundTrackSurface(groundTrack);
    updateSatellitePosition({ lat: current.lat, lon: current.lon }, computeFootprint(current.alt));
    const station = getSelectedStation();
    renderStations3D(state.stations.list, station?.id);
    updateSatellite(current);
    updateGroundTrackVector(current);
    updateLinkLine({ lat: current.lat, lon: current.lon }, station);
    const elevation = state.computed.metrics?.elevationDeg?.[index];
    updateLink3D(current, station, elevation);
    renderStations2D(state.stations.list, station?.id);
    updateMetricsUI(index);
  } else {
    updateOrbitPath([]);
    updateGroundTrack([]);
    updateGroundTrackSurface([]);
    updateSatellite(null);
    updateSatellitePosition(null);
    updateLinkLine(null, null);
    updateLink3D(null, null);
    updateMetricsUI(null);
  }

  // TLE Constellations
  if (hasActiveConstellations()) {
    if (state.time.index !== lastConstellationIndex) {
      if (!Object.keys(state.computed?.constellationPositions ?? {}).length) {
        refreshConstellationPositions();
      }
      updateConstellationVisuals(index);
      lastConstellationIndex = index;
    }
  } else if (lastConstellationIndex !== -1) {
    updateConstellationVisuals(index);
    lastConstellationIndex = -1;
  }
  
  // Custom Walker Constellation
  if (customConstellation && customConstellation.satellites) {
      const markers = customConstellation.satellites.map(satellite => {
          const timeline = satellite.timeline;
          const customIndex = clamp(state.time.index, 0, timeline.length - 1);
          const snapshot = timeline[customIndex];
          if (!snapshot) return null;
          return { id: satellite.id, name: satellite.name, lat: snapshot.lat, lon: snapshot.lon, alt: snapshot.alt, rEci: snapshot.rEci, gmst: snapshot.gmst };
      }).filter(Boolean);
      
      if (markers.length) {
          renderConstellations2D(customConstellation.id, markers, { color: customConstellation.color });
          renderConstellations3D(customConstellation.id, markers, { color: customConstellation.color });
      } else {
          clearConstellation2D(customConstellation.id);
          clearConstellation3D(customConstellation.id);
      }
  } else {
      clearConstellation2D('customWalker');
      clearConstellation3D('customWalker');
  }
}

function computeFootprint(altitudeKm) {
  if (!Number.isFinite(altitudeKm) || altitudeKm <= 0) return 0;
  const r = EARTH_RADIUS_KM;
  return Math.sqrt((r + altitudeKm) ** 2 - r ** 2);
}

function updateConstellationVisuals(targetIndex = null) {
  if (!hasActiveConstellations()) {
    clearAllConstellations();
    return;
  }
  const timeline = state.time.timeline ?? [];
  if (!timeline.length) {
    clearAllConstellations();
    return;
  }
  const registry = state.constellations?.registry ?? {};
  const index = clamp(
    targetIndex == null ? state.time.index : targetIndex,
    0,
    timeline.length - 1,
  );
  const positionMap = state.computed?.constellationPositions ?? {};

  CONSTELLATION_GROUPS.forEach((group) => {
    if (!registry[group.id]?.enabled) {
      clearConstellation2D(group.id);
      clearConstellation3D(group.id);
      return;
    }

    const groupPayload = positionMap[group.id];
    if (!groupPayload || !Array.isArray(groupPayload.satellites)) {
      clearConstellation2D(group.id);
      clearConstellation3D(group.id);
      return;
    }

    const markers = [];
    groupPayload.satellites.forEach((satellite) => {
      const snapshot = satellite?.timeline?.[index];
      if (!snapshot) return;
      if (!Number.isFinite(snapshot.lat) || !Number.isFinite(snapshot.lon)) return;
      markers.push({
        id: satellite.id,
        name: satellite.name,
        lat: snapshot.lat,
        lon: snapshot.lon,
        alt: snapshot.alt,
        rEci: snapshot.rEci,
        gmst: snapshot.gmst,
        // Pass the full ground track and orbit path for this satellite
        groundTrack: satellite.groundTrack,
        orbitPath: satellite.orbitPath,
      });
    });

    if (markers.length) {
      renderConstellations2D(group.id, markers, { color: groupPayload.color });
      renderConstellations3D(group.id, markers, { color: groupPayload.color });
    } else {
      clearConstellation2D(group.id);
      clearConstellation3D(group.id);
    }
  });
}

function updateMetricsUI(index) {
  if (index === null) {
    if (elements.distanceMetric) elements.distanceMetric.textContent = '--';
    if (elements.elevationMetric) elements.elevationMetric.textContent = '--';
    if (elements.zenithMetric) elements.zenithMetric.textContent = '--';
    if (elements.lossMetric) elements.lossMetric.textContent = '--';
    if (elements.dopplerMetric) elements.dopplerMetric.textContent = '--';
    if (elements.r0Metric) elements.r0Metric.textContent = '--';
    if (elements.fGMetric) elements.fGMetric.textContent = '--';
    if (elements.theta0Metric) elements.theta0Metric.textContent = '--';
    if (elements.windMetric) elements.windMetric.textContent = '--';
    if (elements.timeLabel) elements.timeLabel.textContent = '0 s';
    if (elements.elevationLabel) elements.elevationLabel.textContent = '--';
    if (elements.lossLabel) elements.lossLabel.textContent = '--';
    return;
  }
  const { metrics } = state.computed;
  if (!metrics.distanceKm.length) {
    if (elements.distanceMetric) elements.distanceMetric.textContent = '--';
    if (elements.elevationMetric) elements.elevationMetric.textContent = '--';
    if (elements.zenithMetric) elements.zenithMetric.textContent = '--';
    if (elements.lossMetric) elements.lossMetric.textContent = '--';
    if (elements.dopplerMetric) elements.dopplerMetric.textContent = '--';
    if (elements.r0Metric) elements.r0Metric.textContent = '--';
    if (elements.fGMetric) elements.fGMetric.textContent = '--';
    if (elements.theta0Metric) elements.theta0Metric.textContent = '--';
    if (elements.windMetric) elements.windMetric.textContent = '--';
    return;
  }

  const distanceKm = metrics.distanceKm[index];
  const elevation = metrics.elevationDeg[index];
  const loss = metrics.lossDb[index];
  const doppler = metrics.doppler[index];
  const zenith = 90 - elevation;
  const r0Meters = valueFromSeries(metrics.r0_array, index, metrics.r0_zenith);
  const greenwoodHz = valueFromSeries(metrics.fG_array, index, metrics.fG_zenith);
  const thetaArcsec = valueFromSeries(metrics.theta0_array, index, metrics.theta0_zenith);
  const windMps = valueFromSeries(metrics.wind_array, index, metrics.wind_rms);

  if (elements.distanceMetric) elements.distanceMetric.textContent = formatDistanceKm(distanceKm);
  if (elements.elevationMetric) elements.elevationMetric.textContent = formatAngle(elevation);
  if (elements.zenithMetric) elements.zenithMetric.textContent = formatAngle(zenith);
  if (elements.lossMetric) elements.lossMetric.textContent = formatLoss(loss);
  if (elements.dopplerMetric) elements.dopplerMetric.textContent = formatDoppler(doppler);
  if (elements.r0Metric) elements.r0Metric.textContent = formatR0Meters(r0Meters);
  if (elements.fGMetric) elements.fGMetric.textContent = formatGreenwoodHz(greenwoodHz);
  if (elements.theta0Metric) elements.theta0Metric.textContent = formatThetaArcsec(thetaArcsec);
  if (elements.windMetric) elements.windMetric.textContent = formatWindMps(windMps);

  if (elements.timeLabel) {
    const t = state.time.timeline[index] ?? 0;
    if (state.sceneMode === 'helio' && t >= 86400) {
      const days = t / 86400;
      elements.timeLabel.textContent = `${days.toFixed(1)} d`;
    } else if (t >= 3600) {
      const hours = t / 3600;
      elements.timeLabel.textContent = `${hours.toFixed(1)} h`;
    } else {
      elements.timeLabel.textContent = `${t.toFixed(1)} s`;
    }
  }
  // Show total simulation duration
  if (elements.totalDurationLabel) {
    const totalSec = state.time.totalSeconds ?? (state.time.timeline?.length ? state.time.timeline[state.time.timeline.length - 1] : 0);
    elements.totalDurationLabel.textContent = formatDuration(totalSec);
  }
  if (elements.elevationLabel) elements.elevationLabel.textContent = formatAngle(elevation);
  if (elements.lossLabel) elements.lossLabel.textContent = formatLoss(loss);

  const station = getSelectedStation();
  if (station) annotateStationTooltip(station, { distanceKm });
}

function createLineChart(canvas, { color }) {
  const ChartJS = window.Chart;
  if (!canvas || !ChartJS) return null;
  if (typeof ChartJS.getChart === 'function') {
    let existing = ChartJS.getChart(canvas);
    if (!existing && canvas.id) {
      existing = ChartJS.getChart(canvas.id);
    }
    if (existing) existing.destroy();
  }
  return new ChartJS(canvas, {
    type: 'line',
    data: {
      labels: [],
      datasets: [
        {
          label: 'Metric',
          data: [],
          borderColor: color,
          backgroundColor: `${color}33`,
          tension: 0.28,
          pointRadius: 0,
          borderWidth: 2,
          fill: false,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          mode: 'index',
          intersect: false,
          callbacks: {
            label: (ctx) => {
              const value = ctx.parsed.y;
              const lineLabel = ctx.dataset?.label || 'Value';
              if (value == null || Number.isNaN(value)) return `${lineLabel}: --`;
              return `${lineLabel}: ${value.toFixed(2)}`;
            },
          },
        },
      },
      scales: {
        x: {
          title: {
            display: true,
            text: 'Time (s)',
          },
          ticks: {
            maxTicksLimit: 8,
          },
          grid: {
            display: false,
          },
        },
        y: {
          title: {
            display: true,
            text: '',
          },
          ticks: {
            maxTicksLimit: 6,
          },
          grid: {
            color: 'rgba(148, 163, 184, 0.15)',
          },
        },
      },
      interaction: {
        intersect: false,
        mode: 'nearest',
      },
    },
  });
}

function initializeCharts() {
  modalChartInstance = createLineChart(elements.modalChartCanvas, {
    color: '#7c3aed',
  });
  updateChartTheme();
}

function updateChartTheme() {
  const charts = [modalChartInstance];
  if (!charts.some((chart) => chart)) return;
  const styles = window.getComputedStyle(document.body);
  const textColor = styles.getPropertyValue('--text')?.trim() || '#111827';
  const gridColor = styles.getPropertyValue('--border')?.trim() || 'rgba(148, 163, 184, 0.18)';
  const tooltipBg = styles.getPropertyValue('--surface')?.trim() || 'rgba(15, 23, 42, 0.9)';
  charts.forEach((chart) => {
    if (!chart) return;
    const { scales, plugins } = chart.options;
    if (scales?.x?.ticks) scales.x.ticks.color = textColor;
    if (scales?.x?.title) scales.x.title.color = textColor;
    if (scales?.y?.ticks) scales.y.ticks.color = textColor;
    if (scales?.y?.title) scales.y.title.color = textColor;
    if (scales?.y?.grid) scales.y.grid.color = gridColor;
    if (plugins?.tooltip) {
      plugins.tooltip.titleColor = textColor;
      plugins.tooltip.bodyColor = textColor;
      plugins.tooltip.backgroundColor = tooltipBg;
    }
    chart.update('none');
  });
}

function showModalGraph(graphId) {
  if (!modalChartInstance || !elements.graphModal || !elements.graphModalTitle) return;
  const timeline = Array.isArray(state.time.timeline) ? state.time.timeline : [];
  const metrics = state.computed?.metrics ?? {};
  if (!timeline.length || !metrics) return;

  const graphConfig = {
    loss: {
      data: metrics.lossDb ?? [],
      title: 'Loss vs Time',
      yLabel: 'Geometric loss (dB)',
      color: '#7c3aed',
    },
    elevation: {
      data: metrics.elevationDeg ?? [],
      title: 'Elevation vs Time',
      yLabel: 'Station elevation (Â°)',
      color: '#0ea5e9',
    },
    distance: {
      data: metrics.distanceKm ?? [],
      title: 'Range vs Time',
      yLabel: 'Satellite-ground range (km)',
      color: '#22c55e',
    },
    r0: {
      data: metrics.r0_array ?? [],
      title: 'Fried parameter (r0)',
      yLabel: 'r0 (m)',
      color: '#f97316',
      datasetLabel: 'r0 (m)',
    },
    fG: {
      data: metrics.fG_array ?? [],
      title: 'Greenwood frequency (fG)',
      yLabel: 'fG (Hz)',
      color: '#06b6d4',
      datasetLabel: 'fG (Hz)',
    },
    theta0: {
      data: metrics.theta0_array ?? [],
      title: 'Isoplanatic angle (theta0)',
      yLabel: 'theta0 (arcsec)',
      color: '#10b981',
      datasetLabel: 'theta0 (arcsec)',
    },
    wind: {
      data: metrics.wind_array ?? [],
      title: 'RMS wind speed',
      yLabel: 'Wind (m/s)',
      color: '#f59e0b',
      datasetLabel: 'Wind (m/s)',
    },
  };

  const config = graphConfig[graphId];
  if (!config) return;

  const labels = timeline.map((value) => (
    Number.isFinite(value) ? Number(value.toFixed(1)) : value
  ));
  const series = Array.isArray(config.data) ? config.data : [];
  const datasetLabel = config.datasetLabel ?? config.yLabel;

  elements.graphModalTitle.textContent = config.title;
  modalChartInstance.data.labels = labels;
  modalChartInstance.data.datasets[0].data = labels.map((_, idx) => {
    const raw = series[idx];
    if (!Number.isFinite(raw)) return null;
    if (typeof config.transform === 'function') {
      const transformed = config.transform(raw);
      return Number.isFinite(transformed) ? transformed : null;
    }
    return raw;
  });
  modalChartInstance.data.datasets[0].label = datasetLabel;
  modalChartInstance.data.datasets[0].borderColor = config.color;
  modalChartInstance.data.datasets[0].backgroundColor = `${config.color}33`;
  modalChartInstance.options.scales.y.title.text = config.yLabel;
  modalChartInstance.update('none');
  updateChartTheme();

  const modal = elements.graphModal;
  if (!(modal instanceof HTMLDialogElement)) return;
  if (!modal.open) {
    modal.showModal();
  }
  requestAnimationFrame(() => {
    modalChartInstance.resize();
    elements.closeGraphModal?.focus();
  });
}

function renderOrbitMessages() {
  if (!elements.orbitMessages) return;
  const info = state.computed?.resonance ?? {};
  const lines = [];
  const ratio = info?.ratio;
  const requested = Boolean(info?.requested);
  const applied = info?.applied;
  const formatKm = (value) => `${Number(value).toLocaleString('en-US', { maximumFractionDigits: 0 })} km`;

  if (requested && ratio) {
    const label = `${ratio.orbits}:${ratio.rotations}`;
    if (applied !== false) {
      lines.push(`<p><strong>Resonance ${label}</strong> Â· ground track repeats after ${ratio.orbits} orbit(s).</p>`);
    } else {
      lines.push(`<p><strong>Attempted resonance ${label}</strong> Â· adjust the parameters or review the warnings.</p>`);
      if (Number.isFinite(info?.deltaKm)) {
        lines.push(`<p>Current offset relative to the resonance: ${formatKm(info.deltaKm, 3)} km.</p>`);
      }
    }
  }

  const semiMajorKm = state.computed?.semiMajor ?? info?.semiMajorKm;
  if (semiMajorKm) {
    lines.push(`<p>Applied semi-major axis: <strong>${formatKm(semiMajorKm)}</strong></p>`);
  }

  if (info?.periodSeconds) {
    lines.push(`<p>Orbital period: ${formatDuration(info.periodSeconds)}</p>`);
  }

  if (info?.perigeeKm != null && info?.apogeeKm != null) {
    const perigeeAlt = info.perigeeKm - EARTH_RADIUS_KM;
    const apogeeAlt = info.apogeeKm - EARTH_RADIUS_KM;
    lines.push(`<p>Perigee / apogee altitude: ${perigeeAlt.toFixed(0)} km / ${apogeeAlt.toFixed(0)} km</p>`);
  }

  if (info?.closureSurfaceKm != null) {
    const gap = info.closureSurfaceKm;
    const closureText = gap < 0.01 ? '&lt; 0.01 km' : `${gap.toFixed(2)} km`;
    if (requested && info.closed) {
      lines.push(`<p>âœ”ï¸ Ground track closed (Î” ${closureText}).</p>`);
    } else if (requested) {
      lines.push(`<p class="warning">âš ï¸ Offset after resonance: ${closureText}</p>`);
    } else {
      lines.push(`<p>Ground-track closure: ${closureText}</p>`);
    }
  }

  if ((info?.latDriftDeg ?? 0) !== 0 || (info?.lonDriftDeg ?? 0) !== 0) {
    const lat = info.latDriftDeg ?? 0;
    const lon = info.lonDriftDeg ?? 0;
    if (Math.abs(lat) > 1e-3 || Math.abs(lon) > 1e-3) {
      lines.push(`<p>Cycle drift: Î”lat ${lat.toFixed(3)}Â°, Î”lon ${lon.toFixed(3)}Â°.</p>`);
    }
  }

  if (Array.isArray(info?.warnings)) {
    info.warnings.forEach((warning) => {
      if (warning) {
        lines.push(`<p class="warning">âš ï¸ ${warning}</p>`);
      }
    });
  }

  elements.orbitMessages.innerHTML = lines.join('');
  elements.orbitMessages.hidden = lines.length === 0;
}

function clearSingleOrbit() {
    mutate((draft) => {
        draft.computed.dataPoints = [];
        draft.computed.groundTrack = [];
        draft.computed.metrics = {};
    });
}

function clearCustomConstellation() {
    mutate((draft) => {
        draft.computed.customConstellation = null;
    });
    clearConstellation2D('customWalker');
    clearConstellation3D('customWalker');
}

function clearTleConstellations() {
    mutate(draft => {
        if (draft.constellations && draft.constellations.registry) {
            Object.keys(draft.constellations.registry).forEach(groupId => {
                draft.constellations.registry[groupId].enabled = false;
            });
        }
        draft.computed.constellationPositions = {};
    });
}

async function plotWalkerConstellation() {
    const T = Number(elements.walkerT?.value) || 24;
    const P = Number(elements.walkerP?.value) || 6;
    const F = Number(elements.walkerF?.value) || 1;
    const a = Number(elements.walkerA?.value) || 7071;
    const i = Number(elements.walkerI?.value) || 55;
    const e = 0.0;

    const constellationElements = generateWalkerConstellation(T, P, F, a, i, e);

    let timeline = state.time.timeline;
    if (!timeline || timeline.length === 0) {
        await recomputeOrbit(true); // This will generate a timeline
        timeline = state.time.timeline;
    }

    if (!timeline || timeline.length === 0) {
        console.error("Timeline not available for constellation propagation.");
        setConstellationStatusMessage('Error: Timeline not available. Please propagate an orbit first.', 'error');
        return;
    }
    
    setConstellationStatusMessage(`Propagating ${constellationElements.length} satellites...`, 'loading');

    const satellites = [];
    for (let index = 0; index < constellationElements.length; index++) {
        const satElements = constellationElements[index];
        const satSettings = {
            ...state,
            orbital: satElements,
            resonance: { enabled: false },
        };
        const orbitData = orbit.propagateOrbit(satSettings, { samplesPerOrbit: DRAFT_SAMPLES_PER_ORBIT });
        satellites.push({
            id: `walker-${index}`,
            name: `W-${index}`,
            timeline: orbitData.dataPoints,
        });
    }
    
    mutate((draft) => {
        draft.computed.customConstellation = {
            id: 'customWalker',
            color: '#f59e0b',
            satellites,
        };
    });
    setConstellationStatusMessage(`Rendered ${constellationElements.length} satellite constellation.`, 'ready');
}

function playbackLoop(timestamp) {
  const timeline = state.time.timeline;
  if (!state.time.playing || timeline.length === 0) {
    playbackLoop.lastTimestamp = timestamp;
    playbackLoop.simulatedTime = timeline[state.time.index] ?? 0;
    playingRaf = requestAnimationFrame(playbackLoop);
    return;
  }

  if (!Number.isFinite(playbackLoop.lastTimestamp)) {
    playbackLoop.lastTimestamp = timestamp;
  }

  const dt = (timestamp - playbackLoop.lastTimestamp) / 1000;
  playbackLoop.lastTimestamp = timestamp;

  const totalTime = timeline[timeline.length - 1] ?? 0;
  if (!Number.isFinite(playbackLoop.simulatedTime)) {
    playbackLoop.simulatedTime = timeline[state.time.index] ?? 0;
  }

  playbackLoop.simulatedTime += dt * state.time.timeWarp;

  if (totalTime > 0) {
    playbackLoop.simulatedTime %= totalTime;
    if (playbackLoop.simulatedTime < 0) {
      playbackLoop.simulatedTime += totalTime;
    }
  } else {
    playbackLoop.simulatedTime = 0;
  }

  let nextIndex = state.time.index;
  while (nextIndex < timeline.length - 1 && timeline[nextIndex + 1] <= playbackLoop.simulatedTime) {
    nextIndex += 1;
  }
  while (nextIndex > 0 && timeline[nextIndex] > playbackLoop.simulatedTime) {
    nextIndex -= 1;
  }

  if (nextIndex !== state.time.index) {
    setTimeIndex(nextIndex);
    playbackLoop.simulatedTime = timeline[nextIndex] ?? playbackLoop.simulatedTime;
  }

  playingRaf = requestAnimationFrame(playbackLoop);
}

function onStateChange(snapshot) {
  if (Array.isArray(snapshot.time.timeline) && snapshot.time.timeline.length) {
    playbackLoop.simulatedTime = snapshot.time.timeline[snapshot.time.index] ?? playbackLoop.simulatedTime;
  }
  ensureStationSelected();
  refreshStationSelect();
  if (elements.timeSlider && snapshot.time.timeline.length) {
    elements.timeSlider.max = snapshot.time.timeline.length - 1;
    elements.timeSlider.value = String(snapshot.time.index);
  }
  if (snapshot.theme) applyTheme(snapshot.theme);
  if (snapshot.viewMode) updateViewMode(snapshot.viewMode);
  if (elements.j2Toggle && !elements.j2Toggle.matches(':focus')) {
    elements.j2Toggle.checked = snapshot.orbital.j2Enabled ?? false;
  }
  if (elements.groundCn2Day && !elements.groundCn2Day.matches(':focus')) {
    elements.groundCn2Day.value = String(snapshot.optical.groundCn2Day ?? 5e-14);
  }
  if (elements.groundCn2Night && !elements.groundCn2Night.matches(':focus')) {
    elements.groundCn2Night.value = String(snapshot.optical.groundCn2Night ?? 5e-15);
  }
  if (elements.atmosModelInputs?.length) {
    const selectedModel = snapshot.atmosphere?.model ?? 'hufnagel-valley';
    elements.atmosModelInputs.forEach((input) => {
      if (input.matches(':focus')) return;
      const model = input.dataset.atmosModel || input.value;
      input.checked = model === selectedModel;
    });
  }

  const weatherState = snapshot.weather ?? {};
  const weatherFieldKey = weatherState.variable ?? 'wind_speed';
  const weatherLevel = weatherState.level_hpa ?? (WEATHER_FIELDS[weatherFieldKey]?.levels?.[0] ?? 200);
  const weatherSamples = sanitizeWeatherSamples(weatherState.samples ?? 120);
  const weatherTime = (weatherState.time ?? isoNowLocal()).slice(0, 16);

  if (elements.weatherFieldSelect && !elements.weatherFieldSelect.matches(':focus')) {
    if (!elements.weatherFieldSelect.querySelector(`option[value="${weatherFieldKey}"]`)) {
      populateWeatherFieldOptions(weatherFieldKey);
    }
    elements.weatherFieldSelect.value = weatherFieldKey;
  }
  if (elements.weatherLevelSelect && !elements.weatherLevelSelect.matches(':focus')) {
    populateWeatherLevelOptions(weatherFieldKey, weatherLevel);
  }
  if (elements.weatherSamples && !elements.weatherSamples.matches(':focus')) {
    elements.weatherSamples.value = String(weatherSamples);
  }
  if (elements.weatherSamplesSlider && !elements.weatherSamplesSlider.matches(':active')) {
    elements.weatherSamplesSlider.value = String(weatherSamples);
  }
  if (elements.weatherTime && !elements.weatherTime.matches(':focus')) {
    elements.weatherTime.value = weatherTime;
  }
  if (elements.weatherClearBtn) {
    elements.weatherClearBtn.disabled = !weatherState.data;
  }

  updateConstellationToggleStates(snapshot);

  const shouldRenderWeather = weatherState.active && weatherState.data;
  if (shouldRenderWeather) {
    const weatherSig = JSON.stringify({
      ts: weatherState.data.timestamp,
      var: weatherState.data.variable?.open_meteo_key ?? weatherState.data.variable?.key,
      min: weatherState.data.grid?.min,
      max: weatherState.data.grid?.max,
      rows: weatherState.data.grid?.rows,
      cols: weatherState.data.grid?.cols,
    });
    if (weatherSig !== lastWeatherSignature) {
      renderWeatherField(weatherState.data);
      lastWeatherSignature = weatherSig;
    }
  } else if (lastWeatherSignature) {
    clearWeatherField();
    lastWeatherSignature = '';
  }

  const orbitSig = orbitSignature(snapshot);

  // Detect scene mode change (orbit ↔ helio)
  if (snapshot.sceneMode !== onStateChange._lastSceneMode) {
    onStateChange._lastSceneMode = snapshot.sceneMode;
    applySceneModeChange(snapshot.sceneMode);
    return;
  }

  if (orbitSig !== lastOrbitSignature) {
    void recomputeOrbit(true);
    return;
  }

  const metricsSig = metricsSignature(snapshot);
  if (metricsSig !== lastMetricsSignature) {
    void recomputeMetricsOnly(true);
    return;
  }

  scheduleVisualUpdate();
}

async function initialize() {
  cacheElements();
  setWeatherElements(elements);
  initDefaults();
  initInfoButtons();
  // create collapsible panels for each section (guarded)
  try {
    if (typeof createPanelAccordions === 'function') {
      createPanelAccordions();
    } else {
      console.warn('createPanelAccordions not available');
    }
  } catch (e) {
    console.warn('Error while initializing accordions', e);
  }
  bindEvents();
  hasMapBeenFramed = false;
  hasSceneBeenFramed = false;

  mapInstance = initMap(elements.mapContainer);
  setBaseLayer(currentMapStyle);
  await initScene(elements.threeContainer);
  // mark 3D as ready for debug queries
  try { window.__scene3dReady = true; } catch (e) {}
  // restore saved optimization points from localStorage
  try {
    const raw = localStorage.getItem('qkd:optimizationPoints');
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length) {
        mutate((draft) => { draft.optimizationPoints = parsed; });
        // add markers for each point
        if (elements.addOptimizationMarker) {
          parsed.forEach((pt) => {
            try { elements.addOptimizationMarker(pt.lat, pt.lon); } catch (e) { /* ignore */ }
          });
          if (elements.renderPointsList) elements.renderPointsList();
        }
      }
    }
  } catch (err) {
    console.warn('Could not restore optimization points', err);
  }
  initializeCharts();
  applyTheme(state.theme);

  await loadStationsFromServer();
  refreshStationSelect();
  await recomputeOrbit(true);
  subscribe(onStateChange, false);
  onStateChange._lastSceneMode = state.sceneMode;  // initialise mode tracker
  // persist optimization points on each state change (debounced-ish via animation frame)
  let persistRaf = null;
  subscribe(() => {
    if (persistRaf) cancelAnimationFrame(persistRaf);
    persistRaf = requestAnimationFrame(() => {
      try {
        const data = state.optimizationPoints || [];
        localStorage.setItem('qkd:optimizationPoints', JSON.stringify(data));
      } catch (e) {
        console.warn('Could not persist optimization points', e);
      }
    });
  }, false);
  playingRaf = requestAnimationFrame(playbackLoop);
  if (mapInstance) {
    setTimeout(() => invalidateMap(), 400);
  }
  // Expose a lightweight status helper for debugging map/3D issues
  try {
    window.__appStatus = function () {
      const threeCanvas = elements.threeContainer?.querySelector('#threeCanvas');
      let webglAvailable = false;
      try {
        if (threeCanvas) {
          webglAvailable = !!(threeCanvas.getContext && (threeCanvas.getContext('webgl2') || threeCanvas.getContext('webgl')));
        }
      } catch (e) { webglAvailable = false; }
      return {
        mapLoaded: !!mapInstance,
        mapContainerPresent: !!elements.mapContainer,
        currentMapStyle,
        scene3dReady: Boolean(window.__scene3dReady),
        webglAvailable,
        panelCollapsed: elements.controlPanel?.dataset?.collapsed,
      };
    };
  } catch (e) {}
}

initialize();
