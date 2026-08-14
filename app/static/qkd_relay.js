// ---------------------------------------------------------------------------
// app/static/qkd_relay.js
// ---------------------------------------------------------------------------
// Purpose : Key-volume / PCFLOS / untrusted-relay panel. Calls the backend
//           (/api/solve, /api/pcflos, /api/relay) and renders the result
//           tables. Extracted from main.js as a dependency-injected factory.
//
// Usage   : const qkdRelay = createQkdRelay({ elements, getSelectedStation });
//           Returns { computeQKDTimeSeries, fetchPCFLOS, populateRelaySelects,
//             runRelay }.  displayKeyVolume / displayPCFLOS / displayRelayResults
//           are private render helpers.
// ---------------------------------------------------------------------------
import { state, setComputed } from './state.js';
import { buildSolveRequest } from './solve_payload.js';

export function createQkdRelay({ elements, getSelectedStation }) {

const CELL = 'style="text-align:right; padding:0.5rem;"';
const fmt = (v, d = 4) => (Number.isFinite(v) ? Number(v).toFixed(d) : '—');
const pctOf = (v) => (Number.isFinite(v) ? `${(v * 100).toFixed(1)}%` : '—');

function tile(label, value, hint) {
  return `
      <div style="padding:0.5rem; background:rgba(255,255,255,0.05); border-radius:4px;">
        <div style="font-size:0.85rem; color:rgba(255,255,255,0.7);">${label}</div>
        <div style="font-size:1.1rem; font-weight:bold;">${value}</div>
        ${hint ? `<div style="font-size:0.7rem; opacity:.6;">${hint}</div>` : ''}
      </div>`;
}

function displayKeyVolume(keyVolume) {
  const el = document.getElementById('keyVolumeResults');
  if (!keyVolume || !el) return;
  el.style.display = 'block';

  const fkOn = keyVolume.total_key_volume_finite_mb !== undefined;
  const avOn = keyVolume.total_key_volume_available_mb !== undefined;

  // Summary metrics.  The asymptotic clear-sky total stays the headline number
  // and the two penalties are reported SEPARATELY, never folded into it: the
  // finite-key fraction and the cloud factor answer different questions, and a
  // single "effective" number hides which one moved.
  const summary = document.getElementById('keyVolumeSummary');
  if (summary) {
    let html = tile('Passes', keyVolume.pass_count || 0)
      + tile('Asymptotic key', `${fmt(keyVolume.total_key_volume_mb)} MB`, 'clear sky, infinite block')
      + tile('Pass boundary', `${keyVolume.elevation_threshold_deg ?? 5}°`);
    if (fkOn) {
      html += tile('Distillable (Lim 2014)',
        `${fmt(keyVolume.total_key_volume_finite_mb)} MB`,
        `${pctOf(keyVolume.mean_fk_fraction)} of asymptotic · `
        + `${Math.round(keyVolume.total_key_bits_finite_lim || 0).toLocaleString('en-US')} bits`);
    }
    if (avOn) {
      html += tile('Cloud availability', pctOf(keyVolume.mean_availability),
        `key-weighted P_CFLOS(ε) · ${fmt(keyVolume.total_key_volume_available_mb)} MB`);
    }
    if (keyVolume.total_key_volume_expected_mb !== undefined) {
      html += tile('Expected delivered',
        `${fmt(keyVolume.total_key_volume_expected_mb)} MB`,
        'finite key × availability (upper bound)');
    }
    summary.innerHTML = html;
  }

  // Per-pass table
  const passTable = document.getElementById('keyVolumePassTable');
  if (passTable && keyVolume.passes && keyVolume.passes.length > 0) {
    let html = '<table style="width:100%; margin-top:0.75rem; border-collapse:collapse;">'
      + '<thead><tr style="border-bottom:1px solid rgba(255,255,255,0.2);">'
      + '<th style="text-align:left; padding:0.5rem;">Pass</th>'
      + `<th ${CELL}>Duration (s)</th><th ${CELL}>Volume (MB)</th>`
      + (fkOn ? `<th ${CELL}>n sifted</th><th ${CELL}>Finite fraction</th><th ${CELL}>ℓ (bits)</th>` : '')
      + (avOn ? `<th ${CELL}>P_CFLOS</th>` : '')
      + '</tr></thead><tbody>';
    keyVolume.passes.forEach((p, i) => {
      html += '<tr style="border-bottom:1px solid rgba(255,255,255,0.1);">'
        + `<td style="padding:0.5rem;">${i + 1}</td>`
        + `<td ${CELL}>${(p.duration_s || 0).toFixed(0)}</td>`
        + `<td ${CELL}>${fmt(p.key_volume_mb, 6)}</td>`
        + (fkOn
          ? `<td ${CELL}>${Math.round(p.nSifted || 0).toLocaleString('en-US')}</td>`
            + `<td ${CELL}>${pctOf(p.fkFraction)}</td>`
            + `<td ${CELL}>${Math.round(p.ellFiniteBits || 0).toLocaleString('en-US')}</td>`
          : '')
        + (avOn ? `<td ${CELL}>${pctOf(p.availability)}</td>` : '')
        + '</tr>';
      // Block-shrinkage sensitivity, when requested: ℓ(f·n) vs f·ℓ(n).  The
      // "shortfall" is the ratio of the two — below 1 means shortening the block
      // costs MORE than pro rata, and 0 means the key is gone entirely.
      const shrink = p.ellBlockFractions;
      if (shrink && typeof shrink === 'object') {
        const parts = Object.entries(shrink).map(([f, v]) => {
          const bits = Math.round(Number(v?.ellFiniteBits) || 0).toLocaleString('en-US');
          const sh = Number(v?.shortfall);
          return `f=${f}: ${bits} bits`
            + (Number.isFinite(sh) ? ` (${(sh * 100).toFixed(0)}% of pro rata)` : '');
        });
        html += `<tr><td colspan="${fkOn ? (avOn ? 7 : 6) : 3}" `
          + 'style="padding:0 .5rem .5rem 1.5rem;font-size:11px;opacity:.7;">'
          + `↳ ℓ(f·n) block shrinkage — ${parts.join(' · ')}</td></tr>`;
      }
    });
    html += '</tbody></table>';
    if (fkOn) {
      html += '<p class="graph-hint">One pass = one finite-key block (Lim et al. 2014; '
        + 'Islam et al., PRX Quantum 5, 030101 (2024) §III B). Deviations scale as √n while '
        + 'counts scale as n, so a short pass keeps a smaller <em>fraction</em>, and below a '
        + 'threshold block size it keeps nothing.</p>';
    }
    if (avOn) {
      const meta = keyVolume.availability_meta || {};
      html += `<p class="graph-hint">P_CFLOS(ε) = (1 − N)^√(1 + β² cot²ε), β = ${meta.beta ?? 1}, `
        + `${meta.estimator || 'expectation'} estimator${meta.night_only ? ', night hours only' : ''}, `
        + `cloud data ${meta.source || 'archive'}. Key-rate weighted per pass and reported as an `
        + 'UPPER bound on availability.</p>';
    }
    if (keyVolume.availability_note) {
      html += `<p class="graph-hint" style="color:#ffd166;">⚠ ${keyVolume.availability_note}</p>`;
    }
    if (keyVolume.finite_key_note) {
      html += `<p class="graph-hint" style="color:#ffd166;">⚠ ${keyVolume.finite_key_note}</p>`;
    }
    passTable.innerHTML = html;
  } else if (passTable) {
    passTable.innerHTML = '';
  }

  // Daily table
  const dailyTable = document.getElementById('keyVolumeDailyTable');
  if (dailyTable && keyVolume.daily_mb && Object.keys(keyVolume.daily_mb).length > 0) {
    let html = '<h5 style="margin-top:1rem; margin-bottom:0.5rem;">Daily Key Volume</h5><table style="width:100%; border-collapse:collapse;"><thead><tr style="border-bottom:1px solid rgba(255,255,255,0.2);"><th style="text-align:left; padding:0.5rem;">Date</th><th style="text-align:right; padding:0.5rem;">Volume (MB)</th></tr></thead><tbody>';
    for (const [date, mb] of Object.entries(keyVolume.daily_mb)) {
      html += `<tr style="border-bottom:1px solid rgba(255,255,255,0.1);"><td style="padding:0.5rem;">${date}</td><td style="text-align:right; padding:0.5rem;">${(mb || 0).toFixed(6)}</td></tr>`;
    }
    html += '</tbody></table>';
    dailyTable.innerHTML = html;
  } else if (dailyTable) {
    dailyTable.innerHTML = '';
  }
}

// ── Monte Carlo summary (bands + outage) ─────────────────────────────────
// The band itself is drawn in the graph modal (graph id `skrBand`); this is the
// scalar summary plus the caveat that must travel with any published band.
function displayMonteCarlo(mc) {
  const el = document.getElementById('mcSummary');
  if (!el) return;
  if (!mc || !mc.enabled) {
    el.style.display = 'none';
    el.innerHTML = '';
    return;
  }
  el.style.display = 'block';
  const outage = Number(mc.link_time_outage);
  el.innerHTML =
    '<h4 class="metrics-title">🎲 Monte Carlo Channel</h4>'
    + '<div style="display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:0.5rem;">'
    + tile('Link-time outage', Number.isFinite(outage) ? pctOf(outage) : '—',
      'time-weighted over contact')
    + tile('Realizations', (mc.realizations ?? 0).toLocaleString('en-US'),
      `seed ${mc.seed ?? 'random'}`)
    + tile('Band', (mc.quantiles || []).map((q) => `P${Math.round(q)}`).join(' / ') || '—')
    + '</div>'
    + `<p class="graph-hint">${mc.note || ''}</p>`;
}

// ── QKD Time-Series (SKR / QBER vs time / elevation / distance) ──────────
// Calls /api/solve with current orbit + station + QKD parameters.
// On success, injects skrKbps and qberPct arrays into state.computed.metrics
// so that showModalGraph can render them immediately.
async function computeQKDTimeSeries() {
  const station = getSelectedStation();
  if (!station) {
    alert('Please select a ground station first.');
    return;
  }
  const statusEl = document.getElementById('qkdSeriesStatus');
  if (statusEl) statusEl.textContent = 'Computing SKR time series…';

  try {
    // ONE payload builder, shared with the constellation study — and it forwards
    // the WHOLE link budget (atmospheric losses, scintillation, background,
    // fixed optics, link direction).  The earlier partial payload made two of
    // the advanced options no-ops: the Monte Carlo band needs the turbulence
    // statistics the deterministic margin is a quantile of, and temporal gating
    // has nothing to suppress unless the background is on.
    const payload = buildSolveRequest({ station, advanced: true });

    const res = await fetch('/api/solve', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    const data = await res.json();
    const sm = data.station_metrics;
    if (sm && (sm.skrKbps || sm.qberPct)) {
      // Monte Carlo quantile series are named skrKbpsP5 / P50 / P95 after the
      // requested percentiles, so pick them up generically instead of assuming
      // the default band.
      const mcKeys = Object.keys(sm).filter((k) => /^skrKbpsP\d+$/.test(k))
        .sort((a, b) => Number(a.slice(8)) - Number(b.slice(8)));
      const mcSeries = {};
      mcKeys.forEach((k) => { mcSeries[k] = sm[k]; });

      // Store backend series under dedicated keys to avoid alignment issues
      // with client-side elevation/distance arrays (different sample counts).
      setComputed({
        ...state.computed,
        metrics: {
          ...state.computed.metrics,
          skrKbps: sm.skrKbps ?? [],
          qberPct: sm.qberPct ?? [],
          skrElevationDeg: sm.elevationDeg ?? [],    // backend-aligned elevation
          skrDistanceKm: sm.distanceKm ?? [],        // backend-aligned distance
          skrTimeline: data.timeline ?? [],           // backend timeline for x-axis
          ...mcSeries,
          mcQuantileKeys: mcKeys,
          outageProbability: sm.outageProbability ?? [],
        },
      });
      const active = (sm.skrKbps || []).filter((v) => v !== null && v > 0).length;
      if (statusEl) statusEl.textContent = `SKR series ready — ${active} active samples over ${(sm.skrKbps || []).length} total.`;
    } else {
      if (statusEl) statusEl.textContent = 'No QKD data returned — check station/orbit settings.';
    }
    if (data.key_volume) displayKeyVolume(data.key_volume);
    displayMonteCarlo(data.monte_carlo);
  } catch (err) {
    console.error('computeQKDTimeSeries error:', err);
    if (statusEl) statusEl.textContent = `Error: ${err.message}`;
  }
}

async function fetchPCFLOS() {
  const station = getSelectedStation();
  if (!station) {
    alert('Please select a station first');
    return;
  }
  const threshold = parseFloat(document.getElementById('pcflosThreshold')?.value || '30');
  const year = new Date().getFullYear() - 1; // retrospective climatology

  try {
    const res = await fetch('/api/pcflos', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        lat: station.lat,
        lon: station.lon,
        year: year,
        threshold_pct: threshold,
        station_name: station.name || 'Unknown'
      })
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    const data = await res.json();
    displayPCFLOS(data);
  } catch (error) {
    console.error('PCFLOS fetch error:', error);
    alert('Failed to fetch PCFLOS data: ' + error.message);
  }
}

function displayPCFLOS(data) {
  const el = document.getElementById('pcflosResults');
  if (!el) return;
  el.style.display = 'block';
  const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const pct = v => (v !== undefined && v !== null) ? (v * 100).toFixed(1) : 'N/A';

  // Two estimators, both always returned by /api/pcflos. They are DIFFERENT
  // quantities and the threshold one is generally the optimist, so both are
  // shown side by side rather than one being passed off as "the" PCFLOS.
  // Expectation = mean of (1 - N)^f(eps) over hours: no threshold at all, so
  // labelling it with one would be wrong.
  let html = '';
  if (data.station_name) {
    html += `<p><strong>Station:</strong> ${data.station_name}</p>`;
  }
  html += `<p><strong>Annual PCFLOS:</strong> ${pct(data.annual_expectation ?? data.annual_pcflos)}%`
       +  ` &nbsp;<span style="opacity:0.7">(expectation estimator at ${data.elev_deg ?? 90}&deg;`
       +  ` elevation, &beta;=${data.beta ?? 1}, ERA5 ${data.year || 'N/A'}`
       +  `${data.night_only ? ', night hours only' : ''})</span></p>`;
  if (data.annual_threshold !== undefined) {
    html += `<p style="opacity:0.75"><strong>Threshold estimator:</strong> ${pct(data.annual_threshold)}%`
         +  ` &mdash; P(cover &lt; ${data.threshold_pct ?? 30}%). Shown for comparison only:`
         +  ` counting hours below a cutoff treats the ERA5 areal <em>fraction</em> as binary`
         +  ` and generally overstates availability.</p>`;
  }

  html += '<table style="width:100%; margin-top:0.5rem; border-collapse:collapse;"><thead>'
       +  '<tr style="border-bottom:1px solid rgba(255,255,255,0.2);">'
       +  '<th style="text-align:left; padding:0.5rem;">Month</th>'
       +  '<th style="text-align:right; padding:0.5rem;">Expectation (%)</th>'
       +  '<th style="text-align:right; padding:0.5rem;">Threshold (%)</th>'
       +  '<th style="text-align:right; padding:0.5rem;">Hours</th></tr></thead><tbody>';
  for (let m = 1; m <= 12; m++) {
    const exp = (data.monthly_expectation ?? data.monthly_pcflos ?? {})[m];
    const thr = (data.monthly_threshold ?? {})[m];
    const hrs = (data.hours ?? {})[m];
    html += `<tr style="border-bottom:1px solid rgba(255,255,255,0.1);">`
         +  `<td style="padding:0.5rem;">${months[m-1]}</td>`
         +  `<td style="text-align:right; padding:0.5rem;">${pct(exp)}</td>`
         +  `<td style="text-align:right; padding:0.5rem; opacity:0.75">${pct(thr)}</td>`
         +  `<td style="text-align:right; padding:0.5rem; opacity:0.6">${hrs ?? 'N/A'}</td></tr>`;
  }
  html += '</tbody></table>';
  el.innerHTML = html;
}

function populateRelaySelects() {
  const stations = state.stations?.list || [];
  const html = stations.map(s => `<option value="${s.id}" data-lat="${s.lat}" data-lon="${s.lon}" data-alt="${s.altitude_m || 0}" data-aperture="${s.aperture_m || 1}">${s.name || s.id}</option>`).join('');
  ['relayStationA', 'relayStationB'].forEach(id => {
    const sel = document.getElementById(id);
    if (sel) sel.innerHTML = html;
  });
}

async function runRelay() {
  const selA = document.getElementById('relayStationA');
  const selB = document.getElementById('relayStationB');
  if (!selA || !selB || !selA.value || !selB.value) {
    alert('Please select both Station A and Station B');
    return;
  }
  if (selA.value === selB.value) {
    alert('Station A and Station B must be different');
    return;
  }

  // state.stations is { list, selectedId } — the list is what holds the records.
  const stations = state.stations?.list || [];
  const stationA = stations.find(s => s.id === selA.value);
  const stationB = stations.find(s => s.id === selB.value);
  if (!stationA || !stationB) {
    alert('Selected stations not found');
    return;
  }

  // Same builder as the single-link series: the previous local version sent
  // `inclination` / `raan` / `arg_perigee` / `mean_anomaly`, none of which are
  // SolveRequest field names, so the relay was silently propagating the API
  // defaults instead of the orbit on screen.
  const buildStationRequest = (station) => buildSolveRequest({ station, advanced: true });

  const threshold = parseFloat(document.getElementById('pcflosThreshold')?.value || '30');
  const year = new Date().getFullYear() - 1;

  try {
    const res = await fetch('/api/relay', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        solve_a: buildStationRequest(stationA),
        solve_b: buildStationRequest(stationB),
        elevation_threshold_deg: 5.0,
        cloud_threshold_pct: threshold,
        year: year
      })
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${res.status}`);
    }
    const data = await res.json();
    displayRelayResults(data);
  } catch (error) {
    console.error('Relay computation error:', error);
    alert('Failed to compute relay: ' + error.message);
  }
}

function displayRelayResults(data) {
  const el = document.getElementById('relayResults');
  if (!el) return;
  el.style.display = 'block';

  let html = '<h5 style="margin-top:0.5rem; margin-bottom:0.5rem;">Relay Results</h5>';
  
  // Station A metrics
  if (data.station_a) {
    html += '<p style="margin-top:0.5rem;"><strong>Station A:</strong></p>';
    html += '<ul style="margin-left:1rem; margin-bottom:0.5rem;">';
    html += `<li>Total key volume: ${(data.station_a.key_volume?.total_key_volume_mb || 0).toFixed(4)} MB</li>`;
    html += `<li>Pass count: ${data.station_a.key_volume?.pass_count || 0}</li>`;
    if (data.station_a.pcflos_factor !== undefined) {
      html += `<li>PCFLOS factor: ${(data.station_a.pcflos_factor * 100).toFixed(1)}%</li>`;
      html += `<li>Effective volume: ${(data.station_a.effective_key_volume_mb || 0).toFixed(4)} MB</li>`;
    }
    html += '</ul>';
  }

  // Station B metrics
  if (data.station_b) {
    html += '<p style="margin-top:0.5rem;"><strong>Station B:</strong></p>';
    html += '<ul style="margin-left:1rem; margin-bottom:0.5rem;">';
    html += `<li>Total key volume: ${(data.station_b.key_volume?.total_key_volume_mb || 0).toFixed(4)} MB</li>`;
    html += `<li>Pass count: ${data.station_b.key_volume?.pass_count || 0}</li>`;
    if (data.station_b.pcflos_factor !== undefined) {
      html += `<li>PCFLOS factor: ${(data.station_b.pcflos_factor * 100).toFixed(1)}%</li>`;
      html += `<li>Effective volume: ${(data.station_b.effective_key_volume_mb || 0).toFixed(4)} MB</li>`;
    }
    html += '</ul>';
  }

  // Relay metrics
  if (data.relay) {
    html += '<p style="margin-top:0.5rem;"><strong>Relay Summary:</strong></p>';
    html += '<ul style="margin-left:1rem;">';
    html += `<li>Matched orbits: ${data.relay.matched_orbit_count || 0}</li>`;
    html += `<li>Relay passes: ${data.relay.relay_passes?.length || 0}</li>`;
    html += `<li>Total relay volume: ${(data.relay.total_relay_mb || 0).toFixed(4)} MB</li>`;
    if (data.relay.effective_relay_mb !== undefined) {
      html += `<li>Effective relay volume: ${(data.relay.effective_relay_mb || 0).toFixed(4)} MB</li>`;
    }
    html += '</ul>';
  }

  el.innerHTML = html;
}

  return { computeQKDTimeSeries, fetchPCFLOS, populateRelaySelects, runRelay };
}
