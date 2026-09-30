/**
 * The avatar preview on /profile.
 *
 * The file input called `previewAvatar(this)` and nothing in the repository
 * defined it, so choosing a picture produced no feedback at all. The behaviour
 * is small, but it is the only thing that tells a user their selection
 * registered before they save, so it is worth pinning down.
 *
 * The tests are in two groups: the unit tests cover what the preview does with
 * a given file, and the contract test reads the template to check the input and
 * the preview element the module looks for are the ones the page renders - the
 * ids have to agree, and nothing else would notice when they stopped.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  AVATAR_INPUT_ID,
  AVATAR_PREVIEW_ID,
  initAvatarPreview,
  isDisplayableImage,
  showPreview,
} from '../static/js/profile.js';
import { readFileSync } from 'node:fs';

let revoked;

beforeEach(() => {
  revoked = [];
  globalThis.URL = {
    createObjectURL: (file) => `blob:${file.name}`,
    revokeObjectURL: (url) => revoked.push(url),
  };
});

afterEach(() => {
  delete globalThis.URL;
});

/** Enough of a preview element for the module to work with. */
function fakePreview() {
  return { className: 'hidden', src: '', dataset: {}, classList: { remove: () => {} } };
}

describe('isDisplayableImage', () => {
  it('accepts the image types the input allows', () => {
    for (const type of ['image/jpeg', 'image/png', 'image/gif', 'image/webp']) {
      expect(isDisplayableImage({ type })).toBe(true);
    }
  });

  it('refuses anything else', () => {
    for (const value of [null, undefined, {}, { type: '' },
                         { type: 'text/html' }, { type: 'application/pdf' }]) {
      expect(isDisplayableImage(value)).toBe(false);
    }
  });
});

describe('showPreview', () => {
  it('points the preview at the chosen file and reveals it', () => {
    const preview = fakePreview();
    let revealed = false;
    preview.classList.remove = () => { revealed = true; };

    const shown = showPreview({}, preview, { name: 'me.png', type: 'image/png' });

    expect(shown).toBe(true);
    expect(preview.src).toBe('blob:me.png');
    expect(revealed).toBe(true);
  });

  it('refuses a non-image and leaves the existing preview alone', () => {
    const preview = fakePreview();
    preview.src = 'blob:already-chosen.png';

    const shown = showPreview({}, preview, { name: 'notes.txt', type: 'text/plain' });

    expect(shown).toBe(false);
    expect(preview.src).toBe('blob:already-chosen.png');
  });

  it('releases the URL it replaces, so picking repeatedly does not leak', () => {
    const preview = fakePreview();

    showPreview({}, preview, { name: 'first.png', type: 'image/png' });
    showPreview({}, preview, { name: 'second.png', type: 'image/png' });

    expect(revoked).toEqual(['blob:first.png']);
    expect(preview.src).toBe('blob:second.png');
  });
});

describe('initAvatarPreview', () => {
  it('returns null when the page has neither element, rather than throwing', () => {
    const doc = { getElementById: () => null };
    expect(initAvatarPreview(doc)).toBeNull();
  });

  it('shows the file the user picks', () => {
    const listeners = {};
    const input = {
      id: AVATAR_INPUT_ID,
      files: [{ name: 'me.png', type: 'image/png' }],
      addEventListener: (type, fn) => { listeners[type] = fn; },
    };
    const preview = fakePreview();
    preview.id = AVATAR_PREVIEW_ID;
    preview.classList.remove = () => {};
    const doc = { getElementById: (id) => (id === AVATAR_INPUT_ID ? input : preview) };

    initAvatarPreview(doc);
    listeners.change();

    expect(preview.src).toBe('blob:me.png');
  });

  it('does nothing when the user picks no file', () => {
    const listeners = {};
    const input = {
      id: AVATAR_INPUT_ID,
      files: [],
      addEventListener: (type, fn) => { listeners[type] = fn; },
    };
    const preview = fakePreview();
    const doc = { getElementById: (id) => (id === AVATAR_INPUT_ID ? input : preview) };

    initAvatarPreview(doc);
    expect(() => listeners.change()).not.toThrow();
    expect(preview.src).toBe('');
  });
});

describe('contract with the template', () => {
  const html = readFileSync('templates/profile.html', 'utf8');

  it('the page renders the ids the module looks for', () => {
    expect(html).toContain(`id="${AVATAR_INPUT_ID}"`);
    expect(html).toContain(`id="${AVATAR_PREVIEW_ID}"`);
  });

  it('the page loads the module instead of calling a handler inline', () => {
    expect(html).toContain('js/profile.js');
    // The original called previewAvatar(this) and defined the function in an
    // inline <script> that was lost with the rest of the truncated page.
    expect(html).not.toMatch(/onchange="previewAvatar/);
  });
});
