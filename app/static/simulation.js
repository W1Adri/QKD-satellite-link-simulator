// ---------------------------------------------------------------------------
// app/static/simulation.js
// ---------------------------------------------------------------------------
// Purpose : Thin simulation facade.  Physics calculations now live in the
//           Python backend (app/physics/).  This module preserves the same
//           exported interface that main.js expects but delegates heavy work
//           to POST /api/solve and keeps only lightweight client-side maths
//           (resonance search, Walker element generator, unit conversions).
//
// Exports :
//   orbit             – { constants, propagateOrbit, computeStationMetrics,
//                         stationEcef, latLonToEci }
//   resonanceSolver   – { SIDEREAL_DAY, searchResonances, aFromPeriod,
//                         periodFromA }
//   walkerGenerator   – { generateWalkerConstellation }
//   qkdCalculations   – { calculateQKDPerformance }
//   optimizationEngine
//   j2Propagator
//   sunSynchronousOrbit
// ---------------------------------------------------------------------------

import { clamp, validateNumber, haversineDistance } from './utils.js';
import { api } from './api.js';

const DEG2RAD = Math.PI / 180;
const RAD2DEG = 180 / Math.PI;
const TWO_PI = 2 * Math.PI;

// ── Orbital constants (shared by thin helpers) ──────────────────────────
const MU_EARTH          = 398600.4418;
const EARTH_RADIUS_KM   = 6371.0;
const EARTH_ROT_RATE    = 7.2921150e-5;
const SIDEREAL_DAY      = 86164.0905;
const J2                = 1.08263e-3;
const J3                = -2.53881e-6;
const J4                = -1.65597e-6;
const MAX_RESONANCE_SAMPLES = 5000;   // cap on grid points for a full repeat cycle
const MIN_SEMI_MAJOR    = EARTH_RADIUS_KM + 160;
const GEO_ALTITUDE_KM   = 35786;
const MAX_SEMI_MAJOR    = EARTH_RADIUS_KM + GEO_ALTITUDE_KM;

const orbitConstants = {
  MU_EARTH, EARTH_RADIUS_KM, EARTH_ROT_RATE,
  SIDEREAL_DAY, MIN_SEMI_MAJOR, MAX_SEMI_MAJOR,
};


// ── Kepler helpers (needed for fast client-side propagation fallback) ───

function solveKepler(M, e, tol = 1e-8, maxIter = 20) {
  let E = e > 0.8 ? Math.PI : M;
  for (let i = 0; i < maxIter; i++) {
    const d = (E - e * Math.sin(E) - M) / (1 - e * Math.cos(E));
    E -= d;
    if (Math.abs(d) < tol) break;
  }
  return E;
}

function perifocalToEci(rP, inc, raan, argP) {
  const cO = Math.cos(raan), sO = Math.sin(raan);
  const cI = Math.cos(inc),  sI = Math.sin(inc);
  const cW = Math.cos(argP), sW = Math.sin(argP);
  const R = [
    [cO*cW - sO*sW*cI, -cO*sW - sO*cW*cI, sO*sI],
    [sO*cW + cO*sW*cI, -sO*sW + cO*cW*cI, -cO*sI],
    [sW*sI,             cW*sI,              cI],
  ];
  return [
    R[0][0]*rP[0] + R[0][1]*rP[1],
    R[1][0]*rP[0] + R[1][1]*rP[1],
    R[2][0]*rP[0] + R[2][1]*rP[1],
  ];
}

function orbitalPosVel(a, e, inc, raan, argP, M) {
  const E = solveKepler(M, e);
  const cosE = Math.cos(E), sinE = Math.sin(E);
  const r = a * (1 - e * cosE);
  const nu = Math.atan2(Math.sqrt(1 - e*e) * sinE, cosE - e);
  const p = [r * Math.cos(nu), r * Math.sin(nu), 0];
  const n = Math.sqrt(MU_EARTH / (a*a*a));
  const vf = (a * n) / (1 - e * cosE);
  const v = [vf * (-sinE), vf * Math.sqrt(1 - e*e) * cosE, 0];
  return {
    r: perifocalToEci(p, inc, raan, argP),
    v: perifocalToEci(v, inc, raan, argP),
  };
}

function ecefFromLatLon(lat, lon, R = EARTH_RADIUS_KM) {
  const la = lat * DEG2RAD, lo = lon * DEG2RAD;
  return [R * Math.cos(la)*Math.cos(lo), R * Math.cos(la)*Math.sin(lo), R * Math.sin(la)];
}

function rotateToEcef(r, v, gmst) {
  const c = Math.cos(gmst), s = Math.sin(gmst);
  return {
    r: [ c*r[0]+s*r[1], -s*r[0]+c*r[1], r[2]],
    v: [ c*v[0]+s*v[1]+EARTH_ROT_RATE*(-s*r[0]+c*r[1]),
        -s*v[0]+c*v[1]-EARTH_ROT_RATE*( c*r[0]+s*r[1]), v[2]],
  };
}

function ecefToLatLon(r) {
  const x = r[0], y = r[1], z = r[2];
  const d = Math.sqrt(x*x + y*y + z*z);
  return {
    lat: Math.asin(z / d) * RAD2DEG,
    lon: Math.atan2(y, x) * RAD2DEG,
    alt: d - EARTH_RADIUS_KM,
  };
}

function gmstFromDate(date) {
  const jd = date.getTime() / 86400000 + 2440587.5;
  const d = jd - 2451545.0, t = d / 36525.0;
  const deg = 280.46061837 + 360.98564736629*d + 0.000387933*t*t - (t*t*t)/38710000;
  return ((deg * DEG2RAD) % TWO_PI + TWO_PI) % TWO_PI;
}


// ── Client-side propagation (fast fallback for real-time UI) ────────────

