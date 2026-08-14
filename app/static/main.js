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
import { isoNowLocal, clamp, formatAngle, formatDistanceKm, formatLoss, formatDoppler, formatDuration } from './utils.js';

// Re-export from extracted modules for this file's internal use
// (keeping local references for backward compatibility with existing code)
import {
  state, defaultState, CONSTELLATION_GROUPS,
  subscribe, emit, mutate, resetComputed,
  setTheme, setVariant, ensureStationSelected,
  removeStation, removeStations, selectStation,
  setTimeline, setComputed, togglePlay, setTimeIndex, setTimeWarp,
  setSceneMode, setHelioInterval, setHelioStep,
  withConstellationGroup, setConstellationEnabled,
  setConstellationLoading, setConstellationMetadata, setConstellationError,
  createDefaultConstellationState
} from './state.js';

import {
  loadStationsFromServer, clearStations, deleteStationRemote
} from './stations.js';

import {
  firstFiniteValue, valueFromSeries, formatR0Meters, formatGreenwoodHz,
  formatThetaArcsec, formatWindMps
} from './formatters.js';
// formatKm kept local (custom behavior)

import { initInfoButtons } from './tooltips.js';

import {
  WEATHER_FIELDS, setWeatherElements, populateWeatherFieldOptions,
  populateWeatherLevelOptions, sanitizeWeatherSamples, syncWeatherSamplesInputs,
  setWeatherStatus, toWeatherIso
} from './weather.js';
import { orbit, walkerGenerator, qkdCalculations } from './simulation.js';
import {
  map2d, scene3d, initSliders, createPanelAccordions,
  getMapStyles, getMapStyle, setMapStyle, captureViewportPng,
} from './ui.js';
import { createResonancePanel } from './optimizer.js';
import { createQkdRelay } from './qkd_relay.js';
import { createIrradiance } from './irradiance.js';
import { createModalGraphs } from './modal_graphs.js';
import { createStationDialog } from './station_dialog.js';
import { createPaperFigures } from './paper_figures.js';
import { createStudyPanel } from './study_panel.js';
import { showToast } from './toast.js';
import { fetchSolarData, updateSolarFromBackend, getSolarData, clearSolarData, setSolarHelioMode } from './solar.js';
import { fetchSceneTimeline, designSSOOrbit } from './api.js';
import { resetZoom as plotlyResetZoom } from './plotly_charts.js';

const { constants: orbitConstants, gmstFromDate } = orbit;
const { generateWalkerConstellation } = walkerGenerator;
const { calculateQKDPerformance } = qkdCalculations;

// ── Approximate Sun direction from a Date (low-precision solar ephemeris) ──
// Good to ~1°; used as initial lighting when backend solar data is not yet
// available.  Returns ECI unit vector [x, y, z].
function approxSunDirEci(date) {
  const jd = date.getTime() / 86400000 + 2440587.5;
  const n = jd - 2451545.0;                          // days since J2000.0
  const DEG = Math.PI / 180;
  const L = ((280.460 + 0.9856474 * n) % 360) * DEG;  // mean longitude
  const g = ((357.528 + 0.9856003 * n) % 360) * DEG;  // mean anomaly
  const lambda = L + 1.915 * DEG * Math.sin(g) + 0.020 * DEG * Math.sin(2 * g);
  const eps = 23.439 * DEG;                            // obliquity
  return [
    Math.cos(lambda),
    Math.cos(eps) * Math.sin(lambda),
    Math.sin(eps) * Math.sin(lambda),
  ];
}

/**
 * Sync the 3D scene’s Earth rotation and Sun lighting to the current epoch,
 * using client-side GMST + approximate solar position.  Called when no
 * backend solar data is available yet (scene init, epoch change, etc.).
 */
function syncSceneToEpoch() {
  const epochDate = new Date(state.epoch);
  if (Number.isNaN(epochDate.getTime())) return;
  // Earth rotation
  const gmst = gmstFromDate(epochDate);
  setEarthRotationFromTime(gmst);
  // Approximate sun direction
  const [ex, ey, ez] = approxSunDirEci(epochDate);
  // ECI → Three.js axis mapping:  tx=x, ty=z, tz=-y
  updateSolarLighting(ex, ez, -ey);
}

