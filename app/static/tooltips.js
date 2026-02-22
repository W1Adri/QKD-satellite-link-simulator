// ---------------------------------------------------------------------------
// app/static/tooltips.js
// ---------------------------------------------------------------------------
// Purpose : Info tooltip management for the sidebar info buttons.
//           Handles showing, hiding, positioning, and accessibility.
//
// Exports : initInfoButtons, showInfoTooltip, hideInfoTooltip,
//           repositionActiveTooltip, scheduleInfoTooltipHide
// ---------------------------------------------------------------------------

// ─────────────────────────────────────────────────────────────────────────────
// Module State
// ─────────────────────────────────────────────────────────────────────────────
const INFO_TOOLTIP_ID = 'infoTooltip';
let infoTooltipEl = null;
let activeInfoButton = null;
let infoTooltipSticky = false;
let infoTooltipHideTimeout = null;
let infoTooltipListenersBound = false;
const initializedInfoButtons = new WeakSet();

// ─────────────────────────────────────────────────────────────────────────────
// Internal Helpers
// ─────────────────────────────────────────────────────────────────────────────
function ensureInfoTooltip() {
  if (infoTooltipEl) return infoTooltipEl;
  const tooltip = document.createElement('div');
  tooltip.className = 'info-tooltip';
  tooltip.id = INFO_TOOLTIP_ID;
  tooltip.setAttribute('role', 'tooltip');
  tooltip.setAttribute('aria-hidden', 'true');
  tooltip.dataset.visible = 'false';
  document.body.appendChild(tooltip);
  infoTooltipEl = tooltip;
  return tooltip;
}

function positionInfoTooltip(button) {
  if (!infoTooltipEl || !button) return;
  const rect = button.getBoundingClientRect();
  const margin = 12;
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;
  const tooltipWidth = infoTooltipEl.offsetWidth;
  const tooltipHeight = infoTooltipEl.offsetHeight;

  let top = rect.bottom + margin;
  if (top + tooltipHeight + margin > viewportHeight) {
    top = Math.max(rect.top - tooltipHeight - margin, margin);
  }

  let left = rect.left + rect.width / 2 - tooltipWidth / 2;
  left = Math.min(Math.max(left, margin), viewportWidth - tooltipWidth - margin);

  infoTooltipEl.style.top = `${Math.round(top)}px`;
  infoTooltipEl.style.left = `${Math.round(left)}px`;
}

// ─────────────────────────────────────────────────────────────────────────────
// Public API
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Show the info tooltip for a specific button.
 */
export function showInfoTooltip(button, { sticky = false } = {}) {
  const tooltip = ensureInfoTooltip();
  if (!(button instanceof HTMLElement)) return;
  const content = button.dataset.info;
  if (!content) return;
  clearTimeout(infoTooltipHideTimeout);
  infoTooltipSticky = sticky;
  activeInfoButton = button;
  tooltip.textContent = content;
  tooltip.dataset.visible = 'true';
  tooltip.setAttribute('aria-hidden', 'false');
  button.setAttribute('aria-expanded', 'true');
  button.setAttribute('aria-describedby', INFO_TOOLTIP_ID);
  positionInfoTooltip(button);
}

/**
 * Hide the info tooltip.
 */
export function hideInfoTooltip(force = false) {
  if (!infoTooltipEl) return;
  if (!force && infoTooltipSticky) return;
  infoTooltipSticky = false;
  infoTooltipEl.dataset.visible = 'false';
  infoTooltipEl.setAttribute('aria-hidden', 'true');
  if (activeInfoButton) {
    activeInfoButton.setAttribute('aria-expanded', 'false');
    activeInfoButton.removeAttribute('aria-describedby');
  }
  activeInfoButton = null;
}

/**
 * Schedule hiding the tooltip with a delay.
 */
export function scheduleInfoTooltipHide(force = false) {
  clearTimeout(infoTooltipHideTimeout);
  infoTooltipHideTimeout = setTimeout(() => hideInfoTooltip(force), force ? 0 : 120);
}

/**
 * Reposition the active tooltip (e.g., on window resize).
 */
export function repositionActiveTooltip() {
  if (!infoTooltipEl) return;
  if (infoTooltipEl.dataset.visible !== 'true' || !activeInfoButton) return;
  positionInfoTooltip(activeInfoButton);
}

/**
 * Initialize all info buttons in the document.
 */
export function initInfoButtons() {
  ensureInfoTooltip();
  const buttons = document.querySelectorAll('.info-button[data-info]');
  buttons.forEach((button) => {
    if (!(button instanceof HTMLElement) || initializedInfoButtons.has(button)) return;
    initializedInfoButtons.add(button);
    button.setAttribute('aria-expanded', 'false');
    button.addEventListener('pointerenter', () => showInfoTooltip(button, { sticky: false }));
    button.addEventListener('pointerleave', () => scheduleInfoTooltipHide(false));
    button.addEventListener('focus', () => showInfoTooltip(button, { sticky: false }));
    button.addEventListener('blur', () => scheduleInfoTooltipHide(false));
    button.addEventListener('click', (event) => {
      event.preventDefault();
      if (activeInfoButton === button && infoTooltipSticky) {
        scheduleInfoTooltipHide(true);
      } else {
        showInfoTooltip(button, { sticky: true });
      }
    });
  });

  if (!infoTooltipListenersBound) {
    infoTooltipListenersBound = true;
    window.addEventListener('resize', repositionActiveTooltip);
    document.addEventListener('scroll', repositionActiveTooltip, true);
    document.addEventListener('pointerdown', (event) => {
      if (!infoTooltipSticky) return;
      const target = event.target;
      if (target instanceof HTMLElement && (target.closest('.info-button') || target.closest('.info-tooltip'))) {
        return;
      }
      scheduleInfoTooltipHide(true);
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        scheduleInfoTooltipHide(true);
      }
    });
  }
}
