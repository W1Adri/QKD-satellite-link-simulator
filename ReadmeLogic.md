# ReadmeLogic

## Objetivo de este documento
Este archivo describe la arquitectura modular del QKD Satellite Link Simulator, explicando:
- Organización de archivos y carpetas
- Responsabilidades de cada módulo
- Flujo de datos entre frontend y backend
- Conexiones entre componentes

---

## Esquema de Arquitectura

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              FRONTEND (Browser)                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │   main.js   │───▶│  state.js   │    │ stations.js │    │  weather.js │  │
│  │ (~3100 lín.) │    │  (estado)   │    │  (API OGS)  │    │  (campos)   │  │
│  └──────┬──────┘    └─────────────┘    └─────────────┘    └─────────────┘  │
│         │                                                                    │
│         │  imports                                                           │
│         ▼                                                                    │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐  │
│  │simulation.js│    │formatters.js│    │ tooltips.js │    │   utils.js  │  │
│  │  (façade)   │    │ (formateo)  │    │ (info tips) │    │  (helpers)  │  │
│  └──────┬──────┘    └─────────────┘    └─────────────┘    └─────────────┘  │
│         │                                                                    │
│         ▼                                                                    │
│  ┌─────────────┐    ┌─────────────────────────────────────────────────────┐ │
│  │   api.js    │───▶│                      ui.js                          │ │
│  │ (HTTP client)│   │  ┌───────────┐  ┌───────────┐  ┌───────────────┐   │ │
│  └──────┬──────┘    │  │  map2d    │  │  scene3d  │  │ earthTexture  │   │ │
│         │           │  │ (Leaflet) │  │ (Three.js)│  │  (texturas)   │   │ │
│         │           │  └───────────┘  └───────────┘  └───────────────┘   │ │
│         │           └─────────────────────────────────────────────────────┘ │
│         │                                                                    │
│         │  fetch()                                                           │
└─────────┼────────────────────────────────────────────────────────────────────┘
          │
          ▼  HTTP/JSON
┌─────────────────────────────────────────────────────────────────────────────┐
│                              BACKEND (FastAPI)                               │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                         app/backend.py (~69 líneas)                      ││
│  │                         [App Factory + Router Wiring]                    ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│         │                                                                    │
│         │  monta routers                                                     │
│         ▼                                                                    │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                           app/routers/                                   ││
│  │  ┌────────┐ ┌────────┐ ┌────────────┐ ┌────────┐ ┌──────────────────┐  ││
│  │  │pages.py│ │ogs.py  │ │atmosphere.py│ │tles.py │ │constellation.py  │  ││
│  │  │        │ │        │ │             │ │        │ │                  │  ││
│  │  └────────┘ └────────┘ └────────────┘ └────────┘ └──────────────────┘  ││
│  │  ┌────────┐ ┌────────┐ ┌────────────┐                                   ││
│  │  │users.py│ │orbital.py│ │ solver.py │  ◀── POST /api/solve             ││
│  │  │        │ │         │ │ (pipeline) │                                   ││
│  │  └────────┘ └─────────┘ └────────────┘                                   ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│         │                                                                    │
│         │  usa servicios                                                     │
│         ▼                                                                    │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                          app/services/                                   ││
│  │  ┌─────────────┐ ┌─────────────┐ ┌───────────────┐ ┌─────────────────┐ ││
│  │  │ database.py │ │ ogs_store.py│ │atmosphere_svc │ │ weather_svc.py  │ ││
│  │  │  (SQLite)   │ │   (JSON)    │ │   (OpenMeteo) │ │   (OpenMeteo)   │ ││
│  │  └─────────────┘ └─────────────┘ └───────────────┘ └─────────────────┘ ││
│  │  ┌─────────────┐                                                        ││
│  │  │tle_service.py│                                                       ││
│  │  │ (CelesTrak) │                                                        ││
│  │  └─────────────┘                                                        ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│         │                                                                    │
│         │  importa física                                                    │
│         ▼                                                                    │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                           app/physics/                                   ││
│  │  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐           ││
│  │  │constants.py│ │ kepler.py  │ │propagation │ │ geometry.py│           ││
│  │  │ (MU, R, J2)│ │ (Newton-R) │ │   .py      │ │ (LOS, loss)│           ││
│  │  └────────────┘ └────────────┘ └────────────┘ └────────────┘           ││
│  │  ┌────────────┐ ┌────────────┐ ┌────────────────────┐                   ││
│  │  │   qkd.py   │ │ walker.py  │ │atmosphere_models.py│                   ││
│  │  │(BB84/E91)  │ │  (Walker-Δ)│ │   (HV, Bufton)     │                   ││
│  │  └────────────┘ └────────────┘ └────────────────────┘                   ││
│  └─────────────────────────────────────────────────────────────────────────┘│
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Estructura de Archivos

### Backend: `app/`

```
app/
├── backend.py              # App factory (~69 líneas) - monta routers y servicios
├── main.py                 # Punto de entrada Uvicorn
├── models.py               # Esquemas Pydantic (OGSLocation, SolveRequest, etc.)
├── orbital_mechanics.py    # Helpers de Cosmica (sun-sync, Walker, repeat-track)
├── constellation_manager.py# Análisis de constelaciones TLE
│
├── physics/                # Cálculos físicos puros (sin I/O)
│   ├── __init__.py
│   ├── constants.py        # MU_EARTH, EARTH_RADIUS_KM, J2, J3, J4, c, h
│   ├── kepler.py           # Solver de Kepler (Newton-Raphson)
│   ├── propagation.py      # Propagación J2, ECI↔ECEF, ground track
│   ├── geometry.py         # Elevación LOS, Doppler, pérdida geométrica
│   ├── qkd.py              # BB84, E91, CV-QKD (tasas de clave)
│   ├── walker.py           # Generador Walker-Delta
│   └── atmosphere_models.py# Perfiles Cn² (HV57, Bufton, Greenwood)
│
├── services/               # Adaptadores de negocio
│   ├── __init__.py
│   ├── database.py         # SQLite gateway (usuarios, chats)
│   ├── ogs_store.py        # Persistencia JSON para OGS
│   ├── atmosphere_svc.py   # Fachada de perfiles atmosféricos + Open-Meteo
│   ├── weather_svc.py      # Constructor de campos meteorológicos
│   └── tle_service.py      # Fetcher/cache de TLE desde CelesTrak
│
├── routers/                # Endpoints HTTP (un router por dominio)
│   ├── __init__.py
│   ├── pages.py            # Servicio de páginas HTML (/, /layouts/{variant})
│   ├── ogs.py              # CRUD de estaciones (GET/POST/DELETE /api/ogs)
│   ├── atmosphere.py       # POST /api/get_atmosphere_profile, /api/get_weather_field
│   ├── orbital.py          # GET /api/orbital/sun-synchronous, /walker-constellation
│   ├── users.py            # Auth y chat (POST /api/login, GET /api/users)
│   ├── tles.py             # GET /api/tles, /api/tles/{group_id}
│   ├── constellation.py    # POST /api/constellation/analyze, /propagate
│   └── solver.py           # POST /api/solve  ← Pipeline unificado
│
├── templates/              # HTML extraído del backend original
│   ├── dashboard.html      # Layout dashboard
│   └── immersive.html      # Layout inmersivo
│
└── data/
    └── app.sqlite3         # Base de datos SQLite
```

