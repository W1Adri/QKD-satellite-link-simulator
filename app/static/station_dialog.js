// ---------------------------------------------------------------------------
// app/static/station_dialog.js
// ---------------------------------------------------------------------------
// Purpose : Ground-station add/edit dialog + "pick on map" picker + dialog
//           drag handling. Extracted from main.js as a DI factory.
//
// Usage   : const stationDialog = createStationDialog({ elements,
//             getMapInstance, refreshStationSelect, recomputeMetricsOnly });
//           getMapInstance is a getter (the Leaflet instance is created after
//           this factory runs, and the pick-mode guard needs the live value).
//           Returns the dialog/picker handlers consumed by bindEvents.
// ---------------------------------------------------------------------------
import { clamp } from './utils.js';
import { normalizeLongitude } from './formatters.js';
import { upsertStation } from './state.js';
import { persistStation } from './stations.js';
import { map2d } from './ui.js';

const { startStationPicker, stopStationPicker } = map2d;

export function createStationDialog({
  elements,
  getMapInstance,
  refreshStationSelect,
  recomputeMetricsOnly,
}) {
  let stationPickCleanup = null;
  const stationDialogDragState = {
    active: false,
    startX: 0,
    startY: 0,
    dialogX: 0,
    dialogY: 0,
  };

function updateStationPickHint(lat = null, lon = null, awaiting = false) {
  const hintEl = elements.stationPickHint;
  if (!hintEl) return;

  if (awaiting) {
    hintEl.hidden = false;
    hintEl.classList.add('is-active');
    hintEl.textContent = 'Click the map to set the location.';
    return;
  }

  if (Number.isFinite(lat) && Number.isFinite(lon)) {
    hintEl.hidden = false;
    hintEl.classList.add('is-active');
    hintEl.textContent = `Selected location: ${lat.toFixed(4)}Â°, ${lon.toFixed(4)}Â°`;
    return;
  }

  hintEl.hidden = true;
  hintEl.classList.remove('is-active');
  hintEl.textContent = 'Click the map to set the location.';
}

function setStationPickMode(active) {
  if (!elements.stationPickOnMap) return;
  if (active && !getMapInstance()) {
    console.warn('Map is not ready yet to pick stations.');
    return;
  }
  const currentlyActive = Boolean(stationPickCleanup);
  if (active && !currentlyActive) {
    const lat = Number(elements.stationLat?.value);
    const lon = Number(elements.stationLon?.value);
    const normalizedInitialLon = Number.isFinite(lon) ? normalizeLongitude(lon) : undefined;
    const initial = Number.isFinite(lat) && normalizedInitialLon !== undefined
      ? { lat, lon: normalizedInitialLon }
      : undefined;

    stationPickCleanup = startStationPicker(({ lat: pickedLat, lon: pickedLon }) => {
      const normalizedLon = normalizeLongitude(pickedLon);
      if (elements.stationLat) {
        elements.stationLat.value = pickedLat.toFixed(4);
      }
      if (elements.stationLon) {
        elements.stationLon.value = normalizedLon.toFixed(4);
      }
      updateStationPickHint(pickedLat, normalizedLon, false);
    }, initial);

    elements.stationPickOnMap.dataset.active = 'true';
    elements.stationPickOnMap.textContent = 'Cancel selection';
    if (initial) {
      updateStationPickHint(initial.lat, initial.lon, false);
    } else {
      updateStationPickHint(null, null, true);
    }
    return;
  }

  if (!active && currentlyActive) {
    stationPickCleanup?.();
    stationPickCleanup = null;
    stopStationPicker();
    elements.stationPickOnMap.dataset.active = 'false';
  elements.stationPickOnMap.textContent = 'Pick on map';
    updateStationPickHint();
  }
}

function syncStationPickHintFromInputs() {
  if (stationPickCleanup) return;
  const lat = Number(elements.stationLat?.value);
  const lon = Number(elements.stationLon?.value);
  if (Number.isFinite(lat) && Number.isFinite(lon)) {
    updateStationPickHint(lat, normalizeLongitude(lon), false);
  } else {
    updateStationPickHint();
  }
}

async function saveStationFromDialog() {
  const name = elements.stationName?.value.trim() ?? '';
  const lat = Number(elements.stationLat?.value);
  const lon = Number(elements.stationLon?.value);
  const aperture = Number(elements.stationAperture?.value ?? 1.0);
  const altitude = Number(elements.stationAltitude?.value ?? 0);

  if (!name) {
    elements.stationName?.focus();
    return;
  }
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) {
    updateStationPickHint(null, null, true);
    elements.stationLat?.focus();
    return;
  }

  const normalizedLon = normalizeLongitude(lon);
  if (elements.stationLon) {
    elements.stationLon.value = normalizedLon.toFixed(4);
  }

  const id = `${name.replace(/\s+/g, '-').toLowerCase()}-${Date.now()}`;
  const station = { id, name, lat, lon: normalizedLon, altitude, aperture, builtin: false };
  upsertStation(station);
  persistStation(station);
  setStationPickMode(false);
  updateStationPickHint();
  elements.stationDialog?.close('saved');
  refreshStationSelect();
  await recomputeMetricsOnly(true);
}

