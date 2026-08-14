# ---------------------------------------------------------------------------
# app/models.py
# ---------------------------------------------------------------------------
# Purpose : Pydantic schemas shared across routers for request validation
#           and response serialisation.
#
# Classes (request):
#   OGSLocation, UserCreate, ChatCreate, AtmosRequest,
#   WeatherFieldRequest, SolveRequest
#
# Classes (response):
#   UserRead, AuthResponse, ChatRead, UserCount
#
# Helpers:
#   is_in_europe_bbox(lat, lon) – bounding-box guard
#   normalize_username(value)   – lowercase & strip
# ---------------------------------------------------------------------------
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ── OGS ──────────────────────────────────────────────────────────────────

class OGSLocation(BaseModel):
    id: Optional[str] = None
    name: str = Field(min_length=1)
    lat: float
    lon: float
    altitude_m: float = Field(default=0.0, ge=0.0, le=9000.0)
    aperture_m: float = Field(default=1.0, ge=0.1, le=15.0)
    notes: Optional[str] = None
    builtin: bool = False


# ── Users / Chat ─────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=40)
    password: str = Field(min_length=4, max_length=128)


class UserRead(BaseModel):
    id: int
    username: str
    created_at: str


class AuthResponse(UserRead):
    message: str


class ChatCreate(BaseModel):
    user_id: int
    message: str = Field(min_length=1, max_length=2000)


class ChatRead(BaseModel):
    id: int
    user_id: int
    username: str
    message: str
    created_at: str


class UserCount(BaseModel):
    count: int


# ── Atmosphere ───────────────────────────────────────────────────────────

class AtmosRequest(BaseModel):
    lat: float
    lon: float
    time: str
    ground_cn2_day: float
    ground_cn2_night: float
    model: str = Field(default="hufnagel-valley")
    wavelength_nm: Optional[float] = Field(default=810.0, ge=400.0, le=2000.0)


class IrradianceRequest(BaseModel):
    """Request payload for POST /api/irradiance."""
    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)
    time: str
    method: str = Field(default="analytical")   # "analytical" | "open-meteo"
    altitude_m: float = Field(default=0.0, ge=0.0, le=9000.0)


class WeatherFieldRequest(BaseModel):
    time: str
    variable: str = Field(default="wind_speed")
    level_hpa: int = Field(default=200, ge=50, le=1000)
    samples: int = Field(default=120, ge=16, le=900)


# ── Unified solver ───────────────────────────────────────────────────────

