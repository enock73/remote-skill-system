(function () {
  const modal = new bootstrap.Modal(document.getElementById('confirmModal'));
  let pending = null;
  // Confirmation dialog for any form/button carrying data-confirm; loading state + double-submit guard
  document.addEventListener('submit', e => {
    const f = e.target, msg = f.dataset.confirm || (e.submitter && e.submitter.dataset.confirm);
    if (msg && !f.dataset.ok) { e.preventDefault(); pending = f; document.getElementById('confirmText').textContent = msg; modal.show(); return; }
    if (!f.checkValidity()) return;
    const b = e.submitter || f.querySelector('button:not([type=button])');
    if (b && !b.dataset.noload) setTimeout(() => { b.disabled = true; b.insertAdjacentHTML('afterbegin', '<span class="spinner-border spinner-border-sm me-1"></span>'); }, 0);
  });
  document.getElementById('confirmOk').addEventListener('click', () => { if (pending) { pending.dataset.ok = '1'; modal.hide(); pending.requestSubmit(); } });
  // Bootstrap client-side validation (the server re-validates everything)
  document.querySelectorAll('form.needs-validation').forEach(f => f.addEventListener('submit', e => { if (!f.checkValidity()) { e.preventDefault(); e.stopPropagation(); } f.classList.add('was-validated'); }, true));
  document.querySelectorAll('input[type=file][data-preview]').forEach(i => i.addEventListener('change', () => {
    const t = document.querySelector(i.dataset.preview), file = i.files[0];
    if (t && file) { t.src = URL.createObjectURL(file); t.classList.remove('d-none'); } }));
  document.querySelectorAll('[data-toggle-pw]').forEach(b => b.addEventListener('click', () => { const i = document.querySelector(b.dataset.togglePw); i.type = i.type === 'password' ? 'text' : 'password'; }));
  // Live unread-notification badge
  const url = document.body.dataset.countUrl, badge = document.getElementById('notif-badge');
  if (url && badge) setInterval(() => fetch(url, { credentials: 'same-origin' }).then(r => r.ok ? r.json() : null).then(d => {
    if (d) { badge.textContent = d.unread; badge.classList.toggle('d-none', !d.unread); } }).catch(() => {}), 30000);
})();
