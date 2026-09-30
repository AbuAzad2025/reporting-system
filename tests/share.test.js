/**
 * The behaviour the share controls depend on.
 *
 * This was three inline <script> blocks - one in archive.html and one in each
 * of reports/view.html and reports/dyn_view.html - and nothing tested any of
 * it. The two report pages were copies of each other and had already drifted:
 * they used two different spellings of the toast's z-index, and only one of
 * them resolved, so on one page every toast rendered underneath the app header.
 *
 * The tests are in two groups. The unit tests cover what the actions actually
 * do, including the failure paths, because the old copies swallowed a failed
 * fetch and returned null with nothing on screen. The contract tests read the
 * templates and the stylesheet and fail if a name, a fetch target or a class
 * drifts away from what this module and the CSS provide - which is the class of
 * bug that let three copies of the same code disagree in the first place.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  TOAST_MS,
  copyToClipboard,
  fallbackShare,
  fetchShareData,
  initArchiveShare,
  initReportShare,
  shareNativeWith,
  showToast,
} from '../static/js/share.js';
import { readFileSync } from 'node:fs';

const CSS = ['custom.css', 'utilities.css', 'layout.css']
  .map((name) => readFileSync(`static/css/${name}`, 'utf8'))
  .join('\n');

/** The templates that carry a share control. */
const SHARE_TEMPLATES = [
  'templates/archive.html',
  'templates/reports/view.html',
  'templates/reports/dyn_view.html',
];

/** Just enough document for the toast and the clipboard fallback. */
function stubDocument() {
  const appended = [];
  const liveRegion = {
    id: 'toast-root',
    appendChild: (el) => appended.push(el),
  };
  return {
    appended,
    body: { appendChild: (el) => appended.push(el), removeChild: () => {} },
    createElement: () => ({
      className: '',
      textContent: '',
      value: '',
      type: '',
      select() {},
      remove: vi.fn(),
    }),
    getElementById: (id) => (id === 'toast-root' ? liveRegion : null),
    addEventListener: () => {},
  };
}

const PAYLOAD = {
  title: 'تقرير',
  serial: 'DS-00007',
  project: 'Alpha Tower',
};

const SHARE_RESPONSE = {
  url: 'https://example.test/reports/dyn/7',
  whatsapp_url: 'https://wa.me/123',
  email_url: 'mailto:x@example.test',
  payload: PAYLOAD,
};

let originalNavigator;

beforeEach(() => {
  originalNavigator = globalThis.navigator;
  // vitest runs in the node environment, so there is no window. The module
  // installs its entry points onto it because the templates reach them through
  // inline onclick attributes; in a browser that object is the global scope.
  globalThis.window = globalThis;
});

afterEach(() => {
  delete globalThis.window;
  Object.defineProperty(globalThis, 'navigator', {
    value: originalNavigator,
    configurable: true,
    writable: true,
  });
  vi.unstubAllGlobals();
});

/** Replace navigator with a controllable stand-in. */
function setNavigator(value) {
  Object.defineProperty(globalThis, 'navigator', {
    value,
    configurable: true,
    writable: true,
  });
}

describe('fetchShareData', () => {
  it('asks the endpoint for the report type and id it was given', async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => SHARE_RESPONSE });
    vi.stubGlobal('fetch', fetchMock);

    await fetchShareData('dynamic', 7);

    expect(fetchMock).toHaveBeenCalledWith('/reports/share/dynamic/7');
  });

  it('throws when the endpoint refuses, so the caller can say so', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404 }));

    await expect(fetchShareData('legacy', 1)).rejects.toThrow();
  });
});

describe('shareNativeWith', () => {
  beforeEach(() => {
    globalThis.document = stubDocument();
  });

  it('uses the platform sheet when there is one', async () => {
    const share = vi.fn().mockResolvedValue(undefined);
    setNavigator({ share });

    await shareNativeWith({ url: 'https://x.test', ...PAYLOAD });

    expect(share).toHaveBeenCalledWith({
      title: `${PAYLOAD.title} - ${PAYLOAD.serial}`,
      text: `تقرير: ${PAYLOAD.title}\nالرقم: ${PAYLOAD.serial}\nالمشروع: ${PAYLOAD.project}`,
      url: 'https://x.test',
    });
  });

  it('does nothing when the user dismisses the sheet', async () => {
    const aborted = Object.assign(new Error('dismissed'), { name: 'AbortError' });
    setNavigator({ share: vi.fn().mockRejectedValue(aborted) });
    const execCommand = vi.fn();
    globalThis.document.execCommand = execCommand;

    await shareNativeWith({ url: 'https://x.test', ...PAYLOAD });

    // A cancelled share is a decision, not a failure - copying the link would
    // be the wrong answer to it.
    expect(execCommand).not.toHaveBeenCalled();
  });

  it('copies the link when the sheet fails for any other reason', async () => {
    setNavigator({ share: vi.fn().mockRejectedValue(new Error('sheet broke')) });
    const execCommand = vi.fn();
    globalThis.document.execCommand = execCommand;

    await shareNativeWith({ url: 'https://x.test', ...PAYLOAD });

    expect(execCommand).toHaveBeenCalledWith('copy');
  });

  it('copies the link when the platform has no sheet', async () => {
    setNavigator({});
    const execCommand = vi.fn();
    globalThis.document.execCommand = execCommand;

    await shareNativeWith({ url: 'https://x.test', ...PAYLOAD });

    expect(execCommand).toHaveBeenCalledWith('copy');
  });
});