function j2SecularRates(a, e, inc, j3Enabled = false, j4Enabled = false) {
  const p = a * (1 - e*e);
  const n = Math.sqrt(MU_EARTH / (a*a*a));
  const rp = EARTH_RADIUS_KM / p;
  const k = -1.5 * n * J2 * rp * rp;
  const cosI = Math.cos(inc);
  const s2 = Math.sin(inc) ** 2;
  const eta = Math.sqrt(Math.max(0, 1 - e*e));
  let dotRaan = k * cosI;
  let dotArgPerigee = k * (-2.5 * s2 + 2);
  // J3 (odd → long-period approx, inactive at e≈0) and J4 (even → secular).
  // Mirrors propagation.py:compute_enhanced_secular_rates (Kozai 1959).
  if (j3Enabled && Math.abs(e) > 1e-6) {
    const f3 = 0.5 * J3 * Math.pow(rp, 3) * n * rp;
    dotArgPerigee += f3 * Math.sin(inc) * (5 * cosI * cosI - 1) / e;
  }
  if (j4Enabled) {
    const e2 = e * e;
    const rp4 = Math.pow(rp, 4);
    dotRaan += (15 / 32) * n * J4 * rp4 * cosI * (8 + 12 * e2 - (14 + 21 * e2) * s2);
    dotArgPerigee += -(15 / 128) * n * J4 * rp4 *
      (64 + 72 * e2 - (248 + 252 * e2) * s2 + (196 + 189 * e2) * s2 * s2);
  }
  return {
    dotRaan,
    dotArgPerigee,
    // ΔṀ = (3/4) n J₂ (R⊕/p)² √(1−e²) (2 − 3sin²i)  (Vallado 2001, Eq. 9-42)
    dotMeanAnomaly: k * eta * (1.5 * s2 - 1.0),
  };
}

// Semi-major axis of a repeating ground track: k revolutions in j (sidereal)
// days. Keplerian seed (J2 off): a = cbrt(MU·(T/2π)²), T = (j/k)·SIDEREAL_DAY.
// With J2 on, the track only closes when the nodal motion matches Earth's
// rotation relative to the regressing node (Vallado 2013, Eq. 11-?, repeat
// ground track):  k·(ω_E − Ω̇) = j·(n + Ṁ + ω̇).  Since Ω̇, ω̇, Ṁ and n all
// depend on a, solve implicitly by fixed-point iteration (J2 terms are small,
// converges in a few steps). Reduces exactly to the Keplerian form at J2 = 0.
function solveRepeatGroundTrackA(k, j, e, inc, opts = {}) {
  const { j2 = true, j3 = false, j4 = false } = opts;
  let a = aFromPeriod((j / k) * SIDEREAL_DAY);
  if (!j2) return a;
  for (let it = 0; it < 50; it++) {
    const { dotRaan, dotArgPerigee, dotMeanAnomaly } = j2SecularRates(a, e, inc, j3, j4);
    // Required Keplerian mean motion so the ground track closes.
    const nReq = (k / j) * (EARTH_ROT_RATE - dotRaan) - dotMeanAnomaly - dotArgPerigee;
    if (!(nReq > 0)) break;
    const aNew = Math.cbrt(MU_EARTH / (nReq * nReq));
    const converged = Math.abs(aNew - a) < 1e-9;
    a = aNew;
    if (converged) break;
  }
  return a;
}

