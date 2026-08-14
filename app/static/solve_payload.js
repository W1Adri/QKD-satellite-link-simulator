// ---------------------------------------------------------------------------
// app/static/solve_payload.js
// ---------------------------------------------------------------------------
// Purpose : ONE builder for the /api/solve request body, shared by every panel
//           that asks the backend for physics — the SKR time series
//           (qkd_relay.js) and the constellation study (study_panel.js), which
//           sends the same object as its `base`.
//
//           WHY IT IS SHARED.  The study's whole point is that its physics is
//           the simulator's physics; if each panel assembled its own payload,
//           the two would disagree the moment one of them gained a field, and a
//           study whose channel silently differs from the link it cites is not
//           reproducible.  Same reason the backend routes both through
//           `_run_single_station`.
//
//           Reads live UI state (state.js) plus the advanced QKD controls that
//           have no state mirror (they only ever travel to the backend).
//
// Exports : readAdvancedQkdOptions, buildSolveRequest
// ---------------------------------------------------------------------------
import { state } from './state.js';

const $ = (id) => document.getElementById(id);

function num(id, fallback) {
  const raw = $(id)?.value;
  if (raw === undefined || raw === null || raw === '') return fallback;
  const v = Number(raw);
  return Number.isFinite(v) ? v : fallback;
}

function optionalNum(id) {
  const raw = $(id)?.value;
  if (raw === undefined || raw === null || String(raw).trim() === '') return null;
  const v = Number(raw);
  return Number.isFinite(v) ? v : null;
}

function checked(id) {
  return $(id)?.checked === true;
}

/** Parse "1.0, 0.75, 0.5" → [1, 0.75, 0.5]; empty/invalid → null. */
function parseFractions(id) {
  const raw = $(id)?.value;
  if (!raw || !String(raw).trim()) return null;
  const vals = String(raw)
    .split(/[,\s;]+/)
    .map((s) => Number(s))
    .filter((v) => Number.isFinite(v) && v > 0 && v <= 1);
  return vals.length ? vals : null;
}

/**
 * Advanced options that live only in the DOM (QKD panel → "Advanced analysis").
 *
 * Every one of these is OFF by default on the backend too, so a payload built
 * with the checkboxes untouched reproduces the plain asymptotic clear-sky run
 * byte for byte — which is what keeps the Ntanos 2021 comparison valid.
 */
export function readAdvancedQkdOptions() {
  const out = {};

  // ── Temporal gating (daytime QKD) ────────────────────────────────────
  // UI is in nanoseconds because gates are ns-scale; the API takes seconds.
  if (checked('temporalGatingEnabled')) {
    out.temporal_gating_enabled = true;
    out.gate_time_s = num('gateTimeNs', 1.0) * 1e-9;
  }

  // ── Decoy-state intensities (blank → model defaults) ─────────────────
  const muS = optionalNum('muSignal');
  const muD = optionalNum('muDecoy');
  if (muS !== null) out.mu_signal = muS;
  if (muD !== null) out.mu_decoy = muD;

  // ── Per-pass finite key (Lim et al. 2014, PRA 89, 022307) ────────────
  if (checked('finiteKeyEnabled')) {
    out.finite_key_enabled = true;
    out.epsilon_sec = num('epsilonSec', 1e-10);
    out.epsilon_cor = num('epsilonCor', 1e-15);
    out.basis_bias_qx = num('basisBiasQx', 0.5);
    out.p_signal = num('pSignal', 4 / 21);
    out.p_decoy = num('pDecoy', 1 / 21);
    const fracs = parseFractions('fkBlockFractions');
    if (fracs) out.fk_block_fractions = fracs;
  }

  // ── Cloud availability, elevation-resolved PCFLOS ────────────────────
  if (checked('availabilityEnabled')) {
    out.availability_enabled = true;
    out.cloud_aspect_ratio = num('cloudAspectRatio', 1.0);
    out.availability_estimator = $('availabilityEstimator')?.value || 'expectation';
    out.cloud_threshold_pct = num('cloudThresholdPct', 30.0);
    out.cloud_night_only = checked('cloudNightOnly');
    const year = optionalNum('cloudYear');
    if (year !== null) out.cloud_year = Math.round(year);
  }

  // ── Monte Carlo channel realizations ─────────────────────────────────
  if (checked('monteCarloEnabled')) {
    out.monte_carlo_enabled = true;
    out.mc_realizations = Math.round(num('mcRealizations', 200));
    const seed = optionalNum('mcSeed');
    out.mc_seed = seed === null ? null : Math.round(seed);
    const band = $('mcBand')?.value || '5';
    const lo = Number(band);
    out.mc_quantiles = Number.isFinite(lo) ? [lo, 50, 100 - lo] : [5, 50, 95];
  }

  return out;
}

