/**
 * Avatar preview on /profile.
 *
 * The file input called `previewAvatar(this)` but nothing defined
 * `previewAvatar`, anywhere in the repository. The handler had been dead since
 * it was written, so choosing a picture produced no feedback at all - the
 * `#avatarPreview` image next to the input stayed hidden and the user had no
 * way to tell whether their selection had registered before saving.
 *
 * The contract this module owns, and the tests in tests/profile.test.js check:
 *   - a chosen image is shown in the preview and the preview is revealed;
 *   - a non-image is refused and the previous preview is left alone;
 *   - choosing nothing is a no-op rather than an error;
 *   - each object URL is revoked when it is replaced, so repeatedly picking
 *     files does not leak the previous ones.
 */

export const AVATAR_INPUT_ID = 'f-avatar';
export const AVATAR_PREVIEW_ID = 'avatarPreview';

/** Whether a picked file is one the preview will display. */
export function isDisplayableImage(file) {
  return Boolean(file && file.type && file.type.startsWith('image/'));
}

/**
 * Show the chosen file in the preview element.
 *
 * @param {HTMLInputElement} input  the file input
 * @param {HTMLImageElement} preview  the preview image
 * @param {File} file  what the user picked
 * @returns {boolean} whether the preview was updated
 */
export function showPreview(input, preview, file) {
  if (!isDisplayableImage(file)) return false;

  // The URL of the file being replaced has to be released, or a user who
  // picks several times in a row keeps every earlier file alive in memory.
  const previous = preview.dataset.objectUrl;
  if (previous) {
    URL.revokeObjectURL(previous);
    delete preview.dataset.objectUrl;
  }

  const url = URL.createObjectURL(file);
  preview.dataset.objectUrl = url;
  preview.src = url;
  preview.classList.remove('hidden');
  return true;
}

/** Wire the input to the preview. */
export function initAvatarPreview(doc = document) {
  const input = doc.getElementById(AVATAR_INPUT_ID);
  const preview = doc.getElementById(AVATAR_PREVIEW_ID);
  if (!input || !preview) return null;

  input.addEventListener('change', () => {
    const file = input.files && input.files[0];
    if (file) showPreview(input, preview, file);
  });
  return { input, preview };
}
