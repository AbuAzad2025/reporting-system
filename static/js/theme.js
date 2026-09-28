/**
 * Theme switching.
 *
 * This used to be an inline <script> in base.html, which is why the dark theme
 * could sit broken for so long: the toggle wrote `data-theme` while the
 * stylesheet listened for `.dark`, and nothing could catch that - there was no
 * test, and the markup looked right.
 *
 * The contract this module owns, and the tests in tests/theme.test.js check:
 *   - the theme is expressed as the `data-theme` attribute on <html>, which is
 *     the only value the stylesheet reads;
 *   - a stored preference wins over the system preference;
 *   - with no stored preference the system preference is used;
 *   - turning the toggle on writes 'dark' and off writes 'light', and both are
 *     persisted.
 */

export const STORAGE_KEY = 'theme';
export const DARK = 'dark';
export const LIGHT = 'light';

/** The attribute the stylesheet keys off. Changing this means changing CSS. */
export const THEME_ATTRIBUTE = 'data-theme';

/**
 * Decide which theme applies.
 *
 * @param {string|null} stored  value previously written to localStorage
 * @param {boolean} systemPrefersDark  what the OS asks for
 * @returns {'dark'|'light'}
 */
export function resolveTheme(stored, systemPrefersDark) {
  if (stored === DARK) return DARK;
  if (stored === LIGHT) return LIGHT;
  return systemPrefersDark ? DARK : LIGHT;
}

/** Read the stored preference, tolerating storage being unavailable. */
export function readStoredTheme(storage) {
  try {
    return storage.getItem(STORAGE_KEY);
  } catch {
    // Private browsing and blocked storage both throw here; the theme still
    // works for this page view, it just will not be remembered.
    return null;
  }
}

/** Persist the preference, tolerating storage being unavailable. */
export function writeStoredTheme(storage, theme) {
  try {
    storage.setItem(STORAGE_KEY, theme);
    return true;
  } catch {
    return false;
  }
}

/** Apply the theme to the document element. */
export function applyTheme(root, theme) {
  root.setAttribute(THEME_ATTRIBUTE, theme);
}

/** Whether the operating system currently asks for a dark theme. */
export function systemPrefersDark(matchMedia) {
  try {
    return Boolean(matchMedia('(prefers-color-scheme: dark)').matches);
  } catch {
    return false;
  }
}

/**
 * Wire the toggle up. Returns the theme that was applied, so a caller (or a
 * test) can assert it rather than reading the DOM back.
 */
export function initTheme({ root, storage, matchMedia, toggle, onChange }) {
  const prefersDark = systemPrefersDark(matchMedia);
  const theme = resolveTheme(readStoredTheme(storage), prefersDark);

  applyTheme(root, theme);
  if (toggle) {
    toggle.checked = theme === DARK;
    toggle.addEventListener('change', function handleChange() {
      const next = this.checked ? DARK : LIGHT;
      applyTheme(root, next);
      writeStoredTheme(storage, next);
      if (onChange) onChange(next);
    });
  }
  return theme;
}