/**
 * Build a /api/solve request body from the live UI state.
 *
 * @param {object}  opts
 * @param {object}  [opts.station]   Station record (lat/lon/altitude_m/aperture_m).
 *                                   Omit for a study `base`, where the station
 *                                   fields are ignored and the network is given
 *                                   separately.
 * @param {boolean} [opts.advanced]  Include the advanced (finite-key /
 *                                   availability / Monte Carlo / gating) block.
 * @param {object}  [opts.overrides] Merged last — for callers that must pin a
 *                                   field (e.g. a fixed f_rep sweep).
 */
export function buildSolveRequest({ station = null, advanced = true, overrides = {} } = {}) {
  const orb = state.orbital || {};
  const opt = state.optical || {};
  const lb = state.linkBudget || {};
  const atm = state.atmosphere || {};

  const payload = {
    // ── Orbit ──────────────────────────────────────────────────────────
    semi_major_axis: orb.semiMajor ?? 6771,
    eccentricity: orb.eccentricity ?? 0.001,
    inclination_deg: orb.inclination ?? 53,
    raan_deg: orb.raan ?? 0,
    arg_perigee_deg: orb.argPerigee ?? 0,
    mean_anomaly_deg: orb.meanAnomaly ?? 0,
    j2_enabled: orb.j2Enabled !== false,
    j3_enabled: orb.j3Enabled === true,
    j4_enabled: orb.j4Enabled === true,
    epoch: state.epoch || new Date().toISOString(),
    // The propagation window is an explicit control rather than the viewer's
    // playback span: a key-volume total over 3 orbits and one over a day are
    // different results, and the number has to be visible to be reported.
    total_orbits: Math.round(num('solveTotalOrbits', state.time?.totalOrbits ?? 3)),
    samples_per_orbit: state.samplesPerOrbit ?? 180,

    // ── Optics ─────────────────────────────────────────────────────────
    sat_aperture_m: opt.satAperture ?? 0.6,
    ground_aperture_m: opt.groundAperture ?? 1.0,
    wavelength_nm: opt.wavelength ?? 810,

    // ── Atmosphere / turbulence ────────────────────────────────────────
    atmosphere_model: atm.model || null,
    ground_cn2_day: opt.groundCn2Day ?? 5e-14,
    ground_cn2_night: opt.groundCn2Night ?? 5e-15,

    // ── QKD ────────────────────────────────────────────────────────────
    qkd_protocol: $('qkdProtocol')?.value || 'bb84-decoy',
    photon_rate: num('photonRate', 100) * 1e6,
    detector_efficiency: num('detectorEfficiency', 0.65),
    dark_count_rate: num('darkCountRate', 100),

    // ── Link budget ────────────────────────────────────────────────────
    // Forwarded in full: the deterministic loss the Monte Carlo band is
    // de-biased against, and the background the temporal gate suppresses, are
    // both built from these — a payload that omitted them would silently make
    // the stochastic and gating options no-ops.
    link_direction: lb.linkDirection || 'downlink',
    atm_zenith_aod_db: lb.atmZenithAod ?? 0,
    atm_zenith_abs_db: lb.atmZenithAbs ?? 0,
    pointing_error_urad: lb.pointingErrorUrad ?? 0,
    pat_fading_enabled: lb.patFadingEnabled ?? true,
    fixed_optics_loss_db: lb.fixedOpticsLoss ?? 0,
    scintillation_enabled: lb.scintillationEnabled === true,
    scintillation_p0: lb.scintillationP0 ?? 0.01,
    background_enabled: lb.backgroundEnabled === true,
    background_Hrad_W_m2_sr_um: lb.bgRadiance ?? 0,
    background_fov_mrad: lb.bgFovMrad ?? 0,
    background_delta_lambda_nm: lb.bgDeltaLambda ?? 0,
    sun_exclusion_deg: lb.sunExclusionDeg ?? 0,
    min_elevation_deg: lb.minElevationDeg ?? 20,
    elevation_threshold_deg: num('keyVolumeElevThreshold', 5),
    tx_power_dbm: lb.txPowerDbm ?? null,
    rx_sensitivity_dbm: lb.rxSensitivityDbm ?? null,
  };

  if (station) {
    payload.station_lat = station.lat;
    payload.station_lon = station.lon;
    payload.station_altitude_m = station.altitude_m || 0;
    payload.ground_aperture_m = opt.groundAperture ?? station.aperture_m ?? 1.0;
  }

  if (advanced) Object.assign(payload, readAdvancedQkdOptions());
  return { ...payload, ...overrides };
}
