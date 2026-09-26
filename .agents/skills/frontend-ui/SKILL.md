---
name: frontend-ui
description: >-
  Procedures for developing, customizing, and styling Simba Intel's Cyberpunk web interface.
  Use when modifying templates, adding UI components, tweaking theme tokens, updating client-side
  scripts, adjusting streaming buffers, or updating the command palette.
---

# Simba Intel Frontend & UI Runbook

Follow these procedures when modifying templates, stylesheets, and client-side scripts.

## 1. Template Structure & Standards

1. **Django Template Patterns**:
   - Templates reside in `templates/`.
   - Always include `{% csrf_token %}` in forms making state-changing POST requests.
   - For modular components, create reusable snippets in `templates/partials/` and include them via:
     ```django
     {% include "partials/my_component.html" with context_var=value %}
     ```

2. **No Build Step**:
   - Do NOT attempt to run `npm build`, `webpack`, or `vite`.
   - All styles and scripts run natively in modern evergreen browsers.

## 2. Theming & Cyberpunk CSS Tokens

1. **Semantic CSS Tokens**:
   - The interface is powered by CSS custom properties scoped to `html[data-theme]`:
     ```css
     :root {
       --accent: #00f0ff;
       --accent-rgb: 0, 240, 255;
       --bg-primary: #0a0b10;
       --bg-secondary: #12141f;
       --text-primary: #e0e6ed;
     }
     ```
2. **Glassmorphism & Neon Glows**:
   - Use rgba/accent-rgb for borders and glows:
     ```css
     box-shadow: 0 0 15px rgba(var(--accent-rgb), 0.25);
     border: 1px solid rgba(var(--accent-rgb), 0.3);
     backdrop-filter: blur(12px);
     ```
   - Never hardcode fixed hex colors for elements that should adapt to theme presets.

## 3. Client-Side JavaScript Protocols

1. **Markdown & Sanitization**:
   - When rendering markdown streams or user content, always pass HTML through DOMPurify:
     ```javascript
     const rawHtml = marked.parse(markdownText);
     const safeHtml = DOMPurify.sanitize(rawHtml);
     bubbleElement.innerHTML = safeHtml;
     ```

2. **Sibling Switcher Pill Refresh**:
   - When a message is edited or regenerated via in-place DOM patching, refresh the switcher pill immediately:
     ```javascript
     fetch(`/messages/${messageId}/siblings/`)
       .then(res => res.json())
       .then(data => {
         updateSiblingPill(bubbleElement, data.current_index, data.sibling_count);
       });
     ```

3. **Command Palette Integration (`Ctrl+K`)**:
   - The command palette builds its action index dynamically from active DOM elements (models in the select dropdown, sessions in the sidebar).
   - If adding a major new navigation item or action, ensure it registers an entry in the palette filter.

## 4. Verification Checklist

- [ ] Verify template syntax with `python manage.py check`.
- [ ] Confirm layout renders cleanly across light and dark theme presets.
- [ ] Verify that no console errors appear during AI message streaming or branch switching.
