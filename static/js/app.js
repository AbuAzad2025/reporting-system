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

// Geolocation auto-tag for field reports — adds hidden lat/lng if granted
document.addEventListener('submit', (e) => {
  const form = e.target;
  if (form.matches && form.matches('form[action*="/reports/dyn/new"], form[action*="/reports/dyn/"][action*="/edit"]')) {
    if (navigator.geolocation && !form.querySelector('input[name="geo_lat"]')) {
      e.preventDefault();
      const addGeoAndSubmit = (lat, lng) => {
        ["geo_lat", "geo_lng"].forEach((k) => {
          let inp = form.querySelector('input[name="'+k+'"]');
          if (!inp) { inp = document.createElement('input'); inp.type='hidden'; inp.name=k; form.appendChild(inp); }
          inp.value = k==="geo_lat"? String(lat||"") : String(lng||"");
        });
        form.submit();
      };
      navigator.geolocation.getCurrentPosition(
        (pos) => addGeoAndSubmit(pos.coords.latitude, pos.coords.longitude),
        () => addGeoAndSubmit("", ""),
        {timeout: 4000, maximumAge: 60000}
      );
      setTimeout(() => { if (!form.querySelector('input[name="geo_lat"]')) addGeoAndSubmit("", ""); }, 5000);
    }
    // offline draft queue
    if (!navigator.onLine) {
      try {
        const key = "draft_" + (form.action || location.pathname) + "_" + Date.now();
        const data = new FormData(form);
        const obj = {}; data.forEach((v,k)=> obj[k]=v);
        localStorage.setItem(key, JSON.stringify({ts: Date.now(), url: form.action, data: obj}));
        alert("لا يوجد اتصال — تم حفظ المسودة محلياً وسيتم رفعها عند عودة الشبكة.");
      } catch(e) {}
    }
  }
});

// Offline draft replay when back online
window.addEventListener('online', () => {
  try {
    Object.keys(localStorage).forEach((k) => {
      if (!k.startsWith('draft_')) return;
      const item = JSON.parse(localStorage.getItem(k) || "{}");
      if (item.url && item.data) {
        fetch(item.url, {method: "POST", body: new URLSearchParams(item.data), headers: {"X-Offline-Replay":"1"}}).catch(()=>{});
        localStorage.removeItem(k);
      }
    });
  } catch(e) {}
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
