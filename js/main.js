(function () {
  'use strict';

  // ===== NAV =====
  var tog = document.querySelector('.nav-toggle');
  var links = document.querySelector('.nav-links');
  if (tog && links) {
    tog.addEventListener('click', function () { links.classList.toggle('open'); });
    links.querySelectorAll('a').forEach(function (a) {
      a.addEventListener('click', function () { links.classList.remove('open'); });
    });
  }

  var nav = document.querySelector('.nav');
  if (nav) {
    window.addEventListener('scroll', function () {
      nav.classList.toggle('is-scrolled', window.scrollY > 30);
    }, { passive: true });
  }

  // ===== PROGRESS BAR =====
  var bar = document.querySelector('.progress-bar');
  if (bar) {
    window.addEventListener('scroll', function () {
      var max = document.documentElement.scrollHeight - window.innerHeight;
      bar.style.width = (window.scrollY / Math.max(max, 1) * 100) + '%';
    }, { passive: true });
  }

  // ===== SCROLL REVEAL =====
  var els = document.querySelectorAll('.reveal');
  if (els.length) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
      });
    }, { threshold: 0.1, rootMargin: '0px 0px -30px 0px' });
    els.forEach(function (el) { io.observe(el); });
  }

  // ===== STAGGER =====
  document.querySelectorAll('.stagger').forEach(function (p) {
    Array.from(p.children).forEach(function (c, i) { c.style.setProperty('--d', i); });
  });

  // ===== ANIMATED COUNTERS =====
  var nums = document.querySelectorAll('[data-count]');
  if (nums.length) {
    var cio = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { countUp(e.target); cio.unobserve(e.target); }
      });
    }, { threshold: 0.3 });
    nums.forEach(function (el) { cio.observe(el); });
  }

  function countUp(el) {
    var raw = el.getAttribute('data-count');
    var pre = el.getAttribute('data-pre') || '';
    var suf = el.getAttribute('data-suf') || '';
    var n = parseFloat(raw.replace(/,/g, ''));
    if (isNaN(n)) { el.textContent = pre + raw + suf; return; }
    var dur = 1600, start = performance.now();
    (function frame(now) {
      var p = Math.min((now - start) / dur, 1);
      var ease = 1 - Math.pow(1 - p, 3);
      el.textContent = pre + Math.round(n * ease).toLocaleString() + suf;
      if (p < 1) requestAnimationFrame(frame); else el.textContent = pre + raw + suf;
    })(start);
  }

  // ===== SMOOTH ANCHOR SCROLL =====
  document.querySelectorAll('a[href^="#"]').forEach(function (a) {
    a.addEventListener('click', function (e) {
      var id = a.getAttribute('href').slice(1);
      if (!id) return;
      var t = document.getElementById(id);
      if (t) { e.preventDefault(); t.scrollIntoView({ behavior: 'smooth' }); }
    });
  });

  // ===== EMAIL SIGNUP =====
  var forms = document.querySelectorAll('form.signup-form, form[data-signup]');
  forms.forEach(function (form) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var input = form.querySelector('input[type="email"]');
      var msg = form.parentElement.querySelector('.signup-msg') || form.querySelector('.signup-msg');
      if (!input || !msg) return;
      var email = input.value.trim();
      if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
        msg.textContent = 'Please enter a valid email.';
        msg.className = 'signup-msg err';
        return;
      }
      msg.textContent = 'Submitting...';
      msg.className = 'signup-msg';
      fetch('/api/donate/briefing-signup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: email,
          source: location.pathname,
          utm_source: new URLSearchParams(location.search).get('utm_source') || '',
          utm_campaign: new URLSearchParams(location.search).get('utm_campaign') || ''
        })
      })
        .then(function (r) { return r.ok ? r.json() : Promise.reject(r); })
        .then(function () {
          msg.textContent = 'Thanks. Watch your inbox.';
          msg.className = 'signup-msg ok';
          input.value = '';
          ga('email_signup', { source: location.pathname });
        })
        .catch(function () {
          msg.textContent = 'Could not submit. Try again.';
          msg.className = 'signup-msg err';
        });
    });
  });

  // ===== ENDORSEMENT REQUEST FORM =====
  var endForm = document.getElementById('endorsement-form');
  if (endForm) {
    var endMsg = document.getElementById('endorsement-msg');
    endForm.addEventListener('submit', function (e) {
      e.preventDefault();
      var data = {
        name: endForm.querySelector('[name=name]').value.trim(),
        email: endForm.querySelector('[name=email]').value.trim(),
        office: endForm.querySelector('[name=office]').value.trim(),
        party: endForm.querySelector('[name=party]').value,
        message: endForm.querySelector('[name=message]').value.trim()
      };
      if (!data.name || !data.email) {
        endMsg.textContent = 'Name and email are required.';
        endMsg.style.color = 'var(--orange)'; return;
      }
      var btn = endForm.querySelector('button[type=submit]');
      btn.disabled = true;
      endMsg.textContent = 'Submitting...';
      endMsg.style.color = 'var(--text-muted)';
      fetch('/api/donate/endorsement-request', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      })
        .then(function (r) { return r.json().then(function (b) { return r.ok ? b : Promise.reject(b); }); })
        .then(function () {
          endForm.reset();
          endMsg.textContent = 'Thanks. We received your request and will be in touch.';
          endMsg.style.color = 'var(--cyan-deep, #0e7490)';
          if (typeof ga === 'function') ga('endorsement_request', {});
          btn.disabled = false;
        })
        .catch(function (err) {
          endMsg.textContent = (err && err.error) || 'Could not submit. Try again.';
          endMsg.style.color = 'var(--orange)';
          btn.disabled = false;
        });
    });
  }

  // ===== GA4 =====
  function ga(event, params) {
    if (typeof gtag === 'function') gtag('event', event, params);
  }

  var page = location.pathname;

  document.querySelectorAll('a[href^="http"]').forEach(function (a) {
    a.addEventListener('click', function () {
      var url = a.href;
      var type = 'outbound';
      if (/donate|anedot|winred|secure\./i.test(url)) type = 'donate';
      else if (/twitter|x\.com|facebook|instagram|linkedin|youtube/i.test(url)) type = 'social';
      ga('outbound_click', { link_url: url, link_type: type, page: page });
    });
  });

  document.querySelectorAll('.btn').forEach(function (b) {
    b.addEventListener('click', function () {
      ga('cta_click', {
        cta_text: b.textContent.trim().substring(0, 60),
        cta_url: b.href || '',
        page: page
      });
    });
  });

  document.querySelectorAll('.nav-links a').forEach(function (a) {
    a.addEventListener('click', function () {
      ga('nav_click', { nav_item: a.textContent.trim(), from_page: page });
    });
  });

  var depths = {};
  window.addEventListener('scroll', function () {
    var pct = Math.round(window.scrollY / Math.max(document.documentElement.scrollHeight - window.innerHeight, 1) * 100);
    [25, 50, 75, 100].forEach(function (m) {
      if (pct >= m && !depths[m]) {
        depths[m] = true;
        ga('scroll_depth', { depth: m + '%', page: page });
      }
    });
  }, { passive: true });

  [30, 60, 120, 300].forEach(function (s) {
    setTimeout(function () { ga('engaged_time', { seconds: s, page: page }); }, s * 1000);
  });

  ga('page_loaded', {
    page: page,
    referrer: document.referrer || 'direct',
    utm_source: new URLSearchParams(location.search).get('utm_source') || '',
    utm_medium: new URLSearchParams(location.search).get('utm_medium') || '',
    utm_campaign: new URLSearchParams(location.search).get('utm_campaign') || ''
  });

})();