class SolveRequest(BaseModel):
    """Payload for POST /api/solve."""
    # Orbit mode: "elements" or "tle"
    mode: str = Field(default="elements")

    # Keplerian elements (used when mode == "elements")
    semi_major_axis: float = Field(default=6771.0)
    eccentricity: float = Field(default=0.001, ge=0.0, lt=1.0)
    inclination_deg: float = Field(default=53.0, ge=0.0, le=180.0)
    raan_deg: float = Field(default=0.0)
    arg_perigee_deg: float = Field(default=0.0)
    mean_anomaly_deg: float = Field(default=0.0)
    j2_enabled: bool = True
    j3_enabled: bool = False
    j4_enabled: bool = False
    epoch: Optional[str] = None

    # Station
    station_lat: Optional[float] = None
    station_lon: Optional[float] = None
    station_altitude_m: float = Field(default=0.0, ge=0.0, le=9000.0)

    # Optics
    sat_aperture_m: float = Field(default=0.6, ge=0.05, le=5.0)
    ground_aperture_m: float = Field(default=1.0, ge=0.05, le=15.0)
    wavelength_nm: float = Field(default=810.0, ge=400.0, le=2000.0)

    # Time
    samples_per_orbit: int = Field(default=180, ge=10, le=1000)
    total_orbits: int = Field(default=3, ge=1, le=50)

    # Atmosphere (optional)
    atmosphere_model: Optional[str] = None
    ground_cn2_day: float = 5e-14
    ground_cn2_night: float = 5e-15

    # QKD (optional)
    qkd_protocol: Optional[str] = None
    photon_rate: float = 1e9
    detector_efficiency: float = 0.25
    dark_count_rate: float = 100.0

    # Walker constellation (optional)
    walker_T: Optional[int] = None
    walker_P: Optional[int] = None
    walker_F: Optional[int] = None

    # ── Link-budget extensions (all optional, backward-compatible) ────
    # Pointing error (QUARC model)
    pointing_error_urad: float = 0.0

    # Scintillation fading
    scintillation_enabled: bool = False
    scintillation_p0: float = Field(default=0.01, gt=0.0, lt=1.0)

    # Atmosphere attenuation (zenith values, dB)
    atm_zenith_aod_db: float = Field(default=0.0, ge=0.0)
    atm_zenith_abs_db: float = Field(default=0.0, ge=0.0)

    # Fixed optical losses excluding detector (dB)
    fixed_optics_loss_db: float = Field(default=0.0, ge=0.0)

    # Link direction ("downlink" = plane wave, "uplink" = spherical wave)
    link_direction: str = Field(default="downlink")

    # PAT fading model (Rayleigh-averaged pointing jitter)
    pat_fading_enabled: bool = Field(default=False)
    # Dynamic sky background (solar/lunar radiance replaces static Hrad)
    dynamic_background_enabled: bool = Field(default=False)

    # Key volume integration threshold (pass boundary definition)
    elevation_threshold_deg: float = Field(default=5.0, ge=0.0, le=90.0)

    # Minimum elevation angle for link establishment (avoids asymptotic losses at horizon)
    min_elevation_deg: float = Field(default=20.0, ge=0.0, le=90.0)

    # Background noise
    background_enabled: bool = False
    background_Hrad_W_m2_sr_um: float = Field(default=0.0, ge=0.0)
    background_fov_mrad: float = Field(default=0.0, ge=0.0)
    background_delta_lambda_nm: float = Field(default=0.0, ge=0.0)

    # Temporal gating (daytime QKD): suppresses background by Δt_gate · f_rep
    temporal_gating_enabled: bool = False
    gate_time_s: float = Field(default=0.0, ge=0.0)

    # Sun / eclipse
    sun_exclusion_deg: float = Field(default=0.0, ge=0.0, le=90.0)

    # Received power / link margin
    tx_power_dbm: Optional[float] = None
    rx_sensitivity_dbm: Optional[float] = None

    # ── Paper-mode formula variants (Ntanos et al. 2021, Photonics 8, 544) ──
    # Geometric coupling model: "airy" (1.22λ/D, default) | "gaussian" (Eq.3/5/6)
    geometric_model: str = Field(default="airy")
    # Pointing-loss model: "gaussian" (QUARC, default) | "beta" (Eq. 8-10)
    pointing_model: str = Field(default="gaussian")
    # rms wind speed for the modified-HV Cn² profile (m/s, Bufton; paper 10)
    wind_rms_ms: float = Field(default=10.0, ge=0.0)
    # Decoy-state intensities / protocol efficiency (paper: μ=0.56, ν=0.11)
    mu_signal: Optional[float] = None
    mu_decoy: Optional[float] = None
    # Protocol efficiency q (paper Eq. A1 → 2/21 ≈ 0.095; None keeps 0.5 default)
    decoy_q: Optional[float] = None
    # Optical/baseline QBER e_det = (1−V)/2 (paper V=98% → 0.01); None → 0.02
    e_optical: Optional[float] = None
    # Error-correction efficiency f(e) (paper CASCADE 1.22); None → default 1.16
    ec_efficiency: Optional[float] = None
    # Paper-mode noise (Eq. A6): Y0 = (dark + bg·η_det)·t_gate instead of /f_rep
    paper_noise: bool = Field(default=False)

    # ── Per-pass finite-key analysis (Lim et al. 2014, PRA 89, 022307) ──────
    # One satellite pass = one finite-key block (Islam et al., PRX Quantum 5,
    # 030101 (2024) §III B).  Only implemented for the decoy-state protocol —
    # the bound is a decoy-state bound.  When enabled, each pass in the
    # key-volume breakdown gains nSifted / fkFraction / keyVolumeFinite.
    finite_key_enabled: bool = Field(default=False)
    # Composable security parameters.  ε = ε_cor + ε_sec.
    epsilon_sec: float = Field(default=1e-10, gt=0.0, lt=1.0)
    epsilon_cor: float = Field(default=1e-15, gt=0.0, lt=1.0)
    # Basis bias q_x of efficient BB84: key from X, phase estimation from Z.
    # 0.5 = unbiased (textbook BB84 sifting).
    basis_bias_qx: float = Field(default=0.5, gt=0.0, lt=1.0)
    # Intensity-selection probabilities (signal, decoy).  The vacuum
    # probability is the remainder, 1 − p_signal − p_decoy.  Defaults are the
    # Ntanos 2021 ratio signal:decoy:vacuum = 4:1:16.
    p_signal: float = Field(default=4.0 / 21.0, gt=0.0, lt=1.0)
    p_decoy: float = Field(default=1.0 / 21.0, gt=0.0, lt=1.0)
    # Block-shrinkage sensitivity: re-evaluate the finite-key length on f·n
    # counts for each f given, i.e. ℓ(f·n) rather than f·ℓ(n).  This is what
    # quantifies the cost of a pass cut short (by cloud, by scheduling, by a
    # shorter transmission window): because ℓ is superadditive, ℓ(f·n) ≤ f·ℓ(n),
    # with equality only asymptotically — and ℓ(f·n) = 0 outright once the
    # surviving block falls under the threshold block size.  Suggested
    # [1.0, 0.75, 0.5].  None → not computed.
    fk_block_fractions: Optional[List[float]] = None

    # ── Cloud availability (PCFLOS) ─────────────────────────────────────────
    # Elevation-resolved P_CFLOS = (1 − N)^sqrt(1 + β² cot²ε) [Kauth & Penquite
    # 1967], applied per pass as a key-weighted mean.  Off by default: the
    # asymptotic clear-sky totals stay byte-identical, which is what keeps the
    # Ntanos 2021 reproduction comparable (their Table 1 is explicitly
    # cloud-free).  See physics/availability.py.
    availability_enabled: bool = Field(default=False)
    # Cloud aspect ratio β = h/(2r).  1.0 makes the shape factor exactly
    # 1/sin(ε); published cumulus range is 0.6–1.5, so sweep it for the
    # sensitivity band.  0 disables the elevation correction (zenith proxy).
    cloud_aspect_ratio: float = Field(default=1.0, ge=0.0, le=5.0)
    # "expectation" = (1 − N)^f averaged over hours (no free threshold, the
    # defensible default); "threshold" = the legacy P(cover < threshold) count.
    availability_estimator: str = Field(default="expectation")
    cloud_threshold_pct: float = Field(default=30.0, ge=0.0, le=100.0)
    # Condition the cloud statistic on night hours when the link is
    # night-only.  The sign of the day/night difference is site- and
    # season-dependent [Eastman & Warren 2014], so this is a knob, not a
    # correction.
    cloud_night_only: bool = Field(default=False)
    # ERA5 year to draw the climatology from; None → epoch year − 1.
    cloud_year: Optional[int] = Field(default=None, ge=1940, le=2026)
    # Pre-fetched ``{"time": [...], "cloud_cover": [...]}``.  Supplying it keeps
    # the run fully offline and reproducible — the study results must not depend
    # on a live archive call.  When absent the router fetches and attaches an
    # explicit note on failure rather than silently assuming clear skies.
    cloud_cover_hourly: Optional[Dict[str, Any]] = None

    # ── Monte Carlo channel realizations ────────────────────────────────────
    # The deterministic path reports ONE key rate per sample, built from the
    # mean scintillation index and the Rayleigh-AVERAGED pointing fade.  That
    # is a mean, and a mean is not a feasibility statement: the quantity an
    # operator needs is how often the link delivers nothing.  Enabling this
    # draws `mc_realizations` channels per accepted sample and reports the
    # P5/P50/P95 band plus the outage probability.  See physics/monte_carlo.py.
    #
    # MODELLING LIMIT, must be stated wherever these bands are published: the
    # draws are i.i.d. PER SAMPLE, so the band is the distribution of the
    # INSTANTANEOUS key rate.  Fading is temporally correlated on ~1/f_Greenwood,
    # so the outage figure is a fraction of independent instants, NOT a fraction
    # of pass time, and it carries no information about fade DURATION.
    monte_carlo_enabled: bool = Field(default=False)
    mc_realizations: int = Field(default=200, ge=1, le=20000)
    # Fixed seed by default: a published confidence band that moves between two
    # runs of the same configuration is not a result.
    mc_seed: Optional[int] = Field(default=12345)
    # Percentiles to report. P5/P50/P95 is the usual band; widen for tails.
    mc_quantiles: List[float] = Field(default=[5.0, 50.0, 95.0])