function propagateOrbit(settings, options = {}) {
  const { orbital, resonance, samplesPerOrbit: baseSPO } = settings;
  const samplesPerOrbit = options.samplesPerOrbit || baseSPO || 180;

  const inc = (orbital.inclination ?? 53) * DEG2RAD;
  const raan0 = (orbital.raan ?? 0) * DEG2RAD;
  const arg0  = (orbital.argPerigee ?? 0) * DEG2RAD;
  const M0    = (orbital.meanAnomaly ?? 0) * DEG2RAD;
  const e     = orbital.eccentricity ?? 0.001;

  let a = clamp(orbital.semiMajor ?? 6771, MIN_SEMI_MAJOR, MAX_SEMI_MAJOR);

  // Resonance adjustment
  const resonanceInfo = {
    requested: Boolean(resonance?.enabled),
    applied: false, ratio: null, warnings: [],
    semiMajorKm: null, deltaKm: null,
    targetPeriodSeconds: null, periodSeconds: null,
    perigeeKm: null, apogeeKm: null,
    closureSurfaceKm: null, closureCartesianKm: null,
    latDriftDeg: null, lonDriftDeg: null, closed: false,
  };
  if (resonance?.enabled) {
    const sK = Math.max(1, resonance.orbits || 1);
    const sJ = Math.max(1, resonance.rotations || 1);
    const tp = (sJ / sK) * SIDEREAL_DAY;
    resonanceInfo.targetPeriodSeconds = tp;
    const aRes = solveRepeatGroundTrackA(sK, sJ, e, inc, {
      j2: orbital.j2Enabled !== false, j3: orbital.j3Enabled, j4: orbital.j4Enabled,
    });
    if (aRes >= MIN_SEMI_MAJOR && aRes <= MAX_SEMI_MAJOR) {
      resonanceInfo.deltaKm = aRes - a;
      a = aRes;
      resonanceInfo.applied = true;
      resonanceInfo.ratio = { orbits: sK, rotations: sJ };
    }
    resonanceInfo.semiMajorKm = a;
  }

  const n = Math.sqrt(MU_EARTH / (a*a*a));

  const j2 = orbital.j2Enabled !== false;
  let dotRaan = 0, dotArg = 0, dotMA = 0;
  if (j2) {
    const rates = j2SecularRates(a, e, inc, orbital.j3Enabled, orbital.j4Enabled);
    dotRaan = rates.dotRaan;
    dotArg  = rates.dotArgPerigee;
    dotMA   = rates.dotMeanAnomaly;
  }

  // Time grid spans whole orbital cycles. For a repeating ground track the
  // cycle is the nodal (draconitic) period 2π/(n + Ṁ + ω̇), so that
  // `rotations` nodal days = `orbits` revolutions close exactly; otherwise the
  // Keplerian period is used. (Keplerian when J2 off — rates are zero.)
  const nodalRate = n + dotMA + dotArg;
  const period = (resonanceInfo.applied && nodalRate > 0) ? TWO_PI / nodalRate : TWO_PI / n;
  // A repeating ground track only closes after exactly `orbits` (k) revolutions,
  // so span the full repeat cycle when applied; cap samples for large k.
  const totalOrbits = resonanceInfo.applied
    ? Math.max(1, Math.round(resonanceInfo.ratio.orbits))
    : (settings.time?.totalOrbits || 3);
  const totalTime = period * totalOrbits;
  const spo = resonanceInfo.applied
    ? Math.max(30, Math.min(samplesPerOrbit, Math.floor(MAX_RESONANCE_SAMPLES / totalOrbits)))
    : samplesPerOrbit;
  const totalSamples = Math.max(2, spo * totalOrbits);
  const dt = totalTime / (totalSamples - 1);

  const epoch = settings.epoch ? new Date(settings.epoch) : new Date();
  const gmst0 = gmstFromDate(epoch);

  const timeline = [], dataPoints = [], groundTrack = [];
  for (let si = 0; si < totalSamples; si++) {
    const t = si * dt;
    timeline.push(t);
    const raanT = raan0 + dotRaan * t;
    const argT  = arg0  + dotArg  * t;
    const M = (M0 + (n + dotMA) * t) % TWO_PI;
    const { r: rEci, v: vEci } = orbitalPosVel(a, e, inc, raanT, argT, M);
    const gmst = (gmst0 + EARTH_ROT_RATE * t) % TWO_PI;
    const ecef = rotateToEcef(rEci, vEci, gmst);
    const geo = ecefToLatLon(ecef.r);
    dataPoints.push({
      t, rEci, vEci, rEcef: ecef.r, vEcef: ecef.v,
      lat: geo.lat, lon: geo.lon, alt: geo.alt, gmst,
    });
    groundTrack.push({ lat: geo.lat, lon: geo.lon });
  }

  // Closure check
  if (resonanceInfo.applied && dataPoints.length >= 2) {
    const first = dataPoints[0], last = dataPoints[dataPoints.length - 1];
    resonanceInfo.closureSurfaceKm = haversineDistance(first.lat, first.lon, last.lat, last.lon, EARTH_RADIUS_KM);
    const dx = last.rEcef[0]-first.rEcef[0], dy = last.rEcef[1]-first.rEcef[1], dz = last.rEcef[2]-first.rEcef[2];
    resonanceInfo.closureCartesianKm = Math.sqrt(dx*dx+dy*dy+dz*dz);
    resonanceInfo.latDriftDeg = last.lat - first.lat;
    resonanceInfo.lonDriftDeg = last.lon - first.lon;
    resonanceInfo.closed = resonanceInfo.closureSurfaceKm < 0.25 && resonanceInfo.closureCartesianKm < 0.1;
    resonanceInfo.periodSeconds = period;
    resonanceInfo.perigeeKm = a*(1-e) - EARTH_RADIUS_KM;
    resonanceInfo.apogeeKm  = a*(1+e) - EARTH_RADIUS_KM;
  }

  return {
    semiMajor: a, orbitPeriod: period, totalTime,
    timeline, dataPoints, groundTrack,
    resonance: resonanceInfo,
  };
}


// ── Station metrics (LOS, geometric loss, Doppler, atmosphere) ──────────

function enuMatrix(lat, lon) {
  const la = lat * DEG2RAD, lo = lon * DEG2RAD;
  const sl = Math.sin(la), cl = Math.cos(la);
  const so = Math.sin(lo), co = Math.cos(lo);
  return [[-so,co,0],[-sl*co,-sl*so,cl],[cl*co,cl*so,sl]];
}

function losElevation(station, rEcef) {
  const altKm = (station.altitude ?? 0) / 1000;
  const sE = ecefFromLatLon(station.lat, station.lon, EARTH_RADIUS_KM + altKm);
  const rel = [rEcef[0]-sE[0], rEcef[1]-sE[1], rEcef[2]-sE[2]];
  const M = enuMatrix(station.lat, station.lon);
  const enu = M.map(row => row[0]*rel[0]+row[1]*rel[1]+row[2]*rel[2]);
  const dist = Math.sqrt(rel[0]**2+rel[1]**2+rel[2]**2);
  const elev = Math.atan2(enu[2], Math.sqrt(enu[0]**2+enu[1]**2));
  const az = Math.atan2(enu[0], enu[1]);
  return { distanceKm: dist, elevationDeg: elev*RAD2DEG, azimuthDeg: ((az*RAD2DEG)+360)%360 };
}

function dopplerFactor(station, rEcef, vEcef, wavNm) {
  const altKm = (station.altitude ?? 0) / 1000;
  const sE = ecefFromLatLon(station.lat, station.lon, EARTH_RADIUS_KM + altKm);
  const rel = [rEcef[0]-sE[0], rEcef[1]-sE[1], rEcef[2]-sE[2]];
  const d = Math.sqrt(rel[0]**2+rel[1]**2+rel[2]**2);
  const u = rel.map(c => c/d);
  const vr = vEcef[0]*u[0]+vEcef[1]*u[1]+vEcef[2]*u[2];
  const f = 1 / (1 - vr / 299792.458);
  return { factor: f, observedWavelength: wavNm*1e-9*f };
}

function geometricLoss(distKm, satAp, gndAp, wavNm) {
  const lam = wavNm*1e-9, dM = distKm*1000;
  const div = 1.22*lam/Math.max(satAp,1e-3);
  const spot = Math.max(div*dM*0.5,1e-6);
  const cap = gndAp*0.5;
  const coup = Math.min(1,(cap/spot)**2);
  return { coupling: coup, lossDb: -10*Math.log10(Math.max(coup,1e-9)) };
}

// ── Link Budget helpers (client-side mirror of link_budget.py) ──────────

