/**
 * Simba Intel - Local Timezone Formatting Utilities
 * Automatically formats all datetime elements to the user's local timezone.
 */

window.TimeUtils = {
    // Formats: 'Nov 5, 2023'
    formatLocalDate: function(isoString) {
        if (!isoString) return '';
        const d = new Date(isoString);
        return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
    },

    // Formats: '14:30' or '2:30 PM' depending on locale
    formatLocalTime: function(isoString) {
        if (!isoString) return '';
        const d = new Date(isoString);
        return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
    },
    
    // Formats: '14:30:45'
    formatLocalTimeSeconds: function(isoString) {
        if (!isoString) return '';
        const d = new Date(isoString);
        return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' });
    },

    // Formats: 'Nov 5, 2023 14:30'
    formatLocalDateTime: function(isoString) {
        if (!isoString) return '';
        const d = new Date(isoString);
        return d.toLocaleString(undefined, { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' });
    },
    
    // Formats: 'Nov 5, 14:30'
    formatLocalDateTimeShort: function(isoString) {
        if (!isoString) return '';
        const d = new Date(isoString);
        return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    },
    
    // Formats: 'Nov 5, 14:30:45'
    formatLocalDateTimeSeconds: function(isoString) {
        if (!isoString) return '';
        const d = new Date(isoString);
        return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' });
    },
    
    // Formats: 'Nov 5, 2023 14:30:45'
    formatLocalDateTimeFull: function(isoString) {
        if (!isoString) return '';
        const d = new Date(isoString);
        return d.toLocaleString(undefined, { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' });
    },

    // Formats: '5 mins ago', '2 hours ago', etc.
    relativeTime: function(isoString) {
        if (!isoString) return '';
        const date = new Date(isoString);
        const now = new Date();
        const seconds = Math.floor((now - date) / 1000);
        
        let interval = seconds / 31536000;
        if (interval > 1) return Math.floor(interval) + " years ago";
        interval = seconds / 2592000;
        if (interval > 1) return Math.floor(interval) + " months ago";
        interval = seconds / 86400;
        if (interval > 1) return Math.floor(interval) + " days ago";
        interval = seconds / 3600;
        if (interval > 1) return Math.floor(interval) + " hours ago";
        interval = seconds / 60;
        if (interval > 1) return Math.floor(interval) + " mins ago";
        return Math.floor(seconds) + " seconds ago";
    },
    
    // Auto-parse elements
    // Examples:
    // <time class="local-time" datetime="2023-11-05T14:30:00Z" data-format="datetime"></time>
    parseAll: function() {
        document.querySelectorAll('.local-time').forEach(el => {
            const iso = el.getAttribute('datetime');
            const format = el.getAttribute('data-format') || 'datetime';
            const fallback = el.getAttribute('data-fallback') || '';
            
            if (!iso) {
                if (fallback) el.textContent = fallback;
                return;
            }
            
            let result = '';
            switch(format) {
                case 'date': result = this.formatLocalDate(iso); break;
                case 'time': result = this.formatLocalTime(iso); break;
                case 'time-seconds': result = this.formatLocalTimeSeconds(iso); break;
                case 'datetime': result = this.formatLocalDateTime(iso); break;
                case 'datetime-short': result = this.formatLocalDateTimeShort(iso); break;
                case 'datetime-seconds': result = this.formatLocalDateTimeSeconds(iso); break;
                case 'datetime-full': result = this.formatLocalDateTimeFull(iso); break;
                case 'relative': result = this.relativeTime(iso); break;
                default: result = this.formatLocalDateTime(iso); break;
            }
            
            el.textContent = result;
            // Only parse once to prevent overriding manual updates or duplicate runs
            el.classList.remove('local-time'); 
            el.classList.add('local-time-parsed');
        });
    }
};

// Run automatically on load
document.addEventListener('DOMContentLoaded', () => {
    window.TimeUtils.parseAll();
});

// Create a MutationObserver to parse dynamically added elements (like chat messages)
const timeObserver = new MutationObserver((mutations) => {
    let shouldParse = false;
    for (const mutation of mutations) {
        if (mutation.addedNodes.length > 0) {
            shouldParse = true;
            break;
        }
    }
    if (shouldParse) {
        window.TimeUtils.parseAll();
    }
});

// Start observing the body for injected elements
document.addEventListener('DOMContentLoaded', () => {
    timeObserver.observe(document.body, { childList: true, subtree: true });
});
