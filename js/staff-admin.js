// Staff administration. Every action is re-authorised by the server and inside the database.
(() => {
  const $ = id => document.getElementById(id);
  let data = null, epoch = 0;
  function el(tag, text, cls) { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; }
  function state(message, error = false) { $('page-state').textContent = message; $('page-state').classList.toggle('error', error); }
  function button(label, handler, cls) { const b = el('button', label, cls); b.type = 'button'; b.addEventListener('click', () => run(b, handler)); return b; }
  async function run(control, handler) {
    control.disabled = true;
    try { const message = await handler(); await load(); if (message) state(message); }
    catch (error) { state(error.message, true); }
    finally { control.disabled = false; }
  }
  const post = (path, body) => RudoApi.request(path, { method: 'POST', body: JSON.stringify(body) });
  const facilityLabel = s => (data.facilities.find(f => f.account === s.account && f.facility === s.facility)?.name) || `${s.account} / ${s.facility}`;
  function facilityChecks(container, selected = []) {
    container.replaceChildren();
    data.facilities.forEach(f => {
      const label = el('label'); const box = el('input'); box.type = 'checkbox'; box.dataset.account = f.account; box.dataset.facility = f.facility;
      box.checked = selected.some(s => s.account === f.account && s.facility === f.facility);
      label.append(box, document.createTextNode(f.name)); container.append(label);
    });
  }
  const checked = container => [...container.querySelectorAll('input:checked')].map(b => ({ account: b.dataset.account, facility: b.dataset.facility }));
  function renderRequests() {
    $('requests').replaceChildren();
    if (!data.requests.length) { $('requests').append(el('p', 'No pending sign-ins.', 'empty')); return; }
    data.requests.forEach(r => {
      const row = el('article', undefined, 'row');
      row.append(el('h3', r.email || 'No email on this sign-in'),
        el('p', `${r.provider === 'supabase' ? 'Supabase Auth' : 'Firebase'} sign-in · ${r.email_verified ? 'email verified' : 'EMAIL NOT VERIFIED'} · last seen ${new Date(r.last_seen).toLocaleString()} · ${r.attempts} attempt(s)`));
      const actions = el('div', undefined, 'actions');
      const match = data.invitations.find(i => !i.expired && r.email && i.email === r.email.toLowerCase());
      if (match && r.email_verified) {
        actions.append(button(match.staff_id ? 'Approve: add this login to the existing staff member' : `Approve as ${match.role}`,
          async () => { await post(`/api/admin/invitations/${match.id}/approve`, { issuer: r.issuer, subject: r.subject }); return `${r.email} approved.`; }, 'primary'));
      } else actions.append(el('span', match ? 'Email must be verified before approval.' : 'No pending invitation for this email. Invite it first.', 'pill'));
      actions.append(button('Dismiss', async () => { await post('/api/admin/requests/dismiss', { issuer: r.issuer, subject: r.subject }); return 'Sign-in dismissed.'; }));
      row.append(actions); $('requests').append(row);
    });
  }
  function renderInvitations() {
    $('invitations').replaceChildren();
    data.invitations.forEach(i => {
      const row = el('article', undefined, 'row');
      row.append(el('h3', `Invitation · ${i.email}`),
        el('p', i.staff_id ? 'Adds a new login to an existing staff member.' : `${i.role} · ${i.scopes.map(facilityLabel).join(', ')}`),
        el('p', i.expired ? 'Expired. Revoke and invite again.' : `Expires ${new Date(i.expires_at).toLocaleDateString()}. The person should sign in now; then approve them under Pending sign-ins.`));
      const actions = el('div', undefined, 'actions');
      actions.append(button('Revoke invitation', async () => { await post(`/api/admin/invitations/${i.id}/revoke`, {}); return 'Invitation revoked.'; }, 'danger'));
      row.append(actions); $('invitations').append(row);
    });
  }
  function renderStaff() {
    $('staff').replaceChildren();
    data.staff.forEach(s => {
      const row = el('article', undefined, 'row');
      const title = el('h3', `${s.name || s.email} `); title.append(el('span', s.status, 'pill ' + s.status), document.createTextNode(' '), el('span', s.role, 'pill'));
      row.append(title, el('p', s.email),
        el('p', 'Logins: ' + (s.identities.map(i => `${i.provider === 'supabase' ? 'Supabase Auth' : 'Firebase'}${i.email ? ' (' + i.email + ')' : ''}`).join(', ') || 'none')),
        el('p', 'Facilities: ' + (s.scopes.map(facilityLabel).join(', ') || 'none')));
      if (s.self) { row.append(el('p', 'This is you. Another admin must change your role, status or facilities.')); $('staff').append(row); return; }
      const actions = el('div', undefined, 'actions');
      const role = el('select'); ['operator', 'analyst', 'admin'].forEach(r => role.add(new Option(r, r, false, r === s.role)));
      actions.append(role, button('Change role', async () => { await post(`/api/admin/staff/${s.id}`, { role: role.value }); return 'Role updated.'; }));
      actions.append(s.status === 'active'
        ? button('Suspend', async () => { await post(`/api/admin/staff/${s.id}`, { status: 'suspended' }); return `${s.email} suspended. Access ends on their next request.`; }, 'danger')
        : button('Reactivate', async () => { await post(`/api/admin/staff/${s.id}`, { status: 'active' }); return `${s.email} reactivated.`; }));
      if (!s.identities.some(i => i.provider === 'supabase')) actions.append(button('Invite Supabase login', async () => {
        await post('/api/admin/invitations', { email: s.email, staffId: s.id }); return 'Invitation created for the additional Supabase login.'; }));
      const scopes = el('fieldset'); scopes.append(el('legend', 'Facilities')); const box = el('div', undefined, 'checks'); facilityChecks(box, s.scopes); scopes.append(box);
      row.append(actions, scopes, button('Save facilities', async () => { await post(`/api/admin/staff/${s.id}`, { scopes: checked(box) }); return 'Facilities updated.'; }));
      s.identities.forEach(i => row.append(button(`Remove ${i.provider} login`, async () => {
        await post('/api/admin/identities/unlink', { issuer: i.issuer, subject: i.subject }); return 'Login removed.'; }, 'danger')));
      $('staff').append(row);
    });
  }
  function renderEvents() {
    $('events').replaceChildren();
    data.events.forEach(e => $('events').append(el('li', `${new Date(e.at).toLocaleString()} · ${e.action} · ${e.target}`)));
    if (!data.events.length) $('events').append(el('li', 'No administrative activity yet.'));
  }
  async function load() {
    const current = ++epoch;
    const next = await RudoApi.request('/api/admin/overview');
    if (current !== epoch) return;
    data = next; $('admin').hidden = false;
    const selected = checked($('invite-facilities')); facilityChecks($('invite-facilities'), selected);
    renderRequests(); renderInvitations(); renderStaff(); renderEvents();
    state(`${data.staff.length} staff · ${data.invitations.length} pending invitation(s) · ${data.requests.length} pending sign-in(s).`);
  }
  async function start() {
    data = null; $('admin').hidden = true; state('Verifying staff identity…');
    if (!(await RudoAuth.requireSignedIn())) return;
    try {
      const member = await RudoApi.request('/api/me');
      $('identity').textContent = `${member.displayName || member.email} · ${member.role}`;
      if (member.role !== 'admin') { state('Only admins can manage staff.', true); return; }
      await load();
    } catch (error) { $('admin').hidden = true; state(error.message, true); }
  }
  $('invite').addEventListener('submit', event => { event.preventDefault(); run(event.submitter || $('invite').querySelector('button'), async () => {
    const scopes = checked($('invite-facilities'));
    if (!scopes.length) throw new Error('Choose at least one facility.');
    await post('/api/admin/invitations', { email: $('invite-email').value.trim(), role: $('invite-role').value, scopes });
    const email = $('invite-email').value.trim(); $('invite-email').value = '';
    return `Invitation created for ${email}. Ask them to sign in, then approve them under Pending sign-ins.`;
  }); });
  $('refresh').addEventListener('click', () => run($('refresh'), load));
  $('logout').addEventListener('click', () => RudoAuth.signOut());
  window.addEventListener('rudo-identity-changed', start);
  start();
})();