function resetStationDialogPosition() {
  if (!elements.stationDialog) return;
  elements.stationDialog.style.left = '50%';
  elements.stationDialog.style.top = '50%';
  elements.stationDialog.style.transform = 'translate(-50%, -50%)';
}

function setStationDialogPosition(x, y) {
  if (!elements.stationDialog) return;
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;
  const rect = elements.stationDialog.getBoundingClientRect();
  const clampedX = clamp(x, 8, viewportWidth - rect.width - 8);
  const clampedY = clamp(y, 8, viewportHeight - rect.height - 8);
  elements.stationDialog.style.left = `${clampedX}px`;
  elements.stationDialog.style.top = `${clampedY}px`;
  elements.stationDialog.style.transform = 'translate(0, 0)';
}

function beginStationDialogDrag(event) {
  if (!elements.stationDialog) return;
  event.preventDefault();
  stationDialogDragState.active = true;
  stationDialogDragState.startX = event.clientX;
  stationDialogDragState.startY = event.clientY;
  const rect = elements.stationDialog.getBoundingClientRect();
  stationDialogDragState.dialogX = rect.left;
  stationDialogDragState.dialogY = rect.top;
  elements.stationDialog.classList.add('is-dragging');
  window.addEventListener('pointermove', handleStationDialogDragMove);
  window.addEventListener('pointerup', endStationDialogDrag, { once: true });
  window.addEventListener('pointercancel', endStationDialogDrag, { once: true });
}

function handleStationDialogDragMove(event) {
  if (!stationDialogDragState.active) return;
  const deltaX = event.clientX - stationDialogDragState.startX;
  const deltaY = event.clientY - stationDialogDragState.startY;
  setStationDialogPosition(stationDialogDragState.dialogX + deltaX, stationDialogDragState.dialogY + deltaY);
}

function endStationDialogDrag() {
  if (!stationDialogDragState.active) {
    window.removeEventListener('pointermove', handleStationDialogDragMove);
    window.removeEventListener('pointerup', endStationDialogDrag);
    window.removeEventListener('pointercancel', endStationDialogDrag);
    elements.stationDialog?.classList.remove('is-dragging');
    return;
  }
  stationDialogDragState.active = false;
  elements.stationDialog?.classList.remove('is-dragging');
  window.removeEventListener('pointermove', handleStationDialogDragMove);
  window.removeEventListener('pointerup', endStationDialogDrag);
  window.removeEventListener('pointercancel', endStationDialogDrag);
}

function openStationDialog() {
  if (!elements.stationDialog) return;
  resetStationDialogPosition();
  endStationDialogDrag();
  if (!elements.stationDialog.open) {
    try {
      elements.stationDialog.show();
    } catch (error) {
      console.warn('Could not open the station dialog', error);
    }
  }
  elements.stationName?.focus();
}

  return {
    updateStationPickHint,
    setStationPickMode,
    syncStationPickHintFromInputs,
    saveStationFromDialog,
    resetStationDialogPosition,
    beginStationDialogDrag,
    endStationDialogDrag,
    openStationDialog,
  };
}
