// ---------------------------------------------------------------------------
// app/static/paper_figures.js
// ---------------------------------------------------------------------------
// "Paper (Ntanos 2021)" panel — reproduces the figures of
//   Ntanos et al., "LEO Satellites Constellation-to-Ground QKD Links: Greek
//   QCI Paradigm", Photonics 2021, 8, 544
// by calling the /api/paper/* endpoints and drawing with the shared Plotly
// helpers.  Renders into the #paperDialog modal (grid + table).
// ---------------------------------------------------------------------------
import { api } from './api.js';
import {
  renderContour, renderLinkMarginChart, resizeChart, destroyChart, resetZoom,
} from './plotly_charts.js';

const NEON = ['#4fd1ff', '#ff6b6b', '#ffd166', '#06d6a0', '#c77dff',
              '#f78c6b', '#8bd450', '#ff9ff3', '#48dbfb', '#feca57'];

export function createPaperFigures({ onApplyPreset } = {}) {
  let preset = null;
  let charts = [];

  const $ = (id) => document.getElementById(id);
  const grid = () => $('paperGrid');
  const tableEl = () => $('paperTable');
  const dialog = () => $('paperDialog');

  function setStatus(msg) { const s = $('paperStatus'); if (s) s.textContent = msg || ''; }

  async function loadPreset() {
    try {
      preset = await api.paperPreset();
      const p = preset.params;
      const info = $('paperPresetInfo');
      if (info) {
        info.innerHTML =
          `λ=${p.wavelength_nm} nm · μ=${p.mu_signal}, ν=${p.mu_decoy} · ` +
          `q=${p.q.toFixed(4)} · f(e)=${p.f_ec} · f_rep=${(p.f_rep / 1e6).toFixed(0)} MHz<br>` +
          `OGS: ${preset.stations.map((s) => `${s.name} (${s.aperture_m} m)`).join(' · ')}`;
      }
    } catch (e) {
      const info = $('paperPresetInfo');
      if (info) info.textContent = `Could not load paper preset: ${e.message}`;
    }
  }

  function clearCharts() {
    charts.forEach(destroyChart);
    charts = [];
    if (grid()) grid().innerHTML = '';
    if (tableEl()) tableEl().innerHTML = '';
  }

  function newChartDiv() {
    const wrapper = document.createElement('div');
    wrapper.className = 'lm-chart-wrapper';
    const div = document.createElement('div');
    wrapper.appendChild(div);
    grid().appendChild(wrapper);
    charts.push(div);
    return div;
  }

  function openDialog(title) {
    const t = $('paperDialogTitle');
    if (t) t.textContent = title;
    const dg = dialog();
    if (dg instanceof HTMLDialogElement && !dg.open) dg.showModal();
    requestAnimationFrame(() => charts.forEach(resizeChart));
  }

  // ── Fig 2: total loss & SKR vs distance × aperture ──────────────────────
  async function showFig2() {
    setStatus('Computing Fig 2 (link sweep)…');
    try {
      const r = await api.paperLinkSweep({});
      clearCharts();
      renderContour(newChartDiv(), {
        x: r.apertures_m, y: r.distances_km, z: r.lossDb,
        xTitle: 'Receiver telescope aperture (m)', yTitle: 'Distance (km)',
        colorbarTitle: 'Loss (dB)', colorscale: 'Blues', height: 340,
      });
      const skr5 = r.skrPerPulse.map((row) => row.map((v) => v * 1e5));
      renderContour(newChartDiv(), {
        x: r.apertures_m, y: r.distances_km, z: skr5,
        xTitle: 'Receiver telescope aperture (m)', yTitle: 'Distance (km)',
        colorbarTitle: 'SKR ×10⁻⁵ (bps/pulse)', colorscale: 'YlOrBr', height: 340,
      });
      openDialog('Fig 2 — Total downlink loss (dB) & nighttime SKR vs distance and aperture');
      setStatus('');
    } catch (e) { setStatus(`Fig 2 error: ${e.message}`); }
  }

  // ── Fig 3: SKR vs solar radiance (× distance and × elevation) ───────────
  async function showFig3() {
    setStatus('Computing Fig 3 (radiance sweep)…');
    try {
      const [a, b] = await Promise.all([
        api.paperRadianceSweep({ x_axis: 'distance', x_min: 300, x_max: 1000 }),
        api.paperRadianceSweep({ x_axis: 'elevation', x_min: 20, x_max: 90 }),
      ]);
      clearCharts();
      renderContour(newChartDiv(), {
        x: a.x_values, y: a.radiances, z: a.skrPerPulse.map((r) => r.map((v) => v * 1e5)),
        xTitle: 'Distance (km)', yTitle: 'Solar radiance (W/sr·m²·µm)',
        colorbarTitle: 'SKR ×10⁻⁵', colorscale: 'YlOrBr', height: 340,
      });
      renderContour(newChartDiv(), {
        x: b.x_values, y: b.radiances, z: b.skrPerPulse.map((r) => r.map((v) => v * 1e5)),
        xTitle: 'Elevation angle (deg)', yTitle: 'Solar radiance (W/sr·m²·µm)',
        colorbarTitle: 'SKR ×10⁻⁵', colorscale: 'YlOrBr', height: 340,
      });
      openDialog('Fig 3 — SKR vs solar radiance over distance (600 km orbit) and elevation');
      setStatus('');
    } catch (e) { setStatus(`Fig 3 error: ${e.message}`); }
  }

  // ── Fig 5: single satellite pass over Helmos ────────────────────────────
  async function showFig5() {
    setStatus('Propagating single pass over Helmos…');
    try {
      const r = await api.paperSinglePass({ station_id: 'helmos', total_orbits: 48 });
      clearCharts();
      const skr4 = r.skrPerPulse.map((v) => v * 1e4);
      renderLinkMarginChart(newChartDiv(), {
        title: 'Normalized SKR over the pass',
        xLabels: r.t, xTitle: 'Time (s)', yLabel: 'SKR ×10⁻⁴ (bps/pulse)',
        datasets: [{ label: 'SKR/pulse', color: NEON[0], data: skr4 }],
      });
      renderLinkMarginChart(newChartDiv(), {
        title: 'Slant distance over the pass',
        xLabels: r.t, xTitle: 'Time (s)', yLabel: 'Distance (km)',
        datasets: [{ label: 'Distance', color: NEON[1], data: r.distanceKm }],
      });
      const st = r.station;
      tableEl().innerHTML =
        `<table class="data-table"><tbody>` +
        `<tr><td>Ground station</td><td>${st.name} (${st.aperture_m} m, ${st.altitude_m} m)</td></tr>` +
        `<tr><td>Pass duration</td><td>${r.duration_s} s</td></tr>` +
        `<tr><td>Max elevation</td><td>${r.max_elevation_deg}°</td></tr>` +
        `<tr><td>Peak SKR/pulse</td><td>${r.max_skr_per_pulse.toExponential(3)} bps/pulse</td></tr>` +
        `<tr><td>Distilled key (this pass)</td><td>${r.total_key_Mbit} Mbit @ 100 MHz</td></tr>` +
        `</tbody></table>` +
        `<p class="graph-hint">Paper Fig 5: 340 s pass, peak 3.33×10⁻⁴, ~1.99 Mbit (67.2° pass).</p>`;
      openDialog('Fig 5 — Single LEO pass over Helmos: SKR & distance vs time');
      setStatus('');
    } catch (e) { setStatus(`Fig 5 error: ${e.message}`); }
  }

  // ── Fig 6/7 + Table 1: 10-satellite constellation ──────────────────────
  async function showFig67() {
    setStatus('Propagating 10-satellite constellation (may take ~20 s)…');
    try {
      const r = await api.paperConstellation({});
      clearCharts();
      for (const [sid, meta] of Object.entries(r.stations)) {
        const sats = r.series[sid] || [];
        if (!sats.length) continue;
        const xLabels = sats[0].t_hours;
        const datasets = sats.map((s, i) => ({
          label: s.sat, color: NEON[i % NEON.length],
          data: s.skrPerPulse.map((v) => v * 1e4),
        }));
        const d = newChartDiv();
        renderLinkMarginChart(d, {
          title: `${meta.name} (${meta.aperture_m} m)`,
          xLabels, xTitle: 'Time (hours)', yLabel: 'SKR ×10⁻⁴ (bps/pulse)', datasets,
        });
      }
      // Table 1
      const paperRef = { helmos: 1.435, skinakas: 0.40, cholomondas: 0.12 };
      let rows = '';
      for (const [sid, meta] of Object.entries(r.stations)) {
        const total = r.totals_gbit_year[sid] ?? 0;
        const peak = r.peak_skr_per_pulse[sid] ?? 0;
        rows += `<tr><td>${meta.name}</td><td>${meta.aperture_m}</td>` +
          `<td>${total.toFixed(3)}</td><td>${(paperRef[sid] ?? '—')}</td>` +
          `<td>${peak.toExponential(2)}</td></tr>`;
      }
      tableEl().innerHTML =
        `<h4 style="margin:8px 0;">Table 1 — Distilled key (Gbit/year, ${r.meta.n_sats} satellites)</h4>` +
        `<table class="data-table"><thead><tr>` +
        `<th>OGS</th><th>Aperture (m)</th><th>This model (Gbit/yr)</th>` +
        `<th>Paper (Gbit/yr)</th><th>Peak SKR/pulse</th></tr></thead><tbody>${rows}</tbody></table>` +
        `<p class="graph-hint">Window ${r.meta.window_days} d scaled ×${r.meta.year_scale} to 1 year. ` +
        `Absolute totals overestimate the paper (~×7) because the self-generated SSO ground track ` +
        `yields more high-elevation nighttime passes than the real STK ephemerides; the ` +
        `inter-station ratios match the paper (≈1 : 0.28 : 0.084).</p>`;
      openDialog('Fig 6/7 & Table 1 — Constellation SKR over time and yearly key per OGS');
      setStatus('');
    } catch (e) { setStatus(`Fig 6/7 error: ${e.message}`); }
  }

  function show(fig) {
    clearCharts();  // drop any previous figure immediately (loads can take ~20 s)
    if (fig === 'fig2') return showFig2();
    if (fig === 'fig3') return showFig3();
    if (fig === 'fig5') return showFig5();
    if (fig === 'fig67') return showFig67();
  }

  function applyPreset() {
    if (typeof onApplyPreset === 'function' && preset) onApplyPreset(preset.params);
  }

  function resetZoomAll() { charts.forEach(resetZoom); }

  return { loadPreset, show, applyPreset, resetZoomAll };
}
