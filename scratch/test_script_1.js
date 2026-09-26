
        // Dismissal is tracked client-side only (localStorage), keyed by
        // broadcast id - there's no per-user DB row for "has this user
        // seen broadcast #N", so a dismissal is per-browser, not
        // per-account. A non-dismissible ("pinned") broadcast has no
        // dismiss button at all and is never hidden this way.
        (function () {
            const id = "dj_var"; const key = 'simba_dismissed_broadcast_' + id; if (localStorage.getItem(key)) { const banner = document.getElementById('broadcastBanner'); const popup = document.getElementById('broadcastPopupOverlay'); if (banner) banner.remove(); if (popup) popup.remove(); } }) (); function dismissBroadcast(id, isPopup) { localStorage.setItem('simba_dismissed_broadcast_' + id, '1'); const el = document.getElementById(isPopup ? 'broadcastPopupOverlay' : 'broadcastBanner'); if (el) el.remove(); } 