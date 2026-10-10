/* Interaction layer: press ripple, single-selection highlight, reveal-on-scroll, nav feedback,
   validation shake, auto-dismissing notices, page progress bar. Every part is wrapped so a failure here
   can never stop the rest of the site from working. */
(function () {
  'use strict';
  const reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  const $ = (s, r) => (r || document).querySelector(s), $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const safe = fn => { try { fn(); } catch (e) { if (window.console) console.warn('motion:', e); } };
  const nav = (() => { try { const n = performance.getEntriesByType('navigation')[0]; return n ? n.type : ''; } catch (e) { return ''; } })();

  /* ---- 0. Mark interactive cards (the whole card is a link) ---- */
  safe(() => {
    $$('.stretched-link').forEach(a => { const c = a.closest('.card'); if (c && !c.classList.contains('skill-card')) c.classList.add('mo-card'); });
    $$('.catlink .card').forEach(c => c.classList.add('mo-card'));
    $$('.navbar-nav .nav-item').forEach((li, i) => li.style.setProperty('--mo-i', i));
    $$('.nav-link.active').forEach(a => a.setAttribute('aria-current', 'page'));
  });

  /* ---- 1. Press feedback: works for mouse, pen and touch ---- */
  safe(() => {
    document.addEventListener('touchstart', () => {}, { passive: true });          // lets :active work on iOS Safari
    const unpress = e => { const t = e.target.closest && e.target.closest('.btn'); if (t) t.classList.remove('is-pressed'); };
    document.addEventListener('pointerdown', e => {
      const b = e.target.closest && e.target.closest('.btn');
      if (!b || b.disabled || b.classList.contains('disabled')) return;
      b.classList.add('is-pressed');
      if (reduce) return;
      const r = b.getBoundingClientRect(), d = Math.max(r.width, r.height) * 2;
      const s = document.createElement('span'); s.className = 'mo-ripple';
      s.style.cssText = 'width:' + d + 'px;height:' + d + 'px;left:' + (e.clientX - r.left - d / 2) + 'px;top:' + (e.clientY - r.top - d / 2) + 'px';
      b.appendChild(s); setTimeout(() => s.remove(), 600);
    }, { passive: true });
    ['pointerup', 'pointercancel', 'pointerleave', 'dragend'].forEach(t => document.addEventListener(t, unpress, true));
    document.addEventListener('keydown', e => { if ((e.key === ' ' || e.key === 'Enter') && e.target.classList && e.target.classList.contains('btn')) e.target.classList.add('is-pressed'); });
    document.addEventListener('keyup', unpress);
    document.addEventListener('blur', unpress, true);
  });

  /* ---- 2. Selection: one highlighted item per group until another is chosen or the page changes ---- */
  const KEY = 'mo-sel:' + location.pathname + location.search;
  const cardGroup = el => $$('.skill-card, .mo-card', el.closest('.row') || document);
  function selectCard(c) {
    cardGroup(c).forEach(x => x.classList.remove('is-selected')); c.classList.add('is-selected');
    safe(() => sessionStorage.setItem(KEY, String($$('.skill-card, .mo-card').indexOf(c))));
  }
  safe(() => {
    document.addEventListener('click', e => {
      const t = e.target; if (!t.closest) return;
      const card = t.closest('.skill-card, .mo-card');
      if (card && !t.closest('button, input, select, textarea, form')) selectCard(card);
      const sel = t.closest('.selectable');
      if (sel) { $$('.selectable', sel.parentElement).forEach(x => x.classList.remove('is-selected')); sel.classList.add('is-selected'); }
      const item = t.closest('.dropdown-item, .list-group-item-action, .icon-btn[data-select]');
      if (item) { $$('.is-selected', item.parentElement).forEach(x => x.classList.remove('is-selected')); item.classList.add('is-selected'); }
      const row = t.closest('.table tbody tr');
      if (row && !t.closest('a, button, input, select, textarea, label, form')) { $$('tr.is-selected', row.parentElement).forEach(x => x.classList.remove('is-selected')); row.classList.add('is-selected'); }
      const link = t.closest('.navbar-nav .nav-link');
      if (link && !(e.ctrlKey || e.metaKey || e.shiftKey)) {
        $$('.navbar-nav .nav-link').forEach(x => { x.classList.remove('active', 'is-selected'); x.removeAttribute('aria-current'); });
        link.classList.add('active', 'is-selected'); link.setAttribute('aria-current', 'page');
      }
    });
    // Back/forward: bring back the highlight the person had on that page (a fresh visit starts clean)
    const restore = persisted => {
      if (!persisted && nav !== 'back_forward') return;
      const i = parseInt(sessionStorage.getItem(KEY), 10), all = $$('.skill-card, .mo-card');
      if (!isNaN(i) && all[i]) { all.forEach(x => x.classList.remove('is-selected')); all[i].classList.add('is-selected'); }
    };
    restore(false);
    window.addEventListener('pageshow', e => { if (e.persisted) restore(true); });
  });

  /* ---- 3. Entrance animation, revealed as cards scroll into view ---- */
  safe(() => {
    const items = $$('.skill-card, .mo-card, .stat, .lcard, main .row > [class*="col"] > .card, main > .card, main .card.p-3, main .card.p-4')
      .filter((el, i, a) => a.indexOf(el) === i && !el.closest('.modal, .chat-card'));
    const top = items.filter(el => !items.some(p => p !== el && p.contains(el)));          // never animate a card and the card inside it
    const done = el => { el.classList.add('mo-in'); setTimeout(() => el.classList.remove('mo-reveal', 'mo-in'), 900 + (+el.style.getPropertyValue('--mo-i') || 0) * 55); };
    if (reduce || !('IntersectionObserver' in window)) return;
    top.forEach((el, n) => { const same = top.filter(x => x.parentElement.parentElement === el.parentElement.parentElement); el.style.setProperty('--mo-i', Math.min(same.indexOf(el), 8)); el.classList.add('mo-reveal'); });
    const io = new IntersectionObserver(es => es.forEach(en => { if (en.isIntersecting) { io.unobserve(en.target); done(en.target); } }), { threshold: 0.08, rootMargin: '0px 0px -30px 0px' });
    top.forEach(el => io.observe(el));
    setTimeout(() => top.forEach(el => { if (el.classList.contains('mo-reveal') && !el.classList.contains('mo-in')) done(el); }), 2500);   // never leave anything hidden
  });

  /* ---- 4. Forms: label colour on focus, shake on invalid, loading state ---- */
  safe(() => {
    document.addEventListener('focusin', e => { const f = e.target; if (f.id) { const l = $('label[for="' + f.id + '"]'); if (l) l.classList.add('mo-focus'); } });
    document.addEventListener('focusout', e => { const f = e.target; if (f.id) { const l = $('label[for="' + f.id + '"]'); if (l) l.classList.remove('mo-focus'); } });
    let shaken = 0;
    document.addEventListener('invalid', e => {
      const f = e.target; f.setAttribute('aria-invalid', 'true');
      if (reduce || Date.now() - shaken < 400) return; shaken = Date.now();
      f.classList.remove('mo-shake'); void f.offsetWidth; f.classList.add('mo-shake'); setTimeout(() => f.classList.remove('mo-shake'), 400);
    }, true);
    document.addEventListener('input', e => { if (e.target.getAttribute && e.target.getAttribute('aria-invalid') && e.target.checkValidity()) e.target.removeAttribute('aria-invalid'); });
    document.addEventListener('submit', e => {
      const f = e.target;
      if (f.classList.contains('needs-validation') && !f.checkValidity()) { const bad = $(':invalid', f); if (bad) { bad.dispatchEvent(new Event('invalid')); bad.focus({ preventScroll: false }); } }
      setTimeout(() => {            // after app.js decided: only show loading for a submit that really goes ahead
        if (e.defaultPrevented || !f.checkValidity()) return;
        const b = e.submitter || $('button:not([type=button])', f);
        if (b && !b.dataset.noload) { b.setAttribute('aria-busy', 'true'); b.dataset.moLoading = '1'; }
        bar.start();
      }, 0);
    });
  });

  /* ---- 5. Page progress bar + gentle fade while the next page loads ---- */
  const bar = (() => {
    const el = document.createElement('div'); el.id = 'mo-progress'; el.setAttribute('aria-hidden', 'true'); document.body.appendChild(el);
    let t;
    return {
      start() { if (reduce) return; clearTimeout(t); el.className = ''; void el.offsetWidth; el.className = 'on'; },
      end() { clearTimeout(t); if (!el.classList.contains('on')) return; el.className = 'done'; t = setTimeout(() => { el.className = ''; }, 500); }
    };
  })();
  safe(() => {
    document.addEventListener('click', e => {
      const a = e.target.closest && e.target.closest('a[href]');
      if (!a || e.defaultPrevented || e.button || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
      if (a.target && a.target !== '_self' || a.hasAttribute('download') || a.hasAttribute('data-bs-toggle') || a.origin !== location.origin) return;
      if (a.pathname === location.pathname && a.search === location.search && a.hash) return;
      if (/^(mailto|tel|javascript):/i.test(a.getAttribute('href'))) return;
      bar.start(); if (!reduce) document.body.classList.add('mo-leaving');
    });
    window.addEventListener('pageshow', e => {
      document.body.classList.remove('mo-leaving'); bar.end();
      $$('[data-mo-loading]').forEach(b => {      // leaving by Back must not leave a frozen spinner button
        b.disabled = false; b.removeAttribute('aria-busy'); delete b.dataset.moLoading; $$('.spinner-border', b).forEach(s => s.remove());
      });
    });
    window.addEventListener('load', () => bar.end());
  });

  /* ---- 6. Notices: slide in (CSS), fade away by themselves unless they need attention ---- */
  safe(() => {
    $$('main .alert').forEach(al => {
      if (!/alert-(success|info)/.test(al.className)) return;
      let t = setTimeout(go, 7000);
      function go() { al.classList.add('mo-out'); setTimeout(() => al.remove(), 350); }
      al.addEventListener('mouseenter', () => clearTimeout(t)); al.addEventListener('focusin', () => clearTimeout(t));
      al.addEventListener('mouseleave', () => { t = setTimeout(go, 3000); });
    });
  });
})();
