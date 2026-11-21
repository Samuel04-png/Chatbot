// Explicit loopback synthetic demo only. The normal application refuses to serve this file.
(() => {
  const subject = sessionStorage.getItem('rudoSyntheticIdentity') || 'operator';
  const user = { uid: subject, displayName: `Synthetic ${subject}`, email: `${subject}@example.test`,
    getIdToken: async () => `synthetic:${subject}` };
  const listeners = [];
  const auth = { currentUser: user, onAuthStateChanged(callback) { listeners.push(callback); setTimeout(() => callback(this.currentUser), 0); },
    async signOut() { this.currentUser = null; listeners.forEach(callback => callback(null)); } };
  window.firebase = { apps: [], initializeApp() { this.apps.push({}); }, auth: () => auth };
  window.syntheticSwitchIdentity = (next) => {
    const replacement = next ? { uid: next, getIdToken: async () => `synthetic:${next}` } : null;
    auth.currentUser = replacement; listeners.forEach(callback => callback(replacement));
  };
})();
