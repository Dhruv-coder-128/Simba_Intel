# Frontend & Templates Rules

This rule documents the frontend architecture, templating conventions, and styling tokens for Simba Intel.

## Frontend Architecture

Simba Intel uses server-rendered Django templates styled with custom CSS properties and driven by vanilla JavaScript. There is **no npm/webpack/vite build pipeline**.

```
Browser Request
      │
      ▼
Django Template Engine (templates/)
      ├── chat.html (Main Cyberpunk Assistant Interface)
      ├── profile.html (Settings, Theme Customizer & Security)
      ├── analytics.html (Usage Metrics & Chart.js Visualizations)
      ├── admin_console/ (Super Admin Operations Dashboard)
      └── partials/ & account/ (Modular Subcomponents & Allauth)
      │
      ▼
Client-Side Execution:
      - Vanilla JavaScript (Streaming parser, Sibling Switcher, Ctrl+K Palette)
      - Semantic CSS Variables (Driven by html[data-theme])
      - CDN Utilities: marked.js, DOMPurify, Chart.js
```

## Styling & Theme System

1. **Theme Attributes on `<html>`**:
   - The UI is themed dynamically using `html[data-*]` attributes injected from the user's profile:
     - `data-theme`: Color scheme (e.g., `cyberpunk`, `midnight-purple`, `matrix-green`, `nord`, `light`, `oled-black`, etc.).
     - `data-density`: `comfortable` or `compact`.
     - `data-card-radius`: `sharp`, `rounded`, or `soft`.
     - `data-animation-level`: `full`, `reduced`, or `none`.
     - `data-glass-intensity`: `off`, `light`, `medium`, or `high`.
2. **CSS Custom Properties**:
   - Use tokenized variables: `--accent`, `--accent-rgb`, `--bg-primary`, `--bg-secondary`, `--text-primary`, `--border-color`.
   - Never hardcode raw hex colors in component styles when tokens exist.
   - Do not override `--accent` inline with JavaScript (this prevents stomping user-selected theme presets).

## Client-Side JavaScript Conventions

1. **Vanilla JavaScript Only**:
   - Keep scripts modular and standard-compliant.
   - Do not add heavy npm libraries or framework bundles.
   - External dependencies must be lightweight and loaded via proven CDN URLs (matching existing patterns for `marked.js` and `Chart.js`).

2. **Sanitization & Security**:
   - Every AI response rendered from markdown into HTML must pass through `DOMPurify.sanitize()` to block XSS attacks.
   - CSRF tokens must be included on all POST/PUT/DELETE fetch calls via the `X-CSRFToken` header.

3. **Message Streaming & Sibling Pills**:
   - During AI streaming, text chunks are appended into the active bubble's DOM container.
   - After streaming completes, the frontend must:
     1. Query `GET /session/<session_id>/active-leaf/` to bind the newly streamed message ID.
     2. Query `GET /messages/<message_id>/siblings/` to update the sibling switcher pill (`‹ 1/2 ›`) without requiring a page reload.

4. **Keyboard Accessibility**:
   - Preserve global hotkeys, including `Ctrl+K` / `Cmd+K` for the command palette, `Escape` to close modals, and `Enter` to submit queries.
