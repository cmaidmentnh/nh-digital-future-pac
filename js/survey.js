/* NH Digital Future PAC — candidate survey form */
(function () {
  const params = new URLSearchParams(location.search);
  const token = (params.get('t') || '').trim();
  const loading = document.getElementById('survey-loading');
  const errBox = document.getElementById('survey-error');
  const errDetail = document.getElementById('survey-error-detail');
  const already = document.getElementById('survey-already');
  const form = document.getElementById('survey-form');
  const thanks = document.getElementById('survey-thanks');
  const errMsg = document.getElementById('survey-error-msg');
  const submitBtn = document.getElementById('survey-submit');

  const POSITIONS = [
    'Strongly support', 'Support', 'Neutral / undecided',
    'Oppose', 'Strongly oppose', 'Need more information'
  ];

  // Inject radio groups for each pillar
  const pillarKeys = [
    'self_custody', 'zero_tax', 'cbdc',
    'mine_run', 'encryption', 'smart_contracts'
  ];
  document.querySelectorAll('.survey-options').forEach((box, i) => {
    const key = pillarKeys[i];
    if (!key) return;
    POSITIONS.forEach(pos => {
      const id = `${key}__${pos.replace(/\W+/g, '_').toLowerCase()}`;
      const wrapper = document.createElement('label');
      wrapper.className = 'donate-check';
      wrapper.innerHTML =
        `<input type="radio" name="${key}_position" value="${pos}" id="${id}" required>` +
        `<span>${pos}</span>`;
      box.appendChild(wrapper);
    });
  });

  function showError(msg) {
    loading.hidden = true;
    errBox.hidden = false;
    errDetail.textContent = msg || '';
  }

  if (!token) { showError('No survey token in URL.'); return; }

  fetch('/api/donate/survey/info?t=' + encodeURIComponent(token))
    .then(r => r.json().then(b => r.ok ? b : Promise.reject(b)))
    .then(info => {
      loading.hidden = true;
      if (info.completed) { already.hidden = false; return; }
      // Pre-fill personal info
      form.querySelector('[name=name]').value = info.name || '';
      form.querySelector('[name=email]').value = info.email || '';
      form.querySelector('[name=office]').value = info.office || '';
      const partySel = form.querySelector('[name=party]');
      if (info.party) {
        for (const opt of partySel.options) {
          if (opt.value === info.party || opt.text === info.party) {
            partySel.value = opt.value; break;
          }
        }
      }
      form.hidden = false;
    })
    .catch(err => showError((err && err.error) || 'Could not load survey.'));

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    errMsg.style.display = 'none';
    submitBtn.disabled = true;
    submitBtn.textContent = 'Submitting…';

    const fd = new FormData(form);
    const answers = {};
    fd.forEach((v, k) => { answers[k] = v; });

    try {
      const resp = await fetch('/api/donate/survey/submit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, answers }),
      });
      const body = await resp.json();
      if (!resp.ok) throw new Error(body.error || 'Submission failed.');
      form.hidden = true;
      thanks.hidden = false;
      thanks.scrollIntoView({ behavior: 'smooth' });
    } catch (err) {
      errMsg.textContent = err.message || 'Could not submit. Try again.';
      errMsg.style.display = 'block';
      submitBtn.disabled = false;
      submitBtn.textContent = 'Submit Survey';
    }
  });
})();
