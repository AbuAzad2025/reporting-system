/**
 * The behaviour the dark theme depends on.
 *
 * The bug this exists to prevent: the toggle wrote `data-theme` while the
 * stylesheet scoped the theme to `.dark`, so the switch flipped an attribute
 * no rule matched and the page stayed light. Nothing failed, every test passed,
 * and the feature was inert.
 *
 * The first test below is the one that would have caught it: it asserts the
 * attribute the stylesheet actually listens for, and the test suite fails if
 * the two ever drift apart again.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  DARK,
  LIGHT,
  STORAGE_KEY,
  THEME_ATTRIBUTE,
  applyTheme,
  initTheme,
  readStoredTheme,
  resolveTheme,
  systemPrefersDark,
  writeStoredTheme,
} from '../static/js/theme.js';
import { readFileSync } from 'node:fs';

/** A minimal stand-in for an Element that only tracks attributes. */
function fakeRoot() {
  const attributes = {};
  return {
    attributes,
    setAttribute(name, value) {
      attributes[name] = value;
    },
    getAttribute(name) {
      return attributes[name];
    },
  };
}

function fakeStorage(initial = {}) {
  const data = { ...initial };
  return {
    data,
    getItem: (k) => (k in data ? data[k] : null),
    setItem: (k, v) => {
      data[k] = String(v);
    },
  };
}

function fakeToggle(checked = false) {
  const listeners = [];
  return {
    checked,
    addEventListener(type, fn) {
      listeners.push({ type, fn });
    },
    /** Simulate the user clicking the switch. */
    flip(to) {
      this.checked = to;
      listeners
        .filter((l) => l.type === 'change')
        .forEach((l) => l.fn.call(this));
    },
  };
}

const prefersDark = () => ({ matches: true });
const prefersLight = () => ({ matches: false });

describe('the attribute the stylesheet listens for', () => {
  it('is the one the theme module writes', () => {
    // If THEME_ATTRIBUTE ever changes, this fails until the CSS is updated -
    // which is exactly the drift that broke dark mode in the first place.
    const css = readFileSync('static/css/custom.css', 'utf8');
    const utilities = readFileSync('static/css/utilities.css', 'utf8');
    const both = css + utilities;
    expect(THEME_ATTRIBUTE).toBe('data-theme');
    expect(both).toContain(`[${THEME_ATTRIBUTE}="dark"]`);
  });

  it('also accepts a class, so either mechanism keeps working', () => {
    const css = readFileSync('static/css/custom.css', 'utf8');
    expect(css).toMatch(/^\.dark,/m);
  });
});

describe('resolveTheme', () => {
  it('a stored dark preference wins over a light system', () => {
    expect(resolveTheme(DARK, false)).toBe(DARK);
  });

  it('a stored light preference wins over a dark system', () => {
    expect(resolveTheme(LIGHT, true)).toBe(LIGHT);
  });

  it('with nothing stored the system preference is used', () => {
    expect(resolveTheme(null, true)).toBe(DARK);
    expect(resolveTheme(null, false)).toBe(LIGHT);
  });

  it('an unrecognised stored value falls back to the system', () => {
    expect(resolveTheme('purple', true)).toBe(DARK);
    expect(resolveTheme('purple', false)).toBe(LIGHT);
  });
});

describe('storage', () => {
  it('reads and writes under one key', () => {
    const storage = fakeStorage();
    expect(readStoredTheme(storage)).toBeNull();
    writeStoredTheme(storage, DARK);
    expect(storage.data[STORAGE_KEY]).toBe(DARK);
    expect(readStoredTheme(storage)).toBe(DARK);
  });

  it('survives storage that throws on read', () => {
    const hostile = {
      getItem() {
        throw new Error('blocked');
      },
    };
    expect(readStoredTheme(hostile)).toBeNull();
  });

  it('survives storage that throws on write', () => {
    const hostile = {
      setItem() {
        throw new Error('quota exceeded');
      },
    };
    expect(writeStoredTheme(hostile, DARK)).toBe(false);
  });
});

describe('systemPrefersDark', () => {
  it('reports the media query result', () => {
    expect(systemPrefersDark(prefersDark)).toBe(true);
    expect(systemPrefersDark(prefersLight)).toBe(false);
  });

  it('treats a browser without matchMedia as light rather than throwing', () => {
    const missing = () => {
      throw new Error('no matchMedia');
    };
    expect(systemPrefersDark(missing)).toBe(false);
  });
});

describe('initTheme', () => {
  let root;
  let storage;
  let toggle;

  beforeEach(() => {
    root = fakeRoot();
    storage = fakeStorage();
    toggle = fakeToggle();
  });

  it('applies the system preference when nothing is stored', () => {
    const theme = initTheme({
      root,
      storage,
      matchMedia: prefersDark,
      toggle,
    });
    expect(theme).toBe(DARK);
    expect(root.getAttribute(THEME_ATTRIBUTE)).toBe(DARK);
    expect(toggle.checked).toBe(true);
  });

  it('turning the toggle on writes dark and persists it', () => {
    initTheme({ root, storage, matchMedia: prefersLight, toggle });
    expect(root.getAttribute(THEME_ATTRIBUTE)).toBe(LIGHT);

    toggle.flip(true);

    expect(root.getAttribute(THEME_ATTRIBUTE)).toBe(DARK);
    expect(storage.data[STORAGE_KEY]).toBe(DARK);
    expect(toggle.checked).toBe(true);
  });

  it('turning the toggle off writes light and persists it', () => {
    initTheme({ root, storage, matchMedia: prefersDark, toggle });
    expect(root.getAttribute(THEME_ATTRIBUTE)).toBe(DARK);

    toggle.flip(false);

    expect(root.getAttribute(THEME_ATTRIBUTE)).toBe(LIGHT);
    expect(storage.data[STORAGE_KEY]).toBe(LIGHT);
    expect(toggle.checked).toBe(false);
  });

  it('a toggle written before the module runs still wins on the next load', () => {
    // This is the regression that matters: the user chose dark, reloaded, and
    // the page came back light because nothing read the stored value.
    const chosen = fakeStorage({ [STORAGE_KEY]: DARK });
    const theme = initTheme({
      root,
      storage: chosen,
      matchMedia: prefersLight,
      toggle,
    });
    expect(theme).toBe(DARK);
    expect(root.getAttribute(THEME_ATTRIBUTE)).toBe(DARK);
  });

  it('notifies a listener with the new theme', () => {
    const onChange = vi.fn();
    initTheme({ root, storage, matchMedia: prefersLight, toggle, onChange });
    toggle.flip(true);
    expect(onChange).toHaveBeenCalledWith(DARK);
  });

  it('works with no toggle element at all', () => {
    const theme = initTheme({
      root,
      storage,
      matchMedia: prefersDark,
      toggle: null,
    });
    expect(theme).toBe(DARK);
    expect(root.getAttribute(THEME_ATTRIBUTE)).toBe(DARK);
  });

  it('applyTheme writes exactly one attribute', () => {
    applyTheme(root, LIGHT);
    expect(Object.keys(root.attributes)).toEqual([THEME_ATTRIBUTE]);
  });
});
