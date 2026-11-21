// Behaviour for staff-login.html and staff-reset.html. All feedback uses text nodes.
(() => {
  const $ = id => document.getElementById(id);
  const page = document.body.dataset.page;
  function state(message, kind = '') { $('state').textContent = message; $('state').className = kind; }
  function show(id) { document.querySelectorAll('form').forEach(form => { form.hidden = form.id !== id; }); }
  async function busy(form, task) {
    const buttons = form.querySelectorAll('button'); buttons.forEach(b => { b.disabled = true; });
    try { await task(); } catch (error) { state(error.message, 'error'); } finally { buttons.forEach(b => { b.disabled = false; }); }
  }
  async function login() {
    const instance = await RudoSupabase.client();
    $('google').hidden = !instance.rudoSettings.google;
    if (await RudoAuth.authReady()) { state('Signed in. Opening the staff workspace…', 'ok'); RudoAuth.redirectAfterLogin(); return; }
    show(location.hash === '#request' ? 'request' : 'signin'); state('Sign in with your staff account.');
    $('show-request').addEventListener('click', e => { e.preventDefault(); show('request'); state('Request staff access.'); });
    $('show-signin').addEventListener('click', e => { e.preventDefault(); show('signin'); state('Sign in with your staff account.'); });
    $('signin').addEventListener('submit', e => { e.preventDefault(); busy($('signin'), async () => {
      state('Signing in…'); await RudoSupabase.signInWithPassword($('email').value.trim(), $('password').value);
      $('password').value = ''; state('Signed in. Opening the staff workspace…', 'ok'); RudoAuth.redirectAfterLogin();
    }); });
    $('google').addEventListener('click', () => busy($('signin'), async () => { state('Opening Google sign-in…'); await RudoSupabase.signInWithGoogle(); }));
    $('request').addEventListener('submit', e => { e.preventDefault(); busy($('request'), async () => {
      await RudoSupabase.requestAccess($('request-email').value.trim(), $('request-password').value);
      $('request-password').value = ''; show('signin');
      state('Request received. Confirm your email if asked, then wait for an administrator to approve access. Until then no records are shown.', 'ok');
    }); });
  }
  async function reset() {
    await RudoSupabase.client();
    if (new URLSearchParams(location.search).get('mode') === 'update') {
      if (!(await RudoSupabase.hasRecoverySession())) { show('reset-request'); state('This reset link is invalid or has expired. Request a new one.', 'error'); }
      else { show('reset-update'); state('Choose a new password.'); }
    } else { show('reset-request'); state('Enter your staff email and we will send a reset link.'); }
    $('reset-request').addEventListener('submit', e => { e.preventDefault(); busy($('reset-request'), async () => {
      await RudoSupabase.requestPasswordReset($('reset-email').value.trim());
      state('If that email belongs to a staff account, a reset link is on its way.', 'ok');
    }); });
    $('reset-update').addEventListener('submit', e => { e.preventDefault(); busy($('reset-update'), async () => {
      if ($('new-password').value !== $('confirm-password').value) throw new Error('The passwords do not match.');
      await RudoSupabase.updatePassword($('new-password').value);
      $('new-password').value = $('confirm-password').value = ''; show('none');
      state('Password updated. Other sessions were signed out. Continue to the workspace.', 'ok');
    }); });
  }
  (page === 'login' ? login() : reset()).catch(error => state(error.message, 'error'));
})();
