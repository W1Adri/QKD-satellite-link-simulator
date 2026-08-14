// ---------------------------------------------------------------------------
// app/static/formatters.js
// ---------------------------------------------------------------------------
// Purpose : Domain-specific formatting functions for display values in the
//           QKD Satellite Link Simulator UI.  Covers atmospheric parameters,
//           orbital metrics, and weather data.
//
// Exports : firstFiniteValue, valueFromSeries, formatR0Meters, formatGreenwoodHz,
//           formatThetaArcsec, formatWindMps, normalizeLongitude, formatKm,
//           formatDecimal, normalizeInt, normalizeTolerance
// ---------------------------------------------------------------------------

/**
 * Return the first finite (non-NaN, non-infinite) value from a numeric series.
 */
export function firstFiniteValue(series) {
  if (!Array.isArray(series)) return null;
  for (let i = 0; i < series.length; i += 1) {
    const val = series[i];
    if (typeof val === 'number' && Number.isFinite(val)) return val;
  }
  return null;
}

/**
 * Safely read a value from a numeric series at a given index.
 */
export function valueFromSeries(series, index, fallback = null) {
  if (!Array.isArray(series)) return fallback;
  if (index < 0 || index >= series.length) return fallback;
  const val = series[index];
  if (typeof val === 'number' && Number.isFinite(val)) return val;
  return fallback;
}

/**
 * Format Fried parameter in meters with appropriate precision.
 */
export function formatR0Meters(value) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  if (value < 1e-2) return `${(value * 100).toFixed(2)} cm`;
  return `${value.toFixed(3)} m`;
}

/**
 * Format Greenwood frequency in Hz.
 */
export function formatGreenwoodHz(value) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  return `${value.toFixed(1)} Hz`;
}

/**
 * Format isoplanatic angle in arcseconds.
 */
export function formatThetaArcsec(value) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  return `${value.toFixed(2)} arcsec`;
}

/**
 * Format wind speed in meters per second.
 */
export function formatWindMps(value) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  return `${value.toFixed(1)} m/s`;
}

/**
 * Normalize a longitude value to the range [-180, 180].
 */
export function normalizeLongitude(lon) {
  let result = lon;
  while (result > 180) result -= 360;
  while (result < -180) result += 360;
  return result;
}

/**
 * Format a kilometer value with locale grouping.
 */
export function formatKm(value, fractionDigits = 3, useGrouping = true) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  return value.toLocaleString(undefined, {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
    useGrouping,
  });
}

/**
 * Format a decimal value with configurable precision.
 */
export function formatDecimal(value, decimals = 3) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return String(value);
  return Number(value.toFixed(decimals)).toString();
}

/**
 * Parse and clamp an integer within bounds.
 */
export function normalizeInt(value, min, max) {
  const parsed = parseInt(value, 10);
  if (!Number.isFinite(parsed)) return min;
  return Math.max(min, Math.min(max, parsed));
}

/**
 * Normalize tolerance to non-negative finite value.
 */
export function normalizeTolerance(value) {
  const parsed = parseFloat(value);
  if (!Number.isFinite(parsed) || parsed < 0) return 0;
  return parsed;
}
