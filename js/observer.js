(() => {
  const $ = id => document.getElementById(id);
  const unknown = value => value === null || value === undefined ? 'Unknown / not recorded' : String(value);
  let view = 'conversations', member = null, cursor = null, activeThread = null, historyCursor = null;
  let pageEpoch = 0, threadEpoch = 0, identityEpoch = 0;
  const messages = new Map();
  function text(tag, content, cls) { const node = document.createElement(tag); node.textContent = content; if (cls) node.className = cls; return node; }
  function state(id, message, error = false) { $(id).textContent = message; $(id).classList.toggle('error', error); }
  function clearThread() { ++threadEpoch; activeThread = null; messages.clear(); $('messages').replaceChildren(); $('thread').hidden = true; $('older').hidden = true; $('workspace').classList.remove('has-thread'); }
  function resetData() { ++pageEpoch; clearThread(); cursor = null; $('records').replaceChildren(); $('more').hidden = true; $('updated').textContent = 'No source read completed yet.'; }
  function params(extra = {}) {
    const p = new URLSearchParams({ limit: '25', ...extra });
    if ($('account').value) p.set('account', $('account').value);
    if ($('facility').value) p.set('facility', $('facility').value);
    return p;
  }
  function populateScopes(scopes) {
    for (const [id,key,label] of [['account','account_id','All approved accounts'],['facility','facility_id','All approved facilities']]) {
      $(id).replaceChildren(new Option(label, ''));
      [...new Map(scopes.map(scope => [scope[key], key === 'facility_id' && scope.facility_name ? scope.facility_name : scope[key]])).entries()].forEach(([value, label]) => $(id).add(new Option(label, value)));
    }
  }
  function renderConversation(row) {
    const card = document.createElement('button'); card.type = 'button'; card.className = 'record conversation-card'; card.dataset.id = row.id;
    card.append(text('h3', row.user_id === null ? row.phone : `${row.user_id} · ${row.phone}`),
      text('p', row.preview === null ? 'No captured messages in source.' : row.preview),
      text('p', `Language: ${unknown(row.language)} · Last captured role: ${unknown(row.last_role)}`),
      text('p', `Account ${row.account_id} · Facility ${row.facility_id} · Delivery unknown`, 'metadata'));
    card.addEventListener('click', () => openThread(row)); return card;
  }
  function renderRecord(row) {
    const card = text('article', '', 'record');
    if (view === 'orders') {
      card.append(text('h3', `Order ${row.id} · ${unknown(row.product)}`), text('p', `Status: ${unknown(row.status)} · Quantity: ${unknown(row.quantity)}`),
        text('p', `Source price: ${unknown(row.price)} · Currency is not separately recorded.`));
    } else card.append(text('h3', `Referral ${row.id}`), text('p', `Attribution: ${unknown(row.source)}`));
    card.append(text('p', `Source phone: ${row.phone} · Timestamp: ${unknown(row.created_at)}`),
      text('p', `Account ${row.account_id} · Facility ${row.facility_id}`, 'metadata'));
    return card;
  }
  function renderAnalytics(data) {
    const grid = text('div', '', 'metric-grid');
    const labels = { source_users: 'Source user rows', conversations: 'Mapped conversations', captured_messages: 'Captured message rows', orders: 'Source order rows', referrals: 'Source referral rows' };
    for (const [key,label] of Object.entries(labels)) { const box = text('article', '', 'metric'); box.append(text('span', label), text('strong', String(data.counts[key]))); grid.append(box); }
    $('records').append(grid, text('p', 'Delivery rate, conversion, response time and clinical resolution are unavailable from these source fields.', 'notice'));
  }
  async function loadPage(append = false) {
    const epoch = ++pageEpoch, identity = identityEpoch;
    if (!member) return;
    if (!append) { $('records').replaceChildren(); clearThread(); cursor = null; }
    $('more').hidden = true; state('page-state', 'Loading approved source…'); $('refresh').disabled = true;
    try {
      let data;
      if (view === 'analytics') data = await RudoApi.request('/api/analytics?' + params());
      else {
        const p = params(); if (append && cursor) p.set('cursor', cursor);
        if (view === 'conversations') { p.set('q', $('search').value.trim()); p.set('filter', $('kind').value); }
        if (view === 'orders' && $('status').value.trim()) p.set('status', $('status').value.trim());
        data = await RudoApi.request(`/api/${view}?${p}`);
      }
      if (epoch !== pageEpoch || identity !== identityEpoch) return;
      if (view === 'analytics') { renderAnalytics(data); state('page-state', 'Scoped source counts. Captured history is incomplete.'); }
      else {
        data.items.forEach(row => $('records').append(view === 'conversations' ? renderConversation(row) : renderRecord(row)));
        cursor = data.nextCursor; $('more').hidden = !cursor;
        state('page-state', $('records').children.length ? 'Source records loaded. Read-only access.' : 'No authorized source records match these filters.');
        if (!$('records').children.length) $('records').append(text('p', 'No source records found.', 'empty'));
      }
      $('updated').textContent = `Last successful source read: ${new Date().toISOString()}. Refresh to observe new source writes.`;
    } catch (error) {
      if (epoch !== pageEpoch || identity !== identityEpoch) return;
      // Clear even previously loaded pages; an outage must not look like a successful empty read.
      $('records').replaceChildren(); clearThread(); cursor = null; state('page-state', error.message, true);
      $('updated').textContent = 'Source unavailable. No successful current result is displayed.';
    } finally { if (epoch === pageEpoch) $('refresh').disabled = false; }
  }
  function renderMessages() {
    $('messages').replaceChildren();
    [...messages.values()].sort((a,b) => BigInt(a.id) < BigInt(b.id) ? -1 : 1).forEach(message => {
      const article = text('article', '', 'message ' + (message.role === 'bot' ? 'bot' : 'user')); article.dataset.sourceId = message.id;
      article.append(text('strong', `${message.role === 'bot' ? 'Bot / source' : 'User / source'} · source message ${message.id}`),
        text('p', message.message), text('small', `${unknown(message.timestamp)} · Delivery unknown · Provider ID not recorded`));
      $('messages').append(article);
    });
  }
  async function openThread(row, older = false) {
    const epoch = ++threadEpoch, identity = identityEpoch;
    if (!older) { activeThread = row; historyCursor = null; messages.clear(); $('messages').replaceChildren(); }
    $('thread').hidden = false; $('workspace').classList.add('has-thread'); $('thread-title').textContent = `Captured history · ${row.phone}`;
    state('thread-state', 'Loading captured messages…'); $('older').hidden = true;
    document.querySelectorAll('.conversation-card').forEach(card => card.classList.toggle('selected', card.dataset.id === row.id));
    try {
      const p = new URLSearchParams({ limit: '50' }); if (older && historyCursor) p.set('cursor', historyCursor);
      const result = await RudoApi.request(`/api/conversations/${row.id}?${p}`);
      if (epoch !== threadEpoch || identity !== identityEpoch) return;
      result.messages.forEach(message => messages.set(message.id, message)); historyCursor = result.nextCursor;
      renderMessages(); $('older').hidden = !historyCursor;
      state('thread-state', messages.size ? 'Captured source history. Refresh replaces this view with current source records.' : 'No captured messages in source; other WhatsApp interactions may exist.');
    } catch (error) {
      if (epoch !== threadEpoch || identity !== identityEpoch) return;
      messages.clear(); $('messages').replaceChildren(); historyCursor = null; state('thread-state', error.message, true);
    }
  }
  function selectView() {
    const candidate = location.hash.slice(1); view = ['conversations','orders','referrals','analytics'].includes(candidate) ? candidate : 'conversations';
    if (member?.role === 'analyst' && view !== 'analytics') { location.hash = 'analytics'; return; }
    resetData(); $('page-title').textContent = view[0].toUpperCase() + view.slice(1);
    document.querySelectorAll('[data-view]').forEach(link => { link.classList.toggle('active', link.dataset.view === view); link.hidden = member?.role === 'analyst' && link.dataset.view !== 'analytics'; });
    $('search-label').hidden = $('kind-label').hidden = view !== 'conversations'; $('status-label').hidden = view !== 'orders';
    loadPage();
  }
  async function identify() {
    const epoch = ++identityEpoch; member = null; resetData();
    $('search').value = ''; $('status').value = ''; $('kind').value = 'all';
    $('account').replaceChildren(new Option('All approved accounts', ''));
    $('facility').replaceChildren(new Option('All approved facilities', ''));
    state('page-state', 'Verifying staff identity…');
    if (RudoAuth.requireSignedIn && !(await RudoAuth.requireSignedIn())) return;
    try {
      const nextMember = await RudoApi.request('/api/me'); if (epoch !== identityEpoch) return; member = nextMember;
      $('identity').textContent = `${member.displayName || member.email || member.subject} · ${member.role} · ${member.scopes.length} approved facilit${member.scopes.length === 1 ? 'y' : 'ies'}`;
      $('staff-link').hidden = member.role !== 'admin';
      populateScopes(member.scopes); selectView();
    } catch (error) { if (epoch === identityEpoch) { member = null; state('page-state', error.message, true); $('identity').textContent = 'Staff access unavailable'; } }
  }
  $('filters').addEventListener('submit', event => { event.preventDefault(); loadPage(); });
  $('refresh').addEventListener('click', () => loadPage()); $('more').addEventListener('click', () => loadPage(true));
  $('older').addEventListener('click', () => activeThread && openThread(activeThread, true));
  $('thread-refresh').addEventListener('click', () => activeThread && openThread(activeThread));
  $('logout').addEventListener('click', () => RudoAuth.signOut()); window.addEventListener('hashchange', selectView);
  window.addEventListener('rudo-identity-changed', () => { identify(); });
  if (document.body.dataset.environment === 'synthetic-local') { $('environment').hidden = false; $('environment').textContent = 'Synthetic local environment. Fixture records only; no production data or provider calls.'; }
  identify();
})();
