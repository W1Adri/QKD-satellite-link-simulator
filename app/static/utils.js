// ---------------------------------------------------------------------------
// app/static/utils.js
// ---------------------------------------------------------------------------
// Purpose : Shared math constants, formatting functions, logging helpers,
//           safe fetch wrapper, and small geometry utilities (haversine).
//
// Exports : DEG2RAD, RAD2DEG, TWO_PI, clamp, lerp, formatDistanceKm,
//           formatAngle, formatLoss, formatDuration, formatDoppler,
//           isoNowLocal, haversineDistance, smoothArray,
//           findClosestRational, logCheckpoint, logError, logWarning,
//           logInfo, setLogLevel, safeFetch, validateNumber,
//           validateRequired
// ---------------------------------------------------------------------------
const DEG2RAD = Math.PI / 180;
const RAD2DEG = 180 / Math.PI;
const TWO_PI = Math.PI * 2;

// Enhanced error logging and checkpoint system
const LOG_LEVELS = {
  DEBUG: 0,
  INFO: 1,
  WARN: 2,
  ERROR: 3,
  CHECKPOINT: 4
};

let currentLogLevel = LOG_LEVELS.INFO;

function setLogLevel(level) {
  currentLogLevel = LOG_LEVELS[level] || LOG_LEVELS.INFO;
}

function logCheckpoint(message, data = null) {
  if (currentLogLevel <= LOG_LEVELS.CHECKPOINT) {
    console.log(`%c[CHECKPOINT]%c ${message}`, 
      'background: #4fd1ff; color: #000; padding: 2px 6px; border-radius: 3px; font-weight: bold',
      'color: #4fd1ff',
      data || '');
  }
}

function logError(context, error, additionalData = null) {
  if (currentLogLevel <= LOG_LEVELS.ERROR) {
    console.error(`%c[ERROR]%c ${context}:`, 
      'background: #ff4d4d; color: #fff; padding: 2px 6px; border-radius: 3px; font-weight: bold',
      'color: #ff4d4d',
      error);
    if (additionalData) {
      console.error('Additional data:', additionalData);
    }
    console.trace('Stack trace:');
  }
}

function logWarning(message, data = null) {
  if (currentLogLevel <= LOG_LEVELS.WARN) {
    console.warn(`%c[WARN]%c ${message}`, 
      'background: #ffa500; color: #000; padding: 2px 6px; border-radius: 3px; font-weight: bold',
      'color: #ffa500',
      data || '');
  }
}

function logInfo(message, data = null) {
  if (currentLogLevel <= LOG_LEVELS.INFO) {
    console.log(`%c[INFO]%c ${message}`, 
      'background: #4f46e5; color: #fff; padding: 2px 6px; border-radius: 3px; font-weight: bold',
      'color: #4f46e5',
      data || '');
  }
}

async function safeFetch(url, options = {}, context = 'API call') {
  logCheckpoint(`Starting fetch: ${context}`, { url, options });
  try {
    const response = await fetch(url, options);
    logCheckpoint(`Fetch response received: ${context}`, { 
      status: response.status, 
      ok: response.ok 
    });
    
    if (!response.ok) {
      const errorText = await response.text().catch(() => 'Unable to read error response');
      const error = new Error(`HTTP ${response.status}: ${response.statusText}`);
      error.response = response;
      error.body = errorText;
      throw error;
    }
    
    return response;
  } catch (error) {
    logError(context, error, { url, options });
    throw error;
  }
}

function validateNumber(value, min = -Infinity, max = Infinity, paramName = 'value') {
  const num = Number(value);
  if (!isFinite(num)) {
    logWarning(`Invalid number for ${paramName}: ${value}`);
    return null;
  }
  if (num < min || num > max) {
    logWarning(`${paramName} out of range [${min}, ${max}]: ${num}`);
    return null;
  }
  return num;
}

function validateRequired(value, paramName = 'value') {
  if (value === null || value === undefined || value === '') {
    logWarning(`Required parameter missing: ${paramName}`);
    return false;
  }
  return true;
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function lerp(a, b, t) {
  return a + (b - a) * t;
}

function formatDistanceKm(valueKm) {
  if (!isFinite(valueKm)) return '--';
  if (valueKm >= 1000) {
    return `${(valueKm / 1000).toFixed(2)} Mm`;
  }
  return `${valueKm.toFixed(2)} km`;
}

function formatAngle(valueDeg) {
  if (!isFinite(valueDeg)) return '--';
  return `${valueDeg.toFixed(2)}°`;
}

function formatLoss(dB) {
  if (!isFinite(dB)) return '--';
  return `${dB.toFixed(2)} dB`;
}

function formatDuration(seconds) {
  if (!isFinite(seconds)) return '--';
  const sign = seconds < 0 ? '-' : '';
  const total = Math.floor(Math.abs(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  const parts = [];
  if (hours) parts.push(`${hours} h`);
  if (minutes || hours) parts.push(`${minutes} min`);
  parts.push(`${secs} s`);
  return `${sign}${parts.join(' ')}`;
}

function formatDoppler(factor) {
  if (!isFinite(factor)) return '--';
  if (Math.abs(factor - 1) < 1e-5) {
    return '≈1';
  }
  return factor.toFixed(6);
}

function isoNowLocal() {
  const now = new Date();
  const tzOffset = now.getTimezoneOffset();
  const local = new Date(now.getTime() - tzOffset * 60000);
  return local.toISOString().slice(0, 16);
}

function haversineDistance(lat1, lon1, lat2, lon2, radiusKm = 6371) {
  const dLat = (lat2 - lat1) * DEG2RAD;
  const dLon = (lon2 - lon1) * DEG2RAD;
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * DEG2RAD) * Math.cos(lat2 * DEG2RAD) * Math.sin(dLon / 2) ** 2;
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return radiusKm * c;
}

function smoothArray(values, window = 5) {
  if (!Array.isArray(values) || values.length === 0) {
    return [];
  }
  const smoothed = [];
  const half = Math.max(1, Math.floor(window / 2));
  for (let i = 0; i < values.length; i++) {
    let sum = 0;
    let count = 0;
    for (let j = i - half; j <= i + half; j++) {
      if (j >= 0 && j < values.length) {
        sum += values[j];
        count++;
      }
    }
    smoothed.push(sum / count);
  }
  return smoothed;
}


function findClosestRational(real, maxDenominator, ignoreList = []) {
  if (!Number.isFinite(real) || !Number.isFinite(maxDenominator) || maxDenominator < 1) {
    return { j: 0, k: 0, error: Infinity };
  }
  let best = { j: 0, k: 1, error: Math.abs(real) };
  const ignored = new Set(ignoreList.map(item => `${item.j}:${item.k}`));

  for (let k = 1; k <= maxDenominator; k++) {
    const j = Math.round(real * k);
    if (j === 0 && real !== 0) continue;
    if (ignored.has(`${j}:${k}`)) continue;
    
    const error = Math.abs(real - j / k);
    if (error < best.error) {
      best = { j, k, error };
    }
  }
  return best;
}

export { 
  DEG2RAD, RAD2DEG, TWO_PI, 
  clamp, lerp, 
  formatDistanceKm, formatAngle, formatLoss, formatDuration, formatDoppler, 
  isoNowLocal, haversineDistance, smoothArray, findClosestRational,
  // Error handling and logging
  logCheckpoint, logError, logWarning, logInfo, setLogLevel,
  safeFetch, validateNumber, validateRequired
};