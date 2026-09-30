/**
 * The field editor on /admin/fields.
 *
 * A field of type `table` needs a column list, and no other type does, so the
 * column input is shown only while `table` is selected. That was an inline
 * <script> between the select and the input it controls, which meant the rule
 * lived in the markup and could not be exercised by a test.
 *
 * The contract this module owns, and the tests in tests/admin-fields.test.js
 * check:
 *   - the column input is visible for exactly one field type, `table`;
 *   - the initial state is correct before any change event has fired, so the
 *     box does not flash open on a page loaded with another type selected.
 */

export const TABLE_TYPE = 'table';
export const COLUMNS_BOX_ID = 'columns_box';

/** The one field type that has columns. */
export function columnsRequiredFor(fieldType) {
  return fieldType === TABLE_TYPE;
}

/**
 * Show or hide the column input to match the selected type.
 *
 * @param {string} fieldType  the select's current value
 * @param {Element} columnsBox  the container to toggle
 */
export function applyColumnsVisibility(fieldType, columnsBox) {
  columnsBox.classList.toggle('hidden', !columnsRequiredFor(fieldType));
}

/**
 * Wire the select to the column input. Safe to call when either element is
 * absent, so the module can be loaded on any admin page.
 */
export function initFieldTypeEditor(doc = document) {
  const select = doc.getElementById('field_type');
  const columnsBox = doc.getElementById(COLUMNS_BOX_ID);
  if (!select || !columnsBox) return null;

  const sync = () => applyColumnsVisibility(select.value, columnsBox);
  select.addEventListener('change', sync);
  sync();
  return { sync };
}
