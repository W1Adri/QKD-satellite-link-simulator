// =====================================================
// settings_ui.js — Settings dialog (Cesium Ion token + imagery mode)
// Mounts a ⚙ button in the topbar that opens a small modal where the user
// pastes their Cesium Ion token and picks the imagery backend. Saving persists
// to ion_token.json (via /api/settings) and reloads so the viewer rebuilds
// with the new imagery. Self-initialising — import once and call initSettingsUI().
// =====================================================
import { config, loadRuntimeSettings, saveRuntimeSettings } from './config.js';
import { showToast } from './toast.js';

let overlayEl = null;

const GEAR_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.6 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z"/></svg>';

function buildModal() {
  const c = config.cesium;
  const overlay = document.createElement('div');
  overlay.className = 'settings-overlay';
  overlay.innerHTML = `
    <div class="settings-modal" role="dialog" aria-modal="true" aria-labelledby="settingsTitle">
      <div class="settings-modal__head">
        <h2 id="settingsTitle">Map &amp; Cesium Ion</h2>
        <button type="button" class="settings-modal__close" aria-label="Close">×</button>
      </div>
      <div class="settings-modal__body">
        <p class="settings-hint">Cesium Ion (free tier) unlocks high-resolution satellite imagery plus 3D terrain &amp; buildings on zoom. Without a token the map falls back to free Blue Marble + ESRI imagery. The token is stored locally in <code>ion_token.json</code> (gitignored) and never leaves this machine.</p>

        <fieldset class="settings-field">
          <legend>Imagery backend</legend>
          <label class="settings-radio"><input type="radio" name="imageryMode" value="ion"> <span><strong>Cesium Ion</strong> — high-res + 3D (needs token)</span></label>
          <label class="settings-radio"><input type="radio" name="imageryMode" value="free"> <span><strong>Free</strong> — Blue Marble + ESRI (no token)</span></label>
        </fieldset>

        <div class="settings-field">
          <label for="ionTokenInput">Cesium Ion access token</label>
          <input id="ionTokenInput" type="password" autocomplete="off" spellcheck="false" placeholder="eyJhbGciOi…" />
          <label class="settings-inline"><input id="ionTokenReveal" type="checkbox"> Show token</label>
          <p class="settings-hint settings-hint--small">Get a free token at <a href="https://cesium.com/ion/tokens" target="_blank" rel="noopener">cesium.com/ion/tokens</a> (scopes: <code>assets:read</code>). It does not expire.</p>
        </div>
      </div>
      <div class="settings-modal__foot">
        <button type="button" class="settings-btn settings-btn--ghost" data-act="cancel">Cancel</button>
        <button type="button" class="settings-btn settings-btn--primary" data-act="save">Save &amp; reload</button>
      </div>
    </div>`;

  // Prefill from current config.
  const tokenInput = overlay.querySelector('#ionTokenInput');
  tokenInput.value = c.ionToken || '';
  const mode = c.imageryMode === 'free' ? 'free' : 'ion';
  const radio = overlay.querySelector(`input[name="imageryMode"][value="${mode}"]`);
  if (radio) radio.checked = true;

  // Reveal toggle.
  overlay.querySelector('#ionTokenReveal').addEventListener('change', (e) => {
    tokenInput.type = e.target.checked ? 'text' : 'password';
  });

  // Dismiss handlers.
  const close = () => closeModal();
  overlay.querySelector('.settings-modal__close').addEventListener('click', close);
  overlay.querySelector('[data-act="cancel"]').addEventListener('click', close);
  overlay.addEventListener('mousedown', (e) => { if (e.target === overlay) close(); });

  // Save handler.
  overlay.querySelector('[data-act="save"]').addEventListener('click', async () => {
    const ionToken = tokenInput.value.trim();
    const imageryMode = overlay.querySelector('input[name="imageryMode"]:checked')?.value || 'ion';
    try {
      await saveRuntimeSettings({ ionToken, imageryMode });
      showToast('Settings saved — reloading…', { type: 'success', duration: 1500 });
      setTimeout(() => window.location.reload(), 700);
    } catch (err) {
      showToast(`Could not save settings: ${err.message}`, { type: 'error', duration: 6000 });
    }
  });

  return overlay;
}

function openModal() {
  if (overlayEl) return;
  overlayEl = buildModal();
  document.body.appendChild(overlayEl);
  requestAnimationFrame(() => overlayEl.classList.add('settings-overlay--in'));
  document.addEventListener('keydown', onKeydown);
}

function closeModal() {
  if (!overlayEl) return;
  document.removeEventListener('keydown', onKeydown);
  const el = overlayEl;
  overlayEl = null;
  el.classList.remove('settings-overlay--in');
  el.addEventListener('transitionend', () => el.remove(), { once: true });
  setTimeout(() => el.remove(), 400);
}

function onKeydown(e) { if (e.key === 'Escape') closeModal(); }

/** Mount the ⚙ button into the topbar and load persisted settings. */
export function initSettingsUI() {
  loadRuntimeSettings(); // warm the cache so the modal prefills correctly
  const mount = () => {
    const actions = document.querySelector('.topbar-actions');
    if (!actions || document.getElementById('btnSettings')) return;
    const btn = document.createElement('button');
    btn.id = 'btnSettings';
    btn.className = 'topbar-icon-btn';
    btn.type = 'button';
    btn.title = 'Map & Cesium Ion settings';
    btn.setAttribute('aria-label', 'Settings');
    btn.innerHTML = GEAR_SVG;
    btn.addEventListener('click', openModal);
    actions.appendChild(btn);
  };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }
}

export default initSettingsUI;