function _erfinvApprox(x) {
  // Winitzki approximation + one Newton step
  const a = 0.147;
  const lnTerm = Math.log(1 - x * x);
  const p1 = 2 / (Math.PI * a) + lnTerm / 2;
  let y = Math.sign(x) * Math.sqrt(Math.sqrt(p1 * p1 - lnTerm / a) - p1);
  // Newton refinement
  const erfY = _erf(y);
  const dErf = (2 / Math.sqrt(Math.PI)) * Math.exp(-y * y);
  if (Math.abs(dErf) > 1e-30) y -= (erfY - x) / dErf;
  return y;
}

function _erf(x) {
  // Abramowitz & Stegun approximation (max error ~1.5e-7)
  const sign = x < 0 ? -1 : 1;
  const t = 1 / (1 + 0.3275911 * Math.abs(x));
  const poly = t * (0.254829592 + t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429))));
  return sign * (1 - poly * Math.exp(-x * x));
}

function atmLossDb(zenithAodDb, zenithAbsDb, elevDeg) {
  if (elevDeg <= 0) return 0;
  const zenRad = (90 - elevDeg) * DEG2RAD;
  const am = 1 / Math.max(Math.cos(zenRad), 1e-6);
  return (zenithAodDb + zenithAbsDb) * am;
}

function pointingLossDb(sigmaUrad, satAp, wavNm) {
  if (sigmaUrad <= 0) return 0;
  const lam = wavNm * 1e-9;
  const thetaDiv = 1.22 * lam / Math.max(satAp, 1e-6);
  const ratio = (sigmaUrad * 1e-6) / thetaDiv;
  const lossLin = Math.exp(-2 * ratio * ratio);
  return Math.max(-10 * Math.log10(Math.max(lossLin, 1e-30)), 0);
}

function scintillationLossDb(wavNm, zenDeg, distKm, cn2Layers, p0, linkDirection, satAltKm, hGs) {
  // cn2Layers: [{h, cn2, dh}]
  if (!cn2Layers || !cn2Layers.length) return 0;
  const lam = wavNm * 1e-9;
  const k = 2 * Math.PI / lam;
  const zenRad = zenDeg * DEG2RAD;
  const secZ = 1 / Math.max(Math.cos(zenRad), 1e-6);
  const isUplink = (linkDirection || '').toLowerCase() === 'uplink';
  const h_gs = hGs ?? 0;  // ground station altitude (m)
  const H_sat = (satAltKm || 550) * 1000;  // satellite altitude (m)
  let integral = 0;
  for (const layer of cn2Layers) {
    const h = layer.h;  // altitude in metres
    if (isUplink) {
      // Spherical wave kernel: [(h-h_gs)(H_sat-h)/(H_sat-h_gs)]^(5/6)
      const num = (h - h_gs) * (H_sat - h);
      const den = H_sat - h_gs;
      const arg = (num > 0 && den > 0) ? num / den : 0;
      integral += layer.cn2 * Math.pow(arg, 5 / 6) * layer.dh;
    } else {
      // Plane wave kernel: (h - h_gs)^(5/6)
      const arg = Math.max(h - h_gs, 0);
      integral += layer.cn2 * Math.pow(arg, 5 / 6) * layer.dh;
    }
  }
  const rytov = 2.25 * (k ** (7 / 6)) * (secZ ** (11 / 6)) * integral;
  if (rytov <= 0) return 0;
  const sigmaI2 = Math.exp(rytov) - 1;
  const sigmaI = Math.sqrt(Math.max(sigmaI2, 1e-30));
  const clampP0 = Math.max(Math.min(p0, 0.5), 1e-9);
  const z2 = _erfinvApprox(2 * clampP0 - 1);
  const fadeDb = -10 * Math.log10(Math.exp(2 * sigmaI * z2 + sigmaI2));
  return Math.max(fadeDb, 0);
}

/**
 * Beam wander variance (rad^2) -- uplink only, returns 0 for downlink.
 * Source: Andrews & Phillips (2005) Eq. 12.46; Vasylyev et al., PRL 117, 090501 (2016).
 */
function beamWanderVarianceRad2(elevDeg, wavNm, txApertureM, r0M, hSatM, linkDirection) {
  if ((linkDirection || '').toLowerCase() !== 'uplink') return 0;
  if (elevDeg <= 0 || r0M <= 0 || txApertureM <= 0) return 0;
  const lam = wavNm * 1e-9;
  const zenRad = (90 - elevDeg) * DEG2RAD;
  const secZ = 1 / Math.max(Math.cos(zenRad), 1e-3);
  const W0 = txApertureM / 2;
  const L = hSatM * secZ;
  return 0.54 * L * L * Math.pow(secZ, 5 / 3) * Math.pow(2 * W0 / r0M, -1 / 3) * Math.pow(lam / (2 * W0), 2);
}

/**
 * Combined PAT + beam wander fading penalty (dB).
 * Adds beam wander in quadrature for uplink.
 * Source: Bourgoin et al., Opt. Express 21, 23 (2013); Andrews & Phillips (2005).
 */
function combinedPointingFadingDb(patJitter1sigmaUrad, bwRmsUrad, divergenceRad, linkDirection) {
  const sigmaPat = patJitter1sigmaUrad * 1e-6;
  const sigmaBw = bwRmsUrad * 1e-6;
  let sigmaTotal;
  if ((linkDirection || '').toLowerCase() === 'uplink') {
    sigmaTotal = Math.sqrt(sigmaPat * sigmaPat + sigmaBw * sigmaBw);
  } else {
    sigmaTotal = sigmaPat;
  }
  if (sigmaTotal <= 0 || divergenceRad <= 0) return 0;
  const ratio2 = Math.pow(sigmaTotal / divergenceRad, 2);
  const meanT = 1 / (1 + 8 * ratio2);
  return -10 * Math.log10(Math.max(meanT, 1e-15));
}

/**
 * Solar sky radiance (W/m^2/sr/um) from zenith angle.
 * Source: Pirandola et al., Adv. Opt. Photon. 12, 1012 (2020).
 */
