// Explicit loopback synthetic demo only. The normal application refuses to serve this file.
(() => {
  const IDENTITIES = [['operator', 'Operator · Facility A'], ['admin', 'Admin · all facilities + Staff'], ['analyst', 'Analyst · analytics only'],
                      ['other', 'Operator · Facility B'], ['empty', 'Operator · no records'], ['unknown', 'Not staff (pending)']];
  const fromUrl = new URLSearchParams(location.search).get('as');
  if (fromUrl && IDENTITIES.some(([id]) => id === fromUrl)) sessionStorage.setItem('rudoSyntheticIdentity', fromUrl);
  const subject = sessionStorage.getItem('rudoSyntheticIdentity') || 'operator';
  const user = { uid: subject, displayName: `Synthetic ${subject}`, email: `${subject}@example.test`,
    getIdToken: async () => `synthetic:${subject}` };
  const listeners = [];
  const auth = { currentUser: user, onAuthStateChanged(callback) { listeners.push(callback); setTimeout(() => callback(this.currentUser), 0); },
    async signOut() { this.currentUser = null; listeners.forEach(callback => callback(null)); } };
  window.firebase = { apps: [], initializeApp() { this.apps.push({}); }, auth: () => auth };
  window.syntheticSwitchIdentity = (next) => {
    if (next) sessionStorage.setItem('rudoSyntheticIdentity', next);
    const replacement = next ? { uid: next, getIdToken: async () => `synthetic:${next}` } : null;
    auth.currentUser = replacement; listeners.forEach(callback => callback(replacement));
  };
  // Always-visible demo banner with an identity picker (no browser console needed).
  function banner() {
    const bar = document.createElement('div');
    bar.setAttribute('role', 'note');
    bar.style.cssText = 'position:sticky;top:0;z-index:1000;display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding:8px 16px;' +
      'background:#fff4ce;color:#3d2e00;border-bottom:1px solid #e0c46c;font:14px/1.4 system-ui,sans-serif';
    const text = document.createElement('strong');
    text.textContent = 'SYNTHETIC DEMO: made-up data, no real patients, no WhatsApp messages are sent.';
    const label = document.createElement('label');
    label.textContent = 'Viewing as ';
    const select = document.createElement('select');
    select.setAttribute('aria-label', 'Demo identity');
    for (const [id, name] of IDENTITIES) {
      const option = document.createElement('option'); option.value = id; option.textContent = name; option.selected = id === subject;
      select.append(option);
    }
    select.addEventListener('change', () => { sessionStorage.setItem('rudoSyntheticIdentity', select.value); location.reload(); });
    label.append(select);
    bar.append(text, label);
    document.body.prepend(bar);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', banner); else banner();
})();
