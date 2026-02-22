# QKD Satellite Link Simulator

## Complete User Manual and Technical Documentation

---

## Table of Contents

1. [Introduction](#introduction)
2. [Installation and Setup](#installation-and-setup)
3. [User Interface Overview](#user-interface-overview)
4. [Orbit Configuration](#orbit-configuration)
   - [Orbital Parameters](#orbital-parameters)
   - [J2 Perturbation Effects](#j2-perturbation-effects)
   - [Resonance and Repeat Ground Tracks](#resonance-and-repeat-ground-tracks)
5. [Constellation Management](#constellation-management)
   - [Walker Delta Constellations](#walker-delta-constellations)
   - [TLE Constellation Overlays](#tle-constellation-overlays)
   - [Constellation Optimization](#constellation-optimization)
6. [Optical Link Parameters](#optical-link-parameters)
7. [Ground Station Management](#ground-station-management)
8. [Analytics and Metrics](#analytics-and-metrics)
9. [Weather Data Integration](#weather-data-integration)
10. [Atmospheric Models](#atmospheric-models)
11. [Quantum Key Distribution (QKD)](#quantum-key-distribution-qkd)
12. [3D and 2D Visualization](#3d-and-2d-visualization)
13. [Technical Architecture](#technical-architecture)
14. [API Reference](#api-reference)
15. [Libraries and Dependencies](#libraries-and-dependencies)
16. [Formulas and Algorithms](#formulas-and-algorithms)
17. [Future Development](#future-development)

---

## Introduction

The **QKD Satellite Link Simulator** is a comprehensive web-based application designed for planning and analyzing Quantum Key Distribution (QKD) satellite communication links worldwide. The simulator provides detailed orbital mechanics calculations, atmospheric modeling, and link budget analysis for satellite-to-ground optical communication systems.

This software enables researchers and engineers to:

- Design and visualize satellite orbits with precise orbital mechanics
- Configure and optimize satellite constellations using Walker Delta patterns
- Analyze atmospheric effects on optical links using professional turbulence models
- Calculate QKD performance metrics including secure key rates
- Visualize satellite positions in both 2D map and 3D globe views
- Integrate real-time weather data for accurate link predictions

![Main Interface](https://github.com/user-attachments/assets/1998c335-6c51-49d4-ac37-791a9fe9f8f2)

*Figure 1: Main application interface showing the Orbit configuration panel with J2 perturbation enabled*

---

## Installation and Setup

### System Requirements

- Python 3.10 or higher
- Modern web browser with WebGL support (Chrome, Firefox, Edge, Safari)
- Internet connection for weather data and TLE constellation overlays

### Installation Steps

1. **Clone the Repository**
   ```bash
   git clone https://github.com/W1Adri/QKD_EU_LINK_Simulator.git
   cd QKD_EU_LINK_Simulator
   ```

2. **Install Python Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

   The following key packages will be installed:
   - `fastapi` - Web framework for the backend API
   - `uvicorn` - ASGI server for running the application
   - `numpy` - Numerical computations for orbital mechanics
   - `scipy` - Scientific computing for atmospheric models
   - `geopandas` - Geographic data handling
   - `cosmica` - Professional orbital dynamics library
   - `skyfield` - High-precision astronomy calculations
   - `sgp4` - SGP4/SDP4 satellite propagation

3. **Start the Development Server**
   ```bash
   python run_app.py
   ```

4. **Access the Application**
   Open your web browser and navigate to:
   ```
   http://127.0.0.1:8000/
   ```

### Project Structure

```
QKD_EU_LINK_Simulator/
├── app/
│   ├── __init__.py                # Package initialisation
│   ├── main.py                    # Uvicorn entry point
│   ├── backend.py                 # FastAPI application factory & middleware
│   ├── models.py                  # Pydantic request/response schemas
│   ├── orbital_mechanics.py       # Sun-synchronous & repeat-track solvers
│   ├── constellation_manager.py   # Walker constellation analysis (cosmica)
│   ├── physics/                   # Pure-Python physics library
│   │   ├── constants.py           #   Physical & orbital constants
│   │   ├── kepler.py              #   Keplerian element conversions
│   │   ├── propagation.py         #   Two-body & J2 propagation
│   │   ├── geometry.py            #   Station geometry & link budget
│   │   ├── atmosphere_models.py   #   HV-5/7, Bufton, Greenwood models
│   │   ├── qkd.py                 #   BB84 / decoy-state QKD metrics
│   │   └── walker.py              #   Walker-Delta constellation generator
│   ├── services/                  # Business-logic services
│   │   ├── database.py            #   SQLite async repository
│   │   ├── ogs_store.py           #   Ground-station CRUD (JSON fallback)
│   │   ├── atmosphere_svc.py      #   Atmospheric profile computation
│   │   ├── weather_svc.py         #   Open-Meteo weather fetcher
│   │   └── tle_service.py         #   CelesTrak TLE fetcher & parser
│   ├── routers/                   # FastAPI route modules
│   │   ├── pages.py               #   HTML page routes
│   │   ├── ogs.py                 #   Ground-station CRUD API
│   │   ├── atmosphere.py          #   Atmosphere profile API
│   │   ├── orbital.py             #   Orbital-mechanics API
│   │   ├── solver.py              #   Unified POST /api/solve endpoint
│   │   ├── constellation.py       #   Constellation API
│   │   ├── tles.py                #   TLE proxy API
│   │   └── users.py               #   User-preferences API
│   ├── templates/                 # Jinja2 HTML templates
│   │   ├── dashboard.html         #   Default layout
│   │   └── immersive.html         #   Minimal-chrome layout
│   ├── static/                    # Frontend assets
│   │   ├── app.js                 #   Template entry (imports main.js)
│   │   ├── main.js                #   App coordinator, event binding, charts
│   │   ├── state.js               #   Reactive state (pub/sub, mutations)
│   │   ├── stations.js            #   OGS API helpers & built-in station list
│   │   ├── formatters.js          #   Numeric display formatters
│   │   ├── tooltips.js            #   Info-button tooltip manager
│   │   ├── weather.js             #   Weather field config & DOM helpers
│   │   ├── simulation.js          #   Physics facade (delegates to api.js)
│   │   ├── ui.js                  #   Three.js 3D scene & Leaflet 2D map
│   │   ├── api.js                 #   HTTP client for backend endpoints
│   │   ├── utils.js               #   Shared utility functions
│   │   ├── propagateWorker.js     #   Web Worker for parallel propagation
│   │   ├── index.html             #   Legacy standalone HTML (fallback)
│   │   ├── ogs_locations.json     #   Ground station persistence
│   │   ├── styles/
│   │   │   └── app.css            #   Application stylesheet
│   │   └── data/
│   │       └── europe_union.geojson  # EU border overlay
│   └── data/
│       └── app.sqlite3            # SQLite database
├── requirements.txt               # Python dependencies
├── run_app.py                     # Entry point (python run_app.py)
├── manage.py                      # Database management CLI
├── README.md                      # User manual (this file)
└── ReadmeLogic.md                 # Technical architecture documentation
```

---

## User Interface Overview

The application interface is divided into several key components:

### Navigation Sidebar

The left sidebar provides access to all configuration sections:

| Button | Section | Description |
|--------|---------|-------------|
| 🛰️ **Orbit** | Orbit Configuration | Configure single satellite orbital elements |
| 🌌 **Constellations** | Constellation Management | Design Walker constellations and TLE overlays |
| 🔭 **Optics** | Optical Parameters | Set aperture sizes and wavelength |
| 📡 **Stations** | Ground Stations | Manage optical ground stations |
| 📊 **Analytics** | Link Metrics | View real-time performance data |
| 🌤️ **Weather** | Weather Data | Fetch meteorological fields |
| 🌍 **Atmosphere** | Atmospheric Models | Select turbulence models |
| 🔐 **QKD** | QKD Protocols | Calculate quantum key rates |
| ❓ **Help** | Documentation | Access help information |

### View Modes

The visualization area supports multiple view modes accessible via the top toolbar:

- **Dual** - Side-by-side 3D globe and 2D map
- **3D** - Full-screen 3D Earth globe with orbit visualization
- **2D** - Full-screen 2D Leaflet map with ground tracks
- **Fullscreen** - Expand visualization to full browser window

### Playback Controls

At the bottom of the visualization area, playback controls allow you to:

- ▶ **Play** - Start time animation
- ⏸ **Pause** - Pause animation
- ⏪ **Step Back** - Move one time step backward
- ⏩ **Step Forward** - Move one time step forward
- ↺ **Reset** - Return to simulation start
- **Speed** - Select time warp factor (×1 to ×3600)
- **Timeline Slider** - Scrub through the simulation timeline

---

## Orbit Configuration

The Orbit panel is the primary interface for configuring a single satellite's orbital parameters. This section provides detailed control over all six Keplerian orbital elements plus additional parameters for resonance calculations.

### Orbital Parameters

*The Orbit panel is shown in Figure 1 above, displaying all orbital parameter controls.*

#### Semi-Major Axis (a)

**Parameter:** `Target semi-major axis a₀ (km)`  
**Range:** 6,538 km to 42,164 km  
**Default:** 6,771 km  

The semi-major axis defines the size of the orbit. It is the average of the periapsis and apoapsis distances from Earth's center.
<img width="2440" height="1048" alt="image" src="https://github.com/user-attachments/assets/37e9db05-a7c3-493e-a96b-81147239fe65" />

**Physical Meaning:**
- Determines the orbital period (how long one complete orbit takes)
- Affects the satellite altitude and thus the link distance
- Higher values result in longer orbital periods

**Calculation in Code** (`simulation.js`, lines 707-711):
```javascript
function computeSemiMajorWithResonance(orbits, rotations) {
  const totalTime = (rotations / orbits) * SIDEREAL_DAY;
  const semiMajor = Math.cbrt((MU_EARTH * (totalTime / (2 * Math.PI)) ** 2));
  return semiMajor;
}
```

The relationship between semi-major axis and orbital period follows Kepler's Third Law:

$$T = 2\pi\sqrt{\frac{a^3}{\mu}}$$

Where:
- T = orbital period (seconds)
- a = semi-major axis (km)
- μ = Earth's gravitational parameter (398,600.4418 km³/s²)

  (Note: Kepler's 3rd law assumes perfect sphere as central body, dodes not consider J2)

#### Eccentricity (e)

**Parameter:** `Eccentricity e`  
**Range:** 0 to 0.9  
**Default:** 0.001  

Eccentricity defines the shape of the orbit, from circular (e=0) to highly elliptical (e→1).

**Physical Meaning:**
- e = 0: Perfectly circular orbit
- 0 < e < 1: Elliptical orbit
- Affects perigee and apogee altitudes (specific terms for orbits around the earth corresponding to periapsis/apoapsis respectively)

**Perigee and Apogee Calculation:**
```
Perigee radius = a × (1 - e)
Apogee radius = a × (1 + e)
```

**Warning:** If the eccentricity is set too high for a given semi-major axis, the perigee may drop below Earth's surface. The simulator will display a warning: *"Perigee drops below the Earth surface. Reduce eccentricity or adjust the resonance."*

#### Inclination (i)

**Parameter:** `Inclination i (deg)`  
**Range:** 0° to 180°  
**Default:** 53°  

The inclination defines the tilt of the orbital plane relative to Earth's equatorial plane.

**Physical Meaning:**
- i = 0°: Equatorial orbit (satellite stays above the equator)
- i = 90°: Polar orbit (passes over both poles)
- i > 90°: Retrograde orbit (orbits opposite to Earth's rotation)

**Special Cases:**
- **Sun-synchronous orbits** typically require inclinations of 96° to 100° for LEO altitudes: These are near-polar, retrograde orbits designed so that a satellite passes over any point on Earth at the same local solar time every day, ensuring consistent lighting conditions for observation. This synchronization is achieved by selecting a specific inclination (typically between $96^\circ$ and $105^\circ$) that harnesses the torque caused by Earth’s equatorial bulge ($J_2$ perturbation) to rotate the orbital plane eastward at approximately $0.9856^\circ$ per day. This precession rate perfectly matches Earth's revolution around the Sun; because the gravitational torque weakens with distance, higher altitudes require a more retrograde inclination to maintain this precise lock.

To find the requiered inclination the Nodal Precession (11$\dot{\Omega}$) is set equal to the Earth's mean motion around the sun ($0.9856^\circ$ per day): 

$$\large{\dot{\Omega} = - \frac{3}{2} n J_2 \left( \frac{R_E}{a (1-e^2)} \right)^2 \cos(i)}$$
  
- The J2 perturbation causes RAAN precession that depends on inclination (see below): J2 is a coefficient representing Earth oblateness. Because Earth spins, it bulges at the equator, leading to more gravity when satellites cross it.

**Sun-Synchronous Inclination Calculation** (`simulation.js`, lines 53-100):
```javascript
function calculateSunSynchronousInclination(altitudeKm, eccentricity = 0.0) {
  const a = EARTH_RADIUS_KM + altitudeKm;
  const requiredDriftDegPerDay = SOLAR_MEAN_MOTION_DEG_PER_DAY; // ~0.9856 deg/day
  const requiredDriftRadPerSec = requiredDriftDegPerDay * DEG2RAD / 86400.0;
  
  const n = Math.sqrt(MU_EARTH / (a * a * a));
  const p = a * (1 - eccentricity * eccentricity);
  const factor = -1.5 * J2 * Math.pow(EARTH_RADIUS_KM / p, 2) * n;
  const cosI = requiredDriftRadPerSec / factor;
  
  let inclinationDeg = Math.acos(cosI) * RAD2DEG;
  if (inclinationDeg < 90) {
    inclinationDeg = 180 - inclinationDeg;
  }
  return inclinationDeg;
}
```

#### Right Ascension of Ascending Node (RAAN, Ω)

**Parameter:** `RAAN Ω (deg)`  
**Range:** 0° to 360°  
**Default:** 0°  

The RAAN defines where the satellite crosses the equatorial plane from south to north (the ascending node), measured from the vernal equinox (specific moment in time and a specific point in space that marks the beginning of spring in the Northern Hemisphere).
<img width="2428" height="1006" alt="image" src="https://github.com/user-attachments/assets/6db5e9fc-6369-4f6d-9691-9d59fcf1d194" />


**Physical Meaning:**
- Determines the orientation of the orbital plane in inertial space
- Affected by J2 perturbation (precesses over time)
- Critical for constellation design and ground track patterns

#### Argument of Perigee (ω)

**Parameter:** `Argument of perigee ω (deg)`  
**Range:** 0° to 360°  
**Default:** 0°  

The argument of perigee defines the angle from the ascending node to the perigee point, measured in the orbital plane.

**Physical Meaning:**
- Determines where the lowest point of an elliptical orbit occurs
- For circular orbits (e ≈ 0), this parameter has minimal effect
- Affected by J2 perturbation (rotates over time)

#### Mean Anomaly (M₀)

**Parameter:** `Mean anomaly M₀ (deg)`  
**Range:** 0° to 360°  
**Default:** 0°  

The mean anomaly defines the satellite's position along its orbit at the epoch time (the time where values are measured, due to J2 effect as time passes these values have more errors).

**Physical Meaning:**
- M = 0° corresponds to perigee
- M = 180° corresponds to apogee
- Used for timing the satellite's position in constellation design
  (Note: The mean anomaly is the angle considering perfect spheric earth, the real angle is the true anomaly, however to make calculation easier the mean anomaly is used).

<img width="860" height="775" alt="image" src="https://github.com/user-attachments/assets/e7ca67b5-c05b-425d-9844-c8340e1e054b" />


**Kepler's Equation** (solved in `simulation.js`, lines 528-541):
```javascript
function solveKepler(meanAnomaly, eccentricity, tolerance = 1e-8, maxIter = 20) {
  let E = meanAnomaly;
  if (eccentricity > 0.8) E = Math.PI;
  for (let i = 0; i < maxIter; i++) {
    const f = E - eccentricity * Math.sin(E) - meanAnomaly;
    const fPrime = 1 - eccentricity * Math.cos(E);
    const delta = f / fPrime;
    E -= delta;
    if (Math.abs(delta) < tolerance) break;
  }
  return E;
}
```

### J2 Perturbation Effects

The J2 perturbation is the dominant gravitational perturbation affecting satellite orbits, caused by Earth's equatorial bulge (oblateness).

#### Enabling J2 Perturbation

**Checkbox:** `Enable J2 Perturbation`  
**Default:** Enabled ✓

When enabled, the simulator applies secular rate corrections to the RAAN and argument of perigee, providing much more realistic orbit propagation.

#### The J2 Gravitational Coefficient

The J2 coefficient quantifies Earth's oblateness:

$$J_2 = 1.08263 \times 10^{-3}$$

This is defined in `simulation.js`, line 10:
```javascript
const J2 = 1.08263e-3;
```

#### J2 Secular Rate Formulas

The J2 perturbation causes two primary secular effects:

**1. RAAN Precession (nodal regression)**

$$\dot{\Omega} = -\frac{3}{2} J_2 \left(\frac{R_E}{p}\right)^2 n \cos(i)$$

**2. Argument of Perigee Rotation (apsidal rotation)**

$$\dot{\omega} = -\frac{3}{2} J_2 \left(\frac{R_E}{p}\right)^2 n \left(\frac{5}{2}\sin^2(i) - 2\right)$$

Where:
- R_E = Earth's equatorial radius (6,378.137 km)
- p = semi-latus rectum = a(1 - e²)
- n = mean motion = √(μ/a³)
- i = inclination

**Implementation** (`simulation.js`, lines 12-40):
```javascript
function secularRates(a, e, iRad) {
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
    dotOmega,
    dotOmegaDeg: dotOmega * RAD2DEG,
    dotArgPerigee,
    dotArgPerigeeDeg: dotArgPerigee * RAD2DEG,
    meanMotion: n,
  };
}
```

#### Physical Effects of J2

| Effect | Formula | Typical Value (LEO) |
|--------|---------|---------------------|
| RAAN Precession | Depends on cos(i) | -5° to -8° per day |
| Perigee Rotation | Depends on sin²(i) | +2° to +4° per day |
| Critical Inclination | sin²(i) = 4/5 | i = 63.4° or 116.6° |

**Critical Inclination:** At i ≈ 63.4° (or 116.6°), the argument of perigee drift is zero. This is used for Molniya-type orbits where the apogee needs to remain over a specific latitude.

### Resonance and Repeat Ground Tracks

A resonance orbit is one where the satellite completes an integer number of orbits (k) in an integer number of Earth rotations (j). This causes the ground track to repeat exactly after j sidereal days.

#### Resonance Parameters

*The resonance search parameters can be found in the Orbit panel (see Figure 1).*

**Tolerance ± (km):** How close the computed semi-major axis must be to the target  
**Min/Max Rotations (j):** Bounds for Earth rotations  
**Min/Max Orbits (k):** Bounds for satellite orbits  

#### Understanding Resonance Ratios

A j:k resonance means:
- j = number of Earth rotations (sidereal days)
- k = number of satellite orbits

**Example Resonances:**

| Ratio | Meaning | Altitude Range |
|-------|---------|----------------|
| 1:16 | 16 orbits per day | ~278 km (very low) |
| 1:15 | 15 orbits per day | ~555 km |
| 1:14 | 14 orbits per day | ~876 km |
| 1:1 | Geostationary | ~35,786 km |

#### Resonance Search Algorithm

The resonance search finds all j:k combinations that match the target semi-major axis within tolerance.

**Implementation** (`simulation.js`, lines 1051-1101):
```javascript
function searchResonances({
  targetA,
  toleranceKm = 0,
  minRotations,
  maxRotations,
  minOrbits,
  maxOrbits,
  siderealDay = SIDEREAL_DAY,
}) {
  const hits = [];

  for (let j = lowerBoundJ; j <= upperBoundJ; j++) {
    const periodFactor = j * siderealDay;
    for (let k = lowerBoundK; k <= upperBoundK; k++) {
      const period = periodFactor / k;
      const semiMajorKm = aFromPeriod(period);
      const deltaKm = semiMajorKm - center;
      if (Math.abs(deltaKm) <= tolerance) {
        hits.push({
          j, k,
          ratio: j / k,
          periodSec: period,
          semiMajorKm,
          deltaKm,
        });
      }
    }
  }

  return hits;
}
```

#### Ground Track Closure

When a resonance is applied, the simulator verifies that the ground track actually closes by checking:

1. **Surface Gap** - Haversine distance between start and end points
2. **Cartesian Gap** - 3D ECEF distance between start and end positions

**Tolerance Thresholds:**
- Surface: 0.25 km
- Cartesian: 0.1 km

If the ground track closes within tolerance, the simulator will display: *"✔️ Ground track closed (Δ < 0.01 km)."*

---

## Constellation Management

![Constellations Panel](https://github.com/user-attachments/assets/f670d784-c8f7-46fd-82ab-9f6ca3a5d836)

*Figure 2: Constellation configuration panel showing Walker Delta parameters and TLE overlays*

### Walker Delta Constellations

The Walker Delta pattern is a systematic method for distributing satellites in a constellation to achieve global coverage.

#### Walker Notation: T/P/F

The Walker Delta constellation is defined by three parameters:

**T (Total Satellites):** Total number of satellites in the constellation  
**P (Planes):** Number of equally-spaced orbital planes  
**F (Phasing Factor):** Relative phase offset between adjacent planes  

The number of satellites per plane is: S = T / P

#### Walker Generation Algorithm

**Implementation** (`simulation.js`, lines 137-156):
```javascript
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
```

#### RAAN Distribution

The RAAN values are distributed evenly:

$$\Omega_p = \frac{360° \times p}{P}$$

Where p is the plane index (0 to P-1).

#### Mean Anomaly Distribution

Satellites within each plane are distributed:

$$M_s = \frac{360° \times s}{S}$$

The phasing factor adds an offset between planes:

$$M_{p,s} = \frac{360° \times s}{S} + \frac{360° \times F \times p}{T}$$

#### Example: 24/6/1 Constellation

A 24/6/1 Walker constellation:
- 24 total satellites
- 6 orbital planes
- 4 satellites per plane
- Phase factor of 1

| Plane | RAAN | Satellite Mean Anomalies |
|-------|------|--------------------------|
| 0 | 0° | 0°, 90°, 180°, 270° |
| 1 | 60° | 15°, 105°, 195°, 285° |
| 2 | 120° | 30°, 120°, 210°, 300° |
| 3 | 180° | 45°, 135°, 225°, 315° |
| 4 | 240° | 60°, 150°, 240°, 330° |
| 5 | 300° | 75°, 165°, 255°, 345° |

### TLE Constellation Overlays

The simulator can overlay real satellite constellations using Two-Line Element (TLE) data.

#### Available Constellations

| Constellation | Satellites | Purpose |
|---------------|------------|---------|
| Starlink | ~5000+ | Broadband internet |
| OneWeb | ~600+ | Broadband internet |
| GPS | ~31 | Navigation |
| Galileo | ~30 | Navigation |
| GLONASS | ~24 | Navigation |

**Note:** TLE overlays require the `satellite.js` library to be loaded. If the library fails to load, you will see the message: *"satellite.js failed to load; constellation overlays are unavailable."*

#### TLE Propagation

TLE data is propagated using the SGP4/SDP4 propagator through the satellite.js library:

```javascript
const satrec = satellite.twoline2satrec(tle.line1, tle.line2);
const posVel = satellite.propagate(satrec, date);
const gmst = satellite.gstime(date);
const geo = satellite.eciToGeodetic(posVel.position, gmst);
```

### Constellation Optimization

**Note:** Constellation optimization is planned for future versions. Currently, the optimization controls are present in the interface but the full optimization engine is not yet implemented.

#### Optimization Parameters (Future)

- **Simulation Duration (s):** Time span for coverage analysis
- **Control Points:** Ground locations for coverage optimization
- **Workers:** Number of parallel computation threads

The optimization would use a mutation-based approach to minimize revisit times over specified control points.

---

## Optical Link Parameters

The Optics section configures the optical communication link parameters that affect geometric link losses.

### Satellite Aperture

**Parameter:** `Satellite Aperture (m)`  
**Range:** 0.01 m to 2.0 m  
**Default:** 0.6 m  

The diameter of the satellite's optical transmitter/receiver aperture.

### Ground Station Aperture

**Parameter:** `Ground Aperture (m)`  
**Range:** 0.1 m to 5.0 m  
**Default:** 1.0 m  

The diameter of the ground station's optical telescope.

### Wavelength

**Parameter:** `Wavelength (nm)`  
**Range:** 400 nm to 1600 nm  
**Default:** 810 nm  

The wavelength of the optical carrier. Common QKD wavelengths:
- 810 nm - Near-infrared, common for single-photon detection
- 1550 nm - Telecom wavelength, lower atmospheric absorption

### Geometric Loss Calculation

The geometric (free-space) loss is calculated based on beam divergence and receiver aperture:

**Implementation** (`simulation.js`, lines 696-705):
```javascript
function geometricLoss(distanceKm, satAperture, groundAperture, wavelengthNm) {
  const lambda = wavelengthNm * 1e-9; // Convert to meters
  const distanceM = distanceKm * 1000;
  const divergence = 1.22 * lambda / Math.max(satAperture, 1e-3);
  const spotRadius = Math.max(divergence * distanceM * 0.5, 1e-6);
  const captureRadius = groundAperture * 0.5;
  const coupling = Math.min(1, (captureRadius / spotRadius) ** 2);
  const lossDb = -10 * Math.log10(Math.max(coupling, 1e-9));
  return { coupling, lossDb };
}
```

The beam divergence follows the diffraction limit:

$$\theta = 1.22 \frac{\lambda}{D}$$

Where:
- θ = half-angle divergence (radians)
- λ = wavelength
- D = aperture diameter

---

## Ground Station Management

The Stations panel allows you to manage Optical Ground Stations (OGS) for satellite communication.

### Station Parameters

Each ground station is defined by:
- **Name:** Identifier for the station
- **Latitude (°):** Geographic latitude (-90 to +90)
- **Longitude (°):** Geographic longitude (-180 to +180)
- **Aperture (m):** Telescope aperture diameter

### Default European Stations

The simulator comes pre-configured with European OGS:

| Station | Location | Coordinates | Aperture |
|---------|----------|-------------|----------|
| Teide Observatory | Tenerife, Spain | 28.3°N, 16.5°W | 1.0 m |
| Matera Laser Ranging | Italy | 40.6°N, 16.7°E | 1.5 m |
| Côte d'Azur Observatory | France | 43.8°N, 6.9°E | 1.54 m |
| Vienna Observatory | Austria | 48.2°N, 16.4°E | 0.8 m |

### Adding Stations

1. Click **Add Station** to open the station dialog
2. Enter station name and coordinates
3. Optionally use **Pick on map** to select location graphically
4. Click **Save** to add the station

### Station Selection

Select a station from the dropdown to:
- Highlight it on the map and 3D view
- Calculate link metrics to the selected station
- Show the link line (cyan when visible, red when below horizon)

---

## Analytics and Metrics

![Analytics Panel](https://github.com/user-attachments/assets/e34eba28-f355-486d-8de5-246ee964261d)

*Figure 3: Analytics panel showing real-time link metrics*

### Real-Time Link Metrics

The Analytics panel displays live metrics that update as the simulation runs:

#### Link Loss (dB)

The total geometric loss of the optical link:
- Calculated from beam divergence and receiver size
- Increases with distance and decreases with aperture size

#### Elevation (deg)

The elevation angle from the ground station to the satellite:
- Positive values indicate satellite is above the horizon
- Negative values indicate satellite is below the horizon

**Implementation** (`simulation.js`, lines 659-676):
```javascript
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
```

#### Range (km)

The slant range (3D distance) from ground station to satellite.

#### Zenith Angle (deg)

The complement of elevation: `zenith = 90° - elevation`

#### Doppler Shift

The relativistic Doppler factor affecting wavelength:

$$f_{obs} = f_{source} \times \frac{1}{1 - v_r/c}$$

**Implementation** (`simulation.js`, lines 678-694):
```javascript
function dopplerFactor(station, satEcef, satVelEcef, wavelengthNm) {
  const stationEcef = ecefFromLatLon(station.lat, station.lon);
  const rel = [satEcef[0] - stationEcef[0], satEcef[1] - stationEcef[1], satEcef[2] - stationEcef[2]];
  const distance = Math.sqrt(rel[0] ** 2 + rel[1] ** 2 + rel[2] ** 2);
  const unit = rel.map((c) => c / distance);
  const relVel = satVelEcef;
  const radialVelocity = relVel[0] * unit[0] + relVel[1] * unit[1] + relVel[2] * unit[2];
  const c = 299792.458; // km/s
  const factor = 1 / (1 - radialVelocity / c);
  return { factor, observedWavelength: lambdaMeters * factor };
}
```

#### Atmospheric Parameters

When atmospheric data is loaded:

| Metric | Symbol | Units | Description |
|--------|--------|-------|-------------|
| Fried parameter | r₀ | m | Atmospheric coherence length |
| Greenwood frequency | f_G | Hz | Servo bandwidth for AO |
| Isoplanatic angle | θ₀ | arcsec | Angular field for AO correction |
| RMS wind | v | m/s | High-altitude wind speed |

### Full Pass Metrics

Click **Show graph** next to any metric to view its evolution over the complete orbital pass:

- Geometric loss (dB) vs time
- Station elevation (deg) vs time
- Satellite-ground range (km) vs time
- Fried parameter r₀ vs time
- Greenwood frequency vs time
- Isoplanatic angle vs time
- RMS wind speed vs time

---

## Weather Data Integration

The Weather panel allows fetching real meteorological data from Open-Meteo for accurate atmospheric modeling.

### Available Weather Fields

| Field | Units | Pressure Levels |
|-------|-------|-----------------|
| Wind speed | m/s | 200, 250, 300, 500, 700, 850 hPa |
| Temperature | °C | 200, 300, 500, 700, 850 hPa |
| Relative humidity | % | 700, 850, 925 hPa |
| Geopotential height | m | 500, 700, 850 hPa |

### Fetching Weather Data

1. Select the weather variable
2. Choose the pressure level
3. Set the number of grid samples (16-900)
4. Enter the time (UTC)
5. Click **Fetch Field**

The weather data will be displayed as a color-coded overlay on the 2D map.

### Weather Data in Atmospheric Models

Weather data feeds into the atmospheric turbulence models:
- Wind components at 200-300 hPa for Greenwood frequency
- Temperature profiles for turbulence strength
- Humidity for absorption/scattering estimates

---

## Atmospheric Models

![Atmosphere Panel](https://github.com/user-attachments/assets/22ce5433-456a-416c-91ba-200d73f95f75)

*Figure 4: Atmospheric models panel showing Hufnagel-Valley, Bufton, and Greenwood options*

### Hufnagel-Valley 5/7

The Hufnagel-Valley (HV) model is the most commonly used atmospheric turbulence model for optical propagation.

**Open-Meteo Inputs:**
- wind_u_component_300hPa
- wind_v_component_300hPa

**Site Inputs:**
- Cn²(0) day (default: 5×10⁻¹⁴ m⁻²/³)
- Cn²(0) night (default: 5×10⁻¹⁵ m⁻²/³)

**Outputs:**
- r₀ (Fried parameter)
- θ₀ (isoplanatic angle)
- f_G (Greenwood frequency)
- Wind RMS

**Implementation** (`backend.py`):
The atmospheric profile is calculated on the backend using:

```python
r0_zenith = 0.185 * (wavelength_m ** 2 / integral_cn2) ** (3/5)
```

Where integral_cn2 is the path-integrated Cn² through the atmosphere.

### Bufton Boundary-Layer

The Bufton model extends the surface Cn² inputs with wind and temperature gradients.

**Open-Meteo Inputs:**
- Wind components at 300/500/850 hPa
- temperature_850hPa

**Outputs:**
- Layered r₀, θ₀
- Scintillation index

### Greenwood Lidar-Inspired

The Greenwood model targets adaptive optics design.

**Open-Meteo Inputs:**
- wind_u/v at 200 & 300 hPa
- temperature_200hPa
- relative_humidity_700hPa

**Derived:**
- Greenwood frequency
- Coherence time τ₀

### Zenith Angle Scaling

All atmospheric parameters are scaled with zenith angle:

$$r_0(\zeta) = r_0(0) \times \cos^{3/5}(\zeta)$$

$$f_G(\zeta) = f_G(0) \times \cos^{-9/5}(\zeta)$$

$$\theta_0(\zeta) = \theta_0(0) \times \cos^{8/5}(\zeta)$$

**Implementation** (`simulation.js`, lines 962-974):
```javascript
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
```

---

## Quantum Key Distribution (QKD)

The QKD section calculates secure key generation rates for quantum key distribution protocols.

### Supported Protocols

#### BB84 Protocol

The BB84 protocol is the original QKD protocol using single-photon polarization states.

**Parameters:**
- Photon rate (photons/s)
- Detector efficiency
- Dark count rate (counts/s)
- Channel loss (from link budget)

**Key Rate Formula:**

$$R_{secure} = R_{sifted} \times [1 - h(QBER) - f \times h(QBER)]$$

Where:
- h(x) = -x log₂(x) - (1-x) log₂(1-x) is the binary entropy
- f ≈ 1.16 is the error correction efficiency
- QBER is the quantum bit error rate

**Implementation** (`simulation.js`, lines 258-339):
```javascript
function calculateBB84Performance(params) {
  const channelTransmittance = Math.pow(10, -channelLossdB / 10);
  const mu = 0.5; // Mean photon number per pulse
  const detectionRate = photonRate * channelTransmittance * detectorEff * Math.exp(-mu);
  
  const qber = errorRate / (signalRate + errorRate);
  
  const siftingEfficiency = 0.5;
  const siftedKeyRate = (signalRate + errorRate) * siftingEfficiency;
  
  const h = (x) => {
    if (x <= 0 || x >= 1) return 0;
    return -x * Math.log2(x) - (1 - x) * Math.log2(1 - x);
  };
  
  let secureKeyRate = siftedKeyRate - privacyAmplificationCost - errorCorrectionLeakage;
  
  const qberThreshold = 0.11;
  if (qber > qberThreshold) {
    secureKeyRate = 0;
  }
  
  return {
    qber: qber * 100,
    rawKeyRate: siftedKeyRate / 1000,
    secureKeyRate: secureKeyRate / 1000,
    channelTransmittance,
    protocol: 'BB84'
  };
}
```

#### E91 Protocol

The E91 protocol uses entangled photon pairs for security based on Bell inequality violations.

**Key Features:**
- Requires coincidence detection on both ends
- Can tolerate higher QBER (~15%)
- Security based on quantum correlations

#### CV-QKD (Continuous Variable)

Continuous-variable QKD uses the quadrature components of coherent states.

**Key Features:**
- Higher symbol rates possible
- More sensitive to channel loss
- Uses homodyne/heterodyne detection

### QKD Performance Metrics

| Metric | Description | Typical Values |
|--------|-------------|----------------|
| QBER | Quantum Bit Error Rate | 1-5% for secure link |
| Raw Key Rate | Before error correction | 10-1000 kbps |
| Secure Key Rate | After privacy amplification | 1-100 kbps |
| Channel Transmittance | Total optical efficiency | 10⁻² to 10⁻⁵ |

---

## 3D and 2D Visualization

### 3D Earth Globe

The 3D view uses Three.js to render an interactive Earth globe with:

**Earth Rendering** (`ui.js`, lines 1592-1634):
- Custom shader for day/night cycle
- Real Earth textures (Blue Marble)
- Atmospheric glow effect

```javascript
const EARTH_FRAGMENT_SHADER = `
  uniform sampler2D dayMap;
  uniform sampler2D nightMap;
  uniform vec3 sunDirection;
  varying vec2 vUv;
  varying vec3 vNormal;

  void main() {
    vec3 normal = normalize(vNormal);
    vec3 lightDir = normalize(sunDirection);
    float diffuse = max(dot(normal, lightDir), 0.0);
    
    vec3 dayColor = texture2D(dayMap, sampleUv).rgb;
    vec3 nightColor = texture2D(nightMap, sampleUv).rgb;

    float dayMix = smoothstep(-0.2, 0.45, diffuse);
    vec3 color = mix(nightColor * nightStrength, dayColor * (ambientStrength + diffuse), dayMix);
    
    gl_FragColor = vec4(color, 1.0);
  }
`;
```

**Orbital Elements Rendered:**
- Orbit path (purple line)
- Satellite position (orange sphere)
- Ground track on surface (cyan line)
- Nadir vector (dashed line to surface)
- Station markers (blue spheres)
- Link line (cyan=visible, red=below horizon)

### 2D Leaflet Map

The 2D view uses Leaflet for ground track visualization:

**Features:**
- OpenStreetMap or satellite imagery base layers
- Ground track polyline (with anti-meridian handling)
- Satellite marker with footprint circle
- Station markers with tooltips
- Weather field overlays
- Constellation satellite markers

**Anti-meridian Handling** (`ui.js`, lines 1143-1177):
```javascript
function updateGroundTrack(points) {
  const segments = [];
  let current = [];
  let prevLon = null;

  points.forEach((point) => {
    const lon = ((point.lon + 540) % 360) - 180;
    if (prevLon !== null) {
      const delta = Math.abs(lon - prevLon);
      if (delta > 180) { // Wrap around dateline
        if (current.length) segments.push(current);
        current = [];
      }
    }
    current.push([point.lat, lon]);
    prevLon = lon;
  });

  if (current.length) segments.push(current);
  orbitLayer.setLatLngs(segments);
}
```

---

## Technical Architecture

### Project Structure

```
app/
├── backend.py              # FastAPI app factory (~69 lines)
├── main.py                 # Uvicorn entry point
├── models.py               # Pydantic request/response schemas
├── orbital_mechanics.py    # Cosmica integration helpers
├── constellation_manager.py# TLE constellation analysis
│
├── physics/                # All orbital & QKD maths
│   ├── constants.py        # Physical constants (single source of truth)
│   ├── kepler.py           # Kepler equation solver
│   ├── propagation.py      # J2 orbit propagation, ECI↔ECEF
│   ├── geometry.py         # LOS elevation, Doppler, geometric loss
│   ├── qkd.py              # BB84 / decoy-state key-rate formulas
│   ├── walker.py           # Walker-Delta constellation generator
│   └── atmosphere_models.py# Cn² profiles (HV, Bufton, Greenwood)
│
├── services/               # Business-logic adapters
│   ├── database.py         # SQLite gateway (users, chats)
│   ├── ogs_store.py        # JSON persistence for OGS records
│   ├── atmosphere_svc.py   # Atmosphere profile facade + Open-Meteo
│   ├── weather_svc.py      # Gridded weather field builder
│   └── tle_service.py      # CelesTrak TLE fetcher/cache
│
├── routers/                # One router per domain
│   ├── pages.py            # HTML page serving
│   ├── ogs.py              # OGS CRUD
│   ├── atmosphere.py       # Cn² profiles & weather fields
│   ├── orbital.py          # Sun-sync, Walker, repeat track
│   ├── users.py            # Auth & chat
│   ├── tles.py             # TLE group listing/fetching
│   ├── constellation.py    # Constellation analysis/propagation
│   └── solver.py           # POST /api/solve (unified pipeline)
│
├── templates/              # Jinja2 HTML layouts
│   ├── dashboard.html
│   └── immersive.html
│
└── static/
    ├── app.js              # Entry point for template variants
    ├── main.js             # App coordinator, events, lifecycle
    ├── state.js            # Reactive state (pub/sub, mutations)
    ├── stations.js         # OGS API helpers & built-in list
    ├── formatters.js       # Numeric display formatters
    ├── tooltips.js         # Info-button tooltip manager
    ├── weather.js          # Weather field config & helpers
    ├── simulation.js       # Facade (delegates physics to backend)
    ├── ui.js               # Three.js + Leaflet rendering
    ├── api.js              # HTTP client for all endpoints
    ├── utils.js            # Math helpers, formatting
    ├── propagateWorker.js  # Web Worker for TLE propagation
    ├── index.html          # Legacy standalone HTML
    └── styles/app.css      # Application stylesheet
```

### Design Principles

| Principle | Implementation |
|-----------|----------------|
| **Physics in backend only** | All orbital, atmospheric and QKD computations live in `app/physics/`. The frontend `simulation.js` is a thin façade. |
| **File size ≤ 250 lines** | Every new Python module stays within the 200-300 line budget. Legacy JS files are documented for further decomposition. |
| **Single source of truth** | Physical constants defined once in `physics/constants.py`. |
| **Unified solver** | `POST /api/solve` orchestrates: propagation → station metrics → QKD. |

### Backend (Python/FastAPI)

| Layer | Files | Responsibility |
|-------|-------|----------------|
| **App factory** | `backend.py` | Wire services, mount routers, serve static files |
| **Routers** | `routers/*.py` | HTTP interface, validation, error mapping |
| **Services** | `services/*.py` | Business logic, caching, external APIs |
| **Physics** | `physics/*.py` | Pure functions, no I/O, fully testable |
| **Models** | `models.py` | Pydantic schemas for requests/responses |

### Frontend (JavaScript ES Modules)

**Module Structure:**

| Module | Lines | Purpose | Key Exports |
|--------|-------|---------|-------------|
| `app.js` | 8 | Entry point for template variants | Imports `main.js` |
| `main.js` | ~3100 | App coordinator, events, charts, lifecycle | `initialize()` |
| `state.js` | 313 | Reactive state (pub/sub, mutations) | `state`, `subscribe`, `mutate`, `emit` |
| `stations.js` | 113 | Built-in OGS list & CRUD helpers | `loadStationsFromServer`, `persistStation` |
| `formatters.js` | 104 | Numeric display formatters | `formatR0Meters`, `normalizeLongitude`, … |
| `tooltips.js` | 144 | Info-button tooltip manager | `initInfoButtons` |
| `weather.js` | 124 | Weather field config & DOM helpers | `WEATHER_FIELDS`, `setWeatherElements` |
| `simulation.js` | 418 | Physics facade (delegates to api.js) | `orbit`, `walkerGenerator`, `qkdCalculations` |
| `ui.js` | 2520 | Three.js 3D scene & Leaflet 2D map | `map2d`, `scene3d` |
| `api.js` | 110 | HTTP client for all endpoints | `api.*` (solve, listOGS, …) |
| `utils.js` | 206 | Math/format utility functions | `haversineDistance`, `formatAngle`, … |
| `propagateWorker.js` | 161 | Web Worker for TLE propagation | (postMessage interface) |

### State Management

The application uses a publish/subscribe pattern implemented in `state.js`:

```javascript
// state.js — reactive state container
import { isoNowLocal } from './utils.js';

const state = { ... };          // single mutable state tree
const listeners = new Set();

export function subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); }
export function emit()         { listeners.forEach(fn => fn(state)); }
export function mutate(fn)     { fn(state); emit(); }
```

Higher-level mutations (`setTheme`, `setComputed`, `togglePlay`, …) are also
exported from `state.js` and imported by `main.js`.

### Coordinate Systems

**ECI (Earth-Centered Inertial):**
- X: Vernal equinox direction
- Z: North pole
- Used for orbit propagation

**ECEF (Earth-Centered Earth-Fixed):**
- Rotates with Earth
- Used for ground position calculations

**Geographic:**
- Latitude, Longitude, Altitude
- Used for display and user input

**Transformation Chain:**
```
Orbital Elements → Perifocal → ECI → ECEF → Geographic
```

---

## API Reference

### Unified Solver (main pipeline)

```
POST /api/solve
Content-Type: application/json

{
  "semi_major_axis_km": 6878.0,
  "eccentricity": 0.001,
  "inclination_deg": 53.0,
  "raan_deg": 0.0,
  "arg_perigee_deg": 0.0,
  "mean_anomaly_deg": 0.0,
  "station_lat": 40.4,
  "station_lon": -3.7,
  "station_alt_m": 650,
  "aperture_m": 1.0,
  "wavelength_nm": 810,
  "detector_efficiency": 0.1,
  "dark_count_rate": 100,
  "pointing_error_urad": 2.0,
  "protocol": "bb84",
  "cn2_model": "hufnagel-valley",
  "ground_cn2": 1.7e-14,
  "wind_speed_rms": 21.0,
  "duration_s": 600,
  "dt_s": 1.0
}
```
Returns: propagated orbit + station metrics + QKD key rates.

### Health Check

```
GET /health
```
Returns: `{"status": "ok"}`

### Ground Stations

```
GET /api/ogs
```
List all ground stations.

```
POST /api/ogs
Content-Type: application/json

{
  "id": "station-id",
  "name": "Station Name",
  "lat": 48.2,
  "lon": 16.4,
  "aperture_m": 1.0
}
```
Create a new ground station.

```
DELETE /api/ogs/{station_id}
```
Delete a specific station.

### TLE Data

```
GET /api/tles/{group_id}
```
Fetch TLE data for a constellation group (starlink, oneweb, gps, galileo, glonass).

### Atmospheric Profile

```
POST /api/get_atmosphere_profile
Content-Type: application/json

{
  "lat": 48.2,
  "lon": 16.4,
  "time": "2025-01-01T12:00:00Z",
  "ground_cn2_day": 5e-14,
  "ground_cn2_night": 5e-15,
  "model": "hufnagel-valley",
  "wavelength_nm": 810
}
```

### Weather Field

```
POST /api/get_weather_field
Content-Type: application/json

{
  "variable": "wind_speed",
  "level_hpa": 300,
  "samples": 120,
  "time": "2025-01-01T12:00:00Z"
}
```

### Orbital Mechanics

```
GET /api/orbital/sun-synchronous?altitude_km=700&eccentricity=0
```
Calculate sun-synchronous inclination.

```
GET /api/orbital/walker-constellation?T=24&P=6&F=1&altitude_km=1000&inclination_deg=53
```
Generate Walker constellation elements.

---

## Libraries and Dependencies

### Python Backend

| Library | Version | Purpose |
|---------|---------|---------|
| FastAPI | 0.115.0 | Web framework |
| Uvicorn | 0.30.6 | ASGI server |
| NumPy | 2.1.2 | Numerical computations |
| SciPy | 1.14.1 | Scientific algorithms |
| Pandas | 2.3.3 | Data manipulation |
| GeoPandas | 1.1.1 | Geographic data |
| Requests | 2.32.3 | HTTP client |
| Cosmica | 0.3.0 | Orbital dynamics |
| Skyfield | 1.53 | Astronomy calculations |
| SGP4 | 2.25 | TLE propagation |
| Jinja2 | 3.1.4 | HTML templating |

### JavaScript Frontend

| Library | Source | Purpose |
|---------|--------|---------|
| Three.js | CDN import | 3D rendering |
| Leaflet | CDN | 2D mapping |
| Chart.js | CDN | Graphing |
| satellite.js | CDN | TLE propagation |

### Usage in Code

**Three.js** (`ui.js`):
```javascript
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
```

**Leaflet** (`ui.js`):
```javascript
map = L.map(container, { ... });
L.tileLayer(TILE_URL).addTo(map);
L.polyline(points, { color: '#7c3aed' }).addTo(map);
```

---

## Formulas and Algorithms

### Kepler's Equation

$$M = E - e \sin(E)$$

Solved iteratively using Newton-Raphson method.

### Orbital Position

From eccentric anomaly E:

$$r = a(1 - e \cos E)$$

$$\nu = 2 \arctan\left(\sqrt{\frac{1+e}{1-e}} \tan\frac{E}{2}\right)$$

### GMST (Greenwich Mean Sidereal Time)

$$\theta_{GMST} = 280.46061837° + 360.98564736629 × d + 0.000387933 × T^2$$

Where d = Julian date - 2451545.0

### Haversine Distance

$$d = 2R \arcsin\sqrt{\sin^2\frac{\Delta\phi}{2} + \cos\phi_1 \cos\phi_2 \sin^2\frac{\Delta\lambda}{2}}$$

### Link Budget

$$L_{geo} = 20 \log_{10}\left(\frac{4\pi d}{\lambda}\right) - 20 \log_{10}(D_t D_r)$$

---

## Future Development

The following features are planned for future versions but are **not yet implemented**:

### Currently Not Implemented

1. **Constellation Optimization Engine**
   - The "Optimize Design" button and related controls are present but optimization logic is not yet complete
   - Future: Will use evolutionary algorithms to minimize revisit time

2. **Control Point Definition**
   - The "Define Control Points" interface exists but is not fully functional
   - Future: Will allow drawing polygons for coverage optimization

3. **Web Worker Precomputation**
   - The worker toggle exists but parallel propagation is not fully integrated
   - Future: Will offload heavy computations to background threads

4. **Advanced Atmospheric Models**
   - Some model parameters show placeholder values
   - Future: Will integrate more sophisticated turbulence profiles

5. **QKD Protocol Details**
   - Basic calculations exist but detailed finite-key analysis is planned
   - Future: Will include security parameter optimization

### Planned Enhancements

- Decompose `main.js` (4 k lines) and `ui.js` (2.7 k lines) into ≤ 250-line ES modules
- Multi-segment ground tracks with segment coloring
- Satellite collision analysis
- Ground coverage heat maps
- Export functionality (KML, CZML, JSON)
- Multi-station scheduling optimization
- Real-time TLE updates
- Historical weather data analysis

---

## Contributing

When adding new features:

1. **Physics** → add pure functions to `app/physics/` (keep each module ≤ 250 lines)
2. **External I/O** → add or extend a service in `app/services/`
3. **HTTP endpoint** → add a router in `app/routers/`; include Pydantic models in `app/models.py`
4. **Frontend API call** → add a method to `app/static/api.js`
5. **Visualization** → update `app/static/ui.js`
6. **State / lifecycle** → update `app/static/main.js`
7. Update this README with documentation

---

## License

See repository for license information.

---

*This documentation was generated for QKD Satellite Link Simulator v1.0*
