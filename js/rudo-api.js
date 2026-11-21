(() => {
  let identityGeneration = 0;
  const active = new Set();
  window.addEventListener('rudo-identity-changed', () => { identityGeneration++; active.forEach(controller => controller.abort()); });
  const base = new URL('../', document.currentScript.src);
  const errors = {
    authentication_required: 'Please sign in again.', invalid_identity: 'Please sign in again.',
    staff_required: 'Your account is pending administrator approval. No records are shown until staff access is approved.', role_required: 'Your role does not permit this action.',
    version_conflict: 'This record changed. Refresh before saving again.', remote_database_disabled: 'Remote database access awaits migration review.',
    database_unavailable: 'The database is not configured.', service_unavailable: 'The service is unavailable. Please retry later.',
    audit_unavailable: 'Access audit unavailable. Source data has not been displayed.', observer_read_only: 'This workspace is read-only.',
    origin_denied: 'This site origin is not permitted.', rate_limited: 'Too many requests. Please wait and retry.',
    admin_required: 'Only an active admin can do this.', staff_admin_unavailable: 'Staff management is not configured on this server.',
    email_mismatch: 'The sign-in email does not match the invitation.', email_not_verified: 'That sign-in email is not verified yet.',
    invitation_expired: 'This invitation has expired. Revoke it and invite again.', invitation_not_pending: 'This invitation is no longer pending.',
    scope_not_permitted: 'You can only grant facilities you are assigned to.', scope_required: 'Choose at least one facility.',
    cannot_change_self: 'Another admin must change your own access.', last_admin: 'At least one active admin must remain.',
    staff_exists: 'A staff member with this email already exists.', identity_already_linked: 'That login is already linked to staff.',
    provider_already_linked: 'This staff member already has a login from that provider.', sign_in_required: 'The person must sign in once before approval.',
    invalid_email: 'Enter a valid email address.', invalid_role: 'Choose a valid role.', not_found: 'That record no longer exists.'
  };
  async function request(path, options = {}) {
    if (!path.startsWith('/api/')) throw new Error('Unsupported API path.');
    const generation = identityGeneration;
    const user = await RudoAuth.authReady();
    if (!user) throw new Error('Please sign in to continue.');
    const uid = user.uid;
    const currentUid = () => (RudoAuth.currentUid ? RudoAuth.currentUid() : window.firebase?.auth().currentUser?.uid);
    const unchanged = () => generation === identityGeneration && currentUid() === uid;
    const token = await user.getIdToken();
    if (!unchanged()) throw new Error('Identity changed. Sign in again.');
    const controller = new AbortController();
    active.add(controller);
    const timer = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch(new URL(path.slice(1), base).href, {
        ...options, signal: controller.signal, credentials: 'omit',
        headers: { ...options.headers, Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }
      });
      const data = await response.json();
      if (!unchanged()) throw new Error('Identity changed. Refresh staff access.');
      if (!response.ok) {
        const error = new Error(errors[data.error] || `The request failed (${response.status}).`);
        error.code = data.error; error.status = response.status; throw error;
      }
      return data;
    } finally { clearTimeout(timer); active.delete(controller); }
  }
  async function all(path) {
    const items = [];
    for (let offset = 0; offset < 10000; offset += 100) {
      const result = await request(`${path}?limit=100&offset=${offset}`);
      items.push(...result.items);
      if (result.items.length < 100) return items;
    }
    throw new Error('This dataset requires a narrower server report; no partial totals are displayed.');
  }
  window.RudoApi = { request, all };
})();