const {
  initMap,
  updateGroundTrack,
  updateSatellitePosition,
  renderStations: renderStations2D,
  updateLinkLine,
  focusOnStation,
  flyToOrbit,
  annotateStationTooltip,
  invalidateSize: invalidateMap,
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
let currentMapStyle = 'satellite';
let currentProjection = '3d';   // last projection picked ('3d' | '2d')
// Ground-station display, driven from the Ground Stations panel.
const stationDisplay = { mode: 'all', labels: true };
let lastOrbitSignature = '';
let lastMetricsSignature = '';
let lastWeatherSignature = '';
let playingRaf = null;
let panelWidth = 360;
let lastExpandedPanelWidth = 360;
let hasMapBeenFramed = false;
let hasSceneBeenFramed = false;
let _sceneTimelineData = null;     // cached scene-timeline response for helio mode

const constellationStore = new Map();
let lastConstellationIndex = -1;

const PANEL_MIN_WIDTH = 240;
const PANEL_MAX_WIDTH = 520;
const PANEL_COLLAPSE_THRESHOLD = 280;

function cacheElements() {
  const ids = [
    'satelliteName', 'epochInput', 'semiMajor', 'semiMajorSlider',
    'resonanceToggle', 'resOrbits', 'resDays', 'resonanceSummary',
    'eccentricity', 'eccentricitySlider', 'inclination', 'inclinationSlider', 'raan', 'raanSlider', 'argPerigee', 'argPerigeeSlider',
    'meanAnomaly', 'meanAnomalySlider',
    'satAperture', 'satApertureSlider', 'groundAperture', 'groundApertureSlider', 'wavelength',
    'wavelengthSlider', 'samplesPerOrbit', 'samplesPerOrbitSlider', 'timeSlider', 'btnPlay', 'btnPause',
    'btnStepBack', 'btnStepForward', 'btnResetTime', 'timeWarp', 'btnTheme', 'btnPanelToggle',
  'mapStyleSelect', 'btnExportView', 'exportScale',
  'stationVisibility', 'stationHideNames', 'panelResizer', 'stationSelect', 'btnAddStation', 'btnDeleteStation', 'btnFocusStation', 'stationAltitude', 'timeLabel', 'totalDurationLabel', 'btnMenuToggle',
    'elevationLabel', 'lossLabel', 'distanceMetric', 'elevationMetric', 'zenithMetric', 'lossMetric',
    'dopplerMetric', 'threeContainer', 'mapContainer', 'orbitMessages',
    'stationDialog', 'stationName', 'stationLat', 'stationLon', 'stationAperture', 'stationSave', 'stationCancel',
    'optimizerForm',
    'graphModal', 'graphModalTitle', 'modalChartCanvas', 'closeGraphModal', 'resetZoomBtn',
    'groundCn2Day', 'groundCn2Night', 'r0Metric', 'fGMetric', 'theta0Metric', 'windMetric',
    'stationPickOnMap', 'stationPickHint',
    'weatherFieldSelect', 'weatherLevelSelect', 'weatherSamples', 'weatherSamplesSlider',
    'weatherTime', 'weatherFetchBtn', 'weatherClearBtn', 'weatherStatus',
    'constellationList', 'constellationStatus',
    'walkerPanel', 'walkerT', 'walkerP', 'walkerF', 'walkerA', 'walkerI', 'btnPlotConstellation', 'btnClearOrbit', 'btnClearConstellation',
    'btnDefinePoints', 'btnOptimize', 'btnCancelOptimize', 'simDuration', 'pointsCount', 'optStatus', 'optProgress', 'workerToggle', 'workerCount',
    // QKD elements
    'qkdProtocol', 'photonRate', 'photonRateSlider', 'detectorEfficiency', 'detectorEfficiencySlider',
    'darkCountRate', 'darkCountRateSlider', 'opticalFilterBandwidth', 'opticalFilterBandwidthSlider',
    'btnCalculateQKD', 'btnQKDSeries', 'qkdStatus', 'qberMetric', 'rawKeyRateMetric', 'secureKeyRateMetric', 'channelTransmittanceMetric',
    // QKD → Advanced Analysis (finite key / cloud availability / Monte Carlo /
    // temporal gating).  These travel only to the backend, so they are read
    // from the DOM at request time (solve_payload.js) rather than mirrored into
    // state — but the checkbox → dependent-fields wiring lives here.
    'solveTotalOrbits', 'keyVolumeElevThreshold',
    'temporalGatingEnabled', 'temporalGatingFields', 'gateTimeNs',
    'muSignal', 'muDecoy',
    'finiteKeyEnabled', 'finiteKeyFields',
    'availabilityEnabled', 'availabilityFields', 'availabilityEstimator', 'cloudThresholdPct',
    'monteCarloEnabled', 'monteCarloFields', 'mcSummary',
    // Constellation study
    'studyStations', 'btnRunStudy', 'studyStatus', 'btnShowStudyResults',
    'btnStudySelectEurope', 'btnStudySelectAll', 'btnStudyClearSel',
    'studyDialog', 'studyGrid', 'studyTable', 'closeStudyDialog',
    // Link Budget elements
    'linkDirection',
    'atmZenithAod', 'atmZenithAodSlider', 'atmZenithAbs', 'atmZenithAbsSlider',
    'pointingErrorUrad', 'pointingErrorUradSlider', 'patFadingModel',
    'fixedOpticsLoss', 'fixedOpticsLossSlider',
    'scintillationEnabled', 'scintillationP0', 'scintillationP0Slider', 'scintillationFields',
    'backgroundEnabled', 'bgRadiance', 'bgFovMrad', 'bgFovMradSlider',
    'bgDeltaLambda', 'bgDeltaLambdaSlider', 'backgroundFields',
    // Link Budget analytics metrics
    'geoLossMetric', 'atmLossMetric', 'pointingLossMetric', 'scintLossMetric',
    'fixedLossMetric', 'totalLossMetric', 'bgNoiseMetric', 'couplingMetric',
    'sunAngleMetric', 'eclipseMetric', 'sunExcludedMetric',
    'rxPowerMetric', 'linkMarginMetric',
    'sunExclusionDeg', 'sunExclusionDegSlider',
    'minElevationDeg', 'minElevationDegSlider',
    'txPowerDbm', 'txPowerDbmSlider',
    'rxSensitivityDbm', 'rxSensitivityDbmSlider',
    'j2Toggle', 'j3Toggle', 'j4Toggle',
    // SSO panel elements
    'ssoToggle', 'ssoFields', 'ssoAltitude', 'ssoAltitudeSlider', 'ssoEccentricity',
    'ssoLTAN', 'btnComputeSSO', 'ssoResults', 'ssoError', 'btnApplySSO',
    'ssoResInc', 'ssoResSMA', 'ssoResRAAN', 'ssoResPeriod', 'ssoResRevs',
    'ssoResDrift', 'ssoResClass',
    // Heliocentric mode controls
    'sceneModeSelect', 'helioControls', 'helioInterval', 'helioStep', 'helioSampleCount',
    // Irradiance panel
    'irradianceMethod', 'irradianceTime', 'irradianceAltitude', 'btnFetchIrradiance',
    'irradianceStatus', 'irradianceMetrics', 'irradianceGHI', 'irradianceDNI', 'irradianceDHI',
    'irradianceElevation', 'irradianceDayNight', 'irradianceAirMass', 'irradianceDayLength',
    'irradianceSunrise', 'irradianceSunset', 'irradianceSource', 'irradianceChart',
    // Pass time over OGS
    'passZenithThreshold', 'passZenithThresholdSlider', 'btnComputePassTime',
    'passTimeResults', 'passTimeTotalMetric', 'passTimeCountMetric', 'passTimeLongestMetric',
    // Link Margin Study dialog
    'btnLinkMarginStudy', 'linkMarginDialog', 'linkMarginGrid', 'linkMarginTitle',
    'closeLinkMarginDialog', 'resetLmZoom',
    // UTC clock
    'utcClockDate', 'utcClockTime',
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
  const activeNavItem = document.querySelector(`.app-nav .nav-item[data-section="${target}"]`);
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

function syncPairValue(inputId, sliderId, value, spanId = null) {
  const numeric = Number(value);
  if (elements[inputId]) {
    if (Number.isFinite(numeric)) {
      if (inputId === 'semiMajor') {
        elements[inputId].value = numeric.toFixed(0); // Remove decimals for semiMajor
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

function formatKm(value, fractionDigits = 3, useGrouping = true) {
  if (!Number.isFinite(value)) return '--';
  return Number(value).toLocaleString('en-US', {
    useGrouping,
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  });
}

const resonancePanel = createResonancePanel({
  elements,
  syncPairValue,
  formatKm,
  recomputeOrbit,
});

const qkdRelay = createQkdRelay({ elements, getSelectedStation });
const irradiance = createIrradiance({ elements, getSelectedStation });
const modalGraphs = createModalGraphs({ elements, getSelectedStation });
const stationDialog = createStationDialog({
  elements,
  getMapInstance: () => mapInstance,
  refreshStationSelect,
  recomputeMetricsOnly,
});

const paperFigures = createPaperFigures({
  onApplyPreset: async (p) => {
    // Push the paper's optical/link-budget parameters into the live simulator
    // (the /api/paper/* figures are independent of this — this is a convenience).
    try {
      mutate((draft) => {
        draft.optical.wavelength = p.wavelength_nm;
        draft.optical.satAperture = p.sat_aperture_m;
        draft.linkBudget.minElevationDeg = p.min_elevation_deg;
        draft.linkBudget.pointingErrorUrad = p.sigma_p_urad;
        draft.linkBudget.scintillationEnabled = true;
        draft.linkBudget.backgroundEnabled = true;
        draft.linkBudget.bgRadiance = p.Hrad_night;
        draft.linkBudget.bgFovMrad = p.fov_half_mrad;
        draft.linkBudget.bgDeltaLambda = p.filter_nm;
        draft.linkBudget.fixedOpticsLoss = p.fixed_optics_loss_db;
        draft.linkBudget.patFadingEnabled = false;
      });
      await recomputeOrbit(true);
      showToast('Paper scenario applied to the simulator', { type: 'success' });
    } catch (e) {
      showToast(`Could not apply scenario: ${e.message}`, { type: 'error' });
    }
  },
});

const studyPanel = createStudyPanel({
  getStations: () => state.stations?.list ?? [],
});

function applyTheme(theme) {
  if (theme === 'dark') {
    document.body.dataset.theme = 'dark';
  } else {
    delete document.body.dataset.theme;
  }
  setSceneTheme?.(theme);
  if (elements.btnTheme) {
    const pressed = theme === 'dark';
    elements.btnTheme.setAttribute('aria-pressed', pressed ? 'true' : 'false');
    elements.btnTheme.textContent = pressed ? 'Light mode' : 'Dark mode';
  }
}

function updateViewMode(mode) {
  // 'dual' was a split 3D|2D pane that the single-viewer engine cannot render;
  // any persisted snapshot still carrying it falls back to the 3D globe.
  const target = !mode || mode === 'dual' ? '3d' : mode;
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
      // Hide top-nav and panel for fullscreen
      const sidebar = document.getElementById('topbar');
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
      // Show top-nav and panel
      const sidebar = document.getElementById('topbar');
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

/** Fill the topbar basemap selector from whatever the active engine offers. */
function populateMapStyleOptions(selected) {
  const select = elements.mapStyleSelect;
  if (!select) return;
  const styles = getMapStyles();
  select.innerHTML = '';
  Object.entries(styles).forEach(([key, spec]) => {
    const option = document.createElement('option');
    option.value = key;
    option.textContent = spec.label ?? key;
    select.appendChild(option);
  });
  select.value = styles[selected] ? selected : Object.keys(styles)[0];
}

/**
 * Push the panel's station-display choice to both renderers.
 * The active station is always the one the link budget uses — hiding it on the
 * map is purely cosmetic and never changes a computation.
 */
function applyStationDisplay() {
  const payload = { ...stationDisplay, selectedId: state.stations?.selectedId ?? null };
  scene3d.setStationDisplay?.(payload);
  map2d.setStationDisplay?.(payload);
}

/**
 * Export the current viewport (globe or flat map, with the orbit, ground track
 * and pass as drawn) to a PNG. Only the render canvas is captured, so the
 * control panel, timeline and browser chrome never appear in the figure.
 */
async function exportCurrentView() {
  const btn = elements.btnExportView;
  const scale = Number(elements.exportScale?.value) || 3;
  const label = btn?.textContent;
  if (btn) { btn.disabled = true; btn.textContent = '…'; }
  try {
    const { dataUrl, width, height } = await captureViewportPng({ scale });
    const view = currentProjection === '2d' ? 'map2d' : 'globe3d';
    const sat = (state.satelliteName || 'sat').replace(/[^\w.-]+/g, '_');
    const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    const link = document.createElement('a');
    link.href = dataUrl;
    link.download = `simulcttc_${view}_${sat}_${stamp}.png`;
    link.click();
    showToast(`Imagen exportada (${width}×${height} px)`, { type: 'success' });
  } catch (error) {
    showToast(`No se pudo exportar la imagen: ${error.message}`, { type: 'error' });
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = label ?? '⤓ PNG'; }
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
  if (elements.resOrbits) elements.resOrbits.value = String(state.resonance?.orbits ?? 15);
  if (elements.resDays) elements.resDays.value = String(state.resonance?.rotations ?? 1);
  if (elements.linkDirection) {
    elements.linkDirection.value = state.linkBudget?.linkDirection ?? 'downlink';
  }
  if (elements.patFadingModel) {
    elements.patFadingModel.value =
      (state.linkBudget?.patFadingEnabled ?? true) ? 'rayleigh' : 'deterministic';
  }
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
  updateViewMode(state.viewMode ?? '3d');
  populateMapStyleOptions(currentMapStyle);
  if (elements.stationVisibility) elements.stationVisibility.value = stationDisplay.mode;
  if (elements.stationHideNames) elements.stationHideNames.checked = !stationDisplay.labels;
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
  resonancePanel.refresh();
  if (elements.stationPickOnMap) {
    elements.stationPickOnMap.dataset.active = 'false';
    elements.stationPickOnMap.textContent = 'Pick on map';
  }
  stationDialog.updateStationPickHint();
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
    // Link Budget slider pairs
    ['atmZenithAod', 'atmZenithAodSlider', (value) => clamp(Number(value), 0, 10), 'linkBudget.atmZenithAod'],
    ['atmZenithAbs', 'atmZenithAbsSlider', (value) => clamp(Number(value), 0, 10), 'linkBudget.atmZenithAbs'],
    ['pointingErrorUrad', 'pointingErrorUradSlider', (value) => clamp(Number(value), 0, 50), 'linkBudget.pointingErrorUrad'],
    ['fixedOpticsLoss', 'fixedOpticsLossSlider', (value) => clamp(Number(value), 0, 20), 'linkBudget.fixedOpticsLoss'],
    ['scintillationP0', 'scintillationP0Slider', (value) => clamp(Number(value), 0.001, 0.5), 'linkBudget.scintillationP0'],
    ['bgFovMrad', 'bgFovMradSlider', (value) => clamp(Number(value), 0.01, 10), 'linkBudget.bgFovMrad'],
    ['bgDeltaLambda', 'bgDeltaLambdaSlider', (value) => clamp(Number(value), 0.01, 50), 'linkBudget.bgDeltaLambda'],
    ['sunExclusionDeg', 'sunExclusionDegSlider', (value) => clamp(Number(value), 0, 90), 'linkBudget.sunExclusionDeg'],
    ['minElevationDeg', 'minElevationDegSlider', (value) => clamp(Number(value), 0, 90), 'linkBudget.minElevationDeg'],
    ['txPowerDbm', 'txPowerDbmSlider', (value) => clamp(Number(value), -30, 60), 'linkBudget.txPowerDbm'],
    ['rxSensitivityDbm', 'rxSensitivityDbmSlider', (value) => clamp(Number(value), -120, 0), 'linkBudget.rxSensitivityDbm'],
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
        // A path may be "section.field" or a bare top-level "field"
        // (samplesPerOrbit).  Destructuring [section, field] straight off the
        // split left `field` undefined for the bare case, so the else branch
        // wrote draft[undefined] and the control silently did nothing.
        const parts = path.split('.');
        const field = parts.pop();
        const section = parts.pop() || null;
        const valueToAssign = Number.isFinite(numericValue) ? numericValue : normalized;
        if (section === 'orbital') draft.orbital[field] = valueToAssign;
        else if (section === 'optical') draft.optical[field] = valueToAssign;
        else if (section === 'resonance') draft.resonance[field] = valueToAssign;
        else if (section === 'linkBudget') draft.linkBudget[field] = valueToAssign;
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

  elements.j3Toggle?.addEventListener('change', async (event) => {
    mutate((draft) => {
      draft.orbital.j3Enabled = event.target.checked;
    });
    await recomputeOrbit(true);
  });

  elements.j4Toggle?.addEventListener('change', async (event) => {
    mutate((draft) => {
      draft.orbital.j4Enabled = event.target.checked;
    });
    await recomputeOrbit(true);
  });

  // ── Link Budget checkbox & input handlers ─────────────────────────────
  elements.linkDirection?.addEventListener('change', (event) => {
    mutate((draft) => { draft.linkBudget.linkDirection = event.target.value; });
  });
  elements.patFadingModel?.addEventListener('change', async (event) => {
    mutate((draft) => {
      draft.linkBudget.patFadingEnabled = event.target.value === 'rayleigh';
    });
    await recomputeMetricsOnly(true);
  });
  elements.scintillationEnabled?.addEventListener('change', (event) => {
    mutate((draft) => { draft.linkBudget.scintillationEnabled = event.target.checked; });
    if (elements.scintillationFields) {
      elements.scintillationFields.style.opacity = event.target.checked ? '1' : '0.5';
    }
  });
  elements.backgroundEnabled?.addEventListener('change', (event) => {
    mutate((draft) => { draft.linkBudget.backgroundEnabled = event.target.checked; });
    if (elements.backgroundFields) {
      elements.backgroundFields.style.opacity = event.target.checked ? '1' : '0.5';
    }
  });
  elements.bgRadiance?.addEventListener('change', (event) => {
    const val = Math.max(0, Number(event.target.value) || 0);
    mutate((draft) => { draft.linkBudget.bgRadiance = val; });
  });

  // ── SSO panel event handlers ────────────────────────────────────────────
  let _lastSSOResult = null;

  elements.ssoToggle?.addEventListener('change', (event) => {
    const show = event.target.checked;
    if (elements.ssoFields) elements.ssoFields.style.display = show ? '' : 'none';
    if (!show) {
      if (elements.ssoResults) elements.ssoResults.style.display = 'none';
      if (elements.ssoError) elements.ssoError.style.display = 'none';
      _lastSSOResult = null;
    }
  });

  // Sync SSO altitude slider ↔ input
  const ssoAltEl = elements.ssoAltitude;
  const ssoAltSlider = elements.ssoAltitudeSlider;
  if (ssoAltEl && ssoAltSlider) {
    ssoAltEl.addEventListener('change', () => { ssoAltSlider.value = ssoAltEl.value; });
    ssoAltSlider.addEventListener('input', () => { ssoAltEl.value = ssoAltSlider.value; });
  }

  elements.btnComputeSSO?.addEventListener('click', async () => {
    const alt = Number(elements.ssoAltitude?.value ?? 600);
    const ecc = Number(elements.ssoEccentricity?.value ?? 0.001);
    const ltan = Number(elements.ssoLTAN?.value ?? 10.5);
    const epoch = elements.epochInput?.value || null;

    if (elements.ssoError) elements.ssoError.style.display = 'none';
    if (elements.ssoResults) elements.ssoResults.style.display = 'none';

    try {
      const res = await designSSOOrbit(alt, ecc, ltan, epoch);
      _lastSSOResult = res;

      // Populate results table
      if (elements.ssoResInc)    elements.ssoResInc.textContent    = `${res.inclination_deg.toFixed(4)}°`;
      if (elements.ssoResSMA)    elements.ssoResSMA.textContent    = `${res.semi_major_axis_km.toFixed(3)} km`;
      if (elements.ssoResRAAN)   elements.ssoResRAAN.textContent   = `${res.raan_deg.toFixed(4)}°`;
      if (elements.ssoResPeriod) elements.ssoResPeriod.textContent = `${(res.period_seconds / 60).toFixed(2)} min`;
      if (elements.ssoResRevs)   elements.ssoResRevs.textContent   = `${res.revolutions_per_day.toFixed(2)}`;
      if (elements.ssoResDrift)  elements.ssoResDrift.textContent  = `${res.raan_drift_deg_per_day.toFixed(4)} °/day`;
      if (elements.ssoResClass)  elements.ssoResClass.textContent  = res.orbit_class;

      if (elements.ssoResults) elements.ssoResults.style.display = '';
    } catch (err) {
      if (elements.ssoError) {
        elements.ssoError.textContent = err.message || 'SSO computation failed';
        elements.ssoError.style.display = '';
      }
    }
  });

  elements.btnApplySSO?.addEventListener('click', async () => {
    if (!_lastSSOResult) return;
    const r = _lastSSOResult;

    // Apply computed SSO elements to the main orbit controls
    mutate((draft) => {
      draft.orbital.semiMajor = r.semi_major_axis_km;
      draft.orbital.eccentricity = r.eccentricity;
      draft.orbital.inclination = r.inclination_deg;
      draft.orbital.raan = r.raan_deg;
      draft.orbital.argPerigee = r.arg_perigee_deg;
      draft.orbital.meanAnomaly = r.mean_anomaly_deg;
    });

    // Sync UI inputs with the new values
    if (elements.semiMajor)        { elements.semiMajor.value = String(r.semi_major_axis_km); }
    if (elements.semiMajorSlider)  { elements.semiMajorSlider.value = String(r.semi_major_axis_km); }
    if (elements.eccentricity)     { elements.eccentricity.value = String(r.eccentricity); }
    if (elements.eccentricitySlider) { elements.eccentricitySlider.value = String(r.eccentricity); }
    if (elements.inclination)      { elements.inclination.value = String(r.inclination_deg); }
    if (elements.inclinationSlider) { elements.inclinationSlider.value = String(r.inclination_deg); }
    if (elements.raan)             { elements.raan.value = String(r.raan_deg); }
    if (elements.raanSlider)       { elements.raanSlider.value = String(r.raan_deg); }
    if (elements.argPerigee)       { elements.argPerigee.value = String(r.arg_perigee_deg); }
    if (elements.argPerigeeSlider) { elements.argPerigeeSlider.value = String(r.arg_perigee_deg); }
    if (elements.meanAnomaly)      { elements.meanAnomaly.value = String(r.mean_anomaly_deg); }
    if (elements.meanAnomalySlider) { elements.meanAnomalySlider.value = String(r.mean_anomaly_deg); }

    orbitSamplesOverride = null;
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

  elements.panelTabs?.forEach((tab) => {
    tab.addEventListener('click', () => {
      activatePanelSection(tab.dataset.sectionTarget);
    });
  });

  // New sidebar navigation handling
  const sidebarNavItems = document.querySelectorAll('.app-nav .nav-item[data-section]');
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
    // Top-nav layout: the "menu" button toggles the docked parameters panel.
    if (typeof robustTogglePanel === 'function') {
      robustTogglePanel();
    } else if (elements.controlPanel) {
      const collapsed = elements.controlPanel.dataset.collapsed === 'true';
      setPanelCollapsed(!collapsed);
    }
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
                  worker.postMessage({ type: 'propagateBatch', payload: { constellation, timeline: timelineSeconds, epoch: state.epoch, j2Enabled: state.orbital.j2Enabled, j3Enabled: state.orbital.j3Enabled, j4Enabled: state.orbital.j4Enabled } });
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
                    wk.postMessage({ type: 'propagateBatch', payload: { constellation: subset, timeline: timelineSeconds, epoch: state.epoch, j2Enabled: state.orbital.j2Enabled, j3Enabled: state.orbital.j3Enabled, j4Enabled: state.orbital.j4Enabled } });
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
                  j3Enabled: state.orbital.j3Enabled,
                  j4Enabled: state.orbital.j4Enabled,
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

  elements.mapStyleSelect?.addEventListener('change', async (event) => {
    const requested = event.target.value;
    try {
      currentMapStyle = (await setMapStyle(requested)) || requested;
    } catch (error) {
      showToast(`No se pudo cambiar el mapa: ${error.message}`, { type: 'error' });
      currentMapStyle = getMapStyle();
    }
    if (elements.mapStyleSelect.value !== currentMapStyle) {
      elements.mapStyleSelect.value = currentMapStyle;
    }
  });

  elements.stationVisibility?.addEventListener('change', (event) => {
    stationDisplay.mode = event.target.value;
    applyStationDisplay();
  });

  elements.stationHideNames?.addEventListener('change', (event) => {
    stationDisplay.labels = !event.target.checked;
    applyStationDisplay();
  });

  elements.btnExportView?.addEventListener('click', () => exportCurrentView());

  elements.satelliteName?.addEventListener('input', (event) => {
    mutate((draft) => {
      draft.satelliteName = event.target.value;
    });
  });

  elements.epochInput?.addEventListener('change', (event) => {
    mutate((draft) => {
      draft.epoch = event.target.value;
    });
    // Immediately update 3D scene lighting/rotation for the new epoch
    syncSceneToEpoch();
    // Sync irradiance time picker to the new epoch
    if (elements.irradianceTime) elements.irradianceTime.value = event.target.value.slice(0, 16);
  });

  elements.resonanceToggle?.addEventListener('change', (event) => {
    void resonancePanel.setEnabled(event.target.checked);
  });
  const onResonanceInput = () => {
    if (state.resonance?.enabled) void resonancePanel.apply();
    else resonancePanel.updateSummary();
  };
  elements.resOrbits?.addEventListener('change', onResonanceInput);
  elements.resDays?.addEventListener('change', onResonanceInput);

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

  elements.btnFetchIrradiance?.addEventListener('click', () => {
    void irradiance.fetchIrradiance();
  });

  // ── Pass time over OGS ────────────────────────────────────────────────
  // Sync zenith threshold slider ↔ input
  const syncPassZenith = (val) => {
    const v = Math.max(0, Math.min(90, Number(val) || 70));
    if (elements.passZenithThreshold) elements.passZenithThreshold.value = v;
    if (elements.passZenithThresholdSlider) elements.passZenithThresholdSlider.value = v;
  };
  elements.passZenithThreshold?.addEventListener('change', (e) => syncPassZenith(e.target.value));
  elements.passZenithThresholdSlider?.addEventListener('input', (e) => syncPassZenith(e.target.value));

  elements.btnComputePassTime?.addEventListener('click', () => {
    modalGraphs.computePassTime();
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

  // PCFLOS Fetch button handler
  document.getElementById('pcflosFetchBtn')?.addEventListener('click', () => {
    qkdRelay.fetchPCFLOS();
  });

  // Relay Run button handler
  document.getElementById('relayRunBtn')?.addEventListener('click', () => {
    qkdRelay.runRelay();
  });

  // QKD Calculate button handler
  elements.btnCalculateQKD?.addEventListener('click', () => {
    logCheckpoint('QKD Calculate button clicked');
    try {
      const { logInfo, validateNumber } = require('utils');
      
      // Get current link loss from computed metrics at current time index
      const metricsData = state.computed?.metrics;
      const timeIndex = state.time?.index ?? 0;
      let currentLoss = 0;
      if (metricsData?.totalLossDb?.length > timeIndex) {
        currentLoss = metricsData.totalLossDb[timeIndex] || 0;
      } else if (metricsData?.lossDb?.length > timeIndex) {
        currentLoss = metricsData.lossDb[timeIndex] || 0;
      }
      
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

  // SKR time-series computation button
  elements.btnQKDSeries?.addEventListener('click', () => {
    void qkdRelay.computeQKDTimeSeries();
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
    console.log('[Play] Button clicked, setting playing=true');
    playbackLoop.lastTimestamp = null;
    togglePlay(true);
    console.log('[Play] state.time.playing:', state.time.playing);
    console.log('[Play] timeline length:', state.time.timeline?.length || 0);
  });
  elements.btnPause?.addEventListener('click', () => {
    console.log('[Pause] Button clicked, setting playing=false');
    togglePlay(false);
  });
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
      // "fullscreen" is a layout mode, not a projection — remember the last
      // real projection so an export made in fullscreen is still named right.
      if (mode === '2d' || mode === '3d') currentProjection = mode;
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
      modalGraphs.showModalGraph(target.dataset.graphId);
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

  // Link Margin Study dialog handlers
  elements.btnLinkMarginStudy?.addEventListener('click', modalGraphs.showLinkMarginStudy);
  elements.closeLinkMarginDialog?.addEventListener('click', () => {
    elements.linkMarginDialog?.close();
  });
  elements.resetLmZoom?.addEventListener('click', () => {
    if (window._lmStudyCharts) {
      window._lmStudyCharts.forEach(c => plotlyResetZoom(c));
    }
  });

  // Paper (Ntanos 2021) reproduction panel
  document.getElementById('btnPaperApply')?.addEventListener('click', () => paperFigures.applyPreset());
  document.querySelectorAll('.btn-paper-fig').forEach((btn) => {
    btn.addEventListener('click', () => paperFigures.show(btn.dataset.fig));
  });
  document.getElementById('closePaperDialog')?.addEventListener('click', () => {
    document.getElementById('paperDialog')?.close();
  });
  paperFigures.loadPreset();

  // ── QKD → Advanced Analysis: dim the dependent fields when a block is off ──
  // The values are still read from the DOM at request time only when the box is
  // checked (solve_payload.js), so dimming is purely a legibility cue.
  const advancedBlocks = [
    ['temporalGatingEnabled', 'temporalGatingFields'],
    ['finiteKeyEnabled', 'finiteKeyFields'],
    ['availabilityEnabled', 'availabilityFields'],
    ['monteCarloEnabled', 'monteCarloFields'],
  ];
  advancedBlocks.forEach(([toggleId, fieldsId]) => {
    const toggle = elements[toggleId];
    const fields = elements[fieldsId];
    if (!toggle || !fields) return;
    const sync = () => { fields.style.opacity = toggle.checked ? '1' : '0.5'; };
    toggle.addEventListener('change', sync);
    sync();
  });
  // The threshold cutoff belongs to the threshold estimator only; the
  // expectation estimator has no threshold at all, so showing an active-looking
  // input beside it invites reporting a number that was never used.
  const syncEstimator = () => {
    const isThreshold = elements.availabilityEstimator?.value === 'threshold';
    if (elements.cloudThresholdPct) {
      elements.cloudThresholdPct.disabled = !isThreshold;
      elements.cloudThresholdPct.parentElement.style.opacity = isThreshold ? '1' : '0.45';
    }
  };
  elements.availabilityEstimator?.addEventListener('change', syncEstimator);
  syncEstimator();

  // ── Constellation study panel ─────────────────────────────────────────────
  elements.btnRunStudy?.addEventListener('click', () => studyPanel.run());
  elements.btnShowStudyResults?.addEventListener('click', () => studyPanel.showLast());
  elements.btnStudySelectEurope?.addEventListener('click', () => studyPanel.selectEurope());
  elements.btnStudySelectAll?.addEventListener('click', () => studyPanel.selectAll());
  elements.btnStudyClearSel?.addEventListener('click', () => studyPanel.clearSelection());
  elements.closeStudyDialog?.addEventListener('click', () => elements.studyDialog?.close());

  // Reset zoom button (Plotly double-click already autoscales)
  elements.resetZoomBtn?.addEventListener('click', () => {
    modalGraphs.resetModalZoom();
  });

  if (elements.stationDialog) {
    const dragHandle = elements.stationDialog.querySelector('.dialog-drag-handle');
    dragHandle?.addEventListener('pointerdown', (event) => {
      if (event.button !== 0) return;
      stationDialog.beginStationDialogDrag(event);
    });
    elements.stationDialog.addEventListener('submit', async (event) => {
      event.preventDefault();
      await stationDialog.saveStationFromDialog();
    });
  }

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && elements.stationDialog?.open) {
      event.preventDefault();
      elements.stationDialog.close('cancelled');
    }
  });

  elements.btnAddStation?.addEventListener('click', () => {
    stationDialog.setStationPickMode(false);
    stationDialog.updateStationPickHint();
    stationDialog.openStationDialog();
  });

  elements.btnDeleteStation?.addEventListener('click', async () => {
    const station = getSelectedStation();
    if (!station) return;
    if (station.builtin) {
      window.alert('Built-in stations cannot be deleted.');
      return;
    }
    const confirmed = window.confirm(`Remove the station "${station.name}"?`);
    if (!confirmed) return;
    await deleteStationRemote(station.id);
  });

  if (elements.stationDialog && elements.stationSave) {
    elements.stationDialog.addEventListener('close', () => {
      stationDialog.setStationPickMode(false);
      if (elements.stationName) elements.stationName.value = '';
      if (elements.stationLat) elements.stationLat.value = '';
      if (elements.stationLon) elements.stationLon.value = '';
      if (elements.stationAltitude) elements.stationAltitude.value = '0';
      stationDialog.resetStationDialogPosition();
      stationDialog.updateStationPickHint();
      stationDialog.endStationDialogDrag();
    });

    elements.stationCancel?.addEventListener('click', () => {
      elements.stationDialog.close('cancelled');
    });

    elements.stationPickOnMap?.addEventListener('click', () => {
      const isActive = elements.stationPickOnMap.dataset.active === 'true';
      stationDialog.setStationPickMode(!isActive);
    });

    elements.stationLat?.addEventListener('input', stationDialog.syncStationPickHintFromInputs);
    elements.stationLon?.addEventListener('input', stationDialog.syncStationPickHintFromInputs);

    elements.stationSave.addEventListener('click', async (event) => {
      event.preventDefault();
      await stationDialog.saveStationFromDialog();
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
  const selectedStation = list.find((s) => s.id === selectedId);
  const isBuiltin = selectedStation?.builtin ?? false;
  elements.stationSelect.disabled = !hasStations;
  if (elements.btnDeleteStation) {
    elements.btnDeleteStation.disabled = !hasSelection || isBuiltin;
    elements.btnDeleteStation.title = isBuiltin ? 'Built-in stations cannot be deleted' : 'Remove the selected station';
  }
  if (elements.btnFocusStation) {
    elements.btnFocusStation.disabled = !hasSelection;
  }
  // Also populate relay station dropdowns
  qkdRelay.populateRelaySelects();
  // …and the constellation-study network selector (keeps its own selection).
  studyPanel.populateStations();
}

function orbitSignature(snapshot) {
  return JSON.stringify({
    orbital: snapshot.orbital,
    resonance: snapshot.resonance,
    samplesPerOrbit: snapshot.samplesPerOrbit,
    sceneMode: snapshot.sceneMode,
    helio: snapshot.helio,
  });
}

function metricsSignature(snapshot) {
  return JSON.stringify({
    optical: snapshot.optical,
    linkBudget: snapshot.linkBudget,
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
  const timeline = state.time.timeline ?? [];
  if (!timeline.length) return;
  const index = clamp(state.time.index, 0, timeline.length - 1);
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
let _helioRecomputeInProgress = false;
let _helioRecomputePromise = null;
async function recomputeHelioTimeline() {
  if (_helioRecomputeInProgress) return _helioRecomputePromise;
  _helioRecomputeInProgress = true;
  _helioRecomputePromise = (async () => {
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

    // ── 1. Dense orbit path for the 3D visual ───────────────────────────
    // Helio timeline offsets are typically sparse (e.g. 1 h apart).  For a
    // ~90 min LEO orbit that means < 2 samples per revolution, producing a
    // criss-crossing zigzag.  Generate ~180 pts / orbit so the orbit ring
    // is smooth.
    const probeResult = orbit.propagateOrbitAtTimes(state, [0, 1]);
    const period = probeResult.orbitPeriod;               // seconds
    const pathStep = Math.max(1, period / 180);
    const totalInterval = totalSeconds || 1;
    const denseCount = Math.min(8000, Math.ceil(totalInterval / pathStep) + 1);
    const denseOffsets = [];
    for (let i = 0; i < denseCount; i++) denseOffsets.push(i * pathStep);
    const denseResult = orbit.propagateOrbitAtTimes(state, denseOffsets);

    // ── 2. Helio-offset propagation for satellite tracking / metrics ────
    const helioResult = orbit.propagateOrbitAtTimes(state, offsets);

    const station = getSelectedStation();
    const metrics = orbit.computeStationMetrics(
      helioResult.dataPoints, station, state.optical, state, null,
    );

    // ── 3. Compute TLE constellation positions for helio timeline ─────
    let constellationPositions = state.computed?.constellationPositions ?? {};
    if (hasActiveConstellations() && window.satellite) {
      const datasets = getActiveConstellationDatasets();
      if (datasets.length) {
        constellationPositions = computeConstellationPositions(
          offsets, state.epoch, datasets,
        );
      }
    }

    // ── 4. Apply visuals BEFORE state mutations ─────────────────────────
    // setTimeline / setComputed trigger synchronous emit() → onStateChange
    // which may call scheduleVisualUpdate.  Updating the orbit path first
    // ensures the displayed line is up-to-date before any re-render.
    updateEarthOrbitPath(data.earth_pos_eci_au);
    updateOrbitPath(denseResult.dataPoints, { smooth: false });
    updateGroundTrackSurface(helioResult.groundTrack);
    setTimeline({ timeline: offsets, totalSeconds });
    setComputed({
      ...state.computed,
      dataPoints: helioResult.dataPoints,
      groundTrack: helioResult.groundTrack,
      metrics,
      constellationPositions,
    });
    lastConstellationIndex = -1;

    // Also fetch solar data for lighting
    clearSolarData();
    const solarData = await fetchSolarData(state.epoch, offsets);
    if (solarData) scheduleVisualUpdate();
  } catch (err) {
    console.error('[helio] Failed to fetch scene timeline:', err);
  } finally {
    _helioRecomputeInProgress = false;
  }
  })();
  return _helioRecomputePromise;
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
    lastOrbitSignature = orbitSignature(state);
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
    lastOrbitSignature = orbitSignature(state);
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
  // Draw the orbit FIRST so a panel/readout error can never block rendering.
  updateOrbitPath(orbitData.dataPoints);
  updateGroundTrackSurface(orbitData.groundTrack);
  frameOrbitView(orbitData.dataPoints, { force: !hasSceneBeenFramed });
  // When resonance is active the semi-major axis is derived; mirror the solved
  // value into the (now read-only) input and refresh the panel readout.
  try {
    if (state.resonance?.enabled && orbitData.resonance?.applied) {
      const aDerived = Number(Number(orbitData.semiMajor).toFixed(3));
      state.orbital.semiMajor = aDerived;
      if (!elements.semiMajor?.matches?.(':focus')) {
        syncPairValue('semiMajor', 'semiMajorSlider', aDerived);
      }
    }
    resonancePanel.updateSummary();
  } catch (err) {
    console.error('Resonance panel update failed', err);
  }
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
    // Fall through to render satellite / 2D map updates
  }

  // Single orbit (or helio mode with propagated satellite data)
  const isHelio = state.sceneMode === 'helio';
  if (dataPoints && dataPoints.length > 0) {
    const current = dataPoints[index];

    // In helio mode, Earth rotation & solar lighting are already set above
    if (!isHelio) {
      setEarthRotationFromTime(current.gmst ?? 0);

      // ── Solar lighting update (from backend data) ──────────────────────
      const solarData = getSolarData();
      if (solarData) {
        updateSolarFromBackend(index, solarData);
      } else {
        // Fallback: approximate sun direction from epoch + current offset
        const epochMs = new Date(state.epoch).getTime();
        const t = state.time.timeline?.[index] ?? 0;
        const nowDate = new Date(epochMs + t * 1000);
        const [ex, ey, ez] = approxSunDirEci(nowDate);
        updateSolarLighting(ex, ez, -ey);
      }
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
    // If no single-orbit data, drive Earth rotation + sun from constellation GMST
    if (!dataPoints || !dataPoints.length) {
      const posMap = state.computed?.constellationPositions ?? {};
      const firstGroup = Object.values(posMap)[0];
      const firstSat = firstGroup?.satellites?.[0];
      const snap = firstSat?.timeline?.[index];
      if (snap?.gmst != null) {
        setEarthRotationFromTime(snap.gmst);
      }
      // Approximate sun direction for this timestep
      const epochMs = new Date(state.epoch).getTime();
      const t = state.time.timeline?.[index] ?? 0;
      if (!Number.isNaN(epochMs)) {
        const [ex, ey, ez] = approxSunDirEci(new Date(epochMs + t * 1000));
        updateSolarLighting(ex, ez, -ey);
      }
    }
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
    if (elements.geoLossMetric) elements.geoLossMetric.textContent = '--';
    if (elements.atmLossMetric) elements.atmLossMetric.textContent = '--';
    if (elements.pointingLossMetric) elements.pointingLossMetric.textContent = '--';
    if (elements.scintLossMetric) elements.scintLossMetric.textContent = '--';
    if (elements.fixedLossMetric) elements.fixedLossMetric.textContent = '--';
    if (elements.totalLossMetric) elements.totalLossMetric.textContent = '--';
    if (elements.bgNoiseMetric) elements.bgNoiseMetric.textContent = '--';
    if (elements.couplingMetric) elements.couplingMetric.textContent = '--';
    if (elements.sunAngleMetric) elements.sunAngleMetric.textContent = '--';
    if (elements.eclipseMetric) elements.eclipseMetric.textContent = '--';
    if (elements.sunExcludedMetric) elements.sunExcludedMetric.textContent = '--';
    if (elements.rxPowerMetric) elements.rxPowerMetric.textContent = '--';
    if (elements.linkMarginMetric) elements.linkMarginMetric.textContent = '--';
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

  // ── Link Budget component metrics ─────────────────────────────────────
  const geoLoss = valueFromSeries(metrics.geoLossDb, index, null);
  const atmLoss = valueFromSeries(metrics.atmLossDb, index, null);
  const ptLoss = valueFromSeries(metrics.pointingLossDb, index, null);
  const scLoss = valueFromSeries(metrics.scintLossDb, index, null);
  const fxLoss = valueFromSeries(metrics.fixedLossDb, index, null);
  const totLoss = valueFromSeries(metrics.totalLossDb, index, null);
  const bgNoise = valueFromSeries(metrics.backgroundCps, index, null);
  const coupling = valueFromSeries(metrics.couplingTotal, index, null);
  const fmtDb = (v) => (v != null && Number.isFinite(v)) ? v.toFixed(2) + ' dB' : '--';
  if (elements.geoLossMetric) elements.geoLossMetric.textContent = fmtDb(geoLoss);
  if (elements.atmLossMetric) elements.atmLossMetric.textContent = fmtDb(atmLoss);
  if (elements.pointingLossMetric) elements.pointingLossMetric.textContent = fmtDb(ptLoss);
  if (elements.scintLossMetric) elements.scintLossMetric.textContent = fmtDb(scLoss);
  if (elements.fixedLossMetric) elements.fixedLossMetric.textContent = fmtDb(fxLoss);
  if (elements.totalLossMetric) elements.totalLossMetric.textContent = fmtDb(totLoss);
  if (elements.bgNoiseMetric) elements.bgNoiseMetric.textContent = (bgNoise != null && Number.isFinite(bgNoise)) ? bgNoise.toFixed(0) + ' cps' : '--';
  if (elements.couplingMetric) elements.couplingMetric.textContent = (coupling != null && Number.isFinite(coupling)) ? (coupling * 100).toFixed(4) + ' %' : '--';

  // Sun / eclipse / link margin metrics
  const sunAngle = valueFromSeries(metrics.sunCoreAngleDeg, index, null);
  const eclipsed = metrics.eclipsed?.[index];
  const sunExcl = metrics.sunExcluded?.[index];
  const rxPwr = valueFromSeries(metrics.rxPowerDbm, index, null);
  const lnkMargin = valueFromSeries(metrics.linkMarginDb, index, null);
  if (elements.sunAngleMetric) elements.sunAngleMetric.textContent = (sunAngle != null && Number.isFinite(sunAngle)) ? sunAngle.toFixed(1) + '°' : '--';
  if (elements.eclipseMetric) elements.eclipseMetric.textContent = eclipsed != null ? (eclipsed ? 'Yes' : 'No') : '--';
  if (elements.sunExcludedMetric) elements.sunExcludedMetric.textContent = sunExcl != null ? (sunExcl ? '⚠ Yes' : 'No') : '--';
  if (elements.rxPowerMetric) elements.rxPowerMetric.textContent = (rxPwr != null && Number.isFinite(rxPwr)) ? rxPwr.toFixed(1) + ' dBm' : '--';
  if (elements.linkMarginMetric) elements.linkMarginMetric.textContent = (lnkMargin != null && Number.isFinite(lnkMargin)) ? lnkMargin.toFixed(1) + ' dB' : '--';

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
    updateOrbitPath([]);
    updateGroundTrackSurface([]);
    updateGroundTrack([]);
    updateSatellite(null);
    updateSatellitePosition(null);
    updateGroundTrackVector(null);
    updateLinkLine(null, null);
    updateLink3D(null, null);
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
  try {
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

    const isHelio = state.sceneMode === 'helio';
    const satellites = [];
    for (let index = 0; index < constellationElements.length; index++) {
        const satElements = constellationElements[index];
        const satSettings = {
            ...state,
            orbital: satElements,
            resonance: { enabled: false },
        };
        let dataPoints;
        if (isHelio) {
            // In helio mode, propagate at the helio timeline offsets so
            // per-satellite timelines align with state.time.timeline.
            const result = orbit.propagateOrbitAtTimes(satSettings, timeline);
            dataPoints = result.dataPoints;
        } else {
            const orbitData = orbit.propagateOrbit(satSettings, { samplesPerOrbit: DRAFT_SAMPLES_PER_ORBIT });
            dataPoints = orbitData.dataPoints;
        }
        satellites.push({
            id: `walker-${index}`,
            name: `W-${index}`,
            timeline: dataPoints,
        });
    }
    
    mutate((draft) => {
        draft.computed.customConstellation = {
            id: 'customWalker',
            color: '#f59e0b',
            satellites,
        };
    });
    // Force an immediate visual update so the constellation is rendered
    // without relying on the onStateChange → scheduleVisualUpdate chain
    // (which may be short-circuited by signature checks).
    scheduleVisualUpdate();
    setConstellationStatusMessage(`Rendered ${constellationElements.length} satellite constellation.`, 'ready');
  } catch (err) {
    console.error('[plotWalkerConstellation] Error:', err);
    setConstellationStatusMessage(`Error plotting constellation: ${err.message}`, 'error');
  }
}

function playbackLoop(timestamp) {
  const timeline = state.time.timeline;
  const playing = state.time.playing;
  
  // Debug: log the check values
  if (playing && timeline.length > 0 && !playbackLoop._hasLoggedStart) {
    console.log('[PlaybackLoop] Check - playing:', playing, 'timeline.length:', timeline.length);
    playbackLoop._hasLoggedStart = true;
  }
  
  if (!playing || timeline.length === 0) {
    playbackLoop.lastTimestamp = timestamp;
    playbackLoop.simulatedTime = timeline[state.time.index] ?? 0;
    playbackLoop._hasLoggedStart = false;  // Reset flag when paused
    playingRaf = requestAnimationFrame(playbackLoop);
    return;
  }

  if (!Number.isFinite(playbackLoop.lastTimestamp)) {
    playbackLoop.lastTimestamp = timestamp;
    console.log('[PlaybackLoop] Starting playback, initial timestamp:', timestamp);
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
    if (nextIndex % 10 === 0) {  // Log every 10th index change
      console.log('[PlaybackLoop] Index changed to', nextIndex, '/', timeline.length - 1);
    }
  }

  playingRaf = requestAnimationFrame(playbackLoop);
}

function updateUtcClock(snapshot) {
  if (!elements.utcClockDate || !elements.utcClockTime) return;
  // Treat epoch string as UTC (backend _parse_iso does the same: naive strings → UTC)
  const epochStr = /[Z+]/.test(snapshot.epoch) ? snapshot.epoch : snapshot.epoch + 'Z';
  const epochMs = new Date(epochStr).getTime();
  if (Number.isNaN(epochMs)) return;
  const timeline = snapshot.time.timeline;
  const index = snapshot.time.index;
  const offsetS = (Array.isArray(timeline) && timeline.length) ? (timeline[index] ?? 0) : 0;
  const d = new Date(epochMs + offsetS * 1000);
  const pad = (n) => String(n).padStart(2, '0');
  elements.utcClockDate.textContent =
    `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())}`;
  elements.utcClockTime.textContent =
    `${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
}

function onStateChange(snapshot) {
  updateUtcClock(snapshot);
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
  if (elements.j3Toggle && !elements.j3Toggle.matches(':focus')) {
    elements.j3Toggle.checked = snapshot.orbital.j3Enabled ?? false;
  }
  if (elements.j4Toggle && !elements.j4Toggle.matches(':focus')) {
    elements.j4Toggle.checked = snapshot.orbital.j4Enabled ?? false;
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
  // Pre-fill irradiance time picker from epoch
  if (elements.irradianceTime && state.epoch) {
    elements.irradianceTime.value = state.epoch.slice(0, 16);
  }
  hasMapBeenFramed = false;
  hasSceneBeenFramed = false;

  mapInstance = initMap(elements.mapContainer);
  await initScene(elements.threeContainer);
  // The basemap can only be installed once the viewer exists. 'satellite' is
  // what ensureViewer already applied, so only a different choice needs work.
  if (currentMapStyle !== 'satellite') {
    try {
      currentMapStyle = (await setMapStyle(currentMapStyle)) || currentMapStyle;
    } catch (e) {
      console.warn('Basemap could not be applied at startup:', e?.message || e);
      currentMapStyle = getMapStyle();
    }
  }
  populateMapStyleOptions(currentMapStyle);
  applyStationDisplay();
  // Sync Earth rotation & sun direction to initial epoch
  syncSceneToEpoch();
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
  modalGraphs.initializeCharts();
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
