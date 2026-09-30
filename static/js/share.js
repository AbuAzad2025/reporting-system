/**
 * Report sharing.
 *
 * This behaviour used to be three inline <script> blocks: one in archive.html
 * and one in each of reports/view.html and reports/dyn_view.html. The two
 * report pages were copies of each other, and archive.html was a third
 * arrangement of the same four actions. They had already drifted - the archive
 * copy passed title and serial as arguments while the two report copies read
 * them from the page, and all three had to be edited together for any change
 * to sharing behaviour.
 *
 * There was a latent collision too: `shareNative` and `copyLink` were global
 * on all three pages with incompatible signatures. The pages never rendered
 * together, so nothing broke, but the next template to include two of these
 * blocks would have had a silent last-one-wins failure.
 *
 * The globals stay global. Templates reach these through inline `onclick`
 * attributes, and that is a live DOM contract on the buttons, so the names and
 * the argument shapes are preserved here rather than migrated to listeners.
 * The one accommodation is that `shareNative` and `copyLink` now accept their
 * arguments or fall back to the context the calling page registered, which is
 * what lets both call sites keep working against one implementation.
 *
 * The contract this module owns, and the tests in tests/share.test.js check:
 *   - the share payload is fetched from /reports/share/<type>/<id>;
 *   - a failed fetch shows a toast and never opens a menu;
 *   - a successful share prefers the platform sheet and falls back to copying
 *     the link when there is no sheet, or when the sheet errors for a reason
 *     other than the user cancelling it;
 *   - the toast is the .toast component, so placement comes from the design
 *     tokens rather than from a class string in this file.
 */

const SHARE_ENDPOINT = '/reports/share';

/** Toast dwell time, matching the removal delay the inline copies used. */
export const TOAST_MS = 3000;

/**
 * The share actions a report page registers so the zero-argument globals can
 * find it. Set by initReportShare.
 */
let reportContext = null;

/**
 * The toast. Placement lives in the .toast component in custom.css, which
 * reads the z-index and spacing tokens.
 *
 * Three spellings of this class string existed across the three inline
 * scripts and not one of them resolved: they used `bottom-24`, `left-1/2`,
 * `-translate-x-1/2` and `z-[var(--z-index-toast)]`, none of which any
 * stylesheet defines, so the toast was a fixed box pinned at its static
 * position with no z-index and rendered under the sticky header.
 */
const TOAST_CLASS = 'toast';

/**
 * Show a transient message.
 *
 * Appended to #toast-root when it is present, because that element is the
 * aria-live region base.html provides: a toast mounted on <body> instead is
 * invisible to a screen reader, so the message the user just triggered is
 * never announced. Falls back to <body> only so the module still works in a
 * test or on a page that has no live region.
 *
 * Returns the element so a caller that showed a "working..." message before
 * an await can take it down as soon as the work settles, instead of leaving it
 * to time out.
 */
export function showToast(message) {
  const el = document.createElement('div');
  el.textContent = message;
  el.className = TOAST_CLASS;
  const host = document.getElementById('toast-root') || document.body;
  host.appendChild(el);
  setTimeout(() => el.remove(), TOAST_MS);
  return el;
}

/**
 * Copy without the async clipboard API.
 *
 * Still needed: navigator.clipboard is undefined outside a secure context,
 * and this app is served over plain HTTP on a LAN as well as over TLS. A
 * hidden input plus execCommand is the only thing that works in both.
 */
export function fallbackShare(url, message) {
  const temp = document.createElement('input');
  temp.value = url;
  document.body.appendChild(temp);
  temp.select();
  document.execCommand('copy');
  document.body.removeChild(temp);
  showToast(message);
}

