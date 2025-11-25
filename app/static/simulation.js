import { 
  DEG2RAD, RAD2DEG, TWO_PI, 
  clamp, haversineDistance,
  logCheckpoint, logError, validateNumber 
} from './utils.js';

// Simple J2 secular rate approximations for RAAN and argument of perigee
const MU_EARTH = 398600.4418; // km^3/s^2
const EARTH_RADIUS_KM = 6378.137; // km
const J2 = 1.08263e-3;

function secularRates(a, e, iRad) {
  // Enhanced J2 secular rate computation with proper semi-latus rectum handling
  if (!a || a <= 0) return { dotOmega: 0, dotOmegaDeg: 0, dotArgPerigee: 0, dotArgPerigeeDeg: 0, meanMotion: 0 };
  
  const n = Math.sqrt(MU_EARTH / (a * a * a)); // mean motion (rad/s)
  const p = a * (1 - e * e); // semi-latus rectum
  
  if (p <= 0) return { dotOmega: 0, dotOmegaDeg: 0, dotArgPerigee: 0, dotArgPerigeeDeg: 0, meanMotion: n };
  
  const cosI = Math.cos(iRad);
  const sinI = Math.sin(iRad);
  
  // Factor used in secular rate equations
  const factor = -1.5 * J2 * Math.pow(EARTH_RADIUS_KM / p, 2) * n;
  
  // RAAN precession rate (rad/s)
  const dotOmega = factor * cosI;
  
  // Argument of perigee rate (rad/s)
  const dotArgPerigee = factor * (2.5 * sinI * sinI - 2.0);

  return {
    dotOmega, // rad/s
    dotOmegaDeg: dotOmega * RAD2DEG,
    dotArgPerigee, // rad/s
    dotArgPerigeeDeg: dotArgPerigee * RAD2DEG,
    meanMotion: n,
  };
}

export const j2Propagator = { MU_EARTH, EARTH_RADIUS_KM, J2, secularRates };

// Sun-synchronous orbit calculations
const SOLAR_MEAN_MOTION_DEG_PER_DAY = 360.0 / 365.2421897; // ~0.9856 deg/day

/**
 * Calculate the inclination required for a sun-synchronous orbit
 * @param {number} altitudeKm - Orbital altitude in km
 * @param {number} eccentricity - Orbital eccentricity (default 0)
 * @returns {number} Inclination in degrees for sun-synchronous orbit
 */
function calculateSunSynchronousInclination(altitudeKm, eccentricity = 0.0) {
  logCheckpoint('Calculating sun-synchronous inclination', { altitudeKm, eccentricity });
  
  const a = EARTH_RADIUS_KM + altitudeKm;
  
  // Required RAAN drift rate for sun-synchronous (rad/s)
  const requiredDriftDegPerDay = SOLAR_MEAN_MOTION_DEG_PER_DAY;
  const requiredDriftRadPerSec = requiredDriftDegPerDay * DEG2RAD / 86400.0;
  
  // From J2 secular rate formula: dotOmega = -1.5 * J2 * (R/p)^2 * n * cos(i)
  // Solve for cos(i)
  
  const n = Math.sqrt(MU_EARTH / (a * a * a));
  const p = a * (1 - eccentricity * eccentricity);
  
  const factor = -1.5 * J2 * Math.pow(EARTH_RADIUS_KM / p, 2) * n;
  
  if (Math.abs(factor) < 1e-15) {
    throw new Error('Cannot compute sun-synchronous inclination for this orbit');
  }
  
  const cosI = requiredDriftRadPerSec / factor;
  
  // Check if solution exists
  if (Math.abs(cosI) > 1.0) {
    throw new Error(
      `No sun-synchronous orbit exists at altitude ${altitudeKm.toFixed(1)} km. ` +
      `cos(i) = ${cosI.toFixed(4)} is outside [-1, 1]. ` +
      `Try altitudes between 600-6000 km.`
    );
  }
  
  let inclinationRad = Math.acos(cosI);
  let inclinationDeg = inclinationRad * RAD2DEG;
  
  // Sun-synchronous orbits are typically retrograde (inclination > 90°)
  // For LEO, they are usually between 96° and 100°
  if (inclinationDeg < 90) {
    inclinationDeg = 180 - inclinationDeg;
  }
  
  logCheckpoint('Sun-synchronous inclination calculated', { 
    inclination: inclinationDeg,
    raanDrift: requiredDriftDegPerDay 
  });
  
  return inclinationDeg;
}

/**
 * Validate if an orbit is sun-synchronous
 * @param {number} altitudeKm - Orbital altitude in km
 * @param {number} inclinationDeg - Inclination in degrees
 * @param {number} eccentricity - Eccentricity
 * @returns {Object} Validation result with RAAN drift rate
 */
function validateSunSynchronousOrbit(altitudeKm, inclinationDeg, eccentricity = 0.0) {
  const a = EARTH_RADIUS_KM + altitudeKm;
  const iRad = inclinationDeg * DEG2RAD;
  
  const rates = secularRates(a, eccentricity, iRad);
  const raanDriftDegPerDay = rates.dotOmegaDeg * 86400.0;
  
  const targetDrift = SOLAR_MEAN_MOTION_DEG_PER_DAY;
  const error = Math.abs(raanDriftDegPerDay - targetDrift);
  const tolerance = 0.01; // 0.01 deg/day tolerance
  
  return {
    isSunSynchronous: error < tolerance,
    raanDriftDegPerDay: raanDriftDegPerDay,
    targetDriftDegPerDay: targetDrift,
    errorDegPerDay: raanDriftDegPerDay - targetDrift,
    errorPercent: (error / targetDrift) * 100
  };
}

