// Plotly.js chart helpers — paper-quality figures (TODO-08).
// Replaces Chart.js. Plotly is loaded globally via CDN (window.Plotly).
// Native zoom/pan/box-select + hi-res PNG export (scale 2) for the manuscript.

const FONT_LIGHT = { family: 'Inter, system-ui, -apple-system, sans-serif', size: 12, color: '#111827' };
const FONT_DARK = { family: 'Inter, system-ui, -apple-system, sans-serif', size: 12, color: '#e8eef7' };

const GRID_LIGHT = 'rgba(100, 116, 139, 0.28)';
const GRID_DARK = 'rgba(79, 209, 255, 0.08)';

/** Config shared by interactive (zoomable) charts. scale:2 → crisp PNG export. */
function zoomConfig(filename) {
  return {
    responsive: true,
    scrollZoom: true,
    displaylogo: false,
    modeBarButtonsToRemove: ['select2d', 'lasso2d'],
    toImageButtonOptions: { format: 'png', scale: 2, filename: filename || 'figure' },
  };
}

const STATIC_CONFIG = { responsive: true, displayModeBar: false };

/**
 * Categorical series colours, validated for colour-vision deficiency and for
 * contrast against each mode's chart surface (OKLab ΔE ≥ 8 on every adjacent
 * pair under protan/deutan/tritan simulation; ≥ 3:1 contrast vs surface).
 * Assigned in fixed order — never cycled, never reordered by rank, so a series
 * keeps its colour when others are filtered out.
 */
export const SERIES_COLORS_LIGHT = ['#0369a1', '#c2410c', '#6d28d9'];
export const SERIES_COLORS_DARK = ['#0891b2', '#ea580c', '#7c3aed'];

export function isPlotlyReady() {
  return typeof window.Plotly !== 'undefined';
}

function lightLayout({ xTitle, yTitle, showlegend, height } = {}) {
  const layout = {
    paper_bgcolor: '#ffffff',
    plot_bgcolor: '#ffffff',
    font: FONT_LIGHT,
    margin: { l: 56, r: 16, t: 12, b: 44 },
    showlegend: !!showlegend,
    legend: { orientation: 'h', x: 0, y: 1.12, font: { size: 10 } },
    hovermode: 'x unified',
    xaxis: { title: { text: xTitle || '' }, showgrid: false, zeroline: false,
             linecolor: GRID_LIGHT, ticks: 'outside', tickcolor: GRID_LIGHT, automargin: true },
    yaxis: { title: { text: yTitle || '' }, gridcolor: GRID_LIGHT, zeroline: false,
             linecolor: GRID_LIGHT, ticks: 'outside', tickcolor: GRID_LIGHT, automargin: true },
  };
  if (height) layout.height = height;
  return layout;
}

function darkLayout({ title, xTitle, yTitle } = {}) {
  return {
    paper_bgcolor: 'rgba(0,0,0,0)',
    plot_bgcolor: 'rgba(0,0,0,0)',
    font: FONT_DARK,
    margin: { l: 60, r: 20, t: 40, b: 50 },
    title: { text: title || '', font: { size: 13, color: '#e8eef7' }, x: 0.5, xanchor: 'center' },
    showlegend: true,
    legend: { orientation: 'h', x: 0.5, xanchor: 'center', y: 1.18, font: { size: 11 } },
    hovermode: 'x unified',
    xaxis: { title: { text: xTitle || '' }, gridcolor: GRID_DARK, zeroline: false,
             tickfont: { color: '#9ba3b4' }, tickangle: -45, automargin: true },
    yaxis: { title: { text: yTitle || '' }, gridcolor: GRID_DARK, zeroline: false,
             tickfont: { color: '#9ba3b4' }, automargin: true },
  };
}

/** Single-line metric chart used by the graph modal (light theme, zoomable). */
export function renderModalGraph(el, { labels, values, color, yLabel, xLabel } = {}) {
  if (!el || !isPlotlyReady()) return;
  const trace = {
    x: labels,
    y: values,
    type: 'scatter',
    mode: 'lines',
    line: { color, width: 2.5, shape: 'spline' },
    fill: 'tozeroy',
    fillcolor: `${color}1f`,
    connectgaps: false,
    hovertemplate: '%{y:.2f}<extra></extra>',
  };
  window.Plotly.react(el, [trace], lightLayout({ xTitle: xLabel, yTitle: yLabel }), zoomConfig('skr_chart'));
}

/** Irradiance GHI/DNI/DHI multi-line chart (light theme, static). */
export function renderIrradianceChart(el, { labels, series } = {}) {
  if (!el || !isPlotlyReady()) return;
  const traces = (series || []).map((s) => ({
    x: labels,
    y: s.y,
    name: s.name,
    type: 'scatter',
    mode: 'lines',
    line: { color: s.color, width: 1.5, shape: 'spline' },
    hovertemplate: `${s.name}: %{y:.0f}<extra></extra>`,
  }));
  const layout = lightLayout({ xTitle: 'UTC', yTitle: 'W/m²', showlegend: true, height: 180 });
  layout.margin = { l: 48, r: 12, t: 24, b: 36 };
  window.Plotly.react(el, traces, layout, STATIC_CONFIG);
}