/** Share the platform's native sheet, or copy the link if there is none. */
export async function shareNativeWith({ url, serial, title, project }) {
  if (navigator.share) {
    try {
      await navigator.share({
        title: title + ' - ' + serial,
        text: `تقرير: ${title}\nالرقم: ${serial}\nالمشروع: ${project}`,
        url: url,
      });
      return;
    } catch (err) {
      // A cancelled share is the user changing their mind, not a failure.
      if (err.name === 'AbortError') return;
    }
  }
  fallbackShare(url, 'تم نسخ الرابط (متصفح لا يدعم المشاركة الأصلية)');
}

/** Copy the link, falling back when the clipboard API is unavailable. */
export async function copyToClipboard(url) {
  try {
    await navigator.clipboard.writeText(url);
    showToast('تم نسخ الرابط إلى الحافظة');
  } catch {
    fallbackShare(url, 'تم نسخ الرابط');
  }
}

/** Fetch the share payload for one report. Throws if the endpoint refuses. */
export async function fetchShareData(reportType, reportId) {
  const res = await fetch(`${SHARE_ENDPOINT}/${reportType}/${reportId}`);
  if (!res.ok) throw new Error('فشل في جلب بيانات المشاركة');
  return res.json();
}

/* ------------------------------------------------------------------ dropdown */

/** The dropdown on a single report's page: #shareMenu > #shareDropdown. */
export function toggleShareMenu() {
  const dropdown = document.getElementById('shareDropdown');
  if (dropdown) dropdown.classList.toggle('hidden');
}

export function closeShareMenu() {
  const dropdown = document.getElementById('shareDropdown');
  if (dropdown) dropdown.classList.add('hidden');
}

/** Dismiss the dropdown when the click lands outside the share control. */
function bindDropdownDismissal() {
  document.addEventListener('click', (e) => {
    const menu = document.getElementById('shareMenu');
    if (menu && !menu.contains(e.target)) closeShareMenu();
  });
}

/* --------------------------------------------------------------- archive menu */

const ARCHIVE_MENU_ID = 'archiveShareMenu';

/** One row in the archive share sheet. */
function shareActionRow(icon, label, className, onActivate) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className =
    'w-full text-right px-4 py-3 rounded-xl flex items-center gap-3 ' + className;
  button.addEventListener('click', onActivate);

  const glyph = document.createElement('span');
  glyph.className = 'text-xl';
  glyph.textContent = icon;
  button.appendChild(glyph);
  button.appendChild(document.createTextNode(label));
  return button;
}

/**
 * The archive share sheet, built as DOM rather than as an innerHTML string.
 *
 * The string version interpolated the report title, serial and project into
 * onclick attributes behind a hand-rolled escaper, so the escaping was one
 * missed quote away from being a script injection into a page that renders
 * user-supplied report names. Building the nodes means every value lands in
 * textContent, where it cannot break out of anything.
 */
export function openArchiveShareMenu(data, { serial, title, project }) {
  document.getElementById(ARCHIVE_MENU_ID)?.remove();

  const menu = document.createElement('div');
  menu.id = ARCHIVE_MENU_ID;
  menu.className = 'fixed inset-0 z-50 flex items-center justify-center bg-black/30';

  const panel = document.createElement('div');
  panel.className =
    'bg-white rounded-2xl shadow-xl w-full max-w-sm p-4 m-4 animate-fade-in';
  menu.appendChild(panel);

  const header = document.createElement('div');
  header.className = 'flex items-center justify-between mb-4';
  const heading = document.createElement('h3');
  heading.className = 'font-bold text-lg text-navy';
  heading.textContent = 'مشاركة: ' + serial;
  const dismiss = document.createElement('button');
  dismiss.type = 'button';
  dismiss.className = 'text-slate-400 hover:text-red-600 text-xl';
  dismiss.textContent = '×';
  dismiss.addEventListener('click', () => menu.remove());
  header.append(heading, dismiss);

  const subtitle = document.createElement('div');
  subtitle.className = 'text-sm text-slate-600 mb-4';
  subtitle.textContent = title + ' — ' + project;

  const actions = document.createElement('div');
  actions.className = 'space-y-2';
  const dismissThen = (fn) => () => { menu.remove(); fn(); };
  actions.append(
    shareActionRow('📱', 'مشاركة النظام (Native)',
      'bg-slate-100 hover:bg-slate-200 text-slate-700',
      dismissThen(() => shareNative(data.url, serial, title, project))),
    shareActionRow('💬', 'واتساب (WhatsApp)',
      'bg-green-50 hover:bg-green-100 text-green-700',
      dismissThen(() => window.open(data.whatsapp_url, '_blank'))),
    shareActionRow('🔗', 'نسخ الرابط',
      'bg-blue-50 hover:bg-blue-100 text-blue-700',
      dismissThen(() => copyLink(data.url))),
    shareActionRow('✉️', 'البريد الإلكتروني',
      'bg-amber-50 hover:bg-amber-100 text-amber-700',
      dismissThen(() => { window.location.href = data.email_url; })),
  );

  panel.append(header, subtitle, actions);
  document.body.appendChild(menu);

  // A click on the backdrop itself dismisses; clicks inside the panel do not.
  menu.addEventListener('click', (e) => {
    if (e.target === menu) menu.remove();
  });
}