export const sunSynchronousOrbit = { 
  calculateSunSynchronousInclination, 
  validateSunSynchronousOrbit,
  SOLAR_MEAN_MOTION_DEG_PER_DAY
};

// Walker Delta constellation generator
// T = total satellites, P = number of planes, F = relative phasing
function generateWalkerConstellation(T, P, F, a, iDeg, e = 0.0, raanOffsetDeg = 0) {
  const sats = [];
  const S = Math.round(T / P) || 1; // satellites per plane
  const i = Number(iDeg) || 0;
  for (let p = 0; p < P; p += 1) {
    const raan = (360 * p) / P + (raanOffsetDeg || 0);
    for (let s = 0; s < S; s += 1) {
      const m = (360 * s) / S + (360 * F * p) / T;
      sats.push({
        semiMajor: a,
        eccentricity: e,
        inclination: i,
        raan: ((raan % 360) + 360) % 360,
        argPerigee: 0,
        meanAnomaly: ((m % 360) + 360) % 360,
      });
    }
  }
  return sats;
}

export const walkerGenerator = { generateWalkerConstellation };

function computeRevisitTime(constellationPositions, points, timelineSeconds, revisitThresholdKm = 500) {
  // constellationPositions: { groupId: { satellites: [{ id,name,timeline:[{lat,lon,alt}] }] } }
  // points: [{lat,lon}], timelineSeconds: array of times matching timelines
  if (!Array.isArray(points) || !Array.isArray(timelineSeconds)) return { max: Infinity, mean: Infinity };

  const perPointIntervals = points.map(() => []);
  const numSamples = timelineSeconds.length;

  for (let ti = 0; ti < numSamples; ti += 1) {
    // collect all satellite positions at this time
    const posList = [];
    Object.values(constellationPositions).forEach((group) => {
      (group.satellites || []).forEach((sat) => {
        const snap = sat.timeline && sat.timeline[ti];
        if (snap && Number.isFinite(snap.lat) && Number.isFinite(snap.lon)) {
          posList.push(snap);
        }
      });
    });

    if (!posList.length) continue;

    points.forEach((pt, pIdx) => {
      let seen = false;
      for (let s = 0; s < posList.length; s += 1) {
        const satPos = posList[s];
        const d = haversineDistance(pt.lat, pt.lon, satPos.lat, satPos.lon, 6371);
        if (d <= revisitThresholdKm) { seen = true; break; }
      }
      if (seen) perPointIntervals[pIdx].push(timelineSeconds[ti]);
    });
  }

  const revisitStats = perPointIntervals.map((times) => {
    if (!times.length) return { max: Infinity, mean: Infinity };
    const diffs = [];
    for (let k = 1; k < times.length; k += 1) diffs.push(times[k] - times[k - 1]);
    if (!diffs.length) return { max: 0, mean: 0 };
    const max = Math.max(...diffs);
    const mean = diffs.reduce((a, b) => a + b, 0) / diffs.length;
    return { max, mean };
  });

  const valid = revisitStats.filter((s) => isFinite(s.max));
  if (!valid.length) return { max: Infinity, mean: Infinity };
  const maxRevisit = Math.max(...valid.map((s) => s.max));
  const meanRevisit = valid.reduce((acc, s) => acc + s.mean, 0) / valid.length;
  return { max: maxRevisit, mean: meanRevisit };
}

function mutateConstellation(constellation, sigmaDeg = 1.0) {
  // Create a shallow mutated copy, perturbing RAAN and M by gaussian-like step
  return constellation.map((sat) => {
    const deltaRaan = (Math.random() * 2 - 1) * sigmaDeg;
    const deltaM = (Math.random() * 2 - 1) * sigmaDeg;
    return {
      ...sat,
      raan: ((sat.raan + deltaRaan) % 360 + 360) % 360,
      meanAnomaly: ((sat.meanAnomaly + deltaM) % 360 + 360) % 360,
    };
  });
}

function optimizeConstellation(initialConstellation, constellationPositionsFactory, points, timelineSeconds, iterations = 100) {
  // constellationPositionsFactory: (constellation) => precomputed positions structure matching computeRevisitTime input
  let best = initialConstellation.map((s) => ({ ...s }));
  let bestPositions = constellationPositionsFactory(best);
  let bestScoreObj = computeRevisitTime(bestPositions, points, timelineSeconds);
  let bestScore = bestScoreObj.max;

  for (let it = 0; it < iterations; it += 1) {
    const candidate = mutateConstellation(best, Math.max(0.1, 5 * (1 - it / iterations)));
    const candidatePositions = constellationPositionsFactory(candidate);
    const scoreObj = computeRevisitTime(candidatePositions, points, timelineSeconds);
    const score = scoreObj.max;
    if (score < bestScore) {
      best = candidate;
      bestPositions = candidatePositions;
      bestScoreObj = scoreObj;
      bestScore = score;
    }
  }

  return { constellation: best, stats: bestScoreObj, positions: bestPositions };
}

export const optimizationEngine = { computeRevisitTime, mutateConstellation, optimizeConstellation };

// QKD Calculations Module - Cosmica-inspired implementation
// Physical constants
const H_PLANCK = 6.62607015e-34; // J⋅s
const C_LIGHT = 2.99792458e8;     // m/s

/**
 * Calculate secure key rate for BB84 protocol
 * @param {Object} params - QKD parameters
 * @returns {Object} QKD performance metrics
 */