# ── Helpers ──────────────────────────────────────────────────────────────

def is_in_europe_bbox(lat: float, lon: float) -> bool:
    return (25.0 <= lat <= 72.0) and (-31.0 <= lon <= 45.0)


def normalize_username(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("Invalid username")
    return value.strip().lower()


# ── PCFLOS ───────────────────────────────────────────────────────────────

class PCFLOSRequest(BaseModel):
    """Payload for POST /api/pcflos."""
    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)
    year: int = Field(default=2024, ge=1940, le=2026)
    threshold_pct: float = Field(default=30.0, ge=0.0, le=100.0)
    station_name: Optional[str] = None
    # "expectation" (default) = mean of (1 − N)^f(ε) over hours; "threshold" =
    # the legacy P(cover < threshold_pct) count.  Both are always returned; this
    # only selects which one fills monthly_pcflos / annual_pcflos.
    estimator: str = Field(default="expectation", pattern="^(expectation|threshold)$")
    # Elevation at which to evaluate the expectation estimator.  90 = zenith,
    # where it reduces to 1 − <N>.  A LEO pass is nowhere near zenith for most
    # of its duration, so ask for the elevation you actually care about.
    elev_deg: float = Field(default=90.0, ge=0.0, le=90.0)
    beta: float = Field(default=1.0, ge=0.0, le=5.0)
    night_only: bool = False