/* ------------------------------------------------------------------ entry points */

/**
 * Wire a single report's page (reports/view.html, reports/dyn_view.html).
 *
 * Registers the globals its inline onclick attributes call, with the zero-
 * argument shapes the buttons use.
 */
export function initReportShare({ reportType, reportId }) {
  reportContext = { reportType, reportId };
  bindDropdownDismissal();

  const payloadFor = async () => {
    try {
      return await fetchShareData(reportContext.reportType, reportContext.reportId);
    } catch {
      showToast('فشل في تحميل خيارات المشاركة');
      return null;
    }
  };

  window.toggleShareMenu = toggleShareMenu;
  window.closeShareMenu = closeShareMenu;

  window.shareNative = async (url, serial, title, project) => {
    if (url) {
      await shareNativeWith({ url, serial, title, project });
      return;
    }
    closeShareMenu();
    const data = await payloadFor();
    if (!data) return;
    await shareNativeWith({
      url: data.url,
      serial: data.payload.serial,
      title: data.payload.title,
      project: data.payload.project,
    });
  };

  window.shareWhatsApp = async () => {
    closeShareMenu();
    const data = await payloadFor();
    if (!data) return;
    window.open(data.whatsapp_url, '_blank');
  };

  window.copyLink = async (url) => {
    if (url) {
      await copyToClipboard(url);
      return;
    }
    closeShareMenu();
    const data = await payloadFor();
    if (!data) return;
    await copyToClipboard(data.url);
  };

  window.shareEmail = async () => {
    closeShareMenu();
    const data = await payloadFor();
    if (!data) return;
    window.location.href = data.email_url;
  };
}

/**
 * Wire the archive page (archive.html).
 *
 * Its share buttons carry the report's identity in data attributes, so one
 * delegated listener covers every card on the page.
 */
export function initArchiveShare() {
  document.addEventListener('click', async (e) => {
    const btn = e.target.closest('[data-share-type]');
    if (!btn) return;
    const { shareType: reportType, shareId: reportId } = btn.dataset;

    // Taken down as soon as the fetch settles, rather than left to time out
    // over the menu it is announcing.
    const pending = showToast('جاري تحضير خيارات المشاركة...');
    try {
      const data = await fetchShareData(reportType, reportId);
      openArchiveShareMenu(data, {
        serial: btn.dataset.shareSerial,
        title: btn.dataset.shareTitle,
        project: btn.dataset.shareProject,
      });
    } catch {
      showToast('فشل في تحميل خيارات المشاركة');
    } finally {
      pending.remove();
    }
  });

  // The archive sheet calls these two by name from its own buttons.
  window.shareNative = (url, serial, title, project) =>
    shareNativeWith({ url, serial, title, project });
  window.copyLink = copyToClipboard;
  window.showToast = showToast;
  window.fallbackShare = fallbackShare;
}
