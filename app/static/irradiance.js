// ---------------------------------------------------------------------------
// app/static/irradiance.js
// ---------------------------------------------------------------------------
// Purpose : Solar-irradiance panel — POSTs to /api/irradiance for a station +
//           time, renders the GHI/DNI/DHI metric fields and the daily-profile
//           Plotly chart. Extracted from main.js as a DI factory.
//
// Usage   : const irradiance = createIrradiance({ elements, getSelectedStation });
//           Returns { fetchIrradiance }.  setIrradianceStatus /
//           displayIrradianceResults are private helpers.
// ---------------------------------------------------------------------------
import { isPlotlyReady, renderIrradianceChart } from './plotly_charts.js';

export function createIrradiance({ elements, getSelectedStation }) {

let irradianceChartInstance = null;

function setIrradianceStatus(msg) {
  if (elements.irradianceStatus) {
    elements.irradianceStatus.textContent = msg || '';
    elements.irradianceStatus.hidden = !msg;
  }
}

async function fetchIrradiance() {
  const station = getSelectedStation();
  if (!station) {
    setIrradianceStatus('Select a ground station first.');
    return;
  }
  const method = elements.irradianceMethod?.value || 'analytical';
  // Use the irradiance time input, fall back to epoch
  let timeValue = elements.irradianceTime?.value || elements.epochInput?.value || '';
  if (!timeValue) {
    setIrradianceStatus('Set a time first.');
    return;
  }
  // Ensure ISO format with seconds
  if (timeValue.length === 16) timeValue += ':00';
  const isoTime = timeValue.endsWith('Z') ? timeValue : timeValue + 'Z';
  const altitude = parseFloat(elements.irradianceAltitude?.value) || 0;

  const btn = elements.btnFetchIrradiance;
  if (btn) btn.disabled = true;
  setIrradianceStatus('Computing irradiance…');

  const payload = {
    lat: station.lat,
    lon: station.lon,
    time: isoTime,
    method,
    altitude_m: altitude,
  };

  try {
    const resp = await fetch('/api/irradiance', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) {
      let detail = resp.statusText;
      try {
        const errBody = await resp.json();
        if (errBody?.detail) detail = errBody.detail;
      } catch (_) { /* ignore */ }
      throw new Error(detail || `HTTP ${resp.status}`);
    }
    const data = await resp.json();
    displayIrradianceResults(data);
    setIrradianceStatus(`Done — ${data.is_day ? '☀ Day' : '🌙 Night'} (${method})`);
  } catch (err) {
    console.error('Irradiance fetch failed', err);
    setIrradianceStatus(`Failed: ${err.message}`);
  } finally {
    if (btn) btn.disabled = false;
  }
}

function displayIrradianceResults(data) {
  // Populate metric fields
  const set = (id, val) => { if (elements[id]) elements[id].textContent = val; };
  set('irradianceGHI', `${(data.ghi_w_m2 ?? 0).toFixed(1)} W/m²`);
  set('irradianceDNI', `${(data.dni_w_m2 ?? 0).toFixed(1)} W/m²`);
  set('irradianceDHI', `${(data.dhi_w_m2 ?? 0).toFixed(1)} W/m²`);
  set('irradianceElevation', `${(data.solar_elevation_deg ?? 0).toFixed(2)}°`);
  set('irradianceDayNight', data.is_day ? '☀ Day' : '🌙 Night');
  set('irradianceAirMass', data.air_mass != null ? data.air_mass.toFixed(3) : '--');
  set('irradianceDayLength', data.day_length_h != null ? `${data.day_length_h.toFixed(2)} h` : '--');

  // Sunrise / sunset — analytical model returns float hours (sunrise_utc_h),
  // format as HH:MM for display; fall back to string keys from Open-Meteo.
  const fmtHour = (h) => {
    if (h == null) return '--';
    if (typeof h === 'number') {
      const hh = Math.floor(h) % 24;
      const mm = Math.round((h - Math.floor(h)) * 60);
      return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`;
    }
    return String(h);
  };
  set('irradianceSunrise', fmtHour(data.sunrise_utc_h ?? data.sunrise_utc));
  set('irradianceSunset', fmtHour(data.sunset_utc_h ?? data.sunset_utc));
  set('irradianceSource', data.source ?? '--');

  if (elements.irradianceMetrics) elements.irradianceMetrics.style.display = '';

  // Render daily profile chart
  const profile = data.daily_profile;
  const canvas = elements.irradianceChart;
  if (profile && canvas && isPlotlyReady()) {
    canvas.style.display = '';
    const labels = (profile.times || []).map((t) => {
      if (typeof t === 'string' && t.includes('T')) return t.split('T')[1]?.slice(0, 5) || t;
      return String(t);
    });
    renderIrradianceChart(canvas, {
      labels,
      series: [
        { name: 'GHI', y: profile.ghi_w_m2, color: '#f5c542' },
        { name: 'DNI', y: profile.dni_w_m2, color: '#ff6e40' },
        { name: 'DHI', y: profile.dhi_w_m2, color: '#42a5f5' },
      ],
    });
    irradianceChartInstance = canvas;
  }
}

  return { fetchIrradiance };
}