function calculateBB84Performance(params) {
  logCheckpoint('Calculating BB84 QKD performance', params);
  
  try {
    // Validate inputs
    const photonRate = validateNumber(params.photonRate, 0, 1e12, 'photonRate');
    const channelLossdB = validateNumber(params.channelLossdB, 0, 100, 'channelLossdB');
    const detectorEff = validateNumber(params.detectorEfficiency, 0, 1, 'detectorEfficiency');
    const darkCountRate = validateNumber(params.darkCountRate, 0, 1e6, 'darkCountRate');
    
    if (!photonRate || channelLossdB === null || !detectorEff || darkCountRate === null) {
      throw new Error('Invalid input parameters for QKD calculation');
    }
    
    // Convert channel loss from dB to linear transmittance
    const channelTransmittance = Math.pow(10, -channelLossdB / 10);
    logCheckpoint('Channel transmittance', channelTransmittance);
    
    // Calculate detection rate
    const mu = 0.5; // Mean photon number per pulse for weak coherent pulses
    const detectionRate = photonRate * channelTransmittance * detectorEff * Math.exp(-mu);
    
    // Calculate noise contributions
    const backgroundRate = darkCountRate;
    const totalNoiseRate = backgroundRate;
    
    // Calculate QBER (Quantum Bit Error Rate)
    const signalRate = detectionRate;
    const errorRate = totalNoiseRate / 2; // Noise causes 50% errors
    const qber = errorRate / (signalRate + errorRate);
    
    logCheckpoint('QBER calculated', qber);
    
    // Sifting efficiency for BB84 (after basis reconciliation)
    const siftingEfficiency = 0.5;
    const siftedKeyRate = (signalRate + errorRate) * siftingEfficiency;
    
    // Shannon entropy function
    const h = (x) => {
      if (x <= 0 || x >= 1) return 0;
      return -x * Math.log2(x) - (1 - x) * Math.log2(1 - x);
    };
    
    // Secure key rate using simplified formula
    // R_secure = R_sifted * [1 - h(QBER)] - leakage_EC
    // Where leakage_EC ≈ 1.16 * h(QBER) * R_sifted for practical error correction
    const informationReconciliationEfficiency = 1.16;
    const privacyAmplificationCost = h(qber) * siftedKeyRate;
    const errorCorrectionLeakage = informationReconciliationEfficiency * h(qber) * siftedKeyRate;
    
    let secureKeyRate = siftedKeyRate - privacyAmplificationCost - errorCorrectionLeakage;
    
    // Apply QBER threshold (typically ~11% for BB84)
    const qberThreshold = 0.11;
    if (qber > qberThreshold) {
      secureKeyRate = 0;
      logCheckpoint('QBER exceeds threshold, secure key rate = 0');
    }
    
    // Ensure non-negative
    secureKeyRate = Math.max(0, secureKeyRate);
    
    return {
      qber: qber * 100, // Convert to percentage
      rawKeyRate: siftedKeyRate / 1000, // Convert to kbps
      secureKeyRate: secureKeyRate / 1000, // Convert to kbps
      channelTransmittance: channelTransmittance,
      detectionRate: detectionRate,
      siftedKeyRate: siftedKeyRate,
      protocol: 'BB84'
    };
  } catch (error) {
    logError('BB84 calculation failed', error, params);
    return {
      qber: null,
      rawKeyRate: null,
      secureKeyRate: null,
      channelTransmittance: null,
      error: error.message
    };
  }
}

/**
 * Calculate secure key rate for E91 protocol (entanglement-based)
 * @param {Object} params - QKD parameters
 * @returns {Object} QKD performance metrics
 */
function calculateE91Performance(params) {
  logCheckpoint('Calculating E91 QKD performance', params);
  
  try {
    // Validate inputs
    const pairRate = validateNumber(params.photonRate / 2, 0, 1e12, 'pairRate'); // Entangled pairs
    const channelLossdB = validateNumber(params.channelLossdB, 0, 100, 'channelLossdB');
    const detectorEff = validateNumber(params.detectorEfficiency, 0, 1, 'detectorEfficiency');
    const darkCountRate = validateNumber(params.darkCountRate, 0, 1e6, 'darkCountRate');
    
    if (!pairRate || channelLossdB === null || !detectorEff || darkCountRate === null) {
      throw new Error('Invalid input parameters for E91 calculation');
    }
    
    // Convert channel loss
    const channelTransmittance = Math.pow(10, -channelLossdB / 10);
    
    // E91 requires coincidence detection on both sides
    // Simplified model: both photons must be detected
    const coincidenceRate = pairRate * Math.pow(channelTransmittance * detectorEff, 2);
    
    // Calculate QBER from dark counts and accidental coincidences
    const accidentalRate = darkCountRate * darkCountRate / (pairRate || 1);
    const qber = accidentalRate / (coincidenceRate + accidentalRate);
    
    logCheckpoint('E91 QBER calculated', qber);
    
    // Secure key rate for entanglement-based QKD
    const h = (x) => {
      if (x <= 0 || x >= 1) return 0;
      return -x * Math.log2(x) - (1 - x) * Math.log2(1 - x);
    };
    
    let secureKeyRate = coincidenceRate * (1 - 2 * h(qber));
    
    // QBER threshold for E91 (can tolerate slightly higher QBER)
    const qberThreshold = 0.15;
    if (qber > qberThreshold) {
      secureKeyRate = 0;
    }
    
    secureKeyRate = Math.max(0, secureKeyRate);
    
    return {
      qber: qber * 100,
      rawKeyRate: coincidenceRate / 1000,
      secureKeyRate: secureKeyRate / 1000,
      channelTransmittance: channelTransmittance,
      detectionRate: coincidenceRate,
      protocol: 'E91'
    };
  } catch (error) {
    logError('E91 calculation failed', error, params);
    return {
      qber: null,
      rawKeyRate: null,
      secureKeyRate: null,
      channelTransmittance: null,
      error: error.message
    };
  }
}

/**
 * Calculate continuous variable QKD performance
 * @param {Object} params - QKD parameters
 * @returns {Object} QKD performance metrics
 */