describe('copyToClipboard', () => {
  beforeEach(() => {
    globalThis.document = stubDocument();
  });

  it('uses the clipboard API and says so', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    setNavigator({ clipboard: { writeText } });

    await copyToClipboard('https://x.test');

    expect(writeText).toHaveBeenCalledWith('https://x.test');
  });

  it('falls back when the clipboard API is unavailable', async () => {
    // navigator.clipboard is undefined outside a secure context, and this app
    // is served over plain HTTP on a LAN as well as over TLS.
    setNavigator({});
    const execCommand = vi.fn();
    globalThis.document.execCommand = execCommand;

    await copyToClipboard('https://x.test');

    expect(execCommand).toHaveBeenCalledWith('copy');
  });

  it('falls back when the clipboard API rejects', async () => {
    setNavigator({ clipboard: { writeText: vi.fn().mockRejectedValue(new Error('denied')) } });
    const execCommand = vi.fn();
    globalThis.document.execCommand = execCommand;

    await copyToClipboard('https://x.test');

    expect(execCommand).toHaveBeenCalledWith('copy');
  });
});

describe('showToast', () => {
  it('stacks the toast with the design token, not a literal z-index', () => {
    globalThis.document = stubDocument();

    const el = showToast('hi');

    // This is the drift that let one report page render its toasts underneath
    // the sticky app header: it used z-50, which no stylesheet defines.
    expect(el.className).toBe('toast');
    expect(CSS).toMatch(/\.toast\s*\{[^}]*z-index:\s*var\(--z-index-toast\)/);
  });

  it('every class it sets is one a stylesheet actually defines', () => {
    globalThis.document = stubDocument();

    const el = showToast('hi');

    // The existing template check only reads double-quoted class attributes in
    // HTML, so it cannot see a class name assembled in JavaScript. Assert it
    // here instead, for the one string the JS builds.
    for (const cls of el.className.split(/\s+/)) {
      expect(CSS, `"${cls}" is set on the toast but defined nowhere`).toContain(`.${cls}`);
    }
  });

  it('goes into the live region, so a screen reader announces it', () => {
    const doc = stubDocument();
    globalThis.document = doc;

    showToast('hi');

    // base.html marks #toast-root aria-live="polite". A toast on <body> is
    // rendered but never announced.
    expect(doc.appended).toHaveLength(1);
    expect(doc.getElementById('toast-root').appendChild).toBeDefined();
  });

  it('removes itself, so a toast does not accumulate', () => {
    vi.useFakeTimers();
    globalThis.document = stubDocument();

    const el = showToast('hi');
    expect(el.remove).not.toHaveBeenCalled();

    vi.advanceTimersByTime(TOAST_MS);
    expect(el.remove).toHaveBeenCalled();

    vi.useRealTimers();
  });
});

describe('globals the templates call', () => {
  it('initReportShare installs every name the report pages use in onclick', () => {
    globalThis.document = stubDocument();
    initReportShare({ reportType: 'dynamic', reportId: 7 });

    for (const name of ['toggleShareMenu', 'closeShareMenu', 'shareNative',
                        'shareWhatsApp', 'copyLink', 'shareEmail']) {
      expect(typeof window[name], `${name} is called but not installed`).toBe('function');
    }
  });

  it('initArchiveShare installs the names the archive sheet calls', () => {
    globalThis.document = stubDocument();
    initArchiveShare();

    for (const name of ['shareNative', 'copyLink', 'showToast', 'fallbackShare']) {
      expect(typeof window[name], `${name} is called but not installed`).toBe('function');
    }
  });
});

describe('contract with the templates', () => {
  /** Every bare identifier an inline onclick attribute calls. */
  function calledGlobals(html) {
    const names = new Set();
    for (const match of html.matchAll(/onclick="([a-zA-Z_$][\w$]*)\s*\(/g)) {
      names.add(match[1]);
    }
    return names;
  }

  it('every onclick target in a share template is installed by an init function', () => {
    globalThis.document = stubDocument();
    initReportShare({ reportType: 'legacy', reportId: 1 });
    initArchiveShare();

    for (const path of SHARE_TEMPLATES) {
      for (const name of calledGlobals(readFileSync(path, 'utf8'))) {
        // `window.open` and `this.closest` are not ours to install.
        if (name === 'window' || name === 'this') continue;
        expect(typeof window[name], `${path} calls ${name}(), nothing installs it`)
          .toBe('function');
      }
    }
  });

  it('each share template loads the module rather than inlining the logic', () => {
    for (const path of SHARE_TEMPLATES) {
      const html = readFileSync(path, 'utf8');
      expect(html, `${path} no longer loads the module`).toContain('js/share.js');
      expect(html, `${path} must not define share functions inline`)
        .not.toMatch(/function\s+(shareNative|copyLink|showToast|fetchShareUrls)\s*\(/);
    }
  });

  it('the module is precached, so sharing works offline', () => {
    expect(readFileSync('static/sw.js', 'utf8')).toContain('/static/js/share.js');
  });
});
