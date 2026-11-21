(() => {
  const firebaseConfig = {
    apiKey: 'AIzaSyAVIDHMKVaEUYcV67xJI-DqaOpC8FP8R2M',
    authDomain: 'dawa-ca263.firebaseapp.com',
    projectId: 'dawa-ca263',
    storageBucket: 'dawa-ca263.appspot.com',
    messagingSenderId: '103718044142',
    appId: '1:103718044142:web:f6d166d3d3f95e53c30eff',
    measurementId: 'G-61B20Q72DW'
  };

  const PROFILE_KEY = 'userProfileData';
  function profileKey() { return `${PROFILE_KEY}:${window.firebase?.auth().currentUser?.uid || 'signed-out'}`; }
  const SESSION_KEY = 'rudoSessionActive';
  const REDIRECT_KEY = 'rudoRedirectAfterLogin';

  const defaultProfile = {
    name: 'Rudo Admin',
    title: 'Workspace Administrator',
    role: 'Unverified',
    email: 'admin@dawa.health',
    phone: '+263 77 123 4567',
    bio: 'Managing Rudo conversations, orders, referrals, and healthcare support workflows for the Dawa Health team.',
    linkedin: 'linkedin.com/company/dawa-health',
    github: 'github.com/dawa-health',
    twitter: 'x.com/dawahealth',
    location: 'Lusaka, Zambia',
    timezone: 'Africa/Lusaka',
    profileImage: 'img/user.jpg'
  };

  let authReadyPromise;
  let observedUid;
  let signingOut = false;

  function hasFirebase() {
    return Boolean(window.firebase && window.firebase.initializeApp && window.firebase.auth);
  }

  function initFirebase() {
    if (!hasFirebase()) return null;
    if (!window.firebase.apps.length) {
      window.firebase.initializeApp(firebaseConfig);
    }
    return window.firebase;
  }

  function parseStoredProfile() {
    try {
      return JSON.parse(localStorage.getItem(profileKey()) || '{}');
    } catch (error) {
      return {};
    }
  }

  function saveProfile(profile) {
    const merged = { ...defaultProfile, ...parseStoredProfile(), ...profile };
    localStorage.setItem(profileKey(), JSON.stringify(merged));
    return merged;
  }

  function profileFromUser(user) {
    if (!user) return {};
    return {
      name: user.displayName || user.email?.split('@')[0] || defaultProfile.name,
      email: user.email || defaultProfile.email,
      profileImage: user.photoURL || parseStoredProfile().profileImage || defaultProfile.profileImage
    };
  }

  function getProfile() {
    const user = hasFirebase() ? window.firebase.auth().currentUser : null;
    return { ...defaultProfile, ...parseStoredProfile(), ...profileFromUser(user) };
  }

  function markSignedIn(user) {
    localStorage.setItem(SESSION_KEY, 'true');
    if (user) saveProfile(profileFromUser(user));
  }

  function clearSession() {
    localStorage.removeItem(SESSION_KEY);
    sessionStorage.removeItem(REDIRECT_KEY);
  }

  async function authReady() {
    if (signingOut || !hasFirebase()) return null;
    if (!authReadyPromise) {
      authReadyPromise = new Promise((resolve) => {
        const timer = setTimeout(() => resolve(false), 10000);
        initFirebase();
        window.firebase.auth().onAuthStateChanged((user) => {
          clearTimeout(timer);
          const uid = user?.uid || null;
          if (observedUid !== undefined && observedUid !== uid) {
            if (observedUid) localStorage.removeItem(`${PROFILE_KEY}:${observedUid}`);
            localStorage.removeItem('rudoAccountSettings');
            localStorage.removeItem(SESSION_KEY);
            window.dispatchEvent(new CustomEvent('rudo-identity-changed'));
          }
          observedUid = uid;
          if (user && !signingOut) markSignedIn(user);
          resolve(true);
        }, () => { clearTimeout(timer); resolve(false); });
      });
    }
    const initialized = await authReadyPromise;
    return initialized && !signingOut ? window.firebase.auth().currentUser : null;
  }

  async function requireAuth(options = {}) {
    const user = await authReady();
    if (!user) {
      clearSession();
      sessionStorage.setItem(REDIRECT_KEY, window.location.pathname.split('/').pop() || 'index2.html');
      window.location.replace(options.redirectTo || 'login.html');
      throw new Error('Please sign in to continue.');
    }
    if (window.RudoApi) {
      const staff = await RudoApi.request('/api/me');
      saveProfile({ role: staff.role });
    }
    return user;
  }

      function redirectAfterLogin(defaultTarget = 'index2.html') {
    const candidate = sessionStorage.getItem(REDIRECT_KEY) || defaultTarget;
    const target = /^(index2?|chats|orders|analytics|profile|settings|staff)\.html$|^observer\.html(#(conversations|orders|referrals|analytics))?$/.test(candidate) ? candidate : 'observer.html';
    sessionStorage.removeItem(REDIRECT_KEY);
    window.location.href = target;
  }

  async function signOut(redirectTo = 'login.html') {
    signingOut = true;
    window.dispatchEvent(new CustomEvent('rudo-identity-changed'));
    localStorage.removeItem(profileKey());
    localStorage.removeItem(PROFILE_KEY);
    localStorage.removeItem('rudoAccountSettings');
    clearSession();
    try {
      if (hasFirebase()) {
        initFirebase();
        await window.firebase.auth().signOut();
      }
    } finally {
      window.location.href = redirectTo;
    }
  }

  async function deleteAccount() {
    const firebase = initFirebase();
    const user = firebase?.auth().currentUser;

    if (!user) {
      localStorage.removeItem(profileKey());
      clearSession();
      throw new Error('Please sign in again before deleting your account.');
    }

    try {
      const key = profileKey();
      await user.delete();
      localStorage.removeItem(key);
      clearSession();
      return { ok: true, message: 'Your account has been deleted.' };
    } catch (error) {
      if (error.code === 'auth/requires-recent-login') {
        throw new Error('For safety, please log in again before deleting this account.');
      }
      throw new Error(friendlyAuthError(error.code, error.message));
    }
  }

  function friendlyAuthError(code, fallback = 'Something went wrong. Please try again.') {
    const messages = {
      'auth/email-already-in-use': 'An account with this email already exists. Try logging in instead.',
      'auth/invalid-email': 'Please enter a valid email address.',
      'auth/user-not-found': 'No account was found for that email address.',
      'auth/wrong-password': 'The password is incorrect. Please try again.',
      'auth/invalid-login-credentials': 'The email or password is incorrect.',
      'auth/weak-password': 'Use at least 6 characters for your password.',
      'auth/network-request-failed': 'Network connection failed. Please check your connection and try again.',
      'auth/too-many-requests': 'Too many attempts. Please wait a moment before trying again.',
      'auth/popup-closed-by-user': 'The sign-in window was closed before finishing.',
      'auth/popup-blocked': 'Your browser blocked the sign-in pop-up. Please allow pop-ups and try again.',
      'auth/account-exists-with-different-credential': 'This email already uses a different sign-in method.',
      'auth/requires-recent-login': 'Please log in again before making this account change.'
    };
    return messages[code] || fallback;
  }

  function setButtonLoading(button, isLoading, label) {
    if (!button) return;
    if (isLoading) {
      button.dataset.originalLabel = button.textContent || button.value || '';
      button.disabled = true;
      button.classList.add('is-loading');
      if (button.tagName === 'INPUT') button.value = label || 'Working...';
      else button.textContent = label || 'Working...';
      return;
    }

    button.disabled = false;
    button.classList.remove('is-loading');
    const original = button.dataset.originalLabel;
    if (original) {
      if (button.tagName === 'INPUT') button.value = original;
      else button.textContent = original;
    }
  }

  function showFormMessage(target, message, type = 'info') {
    if (!target) return;
    target.textContent = message;
    target.className = `form-message ${type}`;
    target.hidden = false;
  }

  // Signed-out visitors to protected pages go to the sign-in page and come back afterwards.
  async function requireSignedIn() {
    const user = await authReady();
    if (!user && !signingOut) {
      sessionStorage.setItem(REDIRECT_KEY, (window.location.pathname.split('/').pop() || 'observer.html') + window.location.hash);
      window.location.replace('login.html');
    }
    return user;
  }

  window.RudoAuth = {
    requireSignedIn,
    currentUid: () => (hasFirebase() ? window.firebase.auth().currentUser?.uid : undefined),
    PROFILE_KEY,
    SESSION_KEY,
    defaultProfile,
    initFirebase,
    authReady,
    requireAuth,
    markSignedIn,
    redirectAfterLogin,
    signOut,
    deleteAccount,
    getProfile,
    saveProfile,
    friendlyAuthError,
    setButtonLoading,
    showFormMessage
  };
})();