function calculateCVQKDPerformance(params) {
  logCheckpoint('Calculating CV-QKD performance', params);
  
  try {
    const modulationVariance = 10; // Shot noise units
    const channelLossdB = validateNumber(params.channelLossdB, 0, 100, 'channelLossdB');
    const detectorEff = validateNumber(params.detectorEfficiency, 0, 1, 'detectorEfficiency');
    const electronicNoise = 0.01; // Normalized electronic noise
    
    if (channelLossdB === null || !detectorEff) {
      throw new Error('Invalid input parameters for CV-QKD calculation');
    }
    
    const channelTransmittance = Math.pow(10, -channelLossdB / 10);
    const totalTransmittance = channelTransmittance * detectorEff;
    
    // Simplified CV-QKD rate formula
    // R ∝ log2(1 + SNR) - log2(1 + noise/signal)
    const snr = totalTransmittance * modulationVariance / (1 + electronicNoise);
    const excessNoise = electronicNoise / totalTransmittance;
    
    const symbolRate = 100e6; // 100 MHz symbol rate (example)
    let secureKeyRate = symbolRate * Math.max(0, Math.log2(1 + snr) - Math.log2(1 + excessNoise));
    
    // CV-QKD typically has lower QBER but is more sensitive to loss
    const effectiveQBER = excessNoise / (snr + excessNoise);
    
    return {
      qber: effectiveQBER * 100,
      rawKeyRate: symbolRate / 1000,
      secureKeyRate: secureKeyRate / 1000,
      channelTransmittance: channelTransmittance,
      snr: snr,
      protocol: 'CV-QKD'
    };
  } catch (error) {
    logError('CV-QKD calculation failed', error, params);
    return {
      qber: null,
      rawKeyRate: null,
      secureKeyRate: null,
      channelTransmittance: null,
      error: error.message
    };
  }
}

/**
 * Main QKD performance calculator - routes to appropriate protocol
 * @param {string} protocol - QKD protocol ('bb84', 'e91', 'cv-qkd')
 * @param {Object} params - QKD and link parameters
 * @returns {Object} QKD performance metrics
 */
function calculateQKDPerformance(protocol, params) {
  logCheckpoint(`Calculating QKD performance for protocol: ${protocol}`, params);
  
  switch (protocol.toLowerCase()) {
    case 'bb84':
      return calculateBB84Performance(params);
    case 'e91':
      return calculateE91Performance(params);
    case 'cv-qkd':
      return calculateCVQKDPerformance(params);
    default:
      logError('Unknown QKD protocol', new Error(`Protocol ${protocol} not supported`));
      return {
        error: `Unknown protocol: ${protocol}`
      };
  }
}

export const qkdCalculations = {
  calculateQKDPerformance,
  calculateBB84Performance,
  calculateE91Performance,
  calculateCVQKDPerformance
};

const EARTH_ROT_RATE = 7.2921150e-5; // rad/s
const SIDEREAL_DAY = 86164.0905; // s
const MIN_SEMI_MAJOR = EARTH_RADIUS_KM + 160; // ≈160 km minimum altitude
const GEO_ALTITUDE_KM = 35786; // GEO altitude used as realistic upper bound
const MAX_SEMI_MAJOR = EARTH_RADIUS_KM + GEO_ALTITUDE_KM; // ≈42 164 km
const CLOSURE_SURFACE_TOL_KM = 0.25;
const CLOSURE_CARTESIAN_TOL_KM = 0.1;

function normalizeAngle(angle) {
  const twoPi = Math.PI * 2;
  let normalized = angle % twoPi;
  if (normalized < 0) {
    normalized += twoPi;
  }
  return normalized;
}

function dateToJulian(date) {
  if (!(date instanceof Date) || Number.isNaN(date?.getTime?.())) {
    return null;
  }
  return date.getTime() / 86400000 + 2440587.5;
}

function gmstFromDate(date) {
  const jd = dateToJulian(date);
  if (!Number.isFinite(jd)) {
    return 0;
  }
  const d = jd - 2451545.0;
  const t = d / 36525.0;
  const gmstDeg = 280.46061837 + 360.98564736629 * d + 0.000387933 * t * t - (t * t * t) / 38710000;
  const gmstRad = gmstDeg * DEG2RAD;
  return normalizeAngle(gmstRad);
}

function solveKepler(meanAnomaly, eccentricity, tolerance = 1e-8, maxIter = 20) {
  let E = meanAnomaly;
  if (eccentricity > 0.8) {
    E = Math.PI;
  }
  for (let i = 0; i < maxIter; i++) {
    const f = E - eccentricity * Math.sin(E) - meanAnomaly;
    const fPrime = 1 - eccentricity * Math.cos(E);
    const delta = f / fPrime;
    E -= delta;
    if (Math.abs(delta) < tolerance) break;
  }
  return E;
}

function perifocalToEci(rPerifocal, i, raan, argPerigee) {
  const cosO = Math.cos(raan);
  const sinO = Math.sin(raan);
  const cosI = Math.cos(i);
  const sinI = Math.sin(i);
  const cosW = Math.cos(argPerigee);
  const sinW = Math.sin(argPerigee);

  const rotation = [
    [cosO * cosW - sinO * sinW * cosI, -cosO * sinW - sinO * cosW * cosI, sinO * sinI],
    [sinO * cosW + cosO * sinW * cosI, -sinO * sinW + cosO * cosW * cosI, -cosO * sinI],
    [sinW * sinI, cosW * sinI, cosI],
  ];

  const [x, y, z] = rPerifocal;
  return [
    rotation[0][0] * x + rotation[0][1] * y + rotation[0][2] * z,
    rotation[1][0] * x + rotation[1][1] * y + rotation[1][2] * z,
    rotation[2][0] * x + rotation[2][1] * y + rotation[2][2] * z,
  ];
}

