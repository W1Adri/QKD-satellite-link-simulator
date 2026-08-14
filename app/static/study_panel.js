// ---------------------------------------------------------------------------
// app/static/study_panel.js
// ---------------------------------------------------------------------------
// Purpose : "Constellation Study" panel — frontend for
//           POST /api/study/constellation: a Walker constellation over a
//           ground-station network with contention accounted for.
//
//           WHAT THE PANEL HAS TO MAKE VISIBLE, because these are the results:
//           1. The BOUND CHAIN.  contact_greedy <= contact_OPT <= min(ub_sat,
//              ub_gs) <= preemptive <= independent.  Printed as an ordered list
//              so the ordering can be CHECKED rather than assumed.
//           2. The FINITE-KEY INVERSION.  The preemptive schedule wins the
//              asymptotic contest and can lose the distillable one, because
//              re-pointing mid-pass shatters blocks below the size at which
//              they can be distilled.  When that happens the asymptotic upper
//              bound is not an upper bound on deliverable key, and the panel
//              says so in those words.
//           3. SATURATION.  The marginal value of the n-th station under
//              contention, as a fraction of what that station is worth alone.
//
//           The study's base configuration is built by solve_payload.js — the
//           same builder the single-link SKR series uses, so the study cannot
//           silently drift from the simulator whose physics it claims to share.
//
// Usage   : const study = createStudyPanel({ getStations });
//           → { populateStations, run, showLast, hasResults }
// ---------------------------------------------------------------------------
import { api } from './api.js';
import { buildSolveRequest } from './solve_payload.js';
import {
  renderBarChart, resizeChart, destroyChart,
} from './plotly_charts.js';

const POLICY_LABELS = {
  contact: 'Contact (non-preemptive)',
  preemptive: 'Preemptive (matching)',
  independent: 'Independent (naive N×M)',
};

/** Europe bounding box — mirrors models.is_in_europe_bbox on the backend. */
function isInEuropeBbox(lat, lon) {
  return lat >= 25.0 && lat <= 72.0 && lon >= -31.0 && lon <= 45.0;
}