function solarSkyRadianceWm2srUm(solarZenithDeg) {
  if (solarZenithDeg >= 90) return 0;
  const cosZ = Math.cos(solarZenithDeg * DEG2RAD);
  const airmass = 1 / Math.max(cosZ, 0.1);
  const tau = 0.1;
  const Ilambda = 0.48 * Math.exp(-tau * airmass);
  return Ilambda * 0.1 * cosZ / Math.PI * 1e3;
}

function backgroundNoiseCps(Hrad, fovMrad, deltaLambda, gndAp, wavNm) {
  if (Hrad <= 0 || fovMrad <= 0 || deltaLambda <= 0) return 0;
  const h = 6.62607015e-34;
  const c = 299792458;
  const lam = wavNm * 1e-9;
  const Ephoton = h * c / lam;
  const omega = Math.PI * (fovMrad * 1e-3) ** 2;
  const Ar = Math.PI * (gndAp / 2) ** 2;
  const dlam = deltaLambda * 1e-3; // nm → µm
  return (Hrad * omega * Ar * dlam) / Ephoton;
}

function computeStationMetrics(dataPoints, station, optical, state, atmosphereData) {
  const out = {
    distanceKm:[], elevationDeg:[], lossDb:[], doppler:[], azimuthDeg:[],
    r0_array:[], fG_array:[], theta0_array:[], wind_array:[],
    loss_aod_array:[], loss_abs_array:[],
    // Link budget component arrays
    geoLossDb:[], atmLossDb:[], pointingLossDb:[], scintLossDb:[],
    fixedLossDb:[], totalLossDb:[], couplingTotal:[], backgroundCps:[],
    // Sun / eclipse arrays (computed server-side; placeholders here)
    sunCoreAngleDeg:[], eclipsed:[], sunExcluded:[],
    // Received power / link margin
    rxPowerDbm:[], linkMarginDb:[], linkEstablished:[],
  };
  if (!station || !dataPoints?.length) return out;
  const satAp = optical?.satAperture ?? 0.6;
  const gndAp = optical?.groundAperture ?? station.aperture_m ?? 1.0;
  const wav = optical?.wavelength ?? 810;
  const r0z = atmosphereData?.r0_zenith ?? 0.1;
  const fGz = atmosphereData?.fG_zenith ?? 30;
  const th0z = atmosphereData?.theta0_zenith ?? 1.5;
  const wRms = atmosphereData?.wind_rms ?? 15;
  const aodZ = atmosphereData?.loss_aod_db ?? 0;
  const absZ = atmosphereData?.loss_abs_db ?? 0;

  // Link budget config from state
  const lb = state?.linkBudget ?? {};
  const linkDir = lb.linkDirection ?? 'downlink';
  const isUplink = linkDir.toLowerCase() === 'uplink';
  const lbAod = lb.atmZenithAod ?? 0;
  const lbAbs = lb.atmZenithAbs ?? 0;
  const lbPointUrad = lb.pointingErrorUrad ?? 0;
  const lbPatFading = lb.patFadingEnabled ?? true;  // true → Rayleigh-averaged, false → deterministic worst-case
  const lbFixed = lb.fixedOpticsLoss ?? 0;
  const lbScintOn = lb.scintillationEnabled ?? false;
  const lbScintP0 = lb.scintillationP0 ?? 0.01;
  const lbBgOn = lb.backgroundEnabled ?? false;
  const lbBgHrad = lb.bgRadiance ?? 0;
  const lbBgFov = lb.bgFovMrad ?? 0;
  const lbBgDl = lb.bgDeltaLambda ?? 0;
  const minElevDeg = lb.minElevationDeg ?? 0;

  // Aperture roles depend on link direction
  // Uplink: transmitter = ground, receiver = satellite
  // Downlink: transmitter = satellite, receiver = ground
  const txAp = isUplink ? gndAp : satAp;
  const rxAp = isUplink ? satAp : gndAp;

  // Build Cn2 layers from atmosphere data if available
  let cn2Layers = null;
  if (lbScintOn && atmosphereData?.cn2_profile) {
    const p = atmosphereData.cn2_profile;
    if (Array.isArray(p.heights) && Array.isArray(p.cn2_values)) {
      cn2Layers = [];
      for (let i = 0; i < p.heights.length; i++) {
        const h = p.heights[i];
        let dh;
        if (i === 0) dh = (p.heights.length > 1) ? (p.heights[1] - p.heights[0]) : 100;
        else dh = p.heights[i] - p.heights[i - 1];
        cn2Layers.push({ h, cn2: p.cn2_values[i], dh: Math.max(dh, 1) });
      }
    }
  }

  for (const pt of dataPoints) {
    const los = losElevation(station, pt.rEcef);
    const hasLos = los.elevationDeg > minElevDeg;  // Minimum elevation check
    
    out.distanceKm.push(hasLos ? los.distanceKm : null);
    out.elevationDeg.push(hasLos ? los.elevationDeg : null);
    out.azimuthDeg.push(los.azimuthDeg);
    
    // When no line of sight, push null for all link-dependent metrics
    if (!hasLos) {
      out.doppler.push(null);
      out.geoLossDb.push(null);
      out.atmLossDb.push(null);
      out.pointingLossDb.push(null);
      out.scintLossDb.push(null);
      out.fixedLossDb.push(null);
      out.totalLossDb.push(null);
      out.lossDb.push(null);
      out.couplingTotal.push(null);
      out.backgroundCps.push(null);
      out.sunCoreAngleDeg.push(180);
      out.eclipsed.push(false);
      out.sunExcluded.push(false);
      out.rxPowerDbm.push(null);
      out.linkMarginDb.push(null);
      out.linkEstablished.push(false);
      out.r0_array.push(null);
      out.fG_array.push(null);
      out.theta0_array.push(null);
      out.wind_array.push(null);
      out.loss_aod_array.push(null);
      out.loss_abs_array.push(null);
      continue;
    }
    
    const gl  = geometricLoss(los.distanceKm, txAp, rxAp, wav);
    const dop = dopplerFactor(station, pt.rEcef, pt.vEcef, wav);
    out.doppler.push(dop.factor);

    // Satellite altitude from ECEF position (km)
    const rEcef = pt.rEcef;
    const rMag = Math.sqrt(rEcef[0] ** 2 + rEcef[1] ** 2 + rEcef[2] ** 2);
    const satAltKm = rMag - 6371;  // approximate Earth radius in km

    // Geometric loss (dB)
    const gLoss = gl.lossDb;
    out.geoLossDb.push(gLoss);

    // Atmospheric loss (dB)
    const aLoss = atmLossDb(lbAod, lbAbs, los.elevationDeg);
    out.atmLossDb.push(aLoss);

    // Pointing / PAT fading (dB) — uses transmitter aperture
    // Beam wander + combined fading when pointing error > 0
    // Source: Andrews & Phillips (2005) Eq. 12.46; Bourgoin et al. (2013)
    const lamM = wav * 1e-9;
    const divRad = 1.22 * lamM / Math.max(txAp, 1e-3);
    const zenRadPt = (90 - los.elevationDeg) * DEG2RAD;
    const czPt = Math.max(Math.cos(zenRadPt), 1e-6);
    const r0Pt = r0z * Math.pow(czPt, 3 / 5);  // slant-path Fried parameter (m)
    const satAltM = satAltKm * 1000;
    const bwRad2 = beamWanderVarianceRad2(los.elevationDeg, wav, txAp, r0Pt, satAltM, linkDir);
    const bwRmsUrad = Math.sqrt(Math.max(bwRad2, 0)) * 1e6;
    let pLoss = 0;
    if (lbPointUrad > 0) {
      pLoss = lbPatFading
        ? combinedPointingFadingDb(lbPointUrad, bwRmsUrad, divRad, linkDir)  // Rayleigh-averaged + beam wander
        : pointingLossDb(lbPointUrad, txAp, wav);                            // deterministic worst-case
    }
    out.pointingLossDb.push(pLoss);

    // Scintillation loss (dB) - hasLos already checked at start
    let sLoss = 0;
    if (lbScintOn && cn2Layers) {
      const zenDeg = 90 - los.elevationDeg;
      sLoss = scintillationLossDb(wav, zenDeg, los.distanceKm, cn2Layers, lbScintP0, linkDir, satAltKm, station.altitude ?? 0);
    }
    out.scintLossDb.push(sLoss);

    // Fixed optics loss (dB)
    out.fixedLossDb.push(lbFixed);

    // Total link loss (dB)
    const tLoss = gLoss + aLoss + pLoss + sLoss + lbFixed;
    out.totalLossDb.push(tLoss);
    out.lossDb.push(tLoss); // overwrite lossDb with total

    // Coupling
    out.couplingTotal.push(Math.pow(10, -tLoss / 10));

    // Background noise (cps) — dynamic solar radiance when available
    // Approximate solar zenith for day/night gating (no astronomy-engine needed)
    // Solar declination: Spencer (1971), "Fourier series representation of the
    // position of the sun", Search 2(5), accurate to ~0.035 deg.
    let bgCps = 0;
    if (lbBgOn) {  // hasLos is already checked at start of loop
      let solarZenDeg = 90; // default: horizon (no solar contribution)
      const stationLat = station.lat ?? 0;
      const stationLon = station.lon ?? 0;
      const epochMs = state?.epoch ? new Date(state.epoch).getTime() : Date.now();
      const ptMs = epochMs + (pt.t ?? 0) * 1000;
      const d = new Date(ptMs);
      const dayOfYear = Math.floor((d - new Date(d.getFullYear(), 0, 0)) / 86400000);
      // Solar declination — Spencer (1971)
      const B = 2 * Math.PI * (dayOfYear - 1) / 365;
      const decl = 0.006918 - 0.399912 * Math.cos(B) + 0.070257 * Math.sin(B)
                 - 0.006758 * Math.cos(2 * B) + 0.000907 * Math.sin(2 * B);
      // Hour angle from UTC time and station longitude (equation of time omitted;
      // up to ~16 min offset — acceptable for radiance scaling)
      const utcH = d.getUTCHours() + d.getUTCMinutes() / 60 + d.getUTCSeconds() / 3600;
      const localSolarTime = utcH + stationLon / 15.0;
      const hourAngleRad = (localSolarTime - 12.0) * Math.PI / 12;
      // Solar zenith angle
      const latRad = stationLat * DEG2RAD;
      const cosZ = Math.sin(latRad) * Math.sin(decl)
                 + Math.cos(latRad) * Math.cos(decl) * Math.cos(hourAngleRad);
      solarZenDeg = Math.acos(Math.max(-1, Math.min(1, cosZ))) / DEG2RAD;

      let effectiveHrad = lbBgHrad; // static fallback (nighttime or user-configured)
      // Use dynamic solar model when sun is above horizon
      // Source: Pirandola et al., Adv. Opt. Photon. 12, 1012 (2020)
      const dynamicHrad = solarSkyRadianceWm2srUm(solarZenDeg);
      if (dynamicHrad > 0) {
        effectiveHrad = dynamicHrad;
      }
      bgCps = backgroundNoiseCps(effectiveHrad, lbBgFov, lbBgDl, rxAp, wav);
    }
    out.backgroundCps.push(bgCps);

    // Sun/eclipse: needs astronomy-engine (only available server-side)
    // Client pushes placeholders; real values come from /api/solve
    out.sunCoreAngleDeg.push(180);
    out.eclipsed.push(false);
    out.sunExcluded.push(false);

    // Link margin (client-side computation)
    const txPow = lb.txPowerDbm ?? 30;
    const rxSens = lb.rxSensitivityDbm ?? -90;
    const rxPow = txPow - tLoss;
    const margin = rxPow - rxSens;
    out.rxPowerDbm.push(rxPow);
    out.linkMarginDb.push(margin);
    out.linkEstablished.push(margin >= 0);

    // Atmosphere zenith scaling (only for LoS - already checked with hasLos)
    const zen = (90 - los.elevationDeg) * DEG2RAD;
    const cz = Math.max(Math.cos(zen), 1e-6);
    const am = 1/cz;
    out.r0_array.push(r0z * cz**(3/5));
    out.fG_array.push(fGz * cz**(-9/5));
    out.theta0_array.push(th0z * cz**(8/5));
    out.wind_array.push(wRms);
    out.loss_aod_array.push(aodZ * am);
    out.loss_abs_array.push(absZ * am);
  }
  return out;
}