# ── Multi-OGS batch solver ───────────────────────────────────────────────

class MultiOGSSolveRequest(BaseModel):
    """Payload for POST /api/solve/multi-ogs.

    Run the same satellite/physics configuration over multiple ground stations
    in one request.  Either reference built-in stations by ``station_ids`` or
    supply custom stations via ``inline_stations``; both can be combined.
    """
    # Satellite + orbit (mirrors SolveRequest; station_lat/lon ignored here)
    mode: str = Field(default="elements")
    semi_major_axis: float = Field(default=6771.0)
    eccentricity: float = Field(default=0.001, ge=0.0, lt=1.0)
    inclination_deg: float = Field(default=53.0, ge=0.0, le=180.0)
    raan_deg: float = Field(default=0.0)
    arg_perigee_deg: float = Field(default=0.0)
    mean_anomaly_deg: float = Field(default=0.0)
    j2_enabled: bool = True
    j3_enabled: bool = False
    j4_enabled: bool = False
    epoch: Optional[str] = None
    samples_per_orbit: int = Field(default=180, ge=10, le=1000)
    total_orbits: int = Field(default=3, ge=1, le=50)

    # Optics
    sat_aperture_m: float = Field(default=0.6, ge=0.05, le=5.0)
    wavelength_nm: float = Field(default=810.0, ge=400.0, le=2000.0)

    # QKD
    qkd_protocol: Optional[str] = None
    photon_rate: float = Field(default=1e9, gt=0.0)
    detector_efficiency: float = Field(default=0.25, gt=0.0, le=1.0)
    dark_count_rate: float = Field(default=100.0, ge=0.0)

    # Link budget
    pointing_error_urad: float = Field(default=0.0, ge=0.0)
    scintillation_enabled: bool = False
    scintillation_p0: float = Field(default=0.01, gt=0.0, lt=1.0)
    atm_zenith_aod_db: float = Field(default=0.0, ge=0.0)
    atm_zenith_abs_db: float = Field(default=0.0, ge=0.0)
    fixed_optics_loss_db: float = Field(default=0.0, ge=0.0)
    link_direction: str = Field(default="downlink")
    pat_fading_enabled: bool = False
    dynamic_background_enabled: bool = False
    min_elevation_deg: float = Field(default=20.0, ge=0.0, le=90.0)
    elevation_threshold_deg: float = Field(default=5.0, ge=0.0, le=90.0)
    background_enabled: bool = False
    background_Hrad_W_m2_sr_um: float = Field(default=0.0, ge=0.0)
    background_fov_mrad: float = Field(default=0.0, ge=0.0)
    background_delta_lambda_nm: float = Field(default=0.0, ge=0.0)
    temporal_gating_enabled: bool = False
    gate_time_s: float = Field(default=0.0, ge=0.0)
    sun_exclusion_deg: float = Field(default=0.0, ge=0.0, le=90.0)
    tx_power_dbm: Optional[float] = None
    rx_sensitivity_dbm: Optional[float] = None
    atmosphere_model: Optional[str] = None
    ground_cn2_day: float = 5e-14
    ground_cn2_night: float = 5e-15

    # Per-pass finite-key analysis (mirrors SolveRequest; see there for refs)
    finite_key_enabled: bool = Field(default=False)
    epsilon_sec: float = Field(default=1e-10, gt=0.0, lt=1.0)
    epsilon_cor: float = Field(default=1e-15, gt=0.0, lt=1.0)
    basis_bias_qx: float = Field(default=0.5, gt=0.0, lt=1.0)
    p_signal: float = Field(default=4.0 / 21.0, gt=0.0, lt=1.0)
    p_decoy: float = Field(default=1.0 / 21.0, gt=0.0, lt=1.0)

    # Cloud availability (mirrors SolveRequest; see there and
    # physics/availability.py for the model and its references)
    availability_enabled: bool = Field(default=False)
    cloud_aspect_ratio: float = Field(default=1.0, ge=0.0, le=5.0)
    availability_estimator: str = Field(default="expectation")
    cloud_threshold_pct: float = Field(default=30.0, ge=0.0, le=100.0)
    cloud_night_only: bool = Field(default=False)
    cloud_year: Optional[int] = Field(default=None, ge=1940, le=2026)
    # Keyed by station id here, because each station has its own climatology.
    # Supplying it keeps the run offline; a station missing from the map falls
    # back to a fetch, and to an explicit note if that fails.
    cloud_cover_hourly_by_station: Optional[Dict[str, Dict[str, Any]]] = None

    # Monte Carlo channel (mirrors SolveRequest; see there for the i.i.d. caveat)
    monte_carlo_enabled: bool = Field(default=False)
    mc_realizations: int = Field(default=200, ge=1, le=20000)
    mc_seed: Optional[int] = Field(default=12345)
    mc_quantiles: List[float] = Field(default=[5.0, 50.0, 95.0])

    # Station selection (at least one must be provided)
    station_ids: Optional[List[str]] = Field(
        default=None,
        description="IDs of built-in / saved OGS to include (looked up from store)",
    )
    inline_stations: Optional[List[OGSLocation]] = Field(
        default=None,
        description="Ad-hoc station definitions (lat/lon/aperture) to include",
    )


# ── Relay ────────────────────────────────────────────────────────────────

class RelayRequest(BaseModel):
    """Payload for POST /api/relay — trusted node relay between two stations."""
    solve_a: SolveRequest = Field(description="Solve config for Station A")
    solve_b: SolveRequest = Field(description="Solve config for Station B")
    elevation_threshold_deg: float = Field(default=5.0, ge=0.0, le=90.0)
    cloud_threshold_pct: float = Field(default=30.0, ge=0.0, le=100.0)

