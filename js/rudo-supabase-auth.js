// Supabase Auth staff sign-in. Only the browser-safe project URL and anon/publishable key are used;
// they come from /api/auth-config. Staff authority is decided by the server, never by this file.
(() => {
  const LOGIN_PAGE = 'staff-login.html';
  const base = new URL('../', document.currentScript.src);
  let clientPromise, readyPromise, currentUser = null, signingOut = false;

  async function config() {
    const response = await fetch(new URL('api/auth-config', base).href, { credentials: 'omit' });
    if (!response.ok) throw new Error('Sign-in configuration is unavailable.');
    const data = await response.json();
    if (data.provider !== 'supabase' || !data.supabase) throw new Error('Supabase sign-in is not enabled for this workspace.');
    return data.supabase;
  }

  function client() {
    if (!clientPromise) {
      clientPromise = config().then(settings => {
        if (!window.supabase?.createClient) throw new Error('The sign-in library failed to load.');
        const instance = window.supabase.createClient(settings.url, settings.anonKey, {
          auth: { flowType: 'pkce', persistSession: true, autoRefreshToken: true, detectSessionInUrl: true, storageKey: 'rudo-staff-auth' }
        });
        instance.rudoSettings = settings;
        return instance;
      });
      clientPromise.catch(() => { clientPromise = undefined; });
    }
    return clientPromise;
  }

  function wrap(user) {
    if (!user) return null;
    return {
      uid: user.id, email: user.email || null,
      getIdToken: async () => {
        const { data, error } = await (await client()).auth.getSession();
        if (error || !data.session || data.session.user.id !== user.id) throw new Error('Please sign in again.');
        return data.session.access_token;
      }
    };
  }

  async function authReady() {
    if (signingOut) return null;
    if (!readyPromise) {
      readyPromise = client().then(async instance => {
        const { data } = await instance.auth.getSession();
        currentUser = wrap(data.session?.user);
        instance.auth.onAuthStateChange((_event, session) => {
          const next = wrap(session?.user);
          if ((next?.uid || null) !== (currentUser?.uid || null)) {
            currentUser = next;
            window.dispatchEvent(new CustomEvent('rudo-identity-changed'));
          } else currentUser = next;
        });
        return true;
      });
      readyPromise.catch(() => { readyPromise = undefined; });
    }
    await readyPromise;
    if (!currentUser && !signingOut && !location.pathname.endsWith(LOGIN_PAGE)) {
      sessionStorage.setItem('rudoRedirectAfterLogin', (location.pathname.split('/').pop() || 'observer.html') + location.hash);
      location.replace(LOGIN_PAGE);
    }
    return signingOut ? null : currentUser;
  }

  async function signOut(redirectTo = LOGIN_PAGE) {
    signingOut = true;
    window.dispatchEvent(new CustomEvent('rudo-identity-changed'));
    try { await (await client()).auth.signOut(); } catch { /* local session is cleared regardless */ }
    finally { location.href = redirectTo; }
  }

  function redirectAfterLogin() {
    const candidate = sessionStorage.getItem('rudoRedirectAfterLogin') || 'observer.html';
    sessionStorage.removeItem('rudoRedirectAfterLogin');
    location.href = /^observer\.html(#(conversations|orders|referrals|analytics))?$|^staff\.html$/.test(candidate) ? candidate : 'observer.html';
  }

  // Messages never reveal whether an email is registered.
  function friendly(error) {
    const code = error?.code || '';
    const status = error?.status;
    if (code === 'invalid_credentials' || /invalid login credentials/i.test(error?.message || '')) return 'The email or password is incorrect.';
    if (code === 'email_not_confirmed') return 'Confirm your email address using the link we sent, then sign in.';
    if (code === 'weak_password') return 'Choose a stronger password (at least 12 characters).';
    if (code === 'over_request_rate_limit' || code === 'over_email_send_rate_limit' || status === 429) return 'Too many attempts. Please wait before trying again.';
    if (code === 'same_password') return 'Choose a password different from your current one.';
    if (error instanceof TypeError) return 'Network connection failed. Check your connection and try again.';
    return 'Something went wrong. Please try again.';
  }

  const pageUrl = page => new URL(page, base).href;

  window.RudoSupabase = {
    client,
    async signInWithPassword(email, password) {
      const { error } = await (await client()).auth.signInWithPassword({ email, password });
      if (error) throw new Error(friendly(error));
    },
    async signInWithGoogle() {
      const instance = await client();
      if (!instance.rudoSettings.google) throw new Error('Google sign-in is not enabled for this workspace.');
      const { error } = await instance.auth.signInWithOAuth({ provider: 'google', options: { redirectTo: pageUrl('staff-login.html') } });
      if (error) throw new Error(friendly(error));
    },
    // Sign-up creates an identity only. Staff access stays pending until an administrator approves it.
    async requestAccess(email, password) {
      if (password.length < 12) throw new Error('Choose a stronger password (at least 12 characters).');
      const { error } = await (await client()).auth.signUp({ email, password, options: { emailRedirectTo: pageUrl('staff-login.html') } });
      if (error && error.code !== 'user_already_exists') throw new Error(friendly(error));
    },
    async requestPasswordReset(email) {
      const { error } = await (await client()).auth.resetPasswordForEmail(email, { redirectTo: pageUrl('staff-reset.html?mode=update') });
      if (error && (error.status === 429 || /rate/i.test(error.code || ''))) throw new Error(friendly(error));
    },
    async hasRecoverySession() {
      const { data } = await (await client()).auth.getSession();
      return Boolean(data.session);
    },
    async updatePassword(password) {
      if (password.length < 12) throw new Error('Choose a stronger password (at least 12 characters).');
      const { error } = await (await client()).auth.updateUser({ password });
      if (error) throw new Error(friendly(error));
      await (await client()).auth.signOut({ scope: 'others' });
    },
    friendly
  };
  window.RudoAuth = { authReady, requireSignedIn: authReady, signOut, redirectAfterLogin, currentUid: () => currentUser?.uid, provider: 'supabase' };
})();