export function createStudyPanel({ getStations }) {
  let lastResult = null;
  let charts = [];

  const $ = (id) => document.getElementById(id);
  const grid = () => $('studyGrid');
  const tableEl = () => $('studyTable');

  const num = (id, fallback) => {
    const v = Number($(id)?.value);
    return Number.isFinite(v) ? v : fallback;
  };

  function setStatus(msg, isError = false) {
    const el = $('studyStatus');
    if (!el) return;
    el.textContent = msg || '';
    el.style.color = isError ? 'var(--danger, #ff6b6b)' : '';
  }

  // ── Station selector ────────────────────────────────────────────────────
  function populateStations() {
    const sel = $('studyStations');
    if (!sel) return;
    const previous = new Set(Array.from(sel.selectedOptions).map((o) => o.value));
    const list = (typeof getStations === 'function' ? getStations() : []) || [];
    sel.innerHTML = list
      .map((s) => {
        const id = s.id ?? '';
        const ap = s.aperture_m ?? 1;
        const alt = Math.round(s.altitude_m ?? 0);
        return `<option value="${id}">${s.name || id} — ${ap} m, ${alt} m ASL</option>`;
      })
      .join('');
    // Keep the previous selection across station-list refreshes.
    Array.from(sel.options).forEach((o) => { o.selected = previous.has(o.value); });
  }

  function selectStations(predicate) {
    const sel = $('studyStations');
    if (!sel) return;
    const list = (typeof getStations === 'function' ? getStations() : []) || [];
    const byId = new Map(list.map((s) => [String(s.id ?? ''), s]));
    Array.from(sel.options).forEach((o) => {
      const st = byId.get(o.value);
      o.selected = !!st && predicate(st);
    });
  }

  function selectEurope() {
    selectStations((s) => isInEuropeBbox(Number(s.lat), Number(s.lon)));
    const n = ($('studyStations')?.selectedOptions || []).length;
    setStatus(`${n} European station${n === 1 ? '' : 's'} selected.`);
  }
  function selectAll() { selectStations(() => true); }
  function clearSelection() { selectStations(() => false); }

  // ── Charts ──────────────────────────────────────────────────────────────
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
    const t = $('studyDialogTitle');
    if (t) t.textContent = title;
    const dg = $('studyDialog');
    if (dg instanceof HTMLDialogElement && !dg.open) dg.showModal();
    requestAnimationFrame(() => charts.forEach(resizeChart));
  }

  // ── Request ─────────────────────────────────────────────────────────────
  function buildPayload() {
    const sel = $('studyStations');
    const chosen = Array.from(sel?.selectedOptions || []).map((o) => o.value);
    if (!chosen.length) throw new Error('Select at least one ground station');

    const list = (typeof getStations === 'function' ? getStations() : []) || [];
    const byId = new Map(list.map((s) => [String(s.id ?? ''), s]));
    const stationIds = [];
    const inline = [];
    chosen.forEach((id) => {
      const st = byId.get(id);
      if (id) stationIds.push(id);
      else if (st) {
        inline.push({
          name: st.name || 'Station',
          lat: st.lat, lon: st.lon,
          altitude_m: st.altitude_m || 0,
          aperture_m: st.aperture_m || 1,
        });
      }
    });

    const policies = [];
    if ($('studyPolicyContact')?.checked) policies.push('contact');
    if ($('studyPolicyPreemptive')?.checked) policies.push('preemptive');
    if ($('studyPolicyIndependent')?.checked) policies.push('independent');
    if (!policies.length) throw new Error('Select at least one contention policy');

    const T = Math.round(num('studyWalkerT', 6));
    const P = Math.round(num('studyWalkerP', 3));
    if (P > 0 && T % P !== 0) {
      throw new Error(`Walker T=${T} is not divisible by P=${P} — satellites would be dropped`);
    }

    // Base = the live simulator configuration (optics, link budget, atmosphere,
    // QKD, and the advanced finite-key / availability / Monte Carlo switches),
    // with only the propagation window overridden by this panel's own fields.
    const base = buildSolveRequest({
      advanced: true,
      overrides: {
        total_orbits: Math.round(num('studyOrbits', 3)),
        samples_per_orbit: Math.round(num('studySamples', 120)),
        // Monte Carlo is per-sample and the study evaluates T×N pairs; leaving
        // it on would multiply the cost by the realization count for a band the
        // study does not report.
        monte_carlo_enabled: false,
      },
    });

    const payload = {
      base,
      walker_T: T,
      walker_P: P,
      walker_F: Math.round(num('studyWalkerF', 1)),
      altitude_km: num('studyAltitude', 500),
      inclination_deg: num('studyInclination', 97.5),
      raan_offset_deg: num('studyRaanOffset', 0),
      policies,
      sat_terminals: Math.round(num('studySatTerminals', 1)),
      gs_terminals: Math.round(num('studyGsTerminals', 1)),
    };
    if (stationIds.length) payload.station_ids = stationIds;
    if (inline.length) payload.inline_stations = inline;

    const over = $('studyMarginalOver')?.value || '';
    if (over) {
      payload.marginal_over = over;
      payload.marginal_policy = $('studyMarginalPolicy')?.value || 'contact';
      payload.marginal_metric = $('studyMarginalMetric')?.value || 'finite';
      payload.marginal_order = $('studyMarginalOrder')?.value || 'greedy';
    }
    return payload;
  }

  // ── Rendering ───────────────────────────────────────────────────────────
  const mb = (bits) => (Number(bits) || 0) / 8e6;
  const f3 = (v) => (Number.isFinite(v) ? Number(v).toFixed(3) : '—');
  const pct = (v) => (Number.isFinite(v) ? `${(v * 100).toFixed(1)} %` : '—');

  function renderPolicyChart(res) {
    const keys = Object.keys(res.policies || {});
    if (!keys.length) return;
    const cats = keys.map((k) => POLICY_LABELS[k] || k);
    const asym = keys.map((k) => res.policies[k].asymptotic_mb ?? 0);
    const fin = keys.map((k) => res.policies[k].finite_mb ?? null);
    renderBarChart(newChartDiv(), {
      categories: cats,
      values: asym,
      values2: fin,
      name: 'Asymptotic key (MB)',
      name2: 'Finite / distillable key (MB)',
      yLabel: 'Network key volume (MB)',
      horizontal: false,
      height: 320,
      textFormat: '.3g',
    });
  }

  function renderMarginalCharts(res) {
    const mc = res.marginal_curve;
    if (!mc || !Array.isArray(mc.steps) || !mc.steps.length) return;
    const cats = mc.steps.map((s) => String(s.element));
    renderBarChart(newChartDiv(), {
      categories: cats,
      values: mc.steps.map((s) => mb(s.marginal)),
      values2: mc.steps.map((s) => mb(s.standalone)),
      name: `Marginal gain (MB, ${mc.policy})`,
      name2: 'Standalone value (MB)',
      yLabel: 'Key volume (MB)',
      height: 320,
    });
    renderBarChart(newChartDiv(), {
      categories: cats,
      values: mc.steps.map((s) => (Number(s.saturation) || 0) * 100),
      name: 'Saturation (%)',
      yLabel: 'Marginal gain / standalone value (%)',
      height: 320,
      textFormat: '.1f',
    });
  }

  function policiesTable(res) {
    const keys = Object.keys(res.policies || {});
    if (!keys.length) return '';
    const fkOn = !!res.finite_key?.enabled;
    let rows = '';
    keys.forEach((k) => {
      const p = res.policies[k];
      rows += `<tr><td>${POLICY_LABELS[k] || k}</td>`
        + `<td style="text-align:right">${f3(p.asymptotic_mb)}</td>`
        + (fkOn
          ? `<td style="text-align:right">${f3(p.finite_mb)}</td>`
            + `<td style="text-align:right">${pct(p.finite_fraction)}</td>`
          : '')
        + `<td style="text-align:right">${p.contacts_served ?? '—'}</td></tr>`;
      (p.notes || []).forEach((n) => {
        rows += `<tr><td colspan="${fkOn ? 5 : 3}" style="opacity:.7;font-size:11px">↳ ${n}</td></tr>`;
      });
    });
    return '<h4 style="margin:10px 0 6px;">Key delivered per contention policy</h4>'
      + '<table class="data-table"><thead><tr><th>Policy</th>'
      + '<th style="text-align:right">Asymptotic (MB)</th>'
      + (fkOn ? '<th style="text-align:right">Finite (MB)</th><th style="text-align:right">Finite / asymptotic</th>' : '')
      + '<th style="text-align:right">Intervals served</th></tr></thead>'
      + `<tbody>${rows}</tbody></table>`;
  }

  function boundChainTable(res) {
    const chain = res.bound_chain_asymptotic || {};
    const labels = {
      contact_greedy: 'Contact, greedy (achievable)',
      contact_opt_upper_bound: 'Contact OPT — upper bound',
      preemptive: 'Preemptive (matching per interval)',
      independent: 'Independent (unrealisable reference)',
    };
    // Printed in the order the inequality claims, so a violation is visible.
    const order = ['contact_greedy', 'contact_opt_upper_bound', 'preemptive', 'independent'];
    const present = order.filter((k) => Number.isFinite(chain[k]));
    if (!present.length) return '';
    let rows = '';
    let prev = null;
    let violated = false;
    present.forEach((k) => {
      const v = mb(chain[k]);
      const ok = prev === null || v >= prev - 1e-9;
      if (!ok) violated = true;
      rows += `<tr><td>${labels[k]}</td><td style="text-align:right">${f3(v)}</td>`
        + `<td style="text-align:center">${prev === null ? '' : (ok ? '≤ ✔' : '≤ ✘')}</td></tr>`;
      prev = v;
    });
    const ub = res.contact_upper_bound || {};
    return '<h4 style="margin:14px 0 6px;">Bound chain (asymptotic key, MB)</h4>'
      + '<table class="data-table"><thead><tr><th>Quantity</th>'
      + '<th style="text-align:right">MB</th><th style="text-align:center">Holds</th>'
      + `</tr></thead><tbody>${rows}</tbody></table>`
      + `<p class="graph-hint">Upper bound = min(sat-side ${f3(mb(ub.ub_sat))} MB, GS-side ${f3(mb(ub.ub_gs))} MB)`
      + `${ub.exact ? ', each solved exactly by weighted-interval-scheduling DP' : ' — loose: '}`
      + `${ub.exact ? '' : ub.note || ''}.`
      + (violated ? ' <strong>⚠ The chain does not hold at this configuration — that is a bug, not a result.</strong>' : '')
      + '</p>';
  }

  function inversionBlock(res) {
    const inv = res.finite_key_inversion;
    if (!inv) return '';
    const tone = inv.inverted ? '#ffd166' : 'rgba(255,255,255,.6)';
    return `<div style="margin-top:14px;padding:10px;border-left:3px solid ${tone};background:rgba(255,255,255,.04);">`
      + `<strong>${inv.inverted ? '⚡ Finite-key inversion detected' : 'No inversion at this configuration'}</strong>`
      + `<div style="margin-top:6px;font-size:12px;">Preemptive ${f3(mb(inv.preemptive_finite_bits))} MB `
      + `vs contact ${f3(mb(inv.contact_finite_bits))} MB of distillable key.</div>`
      + `<div style="margin-top:6px;font-size:12px;opacity:.85;">${inv.note}</div></div>`;
  }

  function metaTable(res) {
    const c = res.constellation || {};
    const w = res.window || {};
    const walker = c.walker ? `T/P/F = ${c.walker.T}/${c.walker.P}/${c.walker.F}` : 'explicit elements';
    const stations = (res.stations || []).map((s) => s.name || s.id).join(', ');
    return '<h4 style="margin:14px 0 6px;">Configuration</h4>'
      + '<table class="data-table"><tbody>'
      + `<tr><td>Constellation</td><td>${c.n_sats} satellites, ${walker}, `
      + `${f3(c.altitude_km)} km, ${f3(c.inclination_deg)}°</td></tr>`
      + `<tr><td>Network</td><td>${(res.stations || []).length} stations — ${stations}</td></tr>`
      + `<tr><td>Window</td><td>${w.orbits} orbits, ${w.samples} samples, `
      + `${(Number(w.duration_s) / 3600).toFixed(2)} h (period ${(Number(w.period_s) / 60).toFixed(1)} min)</td></tr>`
      + `<tr><td>Contacts</td><td>${res.contacts?.total ?? '—'} above `
      + `${res.contacts?.elevation_threshold_deg ?? '—'}° elevation</td></tr>`
      + `<tr><td>Finite key</td><td>${res.finite_key?.enabled ? 'on' : 'off'} — ${res.finite_key?.note || ''}</td></tr>`
      + '</tbody></table>';
  }

  function pairsTable(res) {
    const pairs = res.pairs || {};
    const keys = Object.keys(pairs);
    if (!keys.length) return '';
    let rows = '';
    keys.forEach((k) => {
      const p = pairs[k];
      rows += `<tr><td>${k}</td><td style="text-align:right">${p.passes ?? 0}</td>`
        + `<td style="text-align:right">${f3(p.key_mb_unscheduled)}</td>`
        + `<td style="text-align:right">${f3(p.peak_skr_kbps)}</td></tr>`;
    });
    return '<h4 style="margin:14px 0 6px;">Per satellite–station pair (before scheduling)</h4>'
      + '<table class="data-table"><thead><tr><th>Pair</th>'
      + '<th style="text-align:right">Passes</th>'
      + '<th style="text-align:right">Key if alone (MB)</th>'
      + '<th style="text-align:right">Peak SKR (kbps)</th></tr></thead>'
      + `<tbody>${rows}</tbody></table>`
      + '<p class="graph-hint">These are the unscheduled per-pair totals. Their sum is the '
      + '<em>independent</em> policy — what the network would deliver if every pair had its own '
      + 'terminal, which no operator can buy.</p>';
  }

  function marginalTable(res) {
    const mc = res.marginal_curve;
    if (!mc || !Array.isArray(mc.steps) || !mc.steps.length) return '';
    let rows = '';
    mc.steps.forEach((s, i) => {
      rows += `<tr><td>${i + 1}</td><td>${s.element}</td>`
        + `<td style="text-align:right">${f3(mb(s.cumulative))}</td>`
        + `<td style="text-align:right">${f3(mb(s.marginal))}</td>`
        + `<td style="text-align:right">${f3(mb(s.standalone))}</td>`
        + `<td style="text-align:right">${pct(s.saturation)}</td></tr>`;
    });
    return `<h4 style="margin:14px 0 6px;">Marginal value over ${mc.over} `
      + `(${mc.policy}, ${mc.metric}, ${mc.order} order)</h4>`
      + '<table class="data-table"><thead><tr><th>#</th><th>Element</th>'
      + '<th style="text-align:right">Cumulative (MB)</th>'
      + '<th style="text-align:right">Marginal (MB)</th>'
      + '<th style="text-align:right">Standalone (MB)</th>'
      + '<th style="text-align:right">Saturation</th></tr></thead>'
      + `<tbody>${rows}</tbody></table>`
      + `<p class="graph-hint">${mc.note || ''}</p>`;
  }

  function caveatsBlock(res) {
    const cav = res.caveats || [];
    if (!cav.length) return '';
    return '<p class="graph-hint" style="margin-top:10px;">⚠ '
      + cav.map((c) => c).join('<br>⚠ ') + '</p>';
  }

  function render(res) {
    clearCharts();
    renderPolicyChart(res);
    renderMarginalCharts(res);
    tableEl().innerHTML =
      policiesTable(res)
      + boundChainTable(res)
      + inversionBlock(res)
      + marginalTable(res)
      + metaTable(res)
      + pairsTable(res)
      + caveatsBlock(res);
    const nSat = res.constellation?.n_sats ?? '?';
    const nGs = (res.stations || []).length;
    openDialog(`Constellation study — ${nSat} satellites × ${nGs} stations`);
  }

  // ── Run ─────────────────────────────────────────────────────────────────
  async function run() {
    let payload;
    try {
      payload = buildPayload();
    } catch (e) {
      setStatus(e.message, true);
      return;
    }
    const btn = $('btnRunStudy');
    if (btn) btn.disabled = true;
    const nPairs = payload.walker_T
      * ((payload.station_ids?.length || 0) + (payload.inline_stations?.length || 0));
    setStatus(`Running — ${nPairs} satellite–station pairs through the full link budget. `
      + 'This is the slow part; expect tens of seconds.');
    try {
      const res = await api.studyConstellation(payload);
      lastResult = res;
      render(res);
      const show = $('btnShowStudyResults');
      if (show) show.style.display = '';
      const best = res.policies?.contact || res.policies?.preemptive
        || res.policies?.independent || {};
      setStatus(`Done — ${res.contacts?.total ?? 0} contacts, `
        + `${f3(best.asymptotic_mb)} MB asymptotic`
        + (res.finite_key?.enabled ? `, ${f3(best.finite_mb)} MB distillable.` : '.'));
    } catch (e) {
      setStatus(`Study failed: ${e.message}`, true);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  function showLast() {
    if (!lastResult) {
      setStatus('No study has been run yet.', true);
      return;
    }
    render(lastResult);
  }

  return {
    populateStations, run, showLast,
    selectEurope, selectAll, clearSelection,
    hasResults: () => lastResult !== null,
  };
}