function orbitalPositionVelocity(a, e, i, raan, argPerigee, meanAnomaly) {
  const n = Math.sqrt(MU_EARTH / (a ** 3));
  const M = (meanAnomaly + TWO_PI) % TWO_PI;
  const E = solveKepler(M, e);
  const cosE = Math.cos(E);
  const sinE = Math.sin(E);
  const sqrtOneMinusESq = Math.sqrt(1 - e * e);

  const trueAnomaly = Math.atan2(sqrtOneMinusESq * sinE, cosE - e);
  const r = a * (1 - e * cosE);
  const perifocalPosition = [
    r * Math.cos(trueAnomaly),
    r * Math.sin(trueAnomaly),
    0,
  ];

  const perifocalVelocity = [
    -Math.sqrt(MU_EARTH / (a * (1 - e * e))) * Math.sin(trueAnomaly),
    Math.sqrt(MU_EARTH / (a * (1 - e * e))) * (e + Math.cos(trueAnomaly)),
    0,
  ];

  const rEci = perifocalToEci(perifocalPosition, i, raan, argPerigee);
  const vEci = perifocalToEci(perifocalVelocity, i, raan, argPerigee);

  return { rEci, vEci, trueAnomaly, meanMotion: n, radius: r };
}

function rotateEciToEcef(rEci, vEci, gmst) {
  const cosT = Math.cos(gmst);
  const sinT = Math.sin(gmst);

  const rotation = [
    [cosT, sinT, 0],
    [-sinT, cosT, 0],
    [0, 0, 1],
  ];

  const rEcef = [
    rotation[0][0] * rEci[0] + rotation[0][1] * rEci[1] + rotation[0][2] * rEci[2],
    rotation[1][0] * rEci[0] + rotation[1][1] * rEci[1] + rotation[1][2] * rEci[2],
    rotation[2][0] * rEci[0] + rotation[2][1] * rEci[1] + rotation[2][2] * rEci[2],
  ];

  const omegaEarth = [0, 0, EARTH_ROT_RATE];
  const omegaCrossR = [
    omegaEarth[1] * rEcef[2] - omegaEarth[2] * rEcef[1],
    omegaEarth[2] * rEcef[0] - omegaEarth[0] * rEcef[2],
    omegaEarth[0] * rEcef[1] - omegaEarth[1] * rEcef[0],
  ];

  const vEcef = [
    rotation[0][0] * vEci[0] + rotation[0][1] * vEci[1] + rotation[0][2] * vEci[2] - omegaCrossR[0],
    rotation[1][0] * vEci[0] + rotation[1][1] * vEci[1] + rotation[1][2] * vEci[2] - omegaCrossR[1],
    rotation[2][0] * vEci[0] + rotation[2][1] * vEci[1] + rotation[2][2] * vEci[2] - omegaCrossR[2],
  ];

  return { rEcef, vEcef };
}

function ecefToLatLon(rEcef) {
  const [x, y, z] = rEcef;
  const lon = Math.atan2(y, x);
  const hyp = Math.sqrt(x * x + y * y);
  const lat = Math.atan2(z, hyp);
  const alt = Math.sqrt(x * x + y * y + z * z) - EARTH_RADIUS_KM;
  return { lat: lat * RAD2DEG, lon: lon * RAD2DEG, alt };
}

function ecefFromLatLon(latDeg, lonDeg, radiusKm = EARTH_RADIUS_KM) {
  const lat = latDeg * DEG2RAD;
  const lon = lonDeg * DEG2RAD;
  const cosLat = Math.cos(lat);
  return [
    radiusKm * cosLat * Math.cos(lon),
    radiusKm * cosLat * Math.sin(lon),
    radiusKm * Math.sin(lat),
  ];
}

function enuMatrix(latDeg, lonDeg) {
  const lat = latDeg * DEG2RAD;
  const lon = lonDeg * DEG2RAD;
  const sinLat = Math.sin(lat);
  const cosLat = Math.cos(lat);
  const sinLon = Math.sin(lon);
  const cosLon = Math.cos(lon);
  return [
    [-sinLon, cosLon, 0],
    [-sinLat * cosLon, -sinLat * sinLon, cosLat],
    [cosLat * cosLon, cosLat * sinLon, sinLat],
  ];
}

function losElevation(station, satEcef) {
  const stationEcef = ecefFromLatLon(station.lat, station.lon);
  const rel = [
    satEcef[0] - stationEcef[0],
    satEcef[1] - stationEcef[1],
    satEcef[2] - stationEcef[2],
  ];
  const transform = enuMatrix(station.lat, station.lon);
  const enu = [
    transform[0][0] * rel[0] + transform[0][1] * rel[1] + transform[0][2] * rel[2],
    transform[1][0] * rel[0] + transform[1][1] * rel[1] + transform[1][2] * rel[2],
    transform[2][0] * rel[0] + transform[2][1] * rel[1] + transform[2][2] * rel[2],
  ];
  const distance = Math.sqrt(rel[0] ** 2 + rel[1] ** 2 + rel[2] ** 2);
  const elevation = Math.atan2(enu[2], Math.sqrt(enu[0] ** 2 + enu[1] ** 2));
  const azimuth = Math.atan2(enu[0], enu[1]);
  return { distanceKm: distance, elevationDeg: elevation * RAD2DEG, azimuthDeg: (azimuth * RAD2DEG + 360) % 360 };
}

