// Auto-grow textareas for field entry comfort.
document.querySelectorAll('textarea.field-auto').forEach((el) => {
  const grow = () => { el.style.height = 'auto'; el.style.height = el.scrollHeight + 'px'; };
  el.addEventListener('input', grow); grow();
});

// Sticky action bars: any [data-print] button prints the clean A4 view.
document.addEventListener('click', (e) => {
  const btn = e.target.closest('[data-print]');
  if (btn) { e.preventDefault(); window.print(); }
});

// Line-item tables: add-row clones the last row with fresh indices;
// delete-row removes, or clears the last remaining row.
document.addEventListener('click', (e) => {
  const add = e.target.closest('[data-add-row]');
  if (add) {
    const table = document.querySelector(
      'table.table-field[data-field="' + add.dataset.addRow + '"]');
    if (!table) return;
    const tbody = table.tBodies[0];
    const src = tbody.rows[tbody.rows.length - 1];
    if (!src) return;
    const next = parseInt(table.dataset.next || tbody.rows.length, 10);
    const tr = src.cloneNode(true);
    tr.querySelectorAll('input, select, textarea').forEach((el) => {
      el.name = el.name.replace(/__\d+__/, '__' + next + '__');
      if (el.tagName === 'SELECT') { el.selectedIndex = 0; }
      else if (el.type === 'checkbox') { el.checked = false; }
      else { el.value = ''; }
    });
    const num = tr.querySelector('.row-num');
    if (num) num.textContent = String(next + 1);
    tbody.appendChild(tr);
    table.dataset.next = String(next + 1);
    return;
  }
  const del = e.target.closest('[data-del-row]');
  if (del) {
    const tr = del.closest('tr');
    const tbody = tr && tr.parentElement;
    if (!tbody) return;
    if (tbody.rows.length > 1) {
      tr.remove();
      Array.from(tbody.rows).forEach((r, i) => {
        r.querySelectorAll('input, select, textarea').forEach((el) => {
          el.name = el.name.replace(/__\d+__/, '__' + i + '__');
        });
        const num = r.querySelector('.row-num');
        if (num) num.textContent = String(i + 1);
      });
      const table = tbody.closest('table.table-field');
      if (table) table.dataset.next = String(tbody.rows.length);
    } else {
      tr.querySelectorAll('input, select, textarea').forEach((el) => {
        if (el.tagName === 'SELECT') { el.selectedIndex = 0; }
        else if (el.type === 'checkbox') { el.checked = false; }
        else { el.value = ''; }
      });
    }
  }
});