### Frontend: `app/static/`

```
app/static/
├── index.html              # Layout compacto (carga main.js)
│
├── main.js                 # Coordinador principal (~3100 líneas)
│   │                       # - Eventos UI, lifecycle, charts
│   │                       # - Importa de módulos extraídos
│   │
│   ├── imports ──────────────────────────────────────────────────┐
│   │                                                              │
├── state.js                # Estado reactivo (pub/sub) ◀──────────┤
│                           # - defaultState, state, listeners     │
│                           # - subscribe, emit, mutate            │
│                           # - Helpers de estaciones/constelaciones│
│                                                                   │
├── stations.js             # API de estaciones ◀───────────────────┤
│                           # - loadStationsFromServer              │
│                           # - persistStation, deleteStationRemote │
│                                                                   │
├── formatters.js           # Formateadores de valores ◀────────────┤
│                           # - formatR0Meters, formatKm            │
│                           # - normalizeLongitude, formatDecimal   │
│                                                                   │
├── tooltips.js             # Gestión de tooltips ◀─────────────────┤
│                           # - initInfoButtons, showInfoTooltip    │
│                                                                   │
├── weather.js              # Configuración de campos meteo ◀───────┘
│                           # - WEATHER_FIELDS, populateOptions
│
├── simulation.js           # Façade de física (~418 líneas)
│                           # - Delega cálculos al backend via api.js
│                           # - Mantiene interfaz compatible con main.js
│
├── api.js                  # Cliente HTTP thin (~110 líneas)
│                           # - api.solve(), api.listOGS(), etc.
│
├── ui.js                   # Renderizado (~2520 líneas)
│                           # - map2d (Leaflet 2D)
│                           # - scene3d (Three.js 3D)
│                           # - earthTexture (texturas procedurales)
│                           # - initSliders, createPanelAccordions
│
├── utils.js                # Utilidades matemáticas (~206 líneas)
│                           # - DEG2RAD, clamp, lerp, haversine
│
├── propagateWorker.js      # Web Worker para propagación TLE
│
├── app.js                  # Entry point para templates
│
├── ogs_locations.json      # Persistencia local de OGS
│
└── styles/
    └── app.css             # Estilos de la aplicación
```

---

## Flujos de Datos

### 1. Flujo de Cálculo Orbital Completo

```
Usuario ajusta UI
       │
       ▼
┌─────────────────┐
│    main.js      │  detecta cambio en state.orbital
│ onStateChange() │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ recomputeOrbit()│
└────────┬────────┘
         │
         ├──────────────────────────────────────────────────┐
         │                                                   │
         ▼                                                   ▼
┌─────────────────┐                               ┌─────────────────────┐
│ simulation.js   │   (cálculo local rápido)      │      api.js         │
│ orbit.propagate │                               │ api.solve() ────────┼──▶ POST /api/solve
│ Orbit()         │                               │                     │
└────────┬────────┘                               └─────────┬───────────┘
         │                                                   │
         │                                                   ▼
         │                                        ┌─────────────────────┐
         │                                        │  routers/solver.py  │
         │                                        │  - propagate_orbit  │
         │                                        │  - compute_metrics  │
         │                                        │  - calculate_qkd    │
         │                                        └─────────┬───────────┘
         │                                                   │
         │                                                   ▼
         │                                        ┌─────────────────────┐
         │                                        │    physics/*        │
         │                                        │  kepler + geometry  │
         │                                        │  + qkd + propagation│
         │                                        └─────────┬───────────┘
         │                                                   │
         ▼                                                   ▼
┌─────────────────┐                               ┌─────────────────────┐
│  state.computed │ ◀─────────────────────────────│   JSON Response     │
│   (actualizado) │                               │ orbit, metrics, qkd │
└────────┬────────┘                               └─────────────────────┘
         │
         ▼
┌─────────────────┐
│     ui.js       │
│ map2d.update..()│
│ scene3d.update()│
└─────────────────┘
```

### 2. Flujo de Estaciones OGS

```
┌──────────────┐     GET /api/ogs      ┌──────────────┐
│  stations.js │ ───────────────────▶  │ routers/ogs.py│
│ loadFromServer│                      │               │
└──────────────┘                       └───────┬───────┘
                                               │
                                               ▼
                                       ┌──────────────┐
                                       │ogs_store.py  │
                                       │ JSON file    │
                                       └──────────────┘
```

### 3. Flujo de Perfil Atmosférico

```
┌──────────────┐  POST /api/get_atmosphere_profile  ┌─────────────────┐
│   main.js    │ ────────────────────────────────▶  │routers/atmosphere│
│recomputeMetrics│                                   │                 │
└──────────────┘                                     └────────┬────────┘
                                                              │
                                                              ▼
                                                     ┌─────────────────┐
                                                     │atmosphere_svc.py│
                                                     │  OpenMeteoClient│
                                                     └────────┬────────┘
                                                              │
                                                              ▼
                                                     ┌─────────────────┐
                                                     │physics/atmosphere│
                                                     │_models.py       │
                                                     │ HV57, Bufton...  │
                                                     └─────────────────┘
```

---

## Conexiones entre Módulos

### Frontend

| Módulo | Importa de | Exporta a |
|--------|-----------|-----------|
| `main.js` | state, stations, formatters, tooltips, weather, simulation, ui, utils | — (entry point) |
| `state.js` | utils | main.js |
| `stations.js` | state | main.js |
| `formatters.js` | — | main.js |
| `tooltips.js` | — | main.js |
| `weather.js` | — | main.js |
| `simulation.js` | api, utils | main.js |
| `api.js` | — | simulation.js, main.js |
| `ui.js` | utils, simulation | main.js |

### Backend