function dopplerFactor(station, satEcef, satVelEcef, wavelengthNm) {
  const stationEcef = ecefFromLatLon(station.lat, station.lon);
  const rel = [
    satEcef[0] - stationEcef[0],
    satEcef[1] - stationEcef[1],
    satEcef[2] - stationEcef[2],
  ];
  const distance = Math.sqrt(rel[0] ** 2 + rel[1] ** 2 + rel[2] ** 2);
  const unit = rel.map((c) => c / distance);
  const relVel = satVelEcef;
  const radialVelocity = relVel[0] * unit[0] + relVel[1] * unit[1] + relVel[2] * unit[2];
  const c = 299792.458; // km/s
  const factor = 1 / (1 - radialVelocity / c);
  const lambdaMeters = wavelengthNm * 1e-9;
  const observedWavelength = lambdaMeters * factor;
  return { factor, observedWavelength }; // Observed wavelength for reference
}

function geometricLoss(distanceKm, satAperture, groundAperture, wavelengthNm) {
  const lambda = wavelengthNm * 1e-9; // m
  const distanceM = distanceKm * 1000;
  const divergence = 1.22 * lambda / Math.max(satAperture, 1e-3);
  const spotRadius = Math.max(divergence * distanceM * 0.5, 1e-6);
  const captureRadius = groundAperture * 0.5;
  const coupling = Math.min(1, (captureRadius / spotRadius) ** 2);
  const lossDb = -10 * Math.log10(Math.max(coupling, 1e-9));
  return { coupling, lossDb };
}

function computeSemiMajorWithResonance(orbits, rotations) {
  const totalTime = (rotations / orbits) * SIDEREAL_DAY;
  const semiMajor = Math.cbrt((MU_EARTH * (totalTime / (2 * Math.PI)) ** 2));
  return semiMajor;
}