function stationEcef(station) {
  const altKm = (station.altitude ?? 0) / 1000;
  return ecefFromLatLon(station.lat, station.lon, EARTH_RADIUS_KM + altKm);
}

function ecefToEci(r, gmst) {
  const c = Math.cos(gmst), s = Math.sin(gmst);
  return [c*r[0]-s*r[1], s*r[0]+c*r[1], r[2]];
}

function latLonToEci(lat, lon, alt, gmst) {
  return ecefToEci(ecefFromLatLon(lat, lon, EARTH_RADIUS_KM+(alt||0)), gmst);
}

/**
 * Propagate the satellite orbit at arbitrary time offsets (used by helio mode).
 * Returns { dataPoints, groundTrack } with positions at each given offset.
 */
function propagateOrbitAtTimes(settings, tOffsets) {
  const { orbital, resonance } = settings;
  const inc = (orbital.inclination ?? 53) * DEG2RAD;
  const raan0 = (orbital.raan ?? 0) * DEG2RAD;
  const arg0  = (orbital.argPerigee ?? 0) * DEG2RAD;
  const M0    = (orbital.meanAnomaly ?? 0) * DEG2RAD;
  const e     = orbital.eccentricity ?? 0.001;

  let a = clamp(orbital.semiMajor ?? 6771, MIN_SEMI_MAJOR, MAX_SEMI_MAJOR);

  // Resonance adjustment (same logic as propagateOrbit)
  if (resonance?.enabled) {
    const sK = Math.max(1, resonance.orbits || 1);
    const sJ = Math.max(1, resonance.rotations || 1);
    const aRes = solveRepeatGroundTrackA(sK, sJ, e, inc, {
      j2: orbital.j2Enabled !== false, j3: orbital.j3Enabled, j4: orbital.j4Enabled,
    });
    if (aRes >= MIN_SEMI_MAJOR && aRes <= MAX_SEMI_MAJOR) a = aRes;
  }

  const n = Math.sqrt(MU_EARTH / (a * a * a));
  const epoch = settings.epoch ? new Date(settings.epoch) : new Date();
  const gmst0 = gmstFromDate(epoch);

  const j2 = orbital.j2Enabled !== false;
  let dotRaan = 0, dotArg = 0, dotMA = 0;
  if (j2) {
    const rates = j2SecularRates(a, e, inc, orbital.j3Enabled, orbital.j4Enabled);
    dotRaan = rates.dotRaan;
    dotArg  = rates.dotArgPerigee;
    dotMA   = rates.dotMeanAnomaly;
  }

  const dataPoints = [], groundTrack = [];
  for (let si = 0; si < tOffsets.length; si++) {
    const t = tOffsets[si];
    const raanT = raan0 + dotRaan * t;
    const argT  = arg0  + dotArg  * t;
    const M = (M0 + (n + dotMA) * t) % TWO_PI;
    const { r: rEci, v: vEci } = orbitalPosVel(a, e, inc, raanT, argT, M);
    const gmst = (gmst0 + EARTH_ROT_RATE * t) % TWO_PI;
    const ecef = rotateToEcef(rEci, vEci, gmst);
    const geo = ecefToLatLon(ecef.r);
    dataPoints.push({
      t, rEci, vEci, rEcef: ecef.r, vEcef: ecef.v,
      lat: geo.lat, lon: geo.lon, alt: geo.alt, gmst,
    });
    groundTrack.push({ lat: geo.lat, lon: geo.lon });
  }
  const period = TWO_PI / n;
  return { dataPoints, groundTrack, orbitPeriod: period };
}

