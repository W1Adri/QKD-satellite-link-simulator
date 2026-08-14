// ---------------------------------------------------------------------------
// app/static/weather.js
// ---------------------------------------------------------------------------
// Purpose : Weather field configuration, population, and validation helpers.
//           Manages the weather overlay UI state and field definitions.
//
// Exports : WEATHER_FIELDS, populateWeatherFieldOptions, populateWeatherLevelOptions,
//           sanitizeWeatherSamples, syncWeatherSamplesInputs, setWeatherStatus,
//           toWeatherIso
// ---------------------------------------------------------------------------

// ─────────────────────────────────────────────────────────────────────────────
// Weather Field Definitions
// ─────────────────────────────────────────────────────────────────────────────
export const WEATHER_FIELDS = {
  'wind_speed': {
    label: 'Wind speed',
    units: 'm/s',
    levels: [200, 250, 300, 500, 700, 850],
  },
  temperature: {
    label: 'Temperature',
    units: 'degC',
    levels: [200, 300, 500, 700, 850],
  },
  relative_humidity: {
    label: 'Relative humidity',
    units: '%',
    levels: [700, 850, 925],
  },
  geopotential_height: {
    label: 'Geopotential height',
    units: 'm',
    levels: [500, 700, 850],
  },
};

// ─────────────────────────────────────────────────────────────────────────────
// DOM Element References (injected from main.js)
// ─────────────────────────────────────────────────────────────────────────────
let elements = {};

/**
 * Inject DOM element references for weather controls.
 */
export function setWeatherElements(els) {
  elements = els;
}

/**
 * Populate the weather field select dropdown.
 */
export function populateWeatherFieldOptions(selectedKey = 'wind_speed') {
  const select = elements.weatherFieldSelect;
  if (!select) return;
  select.innerHTML = '';
  for (const [key, def] of Object.entries(WEATHER_FIELDS)) {
    const opt = document.createElement('option');
    opt.value = key;
    opt.textContent = `${def.label} (${def.units})`;
    if (key === selectedKey) opt.selected = true;
    select.appendChild(opt);
  }
}

/**
 * Populate the weather level select dropdown based on the selected field.
 */
export function populateWeatherLevelOptions(fieldKey, selectedLevel) {
  const select = elements.weatherLevelSelect;
  if (!select) return;
  const def = WEATHER_FIELDS[fieldKey];
  const levels = def?.levels ?? [200];
  select.innerHTML = '';
  levels.forEach((lvl) => {
    const opt = document.createElement('option');
    opt.value = lvl;
    opt.textContent = `${lvl} hPa`;
    if (lvl === selectedLevel) opt.selected = true;
    select.appendChild(opt);
  });
}

/**
 * Sanitize weather samples to be a multiple of 8, clamped to [16, 900].
 */
export function sanitizeWeatherSamples(value) {
  let v = parseInt(value, 10) || 120;
  v = Math.round(v / 8) * 8;
  return Math.max(16, Math.min(900, v));
}

/**
 * Sync weather samples inputs (number and slider).
 */
export function syncWeatherSamplesInputs(value) {
  const sanitized = sanitizeWeatherSamples(value);
  if (elements.weatherSamples) {
    elements.weatherSamples.value = sanitized;
  }
  if (elements.weatherSamplesSlider) {
    elements.weatherSamplesSlider.value = sanitized;
  }
  return sanitized;
}

/**
 * Set the weather status message in the UI.
 */
export function setWeatherStatus(message) {
  if (!elements.weatherStatus) return;
  elements.weatherStatus.textContent = message ?? '';
}

/**
 * Convert a datetime-local value to ISO 8601 string for API calls.
 */
export function toWeatherIso(timeValue) {
  if (!timeValue) return null;
  // If already ISO-like string, try to parse
  if (typeof timeValue === 'string') {
    // datetime-local format: "2025-01-15T12:00"
    // Convert to ISO: "2025-01-15T12:00:00Z"
    if (timeValue.length === 16) {
      return `${timeValue}:00Z`;
    }
    if (timeValue.endsWith('Z')) {
      return timeValue;
    }
    return `${timeValue}Z`;
  }
  return null;
}
