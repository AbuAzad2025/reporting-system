/**
 * Authentication screens: reveal a password, and stop a double submit.
 *
 * Both behaviours used to live in the markup - an inline onclick that swapped
 * the input's type and rewrote the button's own text, and nothing at all for
 * the double submit, which is how a credential form ends up sending the same
 * password twice on a slow connection. Templates state structure; this file
 * states behaviour.
 *
 * The reveal button carries two glyphs and the CSS shows the one matching the
 * pressed state, so all this has to do is flip `type` and `aria-pressed` - and
 * the accessible name, which is Arabic text the stylesheet cannot own.
 */

const REVEAL_LABEL_SHOW = 'إظهار كلمة المرور';
const REVEAL_LABEL_HIDE = 'إخفاء كلمة المرور';

/** Flip one password field between masked and plain text. */
function wireReveal(button) {
  const input = document.getElementById(button.dataset.passwordReveal);
  if (!input) return;

  button.addEventListener('click', () => {
    const hidden = input.type === 'password';
    input.type = hidden ? 'text' : 'password';
    button.setAttribute('aria-pressed', String(hidden));
    const label = hidden ? REVEAL_LABEL_HIDE : REVEAL_LABEL_SHOW;
    button.setAttribute('aria-label', label);
    button.setAttribute('title', label);
    // The caret is in the field the visitor was typing into; revealing must not
    // move it away, or the next character lands nowhere.
    input.focus({ preventScroll: true });
    const end = input.value.length;
    try { input.setSelectionRange(end, end); } catch { /* type does not support it */ }
  });
}

/**
 * Disable the submit button once, on the first real submission.
 *
 * Guarded on the form's validity check the browser has already made: the
 * button must stay live while a required field is empty, or the visitor who
 * mistypes a password gets a dead button and no message. `submitted` makes it
 * idempotent, because a form can still fire submit more than once.
 */
function wireSubmitState(form) {
  const button = form.querySelector('[data-auth-submit]');
  if (!button) return;
  let submitted = false;

  form.addEventListener('submit', (event) => {
    if (submitted) {
      event.preventDefault();
      return;
    }
    if (!form.checkValidity()) return;
    submitted = true;
    button.disabled = true;
    button.dataset.busy = '1';
  });
}

export function initAuth(root = document) {
  root.querySelectorAll('[data-password-reveal]').forEach(wireReveal);
  root.querySelectorAll('[data-auth-form]').forEach(wireSubmitState);
}

initAuth();