export const orbit = {
  constants: orbitConstants,
  propagateOrbit, propagateOrbitAtTimes, computeStationMetrics,
  stationEcef, latLonToEci, gmstFromDate,
};


// ── Resonance solver (lightweight – stays client-side) ──────────────────

function aFromPeriod(T) { return Math.cbrt(MU_EARTH * (T / TWO_PI) ** 2); }
function periodFromA(a) { return a > 0 ? TWO_PI * Math.sqrt(a**3 / MU_EARTH) : 0; }

function searchResonances({ targetA, toleranceKm = 0, minRotations, maxRotations,
  minOrbits, maxOrbits, siderealDay = SIDEREAL_DAY }) {
  const C = Number(targetA);
  if (!Number.isFinite(C) || C <= 0) return [];
  const tol = Math.max(0, Number(toleranceKm) || 0);
  const jLo = Math.max(1, Math.round(minRotations ?? 1));
  const jHi = Math.max(jLo, Math.round(maxRotations ?? 500));
  const kLo = Math.max(1, Math.round(minOrbits ?? 1));
  const kHi = Math.max(kLo, Math.round(maxOrbits ?? 500));
  const hits = [];
  for (let j = jLo; j <= jHi; j++) {
    const pf = j * siderealDay;
    for (let k = kLo; k <= kHi; k++) {
      const sm = aFromPeriod(pf / k);
      const delta = sm - C;
      if (Math.abs(delta) <= tol) hits.push({ j, k, ratio: j/k, periodSec: pf/k, semiMajorKm: sm, deltaKm: delta });
    }
  }
  hits.sort((a, b) => a.j !== b.j ? a.j - b.j : a.k - b.k);
  return hits;
}

export const resonanceSolver = {
  SIDEREAL_DAY, searchResonances, aFromPeriod, periodFromA, solveRepeatGroundTrackA,
};


// ── Walker constellation generator (lightweight) ────────────────────────