/** One panel of the link-margin study (dark theme, multi-elevation, zoomable). */
export function renderLinkMarginChart(el, { title, xLabels, datasets, xTitle, yLabel } = {}) {
  if (!el || !isPlotlyReady()) return;
  const traces = (datasets || []).map((d) => ({
    x: xLabels,
    y: d.data,
    name: d.label,
    type: 'scatter',
    mode: 'lines+markers',
    line: { color: d.color, width: 2, dash: 'dash', shape: 'spline' },
    marker: { color: d.color, size: 5 },
  }));
  window.Plotly.react(el, traces, darkLayout({ title, xTitle, yTitle: yLabel }), zoomConfig('link_margin'));
}

/**
 * Filled-contour / heatmap chart (light theme, zoomable) — for the paper's
 * 2-D parameter sweeps (loss & SKR vs distance/aperture, SKR vs radiance).
 * `z` is a 2-D array indexed z[iy][ix] (rows = y, cols = x).
 */
export function renderContour(el, {
  x, y, z, xTitle, yTitle, colorbarTitle, colorscale, height, heatmap,
} = {}) {
  if (!el || !isPlotlyReady()) return;
  const trace = {
    x, y, z,
    type: heatmap ? 'heatmap' : 'contour',
    colorscale: colorscale || 'Viridis',
    colorbar: { title: { text: colorbarTitle || '', side: 'right' }, thickness: 14 },
    line: { width: 0.5 },
    contours: heatmap ? undefined : { coloring: 'fill' },
    connectgaps: true,
    hovertemplate: `${xTitle || 'x'}: %{x}<br>${yTitle || 'y'}: %{y}<br>%{z:.3g}<extra></extra>`,
  };
  const layout = lightLayout({ xTitle, yTitle });
  if (height) layout.height = height;
  window.Plotly.react(el, [trace], layout, zoomConfig('paper_contour'));
}

/**
 * Confidence-band chart (light theme, zoomable) — Monte Carlo P5/P50/P95 with
 * the deterministic curve overlaid.
 *
 * The band is ONE hue (magnitude, not identity): a translucent P5→P95 fill with
 * the median as a solid line of the same hue, so the eye reads spread rather
 * than three unrelated categories.  The deterministic curve gets the second
 * categorical hue because it IS a different thing — a different estimator of
 * the same quantity — and it is dashed so the two are told apart without colour.
 *
 * `lower`/`upper`/`median` are aligned to `labels`.  The series is drawn as ONE
 * BAND PER CONTIGUOUS RUN of finite samples, not as one trace with nulls: a
 * `fill:'tonexty'` spans a null gap even when `connectgaps:false` breaks the
 * line, which over a multi-pass window paints a wedge of "uncertainty" across
 * hours in which there was no link at all.  Splitting the runs is the only way
 * the gaps stay gaps.
 */
function contiguousRuns(labels, series) {
  const runs = [];
  let start = -1;
  for (let i = 0; i <= labels.length; i += 1) {
    const ok = i < labels.length && series.every((s) => Number.isFinite(s?.[i]));
    if (ok && start < 0) start = i;
    if (!ok && start >= 0) {
      if (i - start > 1) runs.push([start, i]);   // a single point draws nothing
      start = -1;
    }
  }
  return runs;
}

