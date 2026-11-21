(() => {
  let modalMounted = false;

  function setupShell(pageName) {
    const sidebar = document.querySelector('[data-sidebar]');
    const toggle = document.querySelector('[data-sidebar-toggle]');
    const backdrop = document.querySelector('[data-sidebar-backdrop]');

    setActiveNav(pageName);
    mountAccountMenus();
    mountAccountModal();

    if (window.RudoAuth) {
      window.RudoAuth.requireAuth({ redirectTo: 'login.html' }).then(refreshAccountMenus).catch((error) => {
        const notice = document.createElement('p'); notice.className = 'error-state';
        notice.textContent = error.message; document.querySelector('main')?.prepend(notice);
      });
    } else {
      refreshAccountMenus();
    }

    document.querySelectorAll('[data-nav]').forEach((link) => {
      if (link.dataset.nav === pageName) {
        link.classList.add('active');
        link.setAttribute('aria-current', 'page');
      }
    });

    function closeSidebar() {
      if (!sidebar) return;
      sidebar.classList.remove('open');
      if (backdrop) backdrop.classList.remove('show');
      if (toggle) toggle.setAttribute('aria-expanded', 'false');
    }

    function openSidebar() {
      if (!sidebar) return;
      sidebar.classList.add('open');
      if (backdrop) backdrop.classList.add('show');
      if (toggle) toggle.setAttribute('aria-expanded', 'true');
    }

    if (toggle) {
      toggle.addEventListener('click', () => {
        if (sidebar && sidebar.classList.contains('open')) closeSidebar();
        else openSidebar();
      });
    }

    if (backdrop) {
      backdrop.addEventListener('click', closeSidebar);
    }

    document.querySelectorAll('[data-close-sidebar]').forEach((el) => {
      el.addEventListener('click', () => {
        if (window.innerWidth <= 1024) closeSidebar();
      });
    });

    window.addEventListener('resize', () => {
      if (window.innerWidth > 1024) closeSidebar();
    });

    document.addEventListener('click', (event) => {
      const clickedMenu = event.target.closest('[data-account-menu]');
      document.querySelectorAll('[data-account-menu].open').forEach((menu) => {
        if (menu !== clickedMenu) setAccountMenuOpen(menu, false);
      });
    });

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        document.querySelectorAll('[data-account-menu].open').forEach((menu) => setAccountMenuOpen(menu, false));
        closeDeleteModal();
      }
    });

    return { closeSidebar, openSidebar };
  }

  function setActiveNav(pageName) {
    document.querySelectorAll('[data-nav]').forEach((link) => {
      link.classList.toggle('active', link.dataset.nav === pageName);
    });
  }

  function mountAccountMenus() {
    document.querySelectorAll('[data-sidebar] [data-account-menu], [data-shell-account="sidebar"]').forEach((menu) => menu.remove());

    const pageHeader = document.querySelector('.panel-header .conversation-header');
    if (pageHeader && !pageHeader.querySelector('[data-shell-account="header"]')) {
      pageHeader.insertAdjacentHTML('beforeend', accountMenuMarkup('header'));
    }

    const mobileTopbar = document.querySelector('.mobile-topbar');
    if (mobileTopbar && !mobileTopbar.querySelector('[data-shell-account="mobile"]')) {
      mobileTopbar.insertAdjacentHTML('beforeend', accountMenuMarkup('mobile'));
    }

    document.querySelectorAll('[data-account-trigger]').forEach((trigger) => {
      if (trigger.dataset.bound === 'true') return;
      trigger.dataset.bound = 'true';
      trigger.addEventListener('click', (event) => {
        event.stopPropagation();
        const menu = trigger.closest('[data-account-menu]');
        setAccountMenuOpen(menu, !menu.classList.contains('open'));
      });
    });

    document.querySelectorAll('[data-logout]').forEach((button) => {
      if (button.dataset.bound === 'true') return;
      button.dataset.bound = 'true';
      button.addEventListener('click', () => {
        if (window.RudoAuth) window.RudoAuth.signOut('login.html');
        else window.location.href = 'login.html';
      });
    });

    document.querySelectorAll('[data-open-delete-account]').forEach((button) => {
      if (button.dataset.bound === 'true') return;
      button.dataset.bound = 'true';
      button.addEventListener('click', openDeleteModal);
    });
  }

  function accountMenuMarkup(location) {
    return `
      <div class="account-menu compact" data-account-menu data-shell-account="${location}">
        <button class="account-trigger" type="button" data-account-trigger aria-haspopup="true" aria-expanded="false">
          <span class="account-avatar" data-account-avatar>RA</span>
          <span class="account-copy">
            <strong data-account-name>Rudo Admin</strong>
            <span data-account-subtitle>Workspace administrator</span>
          </span>
          <span class="account-caret" aria-hidden="true">v</span>
        </button>
        <div class="account-dropdown" role="menu">
          <a href="profile.html" role="menuitem">View profile</a>
          <a href="settings.html" role="menuitem">Account settings</a>
          <button type="button" role="menuitem" data-logout>Logout</button>
          <button class="danger" type="button" role="menuitem" data-open-delete-account>Delete account</button>
        </div>
      </div>
    `;
  }

  function refreshAccountMenus() {
    const profile = window.RudoAuth ? window.RudoAuth.getProfile() : {
      name: 'Rudo Admin',
      title: 'Workspace Administrator',
      email: 'admin@dawa.health',
      profileImage: 'img/user.jpg'
    };

    document.querySelectorAll('[data-account-name]').forEach((el) => {
      el.textContent = profile.name || 'Rudo Admin';
    });
    document.querySelectorAll('[data-account-subtitle]').forEach((el) => {
      el.textContent = profile.email || profile.title || 'Workspace administrator';
    });
    document.querySelectorAll('[data-account-avatar]').forEach((el) => {
      el.innerHTML = profile.profileImage
        ? `<img src="${escapeAttribute(profile.profileImage)}" alt="">`
        : escapeHtml(initials(profile.name || profile.email));
    });
  }

  function setAccountMenuOpen(menu, isOpen) {
    if (!menu) return;
    menu.classList.toggle('open', isOpen);
    const trigger = menu.querySelector('[data-account-trigger]');
    if (trigger) trigger.setAttribute('aria-expanded', String(isOpen));
  }

  function mountAccountModal() {
    if (modalMounted || document.querySelector('[data-delete-account-modal]')) return;
    modalMounted = true;
    document.body.insertAdjacentHTML('beforeend', `
      <div class="shell-modal-backdrop" data-delete-account-modal hidden>
        <section class="shell-modal" role="dialog" aria-modal="true" aria-labelledby="deleteAccountTitle">
          <button class="modal-close" type="button" data-close-delete-account aria-label="Close delete account dialog">x</button>
          <p class="eyebrow danger">Danger zone</p>
          <h2 id="deleteAccountTitle">Delete account?</h2>
          <p>This permanently removes the signed-in account where Firebase allows it and clears local Rudo profile data on this device. This action is intentionally protected by confirmation.</p>
          <label class="field-label" for="deleteConfirmInput">Type DELETE to confirm</label>
          <input class="control" id="deleteConfirmInput" data-delete-confirm-input autocomplete="off" placeholder="DELETE">
          <div class="form-message error" data-delete-account-message hidden></div>
          <div class="modal-actions">
            <button class="ghost-button" type="button" data-close-delete-account>Cancel</button>
            <button class="button danger-button" type="button" data-confirm-delete-account disabled>Delete account</button>
          </div>
        </section>
      </div>
    `);

    document.querySelectorAll('[data-close-delete-account]').forEach((button) => {
      button.addEventListener('click', closeDeleteModal);
    });

    const modal = document.querySelector('[data-delete-account-modal]');
    const input = document.querySelector('[data-delete-confirm-input]');
    const confirm = document.querySelector('[data-confirm-delete-account]');
    modal.addEventListener('click', (event) => {
      if (event.target === modal) closeDeleteModal();
    });
    input.addEventListener('input', () => {
      confirm.disabled = input.value.trim().toUpperCase() !== 'DELETE';
    });
    confirm.addEventListener('click', confirmDeleteAccount);
  }

  function openDeleteModal() {
    const modal = document.querySelector('[data-delete-account-modal]');
    const input = document.querySelector('[data-delete-confirm-input]');
    const message = document.querySelector('[data-delete-account-message]');
    const confirm = document.querySelector('[data-confirm-delete-account]');
    if (!modal) return;
    modal.hidden = false;
    input.value = '';
    confirm.disabled = true;
    message.hidden = true;
    document.querySelectorAll('[data-account-menu].open').forEach((menu) => setAccountMenuOpen(menu, false));
    setTimeout(() => input.focus(), 40);
  }

  function closeDeleteModal() {
    const modal = document.querySelector('[data-delete-account-modal]');
    if (modal) modal.hidden = true;
  }

  async function confirmDeleteAccount() {
    const confirm = document.querySelector('[data-confirm-delete-account]');
    const message = document.querySelector('[data-delete-account-message]');
    if (!confirm) return;
    confirm.disabled = true;
    confirm.textContent = 'Deleting...';
    try {
      if (window.RudoAuth) await window.RudoAuth.deleteAccount();
      window.location.href = 'login.html';
    } catch (error) {
      message.textContent = error.message || 'Could not delete the account. Please try again.';
      message.hidden = false;
      confirm.disabled = false;
      confirm.textContent = 'Delete account';
    }
  }

  function skeletonLines(count = 3) {
    return `
      <div class="skeleton-state">
        <div class="skeleton-lines">
          ${Array.from({ length: count }, (_, index) => `<div class="skeleton-line${index === count - 1 ? ' short' : ''}"></div>`).join('')}
        </div>
      </div>
    `;
  }

  function stateMarkup(type, title, message, actionLabel = '', actionId = '') {
    const className = type === 'error' ? 'error-state' : 'empty-state';
    const action = actionLabel ? `<button class="ghost-button" type="button" ${actionId ? `id="${escapeAttribute(actionId)}"` : ''}>${escapeHtml(actionLabel)}</button>` : '';
    return `
      <div class="${className}">
        <strong>${escapeHtml(title)}</strong>
        <span>${escapeHtml(message)}</span>
        ${action}
      </div>
    `;
  }

  function escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function escapeAttribute(value) {
    return escapeHtml(value).replace(/`/g, '&#96;');
  }

  function initials(text) {
    const raw = String(text ?? '').replace(/[^\dA-Za-z ]/g, '').trim();
    if (!raw) return 'RA';
    const parts = raw.split(/\s+/).filter(Boolean);
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return `${parts[0][0]}${parts[1][0]}`.toUpperCase();
  }

  window.AdminShell = {
    setupShell,
    escapeHtml,
    initials,
    skeletonLines,
    stateMarkup,
    refreshAccountMenus,
    openDeleteModal
  };
})();