| Módulo | Importa de | Usado por |
|--------|-----------|-----------|
| `backend.py` | todos los routers, todos los servicios | run_app.py |
| `routers/solver.py` | physics/*, services/* | backend.py |
| `routers/ogs.py` | services/ogs_store | backend.py |
| `routers/atmosphere.py` | services/atmosphere_svc, weather_svc | backend.py |
| `services/atmosphere_svc.py` | physics/atmosphere_models | routers/atmosphere |
| `physics/propagation.py` | physics/kepler, constants | routers/solver |
| `physics/geometry.py` | physics/constants | routers/solver |
| `physics/qkd.py` | — | routers/solver |

---

## Endpoints API Principales

| Endpoint | Método | Descripción | Router |
|----------|--------|-------------|--------|
| `/api/solve` | POST | Pipeline unificado (propagación + métricas + QKD) | solver.py |
| `/api/ogs` | GET/POST/DELETE | CRUD de estaciones terrestres | ogs.py |
| `/api/get_atmosphere_profile` | POST | Perfil Cn² atmosférico | atmosphere.py |
| `/api/get_weather_field` | POST | Campo meteorológico 2D | atmosphere.py |
| `/api/tles/{group}` | GET | TLEs de constelación | tles.py |
| `/api/orbital/sun-synchronous` | GET | Cálculo de órbita sun-sync | orbital.py |
| `/api/orbital/walker-constellation` | GET | Generador Walker-Delta | orbital.py |
| `/health` | GET | Health check | pages.py |

---

## Principios de Diseño

| Principio | Implementación |
|-----------|----------------|
| **Física solo en backend** | Todos los cálculos orbitales, atmosféricos y QKD están en `app/physics/`. El frontend `simulation.js` es una façade ligera. |
| **Archivos ≤ 250 líneas** | Todos los módulos Python nuevos respetan este límite. Los JS legacy (main.js, ui.js) están documentados para futura descomposición. |
| **Fuente única de verdad** | Constantes físicas en `physics/constants.py`. Estado frontend en `state.js`. |
| **Separación de responsabilidades** | Routers → HTTP; Services → lógica de negocio; Physics → cálculos puros. |
| **Sin duplicación de físicas** | El frontend delega al backend; `simulation.js` mantiene solo interfaces compatibles. |

---

## Qué calcula `main.js` vs `simulation.js`

### `main.js` (orquestación)
`main.js` NO implementa la física orbital de bajo nivel. Hace principalmente:
- Gestión de estado global (`state`) y mutaciones (via `state.js`).
- Enlace de eventos de UI (sliders, botones, forms).
- Llamadas API (`/api/ogs`, `/api/get_weather_field`, `/api/get_atmosphere_profile`).
- Decidir cuándo recalcular (`onStateChange` + firmas).
- Pasar datos a motor visual (2D/3D/charts) y pintar resultados.

### `simulation.js` (façade delegadora)
Tras el refactoring, `simulation.js` actúa como façade que:
- Mantiene la interfaz original (`orbit.propagateOrbit`, `computeStationMetrics`).
- Delega los cálculos pesados al backend via `api.js`.
- Permite cálculos locales rápidos para preview interactivo.

En resumen:
- `main.js` coordina y conecta.
- `simulation.js` es una façade que delega al backend.
- `app/physics/` contiene la física real (Python).

---

## Notas para Desarrollo Futuro

1. **Descomposición de main.js (parcialmente completada)**: Los módulos `state.js`, `stations.js`, `formatters.js`, `tooltips.js`, `weather.js` ya están extraídos (reducción de ~4000 → ~3100 líneas). Candidatos restantes:
   - Event binding → `events.js`
   - Chart rendering → `charts.js`
   - Resonance search → `resonance.js`
   - Playback loop → `playback.js`
   - Optimizer (Walker/revisit) → `optimizer.js`

2. **Descomposición de ui.js (~2520 líneas)**: Estructura interna identificada:
   - Geodata/textures → `geodata.js` + `textures.js`
   - map2d (Leaflet) → `map2d.js`
   - scene3d (Three.js) → `scene3d.js`

3. **Formatters duplicados**: `main.js` mantiene versiones locales de `formatKm`, `formatDecimal`, `normalizeInt`, `normalizeTolerance` que difieren de `formatters.js`. Unificar en una sola implementación.

4. **Testing**: Añadir tests unitarios para `app/physics/` usando pytest.

5. **Números de línea en esta documentación**: Las referencias a líneas en secciones 2-9 corresponden al código pre-refactoring y pueden no coincidir exactamente con los archivos actuales.

---

## Inventario completo de calculos numericos y formulas

Este bloque documenta los calculos matematicos de TODO el proyecto (`app/`) y como fluyen los datos:
- de donde salen (UI/API/estado),
- en que bucles se procesan,
- que formula concreta se aplica,
- y donde se consume el resultado.

## 1) Flujo numerico global (entrada -> calculo -> salida)

1. Entrada de parametros orbitales y opticos en UI/estado:
   - estado base: `app/static/main.js:41` a `app/static/main.js:130`.
2. Orquestacion del recalculo:
   - `recomputeOrbit(force)`: `app/static/main.js:3100`.
   - `recomputeMetricsOnly(force)`: `app/static/main.js:3157`.
3. Motor fisico principal:
   - propagacion orbital y resonancia: `orbit.propagateOrbit(...)` en `app/static/main.js:3108`, implementado en `app/static/simulation.js:713`.
   - metricas enlace OGS-satelite: `orbit.computeStationMetrics(...)` en `app/static/main.js:3121` y `app/static/main.js:3198`, implementado en `app/static/simulation.js:906`.
4. Atmosfera/weather (backend):
   - perfil atmosfera: `POST /api/get_atmosphere_profile` en `app/backend.py:1752`.
   - campo meteorologico: `POST /api/get_weather_field` en `app/backend.py:1778`.
5. Salidas:
   - arrays temporales (`distanceKm`, `elevationDeg`, `lossDb`, `doppler`, `r0_array`, etc.) en `state.computed.metrics`: `app/static/main.js:3217`.
   - render 2D/3D/charts: `app/static/main.js:3226`, `app/static/main.js:3533`, `app/static/ui.js:1143`, `app/static/ui.js:2336`.

---

## 2) Calculo orbital y de metricas (core) en `app/static/simulation.js`

> **Nota:** Los números de línea en esta sección y las siguientes corresponden
> a la versión pre-refactoring de `simulation.js`.  La versión actual (~418 líneas)
> es una façade que delega los cálculos pesados al backend Python (`app/physics/`).
> Las fórmulas documentadas siguen siendo válidas conceptualmente.

### 2.1 Constantes y conversiones
- `MU_EARTH`, `EARTH_RADIUS_KM`, `J2`: `app/static/simulation.js:8` a `app/static/simulation.js:10`.
- `EARTH_ROT_RATE`, `SIDEREAL_DAY`: `app/static/simulation.js:492`, `app/static/simulation.js:493`.
- conversiones periodo/semi-major:
  - `aFromPeriod`: `app/static/simulation.js:1038`.
  - `periodFromA`: `app/static/simulation.js:1042`.

### 2.2 Perturbaciones J2 (precesion secular)
- funcion: `secularRates(a, e, iRad)` en `app/static/simulation.js:12`.
- formulas:
  - `n = sqrt(mu / a^3)`: `app/static/simulation.js:16`.
  - `p = a * (1 - e^2)`: `app/static/simulation.js:17`.
  - `factor = -1.5 * J2 * (R/p)^2 * n`: `app/static/simulation.js:25`.
  - `dotOmega = factor * cos(i)`: `app/static/simulation.js:28`.
  - `dotArgPerigee = factor * (2.5*sin^2(i) - 2)`: `app/static/simulation.js:31`.
- uso dentro de propagacion temporal:
  - activacion J2: `app/static/simulation.js:826` a `app/static/simulation.js:830`.
  - aplicacion por muestra temporal: `raan_t = raan + dotOmega*t`, `argPerigee_t = arg + dotArgPerigee*t`: `app/static/simulation.js:834`, `app/static/simulation.js:835`.

### 2.3 Sol-orbita sincronica
- inclinacion requerida:
  - funcion: `calculateSunSynchronousInclination`: `app/static/simulation.js:53`.
  - deriva objetivo solar: `requiredDriftRadPerSec`: `app/static/simulation.js:59`, `app/static/simulation.js:60`.
  - despeje de `cos(i)` desde ecuacion J2: `app/static/simulation.js:68`, `app/static/simulation.js:74`.
  - resolucion `i = acos(cosI)`: `app/static/simulation.js:85`.
- validacion:
  - `validateSunSynchronousOrbit`: `app/static/simulation.js:109`.
  - drift real por dia: `app/static/simulation.js:114`.
  - error absoluto/porcentual: `app/static/simulation.js:117`, `app/static/simulation.js:125`.

### 2.4 Walker-Delta
- generador: `generateWalkerConstellation(T,P,F,a,i,e,raanOffset)` en `app/static/simulation.js:137`.
- bucles:
  - planos `for p`: `app/static/simulation.js:141`.
  - satelites por plano `for s`: `app/static/simulation.js:143`.
- formulas:
  - `raan = 360*p/P + offset`: `app/static/simulation.js:142`.
  - `M = 360*s/S + 360*F*p/T`: `app/static/simulation.js:144`.

### 2.5 Revisit y optimizacion (numerica discreta)
- `computeRevisitTime(...)`: `app/static/simulation.js:160`.
  - bucle tiempo `ti`: `app/static/simulation.js:168`.
  - bucles satelites/constelaciones: `app/static/simulation.js:171` a `app/static/simulation.js:177`.
  - distancia angular sobre esfera (haversine): `app/static/simulation.js:186`.
  - intervalos de revisita `diffs[k]=t[k]-t[k-1]`: `app/static/simulation.js:196`.
  - metricas agregadas:
    - max por punto: `app/static/simulation.js:198`.
    - media por punto: `app/static/simulation.js:199`.
    - max global / media global: `app/static/simulation.js:205`, `app/static/simulation.js:206`.
- `mutateConstellation(...)`: `app/static/simulation.js:210`.
  - perturbaciones aleatorias `deltaRaan`, `deltaM`: `app/static/simulation.js:213`, `app/static/simulation.js:214`.
- `optimizeConstellation(...)`: `app/static/simulation.js:223`.
  - bucle iterativo: `app/static/simulation.js:230`.
  - tamano de mutacion decreciente: `max(0.1, 5*(1-it/iterations))`: `app/static/simulation.js:231`.
  - criterio de mejora: `score < bestScore`: `app/static/simulation.js:235`.

### 2.6 QKD (BB84/E91/CV-QKD)
- router de protocolo: `calculateQKDPerformance`: `app/static/simulation.js:467`.
- BB84 (`app/static/simulation.js:258`):
  - transmitancia canal: `10^(-Loss_dB/10)`: `app/static/simulation.js:273`.
  - tasa deteccion: `photonRate * T * detectorEff * exp(-mu)`: `app/static/simulation.js:278`.
  - QBER: `errorRate/(signalRate+errorRate)`: `app/static/simulation.js:287`.
  - entropia binaria `h(x)`: `app/static/simulation.js:296` a `app/static/simulation.js:299`.
  - clave segura: `R_sifted - h(QBER)R_sifted - 1.16*h(QBER)R_sifted`: `app/static/simulation.js:305` a `app/static/simulation.js:308`.
  - umbral QBER (11%): `app/static/simulation.js:311`.
- E91 (`app/static/simulation.js:346`):
  - coincidencias: `pairRate * (T*detectorEff)^2`: `app/static/simulation.js:365`.
  - accidental rate: `dark^2 / pairRate`: `app/static/simulation.js:368`.
  - QBER: `accidental/(coincidence+accidental)`: `app/static/simulation.js:369`.
  - clave segura: `coincidence*(1-2h(qber))`: `app/static/simulation.js:379`.
- CV-QKD (`app/static/simulation.js:414`):
  - `T = 10^(-Loss_dB/10)`: `app/static/simulation.js:427`.
  - `SNR = totalTransmittance*modulationVariance/(1+electronicNoise)`: `app/static/simulation.js:432`.
  - clave segura: `symbolRate*max(0, log2(1+snr)-log2(1+excessNoise))`: `app/static/simulation.js:436`.
  - QBER efectivo: `excessNoise/(snr+excessNoise)`: `app/static/simulation.js:439`.

### 2.7 Propagacion orbital detallada (Kepler + cambios de marco)

Bloques fisicos:
- Julian Date: `dateToJulian`: `app/static/simulation.js:509`.
- GMST: `gmstFromDate`: `app/static/simulation.js:516` a `app/static/simulation.js:525`.
- Kepler (Newton-Raphson):
  - `solveKepler(M,e)`: `app/static/simulation.js:528`.
  - bucle iterativo `for i < maxIter`: `app/static/simulation.js:533`.
  - paso Newton `delta = f/f'`: `app/static/simulation.js:536`.
- perifocal -> ECI: matriz rotacion en `app/static/simulation.js:551` a `app/static/simulation.js:555`.
- estado orbital:
  - `n = sqrt(mu/a^3)`: `app/static/simulation.js:566`.
  - anomalia verdadera: `atan2(...)`: `app/static/simulation.js:573`.
  - radio orbital: `r = a*(1 - e*cosE)`: `app/static/simulation.js:574`.
  - velocidad perifocal: `app/static/simulation.js:582`, `app/static/simulation.js:583`.
- ECI -> ECEF:
  - rotacion por GMST: `app/static/simulation.js:597` a `app/static/simulation.js:607`.
  - correccion de velocidad por rotacion terrestre `omega x r`: `app/static/simulation.js:610` a `app/static/simulation.js:619`.
- ECEF -> geodesico simplificado:
  - lon `atan2(y,x)`, lat `atan2(z,hyp)`, alt `|r|-R`: `app/static/simulation.js:627` a `app/static/simulation.js:631`.

Funcion principal:
- `propagateOrbit(settings, options)`: `app/static/simulation.js:713`.
- flujo:
  1. lee orbital/resonance/timeline del estado: `app/static/simulation.js:714` a `app/static/simulation.js:719`.
  2. normaliza unidades a radianes: `app/static/simulation.js:722` a `app/static/simulation.js:725`.
  3. si hay resonancia:
     - objetivo de periodo: `(rotations/orbits)*SIDEREAL_DAY`: `app/static/simulation.js:749`.
     - semi-major por resonancia (Kepler): `app/static/simulation.js:751`, implementacion `app/static/simulation.js:707` a `app/static/simulation.js:710`.
     - clamps fisicos (min/max): `app/static/simulation.js:755` a `app/static/simulation.js:769`.
     - chequeo perigeo: `app/static/simulation.js:775` a `app/static/simulation.js:781`.
  4. calcula periodo y muestreo:
     - `meanMotion`: `app/static/simulation.js:797`.
     - `orbitPeriod = 2pi/n`: `app/static/simulation.js:798`.
     - `totalSamples`, `dt`: `app/static/simulation.js:805`, `app/static/simulation.js:806`.
     - timeline: `app/static/simulation.js:808` a `app/static/simulation.js:810`.
  5. bucle por muestra temporal (`timeline.map`):
     - `M(t) = M0 + n*t`: `app/static/simulation.js:836`.
     - calcula `rEci/vEci`, rota a ECEF, convierte a lat/lon/alt: `app/static/simulation.js:837` a `app/static/simulation.js:840`.
  6. cierre de ground-track:
     - gap cartesiano 3D: `app/static/simulation.js:862`.
     - gap superficial (haversine): `app/static/simulation.js:864`.
     - drift lat/lon por ciclo: `app/static/simulation.js:866` a `app/static/simulation.js:868`.
     - validacion closed/no-closed: `app/static/simulation.js:873` a `app/static/simulation.js:877`.

### 2.8 Metricas enlace estacion-satelite
- funcion: `computeStationMetrics(...)`: `app/static/simulation.js:906`.
- bucle principal por muestra: `dataPoints.forEach`: `app/static/simulation.js:942`.
- calculos geometricos:
  - LOS y elevacion/azimut/distancia: `losElevation` en `app/static/simulation.js:659`.
    - elevacion: `atan2(up, sqrt(east^2+north^2))`: `app/static/simulation.js:673`.
    - azimut: `atan2(east,north)`: `app/static/simulation.js:674`.
  - perdida geometrica:
    - divergencia `1.22*lambda/apertura`: `app/static/simulation.js:699`.
    - spot radius y acoplamiento: `app/static/simulation.js:700` a `app/static/simulation.js:702`.
    - `lossDb = -10log10(coupling)`: `app/static/simulation.js:703`.
  - Doppler:
    - velocidad radial por producto escalar: `app/static/simulation.js:688`.
    - factor relativista simplificado `1/(1-vr/c)`: `app/static/simulation.js:690`.
- ajuste atmosferico con angulo zenital (si elevacion > 0):
  - `zenith = (90 - elev)*deg2rad`: `app/static/simulation.js:965`.
  - `air_mass = 1/cos(zenith)`: `app/static/simulation.js:967`.
  - escalados:
    - `r0 = r0_zenith * cos^(3/5)`: `app/static/simulation.js:969`.
    - `fG = fG_zenith * cos^(-9/5)`: `app/static/simulation.js:970`.
    - `theta0 = theta0_zenith * cos^(8/5)`: `app/static/simulation.js:971`.
    - `loss_aod`, `loss_abs` multiplican por `air_mass`: `app/static/simulation.js:972`, `app/static/simulation.js:973`.

### 2.9 Busqueda de resonancias enteras
- funcion: `searchResonances(...)`: `app/static/simulation.js:1051`.
- bucles enteros:
  - `j` (rotaciones): `app/static/simulation.js:1076`.
  - `k` (orbitas): `app/static/simulation.js:1078`.
- formula:
  - periodo candidato `period = (j*siderealDay)/k`: `app/static/simulation.js:1077`, `app/static/simulation.js:1079`.
  - `semiMajor = aFromPeriod(period)`: `app/static/simulation.js:1080`.
  - filtro por tolerancia `|deltaKm| <= tolerance`: `app/static/simulation.js:1082`.

---

## 3) Que calcula `main.js` exactamente (`app/static/main.js`)

`main.js` hace calculo numerico de coordinacion y post-procesado (NO la mecanica orbital base, que esta en `simulation.js`).

### 3.1 Acoplamiento con motor numerico
- importa funciones de calculo: `app/static/main.js:2` a `app/static/main.js:8`.
  - `orbit.propagateOrbit`, `orbit.computeStationMetrics`.
  - `searchResonances`, `periodFromA`, `aFromPeriod`.
  - `calculateQKDPerformance`.

### 3.2 Calculos numericos propios en `main.js`
- normalizacion de longitudes en rango `[-180,180]`:
  - bucles `while`: `app/static/main.js:542` a `app/static/main.js:547`.
- discretizacion de samples weather:
  - redondeo al multiplo de 8 y clamp `[16,900]`: `app/static/main.js:576` a `app/static/main.js:579`.
- propagacion TLE en frontend (satellite.js) para constelaciones:
  - fechas de muestra `epoch + seconds*1000`: `app/static/main.js:1076`.
  - bucles dataset/satelite/tiempo: `app/static/main.js:1080`, `app/static/main.js:1083`, `app/static/main.js:1090`.
  - conversion ECI->geodetico via satellite.js: `app/static/main.js:1091`, `app/static/main.js:1096`.
- buscador de resonancias:
  - `toleranceKm = targetA * 2%`: `app/static/main.js:1393`.
  - fallback parcial `*5`: `app/static/main.js:1412`.
- diagnostico/sugerencias de resonancia:
  - periodo fisico `periodFromA(targetA)`: `app/static/main.js:1430`.
  - razon fisica `period/sidereal`: `app/static/main.js:1432`.
  - altitud requerida para una razon `aFromPeriod(...) - EARTH_RADIUS_KM`: `app/static/main.js:1450`, `app/static/main.js:1456`, `app/static/main.js:1473`.
  - busqueda del par `(j,k)` mas cercano por `min |deltaA|` con doble bucle: `app/static/main.js:1487` a `app/static/main.js:1500`.
- grafica de resonancias:
  - mapeo lineal `alt->x`, `k/j->y`: `app/static/main.js:1543`, `app/static/main.js:1544`.
  - curva de Kepler por pixel:
    - bucle `for px`: `app/static/main.js:1590`.
    - `a = alt + R`, `period = periodFromA(a)`, `kj = sidereal/period`: `app/static/main.js:1592` a `app/static/main.js:1594`.
- optimizador interactivo:
  - construccion de constelacion inicial (Walker o 1 sat): `app/static/main.js:2141` a `app/static/main.js:2158`.
  - fabrica de posiciones (propagacion por satelite) con bucle `for s`: `app/static/main.js:2163`.
  - modo worker: particion por chunks
    - `n=min(workerCount,len)`, `chunkSize=ceil(len/n)`: `app/static/main.js:2245`, `app/static/main.js:2246`.
  - bucle de optimizacion `it=0..iterations`:
    - mutacion decreciente `max(0.1,5*(1-it/iterations))`: `app/static/main.js:2334`.
    - score por revisit y seleccion de mejor candidato: `app/static/main.js:2336` a `app/static/main.js:2343`.
- recalculo orbital:
  - llamada al core orbital: `app/static/main.js:3108`.
  - metricas iniciales: `app/static/main.js:3121`.
  - segunda pasada con atmosfera remota: `app/static/main.js:3150`.
- recalculo solo metricas:
  - tiempo medio de timeline:
    - `midIndex=floor(len/2)`: `app/static/main.js:3168`.
    - `midTimestamp = epoch + midTimeSeconds*1000`: `app/static/main.js:3170`, `app/static/main.js:3171`.
  - llamada API atmosfera: `app/static/main.js:3173`.
  - recomputo metricas con perfil: `app/static/main.js:3198`.
- metricas para UI:
  - zenith instantaneo: `90 - elevation`: `app/static/main.js:3395`.
- valor de footprint:
  - `sqrt((R+h)^2 - R^2)`: `app/static/main.js:3294` a `app/static/main.js:3297`.
- preparacion de arrays de grafica:
  - labels redondeados a 0.1 s: `app/static/main.js:3591` a `app/static/main.js:3593`.
  - serie transformada por muestra (si `transform`): `app/static/main.js:3599` a `app/static/main.js:3607`.
- playback temporal:
  - `dt=(timestamp-lastTimestamp)/1000`: `app/static/main.js:3784`.
  - tiempo simulado `+= dt*timeWarp`: `app/static/main.js:3792`.
  - wrap modular con `totalTime`: `app/static/main.js:3795`.
  - busqueda de indice por bucles `while`: `app/static/main.js:3804` a `app/static/main.js:3808`.

### 3.3 Decision de recalculo por firma (evitar calculo innecesario)
- firma orbita: `app/static/main.js:2857`.
- firma metricas: `app/static/main.js:2865`.
- trigger:
  - si cambia orbita -> `recomputeOrbit(true)`: `app/static/main.js:3898` a `app/static/main.js:3900`.
  - si cambian metricas -> `recomputeMetricsOnly(true)`: `app/static/main.js:3904` a `app/static/main.js:3906`.

---

## 4) Worker de propagacion paralelo: `app/static/propagateWorker.js`

Este archivo replica formulas orbitales para acelerar el optimizador en hilos Web Worker.

- J2 secular rates:
  - `n`, `p`, `factor`, `dotOmega`, `dotArgPerigee`: `app/static/propagateWorker.js:83` a `app/static/propagateWorker.js:99`.
  - deriva en media anomalia `dotMeanAnomaly`: `app/static/propagateWorker.js:109`.
- Kepler:
  - `solveKepler` con bucle Newton: `app/static/propagateWorker.js:22` a `app/static/propagateWorker.js:31`.
- estado orbital:
  - `r = a*(1-e*cosE)`: `app/static/propagateWorker.js:57`.
  - `trueAnomaly` y transformaciones: `app/static/propagateWorker.js:56`, `app/static/propagateWorker.js:35`.
- bucles de trabajo:
  - satelites: `for s`: `app/static/propagateWorker.js:130`.
  - timeline: `for ti`: `app/static/propagateWorker.js:153`.
  - evolucion temporal:
    - `raan_t`, `arg_t`, `M(t)`: `app/static/propagateWorker.js:155` a `app/static/propagateWorker.js:157`.
    - `gmst(t)=gmst0+omega_earth*t`: `app/static/propagateWorker.js:159`.

---

## 5) Utilidades numericas base: `app/static/utils.js`

- conversiones angulares:
  - `DEG2RAD`, `RAD2DEG`: `app/static/utils.js:1`, `app/static/utils.js:2`.
- clamp lineal:
  - `clamp(value,min,max)`: `app/static/utils.js:105`.
- interpolacion lineal:
  - `lerp(a,b,t)=a+(b-a)t`: `app/static/utils.js:109`.
- distancia geodesica (haversine):
  - `app/static/utils.js:160` a `app/static/utils.js:165`.
- suavizado serie (moving average):
  - doble bucle en `smoothArray`: `app/static/utils.js:174`, `app/static/utils.js:177`.
- aproximacion racional:
  - `findClosestRational`: bucle `k=1..maxDenominator` `app/static/utils.js:196`,
  - error `|real - j/k|`: `app/static/utils.js:201`.

---

## 6) Calculo numerico de visualizacion: `app/static/ui.js`

### 6.1 Proyecciones y wrap geodesico 2D
- proyeccion equirectangular:
  - `x=((lon+180)/360)*width`: `app/static/ui.js:594` a `app/static/ui.js:596`.
  - `y=((90-lat)/180)*height`: `app/static/ui.js:598` a `app/static/ui.js:600`.
- correccion dateline en poligonos:
  - ajuste de `delta lon` en `[-180,180]`: `app/static/ui.js:610` a `app/static/ui.js:613`.
  - wrap de `x` en canvas: `app/static/ui.js:615` a `app/static/ui.js:617`.

### 6.2 Segmentacion de ground tracks por salto de dateline
- en constelaciones 2D:
  - `delta = |lon-prevLon|`, corte si `delta>180`: `app/static/ui.js:962`, `app/static/ui.js:963`.
- en orbita individual 2D:
  - mismo criterio: `app/static/ui.js:1160`, `app/static/ui.js:1161`.

### 6.3 Weather overlay
- interpolacion de color por tramos:
  - `localT=(value-left.stop)/(right.stop-left.stop)`: `app/static/ui.js:998`.
  - `r,g,b` lineales: `app/static/ui.js:999` a `app/static/ui.js:1001`.
- celda geoespacial desde centros:
  - `computeEdges` promedia vecinos y extrapola bordes: `app/static/ui.js:1012` a `app/static/ui.js:1020`.
- render numerico por celdas:
  - doble bucle `row/col`: `app/static/ui.js:1395`, `app/static/ui.js:1398`.
  - normalizacion escalar: `(cell-min)/(max-min)`: `app/static/ui.js:1413`.

### 6.4 Conversiones 3D y framing
- vector ECI/ECEF a mundo 3D:
  - `toVector3([x,y,z]) -> (x, z, -y)*UNIT_SCALE`: `app/static/ui.js:2159` a `app/static/ui.js:2162`.
- vector en superficie desde lat/lon:
  - escala radial `(R+h)/R`: `app/static/ui.js:2190`.
- radio de encuadre:
  - maximo `|vec|` en orbit points: `app/static/ui.js:2197` a `app/static/ui.js:2206`.
- posicion camara:
  - `distance=max(safeRadius*2.4,2.6)`,
  - `altitude=distance*0.62`,
  - `lateral=distance*0.45`: `app/static/ui.js:2226` a `app/static/ui.js:2228`.

### 6.5 Suavizado de trayectorias 3D
- orbita principal:
  - cierre por `distanceTo(first,last)<1e-3`: `app/static/ui.js:2353`.
  - Catmull-Rom y densidad `segments=min(2048,max(120,n*3))`: `app/static/ui.js:2354` a `app/static/ui.js:2356`.
- constelaciones 3D:
  - mismo esquema en `app/static/ui.js:1731` a `app/static/ui.js:1734`.

### 6.6 Link 3D y LOS
- color de linea segun visibilidad:
  - `hasLineOfSight = elevationDeg > 0`: `app/static/ui.js:2420`.

---

## 7) Backend atmosfera/weather y orbital API

> **Nota:** Tras el refactoring modular, las funciones documentadas a continuación
> se encuentran ahora distribuidas en los módulos `app/physics/` (cálculos físicos),
> `app/services/` (lógica de negocio) y `app/routers/` (endpoints HTTP).
> `app/backend.py` (~69 líneas) actúa únicamente como app factory que monta los
> routers y servicios.  Las referencias a líneas de `app/backend.py:XXX` a
> continuación corresponden al monolito original y se conservan como guía
> conceptual; el código real reside ahora en los archivos modulares.

### 7.1 Resumen atmosferico desde capas (`_calculate_summary_from_layers`)
- ubicación actual: `app/services/atmosphere_svc.py`
- funcion: `app/backend.py:391`.
- entrada:
  - capas (`alt_km`, `cn2`, `wind_mps`) desde proveedores HV/Bufton/Greenwood.
- preproceso:
  - bucle capas y filtrado `cn2 != None`: `app/backend.py:401` a `app/backend.py:407`.
  - arrays ordenados por altura: `app/backend.py:420` a `app/backend.py:423`.
- integrales (trapecio):
  - `integral_r0 = trapz(cn2 dh)`: `app/backend.py:426`.
  - `integral_theta = trapz(cn2 * h^(5/3) dh)`: `app/backend.py:427`.
  - `integral_wind = trapz(cn2 * |v|^(5/3) dh)`: `app/backend.py:428`.
- formulas de salida:
  - `k=2pi/lambda`: `app/backend.py:425`.
  - `r0_zenith = (0.423*k^2*I_r0)^(-3/5)`: `app/backend.py:430`.
  - `theta0 = (2.91*k^2*I_theta)^(-3/5)`: `app/backend.py:431`.
  - `fG = (0.102*k^2*I_wind)^(3/5)`: `app/backend.py:432`.
  - `wind_rms = sqrt(mean(v^2))`: `app/backend.py:435`.
  - `tau0 = 0.314*r0/wind_rms`: `app/backend.py:439`.
  - perdidas empiricas AOD/ABS: `app/backend.py:442`, `app/backend.py:443`.

### 7.2 Modelos atmosfericos
- HV57 (`_hv57_provider`, `app/backend.py:479`):
  - `W = sqrt(u^2+v^2)`: `app/backend.py:490`.
  - `Cn2(h)` suma de 3 terminos exponenciales/potencia: `app/backend.py:495` a `app/backend.py:498`.
  - viento verticalizado por altura: `app/backend.py:500`, `app/backend.py:501`.
- Bufton (`_bufton_provider`, `app/backend.py:526`):
  - velocidad por nivel: `sqrt(u^2+v^2)`: `app/backend.py:545`.
  - correccion termica (`lapse_correction`): `app/backend.py:552`.
  - `shear_factor`: `app/backend.py:555`.
  - `cn2_bufton` por tramos de altura: `app/backend.py:557` a `app/backend.py:565`.
  - perfil viento por tramos: `app/backend.py:567` a `app/backend.py:574`.
  - perfil temperatura lineal con lapse rate: `app/backend.py:576` a `app/backend.py:581`.
- Greenwood (`_greenwood_provider`, `app/backend.py:612`):
  - velocidad por nivel: `app/backend.py:630`.
  - `cn2_greenwood` por tramos: `app/backend.py:638` a `app/backend.py:646`.
  - viento por tramos: `app/backend.py:648` a `app/backend.py:653`.

### 7.3 Campo meteorologico numerico
- rejilla:
  - `clamped_samples` en `[16,900]`: `app/backend.py:824`.
  - `cols = round(sqrt(samples*2))`, `rows = ceil(samples/cols)`: `app/backend.py:825`, `app/backend.py:826`.
  - lat/lon por interpolacion lineal `_lerp`: `app/backend.py:829`, `app/backend.py:833`.
- muestreo:
  - doble bucle `for lat` y `for lon`: `app/backend.py:862`, `app/backend.py:864`.
  - acumulacion `min`, `max`, suma, contador validos: `app/backend.py:878` a `app/backend.py:883`.
  - media `mean = accumulator/valid_count`: `app/backend.py:889`.
  - metadata `actual_samples = rows*cols`: `app/backend.py:914`.

### 7.4 Endpoints orbitales y constelaciones
- `/api/constellation/analyze`: `app/backend.py:1590` (usa estadistica en `constellation_manager`).
- `/api/constellation/propagate`: `app/backend.py:1637`.
  - `samples_per_satellite = len(first_sat_states)`: `app/backend.py:1684`.
- `/api/constellation/{id}/coverage`: `app/backend.py:1688` (delegado a manager).
- `/api/orbital/sun-synchronous`: `app/backend.py:1807`.
  - devuelve drift RAAN en deg/day: `dot_raan*86400*RAD2DEG`: `app/backend.py:1831`.
- `/api/orbital/walker-constellation`: `app/backend.py:1837` (delegado a `orbital_mechanics`).
- `/api/orbital/repeat-ground-track`: `app/backend.py:1885` (delegado a `optimize_semi_major_axis_for_repeat_ground_track`).

---

## 8) Motor orbital Python: `app/orbital_mechanics.py`

### 8.1 Propiedades de `OrbitalElements`
- altitud: `a - R`: `app/orbital_mechanics.py:44`.
- periodo: `2pi*sqrt(a^3/mu)`: `app/orbital_mechanics.py:49`.
- mean motion: `sqrt(mu/a^3)`: `app/orbital_mechanics.py:54`.

### 8.2 J2/J3/J4
- J2 base (`compute_j2_secular_rates`):
  - `n`, `p`, `factor`: `app/orbital_mechanics.py:85`, `app/orbital_mechanics.py:86`, `app/orbital_mechanics.py:95`.
  - `dot_raan`, `dot_arg_perigee`, `dot_mean_anomaly`: `app/orbital_mechanics.py:98`, `app/orbital_mechanics.py:101`, `app/orbital_mechanics.py:105`.
- mejorado (`compute_enhanced_secular_rates`):
  - termino J3 en argumento de perigeo: `app/orbital_mechanics.py:143`, `app/orbital_mechanics.py:144`.
  - terminos J4 en RAAN/perigeo: `app/orbital_mechanics.py:154` a `app/orbital_mechanics.py:156`.

### 8.3 Sun-synchronous
- `calculate_sun_synchronous_inclination`: `app/orbital_mechanics.py:167`.
- `required_drift = SOLAR_MEAN_MOTION * DEG2RAD / 86400`: `app/orbital_mechanics.py:187`.
- despeje `cos(i)=required_drift/factor`: `app/orbital_mechanics.py:196`, `app/orbital_mechanics.py:201`.
- `i=acos(cos_i)`, ajuste retrogrado si `<90`: `app/orbital_mechanics.py:211` a `app/orbital_mechanics.py:217`.

### 8.4 Walker
- `calculate_walker_constellation_elements`: `app/orbital_mechanics.py:222`.
- bucles `for p` y `for s`: `app/orbital_mechanics.py:259`, `app/orbital_mechanics.py:264`.
- `raan = 360*p/P + offset`: `app/orbital_mechanics.py:261`.
- `M = 360*s/S + 360*F*p/T`: `app/orbital_mechanics.py:268`.

### 8.5 Repeat-ground-track (iterativo)
- `optimize_semi_major_axis_for_repeat_ground_track`: `app/orbital_mechanics.py:285`.
- objetivo:
  - `target_n = 2pi*rev_per_day / sidereal_day`: `app/orbital_mechanics.py:305`.
  - inicial `a = (mu/target_n^2)^(1/3)`: `app/orbital_mechanics.py:308`.
- bucle iterativo:
  - `for _ in range(max_iterations)`: `app/orbital_mechanics.py:316`.
  - factor J2 aproximado: `app/orbital_mechanics.py:319`.
  - `n_perturbed` y `a_new`: `app/orbital_mechanics.py:323`, `app/orbital_mechanics.py:326`.
  - convergencia por `|a_new-a| < tolerance`: `app/orbital_mechanics.py:328`.

### 8.6 Validacion fisica
- perigeo: `a*(1-e)-R`: `app/orbital_mechanics.py:359`.
- limites e/inclinacion/semimajor: `app/orbital_mechanics.py:348` a `app/orbital_mechanics.py:365`.

---

## 9) Constellation manager numerico: `app/constellation_manager.py`

### 9.1 Propagacion TLE y conversion geodesica
- `propagate_tle(...)`: `app/constellation_manager.py:93`.
- conversion:
  - radio `r = sqrt(x^2+y^2+z^2)`: `app/constellation_manager.py:124`.
  - lat `asin(z/r)`, lon `atan2(y,x)`, alt `r-6378.137`: `app/constellation_manager.py:125` a `app/constellation_manager.py:127`.

### 9.2 Propagacion de constelacion en el tiempo
- `propagate_constellation`: `app/constellation_manager.py:184`.
- numero de pasos: `int(duration/time_step)+1`: `app/constellation_manager.py:206`.
- bucles:
  - satelites: `app/constellation_manager.py:210`.
  - tiempo: `app/constellation_manager.py:219`.
  - fecha por paso: `start + step*time_step`: `app/constellation_manager.py:220`.

### 9.3 Analitica agregada de constelacion
- `analyze_constellation`: `app/constellation_manager.py:230`.
- estadisticas:
  - mean/min/max altitud: `app/constellation_manager.py:276`, `app/constellation_manager.py:277`.
  - "inclinacion" aproximada desde latitudes: `app/constellation_manager.py:278` a `app/constellation_manager.py:280`.
  - estimacion de planos por binning `round(lat/10)*10`: `app/constellation_manager.py:269`.

### 9.4 Cobertura en punto de tierra
- `compute_coverage_at_location`: `app/constellation_manager.py:329`.
- bucles:
  - pasos temporales: `app/constellation_manager.py:366`.
  - satelites: `app/constellation_manager.py:368`.
- criterio de visibilidad (aprox):
  - distancia gran circulo `< VISIBILITY_DISTANCE_KM` y altitud `> MIN_OPERATIONAL_ALTITUDE_KM`: `app/constellation_manager.py:382`.
- porcentaje cobertura:
  - `coverage_percent = (covered_steps/num_steps)*100`: `app/constellation_manager.py:390`.

### 9.5 Distancia gran circulo
- `_great_circle_distance`: `app/constellation_manager.py:401`.
- haversine:
  - terminos `a` y `c`: `app/constellation_manager.py:407` a `app/constellation_manager.py:409`.
  - distancia `6371*c`: `app/constellation_manager.py:411`.

---

## 10) Donde se ejecuta cada bloque de calculo (resumen rapido)

- Orbitas y dinamica fisica principal:
  - `app/static/simulation.js` (`propagateOrbit`, `computeStationMetrics`).
- Orquestacion y calculo auxiliar de UI/optimizacion/graficas:
  - `app/static/main.js`.
- Estado reactivo y gestión de mutaciones:
  - `app/static/state.js`.
- Gestión de estaciones OGS (API y lista builtin):
  - `app/static/stations.js`.
- Formateadores numéricos de UI:
  - `app/static/formatters.js`.
- Tooltips informativos:
  - `app/static/tooltips.js`.
- Configuración de campos meteorológicos:
  - `app/static/weather.js`.
- Paralelizacion de propagacion (worker):
  - `app/static/propagateWorker.js`.
- Cálculos físicos puros (Python):
  - `app/physics/` (constants, kepler, propagation, geometry, atmosphere_models, qkd, walker).
- Lógica de negocio y APIs externas:
  - `app/services/` (database, ogs_store, atmosphere_svc, weather_svc, tle_service).
- Endpoints HTTP:
  - `app/routers/` (solver, ogs, atmosphere, orbital, tles, constellation, users, pages).
- Formulacion orbital avanzada reutilizable en backend:
  - `app/orbital_mechanics.py`.
- Calculo TLE/coverage de constelaciones:
  - `app/constellation_manager.py`.
- Transformaciones visuales y geoespaciales:
  - `app/static/ui.js`.
- utilidades matematicas base:
  - `app/static/utils.js`.
