/**
 * Application start-up.
 *
 * This was an inline <script> at the end of base.html. It held two unrelated
 * jobs - resolving the theme and registering the service worker - plus a
 * readyState dance to run the first one once the DOM existed.
 *
 * The dance is not needed here. A module is deferred by definition, so the
 * document has already been parsed by the time this runs and the toggle
 * element is guaranteed to be there. Dropping it removes the one way the
 * theme could fail to apply on a slow page.
 */
import { initTheme } from './theme.js';

/** Resolve and apply the theme, and wire the toggle. */
function bootTheme() {
  initTheme({
    root: document.documentElement,
    storage: window.localStorage,
    matchMedia: window.matchMedia,
    toggle: document.getElementById('theme-toggle'),
  });
}

/**
 * Register the service worker that makes the app work offline.
 *
 * The URL is read from this module's own script tag rather than templated
 * into a string here, so it still carries the cache-busting version that
 * asset_url() adds without any JavaScript being written in the template.
 *
 * Registration is skipped where unsupported, and a failure is not fatal:
 * without a worker the app still works, it just needs the network.
 */
function registerServiceWorker() {
  if (!('serviceWorker' in navigator)) return;
  // document.currentScript is always null inside a module, so the tag is
  // looked up. There is one, and it is the tag that loaded this file.
  const tag = document.querySelector('script[data-sw-url]');
  const url = tag && tag.dataset.swUrl;
  if (!url) return;

  window.addEventListener('load', () => {
    navigator.serviceWorker.register(url, { scope: '/' }).catch(() => {});
  });
}

export function boot() {
  bootTheme();
  registerServiceWorker();
}

boot();
