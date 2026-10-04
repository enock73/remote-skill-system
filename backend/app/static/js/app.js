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

  // Booking chat: send without reloading, and check for new messages every 6 seconds
  const chat = document.getElementById('chat');
  if (chat) {
    const box = document.getElementById('chatBox'), empty = document.getElementById('chatEmpty'), form = document.getElementById('chatForm'), err = document.getElementById('chatError');
    const lastId = () => { const r = box.querySelectorAll('.bubble-row'); return r.length ? +r[r.length - 1].dataset.id : 0; };
    const add = m => {
      if (box.querySelector('[data-id="' + m.id + '"]')) return;
      const row = document.createElement('div'); row.className = 'bubble-row ' + (m.mine ? 'mine' : 'theirs'); row.dataset.id = m.id;
      const b = document.createElement('div'); b.className = 'bubble';
      const w = document.createElement('div'); w.className = 'who'; w.textContent = m.sender + ' · ' + m.time;
      b.appendChild(w); b.appendChild(document.createTextNode(m.body)); row.appendChild(b); box.appendChild(row);
      if (empty) empty.classList.add('d-none');
    };
    const down = () => { box.scrollTop = box.scrollHeight; };
    const poll = () => fetch(chat.dataset.messagesUrl + '?after=' + lastId(), { credentials: 'same-origin' })
      .then(r => r.ok ? r.json() : null).then(d => { if (d && d.messages.length) { d.messages.forEach(add); down(); } }).catch(() => {});
    down(); setInterval(poll, 6000);
    if (form) form.addEventListener('submit', e => {
      e.preventDefault(); e.stopPropagation(); err.classList.add('d-none');
      const btn = form.querySelector('button'), ta = form.querySelector('textarea'); if (!ta.value.trim()) return;
      btn.disabled = true;
      fetch(chat.dataset.sendUrl, { method: 'POST', body: new FormData(form), credentials: 'same-origin', headers: { 'X-Requested-With': 'fetch' } })
        .then(r => r.json().then(d => ({ ok: r.ok, d })))
        .then(({ ok, d }) => { if (ok && d.message) { add(d.message); ta.value = ''; down(); } else { err.textContent = d.error || 'Could not send. Try again.'; err.classList.remove('d-none'); } })
        .catch(() => { err.textContent = 'Network problem. Try again.'; err.classList.remove('d-none'); })
        .finally(() => { btn.disabled = false; ta.focus(); });
    });
  }
})();
