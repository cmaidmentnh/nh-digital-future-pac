/* Digital Future NH — embedded Stripe donate form (two-step flow) */
(function () {
  const form = document.getElementById('donate-form');
  if (!form) return;

  console.log('[donate] script loaded');

  // Persist donor fields to localStorage so refreshes don't wipe them.
  const STORAGE_KEY = 'dfnh_donor_v1';
  const PERSISTED_NAMES = [
    'first_name', 'last_name', 'email', 'phone',
    'address1', 'address2', 'city', 'state', 'postal_code', 'country',
    'employer', 'occupation', 'principal_place',
  ];

  function loadDonor() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const data = JSON.parse(raw);
      PERSISTED_NAMES.forEach(name => {
        if (data[name]) {
          const el = form.querySelector(`[name="${name}"]`);
          if (el && !el.value) el.value = data[name];
        }
      });
      console.log('[donate] restored donor info from localStorage');
    } catch (e) { console.warn('[donate] could not restore donor info', e); }
  }

  function saveDonor() {
    try {
      const out = {};
      PERSISTED_NAMES.forEach(name => {
        const el = form.querySelector(`[name="${name}"]`);
        if (el && el.value) out[name] = el.value;
      });
      localStorage.setItem(STORAGE_KEY, JSON.stringify(out));
    } catch (e) { /* quota or disabled */ }
  }

  loadDonor();
  PERSISTED_NAMES.forEach(name => {
    const el = form.querySelector(`[name="${name}"]`);
    if (el) el.addEventListener('input', saveDonor);
  });

  const API_BASE = '/api/donate';
  const submitBtn = document.getElementById('donate-submit');
  const submitAmt = document.getElementById('donate-submit-amount');
  const errorBox = document.getElementById('donate-error');
  const customInput = document.getElementById('donate-custom-amount');
  const successBox = document.getElementById('donate-success');
  const presetButtons = form.querySelectorAll('.donate-amount');

  let baseAmountCents = 0;   // what the donor wants the PAC to receive
  let amountCents = 0;       // what the card is actually charged (includes fee if covered)
  let coverFees = false;
  let stripe = null;
  let elements = null;
  let paymentIntentId = null;
  let mounted = false;
  let mounting = false;
  let updatingAmount = false;
  const coverFeesBox = document.getElementById('donate-cover-fees');
  const feeSummary = document.getElementById('donate-fee-summary');

  // Stripe US card fee: 2.9% + $0.30. Gross-up formula:
  // total = ceil((net + 30) / 0.971); fee = total - net.
  function grossUpForFees(netCents) {
    if (netCents <= 0) return 0;
    return Math.ceil((netCents + 30) / 0.971);
  }
  function recomputeTotal() {
    amountCents = coverFees ? grossUpForFees(baseAmountCents) : baseAmountCents;
    if (!feeSummary) return;
    if (baseAmountCents <= 0) { feeSummary.textContent = ''; return; }
    if (coverFees) {
      const fee = amountCents - baseAmountCents;
      feeSummary.textContent =
        'You will be charged $' + (amountCents / 100).toFixed(2) +
        ' (fee $' + (fee / 100).toFixed(2) + '). PAC receives $' + (baseAmountCents / 100).toFixed(2) + '.';
    } else {
      const estFee = Math.ceil(baseAmountCents * 0.029 + 30);
      const net = baseAmountCents - estFee;
      feeSummary.textContent = 'Without covering: PAC nets ~$' + (net / 100).toFixed(2) + ' after Stripe fees.';
    }
  }

  function showError(msg) {
    errorBox.textContent = msg || '';
    errorBox.style.display = msg ? 'block' : 'none';
  }

  async function syncAmount() {
    recomputeTotal();
    if (baseAmountCents > 0) {
      submitBtn.disabled = false;
      submitAmt.textContent = ' · $' + (amountCents / 100).toLocaleString('en-US',
        { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    } else {
      submitBtn.disabled = true;
      submitAmt.textContent = '';
    }
    if (!mounted) {
      await ensureMount();
    } else if (paymentIntentId && !updatingAmount) {
      updatingAmount = true;
      try {
        const resp = await fetch(API_BASE + '/update-amount', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ payment_intent_id: paymentIntentId, amount_cents: amountCents }),
        });
        if (!resp.ok) throw new Error((await resp.json()).error || 'update-amount failed');
        if (elements && elements.fetchUpdates) await elements.fetchUpdates();
        console.log('[donate] amount updated to', amountCents);
      } catch (e) {
        console.error('[donate] update-amount failed', e);
        showError(e.message || 'Could not update amount.');
      } finally {
        updatingAmount = false;
      }
    }
  }

  function setBaseAmount(cents) {
    baseAmountCents = cents;
    presetButtons.forEach(b => {
      b.classList.toggle('on', parseInt(b.dataset.amount, 10) === cents);
    });
    syncAmount();
  }

  presetButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      customInput.value = '';
      setBaseAmount(parseInt(btn.dataset.amount, 10));
    });
  });

  customInput.addEventListener('input', () => {
    const v = parseFloat(customInput.value);
    presetButtons.forEach(b => b.classList.remove('on'));
    if (isFinite(v) && v > 0) setBaseAmount(Math.round(v * 100));
    else setBaseAmount(0);
  });

  if (coverFeesBox) {
    coverFeesBox.addEventListener('change', () => {
      coverFees = coverFeesBox.checked;
      syncAmount();
    });
  }

  async function ensureMount() {
    if (mounted || mounting) return;
    if (amountCents <= 0) return;
    // capture amount at time of intent creation; later changes go through update-amount
    const intentAmount = amountCents;
    mounting = true;
    showError('');
    console.log('[donate] starting mount, amount=', amountCents);
    try {
      const cfgResp = await fetch(API_BASE + '/config');
      const cfg = await cfgResp.json();
      console.log('[donate] config loaded', cfg.connected_account);

      if (typeof Stripe === 'undefined') throw new Error('Stripe.js failed to load');
      stripe = Stripe(cfg.publishable_key, { stripeAccount: cfg.connected_account });

      const intentResp = await fetch(API_BASE + '/create-intent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          amount_cents: intentAmount,
          utm: window.location.search.replace(/^\?/, '').slice(0, 200),
        }),
      });
      const intentBody = await intentResp.json();
      if (!intentResp.ok) throw new Error(intentBody.error || 'Could not start payment.');
      paymentIntentId = intentBody.payment_intent_id;
      console.log('[donate] PaymentIntent created', paymentIntentId);

      elements = stripe.elements({
        clientSecret: intentBody.client_secret,
        appearance: {
          theme: 'stripe',
          variables: {
            fontFamily: '"Inter", system-ui, sans-serif',
            colorPrimary: '#2563FF',
            colorText: '#0A1128',
            colorDanger: '#b91c1c',
            borderRadius: '0px',
          },
        },
      });

      const paymentEl = elements.create('payment', { layout: 'tabs' });
      paymentEl.on('ready', () => console.log('[donate] payment element ready'));
      paymentEl.on('loaderror', (e) => {
        console.error('[donate] loaderror', e);
        showError((e.error && e.error.message) || 'Payment form failed to load.');
      });
      paymentEl.mount('#payment-element');
      mounted = true;
      console.log('[donate] mounted');
    } catch (e) {
      console.error('[donate] mount failed', e);
      showError(e.message || 'Could not start payment. Refresh and try again.');
      mounting = false;
    }
  }

  // Re-create-intent if the amount changes after mount.
  // (Stripe Element is bound to the original client_secret; if amount
  // changes, we need a fresh intent. Simplest approach: just modify
  // the existing PaymentIntent via stripe.PaymentIntent.update on the
  // server. For now, refresh the page and pick again.)
  // TODO: hook amount changes into a /update-amount endpoint.

  function readDonor() {
    const fd = new FormData(form);
    const data = Object.fromEntries(fd.entries());
    data.amount_cents = amountCents;
    data.payment_intent_id = paymentIntentId;
    data.utm = window.location.search.replace(/^\?/, '').slice(0, 200);
    return data;
  }

  function validateDonorClient() {
    const required = form.querySelectorAll('input[required], select[required]');
    for (const el of required) {
      if (!el.value.trim()) {
        el.focus();
        return el;
      }
    }
    return null;
  }

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    showError('');

    if (amountCents <= 0) { showError('Please pick an amount.'); return; }
    const missing = validateDonorClient();
    if (missing) {
      showError('Please complete: ' + (missing.previousElementSibling?.textContent || missing.name));
      return;
    }
    if (!mounted || !stripe || !elements) {
      showError('Payment is still loading. Please wait a moment and try again.');
      return;
    }

    submitBtn.disabled = true;
    const labelEl = submitBtn.querySelector('.donate-submit-label');
    labelEl.textContent = 'Processing…';

    try {
      // Attach donor info to the PaymentIntent before confirming.
      const updResp = await fetch(API_BASE + '/update-metadata', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(readDonor()),
      });
      const updBody = await updResp.json();
      if (!updResp.ok) throw new Error(updBody.error || 'Could not save donor info.');

      const { error } = await stripe.confirmPayment({
        elements,
        confirmParams: {
          return_url: window.location.origin + '/involved/?donated=1',
          receipt_email: form.querySelector('[name=email]').value,
          payment_method_data: {
            billing_details: {
              name: form.querySelector('[name=first_name]').value + ' ' + form.querySelector('[name=last_name]').value,
              email: form.querySelector('[name=email]').value,
              phone: form.querySelector('[name=phone]').value || undefined,
              address: {
                line1: form.querySelector('[name=address1]').value,
                line2: form.querySelector('[name=address2]').value || undefined,
                city: form.querySelector('[name=city]').value,
                state: form.querySelector('[name=state]').value,
                postal_code: form.querySelector('[name=postal_code]').value,
                country: form.querySelector('[name=country]').value || 'US',
              },
            },
          },
        },
        redirect: 'if_required',
      });
      if (error) throw error;

      form.style.display = 'none';
      successBox.hidden = false;
      successBox.scrollIntoView({ behavior: 'smooth' });
    } catch (err) {
      showError(err.message || 'Payment failed.');
      submitBtn.disabled = false;
      labelEl.textContent = 'Contribute';
    }
  });

  if (new URLSearchParams(window.location.search).get('donated') === '1') {
    form.style.display = 'none';
    successBox.hidden = false;
  }
})();
