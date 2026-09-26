


// ================= AUDIO ENGINE (SYNTHESIZED) =================
let audioCtx = null;
function getAudioContext() { if (!audioCtx && (window.AudioContext || window.webkitAudioContext)) { try { const Ctor = window.AudioContext || window.webkitAudioContext; audioCtx = new Ctor(); } catch (e) { } } return audioCtx; }
const NOTIFICATIONS_ENABLED = document.documentElement.dataset.notifications !== "off";

function playBlip() {
    if (!NOTIFICATIONS_ENABLED) return;
    if (audioCtx.state === 'suspended') audioCtx.resume();
    const osc = audioCtx.createOscillator();
    const gainNode = audioCtx.createGain();

    osc.type = 'sine'; // રોબોટિક બીપ
    osc.frequency.setValueAtTime(880, audioCtx.currentTime); // હાઈ પીચ
    osc.frequency.exponentialRampToValueAtTime(1760, audioCtx.currentTime + 0.1);

    gainNode.gain.setValueAtTime(0.1, audioCtx.currentTime);
    gainNode.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.1);

    osc.connect(gainNode);
    gainNode.connect(audioCtx.destination);
    osc.start();
    osc.stop(audioCtx.currentTime + 0.1);
}



// ================= SYSTEM BOOT ANIMATION (ULTRA SMART) =================
document.addEventListener("DOMContentLoaded", () => {
    const bootScreen = document.getElementById('boot-screen');
    const terminal = document.getElementById('terminal-output');
    const cursor = document.getElementById('boot-cursor');

    // ૧. બ્રાઉઝરનું નેવિગેશન ચેક કરો (લિંક ક્લિક કરી છે કે રિફ્રેશ માર્યું છે?)
    const navEntries = performance.getEntriesByType("navigation");
    const isReload = navEntries.length > 0 && navEntries[0].type === "reload";

    // ૨. સેશન ચેક કરો
    const isFirstBoot = !sessionStorage.getItem('simba_booted');

    // ૩. 🚀 મેઈન ફિક્સ: જો યુઝરે ખાલી ચેટ બદલી હોય, તો બૂટ સ્ક્રીન તરત ગાયબ! 🚀
    if (!isFirstBoot && !isReload) {
        bootScreen.style.display = 'none';
        // Don't return, continue to set up mobile menu
    }

    let bootLines = [];

    if (isFirstBoot) {
        // પહેલી વાર માટે આખો કમાન્ડ સેટ
        bootLines = [
            "INITIALIZING SIMBA_INTEL KERNEL V3.0...",
            "ESTABLISHING SECURE UPLINK...",
            "ACCESS GRANTED.",
            "SYSTEM ONLINE."
        ];
        sessionStorage.setItem('simba_booted', 'true');
    } else if (isReload) {
        // માત્ર હાર્ડ રિફ્રેશ (F5) પર જ આ શોર્ટ બૂટ આવશે
        bootLines = [
            "INITIALIZING SIMBA_INTEL KERNEL V3.0...",
            "RESTORING PREVIOUS SECURE SESSION...",
            "SYSTEM ONLINE."
        ];
    }

    let lineIndex = 0;

    function typeLine() {
        if (lineIndex < bootLines.length) {
            cursor.style.display = 'none';
            const lineElement = document.createElement('div');
            lineElement.className = 'boot-line';
            terminal.appendChild(lineElement);

            let charIndex = 0;
            const text = bootLines[lineIndex];

            const typeSpeed = isFirstBoot ? 10 : 10;

            const typingInterval = setInterval(() => {
                lineElement.textContent += text[charIndex];
                charIndex++;

                if (charIndex >= text.length) {
                    clearInterval(typingInterval);
                    lineIndex++;
                    cursor.style.display = 'inline-block';

                    const delay = isFirstBoot ? (Math.random() * 50 + 10) : 100;
                    setTimeout(typeLine, delay);
                }
            }, typeSpeed);
        } else {
            setTimeout(() => {
                bootScreen.style.opacity = 0;
                setTimeout(() => {
                    bootScreen.style.display = 'none';
                }, 800);
            }, isFirstBoot ? 300 : 300);
        }
    }

    if (isFirstBoot || isReload) {
        setTimeout(typeLine, 500);
    }

    // ================= MOBILE MENU TOGGLE =================
    const mobileMenuBtn = document.getElementById("mobile-menu-btn");
    const mobileCloseBtn = document.getElementById("mobile-close-btn");
    const mobileOverlay = document.getElementById("mobile-overlay");
    const sidebar = document.getElementById("sidebar");

    function openMobileMenu() {
        sidebar.classList.add("mobile-open");
        mobileOverlay.classList.add("show");
        mobileMenuBtn.style.display = "none";
    }

    function closeMobileMenu() {
        sidebar.classList.remove("mobile-open");
        mobileOverlay.classList.remove("show");
        mobileMenuBtn.style.display = "flex";
    }

    function toggleMobileMenu() {
        if (sidebar.classList.contains("mobile-open")) {
            closeMobileMenu();
        } else {
            openMobileMenu();
        }
    }

    // Hamburger button to open
    if (mobileMenuBtn) {
        mobileMenuBtn.addEventListener("click", openMobileMenu);
    }

    // Close button to close
    if (mobileCloseBtn) {
        mobileCloseBtn.addEventListener("click", closeMobileMenu);
    }

    // Overlay click to close
    if (mobileOverlay) {
        mobileOverlay.addEventListener("click", closeMobileMenu);
    }

    // ESC key to close
    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && sidebar.classList.contains("mobile-open")) {
            closeMobileMenu();
        }
    });

    // Close menu when a chat item is clicked
    const chatLinks = document.querySelectorAll(".chat-link");
    chatLinks.forEach(link => {
        link.addEventListener("click", () => {
            if (window.innerWidth <= 767) {
                closeMobileMenu();
            }
        });
    });
});




const csrfToken = document.getElementById("csrf-token").value;

// ================= No-reload chat-list actions (Part 1) =================
// What page we're currently looking at - every sidebar mutation
// (pin/favorite/archive/folder change) needs this to decide whether
// a chat still belongs where it's currently rendered, without ever
// asking the server via a reload.
const CHAT_VIEW_MODE = "active";
const CHAT_FOLDER_FILTER = "";
const CHAT_DATE_GROUP_LABELS = { today: 'Today', yesterday: 'Yesterday', week: 'Last 7 Days', month: 'Last 30 Days', older: 'Older' };
const CHAT_DATE_GROUP_ORDER = ['today', 'yesterday', 'week', 'month', 'older'];

function getChatRow(id) {
    return document.querySelector(`.chat-item-container[data-session-id="${id}"]`);
}

function calculateDateGroup(isoString) {
    if (!isoString) return 'today';
    const d = new Date(isoString);
    if (isNaN(d.getTime())) return 'today';
    const now = new Date();
    const dDay = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    const nowDay = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const diffTime = nowDay.getTime() - dDay.getTime();
    const diffDays = Math.round(diffTime / (1000 * 60 * 60 * 24));

    if (diffDays <= 0) return 'today';
    if (diffDays === 1) return 'yesterday';
    if (diffDays < 7) return 'week';
    if (diffDays < 30) return 'month';
    return 'older';
}

function insertRowInOrder(container, row) {
    if (!container || !row) return;
    const rowTime = new Date(row.dataset.createdAt || 0).getTime();
    const existing = Array.from(container.querySelectorAll('.chat-item-container'));
    for (const other of existing) {
        if (other === row) continue;
        const otherTime = new Date(other.dataset.createdAt || 0).getTime();
        if (rowTime > otherTime) {
            container.insertBefore(row, other);
            return;
        }
    }
    container.appendChild(row);
}

function chatRowBelongsInCurrentView(row) {
    const archived = row.dataset.archived === '1';
    const wantArchived = CHAT_VIEW_MODE === 'archived';
    if (archived !== wantArchived) return false;
    if (CHAT_FOLDER_FILTER && row.dataset.folder !== CHAT_FOLDER_FILTER) return false;
    return true;
}

// Lazily creates the "FAVORITES" label + container the first time a
// chat is favorited in a session that started with none - both are
// conditionally rendered server-side (only when favorite_sessions
// is non-empty), so they may simply not exist in the DOM yet.
function ensureFavoritesSection() {
    let container = document.getElementById('favorite-chats');
    if (container) return container;
    const liveList = document.getElementById('live-chat-list');
    if (!liveList || !liveList.parentNode) return null;
    const label = document.createElement('div');
    label.className = 'chat-section-label';
    label.id = 'favorites-section-label';
    label.innerHTML = '<i class="fa-solid fa-star"></i> FAVORITES';
    container = document.createElement('div');
    container.id = 'favorite-chats';
    liveList.parentNode.insertBefore(label, liveList);
    liveList.parentNode.insertBefore(container, liveList);
    return container;
}

// Same idea for a date-group bucket that's currently empty/absent
// (e.g. the first "Today" chat of the day, or unpinning a chat back
// into a group that isn't rendered yet) - created in the right sort
// position among whichever other groups already exist.
function getDateGroupContainer(groupKey) {
    const list = document.getElementById('live-chat-list');
    if (!list) return null;
    let group = list.querySelector(`.chat-date-group[data-group="${groupKey}"]`);
    if (group) return group;
    group = document.createElement('div');
    group.className = 'chat-date-group';
    group.dataset.group = groupKey;
    const header = document.createElement('div');
    header.className = 'chat-date-header';
    header.textContent = CHAT_DATE_GROUP_LABELS[groupKey] || groupKey;
    group.appendChild(header);
    const idx = CHAT_DATE_GROUP_ORDER.indexOf(groupKey);
    let inserted = false;
    for (const existing of Array.from(list.querySelectorAll('.chat-date-group'))) {
        if (CHAT_DATE_GROUP_ORDER.indexOf(existing.dataset.group) > idx) {
            list.insertBefore(group, existing);
            inserted = true;
            break;
        }
    }
    if (!inserted) list.appendChild(group);
    return group;
}

function ensureChatListEmptyState() {
    const list = document.getElementById('live-chat-list');
    if (!list) return;
    const hasAny = document.querySelectorAll(
        '#pinned-chats .chat-item-container, #favorite-chats .chat-item-container, #live-chat-list .chat-item-container'
    ).length > 0;
    let empty = list.querySelector('.chat-list-empty');
    if (!hasAny && !empty) {
        const isArchivedView = CHAT_VIEW_MODE === 'archived';
        empty = document.createElement('div');
        empty.className = 'chat-list-empty';
        empty.innerHTML = `<i class="fa-solid ${isArchivedView ? 'fa-box-open' : 'fa-comments'}"></i><span>${isArchivedView ? 'No archived conversations.' : 'No conversations yet - start one below.'}</span>`;
        list.appendChild(empty);
    } else if (hasAny && empty) {
        empty.remove();
    }
}

// Call after ANY structural change to the chat list (move/remove/
// insert a row) - prunes now-empty sections, keeps pagination and
// the empty-state message in sync. Idempotent, cheap to call often.
function refreshChatListChrome() {
    const favContainer = document.getElementById('favorite-chats');
    if (favContainer && favContainer.children.length === 0) {
        document.getElementById('favorites-section-label')?.remove();
        favContainer.remove();
    }
    document.querySelectorAll('#live-chat-list .chat-date-group').forEach(group => {
        if (group.querySelectorAll('.chat-item-container').length === 0) group.remove();
    });
    ensureChatListEmptyState();
    if (typeof updateChatListDisplay === 'function') updateChatListDisplay();
}

// Moves a row into whichever section its CURRENT data attributes say
// it belongs in (pinned > favorite > date group), or removes it
// entirely if it no longer belongs in the current view/folder at
// all. Every toggle function below updates the row's dataset FIRST,
// then calls this - one place decides placement, so the rules for
// "where does this row go" only ever exist once.
function moveRowToCorrectSection(row) {
    if (!chatRowBelongsInCurrentView(row)) {
        row.remove();
        refreshChatListChrome();
        return;
    }
    const pinned = row.dataset.pinned === '1';
    const favorite = row.dataset.favorite === '1';
    let target;
    if (pinned) {
        target = document.getElementById('pinned-chats');
    } else if (favorite) {
        target = ensureFavoritesSection();
    } else {
        target = getDateGroupContainer(calculateDateGroup(row.dataset.createdAt));
    }
    if (target && target !== row.parentElement) {
        insertRowInOrder(target, row);
    }
    refreshChatListChrome();
}

// Rebuilds a row's status-icon cluster + dropdown menu labels from
// its OWN data attributes - the single source of truth every toggle
// function updates first, so the visible icons/menu text can never
// drift out of sync with what the row's dataset says is true.
function refreshRowFromData(row) {
    const pinned = row.dataset.pinned === '1';
    const favorite = row.dataset.favorite === '1';
    const archived = row.dataset.archived === '1';
    const color = row.dataset.color;
    const folder = row.dataset.folder;

    const iconsEl = row.querySelector('.chat-row-icons');
    if (iconsEl) {
        let html = '';
        if (color) html += `<span class="chat-color-dot chat-color-${color}"></span>`;
        if (pinned) html += `<i class="fa-solid fa-thumbtack chat-pin-icon" title="Pinned"></i>`;
        if (favorite) html += `<i class="fa-solid fa-star chat-favorite-icon" title="Favorite"></i>`;
        if (folder) html += `<i class="fa-solid fa-folder chat-folder-icon" title="${escapeHtml(folder)}"></i>`;
        iconsEl.innerHTML = html;
    }

    const pinLabel = row.querySelector('.js-pin-label');
    if (pinLabel) pinLabel.textContent = pinned ? 'Unpin' : 'Pin';
    const favLabel = row.querySelector('.js-favorite-label');
    if (favLabel) favLabel.textContent = favorite ? 'Unfavorite' : 'Favorite';
    const archLabel = row.querySelector('.js-archive-label');
    if (archLabel) archLabel.textContent = archived ? 'Unarchive' : 'Archive';

    const link = row.querySelector('.chat-link');
    if (link) link.setAttribute('href', `/?session=${row.dataset.sessionId}${archived ? '&view=archived' : ''}`);

    const folderMenuLink = row.querySelector(`#drop-${row.dataset.sessionId} a[onclick^="promptSetFolder"]`);
    if (folderMenuLink) {
        folderMenuLink.setAttribute('onclick', `promptSetFolder('${row.dataset.sessionId}', '${(folder || '').replace(/'/g, "\\'")}')`);
    }
}

// Re-renders the folder chip strip from the server (Part 1) - the
// count/colour/existence of a folder can be affected by an action
// on ANY chat, so recomputing it in JS would just be a second,
// easy-to-drift copy of _compute_folders_for_user's own logic.
function renderFolderChipHTML(f) {
    const activeClass = CHAT_FOLDER_FILTER === f.name ? 'active' : '';
    const dotClass = f.color ? `chat-color-${f.color}` : 'folder-chip-dot-none';
    const nameEsc = escapeHtml(f.name);
    return `
                <div class="folder-chip-wrap">
                    <a href="/?view=${CHAT_VIEW_MODE}&folder=${encodeURIComponent(f.name)}" class="folder-chip ${activeClass}"
                       oncontextmenu="return openFolderMenu(event, '${nameEsc}', '${f.color}')">
                        <span class="folder-chip-dot ${dotClass}"></span>
                        ${nameEsc}
                        ${f.count ? `<span class="folder-chip-count">${f.count}</span>` : ''}
                    </a>
                    <button type="button" class="folder-chip-menu-btn" onclick="openFolderMenuFromBtn(event, this, '${nameEsc}', '${f.color}')" title="Folder options"><i class="fa-solid fa-ellipsis"></i></button>
                </div>`;
}

function refreshFolderChipsFromServer() {
    fetch("/folders/summary/", { signal: AbortSignal.timeout(8000) })
        .then(res => res.json())
        .then(data => {
            const section = document.querySelector('.folder-section');
            if (!section) return;
            const folders = data.folders || [];
            let chipsContainer = section.querySelector('.folder-chips');
            let emptyHint = section.querySelector('.folder-empty-hint');
            if (!folders.length) {
                chipsContainer?.remove();
                if (!emptyHint) {
                    emptyHint = document.createElement('div');
                    emptyHint.className = 'folder-empty-hint';
                    emptyHint.textContent = "No folders yet. Use a chat's menu → Set Folder, or the + above.";
                    section.appendChild(emptyHint);
                }
                return;
            }
            emptyHint?.remove();
            if (!chipsContainer) {
                chipsContainer = document.createElement('div');
                chipsContainer.className = 'folder-chips';
                section.appendChild(chipsContainer);
            }
            const allActive = !CHAT_FOLDER_FILTER ? 'active' : '';
            chipsContainer.innerHTML =
                `<a href="/?view=${CHAT_VIEW_MODE}" class="folder-chip ${allActive}"><i class="fa-solid fa-layer-group"></i> All</a>` +
                folders.map(renderFolderChipHTML).join('');
        })
        .catch(() => { });
}

// Updates every row currently filed under `oldName` to `newName` -
// used after a folder rename, which can affect many chats at once.
function relabelRowsInFolder(oldName, newName) {
    document.querySelectorAll('.chat-item-container').forEach(row => {
        if (row.dataset.folder !== oldName) return;
        row.dataset.folder = newName;
        refreshRowFromData(row);
    });
}

// Unfiles every row currently in `name` - used after a folder
// delete, which never deletes the chats themselves (see
// delete_folder's own docstring), only their folder membership.
function unfileRowsInFolder(name) {
    document.querySelectorAll('.chat-item-container').forEach(row => {
        if (row.dataset.folder !== name) return;
        row.dataset.folder = '';
        refreshRowFromData(row);
        moveRowToCorrectSection(row);
    });
}

// ================= Sidebar conversation search (client-side filter) =================
// ================= Conversation list: search + pagination =================
// Pinned chats are always shown in full (they're meant to be a small
// quick-access set). The unpinned list is paginated at CHAT_PAGE_SIZE;
// while a search query is active, pagination is bypassed entirely so
// search always reaches every conversation, not just the current page.
const CHAT_PAGE_SIZE = 10;
let chatListPage = 1;

function getLiveChatRows() {
    return Array.from(document.querySelectorAll('#live-chat-list .chat-item-container'));
}

function updateDateGroupHeaderVisibility() {
    document.querySelectorAll('#live-chat-list .chat-date-group').forEach(group => {
        const anyVisible = Array.from(group.querySelectorAll('.chat-item-container')).some(r => r.style.display !== 'none');
        const header = group.querySelector('.chat-date-header');
        if (header) header.style.display = anyVisible ? '' : 'none';
        group.style.display = anyVisible ? '' : 'none';
    });
}

function renderPageNumberButtons(currentPage, totalPages) {
    let pages = [];
    if (totalPages <= 7) {
        for (let i = 1; i <= totalPages; i++) pages.push(i);
    } else {
        pages.push(1);
        let start = Math.max(2, currentPage - 1);
        let end = Math.min(totalPages - 1, currentPage + 1);
        if (start > 2) pages.push('...');
        for (let i = start; i <= end; i++) pages.push(i);
        if (end < totalPages - 1) pages.push('...');
        pages.push(totalPages);
    }
    return pages.map(p => {
        if (p === '...') {
            return `<span class="page-btn page-ellipsis" style="cursor:default;opacity:0.5;border:none;padding:4px 2px;">…</span>`;
        }
        return `<button type="button" class="page-btn page-num ${p === currentPage ? 'active' : ''}" onclick="goToChatPage(${p})">${p}</button>`;
    }).join('');
}

function updateChatListDisplay() {
    const searchInput = document.getElementById('chat-search-input');
    const query = (searchInput ? searchInput.value : '').trim().toLowerCase();
    const pinnedRows = Array.from(document.querySelectorAll('#pinned-chats .chat-item-container'));
    const favoriteRows = Array.from(document.querySelectorAll('#favorite-chats .chat-item-container'));
    const liveRows = getLiveChatRows();
    const pager = document.getElementById('chatPagination');

    if (query) {
        pinnedRows.forEach(row => {
            const text = (row.querySelector('.chat-link-title')?.textContent || row.innerText || '').toLowerCase();
            row.style.display = text.includes(query) ? '' : 'none';
        });
        favoriteRows.forEach(row => {
            const text = (row.querySelector('.chat-link-title')?.textContent || row.innerText || '').toLowerCase();
            row.style.display = text.includes(query) ? '' : 'none';
        });

        const matchingLiveRows = liveRows.filter(row => {
            const text = (row.querySelector('.chat-link-title')?.textContent || row.innerText || '').toLowerCase();
            return text.includes(query);
        });

        const totalPages = Math.max(1, Math.ceil(matchingLiveRows.length / CHAT_PAGE_SIZE));
        chatListPage = Math.min(Math.max(1, chatListPage), totalPages);

        liveRows.forEach(row => { row.style.display = 'none'; });
        matchingLiveRows.forEach((row, i) => {
            const page = Math.floor(i / CHAT_PAGE_SIZE) + 1;
            row.style.display = page === chatListPage ? '' : 'none';
        });
        updateDateGroupHeaderVisibility();

        if (!pager) return;
        if (matchingLiveRows.length === 0) {
            pager.innerHTML = '';
            return;
        }
        if (totalPages === 1) {
            pager.innerHTML = '<div class="page-numbers"><button type="button" class="page-btn page-num active" disabled>1</button></div>';
            return;
        }
        let html = `<button type="button" class="page-btn" ${chatListPage === 1 ? 'disabled' : ''} onclick="goToChatPage(${chatListPage - 1})">Previous</button>`;
        html += `<div class="page-numbers">${renderPageNumberButtons(chatListPage, totalPages)}</div>`;
        html += `<button type="button" class="page-btn" ${chatListPage === totalPages ? 'disabled' : ''} onclick="goToChatPage(${chatListPage + 1})">Next</button>`;
        pager.innerHTML = html;
        return;
    }

    pinnedRows.forEach(row => { row.style.display = ''; });
    favoriteRows.forEach(row => { row.style.display = ''; });

    const totalPages = Math.max(1, Math.ceil(liveRows.length / CHAT_PAGE_SIZE));
    chatListPage = Math.min(Math.max(1, chatListPage), totalPages);

    liveRows.forEach((row, i) => {
        const page = Math.floor(i / CHAT_PAGE_SIZE) + 1;
        row.style.display = page === chatListPage ? '' : 'none';
    });
    updateDateGroupHeaderVisibility();

    if (!pager) return;
    if (liveRows.length === 0) {
        pager.innerHTML = '';
        return;
    }
    if (totalPages === 1) {
        pager.innerHTML = '<div class="page-numbers"><button type="button" class="page-btn page-num active" disabled>1</button></div>';
        return;
    }
    let html = `<button type="button" class="page-btn" ${chatListPage === 1 ? 'disabled' : ''} onclick="goToChatPage(${chatListPage - 1})">Previous</button>`;
    html += `<div class="page-numbers">${renderPageNumberButtons(chatListPage, totalPages)}</div>`;
    html += `<button type="button" class="page-btn" ${chatListPage === totalPages ? 'disabled' : ''} onclick="goToChatPage(${chatListPage + 1})">Next</button>`;
    pager.innerHTML = html;
}

function goToChatPage(page) {
    chatListPage = page;
    updateChatListDisplay();
    const historyEl = document.querySelector('.history-section');
    if (historyEl) historyEl.scrollTop = 0;
}

// ================= Search: instant title filter + debounced
// server-side title+message search =================
let chatSearchDebounceTimer = null;

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// Single source of truth for the "optimistic" sidebar row inserted
// right after a brand-new chat's first message streams back (before
// the next full page load would otherwise render it via
// partials/_chat_row.html).
function buildOptimisticChatRowHTML(sessionId, rawTitle) {
    const displayTitle = escapeHtml(rawTitle);
    const escapedFullTitle = escapeHtml(rawTitle);
    return `
    <div class="chat-item-container active-chat" style="animation: slideIn 0.3s ease;" data-session-id="${sessionId}" data-title="${escapedFullTitle}" data-folder="${escapeHtml(CHAT_FOLDER_FILTER)}" data-created-at="${new Date().toISOString()}" data-date-group="today" data-pinned="0" data-favorite="0" data-archived="0">
        <input type="checkbox" class="chat-bulk-checkbox" data-session-id="${sessionId}" onclick="event.stopPropagation(); onBulkCheckboxChange();" aria-label="Select conversation">
        <a href="/?session=${sessionId}" class="chat-link" title="${escapedFullTitle}">
            <span class="chat-row-icons"></span>
            <span class="chat-link-marker">&gt;</span>
            <span class="chat-link-title" title="${escapedFullTitle}">${displayTitle}</span>
        </a>
        <div class="side-menu">
            <button type="button" class="side-menu-btn" onclick="toggleMenu(event, 'drop-${sessionId}')" title="More options" aria-haspopup="true" aria-expanded="false"><i class="fa-solid fa-ellipsis"></i></button>
            <div class="side-dropdown" id="drop-${sessionId}" role="menu">
                <a href="javascript:void(0)" role="menuitem" onclick="togglePin('${sessionId}')"><i class="fa-solid fa-thumbtack"></i> <span class="js-pin-label">Pin</span></a>
                <a href="javascript:void(0)" role="menuitem" onclick="toggleFavoriteSession('${sessionId}')"><i class="fa-solid fa-star"></i> <span class="js-favorite-label">Favorite</span></a>
                <a href="javascript:void(0)" role="menuitem" onclick="renameChat('${sessionId}', '${escapedFullTitle.replace(/'/g, "\\'")}')"><i class="fa-solid fa-pen"></i> Rename</a>
                <a href="javascript:void(0)" role="menuitem" onclick="promptSetFolder('${sessionId}', '')"><i class="fa-solid fa-folder"></i> Set Folder</a>
                <a href="javascript:void(0)" role="menuitem" onclick="duplicateChat('${sessionId}')"><i class="fa-solid fa-clone"></i> Duplicate</a>
                <a href="javascript:void(0)" role="menuitem" onclick="toggleArchiveSession('${sessionId}')"><i class="fa-solid fa-box-archive"></i> <span class="js-archive-label">Archive</span></a>
                <a href="javascript:void(0)" role="menuitem" class="danger-item" onclick="deleteChat('${sessionId}')"><i class="fa-solid fa-trash"></i> Delete</a>
            </div>
        </div>
    </div>
`;
}

function insertOptimisticChatRow(sessionId, rawTitle) {
    const targetContainer = getDateGroupContainer('today');
    if (!targetContainer) return;
    const tempDiv = document.createElement('div');
    tempDiv.innerHTML = buildOptimisticChatRowHTML(sessionId, rawTitle);
    const newRow = tempDiv.firstElementChild;
    document.querySelectorAll('.chat-item-container, .chat-link').forEach(el => {
        el.classList.remove('active-chat');
    });
    insertRowInOrder(targetContainer, newRow);
    chatListPage = 1;
    refreshChatListChrome();
}

function highlightMatch(text, query) {
    const escaped = escapeHtml(text);
    const escapedQuery = escapeHtml(query).replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    if (!escapedQuery) return escaped;
    return escaped.replace(new RegExp(escapedQuery, 'gi'), (m) => `<mark>${m}</mark>`);
}

function renderSearchResults(results, query) {
    const panel = document.getElementById('search-results-panel');
    if (!results.length) {
        panel.innerHTML = '<div class="search-empty">No matches.</div>';
        panel.classList.add('show');
        return;
    }
    panel.innerHTML = results.map(r => `
                <a class="search-result-item" href="/?session=${r.session_id}">
                    <div class="search-result-title">${highlightMatch(r.title, query)}</div>
                    ${r.snippet ? `<div class="search-result-snippet">${highlightMatch(r.snippet, query)}</div>` : ''}
                </a>
            `).join('');
    panel.classList.add('show');
}

function filterChatHistory() {
    chatListPage = 1;
    updateChatListDisplay();

    const query = document.getElementById('chat-search-input').value.trim();
    const panel = document.getElementById('search-results-panel');
    clearTimeout(chatSearchDebounceTimer);
    if (query.length < 2) {
        panel.classList.remove('show');
        panel.innerHTML = '';
        return;
    }
    chatSearchDebounceTimer = setTimeout(() => {
        const searchUrl = `/sessions/search/?q=${encodeURIComponent(query)}&view=${encodeURIComponent(CHAT_VIEW_MODE)}${CHAT_FOLDER_FILTER ? `&folder=${encodeURIComponent(CHAT_FOLDER_FILTER)}` : ''}`;
        fetch(searchUrl, { signal: AbortSignal.timeout(8000) })
            .then(res => res.json())
            .then(data => renderSearchResults(data.results || [], query))
            .catch(() => { });
    }, 250);
}

// ================= Toast notifications (Part 9) =================
function showToast(message, type) {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const icon = type === 'success' ? 'fa-solid fa-circle-check' : type === 'error' ? 'fa-solid fa-triangle-exclamation' : 'fa-solid fa-circle-info';
    const toast = document.createElement('div');
    toast.className = `simba-toast toast-${type || 'info'}`;
    toast.innerHTML = `<i class="${icon}"></i><span>${escapeHtml(message)}</span>`;
    container.appendChild(toast);
    setTimeout(() => {
        toast.classList.add('toast-out');
        setTimeout(() => toast.remove(), 220);
    }, 3200);
}

// Settings > Save redirects back here with ?saved=1 - the only
// feedback the user previously got that Save actually worked was
// silently landing back on the chat page.
(function showSettingsSavedToast() {
    const params = new URLSearchParams(window.location.search);
    if (!params.get('saved')) return;
    showToast('Settings saved', 'success');
    params.delete('saved');
    const newSearch = params.toString();
    history.replaceState(null, '', window.location.pathname + (newSearch ? `?${newSearch}` : ''));
})();

// ================= Bookmarks panel (Part 2 - centralized bookmark workflow) =================
let bookmarksCache = [];
let bookmarksDebounceTimer = null;

function openBookmarksPanel() {
    const overlay = document.getElementById('bookmarksPanel');
    const input = document.getElementById('bookmarksSearchInput');
    if (!overlay) return;
    overlay.classList.add('show');
    if (input) { input.value = ''; setTimeout(() => input.focus(), 30); }
    loadBookmarks('');
}

function closeBookmarksPanel() {
    document.getElementById('bookmarksPanel')?.classList.remove('show');
}

function loadBookmarks(q) {
    const panel = document.getElementById('bookmarksResults');
    if (panel) panel.innerHTML = '<div class="search-empty"><i class="fa-solid fa-spinner fa-spin"></i> Loading bookmarks...</div>';
    fetch(`/bookmarks/?q=${encodeURIComponent(q || '')}`, { signal: AbortSignal.timeout(8000) })
        .then(res => res.json())
        .then(data => { bookmarksCache = data.results || []; renderBookmarksResults(bookmarksCache, q || ''); })
        .catch(() => { if (panel) panel.innerHTML = '<div class="search-empty">Could not load bookmarks.</div>'; });
}

function filterBookmarks(query) {
    clearTimeout(bookmarksDebounceTimer);
    bookmarksDebounceTimer = setTimeout(() => loadBookmarks(query.trim()), 200);
}

function bookmarkTypeIcon(type) {
    if (type === 'image') return 'fa-solid fa-image';
    if (type === 'vision') return 'fa-solid fa-eye';
    return 'fa-solid fa-message';
}

function formatBookmarkDate(iso) {
    if (!iso) return '';
    try {
        return new Date(iso).toLocaleString(undefined, {
            month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
        });
    } catch (e) { return ''; }
}

function renderBookmarksResults(results, query) {
    const panel = document.getElementById('bookmarksResults');
    if (!panel) return;
    if (!results.length) {
        panel.innerHTML = `<div class="search-empty"><i class="fa-solid fa-bookmark" style="opacity:0.4;font-size:22px;display:block;margin-bottom:8px;"></i>${query ? 'No bookmarks match that search.' : 'No bookmarks yet - bookmark any reply from its action row.'}</div>`;
        return;
    }
    panel.innerHTML = results.map(r => `
                <div class="bookmark-item" data-message-id="${r.message_id}">
                    <div class="bookmark-item-icon"><i class="${bookmarkTypeIcon(r.type)}"></i></div>
                    <div class="bookmark-item-body" onclick="jumpToBookmark(${r.session_id}, ${r.message_id})">
                        <div class="bookmark-item-title">${highlightMatch(r.label || r.session_title, query)}</div>
                        ${r.label ? `<div class="bookmark-item-convo"><i class="fa-solid fa-diagram-project"></i> ${escapeHtml(r.session_title)}</div>` : ''}
                        ${r.snippet ? `<div class="bookmark-item-snippet">${highlightMatch(r.snippet, query)}</div>` : ''}
                        <div class="bookmark-item-date">${formatBookmarkDate(r.bookmarked_at)}</div>
                    </div>
                    <div class="bookmark-item-actions">
                        <button type="button" class="rail-icon-btn" title="Rename bookmark" onclick="renameBookmark(${r.message_id})"><i class="fa-solid fa-pen"></i></button>
                        <button type="button" class="rail-icon-btn" title="Jump to conversation" onclick="jumpToBookmark(${r.session_id}, ${r.message_id})"><i class="fa-solid fa-arrow-right"></i></button>
                        <button type="button" class="rail-icon-btn" title="Remove bookmark" onclick="removeBookmarkFromPanel(${r.message_id}, this)"><i class="fa-solid fa-trash"></i></button>
                    </div>
                </div>
            `).join('');
}

function jumpToBookmark(sessionId, messageId) {
    closeBookmarksPanel();
    window.location.href = `/?session=${sessionId}&jump=${messageId}`;
}

function renameBookmark(messageId) {
    const current = bookmarksCache.find(r => r.message_id === messageId);
    const label = prompt('Rename this bookmark:', current ? current.label : '');
    if (label === null) return;
    fetch(`/messages/${messageId}/bookmark/label/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': csrfToken },
        body: `label=${encodeURIComponent(label.trim())}`,
        signal: AbortSignal.timeout(8000),
    })
        .then(res => res.json())
        .then(() => {
            loadBookmarks(document.getElementById('bookmarksSearchInput')?.value.trim() || '');
            showToast('Bookmark renamed', 'success');
        })
        .catch(() => showToast('Could not rename this bookmark.', 'error'));
}

function removeBookmarkFromPanel(messageId, btn) {
    const item = btn.closest('.bookmark-item');
    fetch(`/messages/${messageId}/bookmark/`, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrfToken },
        signal: AbortSignal.timeout(8000),
    })
        .then(res => res.json())
        .then(() => {
            if (item) item.remove();
            bookmarksCache = bookmarksCache.filter(r => r.message_id !== messageId);
            // Keep the same in-page reply's bookmark icon in sync if it's
            // currently rendered (unbookmarking here shouldn't require a
            // reload of the conversation to see it reflected).
            const liveBtn = document.querySelector(`.chat-block[data-message-id="${messageId}"] .bookmark-btn`);
            if (liveBtn) {
                liveBtn.classList.remove('active');
                const icon = liveBtn.querySelector('i');
                if (icon) icon.className = 'fa-regular fa-bookmark';
            }
            if (!bookmarksCache.length) renderBookmarksResults([], document.getElementById('bookmarksSearchInput')?.value.trim() || '');
            showToast('Bookmark removed', 'info');
        })
        .catch(() => showToast('Could not remove this bookmark.', 'error'));
}

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeBookmarksPanel();
});

// ================= Prompt Library (Part 5) =================
let promptLibraryTab = 'all';
let promptLibraryCategory = '';
let promptLibraryDebounceTimer = null;
let promptLibraryCache = [];

function openPromptLibrary() {
    const overlay = document.getElementById('promptLibraryPanel');
    const input = document.getElementById('promptLibrarySearchInput');
    if (!overlay) return;
    overlay.classList.add('show');
    if (input) { input.value = ''; setTimeout(() => input.focus(), 30); }
    promptLibraryTab = 'all';
    promptLibraryCategory = '';
    document.querySelectorAll('.prompt-library-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === 'all'));
    loadPromptLibrary('');
}

function closePromptLibrary() {
    document.getElementById('promptLibraryPanel')?.classList.remove('show');
}

function switchPromptLibraryTab(tab) {
    promptLibraryTab = tab;
    document.querySelectorAll('.prompt-library-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
    const query = document.getElementById('promptLibrarySearchInput')?.value.trim() || '';
    if (tab === 'recent') {
        loadRecentPrompts();
    } else {
        loadPromptLibrary(query);
    }
}

function loadPromptLibrary(q) {
    const panel = document.getElementById('promptLibraryResults');
    const chipsPanel = document.getElementById('promptLibraryCategoryChips');
    if (panel) panel.innerHTML = '<div class="search-empty"><i class="fa-solid fa-spinner fa-spin"></i> Loading...</div>';
    const params = new URLSearchParams();
    if (q) params.set('q', q);
    if (promptLibraryTab === 'favorites') params.set('favorites', '1');
    if (promptLibraryCategory) params.set('category', promptLibraryCategory);
    fetch(`/prompts/?${params.toString()}`, { signal: AbortSignal.timeout(8000) })
        .then(res => res.json())
        .then(data => {
            promptLibraryCache = data.results || [];
            renderPromptLibraryResults(promptLibraryCache, q || '');
            if (chipsPanel) {
                const categories = data.categories || [];
                chipsPanel.innerHTML = categories.length ? [
                    `<button type="button" class="folder-chip ${!promptLibraryCategory ? 'active' : ''}" onclick="filterPromptLibraryCategory('')">All</button>`,
                    ...categories.map(c => `<button type="button" class="folder-chip ${promptLibraryCategory === c ? 'active' : ''}" onclick="filterPromptLibraryCategory('${escapeHtml(c)}')"><i class="fa-solid fa-tag"></i> ${escapeHtml(c)}</button>`)
                ].join('') : '';
            }
        })
        .catch(() => { if (panel) panel.innerHTML = '<div class="search-empty">Could not load prompts.</div>'; });
}

function filterPromptLibraryCategory(category) {
    promptLibraryCategory = category;
    loadPromptLibrary(document.getElementById('promptLibrarySearchInput')?.value.trim() || '');
}

function loadRecentPrompts() {
    const panel = document.getElementById('promptLibraryResults');
    const chipsPanel = document.getElementById('promptLibraryCategoryChips');
    if (chipsPanel) chipsPanel.innerHTML = '';
    if (panel) panel.innerHTML = '<div class="search-empty"><i class="fa-solid fa-spinner fa-spin"></i> Loading...</div>';
    fetch('/prompts/recent/', { signal: AbortSignal.timeout(8000) })
        .then(res => res.json())
        .then(data => {
            const results = data.results || [];
            if (!panel) return;
            if (!results.length) {
                panel.innerHTML = '<div class="search-empty">No recent prompts yet - anything you send becomes part of your history.</div>';
                return;
            }
            panel.innerHTML = results.map(r => `
                        <div class="bookmark-item">
                            <div class="bookmark-item-icon"><i class="fa-solid fa-clock-rotate-left"></i></div>
                            <div class="bookmark-item-body" onclick="insertPromptText(this)" data-content="${escapeHtml(r.content)}">
                                <div class="bookmark-item-snippet">${escapeHtml(r.content)}</div>
                            </div>
                        </div>
                    `).join('');
        })
        .catch(() => { if (panel) panel.innerHTML = '<div class="search-empty">Could not load recent prompts.</div>'; });
}

function filterSavedPrompts(query) {
    clearTimeout(promptLibraryDebounceTimer);
    promptLibraryDebounceTimer = setTimeout(() => {
        if (promptLibraryTab === 'recent') return;
        loadPromptLibrary(query.trim());
    }, 200);
}

function renderPromptLibraryResults(results, query) {
    const panel = document.getElementById('promptLibraryResults');
    if (!panel) return;
    if (!results.length) {
        panel.innerHTML = `<div class="search-empty"><i class="fa-solid fa-book-bookmark" style="opacity:0.4;font-size:22px;display:block;margin-bottom:8px;"></i>${query ? 'No prompts match that search.' : 'No saved prompts yet - use the bookmark icon next to the composer to save one.'}</div>`;
        return;
    }
    panel.innerHTML = results.map(p => `
                <div class="bookmark-item" data-prompt-id="${p.id}">
                    <div class="bookmark-item-icon"><i class="fa-solid fa-book-bookmark"></i></div>
                    <div class="bookmark-item-body" onclick="usePromptFromLibrary(${p.id})">
                        <div class="bookmark-item-title">${highlightMatch(p.title, query)}${p.category ? `<span class="prompt-item-category-badge">${escapeHtml(p.category)}</span>` : ''}</div>
                        <div class="bookmark-item-snippet">${highlightMatch(p.content, query)}</div>
                        <div class="bookmark-item-date">Used ${p.use_count} time${p.use_count === 1 ? '' : 's'}</div>
                    </div>
                    <div class="bookmark-item-actions">
                        <button type="button" class="rail-icon-btn" title="${p.is_favorite ? 'Unfavorite' : 'Favorite'}" onclick="toggleFavoritePrompt(${p.id}, this)"><i class="fa-${p.is_favorite ? 'solid' : 'regular'} fa-star"></i></button>
                        <button type="button" class="rail-icon-btn" title="Edit" onclick="editSavedPrompt(${p.id})"><i class="fa-solid fa-pen"></i></button>
                        <button type="button" class="rail-icon-btn" title="Delete" onclick="deleteSavedPromptFromPanel(${p.id}, this)"><i class="fa-solid fa-trash"></i></button>
                    </div>
                </div>
            `).join('');
}

function insertPromptText(el) {
    const input = document.getElementById('user-input');
    if (input) { input.value = el.dataset.content; input.focus(); }
    closePromptLibrary();
}

// Empty-home-screen command chips - same "fill the composer and let
// the user finish typing" pattern as insertPromptText() above, rather
// than auto-sending, since several of these (Debug Code, SQL Query,
// Summarize Notes, Build React App) need the user's own content
// pasted in first.
function fillHomeAction(text) {
    const input = document.getElementById('user-input');
    if (!input) return;
    input.value = text;
    input.focus();
}

function usePromptFromLibrary(promptId) {
    fetch(`/prompts/${promptId}/use/`, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrfToken },
        signal: AbortSignal.timeout(8000),
    })
        .then(res => res.json())
        .then(data => {
            const input = document.getElementById('user-input');
            if (input && data.content) { input.value = data.content; input.focus(); }
            closePromptLibrary();
        })
        .catch(() => showToast('Could not use this prompt.', 'error'));
}

function toggleFavoritePrompt(promptId, btn) {
    const current = promptLibraryCache.find(p => p.id === promptId);
    const nextValue = current ? !current.is_favorite : true;
    fetch(`/prompts/${promptId}/update/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': csrfToken },
        body: `is_favorite=${nextValue ? '1' : '0'}`,
        signal: AbortSignal.timeout(8000),
    })
        .then(res => res.json())
        .then(() => loadPromptLibrary(document.getElementById('promptLibrarySearchInput')?.value.trim() || ''))
        .catch(() => showToast('Could not update favorite.', 'error'));
}

function editSavedPrompt(promptId) {
    const current = promptLibraryCache.find(p => p.id === promptId);
    const newTitle = prompt('Prompt title:', current ? current.title : '');
    if (newTitle === null) return;
    const newCategory = prompt('Category (optional):', current ? current.category : '') || '';
    fetch(`/prompts/${promptId}/update/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': csrfToken },
        body: `title=${encodeURIComponent(newTitle.trim())}&category=${encodeURIComponent(newCategory.trim())}`,
        signal: AbortSignal.timeout(8000),
    })
        .then(res => res.json())
        .then(() => {
            loadPromptLibrary(document.getElementById('promptLibrarySearchInput')?.value.trim() || '');
            showToast('Prompt updated', 'success');
        })
        .catch(() => showToast('Could not update this prompt.', 'error'));
}

function deleteSavedPromptFromPanel(promptId, btn) {
    if (!confirm('Delete this saved prompt?')) return;
    const item = btn.closest('.bookmark-item');
    fetch(`/prompts/${promptId}/delete/`, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrfToken },
        signal: AbortSignal.timeout(8000),
    })
        .then(res => res.json())
        .then(() => {
            if (item) item.remove();
            promptLibraryCache = promptLibraryCache.filter(p => p.id !== promptId);
            showToast('Prompt deleted', 'info');
        })
        .catch(() => showToast('Could not delete this prompt.', 'error'));
}

function openNewPromptDialog() {
    const input = document.getElementById('user-input');
    const defaultContent = input ? input.value.trim() : '';
    const content = prompt('Prompt content:', defaultContent);
    if (!content || !content.trim()) return;
    const title = prompt('Give it a short title:', content.trim().slice(0, 40)) || content.trim().slice(0, 40);
    const category = prompt('Category (optional):', '') || '';
    fetch('/prompts/create/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': csrfToken },
        body: `title=${encodeURIComponent(title.trim())}&content=${encodeURIComponent(content.trim())}&category=${encodeURIComponent(category.trim())}`,
        signal: AbortSignal.timeout(8000),
    })
        .then(res => res.json())
        .then(() => {
            loadPromptLibrary(document.getElementById('promptLibrarySearchInput')?.value.trim() || '');
            showToast('Prompt saved', 'success');
        })
        .catch(() => showToast('Could not save this prompt.', 'error'));
}

function savePromptFromComposer() {
    const input = document.getElementById('user-input');
    const content = input ? input.value.trim() : '';
    if (!content) { alert('Type something in the composer first.'); return; }
    const title = prompt('Save this as a prompt - give it a short title:', content.slice(0, 40));
    if (title === null) return;
    const category = prompt('Category (optional):', '') || '';
    fetch('/prompts/create/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': csrfToken },
        body: `title=${encodeURIComponent((title || content).trim().slice(0, 40))}&content=${encodeURIComponent(content)}&category=${encodeURIComponent(category.trim())}`,
        signal: AbortSignal.timeout(8000),
    })
        .then(res => res.json())
        .then(() => showToast('Prompt saved to your library', 'success'))
        .catch(() => showToast('Could not save this prompt.', 'error'));
}

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closePromptLibrary();
});

// "Jump to original conversation" from the Bookmarks panel lands here
// with ?jump=<message_id> - scroll to it and give it a brief highlight
// flash so it's obvious which reply was meant, then strip the param
// so a later refresh of this same URL doesn't re-trigger it.
(function jumpToMessageFromQuery() {
    const params = new URLSearchParams(window.location.search);
    const jumpId = params.get('jump');
    if (!jumpId) return;
    const target = document.querySelector(`[data-message-id="${jumpId}"]`);
    if (target) {
        setTimeout(() => {
            target.scrollIntoView({ behavior: 'smooth', block: 'center' });
            target.classList.add('jump-highlight');
            setTimeout(() => target.classList.remove('jump-highlight'), 2200);
        }, 150);
    }
    params.delete('jump');
    const newSearch = params.toString();
    history.replaceState(null, '', window.location.pathname + (newSearch ? `?${newSearch}` : ''));
})();

// Client-side local timezone alignment check: if any chat belongs in a different
// date bucket according to the user's browser clock, move it cleanly in descending order.
(function syncChatDateGroups() {
    const rows = getLiveChatRows();
    rows.forEach(row => {
        if (!row.dataset.createdAt) return;
        const expectedGroup = calculateDateGroup(row.dataset.createdAt);
        const currentGroupEl = row.closest('.chat-date-group');
        const currentGroup = currentGroupEl ? currentGroupEl.dataset.group : null;
        if (expectedGroup !== currentGroup) {
            const targetContainer = getDateGroupContainer(expectedGroup);
            if (targetContainer) {
                insertRowInOrder(targetContainer, row);
            }
        }
    });
    refreshChatListChrome();
})();

(function initChatPagination() {
    const liveRows = getLiveChatRows();
    const activeIndex = liveRows.findIndex(row => row.classList.contains('active-chat'));
    chatListPage = activeIndex === -1 ? 1 : Math.floor(activeIndex / CHAT_PAGE_SIZE) + 1;
    updateChatListDisplay();
})();

// ================= Profile popover (avatar + chevron trigger) =================
// IIFE so re-running this script block (should never happen on a normal
// page load, but keeps the guard cheap and explicit) can't double-bind.
(function () {
    const trigger = document.getElementById('profileTriggerBtn');
    const popover = document.getElementById('profilePopover');
    if (!trigger || !popover) return;

    function openProfilePopover() {
        popover.classList.add('show');
        trigger.classList.add('open');
        trigger.setAttribute('aria-expanded', 'true');
    }
    function closeProfilePopover() {
        popover.classList.remove('show');
        trigger.classList.remove('open');
        trigger.setAttribute('aria-expanded', 'false');
    }

    trigger.addEventListener('click', (e) => {
        e.stopPropagation();
        if (popover.classList.contains('show')) closeProfilePopover();
        else openProfilePopover();
    });
    document.addEventListener('click', (e) => {
        if (popover.classList.contains('show') && !popover.contains(e.target) && e.target !== trigger) {
            closeProfilePopover();
        }
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && popover.classList.contains('show')) closeProfilePopover();
    });
})();

// ================= MENU, PIN, DELETE, RENAME, COPY, SHARE =================
// ================= Context menu (Part 2 rebuild) =================
// Shared close routine: clears .show/.flip-up on every open dropdown
// and resets the triggering button's aria-expanded, so opening a
// different row's menu (or clicking away, or Escape) always leaves
// things in a consistent state.
function closeAllSideDropdowns() {
    document.querySelectorAll('.side-dropdown.show').forEach(d => {
        d.classList.remove('show', 'flip-up');
        d.querySelectorAll('.menu-item-active').forEach(el => el.classList.remove('menu-item-active'));
    });
    document.querySelectorAll('.side-menu-btn[aria-expanded="true"]').forEach(btn => {
        btn.setAttribute('aria-expanded', 'false');
    });
}

// Flips the menu above its button instead of below, only when it
// would otherwise overflow the viewport bottom - measured against
// the real rendered box, not an estimate, so it's correct at any
// zoom level or viewport size.
function positionSideDropdown(menu, btn) {
    menu.classList.remove('flip-up');
    const btnRect = btn.getBoundingClientRect();
    const menuRect = menu.getBoundingClientRect();
    const overflowsBottom = btnRect.bottom + menuRect.height > window.innerHeight - 8;
    const fitsAbove = btnRect.top - menuRect.height > 8;
    if (overflowsBottom && fitsAbove) {
        menu.classList.add('flip-up');
    }
}

function getMenuItems(menu) {
    return Array.from(menu.querySelectorAll('[role="menuitem"]'));
}

function toggleMenu(event, id) {
    event.stopPropagation();
    const menu = document.getElementById(id);
    const btn = event.currentTarget || (event.target.closest ? event.target.closest('.side-menu-btn') : null);
    const wasOpen = menu.classList.contains('show');
    closeAllSideDropdowns();
    if (wasOpen) return;

    menu.classList.add('show');
    if (btn) btn.setAttribute('aria-expanded', 'true');
    // Measure on the next frame - the menu must already be laid out
    // (display/visibility resolved) for getBoundingClientRect to
    // reflect its real height.
    requestAnimationFrame(() => positionSideDropdown(menu, btn || menu.parentElement.querySelector('.side-menu-btn')));
}

window.addEventListener("click", function (e) {
    if (!e.target.closest('.side-menu')) {
        closeAllSideDropdowns();
    }
});

// Escape closes an open context menu; Arrow Up/Down move between
// items; Enter/Space activate the focused-or-highlighted one - the
// same keyboard model as a native OS menu.
document.addEventListener('keydown', (e) => {
    const openMenu = document.querySelector('.side-dropdown.show');
    if (!openMenu) return;

    if (e.key === 'Escape') {
        e.preventDefault();
        const btn = openMenu.closest('.side-menu')?.querySelector('.side-menu-btn');
        closeAllSideDropdowns();
        btn?.focus();
        return;
    }

    const items = getMenuItems(openMenu);
    if (!items.length) return;
    const currentIndex = items.findIndex(i => i.classList.contains('menu-item-active'));

    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        const delta = e.key === 'ArrowDown' ? 1 : -1;
        const nextIndex = currentIndex === -1
            ? (delta === 1 ? 0 : items.length - 1)
            : (currentIndex + delta + items.length) % items.length;
        items.forEach(i => i.classList.remove('menu-item-active'));
        items[nextIndex].classList.add('menu-item-active');
        items[nextIndex].focus();
    } else if (e.key === 'Enter' || e.key === ' ') {
        if (currentIndex !== -1) {
            e.preventDefault();
            items[currentIndex].click();
        }
    }
});

// Guards the fetch-straight-to-the-network sidebar actions below
// against a double-click/double-tap firing the same toggle twice
// (e.g. Pin then Unpin racing back to the original state before the
// user's second click even registers as intentional) - the dropdown
// menu item stayed open and clickable for the whole in-flight
// request otherwise, since closeAllSideDropdowns() used to run only
// after the fetch resolved instead of the instant the click fired.
const _inFlightSessionActions = new Set();

async function togglePin(id) {
    const key = 'pin-' + id;
    if (_inFlightSessionActions.has(key)) return;
    _inFlightSessionActions.add(key);
    closeAllSideDropdowns();
    const row = getChatRow(id);
    try {
        const res = await fetch(`/pin_session/${id}/`, {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded", "X-CSRFToken": csrfToken }
        });
        if (!res.ok) { showToast("Could not update pin.", 'error'); return; }
        const data = await res.json();
        if (row) {
            row.dataset.pinned = data.is_pinned ? '1' : '0';
            refreshRowFromData(row);
            moveRowToCorrectSection(row);
        }
    } catch (err) { console.error(err); showToast("Network error - please try again.", 'error'); }
    finally { _inFlightSessionActions.delete(key); }
}

function deleteChat(id) {
    showConfirm({
        title: 'Delete this conversation?',
        message: 'This permanently removes the conversation and everything in it. This cannot be undone.',
        confirmLabel: 'Delete',
        danger: true,
        onConfirm: async () => {
            try {
                const res = await fetch(`/delete_session/${id}/`, {
                    method: "POST",
                    headers: { "Content-Type": "application/x-www-form-urlencoded", "X-CSRFToken": csrfToken }
                });
                if (!res.ok) { showToast("Could not delete chat.", 'error'); return; }
                const wasCurrent = new URLSearchParams(window.location.search).get('session') === String(id);
                getChatRow(id)?.remove();
                refreshChatListChrome();
                if (wasCurrent) {
                    // The open conversation was just deleted out from
                    // under the user - there's nothing left to patch
                    // in place, so this is the one case where landing
                    // back on a blank workspace genuinely needs a
                    // real navigation.
                    window.location.href = '/';
                } else {
                    showToast('Chat deleted', 'info');
                }
            } catch (err) { console.error(err); showToast("Network error - please try again.", 'error'); }
        },
    });
}

async function renameChat(id, oldTitle) {
    const newTitle = prompt("New Title:", oldTitle);
    if (!newTitle || newTitle === oldTitle) return;
    try {
        const res = await fetch(`/rename_session/${id}/`, {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded", "X-CSRFToken": csrfToken },
            body: `title=${encodeURIComponent(newTitle)}`
        });
        if (!res.ok) { showToast("Could not rename chat.", 'error'); return; }
        const row = getChatRow(id);
        if (row) {
            row.dataset.title = newTitle;
            const titleEl = row.querySelector('.chat-link-title');
            if (titleEl) titleEl.textContent = newTitle;
            const renameLink = row.querySelector(`#drop-${id} a[onclick^="renameChat"]`);
            if (renameLink) renameLink.setAttribute('onclick', `renameChat('${id}', '${newTitle.replace(/'/g, "\\'")}')`);
        }
        // The currently-open chat's title also drives the PDF export
        // button's filename - keep that in sync too.
        const exportBtn = document.querySelector('.new-chat[data-chat-title]');
        if (exportBtn && new URLSearchParams(window.location.search).get('session') === String(id)) {
            exportBtn.dataset.chatTitle = newTitle;
        }
        closeAllSideDropdowns();
        showToast('Chat renamed', 'success');
    } catch (err) { console.error(err); showToast("Network error - please try again.", 'error'); }
}

async function toggleFavoriteSession(id) {
    const key = 'favorite-' + id;
    if (_inFlightSessionActions.has(key)) return;
    _inFlightSessionActions.add(key);
    closeAllSideDropdowns();
    const row = getChatRow(id);
    try {
        const res = await fetch(`/sessions/${id}/favorite/`, {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded", "X-CSRFToken": csrfToken }
        });
        if (!res.ok) { showToast("Could not update favorite.", 'error'); return; }
        const data = await res.json();
        if (row) {
            row.dataset.favorite = data.is_favorite ? '1' : '0';
            refreshRowFromData(row);
            moveRowToCorrectSection(row);
        }
    } catch (err) { console.error(err); showToast("Network error - please try again.", 'error'); }
    finally { _inFlightSessionActions.delete(key); }
}

async function toggleArchiveSession(id) {
    const key = 'archive-' + id;
    if (_inFlightSessionActions.has(key)) return;
    _inFlightSessionActions.add(key);
    closeAllSideDropdowns();
    const row = getChatRow(id);
    try {
        const res = await fetch(`/sessions/${id}/archive/`, {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded", "X-CSRFToken": csrfToken }
        });
        if (!res.ok) { showToast("Could not update archive state.", 'error'); return; }
        const data = await res.json();
        if (row) {
            row.dataset.archived = data.is_archived ? '1' : '0';
            refreshRowFromData(row);
            moveRowToCorrectSection(row);
        }
        showToast(data.is_archived ? 'Chat archived' : 'Chat unarchived', 'info');
    } catch (err) { console.error(err); showToast("Network error - please try again.", 'error'); }
    finally { _inFlightSessionActions.delete(key); }
}

async function duplicateChat(id) {
    const key = 'duplicate-' + id;
    if (_inFlightSessionActions.has(key)) return;
    _inFlightSessionActions.add(key);
    closeAllSideDropdowns();
    try {
        const res = await fetch(`/sessions/${id}/duplicate/`, {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded", "X-CSRFToken": csrfToken }
        });
        if (!res.ok) { showToast("Could not duplicate chat.", 'error'); return; }
        const data = await res.json();
        // Inserted as its own row rather than navigated to - a
        // duplicate shouldn't interrupt whatever the user is
        // currently looking at. Only shown here if it actually
        // belongs in the current view/folder (it inherits the
        // original's folder, which might not match a folder filter
        // that's currently active).
        if (CHAT_VIEW_MODE !== 'archived' && (!CHAT_FOLDER_FILTER || CHAT_FOLDER_FILTER === (data.folder || ''))) {
            const wrapper = document.createElement('div');
            wrapper.innerHTML = data.row_html;
            const group = getDateGroupContainer(calculateDateGroup(new Date().toISOString()));
            insertRowInOrder(group, wrapper.firstElementChild);
            refreshChatListChrome();
        }
        if (data.folder) refreshFolderChipsFromServer();
        showToast('Chat duplicated', 'success');
    } catch (err) { console.error(err); showToast("Network error - please try again.", 'error'); }
    finally { _inFlightSessionActions.delete(key); }
}

// ================= Generic confirmation dialog (Part 3/10) =================
// Replaces native confirm() for destructive actions with a styled,
// on-brand dialog. Callback-based: pass an onConfirm; Cancel/Esc/
// backdrop-click just close it.
let _confirmCallback = null;
function showConfirm({ title, message, confirmLabel = 'Confirm', danger = false, onConfirm }) {
    const overlay = document.getElementById('confirmDialogOverlay');
    const dialog = overlay.querySelector('.confirm-dialog');
    document.getElementById('confirmDialogTitle').textContent = title || 'Are you sure?';
    document.getElementById('confirmDialogMessage').textContent = message || '';
    const confirmBtn = document.getElementById('confirmDialogConfirmBtn');
    confirmBtn.textContent = confirmLabel;
    dialog.classList.toggle('danger', !!danger);
    _confirmCallback = onConfirm;
    overlay.classList.add('show');
    setTimeout(() => confirmBtn.focus(), 30);
}

function closeConfirmDialog() {
    document.getElementById('confirmDialogOverlay').classList.remove('show');
    _confirmCallback = null;
}

document.getElementById('confirmDialogConfirmBtn').addEventListener('click', () => {
    const cb = _confirmCallback;
    closeConfirmDialog();
    if (cb) cb();
});

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeConfirmDialog();
});

// ================= Folder management (Part 3) =================
const FOLDER_COLORS = [
    ['', 'None'], ['red', 'Red'], ['orange', 'Orange'], ['yellow', 'Yellow'],
    ['green', 'Green'], ['blue', 'Blue'], ['purple', 'Purple'],
];

function createFolderPrompt() {
    const name = prompt('New folder name:');
    if (name === null) return;
    const trimmed = name.trim();
    if (!trimmed) return;
    fetch("/folders/create/", {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': csrfToken },
        body: `name=${encodeURIComponent(trimmed)}`,
        signal: AbortSignal.timeout(8000),
    })
        .then(res => res.json().then(data => ({ ok: res.ok, data })))
        .then(({ ok, data }) => {
            if (!ok) { showToast(data.error || 'Could not create folder.', 'error'); return; }
            showToast('Folder created', 'success');
            refreshFolderChipsFromServer();
        })
        .catch(() => showToast('Network error - please try again.', 'error'));
}

function buildFolderMenuColors(currentColor) {
    const wrap = document.getElementById('folderMenuColors');
    wrap.innerHTML = FOLDER_COLORS.map(([value, label]) =>
        `<button type="button" class="color-swatch ${value ? 'color-swatch-' + value : 'color-swatch-none'}"
                    title="${label}" style="${value === currentColor ? 'outline:2px solid var(--accent);outline-offset:1px;' : ''}"
                    onclick="folderMenuSetColor('${value}')"></button>`
    ).join('');
}

function positionContextMenu(menu, x, y) {
    menu.classList.add('show');
    const rect = menu.getBoundingClientRect();
    const maxX = window.innerWidth - rect.width - 8;
    const maxY = window.innerHeight - rect.height - 8;
    menu.style.left = Math.max(8, Math.min(x, maxX)) + 'px';
    menu.style.top = Math.max(8, Math.min(y, maxY)) + 'px';
}

function openFolderMenu(event, name, color) {
    event.preventDefault();
    const menu = document.getElementById('folderContextMenu');
    menu.dataset.folderName = name;
    menu.dataset.folderColor = color || '';
    buildFolderMenuColors(color || '');
    positionContextMenu(menu, event.clientX, event.clientY);
    return false;
}

function openFolderMenuFromBtn(event, btn, name, color) {
    event.preventDefault();
    event.stopPropagation();
    const menu = document.getElementById('folderContextMenu');
    menu.dataset.folderName = name;
    menu.dataset.folderColor = color || '';
    buildFolderMenuColors(color || '');
    const rect = btn.getBoundingClientRect();
    positionContextMenu(menu, rect.left, rect.bottom + 4);
}

function closeFolderMenu() {
    document.getElementById('folderContextMenu').classList.remove('show');
}

document.addEventListener('click', (e) => {
    if (!e.target.closest('#folderContextMenu') && !e.target.closest('.folder-chip-menu-btn')) {
        closeFolderMenu();
    }
});

function folderMenuRename() {
    const menu = document.getElementById('folderContextMenu');
    const oldName = menu.dataset.folderName;
    closeFolderMenu();
    const newName = prompt('Rename folder:', oldName);
    if (newName === null) return;
    const trimmed = newName.trim();
    if (!trimmed || trimmed === oldName) return;
    fetch("/folders/rename/", {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': csrfToken },
        body: `old_name=${encodeURIComponent(oldName)}&new_name=${encodeURIComponent(trimmed)}`,
        signal: AbortSignal.timeout(8000),
    })
        .then(res => res.json().then(data => ({ ok: res.ok, data })))
        .then(({ ok, data }) => {
            if (!ok) { showToast(data.error || 'Could not rename folder.', 'error'); return; }
            relabelRowsInFolder(oldName, data.name);
            if (CHAT_FOLDER_FILTER === oldName) {
                const url = new URL(window.location.href);
                url.searchParams.set('folder', data.name);
                history.replaceState(null, '', url);
            }
            refreshFolderChipsFromServer();
            showToast('Folder renamed', 'success');
        })
        .catch(() => showToast('Network error - please try again.', 'error'));
}

function folderMenuSetColor(color) {
    const menu = document.getElementById('folderContextMenu');
    const name = menu.dataset.folderName;
    closeFolderMenu();
    fetch("/folders/color/", {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': csrfToken },
        body: `name=${encodeURIComponent(name)}&color=${encodeURIComponent(color)}`,
        signal: AbortSignal.timeout(8000),
    })
        .then(res => res.json().then(data => ({ ok: res.ok, data })))
        .then(({ ok, data }) => {
            if (!ok) { showToast(data.error || 'Could not update folder color.', 'error'); return; }
            refreshFolderChipsFromServer();
        })
        .catch(() => showToast('Network error - please try again.', 'error'));
}

function folderMenuDelete() {
    const menu = document.getElementById('folderContextMenu');
    const name = menu.dataset.folderName;
    closeFolderMenu();
    showConfirm({
        title: `Delete "${name}"?`,
        message: 'The folder will be removed and its chats moved out of it. No conversations are deleted.',
        confirmLabel: 'Delete folder',
        danger: true,
        onConfirm: () => {
            fetch("/folders/delete/", {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRFToken': csrfToken },
                body: `name=${encodeURIComponent(name)}`,
                signal: AbortSignal.timeout(8000),
            })
                .then(res => res.json().then(data => ({ ok: res.ok, data })))
                .then(({ ok, data }) => {
                    if (!ok) { showToast(data.error || 'Could not delete folder.', 'error'); return; }
                    showToast(`Folder deleted${data.unfiled ? ` · ${data.unfiled} chat(s) unfiled` : ''}`, 'info');
                    if (CHAT_FOLDER_FILTER === name) {
                        // The folder being viewed no longer exists -
                        // "All" is the only view left to show.
                        window.location.href = '/';
                    } else {
                        unfileRowsInFolder(name);
                        refreshFolderChipsFromServer();
                    }
                })
                .catch(() => showToast('Network error - please try again.', 'error'));
        },
    });
}

async function promptSetFolder(id, currentFolder) {
    const folder = prompt("Folder name (leave blank to remove from folder):", currentFolder || "");
    if (folder === null) return;
    try {
        const res = await fetch(`/sessions/${id}/folder/`, {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded", "X-CSRFToken": csrfToken },
            body: `folder=${encodeURIComponent(folder)}`
        });
        if (!res.ok) { showToast("Could not update folder.", 'error'); return; }
        const data = await res.json();
        const row = getChatRow(id);
        if (row) {
            row.dataset.folder = data.folder;
            refreshRowFromData(row);
            moveRowToCorrectSection(row);
        }
        closeAllSideDropdowns();
        refreshFolderChipsFromServer();
        showToast('Folder updated', 'success');
    } catch (err) { console.error(err); showToast("Network error - please try again.", 'error'); }
}

async function setSessionColor(id, color) {
    // Same in-flight guard as togglePin/etc above - without it,
    // clicking two different swatches quickly could let an earlier,
    // slower request resolve AFTER a later one and overwrite the
    // row back to a color the user didn't actually pick last.
    const key = 'color-' + id;
    if (_inFlightSessionActions.has(key)) return;
    _inFlightSessionActions.add(key);
    closeAllSideDropdowns();
    const row = getChatRow(id);
    try {
        const res = await fetch(`/sessions/${id}/color/`, {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded", "X-CSRFToken": csrfToken },
            body: `color=${encodeURIComponent(color)}`
        });
        if (!res.ok) { showToast("Could not update color.", 'error'); return; }
        if (row) {
            row.dataset.color = color;
            refreshRowFromData(row);
        }
    } catch (err) { console.error(err); showToast("Network error - please try again.", 'error'); }
    finally { _inFlightSessionActions.delete(key); }
}

// ================= Bulk select =================
function toggleBulkSelectMode() {
    const isOn = document.body.classList.toggle('bulk-select-mode');
    document.getElementById('bulkSelectToggleBtn').classList.toggle('active', isOn);
    document.getElementById('bulk-action-toolbar').classList.toggle('show', isOn);
    if (!isOn) {
        document.querySelectorAll('.chat-bulk-checkbox').forEach(cb => cb.checked = false);
    }
    onBulkCheckboxChange();
}

function onBulkCheckboxChange() {
    const checked = document.querySelectorAll('.chat-bulk-checkbox:checked');
    const countEl = document.getElementById('bulk-selected-count');
    if (countEl) countEl.textContent = `${checked.length} selected`;
}

async function bulkAction(action) {
    const ids = Array.from(document.querySelectorAll('.chat-bulk-checkbox:checked')).map(cb => cb.dataset.sessionId);
    if (!ids.length) { showToast("No conversations selected.", 'info'); return; }

    const run = async () => {
        const params = new URLSearchParams();
        params.set('action', action);
        ids.forEach(id => params.append('session_ids', id));
        const res = await fetch('/sessions/bulk-action/', {
            method: "POST",
            headers: { "Content-Type": "application/x-www-form-urlencoded", "X-CSRFToken": csrfToken },
            body: params.toString()
        });
        if (!res.ok) { showToast("Bulk action failed", 'error'); return; }

        const currentSessionId = new URLSearchParams(window.location.search).get('session');
        let currentWasDeleted = false;
        ids.forEach(id => {
            const row = getChatRow(id);
            if (action === 'delete') {
                if (String(currentSessionId) === String(id)) currentWasDeleted = true;
                row?.remove();
            } else if (row) {
                row.dataset.archived = action === 'archive' ? '1' : '0';
                refreshRowFromData(row);
                moveRowToCorrectSection(row);
            }
        });
        refreshChatListChrome();
        toggleBulkSelectMode();

        if (currentWasDeleted) {
            window.location.href = '/';
            return;
        }
        const verb = action === 'delete' ? 'deleted' : action === 'archive' ? 'archived' : 'unarchived';
        showToast(`${ids.length} chat${ids.length === 1 ? '' : 's'} ${verb}`, 'info');
    };

    if (action === 'delete') {
        showConfirm({
            title: `Delete ${ids.length} conversation${ids.length === 1 ? '' : 's'}?`,
            message: 'This permanently removes the selected conversations and cannot be undone.',
            confirmLabel: 'Delete',
            danger: true,
            onConfirm: run,
        });
    } else {
        run();
    }
}

// ================= Sidebar resize + collapse =================
(function initSidebarResize() {
    const sidebar = document.getElementById('sidebar');
    const handle = document.getElementById('sidebarResizeHandle');
    if (!sidebar || !handle) return;

    const MIN_WIDTH = 200, MAX_WIDTH = 420;
    // Collapse/resize are desktop-only affordances (the collapse
    // button itself is hidden below 991px) - a stale "collapsed"
    // flag from an earlier desktop visit must never squeeze the
    // mobile overlay sidebar down to 64px on a phone.
    if (window.innerWidth > 991) {
        const savedWidth = localStorage.getItem('simba_sidebar_width');
        if (savedWidth) sidebar.style.width = `${Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, parseInt(savedWidth, 10)))}px`;
        if (localStorage.getItem('simba_sidebar_collapsed') === '1') {
            sidebar.classList.add('collapsed');
        }
    }
    updateCollapseBtnIcon();

    let dragging = false;
    handle.addEventListener('mousedown', (e) => {
        if (sidebar.classList.contains('collapsed')) return;
        dragging = true;
        handle.classList.add('resizing');
        document.body.style.userSelect = 'none';
        e.preventDefault();
    });
    document.addEventListener('mousemove', (e) => {
        if (!dragging) return;
        const width = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, e.clientX));
        sidebar.style.width = `${width}px`;
    });
    document.addEventListener('mouseup', () => {
        if (!dragging) return;
        dragging = false;
        handle.classList.remove('resizing');
        document.body.style.userSelect = '';
        localStorage.setItem('simba_sidebar_width', parseInt(sidebar.style.width, 10));
    });
})();

function updateCollapseBtnIcon() {
    const sidebar = document.getElementById('sidebar');
    const btn = document.getElementById('sidebarCollapseBtn');
    if (!sidebar || !btn) return;
    const collapsed = sidebar.classList.contains('collapsed');
    btn.innerHTML = collapsed ? '<i class="fa-solid fa-angles-right"></i>' : '<i class="fa-solid fa-angles-left"></i>';
    btn.title = collapsed ? 'Expand sidebar' : 'Collapse sidebar';
}

function toggleSidebarCollapse() {
    const sidebar = document.getElementById('sidebar');
    const collapsed = sidebar.classList.toggle('collapsed');
    localStorage.setItem('simba_sidebar_collapsed', collapsed ? '1' : '0');
    updateCollapseBtnIcon();
}

function expandSidebarAndFocusSearch() {
    const sidebar = document.getElementById('sidebar');
    if (sidebar.classList.contains('collapsed')) {
        sidebar.classList.remove('collapsed');
        localStorage.setItem('simba_sidebar_collapsed', '0');
        updateCollapseBtnIcon();
    }
    setTimeout(() => document.getElementById('chat-search-input')?.focus(), 200);
}

// ================= Mobile Drawer Controller & Gestures =================
function openMobileDrawer() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('mobile-overlay');
    if (sidebar) sidebar.classList.add('mobile-open');
    if (overlay) overlay.classList.add('show');
    document.body.style.overflow = 'hidden';
}

function closeMobileDrawer() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('mobile-overlay');
    if (sidebar) sidebar.classList.remove('mobile-open');
    if (overlay) overlay.classList.remove('show');
    document.body.style.overflow = '';
}

(function initMobileDrawer() {
    const menuBtn = document.getElementById('mobile-menu-btn');
    const closeBtn = document.getElementById('mobile-close-btn');
    const overlay = document.getElementById('mobile-overlay');
    const sidebar = document.getElementById('sidebar');

    if (menuBtn) menuBtn.addEventListener('click', openMobileDrawer);
    if (closeBtn) closeBtn.addEventListener('click', closeMobileDrawer);
    if (overlay) overlay.addEventListener('click', closeMobileDrawer);

    // Touch swipe gesture: swipe left on sidebar to dismiss drawer
    if (sidebar) {
        let touchStartX = 0;
        let touchStartY = 0;
        sidebar.addEventListener('touchstart', (e) => {
            touchStartX = e.touches[0].clientX;
            touchStartY = e.touches[0].clientY;
        }, { passive: true });

        sidebar.addEventListener('touchend', (e) => {
            const touchEndX = e.changedTouches[0].clientX;
            const touchEndY = e.changedTouches[0].clientY;
            const diffX = touchEndX - touchStartX;
            const diffY = touchEndY - touchStartY;
            // Swipe left threshold: > 60px horizontal, with minimal vertical angle
            if (diffX < -60 && Math.abs(diffX) > Math.abs(diffY) * 1.2) {
                closeMobileDrawer();
            }
        }, { passive: true });
    }

    // Close on Escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && sidebar && sidebar.classList.contains('mobile-open')) {
            closeMobileDrawer();
        }
    });
})();

function copyToClipboard(text, btn) {
    navigator.clipboard.writeText(text).then(() => {
        const original = btn.innerHTML;
        btn.innerHTML = '<i class="fa-solid fa-check"></i> COPIED!';
        setTimeout(() => btn.innerHTML = original, 2000);
    });
}

function shareChat(text) {
    if (navigator.share) {
        navigator.share({ title: "Simba Intel Log", text: text });
    } else { alert("Sharing not supported."); }
}

// ================= Prompt-context actions under an AI reply =================
// Both act on the USER message that produced this reply, not the reply
// itself - reached via .simba-block's immediately preceding sibling,
// the same DOM relationship regenerateText()/submitEditedMessage() rely on.
function getPromptSourceUserBlock(btn) {
    const simbaBlock = btn.closest('.simba-block');
    const userBlock = simbaBlock ? simbaBlock.previousElementSibling : null;
    return (userBlock && userBlock.classList.contains('user-block')) ? userBlock : null;
}

let _inFlightFollowupMsgId = null;

async function autoLoadFollowupSuggestions(simbaBlock, sessionId, messageId) {
    if (!simbaBlock) return;
    const sid = sessionId || new URLSearchParams(window.location.search).get('session');
    if (!sid) return;

    const msgId = messageId || simbaBlock.dataset.messageId;
    if (!msgId || msgId === 'None' || msgId === 'null') return;

    if (_inFlightFollowupMsgId === msgId) return;
    _inFlightFollowupMsgId = msgId;

    // Clear any stale follow-up chip containers across older conversation turns
    document.querySelectorAll('.followup-chips-container, .followup-suggestions').forEach(el => {
        if (!simbaBlock.contains(el)) {
            el.innerHTML = '';
            el.style.display = 'none';
        }
    });

    let container = simbaBlock.querySelector('.followup-chips-container') || simbaBlock.querySelector('.followup-suggestions');
    if (!container) {
        container = document.createElement('div');
        container.className = 'followup-chips-container';
        simbaBlock.appendChild(container);
    }

    container.style.display = 'flex';
    container.innerHTML = `
                    <div class="followup-loading-chip">
                        <i class="fa-solid fa-wand-magic-sparkles fa-spin"></i> Generating smart follow-ups...
                    </div>
                `;

    try {
        const followupUrl = `/session/${sid}/suggest-followups/?message_id=${encodeURIComponent(msgId)}`;
        const res = await fetch(followupUrl, { signal: AbortSignal.timeout(14000) });
        if (!res.ok) {
            container.innerHTML = '';
            container.style.display = 'none';
            return;
        }
        const data = await res.json();
        const suggestions = data.suggestions || [];
        if (!suggestions || !suggestions.length) {
            container.innerHTML = '';
            container.style.display = 'none';
            return;
        }

        container.innerHTML = `
                        <span class="followup-lead-label"><i class="fa-solid fa-wand-magic-sparkles"></i> Suggested next:</span>
                        ${suggestions.map(s => `<button type="button" class="followup-action-chip" onclick="useFollowupSuggestion(this)"><i class="fa-solid fa-arrow-turn-down-right"></i> ${escapeHtml(s)}</button>`).join('')}
                    `;
    } catch (err) {
        container.innerHTML = '';
        container.style.display = 'none';
    } finally {
        if (_inFlightFollowupMsgId === msgId) _inFlightFollowupMsgId = null;
    }
}

function suggestFollowups(btn) {
    const sessionId = new URLSearchParams(window.location.search).get('session');
    if (!sessionId) { showToast("This conversation isn't saved yet - send a message first.", 'info'); return; }
    const simbaBlock = btn.closest('.simba-block');
    const messageId = simbaBlock ? simbaBlock.dataset.messageId : '';
    autoLoadFollowupSuggestions(simbaBlock, sessionId, messageId);
}

function useFollowupSuggestion(chipBtn) {
    const input = document.getElementById('user-input');
    if (!input) return;
    // Extract suggestion text cleanly
    const text = chipBtn.innerText.replace(/^.*?Suggested next:\s*/i, '').trim();
    input.value = text;
    input.focus();
    // Dismiss suggestions on selection
    const container = chipBtn.closest('.followup-chips-container') || chipBtn.closest('.followup-suggestions');
    if (container) {
        container.style.display = 'none';
    }
    sendQuery();
}

function editPromptFromReply(btn) {
    const userBlock = getPromptSourceUserBlock(btn);
    const editBtn = userBlock ? userBlock.querySelector('.edit-msg-btn') : null;
    if (editBtn) {
        editBtn.click();
        editBtn.scrollIntoView({ block: 'center', behavior: 'smooth' });
    } else {
        alert("This message isn't ready to edit yet - try refreshing the page.");
    }
}

function copyPromptFromReply(btn) {
    const userBlock = getPromptSourceUserBlock(btn);
    const rawQueryEl = userBlock ? userBlock.querySelector('.raw-query') : null;
    const text = rawQueryEl ? rawQueryEl.value : (userBlock ? userBlock.querySelector('.content')?.innerText.trim() : '');
    if (text) copyToClipboard(text, btn);
}

// ================= FORMAT & CODE BUTTONS =================
function formatMessageBlock(block) {
    if (!block) return;
    const raw = block.querySelector(".raw-data");
    const content = block.querySelector(".markdown-content");
    if (raw && content && raw.value && raw.value.trim() !== "") {
        content.innerHTML = renderMarkdown(raw.value.trim());
        renderRichContent(block);
        applyCodeButtons(block);
    }
}

function formatAllMessages() {
    document.querySelectorAll(".simba-block").forEach(block => {
        formatMessageBlock(block);
    });
}

function codeBlockLanguageLabel(pre) {
    const codeEl = pre.querySelector("code");
    const match = codeEl && codeEl.className.match(/language-(\S+)/);
    return match ? match[1] : "text";
}

function applyCodeButtons(root) {
    // Scoped to the just-rendered container when the caller has one
    // (every new/streamed message), falling back to the whole
    // document only for the page-load pass over all history
    // (formatAllMessages) - a full-document "pre" scan on every new
    // message was O(n) in total code blocks shown so far, not O(1)
    // in the size of the new message.
    (root || document).querySelectorAll("pre").forEach(pre => {

        if (pre.querySelector(".code-toolbar-simba")) return;

        pre.style.position = "relative";
        const language = codeBlockLanguageLabel(pre);
        // Tall blocks start collapsed to a readable preview height -
        // "Expand" is one click away, never hidden entirely.
        const isTall = pre.innerText.split("\n").length > 18;
        if (isTall) pre.classList.add("code-collapsed");

        const toolbar = document.createElement("div");
        toolbar.className = "code-toolbar-simba";
        toolbar.innerHTML = `
                    <span class="code-lang-label">${language}</span>
                    <span class="code-toolbar-spacer"></span>
                    <button type="button" class="code-tool-btn code-wrap-btn" title="Toggle line wrap"><i class="fa-solid fa-arrows-left-right"></i></button>
                    ${isTall ? '<button type="button" class="code-tool-btn code-collapse-btn" title="Expand"><i class="fa-solid fa-chevron-down"></i></button>' : ''}
                    <button type="button" class="code-tool-btn code-fullscreen-btn" title="Fullscreen"><i class="fa-solid fa-expand"></i></button>
                    <button type="button" class="code-tool-btn code-copy-btn" title="Copy code"><i class="fa-regular fa-copy"></i> Copy</button>
                `;
        pre.prepend(toolbar);

        toolbar.querySelector(".code-copy-btn").onclick = () => {
            const codeElement = pre.querySelector("code");
            const codeText = codeElement ? codeElement.innerText : pre.innerText;
            const copyBtn = toolbar.querySelector(".code-copy-btn");
            navigator.clipboard.writeText(codeText).then(() => {
                copyBtn.innerHTML = '<i class="fa-solid fa-check"></i> Copied';
                setTimeout(() => { copyBtn.innerHTML = '<i class="fa-regular fa-copy"></i> Copy'; }, 2000);
            });
        };

        toolbar.querySelector(".code-wrap-btn").onclick = () => {
            pre.classList.toggle("code-wrap");
        };

        const fsBtn = toolbar.querySelector(".code-fullscreen-btn");
        fsBtn.onclick = () => {
            const nowFull = pre.classList.toggle("code-fullscreen");
            document.body.classList.toggle("code-fullscreen-active", nowFull);
            fsBtn.innerHTML = nowFull
                ? '<i class="fa-solid fa-compress"></i>'
                : '<i class="fa-solid fa-expand"></i>';
            fsBtn.title = nowFull ? "Exit fullscreen (Esc)" : "Fullscreen";
        };

        const collapseBtn = toolbar.querySelector(".code-collapse-btn");
        if (collapseBtn) {
            collapseBtn.onclick = () => {
                const nowCollapsed = pre.classList.toggle("code-collapsed");
                collapseBtn.innerHTML = nowCollapsed
                    ? '<i class="fa-solid fa-chevron-down"></i>'
                    : '<i class="fa-solid fa-chevron-up"></i>';
                collapseBtn.title = nowCollapsed ? "Expand" : "Collapse";
            };
        }
    });
}

// Esc exits code fullscreen (matches the button's "Esc" hint).
document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    const full = document.querySelector('pre.code-fullscreen');
    if (!full) return;
    full.classList.remove('code-fullscreen');
    document.body.classList.remove('code-fullscreen-active');
    const fsBtn = full.querySelector('.code-fullscreen-btn');
    if (fsBtn) {
        fsBtn.innerHTML = '<i class="fa-solid fa-expand"></i>';
        fsBtn.title = 'Fullscreen';
    }
});

// ================= Model Selector Dropdown & Filter Engine =================
function toggleModelDropdown(event) {
    if (event) {
        event.preventDefault();
        event.stopPropagation();
    }
    const selectBtn = document.getElementById("cyberSelect");
    const optionsBox = document.getElementById("cyberOptions");
    const searchInput = document.getElementById("modelSearchInput");
    if (!optionsBox || !selectBtn) return;

    const isOpen = optionsBox.classList.contains("show");
    if (isOpen) {
        closeModelDropdown();
    } else {
        optionsBox.classList.add("show");
        selectBtn.classList.add("open");
        selectBtn.setAttribute("aria-expanded", "true");
        if (searchInput) {
            searchInput.value = "";
            filterModelDropdown("");
            setTimeout(() => searchInput.focus(), 60);
        }
    }
}

function openModelDropdown(pendingPrompt) {
    if (pendingPrompt) {
        window._pendingRetryPrompt = pendingPrompt;
    }
    const selectBtn = document.getElementById("cyberSelect");
    const optionsBox = document.getElementById("cyberOptions");
    const searchInput = document.getElementById("modelSearchInput");
    if (optionsBox) optionsBox.classList.add("show");
    if (selectBtn) {
        selectBtn.classList.add("open");
        selectBtn.setAttribute("aria-expanded", "true");
    }
    if (searchInput) {
        searchInput.value = "";
        filterModelDropdown("");
        setTimeout(() => searchInput.focus(), 60);
    }
}

function closeModelDropdown() {
    const selectBtn = document.getElementById("cyberSelect");
    const optionsBox = document.getElementById("cyberOptions");
    if (optionsBox) optionsBox.classList.remove("show");
    if (selectBtn) {
        selectBtn.classList.remove("open");
        selectBtn.setAttribute("aria-expanded", "false");
    }
}

window.openModelDropdown = openModelDropdown;
window.closeModelDropdown = closeModelDropdown;

window.retryLastPrompt = function (promptText) {
    const input = document.getElementById("user-input");
    if (input && promptText) {
        input.value = promptText;
        if (typeof autoResizeComposerInput === 'function') autoResizeComposerInput(input);
    }
    const rateLimitCards = document.querySelectorAll(".rate-limit-card");
    rateLimitCards.forEach(card => {
        const simbaBlock = card.closest(".simba-block");
        if (simbaBlock) simbaBlock.remove();
    });
    if (typeof sendQuery === 'function') sendQuery();
};

function filterModelDropdown(query) {
    const q = (query || "").trim().toLowerCase();
    const clearBtn = document.getElementById("modelSearchClear");
    const emptyMsg = document.getElementById("modelSearchEmpty");
    if (clearBtn) clearBtn.style.display = q ? "inline-block" : "none";

    let visibleCount = 0;
    document.querySelectorAll(".cyber-option-group").forEach(group => {
        let groupVisible = 0;
        group.querySelectorAll(".cyber-option").forEach(opt => {
            const val = (opt.dataset.value || "").toLowerCase();
            const name = (opt.dataset.name || opt.innerText || "").toLowerCase();
            const desc = (opt.dataset.desc || "").toLowerCase();
            const match = !q || val.includes(q) || name.includes(q) || desc.includes(q);
            opt.style.display = match ? "flex" : "none";
            if (match) {
                groupVisible++;
                visibleCount++;
            }
        });
        group.style.display = groupVisible > 0 ? "block" : "none";
    });

    if (emptyMsg) {
        emptyMsg.style.display = visibleCount === 0 ? "block" : "none";
    }
}

function clearModelSearch(e) {
    if (e) {
        e.preventDefault();
        e.stopPropagation();
    }
    const searchInput = document.getElementById("modelSearchInput");
    if (searchInput) {
        searchInput.value = "";
        searchInput.focus();
    }
    filterModelDropdown("");
}

document.querySelectorAll("#cyberOptions .cyber-option").forEach(option => {
    option.addEventListener("click", async function (e) {
        e.preventDefault();
        e.stopPropagation();
        const value = this.getAttribute("data-value");
        const name = this.getAttribute("data-name") || this.querySelector('strong')?.innerText || value;

        const hiddenInput = document.getElementById("model-selector");
        const selectedText = document.getElementById("selectedText");

        if (hiddenInput) hiddenInput.value = value;
        if (selectedText) selectedText.innerText = name;

        localStorage.setItem("selected_simba_model", value);

        document.querySelectorAll("#cyberOptions .cyber-option").forEach(o => {
            o.classList.remove("active");
            const check = o.querySelector(".model-active-check");
            if (check) check.remove();
        });
        this.classList.add("active");
        if (!this.querySelector(".model-active-check")) {
            this.insertAdjacentHTML("beforeend", '<i class="fa-solid fa-check model-active-check"></i>');
        }

        // Update aspect ratio visibility
        if (typeof updateAspectRatioVisibility === 'function') updateAspectRatioVisibility();

        try {
            const currentSessionId = new URLSearchParams(window.location.search).get('session') || '';
            await fetch(`/update_model/?model_id=${encodeURIComponent(value)}&session_id=${encodeURIComponent(currentSessionId)}`);
        } catch (err) {
            // Non-fatal fallback
        }

        closeModelDropdown();

        // If a prompt was queued for retry after changing model, dispatch it now
        if (window._pendingRetryPrompt) {
            const promptToSend = window._pendingRetryPrompt;
            window._pendingRetryPrompt = null;
            const input = document.getElementById("user-input");
            if (input) {
                input.value = promptToSend;
                if (typeof autoResizeComposerInput === 'function') autoResizeComposerInput(input);
            }
            const rateLimitCards = document.querySelectorAll(".rate-limit-card");
            rateLimitCards.forEach(card => {
                const simbaBlock = card.closest(".simba-block");
                if (simbaBlock) simbaBlock.remove();
            });
            setTimeout(() => {
                if (typeof sendQuery === 'function') sendQuery();
            }, 50);
        }
    });
});

// Global listener for Escape & outside click dismissal
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        closeModelDropdown();
    }
});

window.addEventListener('click', (e) => {
    if (!e.target.closest('#cyberSelectWrapper')) {
        closeModelDropdown();
    }
});

// ================= Aspect Ratio Selector Logic =================
const aspectSelect = document.getElementById("aspectRatioSelect");
const aspectOptionsBox = document.getElementById("aspectRatioOptions");
const aspectHiddenInput = document.getElementById("aspect-ratio-selector");
const aspectText = document.getElementById("aspectRatioText");
const aspectWrapper = document.getElementById("aspectRatioWrapper");

if (aspectSelect) {
    aspectSelect.addEventListener("click", (e) => {
        e.stopPropagation();
        const isVisible = aspectOptionsBox.style.display === "block";
        aspectOptionsBox.style.display = isVisible ? "none" : "block";
        aspectSelect.classList.toggle("open");
    });

    aspectOptionsBox.querySelectorAll(".cyber-option").forEach(option => {
        option.addEventListener("click", function (e) {
            e.stopPropagation();
            const value = this.getAttribute("data-value");
            const text = this.innerText;

            aspectHiddenInput.value = value;
            aspectText.innerText = text;
            localStorage.setItem("selected_aspect_ratio", value);

            aspectOptionsBox.querySelectorAll(".cyber-option").forEach(o => o.classList.remove("active"));
            this.classList.add("active");
            aspectOptionsBox.style.display = "none";
            aspectSelect.classList.remove("open");
        });
    });
}

// ================= Function to toggle aspect ratio selector visibility =================
function updateAspectRatioVisibility() {
    const currentModel = document.getElementById("model-selector").value;
    // Check if model is image-studio (or whatever the image model ID is)
    const modelConfig = Array.from(document.querySelectorAll("#cyberOptions .cyber-option")).find(o => o.getAttribute("data-value") === currentModel);
    const isImageGenMode = !!(modelConfig && modelConfig.innerText.includes("Image"));
    aspectWrapper.style.display = isImageGenMode ? "block" : "none";

    // Attachments (Vision AI) don't apply in image-generation mode - hide the control there.
    const plusMenuWrapper = document.querySelector(".plus-menu-wrapper");
    if (plusMenuWrapper) plusMenuWrapper.style.display = isImageGenMode ? "none" : "flex";
    if (isImageGenMode) {
        closePlusMenu();
        if (typeof removeAttachment === "function") removeAttachment();
    }
    if (typeof updateComposerPlaceholder === "function") updateComposerPlaceholder();
}

function updateComposerPlaceholder() {
    const input = document.getElementById('user-input');
    if (!input) return;

    const currentModel = document.getElementById("model-selector")?.value || '';
    const modelOption = document.querySelector(`#cyberOptions .cyber-option[data-value="${currentModel}"]`);
    const isImageMode = currentModel === 'image-studio' || !!(modelOption && modelOption.innerText.toLowerCase().includes('image'));

    const sessionTypeParam = new URLSearchParams(window.location.search).get("type") || "assistant";

    if (isImageMode) {
        input.placeholder = "Describe the image you want to generate...";
    } else if (sessionTypeParam === 'agent') {
        input.placeholder = "Describe the task you want SIMBA to perform...";
    } else if (sessionTypeParam === 'voice') {
        input.placeholder = "Speak your request...";
    } else {
        input.placeholder = "Ask SIMBA anything...";
    }
}

// ================= Load saved aspect ratio =================
const savedAspectRatio = localStorage.getItem("selected_aspect_ratio");
if (savedAspectRatio) {
    aspectHiddenInput.value = savedAspectRatio;
    aspectText.innerText = savedAspectRatio;
    aspectOptionsBox.querySelectorAll(".cyber-option").forEach(o => {
        if (o.getAttribute("data-value") === savedAspectRatio) {
            o.classList.add("active");
        } else {
            o.classList.remove("active");
        }
    });
}

window.addEventListener("click", (e) => {
    if (optionsBox) optionsBox.style.display = "none";
    if (select) select.classList.remove("open");
    if (aspectOptionsBox) aspectOptionsBox.style.display = "none";
    if (aspectSelect) aspectSelect.classList.remove("open");
});

// ================= URL SYNC & HISTORY FIX =================
function updateBrowserURL(sessionId) {
    const url = new URL(window.location.href);
    if (url.searchParams.get('session') !== sessionId) {
        url.searchParams.set('session', sessionId);
        window.history.replaceState({ path: url.href }, '', url.href); // આનાથી રિફ્રેશ પર ચેટ રહેશે [cite: 2026-03-01]
    }
}

// ================= Global variable to track if we're generating an image =================
let isGeneratingImage = false;
// ================= Global variable to track if a text query is in flight =================
let isSendingQuery = false;
// ================= AbortController for the in-flight request - powers the Stop button =================
let currentAbortController = null;

// ================= Recover from the browser back/forward cache (bfcache) =================
// Navigating away mid-send (e.g. clicking Settings/Analytics while a
// reply is streaming) and then pressing Back can restore this exact
// page from bfcache instead of a fresh load - a frozen JS snapshot
// with isSendingQuery/isGeneratingImage still true, even though the
// real fetch that would have flipped them back died with the
// navigation that cached this page. Without this, the Send button
// stays permanently stuck in "Stop" mode (every click just aborts an
// already-dead controller and returns) until a hard refresh.
// event.persisted is true only for an actual bfcache restore, never
// for a normal first load, so this never runs on the common path.
window.addEventListener('pageshow', (event) => {
    if (!event.persisted) return;
    if (isSendingQuery || isGeneratingImage) {
        isSendingQuery = false;
        isGeneratingImage = false;
        currentAbortController = null;
        clearWatchdog();
        setSendButtonBusy(false);
        setStatus("status-online", "CORE ONLINE");
    }
});

// ================= Request watchdog: guarantees no request can hang forever =================
// A plain fetch() has no built-in timeout, and the streaming read loop in
// sendQuery/regenerateText/submitEditedMessage awaits reader.read() forever
// if the server or a proxy between here and it stalls without ever closing
// the connection - neither case throws, so the existing try/catch/finally
// blocks never even run. That silent hang is the actual root cause behind
// "stuck in loading" - the fix is a client-side deadline, not more error
// handling around code that IS already throwing correctly.
// Only one request is ever in flight at a time (every call site below
// checks isSendingQuery/isGeneratingImage first), so a single shared timer
// is safe - there is never a second watchdog to collide with.
let watchdogTimer = null;
let watchdogTimedOut = false;
const TEXT_REQUEST_TIMEOUT_MS = 60000;   // no new token for 60s -> abort
const IMAGE_REQUEST_TIMEOUT_MS = 100000; // Pollinations can legitimately take up to ~a minute

function armWatchdog(controller, timeoutMs) {
    clearWatchdog();
    watchdogTimedOut = false;
    watchdogTimer = setTimeout(() => {
        watchdogTimedOut = true;
        controller.abort();
    }, timeoutMs);
}

function resetWatchdog(controller, timeoutMs) {
    if (watchdogTimer) armWatchdog(controller, timeoutMs);
}

function clearWatchdog() {
    if (watchdogTimer) {
        clearTimeout(watchdogTimer);
        watchdogTimer = null;
    }
}

function setSendButtonBusy(isBusy) {
    const btn = document.querySelector(".send-btn");
    if (!btn) return;
    btn.innerHTML = isBusy
        ? '<i class="fa-solid fa-stop"></i>'
        : '<i class="fa-solid fa-chevron-right"></i>';
    btn.classList.toggle("stop-mode", isBusy);
    btn.title = isBusy ? "Stop generating" : "Send";
    btn.setAttribute("aria-label", isBusy ? "Stop generating" : "Send");
}

// ================= Update the CORE_STATUS indicator - shared by sendQuery/sendImageQuery/regenerateText =================
function setStatus(state, text) {
    const el = document.getElementById("aiStatus");
    if (!el) return;
    el.className = "ai-status " + state;
    const textEl = el.querySelector(".status-text");
    if (textEl) textEl.innerText = text;
}

// ================= HTML-escape untrusted text before ever inserting it via innerHTML =================
// ================= LaTeX -> KaTeX, then markdown, then sanitize =================
// Math has to be pulled out and rendered *before* marked.parse() runs -
// markdown syntax chars (_, *, etc.) are also valid inside LaTeX
// (subscripts, multiplication), so parsing markdown first would mangle
// the math source. Rendered KaTeX HTML is swapped back in by placeholder
// token after marked.parse() finishes, then the whole thing is
// sanitized once at the end - DOMPurify's default allowlist covers
// KaTeX's span-based output fine as long as output:'html' skips its
// optional MathML annotation block, which isn't in that allowlist.
// Runs on every streamed token (cheap: regex only matches *complete*
// $...$/$$...$$ pairs, so incomplete LaTeX simply doesn't match yet
// and renders once the closing delimiter arrives) - unlike Mermaid
// diagrams below, which need the full response and real DOM nodes,
// so those stay a separate post-completion step.
function renderMarkdown(text) {
    const mathBlocks = [];
    const stash = (expr, displayMode) => {
        const idx = mathBlocks.length;
        try {
            mathBlocks.push(katex.renderToString(expr.trim(), { throwOnError: false, output: 'html', displayMode }));
        } catch (e) {
            mathBlocks.push(escapeHtml(displayMode ? `$$${expr}$$` : `$${expr}$`));
        }
        return `@@MATH_BLOCK_${idx}@@`;
    };

    let processed = text;
    if (window.katex) {
        processed = processed.replace(/\$\$([\s\S]+?)\$\$/g, (_, expr) => stash(expr, true));
        processed = processed.replace(/\$([^\$\n]+?)\$/g, (_, expr) => stash(expr, false));
    }

    let html = marked.parse(processed);
    html = html.replace(/@@MATH_BLOCK_(\d+)@@/g, (_, idx) => mathBlocks[parseInt(idx, 10)]);

    // Fail closed, not open: if the DOMPurify CDN script didn't load
    // (network hiccup, blocked host, CDN outage), this must NEVER
    // fall through to inserting marked.parse()'s raw, unsanitized
    // HTML via innerHTML - that would turn any HTML/script markup an
    // AI reply happens to contain into a real DOM injection. Falling
    // back to escaped plain text is safe and keeps the reply
    // readable; a real fix (reload) is one refresh away.
    if (!window.DOMPurify) return escapeHtml(text);
    return DOMPurify.sanitize(html);
}

// ================= Throttled streaming markdown renderer =================
// Shared by every streaming loop (send/regenerate/continue/edit).
// Re-parsing the whole accumulated response (renderMarkdown does a
// full marked.parse + DOMPurify.sanitize pass) and forcing a
// synchronous scrollHeight/scrollTop layout read+write on every
// single network chunk is unbounded, roughly quadratic-in-response-
// length work for no visible benefit - only the state right before
// each paint is ever actually seen. Coalescing to at most one
// update per animation frame (originally done only for the main
// send flow) fixes that everywhere a response streams in.
//
// `cf` (the scroll container) is optional - edit's loop never
// auto-scrolled before this helper existed (editing happens
// mid-conversation, not necessarily at the bottom), and passing no
// `cf` here preserves that exact behavior instead of introducing a
// new scroll no caller asked for.
function createThrottledStreamRenderer(getMarkdownDiv, getText, cf) {
    let latestIsAtBottom = true;
    let rafHandle = null;
    const flush = () => {
        rafHandle = null;
        const markdownDiv = getMarkdownDiv();
        if (markdownDiv) markdownDiv.innerHTML = renderMarkdown(getText());
        if (cf && latestIsAtBottom) cf.scrollTop = cf.scrollHeight;
    };
    return {
        schedule() {
            if (cf) latestIsAtBottom = cf.scrollHeight - cf.clientHeight <= cf.scrollTop + 100;
            if (rafHandle === null) rafHandle = requestAnimationFrame(flush);
        },
        // Guarantees the final chunk is rendered even if a throttled
        // update was still pending when the stream ended - call this
        // exactly once, unconditionally, right after the read loop.
        flushNow() {
            if (rafHandle !== null) cancelAnimationFrame(rafHandle);
            flush();
        },
    };
}

if (window.mermaid) {
    mermaid.initialize({ startOnLoad: false, theme: 'dark', securityLevel: 'strict' });
}

// Every markdown image (![alt](url), including the real,
// SearXNG-matched ones the backend now rewrites hallucinated web-
// search images into - see chat/views.py's _rewrite_images_in_stream)
// renders through this fixed-size, lazy-loaded, skeleton-then-fade-in
// wrapper instead of a bare <img> - keeps every image the same size
// (no oversized/stretched images) and never shows a broken-image
// icon (onerror removes the wrapper outright).
if (window.marked) {
    marked.use({
        renderer: {
            image(hrefOrToken, title, text) {
                let href = hrefOrToken, altText = text, titleText = title;
                if (hrefOrToken && typeof hrefOrToken === 'object') {
                    href = hrefOrToken.href;
                    titleText = hrefOrToken.title;
                    altText = hrefOrToken.text;
                }
                const safeHref = escapeHtml(href || '');
                const safeAlt = escapeHtml(altText || '');
                const titleAttr = titleText ? ` title="${escapeHtml(titleText)}"` : '';
                return `<span class="md-img-wrap"><img class="md-img" src="${safeHref}" alt="${safeAlt}"${titleAttr} loading="lazy" decoding="async" onload="this.closest('.md-img-wrap').classList.add('loaded')" onerror="this.closest('.md-img-wrap').remove()"></span>`;
            },
        },
    });
}

// Turns ```mermaid fenced code blocks (already rendered as
// <pre><code class="language-mermaid">) into live diagrams. Only
// called once a reply is fully streamed (see the renderRichContent()
// call sites) since a half-streamed diagram definition is usually
// invalid syntax.
function renderMermaidBlocks(container) {
    if (!window.mermaid || !container) return;
    const blocks = container.querySelectorAll('code.language-mermaid');
    blocks.forEach(code => {
        const pre = code.closest('pre');
        if (!pre) return;
        const div = document.createElement('div');
        div.className = 'mermaid';
        div.textContent = code.textContent;
        pre.replaceWith(div);
    });
    try {
        const targets = container.querySelectorAll('.mermaid');
        if (targets.length) mermaid.run({ nodes: targets });
    } catch (e) {
        console.error('Mermaid render failed (non-fatal - shown as text instead):', e);
    }
}

// Single place every "a reply just finished streaming" call site
// reaches for post-processing: syntax highlighting (existing),
// mermaid diagrams (new). Math is already handled inline by
// renderMarkdown() above, so it needs no separate pass here.
function renderRichContent(container) {
    if (!container) return;
    // The line-numbers plugin only activates for a <pre> that already
    // has this class at highlight time (it hooks into Prism's own
    // "complete" callback) - marked.js never adds it, so every fenced
    // code block needs it added here, before Prism runs.
    container.querySelectorAll("pre").forEach(pre => pre.classList.add("line-numbers"));
    if (window.Prism) Prism.highlightAllUnder(container);
    renderMermaidBlocks(container);
    applyCodeBlockCards(container);
}

function applyCodeBlockCards(container) {
    if (!container) return;
    const pres = container.querySelectorAll("pre");
    pres.forEach(pre => {
        if (pre.closest('.code-block-card')) return;
        const code = pre.querySelector('code');
        let lang = 'CODE';
        if (code) {
            const classList = Array.from(code.classList);
            const langClass = classList.find(c => c.startsWith('language-'));
            if (langClass) lang = langClass.replace('language-', '').toUpperCase();
        }

        const wrapper = document.createElement('div');
        wrapper.className = 'code-block-card';
        wrapper.innerHTML = `
                        <div class="code-card-header">
                            <span class="code-card-lang"><i class="fa-solid fa-code"></i> ${escapeHtml(lang)}</span>
                            <button type="button" class="code-card-copy-btn" onclick="copyCodeBlockFromBtn(this)" title="Copy Code">
                                <i class="fa-regular fa-copy"></i> Copy
                            </button>
                        </div>
                    `;
        pre.parentNode.insertBefore(wrapper, pre);
        wrapper.appendChild(pre);
    });
}

function copyCodeBlockFromBtn(btn) {
    const card = btn.closest('.code-block-card');
    if (!card) return;
    const pre = card.querySelector('pre');
    const text = pre ? pre.innerText : '';
    navigator.clipboard.writeText(text).then(() => {
        const orig = btn.innerHTML;
        btn.innerHTML = '<i class="fa-solid fa-check"></i> Copied!';
        btn.classList.add('copied');
        showSimbaToast('Code copied to clipboard', 'success', 2000);
        setTimeout(() => {
            btn.innerHTML = orig;
            btn.classList.remove('copied');
        }, 2000);
    });
}

// ================= Plus button popover (Camera / Gallery / File Upload) =================
function togglePlusMenu(e) {
    if (e) e.stopPropagation();
    const menu = document.getElementById("plusMenu");
    if (menu) menu.classList.toggle("show");
}

function closePlusMenu() {
    const menu = document.getElementById("plusMenu");
    if (menu) menu.classList.remove("show");
}

function triggerFilePicker(kind) {
    const input = document.getElementById("attach-input");
    if (!input) return;
    if (kind === "image") {
        input.accept = ".jpg,.jpeg,.png,.webp,.gif,.bmp";
    } else if (kind === "pdf") {
        input.accept = ".pdf";
    } else {
        input.accept = ".pdf,.csv,.txt,.jpg,.jpeg,.png,.webp,.gif,.bmp";
    }
    input.click();
}

document.addEventListener("click", (e) => {
    const wrapper = document.querySelector(".plus-menu-wrapper");
    if (wrapper && !wrapper.contains(e.target)) closePlusMenu();
});

// ================= File attach / paste / drag-drop / camera capture (Vision AI + document context) =================
let pendingAttachments = []; // [{file, name, size, isImage, previewUrl}], sent with the next sendQuery()
let cameraStream = null;

const ACCEPTED_ATTACHMENT_RE = /\.(jpe?g|png|webp|gif|bmp|pdf|csv|tsv|txt|md|json|xml|yaml|yml|log|env|sql|ini|cfg|conf|toml|py|js|jsx|ts|tsx|html|css|scss|sass|java|c|cpp|cc|cxx|h|hpp|cs|rs|go|php|rb|swift|kt|sh|bash|zsh|bat|ps1|doc|docx)$/i;
const ACCEPTED_IMAGE_RE = /\.(jpe?g|png|webp|gif|bmp)$/i;
const MAX_ATTACHMENTS = 6;
const MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024; // mirrors the backend's per-file limit

function formatFileSize(bytes) {
    if (!bytes || bytes <= 0) return '0 B';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function getFileIconClass(filename) {
    const ext = (filename || "").split('.').pop().toLowerCase();
    if (['jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp'].includes(ext)) return 'fa-regular fa-image';
    if (ext === 'pdf') return 'fa-solid fa-file-pdf';
    if (['py', 'js', 'jsx', 'ts', 'tsx', 'html', 'css', 'scss', 'sass', 'java', 'c', 'cpp', 'cc', 'cxx', 'h', 'hpp', 'cs', 'rs', 'go', 'php', 'rb', 'swift', 'kt', 'sh', 'bash', 'zsh', 'bat', 'ps1', 'sql'].includes(ext)) {
        return 'fa-solid fa-file-code';
    }
    if (['txt', 'md', 'json', 'xml', 'yaml', 'yml', 'log', 'env', 'csv', 'tsv', 'ini', 'cfg', 'conf', 'toml'].includes(ext)) {
        return 'fa-solid fa-file-lines';
    }
    return 'fa-regular fa-file';
}

function isDuplicateAttachment(file) {
    return pendingAttachments.some(a => a.name === file.name && a.size === file.size);
}

function addAttachment(file) {
    if (!file) return;
    if (!ACCEPTED_ATTACHMENT_RE.test(file.name)) {
        alert(`Unsupported file type: ${file.name}`);
        return;
    }
    if (file.size > MAX_ATTACHMENT_BYTES) {
        alert(`${file.name} is too large (max 10MB)`);
        return;
    }
    if (isDuplicateAttachment(file)) return; // never upload the same file twice
    if (pendingAttachments.length >= MAX_ATTACHMENTS) {
        alert(`You can attach up to ${MAX_ATTACHMENTS} files`);
        return;
    }

    const isImage = ACCEPTED_IMAGE_RE.test(file.name);
    const entry = { file, name: file.name, size: file.size, isImage, previewUrl: null };
    pendingAttachments.push(entry);
    renderAttachmentPreviews();

    if (isImage) {
        const reader = new FileReader();
        reader.onload = () => {
            entry.previewUrl = reader.result;
            renderAttachmentPreviews();
        };
        reader.readAsDataURL(file);
    }
}

function addAttachments(fileList) {
    Array.from(fileList || []).forEach(addAttachment);
}

function removeAttachmentAt(index) {
    pendingAttachments.splice(index, 1);
    renderAttachmentPreviews();
}

function removeAttachment() {
    pendingAttachments = [];
    renderAttachmentPreviews();
    const input = document.getElementById("attach-input");
    if (input) input.value = "";
}

function renderAttachmentPreviews() {
    const preview = document.getElementById("attachment-preview");
    if (!preview) return;
    if (pendingAttachments.length === 0) {
        preview.style.display = "none";
        preview.innerHTML = "";
        if (typeof renderQuickActions === 'function') renderQuickActions();
        return;
    }
    if (typeof renderQuickActions === 'function') renderQuickActions();
    preview.style.display = "flex";
    preview.style.cssText += "flex-wrap:wrap; gap:8px; margin-bottom:8px;";
    preview.innerHTML = pendingAttachments.map((a, i) => `
                <div class="attachment-chip" data-index="${i}" title="Click to preview">
                    ${a.isImage
            ? (a.previewUrl ? `<img src="${a.previewUrl}" alt="${escapeHtml(a.name)}">` : `<div class="attachment-chip-placeholder"></div>`)
            : `<i class="${getFileIconClass(a.name)}"></i>`}
                    <div class="attachment-chip-meta">
                        <span class="attachment-chip-name">${escapeHtml(a.name)}</span>
                        <span class="attachment-chip-size">${formatFileSize(a.size)}</span>
                    </div>
                    <button type="button" class="attachment-chip-remove" aria-label="Remove ${escapeHtml(a.name)}"><i class="fa-solid fa-xmark"></i></button>
                </div>
            `).join("");
}

// ================= Attachment Viewers & Modals =================
let currentReaderContent = "";

function openAttachmentImageViewer(url, name, size) {
    const modal = document.getElementById("attachmentImageViewerModal");
    const img = document.getElementById("attachmentImageModalImg");
    const title = document.getElementById("attachmentImageModalTitle");
    const downloadBtn = document.getElementById("attachmentImageDownloadBtn");
    const openTabBtn = document.getElementById("attachmentImageOpenTabBtn");
    if (!modal || !img) return;

    img.src = url;
    if (title) title.textContent = name || "Image Preview";
    const dlUrl = url.startsWith("data:") ? url : (url.includes("?") ? `${url}&download=1` : `${url.replace(/\/+$/, "")}/?download=1`);
    if (downloadBtn) {
        downloadBtn.href = dlUrl;
        downloadBtn.setAttribute("download", name || "image.png");
    }
    if (openTabBtn) {
        openTabBtn.href = url;
    }
    modal.classList.add("show");
}

function detectLangForPrism(filename) {
    const ext = (filename || "").split('.').pop().toLowerCase();
    const map = {
        js: 'javascript', jsx: 'javascript', ts: 'typescript', tsx: 'typescript',
        py: 'python', html: 'markup', xml: 'markup', css: 'css', scss: 'css',
        json: 'json', md: 'markdown', yaml: 'yaml', yml: 'yaml', sql: 'sql',
        sh: 'bash', bash: 'bash', zsh: 'bash', java: 'java', c: 'c', cpp: 'cpp',
        cs: 'csharp', rs: 'rust', go: 'go', php: 'php', rb: 'ruby',
    };
    return map[ext] || 'none';
}

async function openAttachmentViewer(attachmentId, name, fileType, url) {
    const modal = document.getElementById("attachmentReaderModal");
    const title = document.getElementById("attachmentReaderTitle");
    const icon = document.getElementById("attachmentReaderIcon");
    const body = document.getElementById("attachmentReaderBody");
    const downloadBtn = document.getElementById("attachmentReaderDownloadBtn");
    const copyBtn = document.getElementById("attachmentReaderCopyBtn");
    if (!modal || !body) return;

    if (title) title.textContent = name || "Attachment Viewer";
    if (icon) icon.className = getFileIconClass(name);
    const viewUrl = url || `/attachments/${attachmentId}/`;
    const dlUrl = viewUrl.includes("?") ? `${viewUrl}&download=1` : `${viewUrl.replace(/\/+$/, "")}/?download=1`;
    if (downloadBtn) {
        downloadBtn.href = dlUrl;
        downloadBtn.setAttribute("download", name || "attachment");
    }
    if (copyBtn) copyBtn.style.display = (fileType === "pdf") ? "none" : "inline-flex";

    modal.classList.add("show");
    body.className = "attachment-modal-body";

    if (fileType === "pdf") {
        body.classList.add("attachment-pdf-body");
        body.innerHTML = `<iframe class="attachment-pdf-iframe" src="${viewUrl}" title="${escapeHtml(name)}"></iframe>`;
        currentReaderContent = "";
        return;
    }

    body.classList.add("attachment-code-body");
    body.innerHTML = `<div style="padding: 24px; text-align: center; color: var(--text-dim);"><i class="fa-solid fa-spinner fa-spin"></i> Loading content...</div>`;

    try {
        const res = await fetch(`/attachments/${attachmentId}/content/`);
        if (!res.ok) throw new Error("Failed to load attachment content");
        const data = await res.json();
        if (data.status === "success" && data.content !== undefined) {
            currentReaderContent = data.content;
            const lang = detectLangForPrism(name);
            const truncatedNotice = data.truncated ? `<div style="padding: 6px 12px; background: rgba(255,185,80,0.15); color: #ffb950; font-size: 11px; font-family: monospace; border-bottom: 1px solid rgba(255,185,80,0.2);">Showing first 500 KB of file. Use Download for complete file.</div>` : "";
            body.innerHTML = `${truncatedNotice}<pre class="attachment-code-pre line-numbers"><code class="language-${lang}">${escapeHtml(data.content)}</code></pre>`;
            if (window.Prism) Prism.highlightAllUnder(body);
        } else if (data.status === "success" && data.file_type === "image") {
            closeAttachmentModals();
            openAttachmentImageViewer(data.url, data.name, data.size);
        } else {
            body.innerHTML = `
                        <div style="padding: 40px 20px; text-align: center; color: var(--text-dim);">
                            <i class="${getFileIconClass(name)}" style="font-size: 40px; margin-bottom: 16px; color: var(--accent);"></i>
                            <div style="font-size: 13px; font-weight: 500; color: var(--text);">${escapeHtml(name)}</div>
                            <div style="font-size: 11px; margin-top: 4px; margin-bottom: 20px;">Binary file preview unavailable.</div>
                            <a class="attachment-modal-btn" href="${dlUrl}" download="${escapeHtml(name)}"><i class="fa-solid fa-download"></i> Download File</a>
                        </div>
                    `;
        }
    } catch (err) {
        body.innerHTML = `
                    <div style="padding: 40px 20px; text-align: center; color: var(--text-dim);">
                        <div style="color: #ff5555; margin-bottom: 12px;"><i class="fa-solid fa-triangle-exclamation"></i> Could not load preview</div>
                        <div style="font-size: 11px; margin-bottom: 18px;">${escapeHtml(err.message || "Unknown error")}</div>
                        <a class="attachment-modal-btn" href="${dlUrl}" download="${escapeHtml(name)}"><i class="fa-solid fa-download"></i> Download File</a>
                    </div>
                `;
    }
}

function openPendingFileViewer(index) {
    const att = pendingAttachments[index];
    if (!att) return;
    if (att.isImage && att.previewUrl) {
        openAttachmentImageViewer(att.previewUrl, att.name, att.size);
        return;
    }
    const modal = document.getElementById("attachmentReaderModal");
    const title = document.getElementById("attachmentReaderTitle");
    const icon = document.getElementById("attachmentReaderIcon");
    const body = document.getElementById("attachmentReaderBody");
    const downloadBtn = document.getElementById("attachmentReaderDownloadBtn");
    const copyBtn = document.getElementById("attachmentReaderCopyBtn");
    if (!modal || !body) return;

    if (title) title.textContent = att.name;
    if (icon) icon.className = getFileIconClass(att.name);
    const blobUrl = URL.createObjectURL(att.file);
    if (downloadBtn) {
        downloadBtn.href = blobUrl;
        downloadBtn.setAttribute("download", att.name);
    }
    if (copyBtn) copyBtn.style.display = (att.name.toLowerCase().endsWith('.pdf')) ? "none" : "inline-flex";

    modal.classList.add("show");
    body.className = "attachment-modal-body";

    if (att.name.toLowerCase().endsWith('.pdf')) {
        body.classList.add("attachment-pdf-body");
        body.innerHTML = `<iframe class="attachment-pdf-iframe" src="${blobUrl}" title="${escapeHtml(att.name)}"></iframe>`;
        currentReaderContent = "";
        return;
    }

    body.classList.add("attachment-code-body");
    const reader = new FileReader();
    reader.onload = (e) => {
        const text = e.target.result;
        currentReaderContent = text;
        const lang = detectLangForPrism(att.name);
        body.innerHTML = `<pre class="attachment-code-pre line-numbers"><code class="language-${lang}">${escapeHtml(text)}</code></pre>`;
        if (window.Prism) Prism.highlightAllUnder(body);
    };
    reader.onerror = () => {
        body.innerHTML = `<div style="padding: 24px; text-align: center; color: #ff5555;">Could not read local file.</div>`;
    };
    reader.readAsText(att.file.slice(0, 500 * 1024));
}

function copyAttachmentReaderContent() {
    if (!currentReaderContent) return;
    navigator.clipboard.writeText(currentReaderContent).then(() => {
        const btn = document.getElementById("attachmentReaderCopyBtn");
        if (btn) {
            const original = btn.innerHTML;
            btn.innerHTML = '<i class="fa-solid fa-check"></i> Copied!';
            setTimeout(() => { btn.innerHTML = original; }, 2000);
        }
    });
}

function closeAttachmentModals() {
    document.getElementById("attachmentImageViewerModal")?.classList.remove("show");
    const readerModal = document.getElementById("attachmentReaderModal");
    if (readerModal) {
        readerModal.classList.remove("show");
        const body = document.getElementById("attachmentReaderBody");
        if (body) body.innerHTML = "";
    }
    currentReaderContent = "";
}

// ================= Email verification modal =================
function dismissVerifyModal() {
    document.getElementById('verifyEmailModal')?.classList.add('dismissed');
}

function resendVerificationEmail() {
    const btn = document.getElementById('resendVerifyBtn');
    if (!btn || btn.disabled) return;
    btn.disabled = true;
    const original = btn.innerHTML;
    btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Sending...';
    fetch('/verification/resend/', {
        method: 'POST',
        headers: { 'X-CSRFToken': csrfToken },
        signal: AbortSignal.timeout(15000),
    })
        .then(res => res.json().then(data => ({ ok: res.ok, data })))
        .then(({ ok, data }) => {
            btn.innerHTML = ok ? '<i class="fa-solid fa-check"></i> Sent!' : original;
            if (!ok) alert(data.error || 'Could not resend the verification email.');
            setTimeout(() => { btn.innerHTML = original; btn.disabled = false; }, 3000);
        })
        .catch(() => {
            btn.innerHTML = original;
            btn.disabled = false;
            alert('Network error - please try again.');
        });
}

function refreshVerificationStatus() {
    fetch('/verification/status/', { signal: AbortSignal.timeout(10000) })
        .then(res => res.json())
        .then(data => {
            if (data.verified) {
                window.location.reload();
            } else {
                alert("Still not verified yet - check your inbox (and spam folder) for the confirmation link.");
            }
        })
        .catch(() => alert('Network error - please try again.'));
}

// ================= Chat state preservation (Settings/Analytics round-trip) =================
// Settings and Analytics are real separate pages (not modals), so
// "return to the exact conversation" means saving what's on screen
// into sessionStorage right before navigating away, then restoring
// it once we land back on this same conversation. Scoped to
// sessionStorage (not localStorage) deliberately - it's tab-local
// and self-expiring, so it can never leak into a different tab or
// stick around forever like a stale localStorage key would.
const CHAT_STATE_KEY = 'simba_chat_state';
const CHAT_STATE_MAX_ATTACHMENT_BYTES = 4 * 1024 * 1024;
const CHAT_STATE_MAX_AGE_MS = 60 * 60 * 1000;

function saveChatStateBeforeLeaving() {
    try {
        const sessionId = new URLSearchParams(window.location.search).get('session') || '';
        const userInput = document.getElementById('user-input');
        const modelSelector = document.getElementById('model-selector');
        const aspectSelector = document.getElementById('aspect-ratio-selector');
        const chatFlow = document.getElementById('chat-flow');

        // Only image attachments can be preserved without extra async
        // encoding work (their data URI is already computed for the
        // preview thumbnail) - and only if they fit comfortably under
        // sessionStorage's per-origin quota alongside everything else.
        let attachments = [];
        if (typeof pendingAttachments !== 'undefined' && pendingAttachments.length) {
            const imageEntries = pendingAttachments.filter(a => a.isImage && a.previewUrl);
            const approxBytes = imageEntries.reduce((sum, a) => sum + a.previewUrl.length * 0.75, 0);
            if (approxBytes <= CHAT_STATE_MAX_ATTACHMENT_BYTES) {
                attachments = imageEntries.map(a => ({ name: a.name, dataUrl: a.previewUrl }));
            }
        }

        const state = {
            sessionId,
            scrollTop: chatFlow ? chatFlow.scrollTop : 0,
            draftText: userInput ? userInput.value : '',
            selectedModel: modelSelector ? modelSelector.value : '',
            aspectRatio: aspectSelector ? aspectSelector.value : '',
            attachments,
            savedAt: Date.now(),
        };
        sessionStorage.setItem(CHAT_STATE_KEY, JSON.stringify(state));
    } catch (e) {
        console.error('Could not save chat state before navigating away (non-fatal):', e);
    }
}

// ================= Authoritative Composer Auto-Resize Engine =================
function autoResizeComposerInput(targetInput) {
    const el = targetInput || document.getElementById("user-input");
    if (!el) return;
    const MIN_HEIGHT = 36;
    const MAX_HEIGHT = 140;

    if (!el.value || el.value === "") {
        el.style.height = `${MIN_HEIGHT}px`;
        el.style.overflowY = "hidden";
        return;
    }

    el.style.height = "auto";
    const measured = el.scrollHeight;
    if (measured > MAX_HEIGHT) {
        el.style.height = `${MAX_HEIGHT}px`;
        el.style.overflowY = "auto";
    } else if (measured <= MIN_HEIGHT) {
        el.style.height = `${MIN_HEIGHT}px`;
        el.style.overflowY = "hidden";
    } else {
        el.style.height = `${measured}px`;
        el.style.overflowY = "hidden";
    }
}

async function restoreChatStateIfPresent() {
    let raw;
    try {
        raw = sessionStorage.getItem(CHAT_STATE_KEY);
    } catch (e) { return; }
    if (!raw) return;
    sessionStorage.removeItem(CHAT_STATE_KEY);

    let state;
    try { state = JSON.parse(raw); } catch (e) { return; }
    if (!state.savedAt || Date.now() - state.savedAt > CHAT_STATE_MAX_AGE_MS) return;

    // Only apply draft/model/attachment state if we actually landed
    // back on the same conversation it was saved from - otherwise a
    // "New chat" click right after Settings would resurrect a stale
    // draft that belongs to a different (or no) session.
    const currentSessionId = new URLSearchParams(window.location.search).get('session') || '';
    if ((state.sessionId || '') !== currentSessionId) return;

    const userInput = document.getElementById('user-input');
    const modelSelector = document.getElementById('model-selector');
    const aspectSelector = document.getElementById('aspect-ratio-selector');
    const chatFlow = document.getElementById('chat-flow');

    if (userInput) {
        if (state.draftText) userInput.value = state.draftText;
        autoResizeComposerInput(userInput);
    }
    if (state.selectedModel) {
        const option = document.querySelector(`#cyberOptions .cyber-option[data-value="${CSS.escape(state.selectedModel)}"]`);
        if (option && modelSelector && modelSelector.value !== state.selectedModel) option.click();
    }
    if (state.aspectRatio) {
        const option = document.querySelector(`#aspectRatioOptions .cyber-option[data-value="${CSS.escape(state.aspectRatio)}"]`);
        if (option && aspectSelector && aspectSelector.value !== state.aspectRatio) option.click();
    }
    if (chatFlow && state.scrollTop) {
        // Wait for layout (boot animation, markdown, images) to settle
        // before applying scroll, or it gets stomped by later reflow.
        requestAnimationFrame(() => { requestAnimationFrame(() => { chatFlow.scrollTop = state.scrollTop; }); });
    }
    if (Array.isArray(state.attachments)) {
        for (const att of state.attachments) {
            try {
                const res = await fetch(att.dataUrl);
                const blob = await res.blob();
                addAttachment(new File([blob], att.name, { type: blob.type }));
            } catch (e) {
                console.error('Could not restore attachment (non-fatal):', att.name, e);
            }
        }
    }
}
window.addEventListener('load', restoreChatStateIfPresent);

// Event delegation: clicking a chip previews it (image -> lightbox, file ->
// opens in a new tab); clicking the remove button removes it instead.
document.getElementById("attachment-preview").addEventListener("click", (e) => {
    const chip = e.target.closest(".attachment-chip");
    if (!chip) return;
    const index = parseInt(chip.dataset.index, 10);
    const attachment = pendingAttachments[index];
    if (!attachment) return;

    if (e.target.closest(".attachment-chip-remove")) {
        removeAttachmentAt(index);
        return;
    }
    if (attachment.isImage && attachment.previewUrl) {
        openAttachmentImageViewer(attachment.previewUrl, attachment.name, attachment.size);
    } else if (!attachment.isImage) {
        openPendingFileViewer(index);
    }
});

document.getElementById("attach-input").addEventListener("change", (e) => {
    addAttachments(e.target.files);
    e.target.value = ""; // allow re-selecting the same file later
});

// ----- Paste (Ctrl+V) - ChatGPT-style clipboard image paste -----
document.getElementById("user-input").addEventListener("paste", (e) => {
    const items = e.clipboardData && e.clipboardData.items;
    if (!items) return;
    let pastedImage = false;
    for (const item of items) {
        if (item.kind === "file" && item.type.startsWith("image/")) {
            const file = item.getAsFile();
            if (!file) continue;
            const ext = (item.type.split("/")[1] || "png").replace("jpeg", "jpg");
            const hasRealName = file.name && !/^image\.(png|jpe?g)$/i.test(file.name);
            const named = hasRealName ? file : new File([file], `pasted-image-${Date.now()}.${ext}`, { type: file.type });
            addAttachment(named);
            pastedImage = true;
        }
    }
    if (pastedImage) e.preventDefault();
});

// ----- Drag & Drop -----
(function setupDragAndDrop() {
    const dropTarget = document.querySelector(".command-box");
    if (!dropTarget) return;
    let dragDepth = 0;
    dropTarget.addEventListener("dragenter", (e) => {
        e.preventDefault();
        dragDepth++;
        dropTarget.classList.add("drag-active");
    });
    dropTarget.addEventListener("dragover", (e) => e.preventDefault());
    dropTarget.addEventListener("dragleave", (e) => {
        e.preventDefault();
        dragDepth = Math.max(0, dragDepth - 1);
        if (dragDepth === 0) dropTarget.classList.remove("drag-active");
    });
    dropTarget.addEventListener("drop", (e) => {
        e.preventDefault();
        dragDepth = 0;
        dropTarget.classList.remove("drag-active");
        if (e.dataTransfer && e.dataTransfer.files) addAttachments(e.dataTransfer.files);
    });
})();

async function openCameraCapture() {
    const modal = document.getElementById("camera-modal");
    const video = document.getElementById("camera-video");
    try {
        cameraStream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment" } });
        video.srcObject = cameraStream;
        modal.style.display = "flex";
    } catch (err) {
        console.error("Camera access failed:", err);
        alert("Could not access the camera. Check browser permissions.");
    }
}

function closeCameraCapture() {
    const modal = document.getElementById("camera-modal");
    modal.style.display = "none";
    if (cameraStream) {
        cameraStream.getTracks().forEach(track => track.stop());
        cameraStream = null;
    }
}

function capturePhoto() {
    const video = document.getElementById("camera-video");
    const canvas = document.getElementById("camera-canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d").drawImage(video, 0, 0);
    canvas.toBlob((blob) => {
        const name = `camera-capture-${Date.now()}.jpg`;
        addAttachment(new File([blob], name, { type: "image/jpeg" }));
        closeCameraCapture();
    }, "image/jpeg", 0.9);
}

// ================= Canonical User Message Renderer =================
function renderCanonicalUserMessageHTML({ query, attachmentsHTML = '', userMessageId = '' }) {
    const escapedQuery = escapeHtml(query || '');
    const userDisplayName = "DHRUV SHAH";
    const userInitial = "D";
    const msgIdAttr = userMessageId ? ` data-message-id="${escapeHtml(userMessageId)}"` : '';

    return `<div class="chat-block user-block"${msgIdAttr}>
<span class="msg-label"><div class="avatar user">${userInitial}</div>${userDisplayName}_INPUT</span>
<div class="content">${escapedQuery}${attachmentsHTML}</div>
<textarea class="raw-query" style="display:none;">${escapedQuery}</textarea>
<button class="edit-msg-btn" onclick="editUserMessage(this)" title="Edit and regenerate" aria-label="Edit message"><i class="fa-solid fa-pen"></i></button>
<button class="edit-msg-btn delete-msg-btn" onclick="deleteMessage(this)" title="Delete message" aria-label="Delete message" style="right: calc(100% + 42px);"><i class="fa-solid fa-trash"></i></button>
</div>`;
}

// ================= Canonical Assistant Message Actions Renderer =================
function renderCanonicalAssistantActionsHTML({
    messageId = '',
    bookmarked = false,
    showBranchSwitcher = false,
    siblingIds = [],
    siblingIndex = 1,
    siblingCount = 1,
    showFollowups = true,
} = {}) {
    const msgIdAttr = messageId ? ` data-message-id="${escapeHtml(messageId)}"` : '';
    const bookmarkIconClass = bookmarked ? 'fa-solid' : 'fa-regular';
    const bookmarkActiveClass = bookmarked ? ' active' : '';

    return `
                <div class="reply-actions" style="display: flex; gap: 10px; margin-top: 5px; align-items: center; flex-wrap: wrap;">
                    <button class="copy-btn" onclick="copyToClipboard(this.closest('.simba-block').querySelector('.raw-data').value, this)">
                        <i class="fa-regular fa-copy"></i> COPY_INTEL
                    </button>
                    <button class="copy-btn" onclick="shareChat(this.closest('.simba-block').querySelector('.raw-data').value)">
                        <i class="fa-solid fa-share-nodes"></i> SHARE
                    </button>
                    <button class="copy-btn" onclick="regenerateText(this)">
                        <i class="fa-solid fa-rotate"></i> Regenerate
                    </button>
                    <button class="copy-btn" onclick="continueMessage(this)" title="Extend this reply if it got cut short">
                        <i class="fa-solid fa-forward"></i> Continue
                    </button>
                    <button class="copy-btn bookmark-btn${bookmarkActiveClass}" onclick="bookmarkMessage(this)" title="Bookmark this reply">
                        <i class="${bookmarkIconClass} fa-bookmark"></i>
                    </button>
                    <button class="copy-btn info-btn" onclick="openMessageInfo(this)" title="Message info">
                        <i class="fa-solid fa-circle-info"></i>
                    </button>
                    <button class="copy-btn" onclick="openHighlightModal(this.closest('.simba-block')?.dataset?.messageId, this.closest('.simba-block')?.querySelector('.raw-data')?.value, 'answer')" title="Save Key Highlight / Note">
                        <i class="fa-solid fa-highlighter"></i> Highlight
                    </button>
                    <button class="copy-btn danger" onclick="deleteMessage(this)" title="Delete this reply">
                        <i class="fa-solid fa-trash"></i>
                    </button>
                    ${showBranchSwitcher && siblingCount > 1 ? `
                    <div class="branch-switcher" data-sibling-ids="${escapeHtml(siblingIds.join(','))}" data-current-id="${escapeHtml(messageId)}">
                        <button class="branch-nav-btn" onclick="switchBranch(this, -1)" aria-label="Previous version"><i class="fa-solid fa-chevron-left"></i></button>
                        <span class="branch-counter">${siblingIndex}/${siblingCount}</span>
                        <button class="branch-nav-btn" onclick="switchBranch(this, 1)" aria-label="Next version"><i class="fa-solid fa-chevron-right"></i></button>
                    </div>
                    ` : ''}
                </div>
                <div class="reply-mini-actions">
                    <button class="reply-mini-btn" onclick="editPromptFromReply(this)" title="Edit the prompt that produced this reply">
                        <i class="fa-solid fa-pen"></i> Edit Prompt
                    </button>
                    <button class="reply-mini-btn" onclick="copyPromptFromReply(this)" title="Copy the prompt that produced this reply">
                        <i class="fa-solid fa-copy"></i> Copy Prompt
                    </button>
                    ${showFollowups ? `
                    <button class="reply-mini-btn" onclick="suggestFollowups(this)" title="Suggest what to ask next">
                        <i class="fa-solid fa-wand-magic-sparkles"></i> Suggest Follow-ups
                    </button>
                    ` : ''}
                </div>
                <div class="followup-suggestions"></div>
                <div class="message-reactions"${msgIdAttr} data-message-role="assistant"></div>
                `;
}

// ================= Function to regenerate image =================
async function regenerateImage(prompt, originalPrompt) {
    const seed = Math.floor(Math.random() * 1000000);
    await sendImageQuery(prompt, seed, originalPrompt);
}

// ================= Function to send image query =================
async function sendImageQuery(query, seed = null, originalPrompt = null) {
    if (isGeneratingImage || isSendingQuery) {
        if (currentAbortController) currentAbortController.abort();
        return;
    }
    isGeneratingImage = true;
    currentAbortController = new AbortController();
    armWatchdog(currentAbortController, IMAGE_REQUEST_TIMEOUT_MS);
    setSendButtonBusy(true);

    const input = document.getElementById("user-input");
    if (typeof resetComposerTaskMode === 'function' && activeTaskMode) {
        resetComposerTaskMode();
    }
    const cf = document.getElementById("chat-flow");

    const userPrompt = originalPrompt || query;

    // If it's a new query, add user message
    if (!originalPrompt) {
        const userMsgHTML = renderCanonicalUserMessageHTML({ query: userPrompt });
        cf.insertAdjacentHTML("beforeend", userMsgHTML);
    }

    const loaderId = "img-load-" + Date.now();

    // Show loading card immediately
    cf.insertAdjacentHTML("beforeend", `
        <div class="chat-block simba-block" id="${loaderId}">
            <span class="msg-label" id="status-label-${loaderId}">
                SIMBA_STATUS: INITIALIZING...
            </span>
            <div class="content" id="content-${loaderId}">
                <div style="text-align:center; padding:20px;">
                    <div style="font-size:24px; margin-bottom:10px;">🎨 Creating Image</div>
                    <div id="model-name-${loaderId}" style="color:#0edb2a; margin-bottom:10px;">Loading model...</div>
                    <div id="eta-${loaderId}" style="color:#a0aabf; margin-bottom:15px;">Estimating time...</div>
                    <div id="status-msg-${loaderId}" style="color:var(--accent);">Preparing prompt...</div>
                    <div class="typing-loader" style="margin-top:20px;">
                        <div class="typing-dot"></div>
                        <div class="typing-dot"></div>
                        <div class="typing-dot"></div>
                    </div>
                </div>
            </div>
        </div>
    `);
    cf.scrollTop = cf.scrollHeight;

    // Animate loading messages and ETA
    const loadingMessages = ["Preparing prompt...", "Choosing model...", "Rendering...", "Enhancing quality...", "Finalizing..."];
    let msgIndex = 0;
    const startTime = Date.now();
    const labelElement = document.getElementById(`status-label-${loaderId}`);
    const statusMsgElement = document.getElementById(`status-msg-${loaderId}`);
    const etaElement = document.getElementById(`eta-${loaderId}`);
    const modelNameElement = document.getElementById(`model-name-${loaderId}`);

    const loadingInterval = setInterval(() => {
        statusMsgElement.innerText = loadingMessages[msgIndex % loadingMessages.length];
        msgIndex++;
        const elapsed = (Date.now() - startTime) / 1000;
        const estimated = Math.max(5, 30 - elapsed);
        etaElement.innerText = `Estimated time: ~${Math.round(estimated)}s`;
    }, 2000);

    try {
        const currentModel = document.getElementById("model-selector").value;
        const aspectRatio = document.getElementById("aspect-ratio-selector").value;

        // Validate the payload before it ever leaves the browser - a corrupted
        // model id here is exactly what used to produce a silent backend 500.
        const knownModel = document.querySelector(`#cyberOptions .cyber-option[data-value="${CSS.escape(currentModel || "")}"]`);
        if (!currentModel || !knownModel) {
            throw new Error(`Invalid model selection: "${currentModel}"`);
        }
        if (!aspectRatio) {
            throw new Error("Missing aspect ratio");
        }
        if (!userPrompt) {
            throw new Error("Missing prompt");
        }

        const res = await fetch("/ask_ai/", {
            method: "POST",
            headers: {
                "Content-Type": "application/x-www-form-urlencoded",
                "X-CSRFToken": csrfToken
            },
            body: `query=${encodeURIComponent(userPrompt)}&model_id=${encodeURIComponent(currentModel)}&aspect_ratio=${encodeURIComponent(aspectRatio)}&seed=${seed || ""}&session_id=${new URLSearchParams(window.location.search).get("session")}&folder=${encodeURIComponent(CHAT_FOLDER_FILTER)}`,
            signal: currentAbortController.signal
        });

        if (!res.ok) throw new Error(`Server error: ${res.status}`);

        const data = await res.json();

        if (data.type === "image") {
            // Sidebar/URL sync is cosmetic - never let it prevent the
            // successfully-generated image from rendering below.
            try {
                const sID = res.headers.get('X-Session-ID');
                const urlParams = new URLSearchParams(window.location.search);

                if (sID && !urlParams.get('session')) {
                    updateBrowserURL(sID);
                    insertOptimisticChatRow(sID, userPrompt);
                    // This new chat was just filed into the active folder
                    // (see ask_ai's `folder` param) - its chip count is
                    // now stale without this.
                    if (CHAT_FOLDER_FILTER) refreshFolderChipsFromServer();
                }
            } catch (sidebarErr) {
                console.error("Sidebar sync failed (non-fatal):", sidebarErr);
            }

            // Update model name
            if (modelNameElement) modelNameElement.innerText = data.model_used;

            // Replace loading card with final image
            const loader = document.getElementById(loaderId);
            const contentDiv = document.getElementById(`content-${loaderId}`);
            if (labelElement) labelElement.innerText = "SIMBA_IMAGE";
            if (loader && data.message_id) loader.dataset.messageId = data.message_id;

            if (contentDiv) {
                const finalImageUrl = data.url || data.image_url || "";
                contentDiv.innerHTML = `
                            <div class="image-card" style="display:flex;flex-direction:column;gap:15px;align-items:center;padding:20px;background:rgba(15,21,28,0.5);border:1px solid rgba(var(--accent-rgb),0.2);border-radius:12px;">
                                <img class="generated-image" crossorigin="anonymous" src="${finalImageUrl}" style="max-width:100%;border-radius:8px;box-shadow:0 0 30px rgba(var(--accent-rgb),0.1);" alt="Generated image">
                                <div style="display:flex;flex-direction:column;gap:8px;width:100%;max-width:600px;">
                                    <div style="display:flex;justify-content:space-between;color:#a0aabf;font-size:14px;">
                                        <span>Resolution: ${data.width}x${data.height}</span>
                                        <span>Model: ${data.model_used}</span>
                                    </div>
                                    <div class="gen-time-label" style="text-align:center;color:#0edb2a;font-size:14px;">
                                        Rendering image...
                                    </div>
                                </div>
                                <div style="display:flex;gap:10px;flex-wrap:wrap;justify-content:center;">
                                    <button class="copy-btn favorite-btn" data-message-id="${data.message_id || ''}">
                                        <i class="fa-regular fa-star"></i> Favorite
                                    </button>
                                    <button class="copy-btn download-btn">
                                        <i class="fa-solid fa-download"></i> Download
                                    </button>
                                    <button class="copy-btn open-btn">
                                        <i class="fa-solid fa-up-right-from-square"></i> Open
                                    </button>
                                    <button class="copy-btn copy-prompt-btn">
                                        <i class="fa-solid fa-copy"></i> Copy Prompt
                                    </button>
                                    <button class="copy-btn regen-btn">
                                        <i class="fa-solid fa-rotate"></i> Regenerate
                                    </button>
                                    <button class="copy-btn share-btn">
                                        <i class="fa-solid fa-share-nodes"></i> Share
                                    </button>
                                    <button class="copy-btn bookmark-btn" onclick="bookmarkMessage(this)" title="Bookmark this image">
                                        <i class="fa-regular fa-bookmark"></i>
                                    </button>
                                    <button class="copy-btn info-btn" onclick="openMessageInfo(this)" title="Message info">
                                        <i class="fa-solid fa-circle-info"></i>
                                    </button>
                                    <button class="copy-btn danger" onclick="deleteMessage(this)" title="Delete this image">
                                        <i class="fa-solid fa-trash"></i>
                                    </button>
                                </div>
                            </div>
                            <div class="reply-mini-actions">
                                <button class="reply-mini-btn" onclick="editPromptFromReply(this)" title="Edit the prompt that produced this image">
                                    <i class="fa-solid fa-pen"></i> Edit Prompt
                                </button>
                            </div>
                        `;
            }

            // The image itself is already committed to the DOM above - it is a
            // fully successful render at this point. Everything below is pure
            // cosmetic follow-up (timers, sound, status pill), so it's isolated
            // in its own try/catch: nothing here is allowed to fall through to
            // the outer catch and overwrite a successfully-rendered image with
            // an "Image generation failed" message.
            try {
                if (contentDiv) {
                    const imgEl = contentDiv.querySelector(".generated-image");
                    const genTimeLabel = contentDiv.querySelector(".gen-time-label");
                    const imgFetchStart = performance.now();
                    let renderProgressInterval = null;

                    const finalizeTiming = (ok) => {
                        if (renderProgressInterval) {
                            clearInterval(renderProgressInterval);
                            renderProgressInterval = null;
                        }
                        if (!genTimeLabel) return;
                        const elapsed = ((performance.now() - imgFetchStart) / 1000).toFixed(2);
                        genTimeLabel.innerText = ok
                            ? `Generation completed in ${elapsed}s`
                            : `Image failed to load after ${elapsed}s`;
                        genTimeLabel.style.color = ok ? "#0edb2a" : "#ff4444";
                    };
                    if (imgEl) {
                        if (imgEl.complete && imgEl.naturalWidth > 0) {
                            finalizeTiming(true);
                        } else {
                            imgEl.addEventListener("load", () => finalizeTiming(true));
                            imgEl.addEventListener("error", () => finalizeTiming(false));
                            // Pollinations render time is highly variable (a couple of
                            // seconds up to a minute or more) - keep the label ticking
                            // so a slow-but-working render never looks frozen.
                            if (genTimeLabel) {
                                renderProgressInterval = setInterval(() => {
                                    const elapsedSec = Math.round((performance.now() - imgFetchStart) / 1000);
                                    genTimeLabel.innerText = elapsedSec < 20
                                        ? `Rendering image... ${elapsedSec}s`
                                        : `Still rendering (${elapsedSec}s) - this can take up to a minute...`;
                                }, 1000);
                            }
                        }
                    }

                    const downloadBtn = contentDiv.querySelector(".download-btn");
                    const openBtn = contentDiv.querySelector(".open-btn");
                    const copyPromptBtn = contentDiv.querySelector(".copy-prompt-btn");
                    const regenBtn = contentDiv.querySelector(".regen-btn");
                    const favoriteBtn = contentDiv.querySelector(".favorite-btn");
                    const shareBtn = contentDiv.querySelector(".share-btn");
                    if (downloadBtn) downloadBtn.addEventListener("click", () => downloadImage(data.url, "simba-intel-image.jpg"));
                    if (openBtn) openBtn.addEventListener("click", () => openImage(data.url));
                    if (copyPromptBtn) copyPromptBtn.addEventListener("click", function () { copyToClipboard(data.prompt, this); });
                    if (regenBtn) regenBtn.addEventListener("click", () => regenerateImage(data.prompt, data.prompt));
                    if (favoriteBtn) favoriteBtn.addEventListener("click", function () { toggleFavoriteImage(this); });
                    if (shareBtn) shareBtn.addEventListener("click", () => shareChat(data.prompt));
                }

                setStatus("status-online", "CORE ONLINE");
                playBlip();
            } catch (postRenderErr) {
                console.error("Post-render cosmetic step failed (image itself is fine):", postRenderErr);
            }
        } else if (data.type === "error") {
            const loader = document.getElementById(loaderId);
            const contentDiv = document.getElementById(`content-${loaderId}`);
            const errorMsg = data.message || "Image generation is temporarily unavailable. Please try again.";
            if (contentDiv) {
                contentDiv.innerHTML = `
                                <div class="rate-limit-card" style="padding: 14px; background: rgba(239, 68, 68, 0.08); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 8px; margin-top: 4px;">
                                    <div style="display:flex; align-items:center; gap: 8px; color: #ef4444; font-weight: 600; font-size: 13px;">
                                        <i class="fa-solid fa-circle-exclamation"></i>
                                        <span>Image Generation Notice</span>
                                    </div>
                                    <p style="margin: 6px 0 10px 0; font-size: 13px; color: #cbd5e1; line-height: 1.4;">${escapeHtml(errorMsg)}</p>
                                    <div style="display:flex; gap: 8px; align-items:center; flex-wrap: wrap;">
                                        <button type="button" class="btn-action btn-primary" onclick="retryLastPrompt('${escapeHtml(userPrompt)}')"><i class="fa-solid fa-rotate-right"></i> Retry</button>
                                    </div>
                                </div>
                            `;
            }
            if (labelElement) labelElement.innerText = "SIMBA_ERROR";
            try { setStatus("status-offline", "CONNECTION LOST"); } catch (statusErr) { console.error(statusErr); }
            const inputEl = document.getElementById("user-input");
            if (inputEl && !inputEl.value) {
                inputEl.value = userPrompt;
                if (typeof autoResizeComposerInput === 'function') autoResizeComposerInput(inputEl);
            }
        }
    } catch (e) {
        const loader = document.getElementById(loaderId);
        const contentDiv = document.getElementById(`content-${loaderId}`);
        if (e.name === "AbortError" && watchdogTimedOut) {
            if (contentDiv) {
                contentDiv.innerHTML = `
                                <div class="rate-limit-card" style="padding: 14px; background: rgba(239, 68, 68, 0.08); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 8px; margin-top: 4px;">
                                    <div style="display:flex; align-items:center; gap: 8px; color: #ef4444; font-weight: 600; font-size: 13px;">
                                        <i class="fa-solid fa-circle-exclamation"></i>
                                        <span>Timeout Notice</span>
                                    </div>
                                    <p style="margin: 6px 0 10px 0; font-size: 13px; color: #cbd5e1; line-height: 1.4;">Image generation timed out. Please try again.</p>
                                    <div style="display:flex; gap: 8px; align-items:center; flex-wrap: wrap;">
                                        <button type="button" class="btn-action btn-primary" onclick="retryLastPrompt('${escapeHtml(userPrompt)}')"><i class="fa-solid fa-rotate-right"></i> Retry</button>
                                    </div>
                                </div>
                            `;
            }
            if (labelElement) labelElement.innerText = "SIMBA_TIMEOUT";
            setStatus("status-offline", "CONNECTION LOST");
        } else if (e.name === "AbortError") {
            if (contentDiv) {
                contentDiv.innerHTML = `<div style="color:var(--text-dim);text-align:center;padding:20px;">Generation stopped.</div>`;
            }
            if (labelElement) labelElement.innerText = "SIMBA_STOPPED";
            setStatus("status-online", "CORE ONLINE");
        } else {
            console.error("Image generation request failed:", e);
            if (contentDiv) {
                contentDiv.innerHTML = `
                                <div class="rate-limit-card" style="padding: 14px; background: rgba(239, 68, 68, 0.08); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 8px; margin-top: 4px;">
                                    <div style="display:flex; align-items:center; gap: 8px; color: #ef4444; font-weight: 600; font-size: 13px;">
                                        <i class="fa-solid fa-circle-exclamation"></i>
                                        <span>Image Generation Notice</span>
                                    </div>
                                    <p style="margin: 6px 0 10px 0; font-size: 13px; color: #cbd5e1; line-height: 1.4;">Image generation is temporarily unavailable. Please try again.</p>
                                    <div style="display:flex; gap: 8px; align-items:center; flex-wrap: wrap;">
                                        <button type="button" class="btn-action btn-primary" onclick="retryLastPrompt('${escapeHtml(userPrompt)}')"><i class="fa-solid fa-rotate-right"></i> Retry</button>
                                    </div>
                                </div>
                            `;
            }
            if (labelElement) labelElement.innerText = "SIMBA_ERROR";
            setStatus("status-offline", "CONNECTION LOST");
        }
        const inputEl = document.getElementById("user-input");
        if (inputEl && !inputEl.value) {
            inputEl.value = userPrompt;
            if (typeof autoResizeComposerInput === 'function') autoResizeComposerInput(inputEl);
        }
    } finally {
        clearInterval(loadingInterval);
        clearWatchdog();
        isGeneratingImage = false;
        currentAbortController = null;
        setSendButtonBusy(false);
    }
}

// ================= Function to download image =================
function downloadImage(url, filename) {
    fetch(url)
        .then(response => response.blob())
        .then(blob => {
            const objectUrl = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = objectUrl;
            link.download = filename;
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            URL.revokeObjectURL(objectUrl);
        })
        .catch(() => window.open(url, '_blank'));
}

// ================= Function to open image =================
function openImage(url) {
    window.open(url, '_blank');
}

// ================= Favorite a generated image =================
function toggleFavoriteImage(btn) {
    const messageId = btn.dataset.messageId;
    if (!messageId) {
        console.error('Favorite button missing a message id (image not saved yet?)');
        return;
    }
    btn.disabled = true;
    fetch(`/messages/${messageId}/toggle-favorite/`, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrfToken },
        signal: AbortSignal.timeout(10000),
    })
        .then(res => res.json().then(data => ({ ok: res.ok, data })))
        .then(({ ok, data }) => {
            if (!ok) { alert(data.message || 'Could not update favorite.'); return; }
            const icon = btn.querySelector('i');
            if (icon) icon.className = data.favorited ? 'fa-solid fa-star' : 'fa-regular fa-star';
        })
        .catch(() => alert('Network error - please try again.'))
        .finally(() => { btn.disabled = false; });
}

// ================= Fullscreen image lightbox =================
function openImageLightbox(url) {
    const lightbox = document.getElementById("image-lightbox");
    const img = document.getElementById("lightbox-img");
    if (!lightbox || !img) return;
    img.src = url;
    lightbox.classList.add("show");
}

function closeImageLightbox() {
    const lightbox = document.getElementById("image-lightbox");
    const img = document.getElementById("lightbox-img");
    if (lightbox) lightbox.classList.remove("show");
    if (img) img.src = "";
}

document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
        closeImageLightbox();
        closeAttachmentModals();
    }
});

// Event delegation: any generated image, live or from history, opens the
// lightbox on click - works for images inserted after page load too.
document.addEventListener("click", (e) => {
    const img = e.target.closest(".generated-image");
    if (img) openImageLightbox(img.src);
});

// ================= Export the current conversation as a PDF =================
function exportChatAsPdf(chatTitle) {
    if (typeof html2pdf === "undefined") {
        alert("PDF export library failed to load. Check your connection and try again.");
        return;
    }
    const chatFlow = document.getElementById("chat-flow");
    if (!chatFlow) return;

    const clone = chatFlow.cloneNode(true);
    // Strip interactive/UI-only chrome so the PDF only contains the conversation.
    clone.querySelectorAll(
        '.copy-btn, .typing-loader, textarea.raw-data, textarea.raw-query, .welcome-container'
    ).forEach(el => el.remove());
    clone.style.background = "#0a0b0e";
    clone.style.color = "#d1d5db";
    clone.style.padding = "20px";

    const filename = (chatTitle || "simba-intel-chat")
        .replace(/[^a-z0-9\-_ ]/gi, "").trim() || "simba-intel-chat";

    // Generated images are hosted cross-origin (image.pollinations.ai). html2canvas
    // can only read cross-origin pixel data into the PDF's canvas if useCORS is on
    // AND the <img> tags carry crossorigin="anonymous" (set at render time above).
    html2pdf().set({
        margin: 10,
        filename: `${filename}.pdf`,
        html2canvas: { backgroundColor: "#0a0b0e", scale: 2, useCORS: true, allowTaint: false },
        jsPDF: { unit: "mm", format: "a4", orientation: "portrait" }
    }).from(clone).save();
}

/// ================= SEND QUERY (ચેટ અને સેશન સિંક સાથે) =================
async function sendQuery(event) {
    if (event && typeof event.preventDefault === 'function') event.preventDefault();

    if (isSendingQuery || isGeneratingImage) {
        // Only explicit click on stop button should abort; duplicate sends or enters are ignored
        if (event && event.target && typeof event.target.closest === 'function' && event.target.closest('.send-btn.stop-mode')) {
            if (currentAbortController) currentAbortController.abort();
        }
        return;
    }

    const input = document.getElementById("user-input");
    const query = input ? input.value.trim() : "";
    if (!query && pendingAttachments.length === 0) return;

    // Check if current model is image model
    const currentModel = document.getElementById("model-selector")?.value || "";
    const modelOption = Array.from(document.querySelectorAll("#cyberOptions .cyber-option")).find(o => o.getAttribute("data-value") === currentModel);

    if (modelOption && modelOption.innerText.includes("Image")) {
        // It's an image query
        if (input) {
            input.value = "";
            autoResizeComposerInput(input);
        }
        await sendImageQuery(query);
        return;
    }

    // Snapshot pending attachments and reset UI
    const attachmentsToSend = pendingAttachments;
    if (attachmentsToSend.length > 0) removeAttachment();

    // ----- LOCKDOWN COMMAND -----
    if (query.toLowerCase() === '/lockdown') {
        const lockdownEl = document.getElementById('lockdown-screen');
        if (lockdownEl) lockdownEl.style.display = 'flex';
        setTimeout(() => document.getElementById('lock-pass')?.focus(), 100);
        if (input) {
            input.value = "";
            autoResizeComposerInput(input);
        }
        return;
    }

    isSendingQuery = true;
    currentAbortController = new AbortController();
    armWatchdog(currentAbortController, TEXT_REQUEST_TIMEOUT_MS);
    setSendButtonBusy(true);

    // 🟡 PROCESSING STATE
    setStatus("status-processing", "PROCESSING...");

    const welcomeContainer = document.querySelector('.welcome-container');
    if (welcomeContainer) welcomeContainer.style.display = 'none';

    let modelId =
        document.getElementById("model-selector")?.value ||
        localStorage.getItem("selected_simba_model") ||
        "quantum-core";

    // Defensive: if model-selector's value ever ends up not matching any real
    // model (e.g. state corruption), fall back to a known-good model instead
    // of sending an invalid model_id to the backend.
    if (!document.querySelector(`#cyberOptions .cyber-option[data-value="${CSS.escape(modelId)}"]`)) {
        console.error(`Invalid model id "${modelId}" - falling back to quantum-core`);
        modelId = "quantum-core";
        const modelHiddenInput = document.getElementById("model-selector");
        if (modelHiddenInput) modelHiddenInput.value = modelId;
        localStorage.setItem("selected_simba_model", modelId);
    }

    if (input) {
        input.value = "";
        autoResizeComposerInput(input);
    }
    if (typeof resetComposerTaskMode === 'function' && activeTaskMode) {
        resetComposerTaskMode();
    }
    const cf = document.getElementById("chat-flow");

    const attachmentCardsHTML = attachmentsToSend.length > 0
        ? `
                    <div class="message-attachments-container">
                        ${attachmentsToSend.map((a, idx) => {
            if (a.isImage && a.previewUrl) {
                return `
                                    <div class="msg-attachment-card image-card" onclick="openAttachmentImageViewer('${escapeHtml(a.previewUrl)}', '${escapeHtml(a.name)}', ${a.size})" title="${escapeHtml(a.name)} (Click to view)">
                                        <div class="msg-attachment-thumb-wrapper">
                                            <img class="msg-attachment-thumb" src="${a.previewUrl}" alt="${escapeHtml(a.name)}">
                                        </div>
                                        <span class="msg-attachment-name">${escapeHtml(a.name)}</span>
                                    </div>
                                `;
            } else {
                const iconClass = getFileIconClass(a.name);
                return `
                                    <div class="msg-attachment-card file-card" onclick="openPendingFileViewer(${idx})" title="${escapeHtml(a.name)} (Click to read/view)">
                                        <div class="msg-attachment-icon"><i class="${iconClass}"></i></div>
                                        <div class="msg-attachment-info">
                                            <span class="msg-attachment-name">${escapeHtml(a.name)}</span>
                                            <span class="msg-attachment-size">${formatFileSize(a.size)}</span>
                                        </div>
                                    </div>
                                `;
            }
        }).join("")}
                    </div>
                `
        : "";

    const userMsgHTML = renderCanonicalUserMessageHTML({
        query: query,
        attachmentsHTML: attachmentCardsHTML
    });
    cf.insertAdjacentHTML("beforeend", userMsgHTML);

    if (window.Prism) Prism.highlightAll();

    const loaderId = "load-" + Date.now();

    cf.insertAdjacentHTML("beforeend", `
        <div class="chat-block simba-block" id="${loaderId}">
            <span class="msg-label" id="status-label-${loaderId}">
                SIMBA_STATUS: INITIALIZING...
            </span>
            <div class="content">
                <div class="typing-loader">
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                </div>
            </div>
        </div>
    `);

    cf.scrollTop = cf.scrollHeight;

    const statusMessages = [
        "OPTIMIZING LOGIC PATH...",
        "ACCESSING DATABASE...",
        "SIMBA_AI: GENERATING...",
        "ANALYZING QUERY STRUCTURE..."
    ];

    let msgIndex = 0;
    const labelElement = document.getElementById(`status-label-${loaderId}`);

    const statusInterval = setInterval(() => {
        if (labelElement) {
            labelElement.innerText =
                "SIMBA_STATUS: " + statusMessages[msgIndex];
            msgIndex = (msgIndex + 1) % statusMessages.length;
        }
    }, 1500);

    try {
        const startTime = performance.now();
        const sessionParam = new URLSearchParams(window.location.search).get("session");
        const sessionTypeParam = new URLSearchParams(window.location.search).get("type") || "assistant";
        const attachedCtx = document.getElementById('agentContextSelect')?.value || '';

        let fetchOptions;
        if (attachmentsToSend.length > 0) {
            const form = new FormData();
            form.append("query", query);
            form.append("model_id", modelId);
            form.append("session_id", sessionParam || "");
            form.append("session_type", sessionTypeParam);
            if (attachedCtx) form.append("context_session_id", attachedCtx);
            form.append("folder", CHAT_FOLDER_FILTER);
            attachmentsToSend.forEach(a => form.append("attachment", a.file, a.name));
            fetchOptions = {
                method: "POST",
                headers: { "X-CSRFToken": csrfToken },
                body: form,
                signal: currentAbortController.signal
            };
        } else {
            fetchOptions = {
                method: "POST",
                headers: {
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-CSRFToken": csrfToken
                },
                body: `query=${encodeURIComponent(query)}&model_id=${encodeURIComponent(modelId)}&session_id=${sessionParam || ""}&session_type=${encodeURIComponent(sessionTypeParam)}&context_session_id=${encodeURIComponent(attachedCtx)}&folder=${encodeURIComponent(CHAT_FOLDER_FILTER)}`,
                signal: currentAbortController.signal
            };
        }

        const res = await fetch("/ask_ai/", fetchOptions);

        if (res.status === 429) {
            clearInterval(statusInterval);
            const errorData = await res.json().catch(() => ({}));
            const loader = document.getElementById(loaderId);
            const contentDiv = loader ? loader.querySelector('.content') : null;

            const errType = errorData.error_type || "rate_limited";
            let rateMsg = errorData.message || "SIMBA couldn't generate a response because the selected AI provider is temporarily rate-limited.";
            if (errorData.retry_after && !rateMsg.includes("second")) {
                rateMsg += ` Please try again in about ${errorData.retry_after} seconds.`;
            }

            if (contentDiv) {
                if (errType === "daily_limit_reached" || errorData.is_user_quota) {
                    contentDiv.innerHTML = `
                                    <div class="rate-limit-card" style="padding: 14px; background: rgba(239, 68, 68, 0.08); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 8px; margin-top: 4px;">
                                        <div style="display:flex; align-items:center; gap: 8px; color: #ef4444; font-weight: 600; font-size: 13px;">
                                            <i class="fa-solid fa-circle-exclamation"></i>
                                            <span>Account Daily Quota Reached</span>
                                        </div>
                                        <p style="margin: 6px 0 10px 0; font-size: 13px; color: #cbd5e1; line-height: 1.4;">${escapeHtml(rateMsg)}</p>
                                        <div style="display:flex; gap: 8px; align-items:center; flex-wrap: wrap;">
                                            <a href="/profile/" class="btn-action" style="text-decoration:none;"><i class="fa-solid fa-user"></i> View Profile & Quota</a>
                                        </div>
                                    </div>
                                `;
                } else if (errType === "burst_limited") {
                    contentDiv.innerHTML = `
                                    <div class="rate-limit-card" style="padding: 14px; background: rgba(59, 130, 246, 0.08); border: 1px solid rgba(59, 130, 246, 0.3); border-radius: 8px; margin-top: 4px;">
                                        <div style="display:flex; align-items:center; gap: 8px; color: #60a5fa; font-weight: 600; font-size: 13px;">
                                            <i class="fa-solid fa-hourglass-half"></i>
                                            <span>Too Many Requests</span>
                                        </div>
                                        <p style="margin: 6px 0 10px 0; font-size: 13px; color: #cbd5e1; line-height: 1.4;">${escapeHtml(rateMsg)}</p>
                                        <div style="display:flex; gap: 8px; align-items:center; flex-wrap: wrap;">
                                            <button type="button" class="btn-action btn-primary" onclick="retryLastPrompt('${escapeHtml(query)}')"><i class="fa-solid fa-rotate-right"></i> Retry</button>
                                        </div>
                                    </div>
                                `;
                } else {
                    contentDiv.innerHTML = `
                                    <div class="rate-limit-card" style="padding: 14px; background: rgba(234, 179, 8, 0.08); border: 1px solid rgba(234, 179, 8, 0.3); border-radius: 8px; margin-top: 4px;">
                                        <div style="display:flex; align-items:center; gap: 8px; color: #eab308; font-weight: 600; font-size: 13px;">
                                            <i class="fa-solid fa-triangle-exclamation"></i>
                                            <span>AI Provider Rate Limited</span>
                                        </div>
                                        <p style="margin: 6px 0 10px 0; font-size: 13px; color: #cbd5e1; line-height: 1.4;">${escapeHtml(rateMsg)}</p>
                                        <div style="display:flex; gap: 8px; align-items:center; flex-wrap: wrap;">
                                            <button type="button" class="btn-action btn-primary" onclick="retryLastPrompt('${escapeHtml(query)}')"><i class="fa-solid fa-rotate-right"></i> Retry</button>
                                            <button type="button" class="btn-action" onclick="openModelDropdown('${escapeHtml(query)}')"><i class="fa-solid fa-sliders"></i> Change Model</button>
                                        </div>
                                    </div>
                                `;
                }
            }
            if (labelElement) labelElement.innerText = "SIMBA_RATE_LIMITED";
            setStatus("status-offline", "RATE LIMITED");
            if (input && !input.value) {
                input.value = query;
                autoResizeComposerInput(input);
            }
            return;
        }

        if (!res.ok) {
            let errorMsg = `Server error: ${res.status}`;
            let errType = "error";
            try {
                const errJson = await res.json();
                if (errJson.message) errorMsg = errJson.message;
                if (errJson.error_type) errType = errJson.error_type;
            } catch (_) { }

            clearInterval(statusInterval);
            const loader = document.getElementById(loaderId);
            const contentDiv = loader ? loader.querySelector('.content') : null;
            if (contentDiv) {
                contentDiv.innerHTML = `
                                <div class="rate-limit-card" style="padding: 14px; background: rgba(239, 68, 68, 0.08); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 8px; margin-top: 4px;">
                                    <div style="display:flex; align-items:center; gap: 8px; color: #ef4444; font-weight: 600; font-size: 13px;">
                                        <i class="fa-solid fa-circle-exclamation"></i>
                                        <span>Generation Notice</span>
                                    </div>
                                    <p style="margin: 6px 0 10px 0; font-size: 13px; color: #cbd5e1; line-height: 1.4;">${escapeHtml(errorMsg)}</p>
                                    <div style="display:flex; gap: 8px; align-items:center; flex-wrap: wrap;">
                                        <button type="button" class="btn-action btn-primary" onclick="retryLastPrompt('${escapeHtml(query)}')"><i class="fa-solid fa-rotate-right"></i> Retry</button>
                                        <button type="button" class="btn-action" onclick="openModelDropdown('${escapeHtml(query)}')"><i class="fa-solid fa-sliders"></i> Change Model</button>
                                    </div>
                                </div>
                            `;
            }
            if (labelElement) labelElement.innerText = "SIMBA_ERROR";
            setStatus("status-offline", "ERROR");
            if (input && !input.value) {
                input.value = query;
                autoResizeComposerInput(input);
            }
            return;
        }

        // Check if response is JSON (image / vision / error case)
        const contentType = res.headers.get("content-type");
        if (contentType && contentType.includes("application/json")) {
            const data = await res.json();
            clearInterval(statusInterval);
            const loader = document.getElementById(loaderId);
            const contentDiv = loader ? loader.querySelector('.content') : null;

            if (data.type === "error") {
                if (contentDiv) contentDiv.innerText = data.message;
                labelElement.innerText = "SIMBA_ERROR";
                setStatus("status-offline", "CONNECTION LOST");
                if (input && !input.value) {
                    input.value = query;
                    autoResizeComposerInput(input);
                }
                return;
            }

            if (data.type === "vision") {
                if (loader && data.message_id) loader.dataset.messageId = data.message_id;
                if (contentDiv) {
                    contentDiv.className = "content markdown-content";
                    contentDiv.innerHTML = renderMarkdown(data.response);

                    let rawDataEl = loader.querySelector('.raw-data');
                    if (!rawDataEl) {
                        rawDataEl = document.createElement('textarea');
                        rawDataEl.className = 'raw-data';
                        rawDataEl.style.display = 'none';
                        loader.insertBefore(rawDataEl, contentDiv);
                    }
                    rawDataEl.value = data.response;

                    loader.querySelectorAll('.reply-actions, .reply-mini-actions, .followup-suggestions, .message-reactions').forEach(el => el.remove());
                    loader.insertAdjacentHTML('beforeend', renderCanonicalAssistantActionsHTML({
                        messageId: data.message_id || loader.dataset.messageId || '',
                        bookmarked: false,
                        showFollowups: false,
                    }));

                    renderRichContent(loader);
                    applyCodeButtons(loader);
                }
                labelElement.innerText = "SIMBA_VISION";
                setStatus("status-online", "CORE ONLINE");
                playBlip();
                return;
            }
        }

        // Sidebar/URL sync is cosmetic - never let it block the response stream below.
        try {
            const sID = res.headers.get('X-Session-ID');
            const urlParams = new URLSearchParams(window.location.search);

            if (sID && !urlParams.get('session')) {
                updateBrowserURL(sID);

                insertOptimisticChatRow(sID, query);
                // This new chat was just filed into the active folder
                // (see ask_ai's `folder` param) - its chip count is
                // now stale without this.
                if (CHAT_FOLDER_FILTER) refreshFolderChipsFromServer();
            }
        } catch (sidebarErr) {
            console.error("Sidebar sync failed (non-fatal):", sidebarErr);
        }

        clearInterval(statusInterval);

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let fullResponse = "";
        let isThinking = false;
        let firstTokenReceived = false;

        const loader = document.getElementById(loaderId);
        const contentDiv = loader.querySelector('.content');

        let scheduledRenderId = null;
        function scheduleStreamRender() {
            if (scheduledRenderId !== null) return;
            scheduledRenderId = requestAnimationFrame(() => {
                scheduledRenderId = null;
                if (!contentDiv) return;
                contentDiv.className = "content markdown-content";
                contentDiv.innerHTML = renderMarkdown(fullResponse);
                renderRichContent(loader);
                applyCodeButtons(loader);
                cf.scrollTop = cf.scrollHeight;
            });
        }

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            resetWatchdog(currentAbortController, TEXT_REQUEST_TIMEOUT_MS);
            const chunk = decoder.decode(value, { stream: true });

            if (!firstTokenReceived && chunk.trim()) {
                firstTokenReceived = true;
                labelElement.innerText = "SIMBA_STREAMING...";
                setStatus("status-processing", "STREAMING...");
            }

            if (chunk.includes("<think>")) isThinking = true;
            if (chunk.includes("</think>")) isThinking = false;

            // Check for SIMBA_STATUS markers emitted by Agent Controller
            if (chunk.includes("SIMBA_STATUS:")) {
                const statusMatch = chunk.match(/SIMBA_STATUS:\s*([^\n\r]+)/);
                if (statusMatch && statusMatch[1]) {
                    const statusRaw = statusMatch[1].trim();
                    if (labelElement) labelElement.innerText = `SIMBA_${statusRaw}`;
                    if (typeof setAgentLifecycleStatus === 'function') {
                        setAgentLifecycleStatus(statusRaw);
                    }
                }
                // Strip SIMBA_STATUS marker lines from user visible bubble
                const cleanChunk = chunk.replace(/SIMBA_STATUS:\s*[^\n\r]+[\r\n]*/g, '');
                if (cleanChunk) {
                    fullResponse += cleanChunk;
                    scheduleStreamRender();
                }
            } else {
                fullResponse += chunk;
                scheduleStreamRender();
            }
        }

        if (scheduledRenderId !== null) {
            cancelAnimationFrame(scheduledRenderId);
            scheduledRenderId = null;
        }

        contentDiv.className = "content markdown-content";
        contentDiv.innerHTML = renderMarkdown(fullResponse);

        let rawDataEl = loader.querySelector('.raw-data');
        if (!rawDataEl) {
            rawDataEl = document.createElement('textarea');
            rawDataEl.className = 'raw-data';
            rawDataEl.style.display = 'none';
            loader.insertBefore(rawDataEl, contentDiv);
        }
        rawDataEl.value = fullResponse;

        loader.querySelectorAll('.reply-actions, .reply-mini-actions, .followup-suggestions, .message-reactions').forEach(el => el.remove());
        loader.insertAdjacentHTML('beforeend', renderCanonicalAssistantActionsHTML({
            messageId: loader.dataset.messageId || '',
            bookmarked: false,
            showFollowups: true,
        }));

        renderRichContent(loader);
        applyCodeButtons(loader);

        const latency = ((performance.now() - startTime) / 1000).toFixed(2);
        setStatus("status-online", "CORE ONLINE");

        if (labelElement) {
            labelElement.innerText = `SIMBA_RESPONSE • ${latency}s`;
        }

        if (typeof setAgentLifecycleStatus === 'function') {
            setAgentLifecycleStatus("COMPLETED");
        }
        if (typeof maybeVoiceSpeakResponse === 'function') {
            maybeVoiceSpeakResponse(fullResponse);
        }

        const streamedSessionId = res.headers.get('X-Session-ID') || sessionParam;
        if (streamedSessionId) {
            try {
                const leafRes = await fetch(`/session/${streamedSessionId}/active-leaf/`, { signal: AbortSignal.timeout(10000) });
                if (leafRes.ok) {
                    const leafData = await leafRes.json();
                    if (leafData.message_id) loader.dataset.messageId = leafData.message_id;

                    const userBlock = loader.previousElementSibling;
                    if (leafData.user_message_id && userBlock && userBlock.classList.contains('user-block')) {
                        userBlock.dataset.messageId = leafData.user_message_id;
                        if (!userBlock.querySelector('.edit-msg-btn')) {
                            userBlock.insertAdjacentHTML("beforeend", `
                                        <button class="edit-msg-btn" onclick="editUserMessage(this)" title="Edit and regenerate" aria-label="Edit message">
                                            <i class="fa-solid fa-pen"></i>
                                        </button>
                                    `);
                        }
                    }
                }
            } catch (leafErr) {
                console.error("Could not fetch message id (non-fatal):", leafErr);
            }

            // Auto-load smart follow-up suggestions only on successfully completed turns
            if (!fullResponse.includes("SIMBA couldn't generate") && !fullResponse.includes("Something went wrong") && !fullResponse.includes("**Notice:**")) {
                autoLoadFollowupSuggestions(loader, streamedSessionId, loader.dataset.messageId);
            }
        }

    } catch (error) {
        clearInterval(statusInterval);
        const loader = document.getElementById(loaderId);

        if (error.name === "AbortError" && watchdogTimedOut) {
            if (loader) loader.querySelector('.content').innerText = "Request timed out - no response from the server. Please try again.";
            if (labelElement) labelElement.innerText = "SIMBA_TIMEOUT";
            setStatus("status-offline", "CONNECTION LOST");
        } else if (error.name === "AbortError") {
            if (loader) loader.querySelector('.content').innerText = "Generation stopped.";
            if (labelElement) labelElement.innerText = "SIMBA_STOPPED";
            setStatus("status-online", "CORE ONLINE");
        } else {
            console.error("Error:", error);
            if (loader) {
                const contentDiv = loader.querySelector('.content');
                if (contentDiv) {
                    contentDiv.innerHTML = `
                                    <div class="rate-limit-card" style="padding: 14px; background: rgba(239, 68, 68, 0.08); border: 1px solid rgba(239, 68, 68, 0.3); border-radius: 8px; margin-top: 4px;">
                                        <div style="display:flex; align-items:center; gap: 8px; color: #ef4444; font-weight: 600; font-size: 13px;">
                                            <i class="fa-solid fa-circle-exclamation"></i>
                                            <span>Connection Notice</span>
                                        </div>
                                        <p style="margin: 6px 0 10px 0; font-size: 13px; color: #cbd5e1; line-height: 1.4;">Communication with the server was interrupted. Please try again.</p>
                                        <div style="display:flex; gap: 8px; align-items:center; flex-wrap: wrap;">
                                            <button type="button" class="btn-action btn-primary" onclick="retryLastPrompt('${escapeHtml(query)}')"><i class="fa-solid fa-rotate-right"></i> Retry</button>
                                            <button type="button" class="btn-action" onclick="openModelDropdown('${escapeHtml(query)}')"><i class="fa-solid fa-sliders"></i> Change Model</button>
                                        </div>
                                    </div>
                                `;
                }
            }
            if (labelElement) labelElement.innerText = "SIMBA_ERROR";
            setStatus("status-offline", "CONNECTION LOST");
            const inputEl = document.getElementById("user-input");
            if (inputEl && !inputEl.value) {
                inputEl.value = query;
                if (typeof autoResizeComposerInput === 'function') autoResizeComposerInput(inputEl);
            }
        }
    } finally {
        clearWatchdog();
        isSendingQuery = false;
        currentAbortController = null;
        setSendButtonBusy(false);
    }
}

// ================= Regenerate a text response =================
// If the bubble carries a real message id (data-message-id, set for
// every message loaded from history, and for anything streamed live
// in this page session - see the active-leaf fetch in sendQuery),
// this hits /messages/<id>/regenerate/: the backend creates a true
// sibling branch (old reply stays in the DB, just off the active
// path) and this function replaces the bubble's content IN PLACE -
// no duplicate turn appended. Without an id (defensive fallback only
// - shouldn't normally happen), falls back to the old "append a new
// turn via /ask_ai/" behavior so regenerate never just breaks.
async function regenerateText(btn) {
    if (isSendingQuery || isGeneratingImage) return;

    const simbaBlock = btn.closest('.simba-block');
    const userBlock = simbaBlock ? simbaBlock.previousElementSibling : null;
    const rawQueryEl = userBlock ? userBlock.querySelector('.raw-query') : null;
    const query = rawQueryEl ? rawQueryEl.value.trim() : "";
    if (!query || !simbaBlock) return;

    const messageId = simbaBlock.dataset.messageId;
    const hasRealId = messageId && messageId !== "None" && messageId !== "";

    isSendingQuery = true;
    currentAbortController = new AbortController();
    armWatchdog(currentAbortController, TEXT_REQUEST_TIMEOUT_MS);
    setSendButtonBusy(true);

    const modelId =
        document.getElementById("model-selector").value ||
        localStorage.getItem("selected_simba_model") ||
        "quantum-core";

    const cf = document.getElementById("chat-flow");
    const previousContentHTML = simbaBlock.innerHTML;
    const labelElement = simbaBlock.querySelector('.msg-label');
    const contentDiv = simbaBlock.querySelector('.content');
    if (labelElement) labelElement.innerText = "SIMBA_STATUS: REGENERATING...";
    if (contentDiv) {
        contentDiv.innerHTML = `
                    <div class="typing-loader">
                        <div class="typing-dot"></div>
                        <div class="typing-dot"></div>
                        <div class="typing-dot"></div>
                    </div>
                `;
    }
    // The old footer (raw-data textarea + COPY_INTEL/SHARE/Regenerate
    // buttons) lives as direct-child siblings of .content, not inside
    // it - contentDiv.innerHTML above doesn't touch them. Strip them
    // now so the fresh footer appended after streaming doesn't
    // duplicate them.
    Array.from(simbaBlock.children).forEach(child => {
        if (!child.classList.contains('msg-label') && !child.classList.contains('content')) {
            child.remove();
        }
    });

    try {
        const sessionParam = new URLSearchParams(window.location.search).get("session");
        const fetchUrl = hasRealId ? `/messages/${messageId}/regenerate/` : "/ask_ai/";
        const fetchBody = hasRealId
            ? `model_id=${encodeURIComponent(modelId)}`
            : `query=${encodeURIComponent(query)}&model_id=${encodeURIComponent(modelId)}&session_id=${sessionParam || ""}`;

        const res = await fetch(fetchUrl, {
            method: "POST",
            headers: {
                "Content-Type": "application/x-www-form-urlencoded",
                "X-CSRFToken": csrfToken
            },
            body: fetchBody,
            signal: currentAbortController.signal
        });

        if (res.status === 429) {
            const errorData = await res.json().catch(() => ({}));
            simbaBlock.innerHTML = previousContentHTML;
            renderRichContent(simbaBlock);
            let rateMsg = errorData.message || "The selected AI provider is temporarily rate-limited. Please wait a moment and try again.";
            if (errorData.retry_after) rateMsg += ` (Retry in ~${errorData.retry_after}s)`;
            if (typeof showSimbaToast === 'function') {
                showSimbaToast(rateMsg, "warning");
            } else {
                alert(rateMsg);
            }
            setStatus("status-offline", "RATE LIMITED");
            return;
        }

        if (!res.ok) throw new Error(`Server error: ${res.status}`);

        const contentType = res.headers.get("content-type");
        if (contentType && contentType.includes("application/json")) {
            const data = await res.json();
            if (data.type === "error") {
                simbaBlock.innerHTML = previousContentHTML;
                renderRichContent(simbaBlock);
                if (typeof showSimbaToast === 'function') {
                    showSimbaToast(data.message || "Regenerate failed.", "warning");
                } else {
                    alert(data.message || "Regenerate failed. The original response is unchanged.");
                }
                return;
            }
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let fullResponse = "";
        let firstTokenReceived = false;
        const renderer = createThrottledStreamRenderer(
            () => contentDiv.querySelector('.markdown-content'), () => fullResponse, cf,
        );

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            resetWatchdog(currentAbortController, TEXT_REQUEST_TIMEOUT_MS);
            const chunk = decoder.decode(value, { stream: true });
            if (!firstTokenReceived) {
                contentDiv.innerHTML = `<div class="markdown-content"></div>`;
                if (labelElement) labelElement.innerText = "SIMBA_RESPONSE";
                firstTokenReceived = true;
            }
            fullResponse += chunk.replace("<think>", "").replace("</think>", "");
            renderer.schedule();
        }
        renderer.flushNow();

        if (!fullResponse.trim()) {
            // Nothing was generated (and nothing was persisted server-side
            // either, matching append_turn's all-or-nothing behavior) -
            // restore what was there before rather than leaving it blank.
            simbaBlock.innerHTML = previousContentHTML;
            return;
        }

        renderRichContent(simbaBlock);
        applyCodeButtons(simbaBlock);
        playBlip();

        const contentDiv = simbaBlock.querySelector('.content');
        if (contentDiv) {
            contentDiv.className = "content markdown-content";
            contentDiv.innerHTML = renderMarkdown(fullResponse);
        }

        let rawDataEl = simbaBlock.querySelector('.raw-data');
        if (!rawDataEl) {
            rawDataEl = document.createElement('textarea');
            rawDataEl.className = 'raw-data';
            rawDataEl.style.display = 'none';
            if (contentDiv) simbaBlock.insertBefore(rawDataEl, contentDiv);
        }
        if (rawDataEl) rawDataEl.value = fullResponse;

        simbaBlock.querySelectorAll('.reply-actions, .reply-mini-actions, .followup-suggestions, .message-reactions').forEach(el => el.remove());
        simbaBlock.insertAdjacentHTML('beforeend', renderCanonicalAssistantActionsHTML({
            messageId: simbaBlock.dataset.messageId || '',
            bookmarked: false,
            showFollowups: true,
        }));

        // Keep data-message-id accurate (points at whichever sibling is
        // now showing) so a follow-up regenerate/COPY_INTEL targets the
        // right node. All siblings share the same parent, so this is
        // purely for accuracy, not correctness of the branch itself.
        const sID = res.headers.get('X-Session-ID') || sessionParam;
        if (sID) {
            try {
                const leafRes = await fetch(`/session/${sID}/active-leaf/`, { signal: AbortSignal.timeout(10000) });
                if (leafRes.ok) {
                    const leafData = await leafRes.json();
                    if (leafData.message_id) {
                        simbaBlock.dataset.messageId = leafData.message_id;
                        const footer = simbaBlock.querySelector('.reply-actions');
                        if (footer) await refreshBranchSwitcher(leafData.message_id, footer);
                    }
                }
            } catch (leafErr) {
                console.error("Could not refresh message id (non-fatal):", leafErr);
            }
            autoLoadFollowupSuggestions(simbaBlock, sID, simbaBlock.dataset.messageId);
        }
    } catch (e) {
        if (e.name === "AbortError" && watchdogTimedOut) {
            simbaBlock.innerHTML = previousContentHTML;
            renderRichContent(simbaBlock);
            alert("Regenerate timed out - no response from the server. Please try again.");
        } else if (e.name === "AbortError") {
            simbaBlock.innerHTML = previousContentHTML;
            renderRichContent(simbaBlock);
        } else {
            console.error("Regenerate failed:", e);
            simbaBlock.innerHTML = previousContentHTML;
            alert("Regenerate failed. The original response is unchanged.");
        }
    } finally {
        clearWatchdog();
        isSendingQuery = false;
        currentAbortController = null;
        setSendButtonBusy(false);
    }
}

function bookmarkMessage(btn) {
    const block = btn.closest('.chat-block');
    const messageId = block ? block.dataset.messageId : null;
    if (!messageId || messageId === "None") { alert("This message hasn't been saved yet."); return; }
    btn.disabled = true;
    fetch(`/messages/${messageId}/bookmark/`, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrfToken },
        signal: AbortSignal.timeout(10000),
    })
        .then(res => res.json().then(data => ({ ok: res.ok, data })))
        .then(({ ok, data }) => {
            if (!ok) { alert(data.message || data.error || 'Could not bookmark.'); return; }
            btn.classList.toggle('active', data.bookmarked);
            const icon = btn.querySelector('i');
            if (icon) icon.className = data.bookmarked ? 'fa-solid fa-bookmark' : 'fa-regular fa-bookmark';
        })
        .catch(() => alert('Network error - please try again.'))
        .finally(() => { btn.disabled = false; });
}

async function deleteMessage(btn) {
    const block = btn.closest('.chat-block');
    const messageId = block ? block.dataset.messageId : null;
    if (!messageId || messageId === "None") { alert("This message hasn't been saved yet."); return; }
    if (!confirm("Delete this message? Any replies under it will be deleted too.")) return;
    try {
        const res = await fetch(`/messages/${messageId}/delete/`, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken },
            signal: AbortSignal.timeout(10000),
        });
        // A full reload is the simplest correct redraw here: deleting a
        // node can cascade to every descendant (a whole sub-branch),
        // which is more than a targeted DOM patch could safely handle -
        // same reasoning switchBranch's reload already relies on.
        if (res.ok) location.reload();
        else alert('Delete failed.');
    } catch (e) {
        alert('Network error - please try again.');
    }
}

// ================= Message Information Panel =================
// Displays genuine real-time and captured metadata for any assistant message.
function _msgInfoRow(label, value, isNA) {
    const displayVal = (value === null || value === undefined || value === '' || isNA) ? 'Not available' : String(value);
    const isNaClass = displayVal === 'Not available' ? ' na' : '';
    return `<div class="message-info-row"><span class="label">${escapeHtml(label)}</span><span class="value${isNaClass}">${escapeHtml(displayVal)}</span></div>`;
}

function _msgInfoDivider() {
    return '<div class="message-info-section-divider"></div>';
}

function _msgInfoBool(value) {
    if (value === null || value === undefined) return 'Not available';
    return value ? 'Yes' : 'No';
}

function renderMessageInfoBody(stats) {
    const rows = [];
    // Core Identification
    if (stats.message_id) rows.push(_msgInfoRow('Message ID', `#${stats.message_id}`));
    if (stats.session_id) rows.push(_msgInfoRow('Session ID', `#${stats.session_id}`));
    if (stats.message_type) rows.push(_msgInfoRow('Message Type', stats.message_type));
    rows.push(_msgInfoDivider());

    // Model & Provider
    rows.push(_msgInfoRow('Provider', stats.provider));
    rows.push(_msgInfoRow('Model Used', stats.actual_model));
    if (stats.fallback_used) {
        rows.push(_msgInfoRow('Fallback Used', 'Yes'));
        rows.push(_msgInfoRow('Fallback Model', stats.fallback_model));
    }
    rows.push(_msgInfoDivider());

    // Token & Usage Telemetry (real only)
    rows.push(_msgInfoRow('Input Tokens', stats.input_tokens));
    rows.push(_msgInfoRow('Output Tokens', stats.output_tokens));
    rows.push(_msgInfoRow('Total Tokens', stats.total_tokens));
    rows.push(_msgInfoDivider());

    // Performance & Latency
    rows.push(_msgInfoRow('Response Time', stats.response_time_s ? `${stats.response_time_s}s` : null));
    rows.push(_msgInfoRow('Time to 1st Token', stats.ttft_s ? `${stats.ttft_s}s` : null));
    rows.push(_msgInfoRow('Streaming Mode', _msgInfoBool(stats.streaming)));
    rows.push(_msgInfoDivider());

    // Content metrics & timestamp
    if (stats.word_count) rows.push(_msgInfoRow('Word Count', stats.word_count));
    if (stats.timestamp) {
        try {
            rows.push(_msgInfoRow('Timestamp', new Date(stats.timestamp).toLocaleString()));
        } catch (e) {
            rows.push(_msgInfoRow('Timestamp', stats.timestamp));
        }
    }
    if (stats.request_id) rows.push(_msgInfoRow('Request ID', stats.request_id));

    return rows.join('');
}

async function openMessageInfo(btn) {
    if (window.event) {
        window.event.preventDefault();
        window.event.stopPropagation();
    }
    let messageId = null;
    if (typeof btn === 'string' || typeof btn === 'number') {
        messageId = btn;
    } else if (btn) {
        const block = btn.closest('.chat-block') || btn.closest('.simba-block');
        messageId = block ? block.dataset.messageId : btn.dataset?.messageId;
    }
    const overlay = document.getElementById('messageInfoOverlay');
    const body = document.getElementById('messageInfoBody');
    if (!overlay || !body) return;

    if (!messageId || messageId === "None" || messageId === "null" || messageId === "undefined") {
        showToast("Message is still finalizing. Please wait a moment.", "info");
        return;
    }

    body.innerHTML = '<div class="message-info-empty"><i class="fa-solid fa-spinner fa-spin"></i> Loading metadata...</div>';
    overlay.classList.add('show');
    overlay.classList.add('active');
    overlay.style.display = 'flex';

    try {
        const res = await fetch(`/messages/${messageId}/info/`, { signal: AbortSignal.timeout(10000) });
        const data = await res.json();
        if (!res.ok || data.status !== 'success' || !data.stats) {
            body.innerHTML = '<div class="message-info-empty">Could not load message info.</div>';
            return;
        }
        body.innerHTML = renderMessageInfoBody(data.stats);
    } catch (e) {
        body.innerHTML = '<div class="message-info-empty">Network error - please try again.</div>';
    }
}

function closeMessageInfo() {
    const overlay = document.getElementById('messageInfoOverlay');
    if (overlay) {
        overlay.classList.remove('show');
        overlay.classList.remove('active');
        overlay.style.display = 'none';
    }
}

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeMessageInfo();
});

async function continueMessage(btn) {
    if (isSendingQuery || isGeneratingImage) return;

    const simbaBlock = btn.closest('.simba-block');
    const messageId = simbaBlock ? simbaBlock.dataset.messageId : null;
    if (!messageId || messageId === "None") {
        alert("This reply hasn't been saved yet - nothing to continue.");
        return;
    }

    const originalBtnHTML = btn.innerHTML;
    const originalTitle = btn.getAttribute("title") || "Extend this reply if it got cut short";
    const originalAriaLabel = btn.getAttribute("aria-label") || "";

    const setButtonGenerating = () => {
        btn.disabled = true;
        btn.classList.add("is-generating");
        btn.setAttribute("aria-busy", "true");
        btn.setAttribute("aria-label", "Generating continuation...");
        btn.innerHTML = '<i class="fa-solid fa-forward"></i> Continue <span class="continue-dots" aria-hidden="true"><span class="continue-dot"></span><span class="continue-dot"></span><span class="continue-dot"></span></span>';
    };

    const restoreButtonState = () => {
        if (btn && btn.isConnected) {
            btn.disabled = false;
            btn.classList.remove("is-generating");
            btn.removeAttribute("aria-busy");
            if (originalAriaLabel) {
                btn.setAttribute("aria-label", originalAriaLabel);
            } else {
                btn.removeAttribute("aria-label");
            }
            btn.setAttribute("title", originalTitle);
            btn.innerHTML = originalBtnHTML;
        }
    };

    setButtonGenerating();

    isSendingQuery = true;
    currentAbortController = new AbortController();
    armWatchdog(currentAbortController, TEXT_REQUEST_TIMEOUT_MS);
    setSendButtonBusy(true);

    const modelId =
        document.getElementById("model-selector").value ||
        localStorage.getItem("selected_simba_model") ||
        "quantum-core";

    const cf = document.getElementById("chat-flow");
    const rawDataEl = simbaBlock.querySelector('.raw-data');
    const existingContent = rawDataEl ? rawDataEl.value : "";
    const markdownDiv = simbaBlock.querySelector('.markdown-content');
    const previousContentHTML = simbaBlock.innerHTML;

    try {
        const res = await fetch(`/messages/${messageId}/continue/`, {
            method: "POST",
            headers: {
                "Content-Type": "application/x-www-form-urlencoded",
                "X-CSRFToken": csrfToken
            },
            body: `model_id=${encodeURIComponent(modelId)}`,
            signal: currentAbortController.signal
        });

        if (!res.ok) throw new Error(`Server error: ${res.status}`);

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let addedResponse = "";
        let firstChunkReceived = false;

        const renderer = createThrottledStreamRenderer(
            () => markdownDiv, () => existingContent + addedResponse, cf,
        );

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            resetWatchdog(currentAbortController, TEXT_REQUEST_TIMEOUT_MS);
            const chunk = decoder.decode(value, { stream: true });
            if (!firstChunkReceived && chunk) {
                firstChunkReceived = true;
                restoreButtonState();
            }
            addedResponse += chunk.replace("<think>", "").replace("</think>", "");
            renderer.schedule();
        }
        renderer.flushNow();

        if (addedResponse.trim()) {
            if (rawDataEl) rawDataEl.value = existingContent + addedResponse;
            renderRichContent(simbaBlock);
            applyCodeButtons(simbaBlock);
            playBlip();
        }
    } catch (e) {
        if (e.name === "AbortError" && watchdogTimedOut) {
            simbaBlock.innerHTML = previousContentHTML;
            alert("Continue timed out - no response from the server. Please try again.");
        } else if (e.name !== "AbortError") {
            console.error("Continue failed:", e);
            alert("Continue failed. The original response is unchanged.");
        }
    } finally {
        restoreButtonState();
        clearWatchdog();
        isSendingQuery = false;
        currentAbortController = null;
        setSendButtonBusy(false);
    }
}

// ================= Branch/sibling switcher =================
// Regenerate and edit both create real sibling branches (Phase 3) -
// this is the missing navigation UI: "<  2/3  >" pills that flip
// session.active_leaf between siblings via /messages/<id>/switch-branch/
// without creating anything new. A full reload is used to redraw the
// turn because switching branches can change BOTH the user content
// and the assistant content (and its extra_data - image/vision/text
// can differ across siblings), which is more than a targeted DOM
// patch could safely handle.
function branchSwitcherHTML(siblingIds, currentId) {
    const idx = siblingIds.indexOf(currentId);
    const displayIndex = idx === -1 ? 1 : idx + 1;
    return `
                <div class="branch-switcher" data-sibling-ids="${siblingIds.join(',')}" data-current-id="${currentId}">
                    <button class="branch-nav-btn" onclick="switchBranch(this, -1)" aria-label="Previous version"><i class="fa-solid fa-chevron-left"></i></button>
                    <span class="branch-counter">${displayIndex}/${siblingIds.length}</span>
                    <button class="branch-nav-btn" onclick="switchBranch(this, 1)" aria-label="Next version"><i class="fa-solid fa-chevron-right"></i></button>
                </div>
            `;
}

// Called right after a regenerate/edit completes (which patch the DOM
// in place, without a page reload) so the "1/3" pill appears
// immediately instead of only after a manual refresh.
async function refreshBranchSwitcher(messageId, container) {
    try {
        const resp = await fetch(`/messages/${messageId}/siblings/`, { signal: AbortSignal.timeout(10000) });
        if (!resp.ok) return;
        const data = await resp.json();
        const existing = container.querySelector('.branch-switcher');
        if (existing) existing.remove();
        if (data.sibling_ids && data.sibling_ids.length > 1) {
            container.insertAdjacentHTML('beforeend', branchSwitcherHTML(data.sibling_ids, data.current_id));
        }
    } catch (e) {
        console.error('Could not refresh branch switcher (non-fatal):', e);
    }
}

async function switchBranch(btn, direction) {
    if (isSendingQuery || isGeneratingImage) return;
    const wrapper = btn.closest('.branch-switcher');
    const ids = wrapper.dataset.siblingIds.split(',').map(Number).filter(n => !isNaN(n));
    const currentId = Number(wrapper.dataset.currentId);
    if (ids.length < 2) return;
    let idx = ids.indexOf(currentId);
    if (idx === -1) idx = 0;
    idx = (idx + direction + ids.length) % ids.length;
    const targetId = ids[idx];

    wrapper.querySelectorAll('.branch-nav-btn').forEach(b => b.disabled = true);
    try {
        const resp = await fetch(`/messages/${targetId}/switch-branch/`, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken },
            signal: AbortSignal.timeout(15000),
        });
        if (!resp.ok) throw new Error('switch-branch failed');
        location.reload();
    } catch (e) {
        console.error('Branch switch failed:', e);
        wrapper.querySelectorAll('.branch-nav-btn').forEach(b => b.disabled = false);
    }
}

// ================= Command Palette (Ctrl+K) =================
// Items are (re)built from the live DOM each time the palette opens,
// rather than kept in a separate hardcoded list, so it always
// reflects whatever models/sessions/session are actually rendered on
// the page right now - no separate data source to fall out of sync,
// and it stays correct after a session switch or any DOM update
// (every session switch in this app is a real page navigation, so
// the palette's state is naturally fresh - never persisted stale).
let cmdPaletteItems = [];
let cmdPaletteResults = [];
let cmdPaletteSelectedIndex = 0;
const CMD_PALETTE_RECENTS_KEY = 'simba_recent_commands';
const CMD_PALETTE_MAX_RECENTS = 5;

function getRecentCommandIds() {
    try {
        return JSON.parse(localStorage.getItem(CMD_PALETTE_RECENTS_KEY)) || [];
    } catch (e) { return []; }
}

function recordRecentCommand(id) {
    if (!id) return;
    const recents = getRecentCommandIds().filter(existing => existing !== id);
    recents.unshift(id);
    localStorage.setItem(CMD_PALETTE_RECENTS_KEY, JSON.stringify(recents.slice(0, CMD_PALETTE_MAX_RECENTS)));
}

function buildCommandPaletteItems() {
    const items = [
        { id: 'new-chat', icon: 'fa-solid fa-plus', label: 'New chat', action: () => { window.location.href = '/'; } },
        {
            id: 'image-studio', icon: 'fa-solid fa-image', label: 'Open Image Studio',
            action: () => {
                document.querySelector('#cyberOptions .cyber-option[data-value="image-studio"]')?.click();
                document.getElementById('user-input')?.focus();
            },
        },
        {
            id: 'vision-attach', icon: 'fa-solid fa-eye', label: 'Vision: attach an image',
            action: () => {
                const visionOption = Array.from(document.querySelectorAll('#cyberOptions .cyber-option'))
                    .find(o => o.innerText.toLowerCase().includes('vision'));
                visionOption?.click();
                document.getElementById('attach-input')?.click();
            },
        },
        {
            id: 'export-pdf', icon: 'fa-solid fa-file-pdf', label: 'Export conversation as PDF',
            action: () => {
                const exportBtn = document.querySelector('.new-chat[onclick*="exportChatAsPdf"]');
                if (exportBtn) exportBtn.click();
                else alert('Open a conversation first to export it as PDF.');
            },
        },
        { id: 'analytics', icon: 'fa-solid fa-chart-line', label: 'Open analytics', action: () => { saveChatStateBeforeLeaving(); window.location.href = "/analytics/"; } },
        { id: 'settings', icon: 'fa-solid fa-gear', label: 'Open settings', action: () => { saveChatStateBeforeLeaving(); window.location.href = "/settings/"; } },
        { id: 'focus-composer', icon: 'fa-solid fa-keyboard', label: 'Focus message box', action: () => { document.getElementById('user-input')?.focus(); } },
        { id: 'search-conversations', icon: 'fa-solid fa-magnifying-glass', label: 'Search conversations', action: () => { document.getElementById('chat-search-input')?.focus(); } },
        {
            id: 'shortcuts-help', icon: 'fa-solid fa-keyboard', label: 'Keyboard shortcuts', isInfo: true,
            infoHTML: `
                        <div class="cmd-palette-shortcut-row"><span>Open command palette</span><kbd>Ctrl/Cmd + K</kbd></div>
                        <div class="cmd-palette-shortcut-row"><span>Send message</span><kbd>Enter</kbd></div>
                        <div class="cmd-palette-shortcut-row"><span>New line in message</span><kbd>Shift + Enter</kbd></div>
                        <div class="cmd-palette-shortcut-row"><span>Navigate palette</span><kbd>&uarr; / &darr;</kbd></div>
                        <div class="cmd-palette-shortcut-row"><span>Run selected command</span><kbd>Enter</kbd></div>
                        <div class="cmd-palette-shortcut-row"><span>Close palette / dialogs</span><kbd>Esc</kbd></div>
                    `,
        },
        { id: 'logout', icon: 'fa-solid fa-sign-out-alt', label: 'Log out', action: () => { document.getElementById('logout-form')?.submit(); } },
    ];

    document.querySelectorAll('#cyberOptions .cyber-option').forEach(opt => {
        const value = opt.getAttribute('data-value');
        items.push({
            id: `model:${value}`,
            icon: 'fa-solid fa-microchip',
            label: `Switch model: ${opt.innerText.trim()}`,
            action: () => opt.click(),
        });
    });

    // Kept in sync with UserProfile.THEME_CHOICES (chat/models.py) -
    // this used to only list 4 of the 10 real themes.
    const themeNames = {
        cyberpunk: 'Cyber Dark (default)', 'midnight-purple': 'Midnight', 'matrix-green': 'Matrix',
        nord: 'Nord', synthwave: 'Synthwave', 'purple-neon': 'Purple Neon', ocean: 'Ocean',
        'minimal-dark': 'Minimal Dark', graphite: 'Graphite', light: 'Light',
    };
    Object.entries(themeNames).forEach(([value, name]) => {
        items.push({
            id: `theme:${value}`,
            icon: 'fa-solid fa-palette',
            label: `Preview theme: ${name}`,
            action: () => { document.documentElement.setAttribute('data-theme', value); },
        });
    });

    document.querySelectorAll('#pinned-chats .chat-link').forEach(link => {
        const title = link.innerText.trim().replace(/^>\s*/, '').replace(/\s*$/, '');
        if (!title) return;
        items.push({
            id: `session:${link.getAttribute('href')}`,
            icon: 'fa-solid fa-thumbtack',
            label: `Pinned: ${title}`,
            action: () => { window.location.href = link.getAttribute('href'); },
        });
    });

    document.querySelectorAll('#live-chat-list .chat-link').forEach(link => {
        const title = link.innerText.trim().replace(/^>\s*/, '');
        if (!title) return;
        items.push({
            id: `session:${link.getAttribute('href')}`,
            icon: 'fa-solid fa-message',
            label: `Open: ${title}`,
            action: () => { window.location.href = link.getAttribute('href'); },
        });
    });

    return items;
}

function openCommandPalette() {
    const overlay = document.getElementById('commandPalette');
    const input = document.getElementById('cmdPaletteInput');
    if (!overlay || !input) return;
    cmdPaletteItems = buildCommandPaletteItems();
    overlay.classList.add('show');
    input.value = '';
    filterCommandPalette('');
    setTimeout(() => input.focus(), 30);
}

function closeCommandPalette() {
    document.getElementById('commandPalette')?.classList.remove('show');
}

let _globalSearchTimer = null;
function filterCommandPalette(query) {
    const q = query.trim().toLowerCase();
    if (!q) {
        const recentIds = getRecentCommandIds();
        const byId = new Map(cmdPaletteItems.map(item => [item.id, item]));
        const recentItems = recentIds.map(id => byId.get(id)).filter(Boolean);
        const recentIdSet = new Set(recentItems.map(item => item.id));
        const restItems = cmdPaletteItems.filter(item => !recentIdSet.has(item.id));
        cmdPaletteResults = [...recentItems, ...restItems];
        cmdPaletteSelectedIndex = 0;
        renderCommandPaletteResults();
        return;
    }

    // Immediate local filter
    const localMatches = cmdPaletteItems.filter(i => i.label.toLowerCase().includes(q));
    cmdPaletteResults = localMatches;
    cmdPaletteSelectedIndex = 0;
    renderCommandPaletteResults();

    // Multi-entity search backend fetch (Phase 4)
    clearTimeout(_globalSearchTimer);
    if (q.length >= 2) {
        _globalSearchTimer = setTimeout(() => {
            fetch(`/search/global/?q=${encodeURIComponent(q)}`)
                .then(res => res.json())
                .then(data => {
                    if (data && data.results && data.results.length > 0) {
                        const remoteItems = data.results.map(r => {
                            let icon = 'fa-solid fa-message';
                            let action = () => { window.location.href = r.url; };
                            if (r.type === 'bookmark') icon = 'fa-solid fa-bookmark';
                            else if (r.type === 'highlight') icon = 'fa-solid fa-highlighter';
                            else if (r.type === 'prompt') {
                                icon = 'fa-solid fa-bolt';
                                action = () => {
                                    const input = document.getElementById('user-input');
                                    if (input) {
                                        input.value = r.content;
                                        input.focus();
                                    }
                                };
                            } else if (r.type === 'memory') {
                                icon = 'fa-solid fa-brain';
                                action = () => { showSimbaToast(`Memory: ${r.snippet}`, 'info', 3000); };
                            }
                            return {
                                id: `search:${r.type}:${r.session_id || r.message_id || r.prompt_id || Math.random()}`,
                                icon: icon,
                                label: `[${r.category}] ${r.title} — ${r.snippet || ''}`,
                                action: action,
                            };
                        });
                        cmdPaletteResults = [...localMatches, ...remoteItems];
                        renderCommandPaletteResults();
                    }
                })
                .catch(err => console.debug('Global search error:', err));
        }, 180);
    }
}

function renderCommandPaletteResults() {
    const list = document.getElementById('cmdPaletteResults');
    if (!list) return;
    list.innerHTML = '';
    if (cmdPaletteResults.length === 0) {
        list.innerHTML = '<div class="cmd-palette-empty">No matches found</div>';
        return;
    }
    const recentIdSet = new Set(getRecentCommandIds());
    const query = document.getElementById('cmdPaletteInput')?.value.trim();
    let shownRecentsHeader = false;
    let shownAllHeader = false;
    cmdPaletteResults.forEach((item, i) => {
        if (!query && recentIdSet.has(item.id) && !shownRecentsHeader) {
            const header = document.createElement('div');
            header.className = 'cmd-palette-section-label';
            header.textContent = 'Recent';
            list.appendChild(header);
            shownRecentsHeader = true;
        }
        if (!query && shownRecentsHeader && !recentIdSet.has(item.id) && !shownAllHeader) {
            const header = document.createElement('div');
            header.className = 'cmd-palette-section-label';
            header.textContent = 'All commands & actions';
            list.appendChild(header);
            shownAllHeader = true;
        }
        const row = document.createElement('div');
        row.className = 'cmd-palette-item' + (i === cmdPaletteSelectedIndex ? ' selected' : '');
        row.innerHTML = `<i class="${item.icon}"></i><span>${escapeHtml(item.label)}</span>`;
        row.addEventListener('mouseenter', () => {
            cmdPaletteSelectedIndex = i;
            renderCommandPaletteResults();
        });
        row.addEventListener('click', () => runCommandPaletteItem(i));
        list.appendChild(row);
    });
}

function renderCommandPaletteInfo(html) {
    const list = document.getElementById('cmdPaletteResults');
    if (!list) return;
    list.innerHTML = `<div class="cmd-palette-info">${html}</div>`;
}

function runCommandPaletteItem(i) {
    const item = cmdPaletteResults[i];
    if (!item) return;
    if (item.isInfo) {
        renderCommandPaletteInfo(item.infoHTML);
        return;
    }
    recordRecentCommand(item.id);
    closeCommandPalette();
    item.action();
}

function moveCommandPaletteSelection(delta) {
    if (cmdPaletteResults.length === 0) return;
    cmdPaletteSelectedIndex = (cmdPaletteSelectedIndex + delta + cmdPaletteResults.length) % cmdPaletteResults.length;
    renderCommandPaletteResults();
    document.querySelector('.cmd-palette-item.selected')?.scrollIntoView({ block: 'nearest' });
}



function jumpToMessage(msgId) {
    const target = document.querySelector(`[data-message-id="${msgId}"]`);
    if (target) {
        target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        target.style.outline = '2px solid var(--accent)';
        setTimeout(() => target.style.outline = '', 2000);
    } else {
        showSimbaToast('Message turn not on active branch', 'info');
    }
}

function openHighlightModal(messageId, defaultContent, defaultType) {
    const modal = document.getElementById('highlightModal');
    if (!modal) return;
    document.getElementById('highlightMessageId').value = messageId || '';
    document.getElementById('highlightContentInput').value = defaultContent || '';
    document.getElementById('highlightTitleInput').value = (defaultContent || '').slice(0, 40);
    if (defaultType) document.getElementById('highlightTypeSelect').value = defaultType;
    modal.classList.add('show');
    setTimeout(() => document.getElementById('highlightTitleInput').focus(), 40);
}

function closeHighlightModal() {
    document.getElementById('highlightModal')?.classList.remove('show');
}

function saveHighlightFromModal(e) {
    if (e) e.preventDefault();
    const sessionParam = new URLSearchParams(window.location.search).get('session');
    if (!sessionParam) {
        showSimbaToast('Save a message to start a conversation session first', 'info');
        return;
    }
    const msgId = document.getElementById('highlightMessageId').value;
    const title = document.getElementById('highlightTitleInput').value;
    const content = document.getElementById('highlightContentInput').value;
    const type = document.getElementById('highlightTypeSelect').value;

    const formData = new FormData();
    formData.append('session_id', sessionParam);
    if (msgId) formData.append('message_id', msgId);
    formData.append('title', title);
    formData.append('content', content);
    formData.append('type', type);

    const csrftoken = getCookie('csrftoken');
    fetch('/highlights/create/', {
        method: 'POST',
        headers: { 'X-CSRFToken': csrftoken },
        body: formData
    })
        .then(r => r.json())
        .then(d => {
            if (d.status === 'success') {
                showSimbaToast('Highlight saved to workspace', 'success');
                closeHighlightModal();
            } else {
                showSimbaToast(d.error || 'Failed to save highlight', 'error');
            }
        })
        .catch(() => showSimbaToast('Error saving highlight', 'error'));
}

function deleteHighlight(highlightId) {
    const csrftoken = getCookie('csrftoken');
    fetch(`/highlights/${highlightId}/delete/`, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrftoken }
    })
        .then(r => r.json())
        .then(d => {
            if (d.status === 'success') {
                showSimbaToast('Highlight deleted', 'info');
                document.getElementById(`highlight-card-${highlightId}`)?.remove();
            }
        });
}

function exportCurrentSession(format) {
    const sessionParam = new URLSearchParams(window.location.search).get('session');
    if (!sessionParam) {
        showSimbaToast('No active conversation to export', 'info');
        return;
    }
    window.location.href = `/session/${sessionParam}/export/?format=${format}`;
}

// ================= PROMPT TEMPLATE VARIABLES (PHASE 4) =================
let _currentPromptTemplate = '';
function usePromptWithVariables(promptId, content, variables) {
    if (variables && variables.length > 0) {
        _currentPromptTemplate = content;
        const modal = document.getElementById('promptVarModal');
        const fields = document.getElementById('promptVarFields');
        if (modal && fields) {
            fields.innerHTML = variables.map(v => {
                const escapedVar = escapeHtml(v);
                const tokenLabel = '{' + '{ ' + escapedVar + ' }' + '}';
                return `
                                <div>
                                    <label style="font-size:11px; font-family:var(--font-mono); color:var(--accent); margin-bottom:3px; display:block;">${tokenLabel}</label>
                                    <input type="text" class="simba-input prompt-var-field" data-var="${escapedVar}" placeholder="Enter ${escapedVar}..." style="width:100%; box-sizing:border-box;">
                                </div>
                            `;
            }).join('');
            modal.classList.add('show');
            setTimeout(() => fields.querySelector('input')?.focus(), 40);
        }
    } else {
        const input = document.getElementById('user-input');
        if (input) {
            input.value = content;
            input.focus();
            closePromptLibrary();
            showSimbaToast('Prompt inserted into composer', 'info', 1800);
        }
    }
}

function closePromptVarModal() {
    document.getElementById('promptVarModal')?.classList.remove('show');
}

function applyPromptVariables() {
    let replaced = _currentPromptTemplate;
    document.querySelectorAll('.prompt-var-field').forEach(input => {
        const varName = input.getAttribute('data-var');
        const val = input.value.trim() || ('[' + varName + ']');
        const escapedName = varName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const regex = new RegExp('\\{\\{\\s*' + escapedName + '\\s*\\}\\}', 'g');
        replaced = replaced.replace(regex, val);
    });
    const input = document.getElementById('user-input');
    if (input) {
        input.value = replaced;
        input.focus();
    }
    closePromptVarModal();
    closePromptLibrary();
    showSimbaToast('Prompt configured and inserted', 'success', 2000);
}

// Registered exactly once, at top-level script execution (never
// re-bound from inside a function/callback), so there is no code
// path that can register a second copy of this listener - confirmed
// by grepping the file for every `addEventListener('keydown'` call
// before writing this. Deliberately global (not scoped to "not
// while typing"): Ctrl/Cmd+K is a modifier chord, so it can never
// insert a stray character into a focused input/textarea, which is
// exactly why Slack/Linear/Notion all let it fire while typing too -
// the `ctrlKey`/`metaKey` check below is what "ignore it as normal
// typing" actually means here, not disabling the shortcut inside inputs.
document.addEventListener('keydown', (e) => {
    // Ignore IME composition keystrokes (e.g. typing Japanese/Chinese/
    // Korean) and OS key-repeat while a modifier is held - neither
    // should re-toggle the palette.
    if (e.isComposing || e.repeat) return;

    const isMac = navigator.platform.toUpperCase().includes('MAC');
    const mod = isMac ? e.metaKey : e.ctrlKey;
    // Ctrl/Cmd+Shift+P: same command palette, matching the shortcut
    // VS Code/many editors use for their own "command palette" -
    // an alias for Ctrl/Cmd+K, not a second feature.
    if (mod && e.shiftKey && e.key.toLowerCase() === 'p') {
        e.preventDefault();
        try {
            const overlay = document.getElementById('commandPalette');
            if (overlay && overlay.classList.contains('show')) closeCommandPalette();
            else openCommandPalette();
        } catch (err) {
            console.error('Command palette toggle failed:', err);
        }
        return;
    }
    if (mod && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        try {
            const overlay = document.getElementById('commandPalette');
            if (overlay && overlay.classList.contains('show')) {
                closeCommandPalette();
            } else {
                openCommandPalette();
            }
        } catch (err) {
            // A thrown error here must never leave the shortcut
            // permanently "stuck" - log it and let the next Ctrl+K
            // press try again instead of silently doing nothing forever.
            console.error('Command palette toggle failed:', err);
        }
        return;
    }
    // Ctrl//: focuses the sidebar's conversation search - the classic
    // "quick search" shortcut (Slack/Linear/GitHub all use it).
    if (mod && e.key === '/') {
        e.preventDefault();
        const searchInput = document.getElementById('chat-search-input');
        if (searchInput) { searchInput.focus(); searchInput.select(); }
        return;
    }

    const overlay = document.getElementById('commandPalette');
    if (!overlay || !overlay.classList.contains('show')) return;
    if (e.key === 'Escape') {
        closeCommandPalette();
    } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        moveCommandPaletteSelection(1);
    } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        moveCommandPaletteSelection(-1);
    } else if (e.key === 'Enter') {
        e.preventDefault();
        runCommandPaletteItem(cmdPaletteSelectedIndex);
    }
});

// ================= Edit a user message =================
// Turns the bubble into an editable textarea. On save, POSTs to
// /messages/<id>/edit/, which creates a sibling user node (the old
// one stays in the DB) plus a fresh assistant reply as its child, and
// moves active_leaf there. The paired assistant bubble is updated in
// place, same "replace, don't append a new turn" pattern as regenerate.
function editUserMessage(btn) {
    if (isSendingQuery || isGeneratingImage) return;
    const userBlock = btn.closest('.user-block');
    if (!userBlock || userBlock.querySelector('.edit-msg-wrapper')) return;

    const messageId = userBlock.dataset.messageId;
    if (!messageId || messageId === "None" || messageId === "") {
        alert("This message isn't ready to edit yet - try refreshing the page.");
        return;
    }

    const contentDiv = userBlock.querySelector('.content');
    const rawQueryEl = userBlock.querySelector('.raw-query');
    const currentText = rawQueryEl ? rawQueryEl.value : contentDiv.innerText;

    contentDiv.style.display = 'none';
    btn.style.display = 'none';

    const wrapper = document.createElement('div');
    wrapper.className = 'edit-msg-wrapper';
    wrapper.innerHTML = `
                <textarea class="edit-msg-textarea">${escapeHtml(currentText)}</textarea>
                <div class="edit-msg-actions">
                    <button type="button" class="copy-btn edit-save-btn"><i class="fa-solid fa-check"></i> Save &amp; Regenerate</button>
                    <button type="button" class="copy-btn edit-cancel-btn"><i class="fa-solid fa-xmark"></i> Cancel</button>
                </div>
            `;
    contentDiv.insertAdjacentElement('afterend', wrapper);

    const textarea = wrapper.querySelector('.edit-msg-textarea');
    textarea.focus();
    textarea.setSelectionRange(textarea.value.length, textarea.value.length);

    const cancelEdit = () => {
        wrapper.remove();
        contentDiv.style.display = '';
        btn.style.display = '';
    };
    wrapper.querySelector('.edit-cancel-btn').addEventListener('click', cancelEdit);
    textarea.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') cancelEdit();
    });

    wrapper.querySelector('.edit-save-btn').addEventListener('click', () => {
        const newText = textarea.value.trim();
        if (!newText) return;
        submitEditedMessage(userBlock, messageId, newText, wrapper, contentDiv, btn);
    });
}

async function submitEditedMessage(userBlock, messageId, newText, wrapper, contentDiv, editBtn) {
    isSendingQuery = true;
    currentAbortController = new AbortController();
    armWatchdog(currentAbortController, TEXT_REQUEST_TIMEOUT_MS);
    setSendButtonBusy(true);

    const modelId =
        document.getElementById("model-selector").value ||
        localStorage.getItem("selected_simba_model") ||
        "quantum-core";

    const simbaBlock = userBlock.nextElementSibling;
    const isTextReply = simbaBlock && simbaBlock.classList.contains('simba-block');
    const previousAssistantHTML = isTextReply ? simbaBlock.innerHTML : null;
    const assistantLabel = isTextReply ? simbaBlock.querySelector('.msg-label') : null;
    const assistantContentDiv = isTextReply ? simbaBlock.querySelector('.content') : null;

    wrapper.innerHTML = `
                <div class="typing-loader">
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                    <div class="typing-dot"></div>
                </div>
            `;
    if (assistantLabel) assistantLabel.innerText = "SIMBA_STATUS: REGENERATING...";
    if (assistantContentDiv) {
        assistantContentDiv.innerHTML = `
                    <div class="typing-loader">
                        <div class="typing-dot"></div>
                        <div class="typing-dot"></div>
                        <div class="typing-dot"></div>
                    </div>
                `;
    }
    if (isTextReply) {
        Array.from(simbaBlock.children).forEach(child => {
            if (!child.classList.contains('msg-label') && !child.classList.contains('content')) {
                child.remove();
            }
        });
    }

    const restore = () => {
        wrapper.remove();
        contentDiv.style.display = '';
        editBtn.style.display = '';
        if (isTextReply && previousAssistantHTML !== null) simbaBlock.innerHTML = previousAssistantHTML;
    };

    try {
        const res = await fetch(`/messages/${messageId}/edit/`, {
            method: "POST",
            headers: {
                "Content-Type": "application/x-www-form-urlencoded",
                "X-CSRFToken": csrfToken
            },
            body: `content=${encodeURIComponent(newText)}&model_id=${encodeURIComponent(modelId)}`,
            signal: currentAbortController.signal
        });

        if (res.status === 429) {
            const errorData = await res.json().catch(() => ({}));
            restore();
            let rateMsg = errorData.message || "The selected AI provider is temporarily rate-limited. Please wait a moment and try again.";
            if (errorData.retry_after) rateMsg += ` (Retry in ~${errorData.retry_after}s)`;
            if (typeof showSimbaToast === 'function') {
                showSimbaToast(rateMsg, "warning");
            } else {
                alert(rateMsg);
            }
            setStatus("status-offline", "RATE LIMITED");
            return;
        }

        if (!res.ok) throw new Error(`Server error: ${res.status}`);

        const contentType = res.headers.get("content-type");
        if (contentType && contentType.includes("application/json")) {
            const data = await res.json();
            restore();
            if (typeof showSimbaToast === 'function') {
                showSimbaToast(data.message || data.response || "Edit failed.", "warning");
            } else {
                alert(data.message || data.response || "Edit failed");
            }
            return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let fullResponse = "";
        let firstToken = false;
        const renderer = createThrottledStreamRenderer(
            () => assistantContentDiv && assistantContentDiv.querySelector('.markdown-content'),
            () => fullResponse,
        );
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            resetWatchdog(currentAbortController, TEXT_REQUEST_TIMEOUT_MS);
            const chunk = decoder.decode(value, { stream: true });
            fullResponse += chunk.replace("<think>", "").replace("</think>", "");
            if (assistantContentDiv) {
                if (!firstToken) {
                    assistantContentDiv.innerHTML = `<div class="markdown-content"></div>`;
                    if (assistantLabel) assistantLabel.innerText = "SIMBA_RESPONSE";
                    firstToken = true;
                }
                renderer.schedule();
            }
        }
        renderer.flushNow();

        if (!fullResponse.trim()) {
            // Nothing generated, nothing persisted server-side either -
            // restore both bubbles to their pre-edit state.
            restore();
            return;
        }

        // Commit: the edited text becomes the bubble's displayed content.
        contentDiv.innerText = newText;
        const rawQueryEl = userBlock.querySelector('.raw-query');
        if (rawQueryEl) rawQueryEl.value = newText;
        wrapper.remove();
        contentDiv.style.display = '';
        editBtn.style.display = '';

        if (isTextReply && assistantContentDiv) {
            assistantContentDiv.className = "content markdown-content";
            assistantContentDiv.innerHTML = renderMarkdown(fullResponse);

            let rawDataEl = simbaBlock.querySelector('.raw-data');
            if (!rawDataEl) {
                rawDataEl = document.createElement('textarea');
                rawDataEl.className = 'raw-data';
                rawDataEl.style.display = 'none';
                simbaBlock.insertBefore(rawDataEl, assistantContentDiv);
            }
            if (rawDataEl) rawDataEl.value = fullResponse;

            simbaBlock.querySelectorAll('.reply-actions, .reply-mini-actions, .followup-suggestions, .message-reactions').forEach(el => el.remove());
            simbaBlock.insertAdjacentHTML('beforeend', renderCanonicalAssistantActionsHTML({
                messageId: simbaBlock.dataset.messageId || '',
                bookmarked: false,
                showFollowups: true,
            }));

            renderRichContent(simbaBlock);
            applyCodeButtons(simbaBlock);
            playBlip();
        }

        // Refresh ids: the new user node and new assistant node are
        // now the active leaf pair.
        const sID = res.headers.get('X-Session-ID');
        if (sID) {
            try {
                const leafRes = await fetch(`/session/${sID}/active-leaf/`, { signal: AbortSignal.timeout(10000) });
                if (leafRes.ok) {
                    const leafData = await leafRes.json();
                    if (leafData.message_id && isTextReply) {
                        simbaBlock.dataset.messageId = leafData.message_id;
                        const footer = simbaBlock.querySelector('.reply-actions');
                        if (footer) await refreshBranchSwitcher(leafData.message_id, footer);
                    }
                    if (leafData.user_message_id) {
                        userBlock.dataset.messageId = leafData.user_message_id;
                        await refreshBranchSwitcher(leafData.user_message_id, userBlock);
                    }
                }
            } catch (leafErr) {
                console.error("Could not refresh message id (non-fatal):", leafErr);
            }
        }
    } catch (e) {
        if (e.name === "AbortError" && watchdogTimedOut) {
            restore();
            alert("Edit timed out - no response from the server. Please try again.");
        } else if (e.name === "AbortError") {
            restore();
        } else {
            console.error("Edit failed:", e);
            restore();
            alert("Edit failed. Your original message is unchanged.");
        }
    } finally {
        clearWatchdog();
        isSendingQuery = false;
        currentAbortController = null;
        setSendButtonBusy(false);
    }
}

// ================= LOCAL STORAGE & INIT =================
function syncModelSelectorFromStorage() {
    const hiddenInput = document.getElementById("model-selector");
    const selectedText = document.getElementById("selectedText");
    if (!hiddenInput) return;

    const savedModel = localStorage.getItem("selected_simba_model");
    if (savedModel) {
        hiddenInput.value = savedModel;
        document.querySelectorAll("#cyberOptions .cyber-option").forEach(option => {
            const val = option.getAttribute("data-value");
            const isMatch = (val === savedModel);
            option.classList.toggle("active", isMatch);
            if (isMatch) {
                if (selectedText) selectedText.innerText = option.getAttribute("data-name") || option.querySelector('strong')?.innerText || option.innerText;
            }
        });
    }
    if (typeof updateAspectRatioVisibility === 'function') {
        updateAspectRatioVisibility();
    }
}

window.addEventListener("load", () => {
    syncModelSelectorFromStorage();
    formatAllMessages();
    if (typeof autoResizeComposerInput === 'function') autoResizeComposerInput();
    const cf = document.getElementById("chat-flow");
    if (cf) cf.scrollTop = cf.scrollHeight;
});

// ================= LIVE SYSTEM STATS =================
// Initialize history arrays and limit for sparklines (kept for potential future use)
const HISTORY_LIMIT = 20;
let cpuHistory = [];
let ramHistory = [];

let statsInFlight = false;

function updateSystemStats() {
    if (statsInFlight) return;
    statsInFlight = true;
    fetch('/system_stats/', { signal: AbortSignal.timeout(4000) })
        .then(res => res.json())
        .then(data => {
            statsInFlight = false;
            const rawCpu = typeof data.cpu === 'number' ? data.cpu : parseFloat(data.cpu) || 0;
            const rawRam = typeof data.ram === 'number' ? data.ram : parseFloat(data.ram) || 0;

            const cpuValEl = document.getElementById("cpu-val");
            const ramValEl = document.getElementById("ram-val");
            const cpuBarEl = document.getElementById("cpu-bar");
            const ramBarEl = document.getElementById("ram-bar");

            if (cpuValEl) cpuValEl.innerText = rawCpu.toFixed(1) + "%";
            if (ramValEl) ramValEl.innerText = rawRam.toFixed(1) + "%";

            // Update progress bars - ensure values are within 0-100 range
            const cpuPercent = Math.min(100, Math.max(0, rawCpu));
            const ramPercent = Math.min(100, Math.max(0, rawRam));

            if (cpuBarEl) cpuBarEl.style.width = cpuPercent + "%";
            if (ramBarEl) ramBarEl.style.width = ramPercent + "%";

            // Maintain history for potential future sparkline use
            cpuHistory.push(rawCpu);
            if (cpuHistory.length > HISTORY_LIMIT) cpuHistory.shift();

            ramHistory.push(rawRam);
            if (ramHistory.length > HISTORY_LIMIT) ramHistory.shift();
        })
        .catch(() => {
            statsInFlight = false;
        });
}

const SYSTEM_STATS_INTERVAL_MS = 5000;
let statsInterval = null;
function startStatsPolling() {
    if (statsInterval) return;
    updateSystemStats();
    statsInterval = setInterval(updateSystemStats, SYSTEM_STATS_INTERVAL_MS);
}
function stopStatsPolling() {
    if (!statsInterval) return;
    clearInterval(statsInterval);
    statsInterval = null;
}
document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopStatsPolling();
    else startStatsPolling();
});
if (!document.hidden) startStatsPolling();


// ================= LIVE WEATHER API (SMART CACHE) =================
function fetchEnvIntel() {
    // The ENV_INTEL widget's HTML is currently commented out in the sidebar.
    // Without this guard the callbacks below throw "Cannot set properties
    // of null" on every page load.
    if (!document.getElementById('env-temp') || !document.getElementById('env-status')) return;

    // મેમરીમાંથી જૂનું સેવ કરેલું તાપમાન લાવો
    const cachedTemp = sessionStorage.getItem('simba_env_temp');

    // ચેક કરો કે યુઝરે પેજ રિફ્રેશ (F5) કર્યું છે કે નહીં
    const navEntries = performance.getEntriesByType("navigation");
    const isReload = navEntries.length > 0 && navEntries[0].type === "reload";

    // જો ડેટા સેવ હોય અને રિફ્રેશ ના માર્યું હોય, તો સેવ કરેલો ડેટા જ વાપરો
    if (cachedTemp && !isReload) {
        document.getElementById('env-temp').innerText = cachedTemp;
        document.getElementById('env-status').innerText = "SECURE";
        document.getElementById('env-status').style.color = "#0edb2a";
        return; // અહીંથી જ પાછા ફરી જાવ, API કોલ ન કરો
    }

    // નહીંતર ઈન્ટરનેટ પરથી નવો ડેટા લાવો (ફક્ત રિફ્રેશ પર અથવા પહેલી વાર)
    document.getElementById('env-status').innerText = "SCANNING...";
    document.getElementById('env-status').style.color = "#a0aabf";

    // જૂનાગઢના કોઓર્ડિનેટ્સ
    fetch('https://api.open-meteo.com/v1/forecast?latitude=21.5222&longitude=70.4579¤t_weather=true')
        .then(res => res.json())
        .then(data => {
            const currentTemp = data.current_weather.temperature + "°C";
            document.getElementById('env-temp').innerText = currentTemp;
            document.getElementById('env-status').innerText = "SECURE";
            document.getElementById('env-status').style.color = "#0edb2a";

            // નવો ડેટા મેમરીમાં સેવ કરો જેથી બીજી ચેટમાં કામ લાગે
            sessionStorage.setItem('simba_env_temp', currentTemp);
        }).catch(e => {
            document.getElementById('env-status').innerText = "OFFLINE";
            document.getElementById('env-status').style.color = "#ff4444";
        });
}

// પેજ લોડ થાય એટલે તરત જ આ ફંક્શન ચલાવો (ટાઈમર ઓછું કરી દીધું છે)
setTimeout(fetchEnvIntel, 300);


// ===== SIMBA MIC VOICE SYSTEM =====

const micBtn = document.getElementById("micBtn")
const inputBox = document.getElementById("user-input")
const waveContainer = document.getElementById("wave-container")

let recognition
let listening = false


// ---- SPEECH ENGINE (Unified with SIMBA Desktop Agent Pipeline) ----
if ('webkitSpeechRecognition' in window) {

    recognition = new webkitSpeechRecognition()

    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = "en-US"

    recognition.onstart = () => {
        micBtn.classList.add("mic-active")
        if (waveContainer) {
            waveContainer.style.display = "flex"
        }
    }

    recognition.onresult = (event) => {
        let transcript = ""

        for (let i = event.resultIndex; i < event.results.length; i++) {
            transcript += event.results[i][0].transcript
        }

        transcript = transcript.trim()

        // show live speech
        inputBox.value = transcript

        if (event.results[event.results.length - 1].isFinal) {
            const finalTranscript = transcript;
            inputBox.value = finalTranscript;
            listening = false;
            try {
                recognition.stop();
            } catch (e) { }

            // Feed directly into the unified Agent / Chat pipeline
            if (finalTranscript) {
                sendQuery(finalTranscript);
            }
        }
    }

    recognition.onend = () => {
        micBtn.classList.remove("mic-active")
        if (waveContainer) {
            waveContainer.style.display = "none"
        }
        if (listening) {
            try {
                recognition.start()
            } catch (e) { }
        }
    }
}


// ---- MIC BUTTON ----
micBtn.onclick = () => {

    if (!recognition) return

    if (!listening) {

        listening = true
        recognition.start()

    } else {

        listening = false
        recognition.stop()

    }

}



const input = document.getElementById("user-input");

if (input) {
    input.addEventListener("input", () => {
        autoResizeComposerInput(input);
    });
    input.addEventListener("keydown", function (e) {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            if (e.isComposing || e.repeat) return;
            if (isSendingQuery || isGeneratingImage) return;
            sendQuery();
        }
    });
}

// ================= Professional Contextual Quick Action Engine =================
const QUICK_ACTION_REGISTRY = {
    'explain-pdf': {
        id: 'explain-pdf',
        label: 'Explain PDF',
        icon: 'fa-solid fa-file-pdf',
        category: 'understand',
        mode: 'document',
        badge: 'PDF Document Analysis',
        placeholder: 'Attach a PDF or ask about your document...',
        workflow: 'pdf',
        description: 'Analyze, explain, or extract data from PDF files'
    },
    'analyze-image': {
        id: 'analyze-image',
        label: 'Analyze Image',
        icon: 'fa-solid fa-image',
        category: 'understand',
        mode: 'vision',
        badge: 'Vision Analysis',
        placeholder: 'Attach an image or describe what to analyze...',
        workflow: 'image-analysis',
        description: 'Perform AI vision inspection on images or charts'
    },
    'write-code': {
        id: 'write-code',
        label: 'Write Code',
        icon: 'fa-solid fa-code',
        category: 'create',
        mode: 'coding',
        badge: 'Code Generator',
        placeholder: 'Describe the code or function you want to create...',
        workflow: 'coding',
        description: 'Generate production-ready code in any language'
    },
    'debug-code': {
        id: 'debug-code',
        label: 'Debug Code',
        icon: 'fa-solid fa-bug',
        category: 'develop',
        mode: 'diagnostics',
        badge: 'Diagnostics & Debug',
        placeholder: 'Paste your code snippet or describe the error...',
        workflow: 'debug',
        description: 'Find bugs, trace exceptions, and get fixes'
    },
    'generate-image': {
        id: 'generate-image',
        label: 'Generate Image',
        icon: 'fa-solid fa-wand-magic-sparkles',
        category: 'create',
        mode: 'image',
        badge: 'Image Studio',
        placeholder: 'Describe the image you want to generate...',
        workflow: 'image-gen',
        description: 'Create high-resolution AI artwork via Image Studio'
    },
    'build-react-app': {
        id: 'build-react-app',
        label: 'Build React App',
        icon: 'fa-brands fa-react',
        category: 'develop',
        mode: 'frontend',
        badge: 'React App Builder',
        placeholder: 'Describe the React app or UI component you want to build...',
        workflow: 'frontend',
        description: 'Scaffold interactive modern React web applications'
    },
    'sql-query': {
        id: 'sql-query',
        label: 'SQL Query',
        icon: 'fa-solid fa-database',
        category: 'develop',
        mode: 'database',
        badge: 'SQL & Database',
        placeholder: 'Describe the SQL query or database problem...',
        workflow: 'database',
        description: 'Write, optimize, and explain SQL queries'
    },
    'summarize-notes': {
        id: 'summarize-notes',
        label: 'Summarize Notes',
        icon: 'fa-solid fa-file-invoice',
        category: 'understand',
        mode: 'memory',
        badge: 'Summarization',
        placeholder: 'Paste notes or attach a document to summarize...',
        workflow: 'summarize',
        description: 'Synthesize meeting notes, articles, or transcripts'
    },
    'refactor-code': {
        id: 'refactor-code',
        label: 'Refactor Code',
        icon: 'fa-solid fa-arrows-rotate',
        category: 'develop',
        mode: 'coding',
        badge: 'Code Refactor',
        placeholder: 'Paste the code you want to optimize and refactor...',
        workflow: 'coding',
        description: 'Clean up code architecture, naming, and patterns'
    },
    'test-code': {
        id: 'test-code',
        label: 'Test Code',
        icon: 'fa-solid fa-vial-circle-check',
        category: 'develop',
        mode: 'coding',
        badge: 'Test Suite Generator',
        placeholder: 'Paste code to generate unit & integration tests...',
        workflow: 'coding',
        description: 'Generate unit tests and edge-case assertions'
    },
    'explain-code': {
        id: 'explain-code',
        label: 'Explain Code',
        icon: 'fa-solid fa-circle-question',
        category: 'understand',
        mode: 'coding',
        badge: 'Code Explanation',
        placeholder: 'Paste the code you want explained step-by-step...',
        workflow: 'coding',
        description: 'Break down complex logic into clear explanations'
    },
    'extract-text': {
        id: 'extract-text',
        label: 'Extract Text (OCR)',
        icon: 'fa-solid fa-font',
        category: 'understand',
        mode: 'vision',
        badge: 'Text Extraction OCR',
        placeholder: 'Attach an image or screenshot to extract text from...',
        workflow: 'image-analysis',
        description: 'Extract readable text and tabular data from images'
    },
    'describe-image': {
        id: 'describe-image',
        label: 'Describe Image',
        icon: 'fa-solid fa-eye',
        category: 'understand',
        mode: 'vision',
        badge: 'Visual Description',
        placeholder: 'Attach an image to get a detailed scene description...',
        workflow: 'image-analysis',
        description: 'Generate detailed accessibility and visual descriptions'
    },
    'optimize-query': {
        id: 'optimize-query',
        label: 'Optimize Query',
        icon: 'fa-solid fa-gauge-high',
        category: 'develop',
        mode: 'database',
        badge: 'Query Optimization',
        placeholder: 'Paste the slow SQL query and table schemas to optimize...',
        workflow: 'database',
        description: 'Improve database indexes, joins, and query plan speed'
    },
    'extract-key-points': {
        id: 'extract-key-points',
        label: 'Extract Key Points',
        icon: 'fa-solid fa-list-check',
        category: 'understand',
        mode: 'document',
        badge: 'Key Points Extraction',
        placeholder: 'Attach a document or paste text to extract key bullet points...',
        workflow: 'pdf',
        description: 'Pull high-impact takeaways from lengthy text'
    }
};

let activeTaskMode = null;
let previousModelBeforeTask = null;
let currentActionCategory = 'all';

function activateQuickAction(actionId) {
    const action = QUICK_ACTION_REGISTRY[actionId];
    if (!action) return;

    activeTaskMode = actionId;

    // 1. Update active task banner
    const banner = document.getElementById('composerTaskContext');
    const tagIcon = document.getElementById('composerTaskIcon');
    const tagLabel = document.getElementById('composerTaskLabel');
    if (banner && tagIcon && tagLabel) {
        tagIcon.className = action.icon;
        tagLabel.textContent = action.badge || action.label;
        banner.style.display = 'flex';
    }

    // 2. Set contextual placeholder without entering raw text
    const input = document.getElementById('user-input');
    if (input) {
        input.placeholder = action.placeholder;
        input.focus();
    }

    // 3. Trigger workflow action
    if (action.workflow === 'image-gen') {
        const modelSelector = document.getElementById('model-selector');
        if (modelSelector && modelSelector.value !== 'image-studio') {
            previousModelBeforeTask = modelSelector.value || 'auto';
        }
        switchToImageMode();
    } else if (action.workflow === 'pdf') {
        triggerFilePicker('pdf');
    } else if (action.workflow === 'image-analysis') {
        triggerFilePicker('image');
    }

    // 4. Update quantum core HUD glow if present
    if (typeof window.applyQcMode === 'function' && action.mode) {
        window.applyQcMode(action.mode);
    }
}

async function resetComposerTaskMode() {
    activeTaskMode = null;

    // 1. Hide task banner
    const banner = document.getElementById('composerTaskContext');
    if (banner) banner.style.display = 'none';

    // 2. If we entered Image Studio from quick action, revert back to previous model or auto
    const modelSelector = document.getElementById('model-selector');
    if (modelSelector && modelSelector.value === 'image-studio' && previousModelBeforeTask) {
        const targetModel = previousModelBeforeTask || 'auto';
        previousModelBeforeTask = null;
        modelSelector.value = targetModel;

        const optionsBox = document.getElementById('cyberOptions');
        const selectedText = document.getElementById('selectedText');
        if (optionsBox && selectedText) {
            const targetOption = optionsBox.querySelector(`.cyber-option[data-value="${targetModel}"]`);
            if (targetOption) {
                selectedText.innerText = targetOption.innerText;
                optionsBox.querySelectorAll('.cyber-option').forEach(o => o.classList.remove('active'));
                targetOption.classList.add('active');
            }
        }
        localStorage.setItem('selected_simba_model', targetModel);
        if (typeof updateAspectRatioVisibility === 'function') updateAspectRatioVisibility();
        try { await fetch(`/update_model/?model_id=${encodeURIComponent(targetModel)}`); } catch (e) { }
    }

    // 3. Revert composer placeholder
    if (typeof updateComposerPlaceholder === 'function') {
        updateComposerPlaceholder();
    }

    // 4. Revert quantum core HUD glow to idle
    if (typeof window.applyQcMode === 'function') {
        window.applyQcMode(null);
    }

    // 5. Focus input
    const input = document.getElementById('user-input');
    if (input) input.focus();
}

function detectCurrentChatContext() {
    if (typeof pendingAttachments !== 'undefined' && pendingAttachments.length > 0) {
        if (pendingAttachments.some(a => a.isImage || /\.(jpe?g|png|webp|gif|bmp)$/i.test(a.name || ''))) return 'image';
        if (pendingAttachments.some(a => /\.pdf$/i.test(a.name || ''))) return 'pdf';
        return 'document';
    }

    const blocks = document.querySelectorAll('#chat-flow .chat-block');
    if (!blocks || blocks.length === 0) return 'general';

    let combined = '';
    const sample = Array.from(blocks).slice(-4);
    sample.forEach(b => { combined += ' ' + (b.innerText || '').toLowerCase(); });

    if (combined.includes('select ') && (combined.includes(' from ') || combined.includes(' where ') || combined.includes('join ') || combined.includes('database') || combined.includes('table '))) {
        return 'sql';
    }
    if (combined.includes('```') || combined.includes('def ') || combined.includes('function ') || combined.includes('const ') || combined.includes('class ') || combined.includes('import ') || combined.includes('react') || combined.includes('python') || combined.includes('javascript')) {
        return 'programming';
    }
    if (combined.includes('image') || combined.includes('photo') || combined.includes('picture') || document.querySelector('.msg-attachment-img')) {
        return 'image';
    }
    if (combined.includes('pdf') || combined.includes('document') || document.querySelector('.msg-attachment-doc')) {
        return 'pdf';
    }
    return 'general';
}

function getContextPrioritizedActionIds(ctx) {
    if (ctx === 'programming') {
        return ['write-code', 'debug-code', 'refactor-code', 'test-code', 'explain-code', 'build-react-app'];
    }
    if (ctx === 'image') {
        return ['analyze-image', 'describe-image', 'extract-text', 'generate-image'];
    }
    if (ctx === 'pdf') {
        return ['explain-pdf', 'summarize-notes', 'extract-key-points'];
    }
    if (ctx === 'sql') {
        return ['sql-query', 'optimize-query', 'debug-code'];
    }
    return ['explain-pdf', 'analyze-image', 'write-code', 'debug-code', 'generate-image', 'build-react-app', 'sql-query', 'summarize-notes'];
}

let showAllQuickActions = false;

function toggleMoreQuickActions() {
    showAllQuickActions = !showAllQuickActions;
    renderQuickActions();
}

function filterQuickActions(category) {
    currentActionCategory = category;
    showAllQuickActions = false;
    document.querySelectorAll('#qcCategoryBar .qc-cat-btn').forEach(b => {
        const isActive = b.dataset.category === category;
        b.classList.toggle('active', isActive);
        b.setAttribute('aria-selected', isActive ? 'true' : 'false');
    });
    renderQuickActions();
}

function renderQuickActions() {
    const container = document.getElementById('qcCommandsContainer');
    if (!container) return;

    const ctx = detectCurrentChatContext();
    let actionIds = [];

    if (currentActionCategory === 'all') {
        if (showAllQuickActions) {
            actionIds = Object.keys(QUICK_ACTION_REGISTRY);
        } else {
            actionIds = getContextPrioritizedActionIds(ctx).slice(0, 8);
        }
    } else {
        actionIds = Object.keys(QUICK_ACTION_REGISTRY).filter(id => {
            return QUICK_ACTION_REGISTRY[id].category === currentActionCategory;
        });
    }

    let chipsHTML = actionIds.map(id => {
        const a = QUICK_ACTION_REGISTRY[id];
        if (!a) return '';
        return `<button type="button" class="qc-chip" data-action="${a.id}" data-mode="${a.mode}" onclick="activateQuickAction('${a.id}')" title="${escapeHtml(a.description || a.label)}" aria-label="${escapeHtml(a.label)}">
                        <span class="qc-chip-icon"><i class="${a.icon}"></i></span>
                        <span>${escapeHtml(a.label)}</span>
                    </button>`;
    }).join('');

    if (currentActionCategory === 'all') {
        if (showAllQuickActions) {
            chipsHTML += `<button type="button" class="qc-chip qc-chip-more" onclick="toggleMoreQuickActions()" title="Show fewer assistant actions" aria-label="Show fewer actions">
                            <span class="qc-chip-icon"><i class="fa-solid fa-chevron-up"></i></span>
                            <span>Less</span>
                        </button>`;
        } else {
            chipsHTML += `<button type="button" class="qc-chip qc-chip-more" onclick="toggleMoreQuickActions()" title="View all available assistant actions" aria-label="View all actions">
                            <span class="qc-chip-icon"><i class="fa-solid fa-ellipsis"></i></span>
                            <span>More</span>
                        </button>`;
        }
    }

    container.innerHTML = chipsHTML;

    container.querySelectorAll('.qc-chip[data-mode]').forEach(chip => {
        chip.addEventListener('mouseenter', () => { if (typeof window.applyQcMode === 'function') window.applyQcMode(chip.dataset.mode); });
        chip.addEventListener('focus', () => { if (typeof window.applyQcMode === 'function') window.applyQcMode(chip.dataset.mode); });
        chip.addEventListener('mouseleave', () => {
            if (typeof window.applyQcMode === 'function') {
                const current = activeTaskMode ? QUICK_ACTION_REGISTRY[activeTaskMode]?.mode : null;
                window.applyQcMode(current);
            }
        });
        chip.addEventListener('blur', () => {
            if (typeof window.applyQcMode === 'function') {
                const current = activeTaskMode ? QUICK_ACTION_REGISTRY[activeTaskMode]?.mode : null;
                window.applyQcMode(current);
            }
        });
    });
}

// Compatibility shim for any legacy callers
function fillHomeAction(promptText) {
    const lower = (promptText || '').toLowerCase();
    if (lower.includes('image') && lower.includes('generate')) activateQuickAction('generate-image');
    else if (lower.includes('pdf') || lower.includes('document')) activateQuickAction('explain-pdf');
    else if (lower.includes('image') && lower.includes('analyze')) activateQuickAction('analyze-image');
    else if (lower.includes('debug')) activateQuickAction('debug-code');
    else if (lower.includes('react')) activateQuickAction('build-react-app');
    else if (lower.includes('sql')) activateQuickAction('sql-query');
    else if (lower.includes('code')) activateQuickAction('write-code');
    else if (lower.includes('summarize')) activateQuickAction('summarize-notes');
    else {
        const input = document.getElementById("user-input");
        if (input) {
            input.value = promptText;
            input.focus();
            autoResizeComposerInput(input);
        }
    }
}

// ================= Image Studio Functions =================
async function switchToImageMode() {
    const hiddenInput = document.getElementById("model-selector");
    const optionsBox = document.getElementById("cyberOptions");
    const selectedText = document.getElementById("selectedText");

    if (hiddenInput) hiddenInput.value = "image-studio";
    if (optionsBox) {
        const imageOption = optionsBox.querySelector('.cyber-option[data-value="image-studio"]');
        if (imageOption) {
            if (selectedText) selectedText.innerText = imageOption.innerText;
            optionsBox.querySelectorAll(".cyber-option").forEach(o => o.classList.remove("active"));
            imageOption.classList.add("active");
        }
    }
    localStorage.setItem("selected_simba_model", "image-studio");
    if (typeof updateAspectRatioVisibility === 'function') updateAspectRatioVisibility();
    try {
        await fetch(`/update_model/?model_id=image-studio`);
    } catch (e) { }
}

function checkUnlock(e) {
    if (e.key === 'Enter') {
        const pass = document.getElementById('lock-pass');
        // Cosmetic-only "lockdown" Easter egg (real access control is
        // Django's @login_required, not this) - unlock code is
        // generic rather than any one person's name.
        if (pass.value === 'admin') {
            document.getElementById('lockdown-screen').style.display = 'none';
            pass.value = '';
            pass.style.borderColor = 'rgba(255, 68, 68, 0.4)';
            pass.placeholder = "PASSCODE...";
        } else {
            pass.style.borderColor = 'red';
            pass.value = '';
            pass.placeholder = "ACCESS DENIED!";
        }
    }
}

// ================= MESSAGE REACTIONS =================
function toggleReaction(button, messageId, role, reaction) {
    // Toggle active state on button
    button.classList.toggle('active');

    // Get the reaction count element (next sibling)
    const countSpan = button.nextElementSibling;
    let count = parseInt(countSpan.textContent || '0');

    // If button is now active, increment count, else decrement
    if (button.classList.contains('active')) {
        count++;
    } else {
        count = Math.max(0, count - 1); // Don't go below 0
    }

    countSpan.textContent = count;

    // Send AJAX request to update reactions in database
    fetch(`/update_reaction/`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCookie('csrftoken')
        },
        body: JSON.stringify({
            message_id: messageId,
            role: role,
            reaction: reaction
        })
    }).then(response => {
        if (!response.ok) {
            // Revert the UI change on failure
            button.classList.toggle('active');
            countSpan.textContent = button.classList.contains('active') ?
                (parseInt(countSpan.textContent || '0') + 1) :
                Math.max(0, (parseInt(countSpan.textContent || '0') - 1));
        }
    }).catch(error => {
        // Revert the UI change on error
        button.classList.toggle('active');
        countSpan.textContent = button.classList.contains('active') ?
            (parseInt(countSpan.textContent || '0') + 1) :
            Math.max(0, (parseInt(countSpan.textContent || '0') - 1));
        console.error('Error updating reaction:', error);
    });
}

// =========================================================================
// SIMBA INTEL — VIBE-CODED PRODUCT EXPERIENCE & MOTION SYSTEM
// =========================================================================

// ---- 1. UNIFIED TOAST NOTIFICATION SYSTEM ----
function showSimbaToast(message, type = 'info', duration = 3200) {
    const container = document.getElementById('simbaToastContainer');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `simba-toast toast-${type}`;

    let iconClass = 'fa-solid fa-circle-info';
    if (type === 'success') iconClass = 'fa-solid fa-circle-check';
    else if (type === 'warning') iconClass = 'fa-solid fa-triangle-exclamation';
    else if (type === 'danger') iconClass = 'fa-solid fa-circle-xmark';

    toast.innerHTML = `
                    <i class="${iconClass} simba-toast-icon"></i>
                    <span class="simba-toast-msg">${message}</span>
                    <button type="button" class="simba-toast-close" aria-label="Dismiss">&times;</button>
                `;

    const closeBtn = toast.querySelector('.simba-toast-close');
    const dismiss = () => {
        toast.classList.add('toast-leaving');
        setTimeout(() => { if (toast.parentNode) toast.parentNode.removeChild(toast); }, 250);
    };

    closeBtn.addEventListener('click', dismiss);
    container.appendChild(toast);

    if (duration > 0) {
        setTimeout(dismiss, duration);
    }
}

// ---- 2. COMMAND PALETTE 2.0 (Ctrl+K / Cmd+K) ----
let paletteActiveIndex = 0;
let paletteItemsList = [];

function applySimbaTheme(themeName) {
    document.documentElement.setAttribute('data-theme', themeName);
    localStorage.setItem('simba_selected_theme', themeName);
    showSimbaToast(`Theme switched to ${themeName}`, 'success');
}

const defaultPaletteCatalog = [
    { section: 'Quick Actions', title: 'New Conversation', subtitle: 'Initialize fresh intel session', icon: 'fa-solid fa-plus', badge: 'Action', action: () => { window.location.href = '/'; } },
    { section: 'Quick Actions', title: 'Start Desktop Agent', subtitle: 'Open local PC automation controls', icon: 'fa-solid fa-desktop', badge: 'Agent', action: () => { openDesktopAgentModal(); } },
    { section: 'Quick Actions', title: 'Voice Uplink Studio', subtitle: 'Synthesize audio & voice generation', icon: 'fa-solid fa-microphone', badge: 'Voice', action: () => { toggleVoiceUplink(); } },
    { section: 'Quick Actions', title: 'Deep Research Mode', subtitle: 'Activate autonomous multi-step research', icon: 'fa-solid fa-brain', badge: 'Research', action: () => { switchToDeepResearch(); } },
    { section: 'Quick Actions', title: 'Profile & Settings', subtitle: 'Themes, density, model defaults & keys', icon: 'fa-solid fa-gear', badge: 'Config', action: () => { window.location.href = '/settings/'; } },
    { section: 'Quick Actions', title: 'Analytics Dashboard', subtitle: 'System metrics & model usage telemetry', icon: 'fa-solid fa-chart-line', badge: 'Metrics', action: () => { window.location.href = '/analytics/'; } },
    { section: 'Quick Actions', title: 'Export Chat as PDF', subtitle: 'Download formatted transcript', icon: 'fa-solid fa-file-pdf', badge: 'Export', action: () => { const btn = document.querySelector('[data-chat-title]'); if (btn) btn.click(); else showSimbaToast('No active chat to export', 'warning'); } },

    { section: 'Files & Media', title: 'Upload Document / PDF', subtitle: 'Attach PDF, text, or code file', icon: 'fa-solid fa-file-arrow-up', badge: 'Upload', action: () => { triggerFilePicker('file'); } },
    { section: 'Files & Media', title: 'Upload Image', subtitle: 'Attach image for vision analysis', icon: 'fa-solid fa-image', badge: 'Upload', action: () => { triggerFilePicker('image'); } },
    { section: 'Files & Media', title: 'Capture Camera Photo', subtitle: 'Snap live photo for SIMBA Vision', icon: 'fa-solid fa-camera', badge: 'Camera', action: () => { openCameraCapture(); } },

    { section: 'Bookmarks & Prompts', title: 'Open Saved Bookmarks', subtitle: 'View bookmarked conversations and messages', icon: 'fa-solid fa-bookmark', badge: 'Saved', action: () => { openBookmarksPanel(); } },
    { section: 'Bookmarks & Prompts', title: 'Open Prompt Library', subtitle: 'Browse and run reusable prompt templates', icon: 'fa-solid fa-book-bookmark', badge: 'Prompts', action: () => { openPromptLibrary(); } },
    { section: 'Bookmarks & Prompts', title: 'Save Prompt to Library', subtitle: 'Store current composer text', icon: 'fa-solid fa-floppy-disk', badge: 'Save', action: () => { savePromptFromComposer(); } },

    { section: 'Themes & Visuals', title: 'Theme: Cyberpunk (Cyan)', subtitle: 'Default futuristic cyan glow', icon: 'fa-solid fa-palette', badge: 'Theme', action: () => { applySimbaTheme('cyberpunk'); } },
    { section: 'Themes & Visuals', title: 'Theme: Midnight Purple', subtitle: 'Deep cosmic violet ambient palette', icon: 'fa-solid fa-palette', badge: 'Theme', action: () => { applySimbaTheme('midnight-purple'); } },
    { section: 'Themes & Visuals', title: 'Theme: Matrix Green', subtitle: 'Terminal phosphor emerald matrix', icon: 'fa-solid fa-palette', badge: 'Theme', action: () => { applySimbaTheme('matrix-green'); } },
    { section: 'Themes & Visuals', title: 'Theme: Cyber Orange', subtitle: 'Amber industrial tech glow', icon: 'fa-solid fa-palette', badge: 'Theme', action: () => { applySimbaTheme('cyber-orange'); } },
    { section: 'Themes & Visuals', title: 'Theme: Ocean Cyan', subtitle: 'Deep sea aquamarine interface', icon: 'fa-solid fa-palette', badge: 'Theme', action: () => { applySimbaTheme('ocean'); } },
    { section: 'Themes & Visuals', title: 'Theme: Nord Frost', subtitle: 'Arctic muted blue-grey palette', icon: 'fa-solid fa-palette', badge: 'Theme', action: () => { applySimbaTheme('nord'); } },
    { section: 'Themes & Visuals', title: 'Theme: Light Mode', subtitle: 'Clean high-contrast crisp theme', icon: 'fa-solid fa-sun', badge: 'Theme', action: () => { applySimbaTheme('light'); } },

    { section: 'Slash Commands', title: '/agent <task>', subtitle: 'Direct desktop agent automation task', icon: 'fa-solid fa-terminal', badge: 'Command', action: () => { focusComposerWithText('/agent '); } },
    { section: 'Slash Commands', title: '/voice <text>', subtitle: 'Synthesize audio response', icon: 'fa-solid fa-wave-square', badge: 'Command', action: () => { focusComposerWithText('/voice '); } },
    { section: 'Slash Commands', title: '/research <topic>', subtitle: 'Trigger deep multi-source research', icon: 'fa-solid fa-magnifying-glass-chart', badge: 'Command', action: () => { focusComposerWithText('/research '); } },
    { section: 'Slash Commands', title: '/code <spec>', subtitle: 'Code generation & debugging prompt', icon: 'fa-solid fa-code', badge: 'Command', action: () => { focusComposerWithText('/code '); } },
    { section: 'Slash Commands', title: '/help', subtitle: 'System assistance and command list', icon: 'fa-solid fa-circle-question', badge: 'Command', action: () => { focusComposerWithText('/help'); } },
    { section: 'Slash Commands', title: '/clear', subtitle: 'Clear prompt input', icon: 'fa-solid fa-eraser', badge: 'Command', action: () => { const inp = document.getElementById('user-input'); if (inp) inp.value = ''; } }
];

function getLiveConversationsForPalette() {
    const results = [];
    const rows = document.querySelectorAll('.chat-item-container');
    rows.forEach(row => {
        const titleEl = row.querySelector('.chat-link-title') || row.querySelector('.chat-title');
        const link = row.querySelector('.chat-link');
        if (titleEl && link) {
            const title = titleEl.textContent.trim();
            const href = link.getAttribute('href');
            results.push({
                section: 'Conversations',
                title: title,
                subtitle: 'Open chat session',
                icon: 'fa-solid fa-message',
                badge: 'Chat',
                action: () => { window.location.href = href; }
            });
        }
    });
    return results;
}

function openCommandPalette() {
    const modal = document.getElementById('commandPalette');
    const input = document.getElementById('cmdPaletteInput');
    if (!modal || !input) return;

    modal.classList.add('active');
    input.value = '';
    paletteActiveIndex = 0;
    renderPaletteResults('');
    setTimeout(() => input.focus(), 50);
}

function closeCommandPalette() {
    const modal = document.getElementById('commandPalette');
    if (modal) modal.classList.remove('active');
}

function filterCommandPalette(query) {
    paletteActiveIndex = 0;
    renderPaletteResults(query);
}

function renderPaletteResults(query) {
    const container = document.getElementById('cmdPaletteResults');
    if (!container) return;

    const cleanQ = query.trim().toLowerCase();
    const allItems = [...defaultPaletteCatalog, ...getLiveConversationsForPalette()];

    paletteItemsList = allItems.filter(item => {
        if (!cleanQ) return true;
        return item.title.toLowerCase().includes(cleanQ) ||
            item.subtitle.toLowerCase().includes(cleanQ) ||
            item.section.toLowerCase().includes(cleanQ);
    });

    if (paletteItemsList.length === 0) {
        container.innerHTML = `
                        <div style="padding: 24px; text-align: center; color: var(--text-dim); font-size: 13px;">
                            <i class="fa-solid fa-magnifying-glass" style="margin-bottom: 8px; font-size: 18px; opacity: 0.5;"></i>
                            <p>No matching commands or conversations found for "${escapeHtml(cleanQ)}"</p>
                        </div>
                    `;
        return;
    }

    // Group items by section
    let html = '';
    let currentSection = '';

    paletteItemsList.forEach((item, idx) => {
        if (item.section !== currentSection) {
            currentSection = item.section;
            html += `<div class="palette-section-header">${currentSection}</div>`;
        }
        const isActive = idx === paletteActiveIndex ? 'active' : '';
        html += `
                        <div class="palette-item ${isActive}" data-idx="${idx}" onclick="executePaletteItem(${idx})">
                            <div class="palette-item-icon"><i class="${item.icon}"></i></div>
                            <div class="palette-item-details">
                                <div class="palette-item-title">${escapeHtml(item.title)}</div>
                                <div class="palette-item-subtitle">${escapeHtml(item.subtitle)}</div>
                            </div>
                            <span class="palette-item-badge">${item.badge}</span>
                        </div>
                    `;
    });

    container.innerHTML = html;
}

function executePaletteItem(index) {
    if (paletteItemsList[index] && typeof paletteItemsList[index].action === 'function') {
        closeCommandPalette();
        paletteItemsList[index].action();
    }
}

function focusComposerWithText(text) {
    const input = document.getElementById('user-input');
    if (input) {
        input.value = text;
        input.focus();
        input.selectionStart = input.selectionEnd = input.value.length;
        autoResizeComposerInput(input);
    }
}

function switchToDeepResearch() {
    const hiddenInput = document.getElementById('model-selector');
    const selectedText = document.getElementById('selectedText');
    if (hiddenInput) hiddenInput.value = 'gemini-1.5-pro';
    if (selectedText) selectedText.innerText = 'Deep Research (Pro)';
    showSimbaToast('Switched to Deep Research Mode', 'info');
}

// Keyboard navigation for Command Palette
document.addEventListener('keydown', (e) => {
    // Global Ctrl+K / Cmd+K trigger
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        const modal = document.getElementById('commandPalette');
        if (modal && modal.classList.contains('active')) {
            closeCommandPalette();
        } else {
            openCommandPalette();
        }
        return;
    }

    const modal = document.getElementById('commandPalette');
    if (!modal || !modal.classList.contains('active')) return;

    if (e.key === 'Escape') {
        e.preventDefault();
        closeCommandPalette();
    } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        if (paletteItemsList.length > 0) {
            paletteActiveIndex = (paletteActiveIndex + 1) % paletteItemsList.length;
            updatePaletteActiveDOM();
        }
    } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        if (paletteItemsList.length > 0) {
            paletteActiveIndex = (paletteActiveIndex - 1 + paletteItemsList.length) % paletteItemsList.length;
            updatePaletteActiveDOM();
        }
    } else if (e.key === 'Enter') {
        e.preventDefault();
        executePaletteItem(paletteActiveIndex);
    }
});

function updatePaletteActiveDOM() {
    const items = document.querySelectorAll('.palette-item');
    items.forEach((item) => {
        const idx = parseInt(item.getAttribute('data-idx'));
        if (idx === paletteActiveIndex) {
            item.classList.add('active');
            item.scrollIntoView({ block: 'nearest' });
        } else {
            item.classList.remove('active');
        }
    });
}

// Input event for command palette search
const paletteSearchInput = document.getElementById('cmdPaletteInput');
if (paletteSearchInput) {
    paletteSearchInput.addEventListener('input', function () {
        filterCommandPalette(this.value);
    });
}

// ---- 3. SMART COMPOSER AUTOCOMPLETE (@ & /) ----
const autocompleteCatalog = [
    { trigger: '@', token: '@agent', desc: 'Autonomous PC desktop actions', icon: 'fa-solid fa-desktop' },
    { trigger: '@', token: '@voice', desc: 'Voice synthesis & audio mode', icon: 'fa-solid fa-microphone' },
    { trigger: '@', token: '@research', desc: 'Deep multi-source web research', icon: 'fa-solid fa-brain' },
    { trigger: '@', token: '@code', desc: 'Coding, debugging & scripts', icon: 'fa-solid fa-code' },
    { trigger: '@', token: '@image', desc: 'Image synthesis studio', icon: 'fa-solid fa-palette' },

    { trigger: '/', token: '/agent ', desc: 'Direct PC automation task', icon: 'fa-solid fa-desktop' },
    { trigger: '/', token: '/voice ', desc: 'Voice response uplink', icon: 'fa-solid fa-microphone' },
    { trigger: '/', token: '/research ', desc: 'Deep research workflow', icon: 'fa-solid fa-magnifying-glass' },
    { trigger: '/', token: '/code ', desc: 'Generate & inspect code', icon: 'fa-solid fa-code' },
    { trigger: '/', token: '/settings', desc: 'Open system settings', icon: 'fa-solid fa-gear' },
    { trigger: '/', token: '/help', desc: 'System commands & docs', icon: 'fa-solid fa-circle-question' },
    { trigger: '/', token: '/clear', desc: 'Clear composer text', icon: 'fa-solid fa-eraser' }
];

let autocompleteActiveIdx = 0;
let currentAutocompleteMatches = [];

function initComposerAutocomplete() {
    const input = document.getElementById('user-input');
    const menu = document.getElementById('composerAutocomplete');
    const results = document.getElementById('autocompleteResults');
    const header = document.getElementById('autocompleteHeader');
    if (!input || !menu || !results) return;

    input.addEventListener('input', () => {
        const val = input.value;
        const pos = input.selectionStart;
        const textBefore = val.slice(0, pos);
        const lastWord = textBefore.split(/\s+/).pop() || '';

        if (lastWord.startsWith('@') || lastWord.startsWith('/')) {
            const triggerChar = lastWord[0];

            currentAutocompleteMatches = autocompleteCatalog.filter(item =>
                item.trigger === triggerChar && item.token.toLowerCase().includes(lastWord.toLowerCase())
            );

            if (currentAutocompleteMatches.length > 0) {
                header.textContent = triggerChar === '@' ? 'Mention Mode' : 'Slash Commands';
                autocompleteActiveIdx = 0;
                results.innerHTML = currentAutocompleteMatches.map((item, i) => `
                                <div class="autocomplete-item ${i === 0 ? 'active' : ''}" data-idx="${i}" onclick="selectAutocompleteToken(${i})">
                                    <div class="autocomplete-icon"><i class="${item.icon}"></i></div>
                                    <span class="autocomplete-token">${escapeHtml(item.token)}</span>
                                    <span class="autocomplete-desc">${escapeHtml(item.desc)}</span>
                                </div>
                            `).join('');
                menu.classList.add('active');
                return;
            }
        }
        menu.classList.remove('active');
    });

    input.addEventListener('keydown', (e) => {
        if (!menu.classList.contains('active')) return;

        if (e.key === 'ArrowDown') {
            e.preventDefault();
            autocompleteActiveIdx = (autocompleteActiveIdx + 1) % currentAutocompleteMatches.length;
            updateAutocompleteDOM();
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            autocompleteActiveIdx = (autocompleteActiveIdx - 1 + currentAutocompleteMatches.length) % currentAutocompleteMatches.length;
            updateAutocompleteDOM();
        } else if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey)) {
            e.preventDefault();
            selectAutocompleteToken(autocompleteActiveIdx);
        } else if (e.key === 'Escape') {
            menu.classList.remove('active');
        }
    });

    document.addEventListener('click', (e) => {
        if (!menu.contains(e.target) && e.target !== input) {
            menu.classList.remove('active');
        }
    });
}

function updateAutocompleteDOM() {
    const items = document.querySelectorAll('.autocomplete-item');
    items.forEach((item, idx) => {
        if (idx === autocompleteActiveIdx) {
            item.classList.add('active');
            item.scrollIntoView({ block: 'nearest' });
        } else {
            item.classList.remove('active');
        }
    });
}

function selectAutocompleteToken(idx) {
    const item = currentAutocompleteMatches[idx];
    const input = document.getElementById('user-input');
    const menu = document.getElementById('composerAutocomplete');
    if (!item || !input) return;

    const val = input.value;
    const pos = input.selectionStart;
    const textBefore = val.slice(0, pos);
    const textAfter = val.slice(pos);
    const words = textBefore.split(/\s+/);
    words.pop(); // remove partial token

    const newBefore = (words.length ? words.join(' ') + ' ' : '') + item.token + ' ';
    input.value = newBefore + textAfter;
    input.selectionStart = input.selectionEnd = newBefore.length;
    input.focus();

    if (menu) menu.classList.remove('active');
}

// ---- 4. DYNAMIC CONTEXT-AWARE SMART FOLLOW-UPS ----
function attachSmartFollowUpsToElement(simbaBlock) {
    if (!simbaBlock || simbaBlock.querySelector('.smart-followup-container')) return;

    const text = (simbaBlock.innerText || '').toLowerCase();
    const chips = [];

    if (text.includes('```') || text.includes('function') || text.includes('def ') || text.includes('const ') || text.includes('class ')) {
        chips.push({ label: 'Fix bugs & optimize', icon: 'fa-solid fa-wrench', prompt: 'Please optimize this code and check for potential edge cases or bugs.' });
        chips.push({ label: 'Write unit tests', icon: 'fa-solid fa-vial', prompt: 'Write comprehensive unit tests for this code implementation.' });
        chips.push({ label: 'Explain step-by-step', icon: 'fa-solid fa-lightbulb', prompt: 'Explain the internal logic and algorithm of this code step-by-step.' });
    } else if (text.includes('desktop agent') || text.includes('automation') || text.includes('executed')) {
        chips.push({ label: 'Run next step', icon: 'fa-solid fa-forward', prompt: 'Proceed with the next operational step.' });
        chips.push({ label: 'Inspect details', icon: 'fa-solid fa-magnifying-glass', prompt: 'Show detailed technical execution logs and verification state.' });
    } else {
        chips.push({ label: 'Give real example', icon: 'fa-solid fa-bullseye', prompt: 'Can you provide a practical real-world example of this?' });
        chips.push({ label: 'Explain simpler', icon: 'fa-solid fa-feather', prompt: 'Can you explain this in simpler terms with key takeaways?' });
        chips.push({ label: 'Deep research', icon: 'fa-solid fa-brain', prompt: 'Perform a deeper technical analysis with additional source perspectives.' });
    }

    const followupDiv = document.createElement('div');
    followupDiv.className = 'smart-followup-container';
    followupDiv.innerHTML = chips.map(c => `
                    <button type="button" class="followup-chip" onclick="fillAndSubmitPrompt('${escapeHtml(c.prompt)}')">
                        <i class="${c.icon}"></i> ${escapeHtml(c.label)}
                    </button>
                `).join('');

    simbaBlock.appendChild(followupDiv);
}

function fillAndSubmitPrompt(prompt) {
    const input = document.getElementById('user-input');
    if (input) {
        input.value = prompt;
        input.focus();
        sendQuery();
    }
}

// ---- 5. UPGRADED COPY / BOOKMARK TOAST FEEDBACK ----
const originalCopyToClipboard = window.copyToClipboard;
window.copyToClipboard = function (text, btn) {
    if (originalCopyToClipboard) {
        originalCopyToClipboard(text, btn);
    } else {
        navigator.clipboard.writeText(text);
    }
    showSimbaToast('Copied to clipboard', 'success', 2200);
};

// ---- 6. SIMBA IDENTITY STATE PULSE CONTROLLER ----
function setSimbaLogoState(state) {
    const icons = [document.getElementById('qcCoreIcon'), document.querySelector('.brand .text-wrapper div')];
    icons.forEach(icon => {
        if (!icon) return;
        icon.classList.remove('logo-processing', 'logo-success', 'logo-error');
        if (state === 'processing') icon.classList.add('logo-processing');
        else if (state === 'success') {
            icon.classList.add('logo-success');
            setTimeout(() => icon.classList.remove('logo-success'), 1200);
        } else if (state === 'error') {
            icon.classList.add('logo-error');
            setTimeout(() => icon.classList.remove('logo-error'), 1200);
        }
    });
}

// ---- 7. MOBILE GESTURES & TOUCH ----
(function initMobileGestures() {
    let touchStartX = 0;
    let touchStartY = 0;

    document.addEventListener('touchstart', (e) => {
        if (!e.changedTouches || !e.changedTouches.length) return;
        touchStartX = e.changedTouches[0].screenX;
        touchStartY = e.changedTouches[0].screenY;
    }, { passive: true });

    document.addEventListener('touchend', (e) => {
        if (!e.changedTouches || !e.changedTouches.length) return;
        const touchEndX = e.changedTouches[0].screenX;
        const touchEndY = e.changedTouches[0].screenY;
        const deltaX = touchEndX - touchStartX;
        const deltaY = touchEndY - touchStartY;

        // Swipe left to close sidebar drawer on mobile
        if (deltaX < -70 && Math.abs(deltaY) < 50) {
            const sidebar = document.getElementById('sidebar');
            const overlay = document.getElementById('mobile-overlay');
            if (sidebar && sidebar.classList.contains('mobile-open')) {
                sidebar.classList.remove('mobile-open');
                if (overlay) overlay.classList.remove('active');
            }
        }

        // Swipe down on command palette to dismiss bottom sheet
        if (deltaY > 80 && Math.abs(deltaX) < 60) {
            const palette = document.getElementById('commandPalette');
            if (palette && palette.classList.contains('active')) {
                closeCommandPalette();
            }
        }
    }, { passive: true });
})();

function onAgentContextChange(sessionId) {
    if (sessionId) {
        sessionStorage.setItem('attached_agent_context_id', sessionId);
        showSimbaToast('Conversation context attached to Agent Mode', 'info', 2500);
    } else {
        sessionStorage.removeItem('attached_agent_context_id');
        showSimbaToast('Detached conversation context', 'info', 1800);
    }
}

let _isCreatingNewChat = false;
function startNewConversation(event) {
    if (event) event.preventDefault();
    if (_isCreatingNewChat) return;
    _isCreatingNewChat = true;

    const currentMode = new URLSearchParams(window.location.search).get('type') || '';
    const targetUrl = currentMode ? `/?type=${encodeURIComponent(currentMode)}` : '/';

    const currentSessionId = new URLSearchParams(window.location.search).get('session');
    if (!currentSessionId) {
        const input = document.getElementById('user-input');
        if (input) {
            input.value = '';
            input.focus();
        }
        _isCreatingNewChat = false;
        return;
    }

    window.location.href = targetUrl;
}

// Global Keyboard Shortcuts
document.addEventListener('keydown', (e) => {
    // Ctrl+N or Cmd+N (or Ctrl+Shift+O) for New Session
    if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key.toLowerCase() === 'n') {
        // Only intercept if not inside a standard editable input that handles native key
        if (document.activeElement?.tagName !== 'INPUT' && document.activeElement?.tagName !== 'TEXTAREA') {
            e.preventDefault();
            startNewConversation();
        }
    }
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key.toLowerCase() === 'o') {
        e.preventDefault();
        startNewConversation();
    }
});

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    if (typeof initComposerAutocomplete === 'function') initComposerAutocomplete();

    // Format all restored assistant messages from database immediately
    formatAllMessages();

    // Enforce stable composer sizing and contextual placeholder immediately on DOM ready
    if (typeof autoResizeComposerInput === 'function') autoResizeComposerInput();
    if (typeof updateComposerPlaceholder === 'function') updateComposerPlaceholder();
    if (typeof renderQuickActions === 'function') renderQuickActions();

    const savedCtx = sessionStorage.getItem('attached_agent_context_id');
    const ctxSelect = document.getElementById('agentContextSelect');
    if (savedCtx && ctxSelect) {
        ctxSelect.value = savedCtx;
    }

    if (typeof initVoiceAgent === 'function') {
        initVoiceAgent();
    }
});

// Immediate fallback formatting and sizing if document is already ready
if (document.readyState === "interactive" || document.readyState === "complete") {
    formatAllMessages();
    if (typeof autoResizeComposerInput === 'function') autoResizeComposerInput();
    if (typeof updateComposerPlaceholder === 'function') updateComposerPlaceholder();
    if (typeof renderQuickActions === 'function') renderQuickActions();
}

// =========================================================================
// SIMBA_INTEL AGENT MODE & LIFECYCLE MANAGEMENT
// =========================================================================
window.setAgentLifecycleStatus = function (statusText, descText, taskTitle) {
    const upper = (statusText || '').toUpperCase().trim() || 'IDLE';

    // Badges
    const badge = document.getElementById('agentLifecycleBadge');
    const textEl = document.getElementById('agentLifecycleText');
    const badgeHeader = document.getElementById('agentLifecycleBadgeHeader');
    const textElHeader = document.getElementById('agentLifecycleTextHeader');
    const stopBtn = document.getElementById('btnStopAgentTask');
    const descEl = document.getElementById('agentStatusDesc');

    // Determine lifecycle CSS class and icon
    let statusClass = 'status-idle';
    let statusIcon = 'fa-circle-notch';
    let defaultDesc = 'Autonomous planner & multi-step execution engine standing by.';

    if (upper.includes('PLAN')) {
        statusClass = 'status-planning';
        statusIcon = 'fa-diagram-project';
        defaultDesc = 'Synthesizing multi-step execution plan and verifying tools...';
    } else if (upper.includes('WAIT') || upper.includes('CONFIRM') || upper.includes('APPROVAL')) {
        statusClass = 'status-waiting';
        statusIcon = 'fa-hand';
        defaultDesc = 'Dangerous operation detected. Awaiting explicit confirmation.';
    } else if (upper.includes('EXEC') || upper.includes('STEP')) {
        statusClass = 'status-executing';
        statusIcon = 'fa-gear fa-spin';
        defaultDesc = 'Executing planned steps and system commands...';
    } else if (upper.includes('VERIF')) {
        statusClass = 'status-verifying';
        statusIcon = 'fa-shield';
        defaultDesc = 'Verifying step outcome, process output, and system status...';
    } else if (upper.includes('SUCCESS') || upper.includes('COMPLET')) {
        statusClass = 'status-completed';
        statusIcon = 'fa-check';
        defaultDesc = 'Task executed and verified successfully.';
    } else if (upper.includes('FAIL') || upper.includes('ERROR') || upper.includes('OFFLINE')) {
        statusClass = 'status-failed';
        statusIcon = 'fa-triangle-exclamation';
        defaultDesc = 'Task stopped or failed due to an error.';
    } else if (upper.includes('CANCEL')) {
        statusClass = 'status-cancelled';
        statusIcon = 'fa-ban';
        defaultDesc = 'Task cancelled by user.';
    }

    if (textEl) textEl.textContent = upper;
    if (badge) {
        badge.className = `agent-lifecycle-badge ${statusClass}`;
        const iconEl = badge.querySelector('i');
        if (iconEl) iconEl.className = `fa-solid ${statusIcon}`;
    }
    if (textElHeader) textElHeader.textContent = upper;
    if (badgeHeader) {
        badgeHeader.className = `agent-lifecycle-badge ${statusClass}`;
        const iconEl = badgeHeader.querySelector('i');
        if (iconEl) iconEl.className = `fa-solid ${statusIcon}`;
    }
    if (descEl) {
        descEl.textContent = descText || defaultDesc;
    }

    // Active Task vs Empty Task UI
    const emptyCard = document.getElementById('agentEmptyTaskCard');
    const activeCard = document.getElementById('agentActiveTaskCard');
    const cardTitle = document.getElementById('agentTaskCardTitle');
    const cardBadge = document.getElementById('agentTaskCardBadge');
    const cardBadgeText = document.getElementById('agentTaskCardBadgeText');
    const resultBox = document.getElementById('agentTaskResultBox');
    const resultText = document.getElementById('agentTaskResultText') || document.getElementById('agentTaskResultSummary');

    const isRunning = upper.includes('PLAN') || upper.includes('EXEC') || upper.includes('VERIF') || upper.includes('WAIT');

    if (isRunning) {
        if (emptyCard) emptyCard.style.display = 'none';
        if (activeCard) activeCard.style.display = 'block';
        if (cardTitle && taskTitle) cardTitle.textContent = taskTitle;
        if (cardBadgeText) cardBadgeText.textContent = upper;
        if (cardBadge) {
            cardBadge.className = `agent-lifecycle-badge ${statusClass}`;
            const bIcon = cardBadge.querySelector('i');
            if (bIcon) bIcon.className = `fa-solid ${statusIcon}`;
        }
        if (resultBox) resultBox.style.display = 'none';
    } else if (upper.includes('COMPLET')) {
        if (cardBadgeText) cardBadgeText.textContent = 'COMPLETED';
        if (cardBadge) cardBadge.className = 'agent-lifecycle-badge status-completed';
        if (resultBox && resultText) {
            resultBox.style.display = 'block';
            resultText.textContent = descText || 'All task steps completed and verified successfully.';
        }
    }

    if (stopBtn) {
        stopBtn.style.display = isRunning ? 'inline-flex' : 'none';
    }
};

window.stopCurrentAgentTask = async function () {
    const btn = document.getElementById('btnStopAgentTask');
    try {
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Stopping...';
        }
        if (typeof currentAbortController !== 'undefined' && currentAbortController) {
            currentAbortController.abort();
        }
        await fetch('/api/agent/task/cancel/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken(),
            },
            body: JSON.stringify({})
        });
        setAgentLifecycleStatus('CANCELLED', 'Task execution stopped safely.');
        showSimbaToast('Task execution stopped safely.', 'info', 3000);
    } catch (e) {
        console.error("Cancel task error:", e);
        setAgentLifecycleStatus('CANCELLED', 'Task stopped.');
    } finally {
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<i class="fa-solid fa-hand"></i> Stop Task';
            btn.style.display = 'none';
        }
    }
};

window.executeQuickTask = function (promptText) {
    if (!promptText) return;
    const input = document.getElementById('user-input');
    if (input) {
        input.value = promptText;
        if (typeof autoResizeComposerInput === 'function') autoResizeComposerInput(input);
        input.focus();
    }
    setAgentLifecycleStatus('PLANNING', 'Analyzing request & creating execution plan...', promptText);
    sendQuery(promptText);
};

let isCurrentTaskPaused = false;
window.pauseCurrentAgentTask = function () {
    const pauseBtn = document.getElementById('btnPauseAgentTask');
    isCurrentTaskPaused = !isCurrentTaskPaused;
    if (isCurrentTaskPaused) {
        if (pauseBtn) {
            pauseBtn.innerHTML = '<i class="fa-solid fa-play"></i> <span>Resume</span>';
            pauseBtn.classList.add('resuming');
        }
        setAgentLifecycleStatus('WAITING', 'Task execution paused by user.');
        showSimbaToast('Task execution paused.', 'info', 2500);
    } else {
        if (pauseBtn) {
            pauseBtn.innerHTML = '<i class="fa-solid fa-pause"></i> <span>Pause</span>';
            pauseBtn.classList.remove('resuming');
        }
        setAgentLifecycleStatus('EXECUTING', 'Task execution resumed.');
        showSimbaToast('Task execution resumed.', 'info', 2500);
    }
};

window.reRunCompletedAgentTask = function () {
    const cardTitle = document.getElementById('agentTaskCardTitle');
    const title = cardTitle ? cardTitle.textContent.trim() : '';
    if (title && title !== 'Ready for Agent Task' && title !== 'Processing Request...') {
        executeQuickTask(title);
    } else {
        const input = document.getElementById('user-input');
        if (input && input.value.trim()) {
            sendQuery(input.value.trim());
        } else {
            showSimbaToast('No previous task to re-run.', 'warning', 2500);
        }
    }
};

window.executePlanApproved = function () {
    const planBox = document.getElementById('agentPlanPreviewBox');
    if (planBox) planBox.style.display = 'none';
    setAgentLifecycleStatus('EXECUTING', 'Plan approved. Executing tool actions...');
    showSimbaToast('Plan approved. Running task...', 'success', 2500);
};

window.focusAgentComposer = function () {
    const input = document.getElementById('user-input');
    if (input) {
        input.focus();
    }
};

window.confirmAgentAction = async function (btn, actionJson) {
    if (!btn) return;
    try {
        btn.disabled = true;
        btn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Executing...';

        let data = {};
        if (typeof actionJson === 'string') {
            try {
                data = JSON.parse(actionJson);
            } catch (e) {
                try {
                    const decoded = actionJson.replace(/&quot;/g, '"').replace(/&#39;/g, "'");
                    data = JSON.parse(decoded);
                } catch (_) {
                    console.warn("Could not parse actionJson directly:", actionJson);
                }
            }
        } else if (typeof actionJson === 'object' && actionJson !== null) {
            data = actionJson;
        }

        const card = btn.closest('.simba-action-card') || btn.closest('.agent-confirm-card') || btn.parentElement;

        if (data.task_id) {
            // Task Manager approval
            const res = await fetch('/api/agent/task/confirm/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCsrfToken(),
                },
                body: JSON.stringify({ task_id: data.task_id, action: 'allow' })
            });
            const resData = await res.json();
            if (res.ok && resData.status === 'ok') {
                if (card) {
                    card.innerHTML = `
                                    <div style="padding:10px 14px; background:rgba(14,219,42,0.1); border:1px solid rgba(14,219,42,0.3); border-radius:6px; color:#0edb2a; font-size:12.5px; font-weight:600; display:flex; align-items:center; gap:8px;">
                                        <i class="fa-solid fa-circle-check"></i> Action approved and scheduled.
                                    </div>
                                `;
                }
                setAgentLifecycleStatus('EXECUTING', 'Action approved. Running execution...');
                showSimbaToast('Action approved.', 'success', 2500);
            } else {
                throw new Error(resData.error || "Approval failed.");
            }
        } else {
            // Direct Tool execution via /agent/confirm/
            const toolName = data.tool || data.tool_name || '';
            const argsObj = data.args || {};
            const formData = new FormData();
            formData.append('tool_name', toolName);
            formData.append('args', JSON.stringify(argsObj));
            formData.append('csrfmiddlewaretoken', getCsrfToken());

            const res = await fetch('/agent/confirm/', {
                method: 'POST',
                body: formData
            });
            const resData = await res.json();
            if (res.ok && (resData.success || resData.status === 'ok' || !resData.error)) {
                const outputText = resData.output || resData.result || resData.message || 'Action completed successfully.';
                if (card) {
                    card.innerHTML = `
                                    <div style="padding:10px 14px; background:rgba(14,219,42,0.1); border:1px solid rgba(14,219,42,0.3); border-radius:6px; color:#0edb2a; font-size:12.5px; font-weight:600; display:flex; align-items:center; gap:8px;">
                                        <i class="fa-solid fa-circle-check"></i> <span>${escapeHtml(String(outputText))}</span>
                                    </div>
                                `;
                }
                setAgentLifecycleStatus('COMPLETED', 'Action completed: ' + outputText);
                showSimbaToast('Action executed successfully.', 'success', 2500);
                if (typeof maybeVoiceSpeakResponse === 'function') {
                    maybeVoiceSpeakResponse('Action executed: ' + outputText);
                }
            } else {
                const errMsg = resData.error || resData.message || 'Execution failed.';
                if (card) {
                    card.innerHTML = `
                                    <div style="padding:10px 14px; background:rgba(239,68,68,0.1); border:1px solid rgba(239,68,68,0.3); border-radius:6px; color:#f87171; font-size:12.5px; font-weight:600; display:flex; align-items:center; gap:8px;">
                                        <i class="fa-solid fa-triangle-exclamation"></i> <span>Failed: ${escapeHtml(String(errMsg))}</span>
                                    </div>
                                `;
                }
                setAgentLifecycleStatus('FAILED', 'Action failed: ' + errMsg);
                showSimbaToast('Action failed: ' + errMsg, 'error', 3500);
            }
        }
    } catch (err) {
        console.error("confirmAgentAction error:", err);
        showSimbaToast('Confirmation error: ' + err.message, 'error', 3500);
        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<i class="fa-solid fa-check"></i> Allow Once';
        }
    }
};

window.cancelAgentAction = function (btn) {
    if (!btn) return;
    const card = btn.closest('.simba-action-card') || btn.closest('.agent-confirm-card') || btn.parentElement;
    if (card) {
        card.innerHTML = `
                        <div style="padding:10px 14px; background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.1); border-radius:6px; color:rgba(255,255,255,0.6); font-size:12.5px; display:flex; align-items:center; gap:8px;">
                            <i class="fa-solid fa-ban"></i> <span>Action cancelled by user.</span>
                        </div>
                    `;
    }
    setAgentLifecycleStatus('CANCELLED', 'Action execution cancelled by user.');
    showSimbaToast('Action cancelled.', 'info', 2000);
};

let taskHistoryCurrentStatus = 'all';
let taskHistorySearchDebounceTimer = null;

window.toggleAgentTaskHistory = function (forceOpen) {
    const drawer = document.getElementById('agentTaskHistoryDrawer');
    const overlay = document.getElementById('agentHistoryOverlay');
    if (!drawer) return;
    const isOpen = drawer.classList.contains('open');
    const shouldOpen = (typeof forceOpen === 'boolean') ? forceOpen : !isOpen;

    if (shouldOpen) {
        drawer.classList.add('open');
        if (overlay) overlay.style.display = 'block';
        loadAgentTaskHistory();
    } else {
        drawer.classList.remove('open');
        if (overlay) overlay.style.display = 'none';
    }
};

window.onTaskHistorySearchInput = function () {
    clearTimeout(taskHistorySearchDebounceTimer);
    taskHistorySearchDebounceTimer = setTimeout(() => {
        loadAgentTaskHistory();
    }, 280);
};

window.filterTaskHistoryStatus = function (status) {
    taskHistoryCurrentStatus = status || 'all';
    const filterBtns = document.querySelectorAll('.drawer-filter-btn');
    filterBtns.forEach(btn => {
        if (btn.getAttribute('data-status') === taskHistoryCurrentStatus) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });
    loadAgentTaskHistory();
};

window.loadAgentTaskHistory = async function () {
    const listEl = document.getElementById('agentTaskHistoryList');
    if (!listEl) return;

    // 1. LOADING STATE
    listEl.innerHTML = `
                    <div class="task-hist-loading">
                        <i class="fa-solid fa-circle-notch fa-spin fa-2x" style="color:var(--accent);"></i>
                        <span style="margin-top:10px; display:block; font-size:12px;">Loading agent tasks...</span>
                    </div>
                `;

    try {
        const searchInput = document.getElementById('taskHistorySearchInput');
        const query = searchInput ? searchInput.value.trim() : '';

        let url = '/api/agent/task/history/?';
        if (taskHistoryCurrentStatus && taskHistoryCurrentStatus !== 'all') {
            url += 'status=' + encodeURIComponent(taskHistoryCurrentStatus) + '&';
        }
        if (query) {
            url += 'search=' + encodeURIComponent(query);
        }

        const res = await fetch(url);
        if (!res.ok) throw new Error("HTTP error " + res.status);
        const data = await res.json();
        const tasks = data.tasks || [];

        // 2. EMPTY STATE
        if (tasks.length === 0) {
            listEl.innerHTML = `
                            <div class="task-hist-empty">
                                <i class="fa-solid fa-clipboard-list fa-2x" style="opacity:0.35; margin-bottom:8px;"></i>
                                <h4 style="font-size:13px; margin:0 0 4px 0;">No agent tasks found</h4>
                                <p style="font-size:11.5px; color:rgba(255,255,255,0.5); margin:0;">${query ? 'No tasks match search query.' : 'Start a task in Agent Mode to see execution history.'}</p>
                            </div>
                        `;
            return;
        }

        // 3. LOADED STATE
        let html = '';
        tasks.forEach(t => {
            const rawStatus = (t.status || 'COMPLETED').toUpperCase();
            let statusClass = 'status-completed';
            let statusIcon = 'fa-check';
            if (rawStatus.includes('PLAN')) {
                statusClass = 'status-planning'; statusIcon = 'fa-diagram-project';
            } else if (rawStatus.includes('EXEC')) {
                statusClass = 'status-executing'; statusIcon = 'fa-gear fa-spin';
            } else if (rawStatus.includes('WAIT')) {
                statusClass = 'status-waiting'; statusIcon = 'fa-clock';
            } else if (rawStatus.includes('VERIF')) {
                statusClass = 'status-verifying'; statusIcon = 'fa-shield';
            } else if (rawStatus.includes('FAIL') || rawStatus.includes('ERROR')) {
                statusClass = 'status-failed'; statusIcon = 'fa-triangle-exclamation';
            } else if (rawStatus.includes('CANCEL')) {
                statusClass = 'status-cancelled'; statusIcon = 'fa-ban';
            }

            const timeStr = t.start_time ? new Date(t.start_time * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
            const durStr = t.duration ? `${t.duration}s` : '';
            const stepsCount = (t.steps || []).length;
            const finalClean = t.final_result ? escapeHtml(t.final_result.replace(/<[^>]*>/g, '').trim()) : '';
            const taskTitleEscaped = escapeHtml(t.title || 'Untitled Task');

            html += `
                            <div class="task-history-card">
                                <div class="task-hist-top">
                                    <span class="task-hist-title" title="${taskTitleEscaped}">${taskTitleEscaped}</span>
                                    <span class="agent-lifecycle-badge ${statusClass}">
                                        <i class="fa-solid ${statusIcon}"></i> ${escapeHtml(rawStatus)}
                                    </span>
                                </div>
                                <div class="task-hist-meta">
                                    ${timeStr ? `<span><i class="fa-regular fa-clock"></i> ${timeStr}</span>` : ''}
                                    ${durStr ? `<span>&bull; ${durStr}</span>` : ''}
                                    ${stepsCount ? `<span>&bull; ${stepsCount} steps</span>` : ''}
                                </div>
                                ${finalClean ? `<div class="task-hist-snippet">${finalClean}</div>` : ''}
                                <div style="margin-top:8px; display:flex; justify-content:flex-end; gap:6px;">
                                    <button type="button" class="btn-use-discovered-tool" style="padding:4px 8px; font-size:10.5px;" onclick="toggleAgentTaskHistory(false); executeQuickTask('${taskTitleEscaped.replace(/'/g, "\\'")}')">
                                        <i class="fa-solid fa-rotate-right"></i> Re-run
                                    </button>
                                </div>
                            </div>
                        `;
        });
        listEl.innerHTML = html;
    } catch (e) {
        console.error("loadAgentTaskHistory error:", e);
        // 4. ERROR STATE
        listEl.innerHTML = `
                        <div class="task-hist-error">
                            <i class="fa-solid fa-triangle-exclamation fa-2x" style="color:#f87171; margin-bottom:8px;"></i>
                            <h4 style="font-size:13px; margin:0 0 4px 0;">Couldn't load agent tasks</h4>
                            <p style="font-size:11.5px; color:rgba(255,255,255,0.5); margin:0 0 10px 0;">Failed to retrieve task records from server.</p>
                            <button type="button" class="btn-use-discovered-tool" onclick="loadAgentTaskHistory()">
                                <i class="fa-solid fa-rotate-right"></i> Retry
                            </button>
                        </div>
                    `;
    }
};

let allDiscoveredTools = [];
let activeDiscoveryCategory = 'all';

window.openActionDiscoveryModal = async function () {
    const modal = document.getElementById('actionDiscoveryModal');
    if (!modal) return;
    modal.style.display = 'grid';
    if (allDiscoveredTools.length === 0) {
        await loadDiscoveredTools();
    } else {
        renderDiscoveredTools();
    }
    const searchInput = document.getElementById('discoverySearchInput');
    if (searchInput) {
        searchInput.value = '';
        setTimeout(() => searchInput.focus(), 50);
    }
};

window.closeActionDiscoveryModal = function () {
    const modal = document.getElementById('actionDiscoveryModal');
    if (modal) modal.style.display = 'none';
};

window.loadDiscoveredTools = async function () {
    const grid = document.getElementById('discoveryToolsGrid');
    const chip = document.getElementById('discoveryTargetChip');
    if (grid) {
        grid.innerHTML = `
                        <div class="discovery-loading">
                            <i class="fa-solid fa-circle-notch fa-spin fa-2x" style="color:var(--accent);"></i>
                            <div style="margin-top:12px; font-size:13px;">Loading registered agent tools & capabilities...</div>
                        </div>
                    `;
    }
    try {
        const res = await fetch('/api/agent/tools/');
        if (!res.ok) throw new Error("HTTP error " + res.status);
        const data = await res.json();
        allDiscoveredTools = data.tools || [];
        const desktopOnline = Boolean(data.desktop_online);
        if (chip) {
            chip.innerHTML = desktopOnline
                ? '<span class="pc-dot" style="background:#0edb2a; width:6px; height:6px; border-radius:50%; display:inline-block;"></span> Desktop Online'
                : '<span class="pc-dot" style="background:#f87171; width:6px; height:6px; border-radius:50%; display:inline-block;"></span> Desktop Offline';
        }
        renderDiscoveredTools();
    } catch (e) {
        console.error("loadDiscoveredTools error:", e);
        if (grid) {
            grid.innerHTML = `
                            <div class="discovery-loading" style="color:#f87171;">
                                <i class="fa-solid fa-triangle-exclamation fa-2x"></i>
                                <div style="margin-top:12px; font-size:13px;">Failed to load registered tools.</div>
                                <button type="button" class="btn-use-discovered-tool" style="margin-top:12px;" onclick="loadDiscoveredTools()">
                                    <i class="fa-solid fa-rotate-right"></i> Retry
                                </button>
                            </div>
                        `;
        }
    }
};

window.filterDiscoveryCategory = function (cat) {
    activeDiscoveryCategory = cat || 'all';
    const tabs = document.querySelectorAll('.discovery-tab');
    tabs.forEach(t => {
        if (t.getAttribute('data-cat') === cat) t.classList.add('active');
        else t.classList.remove('active');
    });
    renderDiscoveredTools();
};

window.filterDiscoveredTools = function () {
    renderDiscoveredTools();
};

window.renderDiscoveredTools = function () {
    const grid = document.getElementById('discoveryToolsGrid');
    if (!grid) return;

    const searchInput = document.getElementById('discoverySearchInput');
    const query = (searchInput ? searchInput.value.trim().toLowerCase() : '');

    let filtered = allDiscoveredTools.filter(t => {
        if (activeDiscoveryCategory !== 'all' && t.category !== activeDiscoveryCategory) {
            return false;
        }
        if (query) {
            const matchName = (t.display_name || t.id || '').toLowerCase().includes(query);
            const matchDesc = (t.description || '').toLowerCase().includes(query);
            const matchCat = (t.category || '').toLowerCase().includes(query);
            const matchPrompt = (t.example_prompt || '').toLowerCase().includes(query);
            return matchName || matchDesc || matchCat || matchPrompt;
        }
        return true;
    });

    if (filtered.length === 0) {
        grid.innerHTML = `
                        <div class="discovery-loading">
                            <i class="fa-solid fa-folder-open fa-2x" style="opacity:0.4;"></i>
                            <div style="margin-top:10px; font-size:13px;">No actions matching "${escapeHtml(query)}"</div>
                        </div>
                    `;
        return;
    }

    let html = '';
    filtered.forEach(tool => {
        const isDesktop = tool.execution_target === 'desktop';
        const isDangerous = tool.risk_level === 'dangerous' || tool.risk_level === 'sensitive';
        const targetBadge = isDesktop ? '<span class="discovery-badge desktop">Desktop</span>' : '<span class="discovery-badge cloud">Cloud</span>';
        const offlineBadge = (isDesktop && !tool.available) ? '<span class="discovery-badge offline">Offline</span>' : '';
        const riskBadge = isDangerous ? '<span class="discovery-badge dangerous">Sensitive</span>' : '';
        const promptEscaped = escapeHtml(tool.example_prompt || tool.display_name || tool.id);

        html += `
                        <div class="discovery-card">
                            <div class="discovery-card-top">
                                <div class="discovery-card-title">
                                    <i class="${tool.icon || 'fa-solid fa-wrench'}" style="color:var(--accent);"></i>
                                    <span>${escapeHtml(tool.display_name)}</span>
                                </div>
                                <div class="discovery-badges-wrap">
                                    ${targetBadge}
                                    ${offlineBadge}
                                    ${riskBadge}
                                </div>
                            </div>
                            <div class="discovery-card-desc">${escapeHtml(tool.description || '')}</div>
                            <button type="button" class="btn-use-discovered-tool" onclick="useDiscoveredTool('${promptEscaped.replace(/'/g, "\\'")}')">
                                <i class="fa-solid fa-play"></i> Use Task
                            </button>
                        </div>
                    `;
    });
    grid.innerHTML = html;
};

window.useDiscoveredTool = function (promptText) {
    closeActionDiscoveryModal();
    const input = document.getElementById('user-input');
    if (input && promptText) {
        input.value = promptText;
        if (typeof autoResizeComposerInput === 'function') autoResizeComposerInput(input);
        input.focus();
        showSimbaToast('Task loaded into prompt', 'info', 2000);
    }
};

window.toggleScreenAwareness = async function () {
    try {
        const res = await fetch('/api/agent/screen-awareness/toggle/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCsrfToken(),
            },
            body: JSON.stringify({})
        });
        if (res.ok) {
            const data = await res.json();
            const isEnabled = Boolean(data.screen_awareness_enabled);
            const chip = document.getElementById('screenStatusChip');
            const label = document.getElementById('screenStatusLabel');
            const desc = document.getElementById('screenStatusDesc');
            if (chip) {
                chip.className = `screen-status-chip ${isEnabled ? 'enabled' : 'disabled'}`;
            }
            if (label) {
                label.textContent = isEnabled ? 'Screen Access: ON' : 'Screen Access: OFF';
            }
            if (desc) {
                desc.textContent = isEnabled ? 'Real-time desktop visual analysis active.' : 'Desktop screen awareness disabled.';
            }
            showSimbaToast(isEnabled ? 'Screen awareness enabled' : 'Screen awareness disabled', 'info', 2000);
        }
    } catch (e) {
        console.error("Toggle screen awareness error:", e);
    }
};

window.clearVoiceWorkspace = function () {
    const transcriptBox = document.getElementById('voiceTranscriptText');
    const modeLabel = document.getElementById('voiceTranscriptMode');
    const respCard = document.getElementById('voiceResponseCard');
    const respText = document.getElementById('voiceResponseText');
    simbaStopSpeaking();
    if (transcriptBox) transcriptBox.textContent = '"Speak commands like \'Open YouTube\', \'What is Python?\', or \'Calculate 25 * 8\'..."';
    if (modeLabel) modeLabel.textContent = 'STANDBY';
    if (respCard) respCard.style.display = 'none';
    if (respText) respText.textContent = '';
    setVoiceState('READY');
};

// Global Escape key handler to dismiss drawer/modals
document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
        const drawer = document.getElementById('agentTaskHistoryDrawer');
        if (drawer && drawer.classList.contains('open')) {
            toggleAgentTaskHistory(false);
        }
        const discoveryModal = document.getElementById('actionDiscoveryModal');
        if (discoveryModal && discoveryModal.style.display !== 'none') {
            closeActionDiscoveryModal();
        }
        const pcModal = document.getElementById('pcAgentInstructionsModal');
        if (pcModal && pcModal.style.display !== 'none') {
            pcModal.style.display = 'none';
        }
    }
});

// Cleanup handlers on navigation/unload to prevent zombie listeners
window.addEventListener('beforeunload', function () {
    simbaStopSpeaking();
    if (voiceRecognition) {
        try { voiceRecognition.stop(); } catch (e) { }
    }
});

window.togglePcAgentModal = async function () {
    const modal = document.getElementById('pcAgentInstructionsModal');
    if (!modal) return;
    const isHidden = modal.style.display === 'none';
    if (isHidden) {
        modal.style.display = 'grid';
        try {
            const res = await fetch('/api/agent/status/');
            if (res.ok) {
                const data = await res.json();
                const dev = data.device || {};
                const stateEl = document.getElementById('modalPcStatusText');
                const devEl = document.getElementById('modalPcDeviceText');
                const chip = document.getElementById('pcStatusChip');
                const chipLabel = document.getElementById('pcStatusChipLabel');
                const chipDesc = document.getElementById('pcStatusCardDesc');
                const chipHeader = document.getElementById('pcStatusChipHeader');
                if (data.connected) {
                    if (stateEl) stateEl.innerHTML = '<span style="color:#0edb2a;"><i class="fa-solid fa-circle-check"></i> Connected & Online</span>';
                    if (devEl) devEl.textContent = `${dev.hostname || 'Windows PC'} (${dev.platform || 'Windows'})`;
                    if (chip) {
                        chip.className = 'pc-status-chip connected';
                        if (chipLabel) chipLabel.innerHTML = '<i class="fa-brands fa-windows"></i> PC CONNECTED';
                    }
                    if (chipDesc) {
                        chipDesc.textContent = `Active on ${dev.hostname || 'Windows PC'} (${dev.platform || 'Windows'}). Local actions available.`;
                    }
                    if (chipHeader) {
                        chipHeader.className = 'pc-status-chip connected';
                        chipHeader.innerHTML = '<span class="pc-dot"></span><span>PC CONNECTED</span>';
                    }
                } else {
                    if (stateEl) stateEl.innerHTML = '<span style="color:#f87171;"><i class="fa-solid fa-circle-xmark"></i> Offline</span>';
                    if (devEl) devEl.textContent = 'No local Desktop Agent active';
                    if (chip) {
                        chip.className = 'pc-status-chip offline';
                        if (chipLabel) chipLabel.innerHTML = '<i class="fa-solid fa-desktop"></i> OFFLINE';
                    }
                    if (chipDesc) {
                        chipDesc.textContent = 'Desktop Agent required for local computer actions. Cloud tasks remain active.';
                    }
                    if (chipHeader) {
                        chipHeader.className = 'pc-status-chip offline';
                        chipHeader.innerHTML = '<span class="pc-dot"></span><span>OFFLINE</span>';
                    }
                }
            }
        } catch (e) { }
    } else {
        modal.style.display = 'none';
    }
};

window.copyPcAgentCommand = function () {
    navigator.clipboard.writeText("python simba_agent.py").then(() => {
        showSimbaToast('Command copied: python simba_agent.py', 'success', 2500);
    });
};

// =========================================================================
// VOICE AGENT TTS & STT ORCHESTRATION
// =========================================================================
let voiceRecognition = null;
let isVoiceListening = false;
let isHandsFreeEnabled = false;
let voiceCurrentUtterance = null;

window.initVoiceAgent = function () {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) return;
    try {
        voiceRecognition = new SpeechRecognition();
        voiceRecognition.continuous = false;
        voiceRecognition.interimResults = true;
        voiceRecognition.lang = "en-US";

        voiceRecognition.onstart = function () {
            isVoiceListening = true;
            setVoiceState('LISTENING');
        };

        voiceRecognition.onresult = function (event) {
            let interim = '';
            let finalTranscript = '';
            for (let i = event.resultIndex; i < event.results.length; i++) {
                const transcript = event.results[i][0].transcript;
                if (event.results[i].isFinal) {
                    finalTranscript += transcript;
                } else {
                    interim += transcript;
                }
            }
            const liveText = (finalTranscript || interim).trim();
            const transcriptBox = document.getElementById('voiceTranscriptText');
            if (transcriptBox && liveText) {
                transcriptBox.textContent = `"${liveText}"`;
            }
            if (finalTranscript) {
                isVoiceListening = false;
                setVoiceState('PROCESSING');
                handleVoiceCommand(finalTranscript.trim());
            }
        };

        voiceRecognition.onerror = function (event) {
            isVoiceListening = false;
            let msg = 'Microphone access blocked or unavailable.';
            if (event.error === 'not-allowed' || event.error === 'service-not-allowed') {
                msg = 'Microphone access was denied. Please allow microphone permissions in your browser.';
            } else if (event.error === 'no-speech') {
                setVoiceState('READY');
                return;
            }
            setVoiceState('ERROR', 'ERROR', msg);
        };

        voiceRecognition.onend = function () {
            isVoiceListening = false;
            const badge = document.getElementById('voiceLifecycleBadge');
            if (badge && badge.classList.contains('status-listening')) {
                setVoiceState('READY');
            }
        };
    } catch (e) {
        console.warn("SpeechRecognition init warning:", e);
    }
};

function setVoiceState(state, label, errorMsg) {
    const badge = document.getElementById('voiceLifecycleBadge');
    const textEl = document.getElementById('voiceLifecycleText');
    const heroStatus = document.getElementById('voiceHeroStatus');
    const heroSubtext = document.getElementById('voiceHeroSubtext');
    const visualizer = document.getElementById('voiceVisualizerContainer');
    const micBtn = document.getElementById('voiceMainMicBtn');
    const micIcon = document.getElementById('voiceMicIcon');
    const speakingBars = document.getElementById('voiceSpeakingBars');
    const modeLabel = document.getElementById('voiceTranscriptMode');
    const btnStopListening = document.getElementById('btnStopListening');
    const btnStopSpeaking = document.getElementById('btnStopSpeaking');

    const upper = (state || 'READY').toUpperCase();
    const displayLabel = label || upper;
    if (textEl) textEl.textContent = displayLabel;
    if (modeLabel) modeLabel.textContent = upper === 'READY' ? 'STANDBY' : upper;

    if (badge) {
        badge.className = `voice-lifecycle-badge status-${upper.toLowerCase()}`;
    }

    if (visualizer) {
        visualizer.className = 'voice-visualizer-container';
        if (upper === 'LISTENING') visualizer.classList.add('active');
        else if (upper === 'SPEAKING') visualizer.classList.add('speaking');
        else if (upper === 'PROCESSING') visualizer.classList.add('processing');
        else if (upper === 'ERROR') visualizer.classList.add('error');
    }

    if (micBtn) {
        micBtn.className = 'voice-main-mic-btn';
        if (upper === 'LISTENING') micBtn.classList.add('active');
        else if (upper === 'SPEAKING') micBtn.classList.add('speaking');
        else if (upper === 'PROCESSING') micBtn.classList.add('processing');
        else if (upper === 'ERROR') micBtn.classList.add('error');
    }

    if (micIcon && speakingBars) {
        if (upper === 'SPEAKING') {
            micIcon.style.display = 'none';
            speakingBars.style.display = 'inline-flex';
        } else {
            micIcon.style.display = 'inline-block';
            speakingBars.style.display = 'none';
        }
    }

    if (heroStatus) {
        if (upper === 'LISTENING') heroStatus.textContent = 'LISTENING TO YOU...';
        else if (upper === 'SPEAKING') heroStatus.textContent = 'SIMBA IS SPEAKING...';
        else if (upper === 'PROCESSING') heroStatus.textContent = 'UNDERSTANDING REQUEST...';
        else if (upper === 'ERROR') heroStatus.textContent = 'MICROPHONE / SPEECH ERROR';
        else heroStatus.textContent = 'READY TO LISTEN';
    }

    if (heroSubtext) {
        if (upper === 'LISTENING') heroSubtext.textContent = 'Speak clearly into your microphone...';
        else if (upper === 'SPEAKING') heroSubtext.textContent = 'Click "Stop Audio" or say "Stop" to interrupt at any time.';
        else if (upper === 'PROCESSING') heroSubtext.textContent = 'Converting speech to text & orchestrating model...';
        else if (upper === 'ERROR') heroSubtext.textContent = errorMsg || 'Microphone access blocked or unavailable. Please check browser permissions.';
        else heroSubtext.textContent = 'Voice-first interaction: Listen \u2192 Transcribe \u2192 Understand \u2192 Answer or Execute \u2192 Speak';
    }

    if (btnStopListening) {
        btnStopListening.style.display = (upper === 'LISTENING') ? 'inline-flex' : 'none';
    }
    if (btnStopSpeaking) {
        btnStopSpeaking.style.display = (upper === 'SPEAKING') ? 'inline-flex' : 'none';
    }

    // Update Voice Workflow Pipeline Card (Part 22)
    const pipeSteps = ['pipeStepListen', 'pipeStepTranscribe', 'pipeStepUnderstand', 'pipeStepAct', 'pipeStepSpeak'];
    let activeStep = 'pipeStepListen';
    if (upper === 'LISTENING') activeStep = 'pipeStepListen';
    else if (upper === 'TRANSCRIBING') activeStep = 'pipeStepTranscribe';
    else if (upper === 'PROCESSING') activeStep = 'pipeStepUnderstand';
    else if (upper === 'ACTING' || upper === 'EXECUTING') activeStep = 'pipeStepAct';
    else if (upper === 'SPEAKING') activeStep = 'pipeStepSpeak';
    else if (upper === 'READY') activeStep = 'pipeStepListen';

    pipeSteps.forEach(sId => {
        const el = document.getElementById(sId);
        if (el) {
            if (sId === activeStep) el.classList.add('active');
            else el.classList.remove('active');
        }
    });
}

window.toggleVoiceAgentListening = function () {
    if (!voiceRecognition) initVoiceAgent();
    if (!voiceRecognition) {
        showSimbaToast("Speech recognition is not supported in this browser. Please use Chrome or Edge.", "warning", 3500);
        return;
    }
    simbaStopSpeaking();
    if (isVoiceListening) {
        try { voiceRecognition.stop(); } catch (e) { }
        isVoiceListening = false;
        setVoiceState('READY');
    } else {
        try {
            voiceRecognition.start();
        } catch (e) {
            try { voiceRecognition.stop(); voiceRecognition.start(); } catch (_) { }
        }
    }
};

window.stopVoiceListening = function () {
    if (voiceRecognition && isVoiceListening) {
        try { voiceRecognition.stop(); } catch (e) { }
    }
    isVoiceListening = false;
    setVoiceState('READY');
};

window.toggleHandsFreeVoice = function (enabled) {
    isHandsFreeEnabled = Boolean(enabled);
    showSimbaToast(isHandsFreeEnabled ? 'Hands-Free mode enabled' : 'Hands-Free mode disabled', 'info', 2000);
};

function handleVoiceCommand(spokenText) {
    if (!spokenText) return;
    const lower = spokenText.toLowerCase();

    // 1. Voice stop / interrupt
    if (/^(?:stop|cancel|shut up|be quiet|mute)$/.test(lower)) {
        simbaStopSpeaking();
        stopCurrentAgentTask();
        setVoiceState('READY');
        return;
    }

    // 2. Voice confirmation for pending sensitive agent actions
    const pendingConfirmBtn = document.querySelector('.agent-confirm-actions .agent-btn-confirm');
    const pendingCancelBtn = document.querySelector('.agent-confirm-actions .agent-btn-cancel');
    if (pendingConfirmBtn && /^(?:yes|confirm|allow|proceed|approve|do it|okay|sure)/i.test(lower)) {
        pendingConfirmBtn.click();
        simbaSpeak("Action confirmed and proceeding.");
        return;
    }
    if (pendingCancelBtn && /^(?:no|cancel|abort|stop|don't|reject)/i.test(lower)) {
        pendingCancelBtn.click();
        simbaSpeak("Action cancelled.");
        return;
    }

    // 3. Intent Classifier: Action Task vs Conversational Question
    const isActionTask = /^(?:please\s+)?(?:open|launch|start|run|close|switch to|minimize|maximize|create|delete|remove|save|type|press|click|scroll|calculate|compute|solve|eval|search\s+(?:web|youtube|google|reddit|github))/i.test(spokenText);

    const voiceTaskProgress = document.getElementById('voiceTaskProgress');
    if (isActionTask) {
        const stepAct = document.getElementById('pipeStepAct');
        const stepUnderstand = document.getElementById('pipeStepUnderstand');
        if (stepAct) stepAct.classList.add('active');
        if (stepUnderstand) stepUnderstand.classList.remove('active');
        if (voiceTaskProgress) {
            voiceTaskProgress.style.display = 'block';
            voiceTaskProgress.innerHTML = `<span class="agent-lifecycle-badge status-executing"><i class="fa-solid fa-gear fa-spin"></i> EXECUTING AGENT ACTION</span>`;
        }
    } else {
        if (voiceTaskProgress) voiceTaskProgress.style.display = 'none';
    }

    // Dispatch to composer/chat pipeline
    const input = document.getElementById('user-input');
    if (input) input.value = spokenText;
    sendQuery(spokenText);
}

window.maybeVoiceSpeakResponse = function (rawText) {
    const sessionType = new URLSearchParams(window.location.search).get('type') || 'assistant';
    if (sessionType !== 'voice' && !isHandsFreeEnabled) return;
    simbaSpeak(rawText);
};

window.simbaSpeak = function (text) {
    if (!('speechSynthesis' in window)) return;
    simbaStopSpeaking();

    let clean = (text || '')
        .replace(/<div class="simba-action-card[\s\S]*?<\/div>\s*<\/div>/gi, '')
        .replace(/<[^>]+>/g, '')
        .replace(/SIMBA_STATUS:\s*[^\n\r]+/g, '')
        .replace(/```[\s\S]*?```/g, 'Code block generated.')
        .replace(/[*_#`~\[\]]/g, '')
        .trim();

    // If voice prompt needs permission confirmation
    if (text && text.includes('PERMISSION REQUIRED')) {
        clean = "Permission is required to execute this action. Please click Allow Once, or say 'Yes' to confirm or 'Cancel' to abort.";
    }

    if (!clean) return;

    const sentences = clean.match(/[^.!?]+[.!?]+/g);
    if (sentences && sentences.length > 3) {
        clean = sentences.slice(0, 3).join(' ');
    }

    const respCard = document.getElementById('voiceResponseCard');
    const respText = document.getElementById('voiceResponseText');
    const stopBtn = document.getElementById('btnStopSpeaking');
    if (respCard && respText) {
        respText.textContent = clean;
        respCard.style.display = 'block';
    }
    if (stopBtn) stopBtn.style.display = 'inline-flex';

    voiceCurrentUtterance = new SpeechSynthesisUtterance(clean);
    voiceCurrentUtterance.rate = 1.0;
    voiceCurrentUtterance.pitch = 1.0;

    const voices = window.speechSynthesis.getVoices();
    const preferredVoice = voices.find(v => v.lang.startsWith('en') && (v.name.includes('Natural') || v.name.includes('Google') || v.name.includes('Microsoft')));
    if (preferredVoice) voiceCurrentUtterance.voice = preferredVoice;

    voiceCurrentUtterance.onstart = function () {
        setVoiceState('SPEAKING');
    };

    voiceCurrentUtterance.onend = function () {
        setVoiceState('READY');
        if (stopBtn) stopBtn.style.display = 'none';
        if (isHandsFreeEnabled) {
            setTimeout(() => toggleVoiceAgentListening(), 800);
        }
    };

    voiceCurrentUtterance.onerror = function () {
        setVoiceState('READY');
        if (stopBtn) stopBtn.style.display = 'none';
    };

    window.speechSynthesis.speak(voiceCurrentUtterance);
};

window.simbaStopSpeaking = function () {
    if ('speechSynthesis' in window) {
        window.speechSynthesis.cancel();
    }
    const stopBtn = document.getElementById('btnStopSpeaking');
    if (stopBtn) stopBtn.style.display = 'none';
    setVoiceState('READY');
};
