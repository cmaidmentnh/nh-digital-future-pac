/* Digital Future NH — embedded Stripe donate form */
(function () {
  const form = document.getElementById('donate-form');
  if (!form) return;

  const API_BASE = '/api/donate';
  const submitBtn = document.getElementById('donate-submit');
  const submitAmt = document.getElementById('donate-submit-amount');
  const errorBox = document.getElementById('donate-error');
  const customInput = document.getElementById('donate-custom-amount');
  const successBox = document.getElementById('donate-success');
  const presetButtons = form.querySelectorAll('.donate-amount');

  let amountCents = 0;
  let stripe = null;
  let elements = null;
  let clientSecret = null;
  let paymentIntentId = null;
  let mounted = false;
  let mounting = false;

  function setAmount(cents) {
    amountCents = cents;
    presetButtons.forEach(b => {
      b.classList.toggle('on', parseInt(b.dataset.amount, 10) === cents);
    });
    if (cents > 0) {
      submitBtn.disabled = false;
      submitAmt.textContent = ' · $' + (cents / 100).toLocaleString('en-US', { minimumFractionDigits: 0 });
    } else {
      submitBtn.disabled = true;
      submitAmt.textContent = '';
    }
  }

  presetButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      customInput.value = '';
      setAmount(parseInt(btn.dataset.amount, 10));
    });
  });

  customInput.addEventListener('input', () => {
    const v = parseFloat(customInput.value);
    if (isFinite(v) && v > 0) {
      setAmount(Math.round(v * 100));
    } else {
      setAmount(0);
    }
    presetButtons.forEach(b => b.classList.remove('on'));
  });

  function showError(msg) {
    errorBox.textContent = msg || '';
    errorBox.style.display = msg ? 'block' : 'none';
  }

  function readDonor() {
    const fd = new FormData(form);
    const data = Object.fromEntries(fd.entries());
    data.amount_cents = amountCents;
    data.utm = window.location.search.replace(/^\?/, '').slice(0, 200);
    return data;
  }

  function ensureFilled() {
    const required = form.querySelectorAll('input[required], select[required]');
    for (const el of required) {
      if (el.type === 'checkbox') {
        if (!el.checked) { el.focus(); return false; }
      } else if (!el.value.trim()) {
        el.focus(); return false;
      }
    }
    return amountCents > 0;
  }

  async function ensureMount() {
    if (mounted || mounting) return;
    if (!ensureFilled()) return;
    mounting = true;
    showError('');
    try {
      const cfg = await fetch(API_BASE + '/config').then(r => r.json());
      stripe = Stripe(cfg.publishable_key, { stripeAccount: cfg.connected_account });

      const resp = await fetch(API_BASE + '/create-intent', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(readDonor()),
      });
      const body = await resp.json();
      if (!resp.ok) throw new Error(body.error || 'Could not start payment.');
      clientSecret = body.client_secret;
      paymentIntentId = body.payment_intent_id;

      elements = stripe.elements({
        clientSecret,
        appearance: {
          theme: 'flat',
          variables: {
            fontFamily: '"Inter", system-ui, sans-serif',
            colorPrimary: '#2563FF',
            colorBackground: '#ffffff',
            colorText: '#0A1128',
            colorDanger: '#b91c1c',
            borderRadius: '0px',
            spacingUnit: '4px',
          },
          rules: {
            '.Input': {
              border: '1px solid #d1d5db',
              boxShadow: 'none',
              padding: '12px',
            },
            '.Input:focus': {
              border: '1px solid #2563FF',
              boxShadow: '0 0 0 1px #2563FF',
            },
            '.Label': {
              fontFamily: '"JetBrains Mono", ui-monospace, monospace',
              fontSize: '11px',
              letterSpacing: '0.06em',
              textTransform: 'uppercase',
              color: '#4b5566',
            },
          },
        },
      });

      const paymentEl = elements.create('payment');
      paymentEl.mount('#payment-element');
      mounted = true;
    } catch (e) {
      showError(e.message || 'Could not start payment. Please refresh and try again.');
    } finally {
      mounting = false;
    }
  }

  // Mount the Stripe element as soon as donor info + amount are filled.
  form.addEventListener('change', ensureMount);
  form.addEventListener('blur', ensureMount, true);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    showError('');
    if (!ensureFilled()) {
      showError('Please complete all required fields.');
      return;
    }
    if (!mounted) await ensureMount();
    if (!stripe || !elements) {
      showError('Payment is still loading. Please try again in a moment.');
      return;
    }
    submitBtn.disabled = true;
    submitBtn.querySelector('.donate-submit-label').textContent = 'Processing…';
    const { error } = await stripe.confirmPayment({
      elements,
      confirmParams: {
        return_url: window.location.origin + '/involved/?donated=1',
        receipt_email: form.querySelector('[name=email]').value,
      },
      redirect: 'if_required',
    });
    if (error) {
      showError(error.message || 'Payment failed.');
      submitBtn.disabled = false;
      submitBtn.querySelector('.donate-submit-label').textContent = 'Contribute';
      return;
    }
    form.style.display = 'none';
    successBox.hidden = false;
    successBox.scrollIntoView({ behavior: 'smooth' });
  });

  // If returning from an off-site authentication, show success state.
  if (new URLSearchParams(window.location.search).get('donated') === '1') {
    form.style.display = 'none';
    successBox.hidden = false;
  }
})();
