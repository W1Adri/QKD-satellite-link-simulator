// ---------------------------------------------------------------------------
// app/static/modal_graphs.js
// ---------------------------------------------------------------------------
// Purpose : Graph-modal + link-margin-study panels. Lazily renders the metric
//           modal chart (SKR/QBER/elevation/… vs time) and the multi-panel FSO
//           link-margin study via Plotly. Also the OGS pass-time computation.
//           Extracted from main.js as a DI factory.
//
// Usage   : const modalGraphs = createModalGraphs({ elements, getSelectedStation });
//           Returns { initializeCharts, computePassTime, showModalGraph,
//             showLinkMarginStudy, resetModalZoom }.
//           `modalChartInstance` is private; resetModalZoom() lets the toolbar
//           reset-zoom handler act on it without exposing the reference.
// ---------------------------------------------------------------------------
import { formatDuration } from './utils.js';
import { state } from './state.js';
import {
  isPlotlyReady, renderModalGraph, renderLinkMarginChart, renderBandChart,
  resizeChart as plotlyResizeChart, resetZoom as plotlyResetZoom,
  destroyChart as plotlyDestroyChart,
} from './plotly_charts.js';

export function createModalGraphs({ elements, getSelectedStation }) {
  let modalChartInstance = null;

function initializeCharts() {
  // Plotly renders lazily on first showModalGraph(); just track the target div
  // so the resize/reset-zoom handlers have a valid reference to act on.
  modalChartInstance = elements.modalChartCanvas || null;
}

// ── Pass time over OGS computation ─────────────────────────────────────
function computePassTime() {
  const timeline = Array.isArray(state.time.timeline) ? state.time.timeline : [];
  const metrics  = state.computed?.metrics ?? {};
  const elevArr  = metrics.elevationDeg ?? [];
  const resultsEl = elements.passTimeResults;

  if (!timeline.length || !elevArr.length) {
    if (resultsEl) resultsEl.style.display = 'none';
    return;
  }

  const maxZenith = Number(elements.passZenithThreshold?.value ?? 70);
  const minElev   = 90 - maxZenith;          // elevation threshold

  let totalTime   = 0;   // seconds with LOS
  let passCount   = 0;
  let longestPass = 0;
  let currentPass = 0;
  let inPass      = false;

  for (let i = 0; i < elevArr.length; i++) {
    const elev = elevArr[i];
    // Determine the time step (dt) for this sample
    let dt;
    if (i === 0) {
      dt = timeline.length > 1 ? (timeline[1] - timeline[0]) : 0;
    } else {
      dt = timeline[i] - timeline[i - 1];
    }

    if (elev >= minElev && elev > 0) {
      // Satellite above the zenith-angle threshold and above horizon
      totalTime  += dt;
      currentPass += dt;
      if (!inPass) { passCount++; inPass = true; }
    } else {
      if (inPass) {
        longestPass = Math.max(longestPass, currentPass);
        currentPass = 0;
        inPass = false;
      }
    }
  }
  // Close a pass that extends to the end of the timeline
  if (inPass) {
    longestPass = Math.max(longestPass, currentPass);
  }

  // Display results
  if (resultsEl) resultsEl.style.display = '';
  if (elements.passTimeTotalMetric)   elements.passTimeTotalMetric.textContent   = formatDuration(totalTime);
  if (elements.passTimeCountMetric)   elements.passTimeCountMetric.textContent   = String(passCount);
  if (elements.passTimeLongestMetric)  elements.passTimeLongestMetric.textContent = formatDuration(longestPass);
}

function openModal() {
  const modal = elements.graphModal;
  if (!(modal instanceof HTMLDialogElement)) return;
  if (!modal.open) modal.showModal();
  requestAnimationFrame(() => {
    plotlyResizeChart(modalChartInstance);
  });
}

/**
 * Monte Carlo confidence band over the pass (graph id `skrBand`).
 *
 * Drawn from the backend quantile series, on the BACKEND timeline — the client
 * timeline has a different sample count, and silently reusing it would slide the
 * band against the curve it is supposed to bracket.
 */
function showSkrBand() {
  const metrics = state.computed?.metrics ?? {};
  const keys = Array.isArray(metrics.mcQuantileKeys) ? metrics.mcQuantileKeys : [];
  const labels = (metrics.skrTimeline ?? []).map(
    (v) => (Number.isFinite(v) ? Number(v.toFixed(1)) : null));
  if (keys.length < 2 || !labels.length) {
    elements.graphModalTitle.textContent = 'SKR confidence band — no Monte Carlo data';
    renderModalGraph(modalChartInstance, {
      labels: [], values: [], color: '#0369a1',
      yLabel: 'SKR (kbps)', xLabel: 'Time offset (s)',
    });
    openModal();
    return;
  }
  // Lowest percentile = lower edge, highest = upper edge, P50 (or the middle
  // one) = median.  Read off the requested band rather than assuming 5/50/95.
  const pctOfKey = (k) => Number(k.slice(8));
  const lowKey = keys[0];
  const highKey = keys[keys.length - 1];
  const midKey = keys.find((k) => pctOfKey(k) === 50) ?? keys[Math.floor(keys.length / 2)];
  const pick = (k) => labels.map((_, i) => {
    const v = (metrics[k] ?? [])[i];
    return Number.isFinite(v) ? v : null;
  });

  elements.graphModalTitle.textContent =
    `SKR P${pctOfKey(lowKey)}–P${pctOfKey(highKey)} band vs Time`;
  renderBandChart(modalChartInstance, {
    labels,
    lower: pick(lowKey),
    median: pick(midKey),
    upper: pick(highKey),
    deterministic: pick('skrKbps'),
    xLabel: 'Time offset (s)',
    yLabel: 'SKR (kbps)',
    bandName: `P${pctOfKey(lowKey)}–P${pctOfKey(highKey)}`,
    medianName: `Median (P${pctOfKey(midKey)})`,
    deterministicName: 'Deterministic (p0 margin)',
  });
  openModal();
}

function showModalGraph(graphId) {
  if (!modalChartInstance || !elements.graphModal || !elements.graphModalTitle) return;
  if (graphId === 'skrBand') return showSkrBand();
  const timeline = Array.isArray(state.time.timeline) ? state.time.timeline : [];
  const metrics = state.computed?.metrics ?? {};
  if (!timeline.length || !metrics) return;

  const graphConfig = {
    loss: {
      data: metrics.lossDb ?? [],
      title: 'Loss vs Time',
      yLabel: 'Geometric loss (dB)',
      color: '#00f0ff',
    },
    elevation: {
      data: metrics.elevationDeg ?? [],
      title: 'Elevation vs Time',
      yLabel: 'Station elevation (Â°)',
      color: '#38bdf8',
    },
    distance: {
      data: metrics.distanceKm ?? [],
      title: 'Range vs Time',
      yLabel: 'Satellite-ground range (km)',
      color: '#4ade80',
    },
    r0: {
      data: metrics.r0_array ?? [],
      title: 'Fried parameter (r0)',
      yLabel: 'r0 (m)',
      color: '#fbbf24',
      datasetLabel: 'r0 (m)',
    },
    fG: {
      data: metrics.fG_array ?? [],
      title: 'Greenwood frequency (fG)',
      yLabel: 'fG (Hz)',
      color: '#22d3ee',
      datasetLabel: 'fG (Hz)',
    },
    theta0: {
      data: metrics.theta0_array ?? [],
      title: 'Isoplanatic angle (theta0)',
      yLabel: 'theta0 (arcsec)',
      color: '#34d399',
      datasetLabel: 'theta0 (arcsec)',
    },
    wind: {
      data: metrics.wind_array ?? [],
      title: 'RMS wind speed',
      yLabel: 'Wind (m/s)',
      color: '#fbbf24',
      datasetLabel: 'Wind (m/s)',
    },
    // Link Budget graphs
    totalLoss: {
      data: metrics.totalLossDb ?? [],
      title: 'Total Link Loss vs Time',
      yLabel: 'Total loss (dB)',
      color: '#ff4444',
      datasetLabel: 'Total loss (dB)',
    },
    atmLoss: {
      data: metrics.atmLossDb ?? [],
      title: 'Atmospheric Loss vs Time',
      yLabel: 'Atm loss (dB)',
      color: '#a78bfa',
      datasetLabel: 'Atm loss (dB)',
    },
    pointingLoss: {
      data: metrics.pointingLossDb ?? [],
      title: 'Pointing Loss vs Time',
      yLabel: 'Pointing loss (dB)',
      color: '#f472b6',
      datasetLabel: 'Pointing loss (dB)',
    },
    scintLoss: {
      data: metrics.scintLossDb ?? [],
      title: 'Scintillation Loss vs Time',
      yLabel: 'Scintillation loss (dB)',
      color: '#2dd4bf',
      datasetLabel: 'Scintillation loss (dB)',
    },
    backgroundNoise: {
      data: metrics.backgroundCps ?? [],
      title: 'Background Noise vs Time',
      yLabel: 'Background (cps)',
      color: '#fb923c',
      datasetLabel: 'Background noise (cps)',
    },
    sunAngle: {
      data: metrics.sunCoreAngleDeg ?? [],
      title: 'Sun-Core Angle vs Time',
      yLabel: 'Sun-core angle (Â°)',
      color: '#ffd500',
      datasetLabel: 'Sun-core angle (Â°)',
    },
    rxPower: {
      data: metrics.rxPowerDbm ?? [],
      title: 'Received Power vs Time',
      yLabel: 'Rx power (dBm)',
      color: '#00ff88',
      datasetLabel: 'Rx power (dBm)',
    },
    linkMargin: {
      data: metrics.linkMarginDb ?? [],
      title: 'Link Margin vs Time',
      yLabel: 'Link margin (dB)',
      color: '#ff2c9f',
      datasetLabel: 'Link margin (dB)',
    },
    // ── QKD time-series graphs (populated after computeQKDTimeSeries()) ──
    skrTime: {
      data: metrics.skrKbps ?? [],
      title: 'Secure Key Rate vs Time',
      yLabel: 'SKR (kbps)',
      color: '#22ff88',
      customLabels: metrics.skrTimeline ?? [],   // backend timeline alignment
      xLabel: 'Time offset (s)',
      datasetLabel: 'Secure Key Rate (kbps)',
    },
    qberTime: {
      data: metrics.qberPct ?? [],
      title: 'QBER vs Time',
      yLabel: 'QBER (%)',
      color: '#ff8800',
      customLabels: metrics.skrTimeline ?? [],   // backend timeline alignment
      xLabel: 'Time offset (s)',
      datasetLabel: 'QBER (%)',
    },
    skrVsElevation: {
      data: metrics.skrKbps ?? [],
      title: 'SKR vs Elevation Angle',
      yLabel: 'SKR (kbps)',
      color: '#22ff88',
      // Use backend-aligned elevation (same propagation as SKR computation)
      customLabels: metrics.skrElevationDeg ?? [],
      xLabel: 'Elevation (°)',
      datasetLabel: 'Secure Key Rate (kbps)',
    },
    outageTime: {
      // Fraction of channel realizations delivering zero key at each instant —
      // i.i.d. per sample, so this is a fraction of independent instants and
      // says nothing about how LONG a fade lasts.
      data: (metrics.outageProbability ?? []).map(
        (v) => (Number.isFinite(v) ? v * 100 : null)),
      title: 'Monte Carlo Outage Probability vs Time',
      yLabel: 'Outage (%)',
      color: '#c2410c',
      customLabels: metrics.skrTimeline ?? [],   // backend timeline alignment
      xLabel: 'Time offset (s)',
      datasetLabel: 'Outage probability (%)',
    },
    skrVsDistance: {
      data: metrics.skrKbps ?? [],
      title: 'SKR vs Slant Range',
      yLabel: 'SKR (kbps)',
      color: '#4ade80',
      // Use backend-aligned distance (same propagation as SKR computation)
      customLabels: metrics.skrDistanceKm ?? [],
      xLabel: 'Slant range (km)',
      datasetLabel: 'Secure Key Rate (kbps)',
    },
  };

  const config = graphConfig[graphId];
  if (!config) return;

  const labels = config.customLabels && config.customLabels.length
    ? config.customLabels.map((v) => (Number.isFinite(v) ? Number(v.toFixed(1)) : null))
    : timeline.map((value) => (Number.isFinite(value) ? Number(value.toFixed(1)) : value));
  const series = Array.isArray(config.data) ? config.data : [];

  const values = labels.map((_, idx) => {
    const raw = series[idx];
    if (!Number.isFinite(raw)) return null;
    if (typeof config.transform === 'function') {
      const transformed = config.transform(raw);
      return Number.isFinite(transformed) ? transformed : null;
    }
    return raw;
  });

  elements.graphModalTitle.textContent = config.title;
  renderModalGraph(modalChartInstance, {
    labels,
    values,
    color: config.color,
    yLabel: config.yLabel,
    xLabel: config.xLabel ?? 'Time (s)',
  });

  openModal();
}

// ── Parametric FSO Link Margin Study ────────────────────────────────────
function showLinkMarginStudy() {
  const dialog = elements.linkMarginDialog;
  const grid = elements.linkMarginGrid;
  if (!isPlotlyReady() || !dialog || !grid) return;

  // ── Current parameters from state ─────────────────────────────────
  const lb = state.linkBudget;
  const opt = state.optical;
  const sma = state.orbital.semiMajor || 6771;
  const satAltKm = Math.max(sma - 6371, 100);
  const station = getSelectedStation();
  const stationAltM = station?.altitude ?? 0;
  const linkDir = lb.linkDirection ?? 'downlink';
  const isUplink = linkDir.toLowerCase() === 'uplink';
  const wavNm = opt.wavelength ?? 810;
  const satAp = opt.satAperture ?? 0.6;
  const gndAp = opt.groundAperture ?? 1.0;
  const txAp = isUplink ? gndAp : satAp;
  const rxAp = isUplink ? satAp : gndAp;
  const peUrad = lb.pointingErrorUrad ?? 0;
  const fixedDb = lb.fixedOpticsLoss ?? 0;
  const aodZ = lb.atmZenithAod ?? 0;
  const absZ = lb.atmZenithAbs ?? 0;
  const scintP0 = lb.scintillationP0 ?? 0.01;
  const txPow = lb.txPowerDbm ?? 30;
  const rxSens = lb.rxSensitivityDbm ?? -90;
  const W = 21;  // HV 5/7 default wind speed (m/s)

  // ── Sweep parameters ──────────────────────────────────────────────
  const elevations = [90, 75, 60, 45, 30, 15, 5];
  const cn0Vals = [];
  for (let exp = -15; exp <= -12; exp += 0.2) cn0Vals.push(Math.pow(10, exp));
  const neonColors = ['#00f0ff', '#00ff88', '#ffd500', '#ff9100', '#ff4444', '#ff2c9f', '#b24bf3'];

  // ── Hufnagel-Valley 5/7 Cn² profile generator ────────────────────
  const hvAlts = [0, 200, 500, 1000, 2000, 5000, 10000, 15000, 20000];
  function hvLayers(cn0sq) {
    return hvAlts.map((h, i) => {
      const t1 = 0.00594 * Math.pow(W / 27, 2) * Math.pow(h * 1e-5, 10) * Math.exp(-h / 1000);
      const cn2 = t1 + 2.7e-16 * Math.exp(-h / 1500) + cn0sq * Math.exp(-h / 100);
      const dh = (i < hvAlts.length - 1) ? hvAlts[i + 1] - h : 5000;
      return { h, cn2, dh };
    });
  }

  // ── Slant range ───────────────────────────────────────────────────
  function slantKm(elevDeg) {
    const el = elevDeg * Math.PI / 180;
    const Re = 6371 + stationAltM / 1000;
    const Rs = 6371 + satAltKm;
    return Math.sqrt(Rs * Rs - Re * Re * Math.cos(el) * Math.cos(el)) - Re * Math.sin(el);
  }

  // ── Inline loss helpers (match simulation.js physics) ─────────────
  function geoLossDb(distKm) {
    const lam = wavNm * 1e-9, dM = distKm * 1000;
    const div = 1.22 * lam / Math.max(txAp, 1e-3);
    const spot = Math.max(div * dM * 0.5, 1e-6);
    const cap = rxAp * 0.5;
    const coup = Math.min(1, (cap / spot) ** 2);
    return -10 * Math.log10(Math.max(coup, 1e-9));
  }

  function atmLossDb(elevDeg) {
    if (elevDeg <= 0) return 0;
    const zenRad = (90 - elevDeg) * Math.PI / 180;
    const am = 1 / Math.max(Math.cos(zenRad), 1e-6);
    return (aodZ + absZ) * am;
  }

  function ptLossDb() {
    if (peUrad <= 0) return 0;
    const lam = wavNm * 1e-9;
    const div = 1.22 * lam / Math.max(txAp, 1e-6);
    const ratio = (peUrad * 1e-6) / div;
    return Math.max(-10 * Math.log10(Math.max(Math.exp(-2 * ratio * ratio), 1e-30)), 0);
  }

  // erfinv (Winitzki + Newton refinement)
  function erfFn(x) {
    const sign = x < 0 ? -1 : 1;
    const t = 1 / (1 + 0.3275911 * Math.abs(x));
    const poly = t * (0.254829592 + t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429))));
    return sign * (1 - poly * Math.exp(-x * x));
  }
  function erfinv(x) {
    const a = 0.147;
    const lnTerm = Math.log(1 - x * x);
    const p1 = 2 / (Math.PI * a) + lnTerm / 2;
    let y = Math.sign(x) * Math.sqrt(Math.sqrt(p1 * p1 - lnTerm / a) - p1);
    const dErf = (2 / Math.sqrt(Math.PI)) * Math.exp(-y * y);
    if (Math.abs(dErf) > 1e-30) y -= (erfFn(y) - x) / dErf;
    return y;
  }

  function scintLossDb(elevDeg, layers) {
    if (!layers || !layers.length) return 0;
    const lam = wavNm * 1e-9;
    const k = 2 * Math.PI / lam;
    const zenRad = (90 - elevDeg) * Math.PI / 180;
    const secZ = 1 / Math.max(Math.cos(zenRad), 1e-6);
    const H_sat = satAltKm * 1000;
    let integral = 0;
    for (const layer of layers) {
      const h = layer.h;
      if (isUplink) {
        const num = (h - stationAltM) * (H_sat - h);
        const den = H_sat - stationAltM;
        const arg = (num > 0 && den > 0) ? num / den : 0;
        integral += layer.cn2 * Math.pow(arg, 5 / 6) * layer.dh;
      } else {
        integral += layer.cn2 * Math.pow(Math.max(h - stationAltM, 0), 5 / 6) * layer.dh;
      }
    }
    const rytov = 2.25 * Math.pow(k, 7 / 6) * Math.pow(secZ, 11 / 6) * integral;
    if (rytov <= 0) return 0;
    const sigmaI2 = Math.exp(rytov) - 1;
    const sigmaI = Math.sqrt(Math.max(sigmaI2, 1e-30));
    const z2 = erfinv(2 * Math.max(Math.min(scintP0, 0.5), 1e-9) - 1);
    const fadeDb = -10 * Math.log10(Math.exp(2 * sigmaI * z2 + sigmaI2));
    return Math.max(fadeDb, 0);
  }

  const pLoss = ptLossDb();

  // ── Compute parametric data ───────────────────────────────────────
  const datasets = { rxPower: [], linkMargin: [], totalLoss: [] };

  for (let ei = 0; ei < elevations.length; ei++) {
    const elev = elevations[ei];
    const distKm = slantKm(elev);
    const gL = geoLossDb(distKm);
    const aL = atmLossDb(elev);
    const rxP = [], lM = [], tL = [];

    for (const cn0 of cn0Vals) {
      const layers = hvLayers(cn0);
      const sL = scintLossDb(elev, layers);
      const total = gL + aL + pLoss + sL + fixedDb;
      const rxPow = txPow - total;
      const margin = rxPow - rxSens;
      rxP.push(rxPow);
      lM.push(margin);
      tL.push(total);
    }

    const base = { label: elev + '\u00b0', color: neonColors[ei] };
    datasets.rxPower.push({ ...base, data: rxP });
    datasets.linkMargin.push({ ...base, data: lM });
    datasets.totalLoss.push({ ...base, data: tL });
  }

  const xLabels = cn0Vals.map(v => v.toExponential(1));

  // ── Destroy any previous study charts ─────────────────────────────
  if (window._lmStudyCharts) {
    window._lmStudyCharts.forEach(c => plotlyDestroyChart(c));
  }
  window._lmStudyCharts = [];
  grid.innerHTML = '';

  // ── Title ─────────────────────────────────────────────────────────
  if (elements.linkMarginTitle) {
    elements.linkMarginTitle.textContent =
      'FSO Link Margin \u2014 ' + (isUplink ? 'UPLINK' : 'DOWNLINK') + ' Link';
  }

  // ── Create 3 stacked charts ───────────────────────────────────────
  const chartDefs = [
    { key: 'rxPower',    yLabel: 'Rx Power (dBm)',     title: 'Received Power' },
    { key: 'linkMargin', yLabel: 'Link Margin (dB)',   title: 'Link Margin' },
    { key: 'totalLoss',  yLabel: 'Total Loss (dB)',    title: 'Total Loss' },
  ];

  for (const def of chartDefs) {
    const wrapper = document.createElement('div');
    wrapper.className = 'lm-chart-wrapper';
    const chartDiv = document.createElement('div');
    wrapper.appendChild(chartDiv);
    grid.appendChild(wrapper);

    renderLinkMarginChart(chartDiv, {
      title: def.title,
      xLabels,
      datasets: datasets[def.key],
      xTitle: 'Cn\u2080\u00b2 (m\u207b\u00b2\u2033)',
      yLabel: def.yLabel,
    });
    window._lmStudyCharts.push(chartDiv);
  }

  // ── Open dialog ───────────────────────────────────────────────────
  if (dialog instanceof HTMLDialogElement && !dialog.open) {
    dialog.showModal();
  }
  requestAnimationFrame(() => {
    window._lmStudyCharts.forEach(c => plotlyResizeChart(c));
  });
}

  function resetModalZoom() {
    plotlyResetZoom(modalChartInstance);
  }

  return { initializeCharts, computePassTime, showModalGraph, showLinkMarginStudy, resetModalZoom };
}