function propagateOrbit(settings, options = {}) {
  const {
    orbital,
    resonance,
    samplesPerOrbit,
    time: { timeline: currentTimeline },
  } = settings;
  const { samplesPerOrbit: samplesOverride } = options;

  const i = orbital.inclination * DEG2RAD;
  const raan = orbital.raan * DEG2RAD;
  const argPerigee = orbital.argPerigee * DEG2RAD;
  const meanAnomaly0 = orbital.meanAnomaly * DEG2RAD;

  const resonanceInfo = {
    requested: Boolean(resonance.enabled),
    applied: false,
    ratio: resonance.enabled ? { orbits: resonance.orbits, rotations: resonance.rotations } : null,
    warnings: [],
    semiMajorKm: null,
    deltaKm: null,
    targetPeriodSeconds: null,
    periodSeconds: null,
    perigeeKm: null,
    apogeeKm: null,
    closureSurfaceKm: null,
    closureCartesianKm: null,
    latDriftDeg: null,
    lonDriftDeg: null,
    closed: false,
  };

  let semiMajor = clamp(orbital.semiMajor, MIN_SEMI_MAJOR, MAX_SEMI_MAJOR);
  if (resonance.enabled) {
    const safeOrbits = Math.max(1, resonance.orbits || 1);
    const safeRotations = Math.max(1, resonance.rotations || 1);
    const targetPeriod = (safeRotations / safeOrbits) * SIDEREAL_DAY;
    resonanceInfo.targetPeriodSeconds = targetPeriod;
    let computedSemiMajor = computeSemiMajorWithResonance(safeOrbits, safeRotations);
    resonanceInfo.semiMajorKm = computedSemiMajor;
    let resonanceFeasible = true;

    if (computedSemiMajor < MIN_SEMI_MAJOR) {
      resonanceInfo.warnings.push(
        `Resonance ${safeOrbits}:${safeRotations} requires a semi-major axis below the operational minimum (${MIN_SEMI_MAJOR.toFixed(0)} km). ` +
        'Using the lower bound, so the ground track will not repeat exactly.'
      );
      computedSemiMajor = MIN_SEMI_MAJOR;
      resonanceFeasible = false;
    }
    if (computedSemiMajor > MAX_SEMI_MAJOR) {
      resonanceInfo.warnings.push(
        `Resonance ${safeOrbits}:${safeRotations} exceeds the maximum limit (${MAX_SEMI_MAJOR.toFixed(0)} km). ` +
        'Using the upper bound without an exact resonance.'
      );
      computedSemiMajor = MAX_SEMI_MAJOR;
      resonanceFeasible = false;
    }

    const deltaKm = Math.abs(computedSemiMajor - semiMajor);
    resonanceInfo.deltaKm = deltaKm;

    const perigeeTarget = computedSemiMajor * (1 - orbital.eccentricity);
    const apogeeTarget = computedSemiMajor * (1 + orbital.eccentricity);
    const perigeeWarning = 'Perigee drops below the Earth surface. Reduce eccentricity or adjust the resonance.';
    if (perigeeTarget <= EARTH_RADIUS_KM + 10) {
      resonanceInfo.warnings.push(perigeeWarning);
      resonanceFeasible = false;
    }

    const resonanceToleranceKm = 0.5;
    resonanceInfo.applied = resonanceFeasible && deltaKm <= resonanceToleranceKm;
  }

  semiMajor = clamp(semiMajor, MIN_SEMI_MAJOR, MAX_SEMI_MAJOR);
  const perigee = semiMajor * (1 - orbital.eccentricity);
  const apogee = semiMajor * (1 + orbital.eccentricity);
  resonanceInfo.perigeeKm = perigee;
  resonanceInfo.apogeeKm = apogee;
  const perigeeWarning = 'Perigee drops below the Earth surface. Reduce eccentricity or adjust the resonance.';
  if (perigee <= EARTH_RADIUS_KM + 10 && !resonanceInfo.warnings.includes(perigeeWarning)) {
    resonanceInfo.warnings.push(perigeeWarning);
  }

  const meanMotion = Math.sqrt(MU_EARTH / (semiMajor ** 3));
  const orbitPeriod = TWO_PI / meanMotion;
  resonanceInfo.periodSeconds = orbitPeriod;
  const totalOrbits = resonance.enabled ? Math.max(1, resonance.orbits) : 3;
  const totalTime = orbitPeriod * totalOrbits;
  const effectiveSamplesPerOrbit = Number.isFinite(samplesOverride)
    ? Math.max(2, samplesOverride)
    : samplesPerOrbit;
  const totalSamples = Math.max(2, Math.round(effectiveSamplesPerOrbit * totalOrbits));
  const dt = totalTime / (totalSamples - 1);

  const timeline = currentTimeline?.length === totalSamples
    ? currentTimeline
    : Array.from({ length: totalSamples }, (_, idx) => idx * dt);

  let epochDate = null;
  if (settings?.epoch) {
    const parsed = new Date(settings.epoch);
    if (!Number.isNaN(parsed.getTime())) {
      epochDate = parsed;
    }
  }
  if (!epochDate) {
    epochDate = new Date();
  }
  const gmstInitial = gmstFromDate(epochDate);

  let dotOmega = 0;
  let dotArgPerigee = 0;
  if (orbital.j2Enabled) {
    const rates = j2Propagator.secularRates(semiMajor, orbital.eccentricity, i);
    dotOmega = rates.dotOmega || 0;
    dotArgPerigee = rates.dotArgPerigee || 0;
  }

  const dataPoints = timeline.map((t) => {
    // apply secular drift to RAAN and argument of perigee
    const raan_t = raan + dotOmega * t;
    const argPerigee_t = argPerigee + dotArgPerigee * t;
    const M = (meanAnomaly0 + meanMotion * t) % TWO_PI;
    const { rEci, vEci } = orbitalPositionVelocity(semiMajor, orbital.eccentricity, i, raan_t, argPerigee_t, M);
    const gmst = normalizeAngle(gmstInitial + EARTH_ROT_RATE * t);
    const { rEcef, vEcef } = rotateEciToEcef(rEci, vEci, gmst);
    const geo = ecefToLatLon(rEcef);
    return {
      t,
      rEci,
      vEci,
      rEcef,
      vEcef,
      lat: geo.lat,
      lon: ((geo.lon + 540) % 360) - 180,
      alt: geo.alt,
      gmst,
    };
  });

  const groundTrack = dataPoints.map((p) => ({ lat: p.lat, lon: p.lon }));

  if (dataPoints.length >= 2) {
    const start = dataPoints[0];
    const end = dataPoints[dataPoints.length - 1];
    const diffX = end.rEcef[0] - start.rEcef[0];
    const diffY = end.rEcef[1] - start.rEcef[1];
    const diffZ = end.rEcef[2] - start.rEcef[2];
    const cartesianGap = Math.sqrt(diffX ** 2 + diffY ** 2 + diffZ ** 2);
    resonanceInfo.closureCartesianKm = cartesianGap;
    const surfaceGap = haversineDistance(start.lat, start.lon, end.lat, end.lon, EARTH_RADIUS_KM);
    resonanceInfo.closureSurfaceKm = surfaceGap;
    resonanceInfo.latDriftDeg = end.lat - start.lat;
    const lonDiff = ((end.lon - start.lon + 540) % 360) - 180;
    resonanceInfo.lonDriftDeg = lonDiff;
    if (resonance.enabled && surfaceGap > 0.5) {
  resonanceInfo.warnings.push(`Ground track does not close: surface offset of ${surfaceGap.toFixed(2)} km.`);
      resonanceInfo.applied = false;
    }
    if (resonance.enabled && resonanceInfo.applied) {
      const surfaceOk = Number.isFinite(surfaceGap) && surfaceGap <= CLOSURE_SURFACE_TOL_KM;
      const cartesianOk = Number.isFinite(cartesianGap) && cartesianGap <= CLOSURE_CARTESIAN_TOL_KM;
      resonanceInfo.closed = surfaceOk && cartesianOk;
      if (resonanceInfo.closed) {
        const lastIndex = dataPoints.length - 1;
        if (lastIndex > 0) {
          const startClone = {
            ...dataPoints[0],
            t: dataPoints[lastIndex].t,
            rEci: Array.isArray(dataPoints[0].rEci) ? [...dataPoints[0].rEci] : dataPoints[0].rEci,
            vEci: Array.isArray(dataPoints[0].vEci) ? [...dataPoints[0].vEci] : dataPoints[0].vEci,
            rEcef: Array.isArray(dataPoints[0].rEcef) ? [...dataPoints[0].rEcef] : dataPoints[0].rEcef,
            vEcef: Array.isArray(dataPoints[0].vEcef) ? [...dataPoints[0].vEcef] : dataPoints[0].vEcef,
          };
          dataPoints[lastIndex] = startClone;
          groundTrack[groundTrack.length - 1] = { lat: startClone.lat, lon: startClone.lon };
        }
      }
    }
  }

  return {
    semiMajor,
    orbitPeriod,
    totalTime,
    timeline,
    dataPoints,
    groundTrack,
    resonance: resonanceInfo,
  };
}

