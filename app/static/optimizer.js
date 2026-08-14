// ---------------------------------------------------------------------------
// app/static/optimizer.js
// ---------------------------------------------------------------------------
// Purpose : Repeating-ground-track ("resonance") panel. Resonance-first model:
//           the user enters k revolutions in j (sidereal) days and the
//           semi-major axis is solved exactly — J2-aware when J2 is enabled —
//           then the orbit is recomputed to span one full repeat cycle.
//
// Usage   : const resonancePanel = createResonancePanel({ elements,
//             syncPairValue, formatKm, recomputeOrbit });
//           Returns { refresh, apply, setEnabled, updateSummary }.
// ---------------------------------------------------------------------------
import { formatDuration } from './utils.js';
import { state, mutate } from './state.js';
import { orbit, resonanceSolver } from './simulation.js';

const DEG2RAD = Math.PI / 180;
const { constants: orbitConstants } = orbit;
const { solveRepeatGroundTrackA, periodFromA } = resonanceSolver;
const { EARTH_RADIUS_KM, MIN_SEMI_MAJOR, MAX_SEMI_MAJOR } = orbitConstants;

export function createResonancePanel({ elements, syncPairValue, formatKm, recomputeOrbit }) {
  function readKJ() {
    const k = Math.max(1, Math.round(Number(elements.resOrbits?.value) || 1));
    const j = Math.max(1, Math.round(Number(elements.resDays?.value) || 1));
    return { k, j };
  }

  // J2-aware resonant semi-major axis for the current k:j and orbital elements.
  // Returns null when the result falls outside the supported altitude range.
  function solveA() {
    const { k, j } = readKJ();
    const o = state.orbital;
    const a = solveRepeatGroundTrackA(k, j, o.eccentricity ?? 0.001, (o.inclination ?? 53) * DEG2RAD, {
      j2: o.j2Enabled !== false, j3: o.j3Enabled, j4: o.j4Enabled,
    });
    return a >= MIN_SEMI_MAJOR && a <= MAX_SEMI_MAJOR ? a : null;
  }

  // Reflect enabled state on the controls; semi-major axis is a derived display
  // while resonance is on (the solver owns it), editable otherwise.
  function refresh() {
    const enabled = Boolean(state.resonance?.enabled);
    if (elements.resonanceToggle) elements.resonanceToggle.checked = enabled;
    if (elements.resOrbits) elements.resOrbits.disabled = !enabled;
    if (elements.resDays) elements.resDays.disabled = !enabled;
    if (elements.semiMajor) elements.semiMajor.disabled = enabled;
    if (elements.semiMajorSlider) elements.semiMajorSlider.disabled = enabled;
    updateSummary();
  }

  function updateSummary() {
    if (!elements.resonanceSummary) return;
    if (!state.resonance?.enabled) {
      elements.resonanceSummary.textContent = 'Free orbit — semi-major axis set manually.';
      return;
    }
    const { k, j } = readKJ();
    const info = state.computed?.resonance ?? {};
    const a = info.applied ? info.semiMajorKm : solveA();
    if (a == null) {
      elements.resonanceSummary.textContent =
        `${k}:${j} resolves outside the supported altitude range (160 km – GEO). Adjust k or j.`;
      return;
    }
    const altKm = a - EARTH_RADIUS_KM;
    const cycle = formatDuration(periodFromA(a) * k);
    let closure = '';
    if (info.applied && info.closureSurfaceKm != null) {
      closure = info.closed
        ? ' · ground track closes ✓'
        : ` · residual ${formatKm(info.closureSurfaceKm, 2)} km (J2 apsidal drift)`;
    }
    elements.resonanceSummary.textContent =
      `${k} revolutions in ${j} sidereal day(s): a = ${formatKm(a, 1)} km ` +
      `(alt ${formatKm(altKm, 0)} km, cycle ${cycle})${closure}`;
  }

  // Push the current k:j into state, sync the semi-major display, recompute.
  async function apply() {
    const { k, j } = readKJ();
    const a = solveA();
    mutate((draft) => {
      draft.resonance.enabled = true;
      draft.resonance.orbits = k;
      draft.resonance.rotations = j;
      if (a != null) draft.orbital.semiMajor = Number(a.toFixed(3));
    });
    if (a != null) syncPairValue('semiMajor', 'semiMajorSlider', Number(a.toFixed(3)));
    await recomputeOrbit(true);
    refresh();
  }

  async function setEnabled(on) {
    if (on) {
      await apply();
    } else {
      mutate((draft) => { draft.resonance.enabled = false; });
      refresh();
      await recomputeOrbit(true);
    }
  }

  return { refresh, apply, setEnabled, updateSummary };
}
