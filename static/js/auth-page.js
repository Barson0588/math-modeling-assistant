// Auth page scripts (login / register)
(function() {
  const loginForm = document.getElementById('login-form');
  const regForm = document.getElementById('register-form');

  async function api(url, body) {
    const res = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    return { status: res.status, data: await res.json() };
  }

  function setLoading(form, btnId, loading) {
    const btn = document.getElementById(btnId);
    if (!btn) return;
    const text = btn.querySelector('.btn-text');
    const load = btn.querySelector('.btn-loading');
    if (text) text.hidden = loading;
    if (load) load.hidden = !loading;
    btn.disabled = loading;
  }

  async function handleAuth(form, errorId, btnId, url, extraField) {
    const errorEl = document.getElementById(errorId);
    const email = form.querySelector('input[type="email"]').value.trim();
    const password = form.querySelector('input[type="password"]').value;
    const confirmEl = form.querySelector('#reg-confirm');

    if (!email || !password) {
      errorEl.textContent = '请填写邮箱和密码'; errorEl.hidden = false; return;
    }
    if (confirmEl) {
      if (password !== confirmEl.value) {
        errorEl.textContent = '两次密码不一致'; errorEl.hidden = false; return;
      }
      if (password.length < 6) {
        errorEl.textContent = '密码至少 6 位'; errorEl.hidden = false; return;
      }
    }

    setLoading(form, btnId, true);
    errorEl.hidden = true;

    const { status, data } = await api(url, { email, password });
    setLoading(form, btnId, false);

    if (status === 200) {
      // Sync localStorage API key to server
      try {
        const localKey = localStorage.getItem('mma-api-key');
        if (localKey && localKey.startsWith('sk-')) {
          await api('/api/auth/save-key', { api_key: localKey });
        }
      } catch(e) {}

      // Import local history
      try {
        const localHistory = localStorage.getItem('mma-generator-history');
        if (localHistory) {
          await fetch('/api/history/import', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ items: JSON.parse(localHistory) }),
          });
        }
      } catch(e) {}

      window.location.href = '/';
    } else {
      errorEl.textContent = data.error || '操作失败';
      errorEl.hidden = false;
    }
  }

  if (loginForm) {
    loginForm.addEventListener('submit', (e) => {
      e.preventDefault();
      handleAuth(loginForm, 'login-error', 'login-btn', '/api/auth/login');
    });
  }

  if (regForm) {
    regForm.addEventListener('submit', (e) => {
      e.preventDefault();
      handleAuth(regForm, 'reg-error', 'reg-btn', '/api/auth/register');
    });
  }
})();