export function renderBandChart(el, {
  labels, lower, median, upper, deterministic,
  xLabel, yLabel, bandName, medianName, deterministicName,
} = {}) {
  if (!el || !isPlotlyReady()) return;
  const [cBand, cDet] = SERIES_COLORS_LIGHT;
  const bName = bandName || 'P5–P95';
  const mName = medianName || 'Median (P50)';
  const dName = deterministicName || 'Deterministic';
  const traces = [];

  contiguousRuns(labels, [lower, upper, median]).forEach(([a, b], runIdx) => {
    const x = labels.slice(a, b);
    const first = runIdx === 0;   // legend entry once, not once per pass
    traces.push({
      x, y: lower.slice(a, b), name: bName, legendgroup: 'band',
      type: 'scatter', mode: 'lines', line: { color: cBand, width: 0 },
      hoverinfo: 'skip', showlegend: false,
    });
    traces.push({
      x, y: upper.slice(a, b), name: bName, legendgroup: 'band', showlegend: first,
      type: 'scatter', mode: 'lines', line: { color: cBand, width: 0 },
      fill: 'tonexty', fillcolor: `${cBand}26`,
      hovertemplate: 'P95 %{y:.3g}<extra></extra>',
    });
    traces.push({
      x, y: median.slice(a, b), name: mName, legendgroup: 'median', showlegend: first,
      type: 'scatter', mode: 'lines', line: { color: cBand, width: 2 },
      hovertemplate: 'P50 %{y:.3g}<extra></extra>',
    });
  });

  if (Array.isArray(deterministic) && deterministic.some((v) => Number.isFinite(v))) {
    // A line needs no splitting — connectgaps:false already breaks it at nulls.
    traces.push({
      x: labels, y: deterministic, name: dName,
      type: 'scatter', mode: 'lines',
      line: { color: cDet, width: 2, dash: 'dash' },
      connectgaps: false, hovertemplate: 'det. %{y:.3g}<extra></extra>',
    });
  }
  const layout = lightLayout({ xTitle: xLabel, yTitle: yLabel, showlegend: true });

  // A multi-orbit window is mostly gap: a few 400 s passes inside 24 h render as
  // vertical slivers. Open on the longest pass — and SAY SO on the figure, since
  // a silently clipped x-axis reads as "this is the whole run".
  const runs = contiguousRuns(labels, [lower, upper, median]);
  if (runs.length) {
    const [a, b] = runs.reduce((best, r) => (r[1] - r[0] > best[1] - best[0] ? r : best));
    const span = Number(labels[b - 1]) - Number(labels[a]);
    const total = Number(labels[labels.length - 1]) - Number(labels[0]);
    if (span > 0 && total > 3 * span) {
      const pad = span * 0.25;
      layout.xaxis = {
        ...layout.xaxis,
        range: [Number(labels[a]) - pad, Number(labels[b - 1]) + pad],
      };
      layout.annotations = [{
        text: `zoomed to the longest of ${runs.length} pass${runs.length === 1 ? '' : 'es'}`
          + ' — double-click to show the whole window',
        xref: 'paper', yref: 'paper', x: 1, y: 1.06,
        xanchor: 'right', yanchor: 'bottom', showarrow: false,
        font: { size: 10, color: '#6b7280' },
      }];
    }
  }
  window.Plotly.react(el, traces, layout, zoomConfig('mc_band'));
}

/**
 * Horizontal-or-vertical bar chart (light theme, zoomable) — magnitude by
 * category, e.g. the marginal value of the n-th station or the key each
 * contention policy delivers.
 *
 * One hue: bars encode magnitude, and the category is already named on the
 * axis, so colouring each bar differently would spend identity on nothing.
 * `values2` adds a second measure as a paired bar (grouped, 2 px gap), which is
 * how asymptotic-vs-finite key is compared — same units, one axis, never a
 * second y-scale.
 */
export function renderBarChart(el, {
  categories, values, values2, name, name2, xLabel, yLabel, horizontal, height, textFormat,
} = {}) {
  if (!el || !isPlotlyReady()) return;
  const [c1, c2] = SERIES_COLORS_LIGHT;
  const fmt = textFormat || '.3g';
  const mk = (vals, nm, color) => ({
    [horizontal ? 'y' : 'x']: categories,
    [horizontal ? 'x' : 'y']: vals,
    name: nm,
    type: 'bar',
    orientation: horizontal ? 'h' : 'v',
    marker: { color, line: { width: 0 } },
    texttemplate: `%{${horizontal ? 'x' : 'y'}:${fmt}}`,
    textposition: 'outside',
    textfont: { size: 10 },
    cliponaxis: false,
    hovertemplate: `${nm}: %{${horizontal ? 'x' : 'y'}:.4g}<extra></extra>`,
  });
  const traces = [mk(values, name || 'Value', c1)];
  const paired = Array.isArray(values2) && values2.some((v) => Number.isFinite(v));
  if (paired) traces.push(mk(values2, name2 || 'Value 2', c2));

  const layout = lightLayout({ xTitle: xLabel, yTitle: yLabel, showlegend: paired, height });
  layout.bargap = 0.35;
  layout.bargroupgap = 0.08;     // 2 px surface gap between paired bars
  layout.hovermode = 'closest';
  // Headroom for the outside data labels, which Plotly will otherwise clip at
  // the plot edge on the tallest bar — the one whose number matters most.
  const all = [...(values || []), ...(paired ? values2 : [])]
    .filter((v) => Number.isFinite(v));
  const peak = all.length ? Math.max(...all, 0) : 0;
  if (peak > 0) {
    const axis = horizontal ? 'xaxis' : 'yaxis';
    layout[axis] = { ...layout[axis], range: [Math.min(0, ...all), peak * 1.15] };
  }
  window.Plotly.react(el, traces, layout, zoomConfig('bar_chart'));
}

/** Reset zoom/pan to autoscale on an existing Plotly chart div. */
export function resetZoom(el) {
  if (el && isPlotlyReady()) {
    window.Plotly.relayout(el, { 'xaxis.autorange': true, 'yaxis.autorange': true });
  }
}

/** Re-fit a Plotly chart to its container (call after a dialog opens/resizes). */
export function resizeChart(el) {
  if (el && isPlotlyReady()) window.Plotly.Plots.resize(el);
}

/** Tear down a Plotly chart and free its resources. */
export function destroyChart(el) {
  if (el && isPlotlyReady()) window.Plotly.purge(el);
}