function generateWalkerConstellation(T, P, F, a, iDeg, e = 0, raanOffset = 0) {
  const S = Math.round(T / P) || 1;
  const sats = [];
  for (let p = 0; p < P; p++) {
    const raan = (360 * p) / P + (raanOffset || 0);
    for (let s = 0; s < S; s++) {
      const m = (360 * s) / S + (360 * F * p) / T;
      sats.push({
        semiMajor: a, eccentricity: e, inclination: Number(iDeg) || 0,
        raan: ((raan % 360) + 360) % 360, argPerigee: 0,
        meanAnomaly: ((m % 360) + 360) % 360,
      });
    }
  }
  return sats;
}

export const walkerGenerator = { generateWalkerConstellation };


// ── QKD (delegates to backend via /api/solve, fallback client-side) ─────

function calculateQKDPerformance(protocol, params) {
  // Client-side fallback for synchronous calls. The backend /api/solve
  // endpoint provides the authoritative calculation.
  const pr = (protocol || 'bb84').toLowerCase();
  const lossdB = params.channelLossdB ?? 0;
  const eta = Math.pow(10, -lossdB / 10);
  const detEff = params.detectorEfficiency ?? 0.25;
  const dark = params.darkCountRate ?? 100;
  const photonRate = params.photonRate ?? 1e9;
  const h = x => (x <= 0 || x >= 1) ? 0 : -x*Math.log2(x)-(1-x)*Math.log2(1-x);

  if (pr === 'bb84') {
    const mu = 0.5;
    const det = photonRate * eta * detEff * Math.exp(-mu);
    const qber = (dark/2) / (det + dark/2);
    const sifted = (det + dark/2) * 0.5;
    let skr = sifted - h(qber)*sifted - 1.16*h(qber)*sifted;
    if (qber > 0.11) skr = 0;
    skr = Math.max(0, skr);
    return { qber: qber*100, rawKeyRate: sifted/1000, secureKeyRate: skr/1000, channelTransmittance: eta, protocol: 'BB84' };
  }
  if (pr === 'e91') {
    const pair = photonRate / 2;
    const coinc = pair * (eta * detEff) ** 2;
    const acc = dark * dark / (pair || 1);
    const qber = acc / (coinc + acc);
    let skr = coinc * (1 - 2*h(qber));
    if (qber > 0.15) skr = 0;
    skr = Math.max(0, skr);
    return { qber: qber*100, rawKeyRate: coinc/1000, secureKeyRate: skr/1000, channelTransmittance: eta, protocol: 'E91' };
  }
  if (pr !== 'cv-qkd' && pr !== 'cvqkd') {
    // No silent fall-through: decoy-state BB84, MDI-QKD and TF-QKD have no
    // client-side estimate, and returning the CV-QKD branch's numbers under
    // their name (which is what this function used to do for any unrecognised
    // string) is worse than returning nothing.
    return {
      error: `${protocol} has no client-side estimate — use "Compute SKR Time Series" `
        + '(backend physics) in the QKD panel.',
      qber: null, rawKeyRate: null, secureKeyRate: null,
      channelTransmittance: eta, protocol,
    };
  }
  // cv-qkd
  const modVar = 10;
  const totT = eta * detEff;
  const eNoise = 0.01;
  const snr = totT * modVar / (1 + eNoise);
  const ex = eNoise / totT;
  const symRate = 100e6;
  const skr = symRate * Math.max(0, Math.log2(1+snr) - Math.log2(1+ex));
  const effQ = ex / (snr + ex);
  return { qber: effQ*100, rawKeyRate: symRate/1000, secureKeyRate: skr/1000, channelTransmittance: eta, protocol: 'CV-QKD' };
}

export const qkdCalculations = { calculateQKDPerformance };


// ── Optimisation engine (lightweight – stays client-side) ───────────────

function computeRevisitTime(positions, points, timeline, threshKm = 500) {
  if (!Array.isArray(points) || !Array.isArray(timeline)) return { max: Infinity, mean: Infinity };
  const perPt = points.map(() => []);
  for (let ti = 0; ti < timeline.length; ti++) {
    const posList = [];
    Object.values(positions).forEach(g => (g.satellites||[]).forEach(s => {
      const snap = s.timeline?.[ti];
      if (snap && Number.isFinite(snap.lat)) posList.push(snap);
    }));
    if (!posList.length) continue;
    points.forEach((pt, pi) => {
      for (const sp of posList) {
        if (haversineDistance(pt.lat, pt.lon, sp.lat, sp.lon, 6371) <= threshKm) { perPt[pi].push(timeline[ti]); break; }
      }
    });
  }
  const stats = perPt.map(ts => {
    if (!ts.length) return { max: Infinity, mean: Infinity };
    const d = []; for (let i=1;i<ts.length;i++) d.push(ts[i]-ts[i-1]);
    if (!d.length) return { max:0, mean:0 };
    return { max: Math.max(...d), mean: d.reduce((a,b)=>a+b,0)/d.length };
  });
  const v = stats.filter(s => isFinite(s.max));
  if (!v.length) return { max: Infinity, mean: Infinity };
  return { max: Math.max(...v.map(s=>s.max)), mean: v.reduce((a,s)=>a+s.mean,0)/v.length };
}

export const optimizationEngine = { computeRevisitTime };


// ── J2 propagator & SSO (thin re-exports for backward compatibility) ────

export const j2Propagator = {
  secularRates: j2SecularRates,
  MU_EARTH, EARTH_RADIUS_KM, J2,
};

export const sunSynchronousOrbit = {
  calculateSunSynchronousInclination(altKm, e = 0) {
    const a = EARTH_RADIUS_KM + altKm;
    const p = a * (1 - e*e);
    const n = Math.sqrt(MU_EARTH / (a*a*a));
    const target = 1.99098659e-7; // rad/s solar
    const cosI = -target / (1.5 * n * J2 * (EARTH_RADIUS_KM/p)**2);
    if (Math.abs(cosI) > 1) throw new Error('No SSO solution');
    return Math.acos(cosI) * RAD2DEG;
  },
};
