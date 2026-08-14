// =====================================================
// toast.js — tiny, dependency-free transient notifications
// One global stack pinned bottom-centre. Used for the Cesium Ion fallback
// notice and Settings-dialog feedback. Styles live in app.css (.toast*).
// =====================================================

let stackEl = null;

function ensureStack() {
  if (stackEl && document.body.contains(stackEl)) return stackEl;
  stackEl = document.createElement('div');
  stackEl.className = 'toast-stack';
  stackEl.setAttribute('aria-live', 'polite');
  document.body.appendChild(stackEl);
  return stackEl;
}

/**
 * Show a transient toast.
 * @param {string} message  text content
 * @param {{type?: 'info'|'warn'|'error'|'success', duration?: number}} [opts]
 */
export function showToast(message, opts = {}) {
  const { type = 'info', duration = 5000 } = opts;
  const stack = ensureStack();

  const el = document.createElement('div');
  el.className = `toast toast--${type}`;
  el.setAttribute('role', 'status');

  const text = document.createElement('span');
  text.className = 'toast__text';
  text.textContent = message;
  el.appendChild(text);

  const close = document.createElement('button');
  close.className = 'toast__close';
  close.type = 'button';
  close.setAttribute('aria-label', 'Dismiss');
  close.textContent = '×';
  el.appendChild(close);

  const dismiss = () => {
    el.classList.add('toast--leaving');
    el.addEventListener('transitionend', () => el.remove(), { once: true });
    // Fallback removal if no transition fires.
    setTimeout(() => el.remove(), 400);
  };
  close.addEventListener('click', dismiss);

  stack.appendChild(el);
  // Trigger enter transition on next frame.
  requestAnimationFrame(() => el.classList.add('toast--in'));

  if (duration > 0) setTimeout(dismiss, duration);
  return dismiss;
}

export default showToast;
