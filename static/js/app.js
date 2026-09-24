// Azadexa professional front-end: toasts, dismissible flashes,
// non-blocking geolocation, safe offline drafts, dynamic tables.
(function () {
  "use strict";

  // Auto-grow textareas for field entry comfort.
  document.querySelectorAll("textarea.field-auto").forEach((el) => {
    const grow = () => { el.style.height = "auto"; el.style.height = el.scrollHeight + "px"; };
    el.addEventListener("input", grow); grow();
  });

  // Dismissible flash messages.
  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-dismiss-flash]");
    if (btn) {
      const msg = btn.closest(".flash-msg");
      if (msg) msg.remove();
    }
    const printBtn = e.target.closest("[data-print]");
    if (printBtn) { e.preventDefault(); window.print(); }
  });

  // Toast helper (replaces alert()).
  function toast(msg) {
    const root = document.getElementById("toast-root");
    if (!root) { alert(msg); return; }
    const el = document.createElement("div");
    el.className = "toast";
    el.textContent = msg;
    root.appendChild(el);
    setTimeout(() => el.remove(), 3200);
  }
  window.azadToast = toast;

  // Geolocation: NEVER block submit. Race location against 900ms timeout,
  // then submit once with whatever we have.
  document.addEventListener("submit", (e) => {
    const form = e.target;
    if (!(form.matches && form.matches('form[action*="/reports/dyn/new"], form[action*="/reports/dyn/"][action*="/edit"]'))) return;
    if (!navigator.geolocation || form.querySelector('input[name="geo_lat"]') || form.dataset.geoDone === "1") return;
    // Offline file forms: skip geo race, handle draft below.
    e.preventDefault();
    form.dataset.geoDone = "1";
    let done = false;
    const submitWith = (lat, lng) => {
      if (done) return; done = true;
      ["geo_lat", "geo_lng"].forEach((k) => {
        let inp = form.querySelector('input[name="' + k + '"]');
        if (!inp) { inp = document.createElement("input"); inp.type = "hidden"; inp.name = k; form.appendChild(inp); }
        inp.value = k === "geo_lat" ? String(lat || "") : String(lng || "");
      });
      form.submit();
    };
    try {
      navigator.geolocation.getCurrentPosition(
        (pos) => submitWith(pos.coords.latitude, pos.coords.longitude),
        () => submitWith("", ""),
        { timeout: 900, maximumAge: 60000 }
      );
    } catch (err) { submitWith("", ""); }
    setTimeout(() => submitWith("", ""), 1000);

    // Offline draft (text-only forms; file uploads cannot be replayed safely).
    if (!navigator.onLine && !form.querySelector('input[type="file"]')) {
      try {
        const key = "draft_" + (form.action || location.pathname) + "_" + Date.now();
        const data = new FormData(form);
        const obj = {}; data.forEach((v, k) => { if (typeof v === "string") obj[k] = v; });
        localStorage.setItem(key, JSON.stringify({ ts: Date.now(), url: form.action, data: obj }));
        toast("لا يوجد اتصال — حُفظت مسودة محلياً.");
      } catch (err) {}
    }
  });

  // ESHS checklist integrity: done / not_done are mutually exclusive
  // per row (mirrors server-side validation in reports/routes.py).
  document.addEventListener("change", (e) => {
    const box = e.target.closest
      ? e.target.closest('table.table-field input[type="checkbox"]')
      : null;
    if (!box || !box.checked) return;
    const name = box.name || "";
    const m = name.match(/^(f_.+)__(\d+)__(done|not_done)$/);
    if (!m) return;
    const other = m[3] === "done" ? "not_done" : "done";
    const tr = box.closest("tr");
    if (!tr) return;
    const sibling = tr.querySelector('input[name="' + m[1] + "__" + m[2] + "__" + other + '"]');
    if (sibling && sibling.checked) {
      sibling.checked = false;
      toast("تم إلغاء الخيار المقابل تلقائياً (تم / لم يتم).");
    }
  });

  // Line-item tables: add-row clones the last row with fresh indices;
  // delete-row removes, or clears the last remaining row.
  document.addEventListener("click", (e) => {
    const add = e.target.closest("[data-add-row]");
    if (add) {
      const table = document.querySelector('table.table-field[data-field="' + add.dataset.addRow + '"]');
      if (!table) return;
      const tbody = table.tBodies[0];
      const src = tbody.rows[tbody.rows.length - 1];
      if (!src) return;
      const next = parseInt(table.dataset.next || tbody.rows.length, 10);
      const tr = src.cloneNode(true);
      tr.querySelectorAll("input, select, textarea").forEach((el) => {
        if (el.type === "hidden" && el.value && el.value.includes("/")) return; // keep stored file ref
        el.name = el.name.replace(/__\d+__/, "__" + next + "__");
        if (el.tagName === "SELECT") { el.selectedIndex = 0; }
        else if (el.type === "checkbox") { el.checked = false; }
        else if (el.type !== "hidden") { el.value = ""; }
      });
      // file inputs cannot retain value: clear them explicitly
      tr.querySelectorAll('input[type="file"]').forEach((el) => { el.value = ""; });
      const num = tr.querySelector(".row-num");
      if (num) num.textContent = String(next + 1);
      tbody.appendChild(tr);
      table.dataset.next = String(next + 1);
      const btn = document.querySelector('[data-add-row="' + add.dataset.addRow + '"]');
      if (btn) btn.textContent = "＋ إضافة بند (" + tbody.rows.length + " حالياً)";
      return;
    }
    const del = e.target.closest("[data-del-row]");
    if (del) {
      const tr = del.closest("tr");
      const tbody = tr && tr.parentElement;
      if (!tbody) return;
      if (tbody.rows.length > 1) {
        tr.remove();
        Array.from(tbody.rows).forEach((r, i) => {
          r.querySelectorAll("input, select, textarea").forEach((el) => {
            el.name = el.name.replace(/__\d+__/, "__" + i + "__");
          });
          const num = r.querySelector(".row-num");
          if (num) num.textContent = String(i + 1);
        });
        const table = tbody.closest("table.table-field");
        if (table) {
          table.dataset.next = String(tbody.rows.length);
          const btn = document.querySelector('[data-add-row="' + table.dataset.field + '"]');
          if (btn) btn.textContent = "＋ إضافة بند (" + tbody.rows.length + " حالياً)";
        }
      } else {
        tr.querySelectorAll("input, select, textarea").forEach((el) => {
          if (el.tagName === "SELECT") { el.selectedIndex = 0; }
          else if (el.type === "checkbox") { el.checked = false; }
          else if (el.type !== "hidden") { el.value = ""; }
        });
      }
    }
  });
})();