function computeStationMetrics(dataPoints, station, optical, settings = null, atmosphere = null) {
  const distanceKm = [];
  const elevationDeg = [];
  const lossDb = [];
  const doppler = [];
  const azimuthDeg = [];
  const r0_array = [];
  const fG_array = [];
  const theta0_array = [];
  const wind_array = [];
  const loss_aod_array = [];
  const loss_abs_array = [];

  const r0_zenith = atmosphere?.r0_zenith ?? 0.1;
  const fG_zenith = atmosphere?.fG_zenith ?? 30;
  const theta0_zenith = atmosphere?.theta0_zenith ?? 1.5;
  const wind_rms = atmosphere?.wind_rms ?? 15;
  const loss_aod_db = atmosphere?.loss_aod_db ?? 0;
  const loss_abs_db = atmosphere?.loss_abs_db ?? 0;

  if (!station || !dataPoints?.length) {
    return {
      distanceKm,
      elevationDeg,
      lossDb,
      doppler,
      azimuthDeg,
      r0_array,
      fG_array,
      theta0_array,
      wind_array,
      loss_aod_array,
      loss_abs_array,
    };
  }

  dataPoints.forEach((point) => {
    const los = losElevation(station, point.rEcef);
    const geom = geometricLoss(
      los.distanceKm,
      optical.satAperture,
      optical.groundAperture,
      optical.wavelength,
    );
    const dop = dopplerFactor(station, point.rEcef, point.vEcef, optical.wavelength);

    distanceKm.push(los.distanceKm);
    elevationDeg.push(los.elevationDeg);
    lossDb.push(geom.lossDb);
    doppler.push(dop.factor);
    azimuthDeg.push(los.azimuthDeg);

    let r0_actual = 0;
    let fG_actual = 0;
    let theta0_actual = 0;
    let aod_loss_actual = 0;
    let abs_loss_actual = 0;

    if (los.elevationDeg > 0) {
      const zenith_rad = (90 - los.elevationDeg) * DEG2RAD;
      const cos_zenith = Math.max(Math.cos(zenith_rad), 1e-6);
      const air_mass = 1 / cos_zenith;

      r0_actual = r0_zenith * cos_zenith ** (3 / 5);
      fG_actual = fG_zenith * cos_zenith ** (-9 / 5);
      theta0_actual = theta0_zenith * cos_zenith ** (8 / 5);
      aod_loss_actual = loss_aod_db * air_mass;
      abs_loss_actual = loss_abs_db * air_mass;
    }

    r0_array.push(r0_actual);
    fG_array.push(fG_actual);
    theta0_array.push(theta0_actual);
    wind_array.push(wind_rms);
    loss_aod_array.push(aod_loss_actual);
    loss_abs_array.push(abs_loss_actual);
  });

  return {
    distanceKm,
    elevationDeg,
    lossDb,
    doppler,
    azimuthDeg,
    r0_array,
    fG_array,
    theta0_array,
    wind_array,
loss_aod_array,
    loss_abs_array,
  };
}

function stationEcef(station) {
  return ecefFromLatLon(station.lat, station.lon);
}

const orbitConstants = {
  MU_EARTH,
  EARTH_RADIUS_KM,
  EARTH_ROT_RATE,
  SIDEREAL_DAY,
  MIN_SEMI_MAJOR,
  MAX_SEMI_MAJOR,
};

function ecefToEci(rEcef, gmst) {
    const cosT = Math.cos(gmst);
    const sinT = Math.sin(gmst);

    const rEci = [
        cosT * rEcef[0] - sinT * rEcef[1],
        sinT * rEcef[0] + cosT * rEcef[1],
        rEcef[2]
    ];
    return rEci;
}

function latLonToEci(lat, lon, alt, gmst) {
    const rEcef = ecefFromLatLon(lat, lon, EARTH_RADIUS_KM + (alt || 0));
    return ecefToEci(rEcef, gmst);
}

export const orbit = { constants: orbitConstants, propagateOrbit, computeStationMetrics, stationEcef, latLonToEci };

const MAX_BOUND = 500;

function clampInt(value, min, max) {
  const v = Math.round(Number(value) || 0);
  return Math.min(Math.max(v, min), max);
}

function aFromPeriod(periodSeconds) {
  return Math.pow(MU_EARTH * Math.pow(periodSeconds / TWO_PI, 2), 1 / 3);
}

function periodFromA(a) {
  if (!Number.isFinite(a) || a <= 0) return 0;
  return TWO_PI * Math.sqrt(Math.pow(a, 3) / MU_EARTH);
}

/**
 * Searches integer resonance pairs (j rotations, k orbits) within bounds, returning
 * candidates whose semi-major axis lies inside the tolerance interval.
 */
function searchResonances({
  targetA,
  toleranceKm = 0,
  minRotations,
  maxRotations,
  minOrbits,
  maxOrbits,
  siderealDay = SIDEREAL_DAY,
}) {
  const center = Number(targetA);
  if (!Number.isFinite(center) || center <= 0) {
    return [];
  }

  const tolerance = Math.max(0, Number(toleranceKm) || 0);
  const lowerBoundJ = clampInt(minRotations ?? 1, 1, MAX_BOUND);
  let upperBoundJ = clampInt(maxRotations ?? MAX_BOUND, 1, MAX_BOUND);
  if (upperBoundJ < lowerBoundJ) upperBoundJ = lowerBoundJ;

  const lowerBoundK = clampInt(minOrbits ?? 1, 1, MAX_BOUND);
  let upperBoundK = clampInt(maxOrbits ?? MAX_BOUND, 1, MAX_BOUND);
  if (upperBoundK < lowerBoundK) upperBoundK = lowerBoundK;

  const hits = [];

  for (let j = lowerBoundJ; j <= upperBoundJ; j++) {
    const periodFactor = j * siderealDay;
    for (let k = lowerBoundK; k <= upperBoundK; k++) {
      const period = periodFactor / k;
      const semiMajorKm = aFromPeriod(period);
      const deltaKm = semiMajorKm - center;
      if (Math.abs(deltaKm) <= tolerance) {
        hits.push({
          j,
          k,
          ratio: j / k,
          periodSec: period,
          semiMajorKm,
          deltaKm,
        });
      }
    }
  }

  hits.sort((a, b) => {
    if (a.j !== b.j) return a.j - b.j;
    return a.k - b.k;
  });

  return hits;
}

export const resonanceSolver = { SIDEREAL_DAY, searchResonances, aFromPeriod, periodFromA };