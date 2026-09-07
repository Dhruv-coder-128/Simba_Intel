# Generates and validates the full Agent and Voice CSS module

css_block = '''        /* ==========================================================================
           SIMBA_INTEL AGENT MODE & VOICE AGENT DESIGN SYSTEM FOUNDATION
           ========================================================================== */

        /* --- Part 1: Design Tokens Layer --- */
        :root {
            --agent-bg: var(--bg, #0b0c10);
            --agent-surface: rgba(15, 20, 29, 0.88);
            --agent-surface-card: rgba(13, 17, 26, 0.92);
            --agent-surface-elevated: rgba(22, 28, 40, 0.96);
            --agent-surface-subtle: rgba(255, 255, 255, 0.03);
            
            --agent-border: rgba(255, 255, 255, 0.08);
            --agent-border-subtle: rgba(255, 255, 255, 0.04);
            --agent-border-strong: rgba(var(--accent-rgb, 0, 229, 255), 0.35);
            --agent-border-hover: rgba(255, 255, 255, 0.2);
            
            --agent-accent: var(--accent, #00e5ff);
            --agent-accent-rgb: var(--accent-rgb, 0, 229, 255);
            --agent-accent-soft: rgba(var(--accent-rgb, 0, 229, 255), 0.12);
            --agent-accent-dim: rgba(var(--accent-rgb, 0, 229, 255), 0.05);
            --agent-accent-hover: rgba(var(--accent-rgb, 0, 229, 255), 0.22);
            --agent-accent-glow: 0 0 16px rgba(var(--accent-rgb, 0, 229, 255), 0.25);
            
            --agent-text: var(--text, #d8dbe1);
            --agent-text-heading: #ffffff;
            --agent-text-muted: var(--text-dim, #8b93a3);
            --agent-text-subtle: rgba(255, 255, 255, 0.45);
            
            --agent-success: #10b981;
            --agent-success-soft: rgba(16, 185, 129, 0.12);
            --agent-success-border: rgba(16, 185, 129, 0.32);
            
            --agent-warning: #f59e0b;
            --agent-warning-soft: rgba(245, 158, 11, 0.12);
            --agent-warning-border: rgba(245, 158, 11, 0.32);
            
            --agent-danger: #ef4444;
            --agent-danger-soft: rgba(239, 68, 68, 0.14);
            --agent-danger-border: rgba(239, 68, 68, 0.32);
            
            --agent-info: #06b6d4;
            --agent-info-soft: rgba(6, 182, 212, 0.12);
            --agent-info-border: rgba(6, 182, 212, 0.3);

            --agent-radius-xs: 4px;
            --agent-radius-sm: 6px;
            --agent-radius-md: 10px;
            --agent-radius-lg: 14px;
            --agent-radius-full: 9999px;

            --agent-shadow-xs: 0 1px 3px rgba(0, 0, 0, 0.35);
            --agent-shadow-sm: 0 3px 8px rgba(0, 0, 0, 0.45);
            --agent-shadow-md: 0 8px 24px rgba(0, 0, 0, 0.55);
            --agent-shadow-lg: 0 16px 40px rgba(0, 0, 0, 0.7);

            --agent-font-sans: var(--font-sans, 'Outfit', -apple-system, sans-serif);
            --agent-font-mono: var(--font-mono, 'JetBrains Mono', monospace);
        }

        /* --- Absolute Rule: Strict Control Resets for Agent & Voice --- */
        .agent-workspace-wrapper button,
        .voice-workspace-wrapper button,
        .agent-history-drawer button,
        .discovery-modal button {
            border: none;
            background: transparent;
            color: inherit;
            font-family: inherit;
            cursor: pointer;
            outline: none;
            -webkit-tap-highlight-color: transparent;
        }

        .agent-workspace-wrapper button:focus-visible,
        .voice-workspace-wrapper button:focus-visible,
        .agent-history-drawer button:focus-visible,
        .discovery-modal button:focus-visible,
        .agent-workspace-wrapper select:focus-visible,
        .agent-history-drawer input:focus-visible,
        .discovery-modal input:focus-visible {
            outline: none;
            box-shadow: 0 0 0 2px var(--agent-accent) !important;
        }

        /* ==========================================================================
           PART 2: AGENT PAGE LAYOUT
           ========================================================================== */
        .agent-workspace-wrapper {
            width: 100%;
            max-width: 1060px;
            margin: 0 auto;
            padding: 20px 20px 36px;
            display: flex;
            flex-direction: column;
            gap: 20px;
            box-sizing: border-box;
            overflow-x: hidden;
            animation: simbaFadeSlideUp 0.25s var(--ease-out-expo);
        }

        /* ==========================================================================
           PART 3: AGENT HEADER
           ========================================================================== */
        .agent-header-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
            padding-bottom: 16px;
            border-bottom: 1px solid var(--agent-border);
            flex-wrap: wrap;
        }

        .agent-header-left {
            display: flex;
            flex-direction: column;
            gap: 5px;
        }

        .agent-title-tag {
            display: inline-flex;
            align-items: center;
            gap: 10px;
        }

        .agent-pulse-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--agent-success);
            box-shadow: 0 0 10px var(--agent-success);
            display: inline-block;
            animation: pulseAgentDot 2s infinite ease-in-out;
        }

        @keyframes pulseAgentDot {
            0%, 100% { opacity: 1; transform: scale(1); }
            50% { opacity: 0.5; transform: scale(0.85); }
        }

        .agent-mode-badge {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: var(--agent-accent-soft);
            border: 1px solid var(--agent-border-strong);
            color: var(--agent-accent);
            padding: 3px 8px;
            border-radius: var(--agent-radius-xs);
            font-size: 11px;
            font-weight: 700;
            font-family: var(--agent-font-mono);
            letter-spacing: 0.5px;
            text-transform: uppercase;
        }

        .agent-header-title {
            font-size: 18px;
            font-weight: 700;
            color: var(--agent-text-heading);
            margin: 0;
            font-family: var(--agent-font-sans);
            letter-spacing: 0.3px;
        }

        .agent-header-subtitle {
            font-size: 12.5px;
            color: var(--agent-text-muted);
            margin: 0;
            line-height: 1.4;
        }

        .agent-header-right {
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
        }

        /* --- Header System Status Strip --- */
        .agent-system-strip {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--agent-border);
            border-radius: var(--agent-radius-full);
            padding: 4px 10px;
        }

        .system-chip {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            font-size: 11px;
            font-family: var(--agent-font-mono);
            color: var(--agent-text-muted);
            padding: 2px 6px;
            border-radius: var(--agent-radius-xs);
            transition: all 0.15s ease;
        }

        .system-chip.desktop-chip, .system-chip.screen-chip {
            cursor: pointer;
        }

        .system-chip.desktop-chip:hover, .system-chip.screen-chip:hover {
            background: rgba(255, 255, 255, 0.06);
            color: var(--agent-text);
        }

        .system-chip strong {
            color: #ffffff;
            font-weight: 600;
        }

        /* --- Status Dots --- */
        .status-dot {
            width: 7px;
            height: 7px;
            border-radius: 50%;
            display: inline-block;
        }

        .status-dot.dot-online {
            background: var(--agent-success);
            box-shadow: 0 0 6px rgba(16, 185, 129, 0.5);
        }

        .status-dot.dot-offline {
            background: var(--agent-danger);
            box-shadow: 0 0 6px rgba(239, 68, 68, 0.5);
        }

        .status-dot.dot-disabled {
            background: rgba(255, 255, 255, 0.3);
        }

        /* --- Part 11: Context Selector & Custom Select --- */
        .agent-context-dropdown-wrap {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--agent-border);
            border-radius: var(--agent-radius-sm);
            padding: 2px 6px;
            transition: border-color 0.15s ease;
        }

        .agent-context-dropdown-wrap:hover {
            border-color: var(--agent-border-hover);
        }

        .agent-context-dropdown-wrap label {
            font-size: 11px;
            color: var(--agent-text-muted);
            font-family: var(--agent-font-mono);
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 4px;
            margin: 0;
            cursor: pointer;
            white-space: nowrap;
        }

        .simba-select {
            -webkit-appearance: none;
            -moz-appearance: none;
            appearance: none;
            background-color: transparent;
            background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='10' viewBox='0 0 24 24' fill='none' stroke='rgba(255,255,255,0.5)' stroke-width='2.5' stroke-linecap='round' stroke-linejoin='round'%3E%3Cpolyline points='6 9 12 15 18 9'%3E%3C/polyline%3E%3C/svg%3E");
            background-repeat: no-repeat;
            background-position: right 6px center;
            border: none;
            border-radius: var(--agent-radius-xs);
            padding: 4px 22px 4px 6px;
            font-family: var(--agent-font-mono);
            font-size: 11.5px;
            color: #ffffff;
            cursor: pointer;
            outline: none;
            transition: color 0.15s ease;
            max-width: 180px;
            text-overflow: ellipsis;
            white-space: nowrap;
            overflow: hidden;
        }

        .simba-select:hover {
            color: var(--agent-accent);
        }

        .simba-select option {
            background: #0d121c;
            color: #ffffff;
            padding: 6px 10px;
        }

        /* --- Part 12: Header Action Buttons --- */
        .btn-agent-header-action {
            display: inline-flex;
            align-items: center;
            gap: 7px;
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid var(--agent-border) !important;
            color: var(--agent-text) !important;
            padding: 6px 12px;
            border-radius: var(--agent-radius-sm);
            font-size: 11.5px;
            font-family: var(--agent-font-mono);
            font-weight: 500;
            cursor: pointer;
            transition: all 0.15s ease;
            white-space: nowrap;
        }

        .btn-agent-header-action:hover {
            background: rgba(255, 255, 255, 0.09);
            color: #ffffff !important;
            border-color: var(--agent-border-hover) !important;
        }

        .btn-agent-header-action:active {
            transform: scale(0.98);
        }

        /* ==========================================================================
           PART 4 & 5: AGENT STATUS CARDS & SEMANTIC COLORS
           ========================================================================== */
        .agent-section {
            display: flex;
            flex-direction: column;
            gap: 10px;
        }

        .agent-section-label {
            font-size: 11px;
            font-weight: 700;
            font-family: var(--agent-font-mono);
            letter-spacing: 0.8px;
            color: var(--agent-text-muted);
            text-transform: uppercase;
            display: flex;
            align-items: center;
            gap: 7px;
        }

        .agent-status-grid {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 12px;
        }

        .agent-status-card {
            background: var(--agent-surface-card);
            border: 1px solid var(--agent-border);
            border-radius: var(--agent-radius-md);
            padding: 14px 16px;
            display: flex;
            flex-direction: column;
            gap: 8px;
            transition: border-color 0.15s ease, transform 0.15s ease;
            box-shadow: var(--agent-shadow-xs);
        }

        .agent-status-card:hover {
            border-color: var(--agent-border-hover);
        }

        .agent-card-top {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
        }

        .agent-card-meta {
            font-size: 10.5px;
            font-weight: 700;
            font-family: var(--agent-font-mono);
            color: var(--agent-text-subtle);
            letter-spacing: 0.6px;
            text-transform: uppercase;
        }

        .agent-card-desc {
            font-size: 11.5px;
            color: var(--agent-text-muted);
            line-height: 1.4;
            flex-grow: 1;
        }

        .agent-card-action-btn {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid var(--agent-border) !important;
            color: var(--agent-text) !important;
            padding: 4px 10px;
            border-radius: var(--agent-radius-xs);
            font-size: 10.5px;
            font-family: var(--agent-font-mono);
            cursor: pointer;
            transition: all 0.15s ease;
            margin-top: 4px;
        }

        .agent-card-action-btn:hover {
            background: rgba(255, 255, 255, 0.08);
            color: #ffffff !important;
            border-color: var(--agent-border-hover) !important;
        }

        /* --- Semantic Lifecycle Badges --- */
        .agent-lifecycle-badge {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            padding: 3px 8px;
            border-radius: var(--agent-radius-xs);
            font-size: 10.5px;
            font-family: var(--agent-font-mono);
            font-weight: 700;
            letter-spacing: 0.4px;
            text-transform: uppercase;
        }

        .agent-lifecycle-badge.status-idle {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.1);
            color: var(--agent-text-muted);
        }

        .agent-lifecycle-badge.status-planning {
            background: rgba(139, 92, 246, 0.12);
            border: 1px solid rgba(139, 92, 246, 0.3);
            color: #a78bfa;
        }

        .agent-lifecycle-badge.status-executing {
            background: var(--agent-accent-soft);
            border: 1px solid var(--agent-border-strong);
            color: var(--agent-accent);
        }

        .agent-lifecycle-badge.status-waiting {
            background: var(--agent-warning-soft);
            border: 1px solid var(--agent-warning-border);
            color: var(--agent-warning);
        }

        .agent-lifecycle-badge.status-verifying {
            background: rgba(59, 130, 246, 0.12);
            border: 1px solid rgba(59, 130, 246, 0.3);
            color: #60a5fa;
        }

        .agent-lifecycle-badge.status-completed {
            background: var(--agent-success-soft);
            border: 1px solid var(--agent-success-border);
            color: var(--agent-success);
        }

        .agent-lifecycle-badge.status-failed {
            background: var(--agent-danger-soft);
            border: 1px solid var(--agent-danger-border);
            color: #f87171;
        }

        .agent-lifecycle-badge.status-cancelled {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.1);
            color: rgba(255, 255, 255, 0.5);
        }

        /* --- PC Status Chip --- */
        .pc-status-chip {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 3px 8px;
            border-radius: var(--agent-radius-xs);
            font-size: 10.5px;
            font-family: var(--agent-font-mono);
            font-weight: 700;
            cursor: pointer;
            transition: all 0.15s ease;
        }

        .pc-status-chip.connected {
            background: var(--agent-success-soft);
            border: 1px solid var(--agent-success-border);
            color: var(--agent-success);
        }

        .pc-status-chip.offline {
            background: var(--agent-danger-soft);
            border: 1px solid var(--agent-danger-border);
            color: #f87171;
        }

        .pc-dot {
            width: 6px;
            height: 6px;
            border-radius: 50%;
            display: inline-block;
        }

        .pc-status-chip.connected .pc-dot {
            background: var(--agent-success);
            box-shadow: 0 0 6px var(--agent-success);
        }

        .pc-status-chip.offline .pc-dot {
            background: var(--agent-danger);
            box-shadow: 0 0 6px var(--agent-danger);
        }

        /* --- Screen Status Chip --- */
        .screen-status-chip {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 3px 8px;
            border-radius: var(--agent-radius-xs);
            font-size: 10.5px;
            font-family: var(--agent-font-mono);
            font-weight: 700;
        }

        .screen-status-chip.enabled {
            background: rgba(6, 182, 212, 0.12);
            border: 1px solid rgba(6, 182, 212, 0.3);
            color: #06b6d4;
        }

        .screen-status-chip.disabled {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.1);
            color: rgba(255, 255, 255, 0.5);
        }

        .screen-dot {
            width: 6px;
            height: 6px;
            border-radius: 50%;
            display: inline-block;
        }

        .screen-status-chip.enabled .screen-dot {
            background: #06b6d4;
            box-shadow: 0 0 6px #06b6d4;
        }

        .screen-status-chip.disabled .screen-dot {
            background: rgba(255, 255, 255, 0.3);
        }

        /* ==========================================================================
           PART 6 & 7: CURRENT TASK CARD, EMPTY STATE & TIMELINE STEPPER
           ========================================================================== */
        .agent-current-task-box {
            background: var(--agent-surface-card);
            border: 1px solid var(--agent-border);
            border-radius: var(--agent-radius-md);
            overflow: hidden;
            box-shadow: var(--agent-shadow-sm);
        }

        /* --- Empty Task State --- */
        .agent-empty-task-card {
            padding: 32px 24px;
            display: flex;
            flex-direction: column;
            align-items: center;
            text-align: center;
            gap: 10px;
        }

        .agent-empty-icon {
            width: 44px;
            height: 44px;
            border-radius: 50%;
            background: rgba(255, 255, 255, 0.03);
            border: 1px solid var(--agent-border);
            display: grid;
            place-items: center;
            color: var(--agent-accent);
            font-size: 16px;
        }

        .agent-empty-title {
            font-family: var(--agent-font-sans);
            font-size: 15px;
            font-weight: 700;
            color: #ffffff;
            letter-spacing: 0.3px;
        }

        .agent-empty-sub {
            font-size: 12.5px;
            color: var(--agent-text-muted);
            max-width: 420px;
            line-height: 1.4;
            margin: 0;
        }

        .btn-start-task {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: var(--agent-accent) !important;
            color: #000000 !important;
            font-weight: 700 !important;
            font-family: var(--agent-font-mono) !important;
            font-size: 12px !important;
            padding: 8px 18px !important;
            border-radius: var(--agent-radius-sm) !important;
            cursor: pointer;
            transition: all 0.15s ease;
            margin-top: 6px;
            box-shadow: var(--agent-accent-glow);
        }

        .btn-start-task:hover {
            transform: translateY(-1px);
            filter: brightness(1.1);
        }

        .btn-start-task:active {
            transform: translateY(0) scale(0.98);
        }

        /* --- Active Task Card --- */
        .agent-active-task-card {
            padding: 18px 20px;
            display: flex;
            flex-direction: column;
            gap: 14px;
        }

        .agent-active-card-header {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 16px;
            flex-wrap: wrap;
        }

        .agent-active-info {
            display: flex;
            flex-direction: column;
            gap: 4px;
        }

        .agent-active-task-label {
            font-family: var(--agent-font-mono);
            font-size: 10.5px;
            font-weight: 700;
            color: var(--agent-text-subtle);
            letter-spacing: 0.5px;
        }

        .agent-active-task-title {
            font-family: var(--agent-font-sans);
            font-size: 15px;
            font-weight: 700;
            color: #ffffff;
            margin: 0;
            line-height: 1.3;
        }

        .agent-task-actions-wrap {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .btn-task-control {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 5px 12px;
            border-radius: var(--agent-radius-sm);
            font-size: 11.5px;
            font-family: var(--agent-font-mono);
            font-weight: 600;
            cursor: pointer;
            transition: all 0.15s ease;
        }

        .btn-task-control.pause {
            background: rgba(245, 158, 11, 0.12);
            border: 1px solid rgba(245, 158, 11, 0.3) !important;
            color: #f59e0b !important;
        }

        .btn-task-control.pause:hover {
            background: rgba(245, 158, 11, 0.22);
            color: #ffffff !important;
        }

        .btn-task-control.stop {
            background: rgba(239, 68, 68, 0.12);
            border: 1px solid rgba(239, 68, 68, 0.3) !important;
            color: #f87171 !important;
        }

        .btn-task-control.stop:hover {
            background: rgba(239, 68, 68, 0.22);
            color: #ffffff !important;
        }

        .btn-task-control.rerun {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--agent-border) !important;
            color: #ffffff !important;
        }

        .btn-task-control.rerun:hover {
            background: rgba(255, 255, 255, 0.1);
            border-color: var(--agent-border-hover) !important;
        }

        /* --- Multi-Step Plan Preview --- */
        .agent-plan-preview-box {
            background: rgba(0, 0, 0, 0.25);
            border: 1px solid var(--agent-border);
            border-radius: var(--agent-radius-sm);
            padding: 12px 14px;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .agent-plan-preview-header {
            font-size: 11px;
            font-family: var(--agent-font-mono);
            font-weight: 700;
            color: var(--agent-accent);
            display: flex;
            align-items: center;
            gap: 6px;
            letter-spacing: 0.5px;
        }

        .agent-plan-step-list {
            margin: 0;
            padding-left: 20px;
            font-size: 12px;
            color: rgba(255, 255, 255, 0.85);
            display: flex;
            flex-direction: column;
            gap: 4px;
        }

        .btn-execute-plan {
            align-self: flex-start;
            margin-top: 6px;
            background: var(--agent-accent) !important;
            color: #000000 !important;
            font-weight: 700 !important;
            font-family: var(--agent-font-mono) !important;
            font-size: 11.5px !important;
            padding: 6px 14px !important;
            border-radius: var(--agent-radius-xs) !important;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            cursor: pointer;
            transition: all 0.15s ease;
        }

        .btn-execute-plan:hover {
            filter: brightness(1.1);
        }

        /* --- Part 7: Reusable Task Stepper (Vertical Timeline) --- */
        .agent-step-checklist {
            display: flex;
            flex-direction: column;
            gap: 6px;
            padding: 10px 12px;
            background: rgba(0, 0, 0, 0.2);
            border: 1px solid var(--agent-border);
            border-radius: var(--agent-radius-sm);
        }

        .agent-checklist-item, .agent-step {
            display: flex;
            align-items: center;
            gap: 10px;
            font-size: 12.5px;
            color: var(--agent-text-muted);
            padding: 6px 10px;
            border-radius: var(--agent-radius-xs);
            border: 1px solid transparent;
            transition: all 0.15s ease;
        }

        .checklist-bullet {
            width: 18px;
            height: 18px;
            display: grid;
            place-items: center;
            font-size: 11px;
            flex-shrink: 0;
            color: var(--agent-text-subtle);
        }

        .checklist-text {
            flex-grow: 1;
        }

        /* Stepper States */
        .agent-checklist-item.completed, .agent-step.agent-step-completed {
            color: rgba(255, 255, 255, 0.85);
        }

        .agent-checklist-item.completed .checklist-bullet, .agent-step.agent-step-completed .checklist-bullet {
            color: var(--agent-success);
        }

        .agent-checklist-item.in-progress, .agent-step.agent-step-active {
            background: rgba(var(--agent-accent-rgb, 0, 229, 255), 0.08);
            border-color: rgba(var(--agent-accent-rgb, 0, 229, 255), 0.25);
            color: #ffffff;
            font-weight: 500;
        }

        .agent-checklist-item.in-progress .checklist-bullet, .agent-step.agent-step-active .checklist-bullet {
            color: var(--agent-accent);
        }

        .agent-checklist-item.pending, .agent-step.agent-step-pending {
            color: rgba(255, 255, 255, 0.4);
        }

        .agent-checklist-item.failed, .agent-step.agent-step-failed {
            color: #f87171;
            background: var(--agent-danger-soft);
            border-color: var(--agent-danger-border);
        }

        .agent-checklist-item.failed .checklist-bullet, .agent-step.agent-step-failed .checklist-bullet {
            color: var(--agent-danger);
        }

        /* --- Task Result Box --- */
        .agent-task-result-box {
            background: rgba(16, 185, 129, 0.06);
            border: 1px solid var(--agent-success-border);
            border-radius: var(--agent-radius-sm);
            padding: 12px 14px;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }

        .agent-task-result-header {
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 12px;
            font-family: var(--agent-font-mono);
            font-weight: 700;
            color: var(--agent-success);
        }

        .agent-task-result-summary {
            font-size: 12.5px;
            color: #ffffff;
            line-height: 1.4;
        }

        .agent-technical-details {
            margin-top: 4px;
        }

        .agent-technical-details summary {
            font-size: 11px;
            font-family: var(--agent-font-mono);
            color: var(--agent-text-muted);
            cursor: pointer;
            padding: 4px 0;
            outline: none;
            transition: color 0.15s ease;
        }

        .agent-technical-details summary:hover {
            color: #ffffff;
        }

        .agent-technical-content {
            margin-top: 6px;
            background: #080c14;
            border: 1px solid var(--agent-border);
            border-radius: var(--agent-radius-xs);
            padding: 8px 12px;
            font-family: var(--agent-font-mono);
            font-size: 11px;
            color: rgba(255, 255, 255, 0.7);
            max-height: 160px;
            overflow-y: auto;
            white-space: pre-wrap;
        }

        /* ==========================================================================
           PART 8 & 9: QUICK ACTION CARDS & TECHNICAL BADGES
           ========================================================================== */
        .btn-more-tasks-link {
            background: transparent;
            border: none;
            color: var(--agent-accent) !important;
            font-size: 11px;
            font-family: var(--agent-font-mono);
            font-weight: 600;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 5px;
            transition: opacity 0.15s ease;
        }

        .btn-more-tasks-link:hover {
            opacity: 0.8;
            text-decoration: underline;
        }

        .agent-quick-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 12px;
        }

        .agent-quick-card {
            background: var(--agent-surface-card);
            border: 1px solid var(--agent-border) !important;
            border-radius: var(--agent-radius-md);
            padding: 14px 16px;
            display: flex;
            flex-direction: column;
            gap: 7px;
            cursor: pointer;
            text-align: left;
            transition: transform 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
            box-shadow: var(--agent-shadow-xs);
        }

        .agent-quick-card:hover {
            transform: translateY(-2px);
            border-color: var(--agent-border-hover) !important;
            box-shadow: var(--agent-shadow-sm);
        }

        .agent-quick-card:active {
            transform: translateY(0) scale(0.99);
        }

        .agent-quick-card.discovery-trigger {
            border-style: dashed !important;
            border-color: var(--agent-border-strong) !important;
            background: var(--agent-accent-dim);
        }

        .agent-quick-card.discovery-trigger:hover {
            background: var(--agent-accent-soft);
            border-color: var(--agent-accent) !important;
        }

        .agent-quick-top {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .agent-quick-icon {
            font-size: 14px;
            width: 22px;
            display: grid;
            place-items: center;
        }

        .agent-quick-title {
            font-family: var(--agent-font-sans);
            font-size: 13.5px;
            font-weight: 600;
            color: #ffffff;
        }

        /* --- Part 9: Technical Badges --- */
        .agent-target-badge {
            margin-left: auto;
            font-size: 9px;
            font-family: var(--agent-font-mono);
            font-weight: 700;
            padding: 2px 6px;
            border-radius: var(--agent-radius-xs);
            letter-spacing: 0.4px;
            text-transform: uppercase;
        }

        .agent-target-badge.desktop {
            background: rgba(6, 182, 212, 0.12);
            color: #06b6d4;
            border: 1px solid rgba(6, 182, 212, 0.3);
        }

        .agent-target-badge.cloud {
            background: var(--agent-success-soft);
            color: var(--agent-success);
            border: 1px solid var(--agent-success-border);
        }

        .agent-target-badge.requires-pc {
            background: var(--agent-warning-soft);
            color: var(--agent-warning);
            border: 1px solid var(--agent-warning-border);
        }

        .agent-quick-desc {
            font-size: 11.5px;
            color: var(--agent-text-muted);
            line-height: 1.4;
            margin: 0;
        }

        /* ==========================================================================
           PART 13 & 14: TASK HISTORY DRAWER (DESKTOP & MOBILE)
           ========================================================================== */
        .agent-history-overlay {
            position: fixed;
            inset: 0;
            background: rgba(0, 0, 0, 0.65);
            backdrop-filter: blur(6px);
            z-index: 1040;
            animation: fadeInModal 0.2s ease-out;
        }

        .agent-history-drawer {
            display: none !important;
            position: fixed;
            top: 0;
            right: 0;
            width: 440px;
            max-width: 100vw;
            height: 100dvh;
            background: rgba(11, 15, 24, 0.98);
            border-left: 1px solid var(--agent-border-strong);
            backdrop-filter: blur(24px);
            z-index: 1050;
            flex-direction: column;
            box-shadow: -12px 0 48px rgba(0, 0, 0, 0.75);
            animation: drawerSlideIn 0.25s cubic-bezier(0.16, 1, 0.3, 1);
        }

        .agent-history-drawer.open {
            display: flex !important;
        }

        @keyframes drawerSlideIn {
            from { transform: translateX(100%); }
            to { transform: translateX(0); }
        }

        .drawer-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 16px 20px;
            border-bottom: 1px solid var(--agent-border);
        }

        .drawer-title {
            font-size: 13.5px;
            font-weight: 700;
            color: #ffffff;
            display: flex;
            align-items: center;
            gap: 8px;
            font-family: var(--agent-font-sans);
            letter-spacing: 0.3px;
        }

        .drawer-close-btn {
            background: transparent;
            border: none !important;
            color: var(--agent-text-muted) !important;
            font-size: 15px;
            cursor: pointer;
            width: 32px;
            height: 32px;
            display: grid;
            place-items: center;
            border-radius: var(--agent-radius-xs);
            transition: all 0.15s ease;
        }

        .drawer-close-btn:hover {
            color: #ffffff !important;
            background: rgba(255, 255, 255, 0.08);
        }

        .drawer-toolbar {
            padding: 12px 20px;
            border-bottom: 1px solid var(--agent-border);
            display: flex;
            flex-direction: column;
            gap: 10px;
            background: rgba(0, 0, 0, 0.15);
        }

        .drawer-search-wrap, .discovery-search-wrap {
            position: relative;
            width: 100%;
        }

        .drawer-search-wrap i, .discovery-search-wrap i {
            position: absolute;
            left: 12px;
            top: 50%;
            transform: translateY(-50%);
            color: var(--agent-text-subtle);
            font-size: 12px;
            pointer-events: none;
        }

        .drawer-search-wrap input, .discovery-search-wrap input {
            width: 100%;
            background: rgba(0, 0, 0, 0.35);
            border: 1px solid var(--agent-border);
            border-radius: var(--agent-radius-sm);
            padding: 8px 12px 8px 34px;
            font-size: 12px;
            color: #ffffff;
            outline: none;
            box-sizing: border-box;
            font-family: var(--agent-font-sans);
            transition: border-color 0.15s ease;
        }

        .drawer-search-wrap input:focus, .discovery-search-wrap input:focus {
            border-color: var(--agent-accent);
        }

        .drawer-filters-bar, .discovery-category-tabs {
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
        }

        .drawer-filter-btn, .discovery-tab {
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid var(--agent-border) !important;
            color: var(--agent-text-muted) !important;
            padding: 4px 10px;
            border-radius: var(--agent-radius-xs);
            font-size: 11px;
            font-family: var(--agent-font-mono);
            cursor: pointer;
            transition: all 0.15s ease;
            display: inline-flex;
            align-items: center;
            gap: 5px;
        }

        .drawer-filter-btn:hover, .discovery-tab:hover {
            background: rgba(255, 255, 255, 0.08);
            color: #ffffff !important;
        }

        .drawer-filter-btn.active, .discovery-tab.active {
            background: var(--agent-accent) !important;
            color: #000000 !important;
            font-weight: 700 !important;
            border-color: var(--agent-accent) !important;
        }

        .drawer-content {
            flex: 1;
            overflow-y: auto;
            padding: 16px 20px;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .task-hist-loading, .task-hist-empty, .task-hist-error {
            text-align: center;
            padding: 40px 20px;
            color: var(--agent-text-muted);
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 8px;
        }

        .task-hist-empty h4, .task-hist-error h4 {
            font-family: var(--agent-font-sans);
            font-size: 13.5px;
            font-weight: 600;
            color: #ffffff;
            margin: 0;
        }

        .task-hist-empty p, .task-hist-error p {
            font-size: 11.5px;
            color: var(--agent-text-muted);
            margin: 0;
        }

        .task-history-card {
            background: var(--agent-surface-card);
            border: 1px solid var(--agent-border);
            border-radius: var(--agent-radius-sm);
            padding: 12px 14px;
            display: flex;
            flex-direction: column;
            gap: 6px;
            transition: border-color 0.15s ease;
        }

        .task-history-card:hover {
            border-color: var(--agent-border-hover);
        }

        .task-hist-top {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
        }

        .task-hist-title {
            font-family: var(--agent-font-sans);
            font-size: 13px;
            font-weight: 600;
            color: #ffffff;
            text-overflow: ellipsis;
            overflow: hidden;
            white-space: nowrap;
        }

        .task-hist-meta {
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 10.5px;
            font-family: var(--agent-font-mono);
            color: var(--agent-text-subtle);
        }

        .task-hist-snippet {
            font-size: 11px;
            color: var(--agent-text-muted);
            line-height: 1.4;
            max-height: 38px;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        /* ==========================================================================
           PART 15-22: VOICE AGENT WORKSPACE
           ========================================================================== */
        .voice-workspace-wrapper {
            width: 100%;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px 20px 36px;
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 20px;
            box-sizing: border-box;
            animation: simbaFadeSlideUp 0.25s var(--ease-out-expo);
        }

        .voice-header-card {
            width: 100%;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 16px;
            padding-bottom: 16px;
            border-bottom: 1px solid var(--agent-border);
            flex-wrap: wrap;
        }

        .voice-header-left {
            display: flex;
            flex-direction: column;
            gap: 4px;
        }

        .voice-header-title {
            font-size: 18px;
            font-weight: 700;
            color: #ffffff;
            margin: 0;
            font-family: var(--agent-font-sans);
            letter-spacing: 0.3px;
        }

        .voice-header-subtitle {
            font-size: 12.5px;
            color: var(--agent-text-muted);
            margin: 0;
            line-height: 1.4;
        }

        .voice-pulse-dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #06b6d4;
            box-shadow: 0 0 10px #06b6d4;
            display: inline-block;
            animation: pulseAgentDot 2s infinite ease-in-out;
        }

        /* --- Part 22: Voice Workflow Pipeline Card --- */
        .voice-pipeline-card {
            width: 100%;
            background: var(--agent-surface-card);
            border: 1px solid var(--agent-border);
            border-radius: var(--agent-radius-md);
            padding: 10px 16px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            box-shadow: var(--agent-shadow-xs);
        }

        .voice-pipeline-step {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            font-family: var(--agent-font-mono);
            font-size: 10.5px;
            font-weight: 700;
            color: var(--agent-text-subtle);
            padding: 4px 8px;
            border-radius: var(--agent-radius-xs);
            transition: all 0.2s ease;
        }

        .voice-pipeline-step .pipeline-icon {
            font-size: 11px;
        }

        .voice-pipeline-step.active {
            background: var(--agent-accent-soft);
            border: 1px solid var(--agent-border-strong);
            color: var(--agent-accent);
        }

        .voice-pipeline-card .pipeline-arrow {
            color: rgba(255, 255, 255, 0.2);
            font-size: 10px;
        }

        /* --- Part 18: Voice Hero Microphone Stage --- */
        .voice-hero-stage {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 12px;
            padding: 10px 0;
            width: 100%;
        }

        .voice-visualizer-container {
            position: relative;
            width: 140px;
            height: 140px;
            display: grid;
            place-items: center;
        }

        .voice-wave-ring {
            position: absolute;
            inset: 0;
            border-radius: 50%;
            border: 1px solid rgba(6, 182, 212, 0.15);
            pointer-events: none;
            transition: all 0.3s ease;
        }

        .voice-wave-ring.ring-1 { inset: -8px; }
        .voice-wave-ring.ring-2 { inset: -20px; }
        .voice-wave-ring.ring-3 { inset: -34px; }

        .voice-visualizer-container.active .voice-wave-ring {
            border-color: rgba(6, 182, 212, 0.5);
            animation: voiceWavePulse 1.6s cubic-bezier(0.2, 0.8, 0.2, 1) infinite;
        }

        .voice-visualizer-container.active .ring-1 { animation-delay: 0s; }
        .voice-visualizer-container.active .ring-2 { animation-delay: 0.35s; }
        .voice-visualizer-container.active .ring-3 { animation-delay: 0.7s; }

        .voice-visualizer-container.processing .voice-wave-ring {
            border-color: rgba(245, 158, 11, 0.4);
            animation: voiceWavePulse 1.2s ease-in-out infinite;
        }

        .voice-visualizer-container.speaking .voice-wave-ring {
            border-color: rgba(6, 182, 212, 0.6);
            animation: voiceWavePulse 1.4s ease-in-out infinite;
        }

        .voice-visualizer-container.error .voice-wave-ring {
            border-color: rgba(239, 68, 68, 0.5);
        }

        @keyframes voiceWavePulse {
            0% { transform: scale(0.95); opacity: 0.8; }
            100% { transform: scale(1.22); opacity: 0; }
        }

        .voice-main-mic-btn {
            width: 84px;
            height: 84px;
            border-radius: 50%;
            background: linear-gradient(135deg, rgba(6, 182, 212, 0.25), rgba(6, 182, 212, 0.08));
            border: 2px solid #06b6d4 !important;
            color: #06b6d4 !important;
            font-size: 28px;
            display: grid;
            place-items: center;
            cursor: pointer;
            box-shadow: 0 0 20px rgba(6, 182, 212, 0.3);
            transition: all 0.2s ease;
            z-index: 2;
        }

        .voice-main-mic-btn:hover {
            transform: scale(1.05);
            box-shadow: 0 0 28px rgba(6, 182, 212, 0.5);
        }

        .voice-main-mic-btn.active {
            background: #06b6d4 !important;
            color: #000000 !important;
            box-shadow: 0 0 32px rgba(6, 182, 212, 0.75);
        }

        .voice-main-mic-btn.processing {
            background: rgba(245, 158, 11, 0.2) !important;
            border-color: #f59e0b !important;
            color: #f59e0b !important;
            box-shadow: 0 0 24px rgba(245, 158, 11, 0.4);
        }

        .voice-main-mic-btn.speaking {
            background: rgba(6, 182, 212, 0.25) !important;
            border-color: #06b6d4 !important;
            color: #06b6d4 !important;
            box-shadow: 0 0 30px rgba(6, 182, 212, 0.5);
        }

        .voice-main-mic-btn.error {
            background: rgba(239, 68, 68, 0.2) !important;
            border-color: #ef4444 !important;
            color: #ff5c5c !important;
            box-shadow: 0 0 24px rgba(239, 68, 68, 0.4);
        }

        /* --- Animated Waveform Bars for Speaking State --- */
        .voice-speaking-bars {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            height: 24px;
        }

        .voice-speaking-bars span {
            display: inline-block;
            width: 3px;
            height: 100%;
            background: currentColor;
            border-radius: 2px;
            animation: voiceBarAnim 0.8s ease-in-out infinite alternate;
        }

        .voice-speaking-bars span:nth-child(1) { animation-delay: 0.1s; }
        .voice-speaking-bars span:nth-child(2) { animation-delay: 0.3s; }
        .voice-speaking-bars span:nth-child(3) { animation-delay: 0.5s; }
        .voice-speaking-bars span:nth-child(4) { animation-delay: 0.2s; }
        .voice-speaking-bars span:nth-child(5) { animation-delay: 0.4s; }

        @keyframes voiceBarAnim {
            0% { height: 4px; }
            100% { height: 24px; }
        }

        .voice-hero-status {
            font-family: var(--agent-font-sans);
            font-size: 14px;
            font-weight: 700;
            color: #ffffff;
            letter-spacing: 0.5px;
            text-transform: uppercase;
        }

        .voice-hero-subtext {
            font-size: 12px;
            color: var(--agent-text-muted);
            text-align: center;
            margin: 0;
            max-width: 480px;
            line-height: 1.4;
        }

        /* --- Part 19: Voice Control Buttons --- */
        .voice-stage-controls {
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
            justify-content: center;
        }

        .btn-voice-action {
            display: inline-flex;
            align-items: center;
            gap: 7px;
            padding: 7px 14px;
            border-radius: var(--agent-radius-sm);
            font-size: 12px;
            font-family: var(--agent-font-mono);
            font-weight: 600;
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--agent-border) !important;
            color: #ffffff !important;
            cursor: pointer;
            transition: all 0.15s ease;
        }

        .btn-voice-action:hover {
            background: rgba(255, 255, 255, 0.1);
            border-color: var(--agent-border-hover) !important;
        }

        .btn-voice-action.danger {
            background: rgba(239, 68, 68, 0.12);
            border-color: rgba(239, 68, 68, 0.3) !important;
            color: #f87171 !important;
        }

        .btn-voice-action.danger:hover {
            background: rgba(239, 68, 68, 0.22);
        }

        /* Custom Hands-Free Switch */
        .voice-handsfree-pill {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid var(--agent-border);
            border-radius: var(--agent-radius-full);
            padding: 6px 12px;
            font-family: var(--agent-font-mono);
            font-size: 11.5px;
            color: var(--agent-text-muted);
            cursor: pointer;
            transition: all 0.15s ease;
            user-select: none;
        }

        .voice-handsfree-pill:hover {
            background: rgba(255, 255, 255, 0.08);
            color: #ffffff;
        }

        .voice-handsfree-pill input[type="checkbox"] {
            display: none !important;
        }

        .hf-slider {
            width: 28px;
            height: 16px;
            background: rgba(255, 255, 255, 0.2);
            border-radius: 999px;
            position: relative;
            transition: background-color 0.2s ease;
            display: inline-block;
        }

        .hf-slider::after {
            content: '';
            position: absolute;
            top: 2px;
            left: 2px;
            width: 12px;
            height: 12px;
            border-radius: 50%;
            background: #ffffff;
            transition: transform 0.2s cubic-bezier(0.16, 1, 0.3, 1);
        }

        .voice-handsfree-pill input:checked + .hf-slider {
            background: #06b6d4;
        }

        .voice-handsfree-pill input:checked + .hf-slider::after {
            transform: translateX(12px);
        }

        /* --- Voice Quick Suggestions --- */
        .voice-quick-prompts {
            display: flex;
            align-items: center;
            gap: 8px;
            flex-wrap: wrap;
            justify-content: center;
            max-width: 720px;
            padding: 4px 0;
        }

        .voice-quick-label {
            font-size: 11px;
            font-family: var(--agent-font-mono);
            color: var(--agent-text-subtle);
        }

        .voice-quick-chip {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid var(--agent-border) !important;
            color: var(--agent-text-muted) !important;
            padding: 4px 10px;
            border-radius: var(--agent-radius-full);
            font-size: 11.5px;
            cursor: pointer;
            transition: all 0.15s ease;
        }

        .voice-quick-chip:hover {
            background: rgba(255, 255, 255, 0.09);
            color: #ffffff !important;
            border-color: var(--agent-border-hover) !important;
        }

        /* --- Part 20 & 21: Dual Voice Cards --- */
        .voice-cards-grid {
            width: 100%;
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .voice-transcript-card, .voice-response-card {
            width: 100%;
            background: var(--agent-surface-card);
            border: 1px solid var(--agent-border);
            border-radius: var(--agent-radius-md);
            padding: 14px 16px;
            display: flex;
            flex-direction: column;
            gap: 8px;
            box-shadow: var(--agent-shadow-xs);
        }

        .voice-response-card {
            background: rgba(6, 182, 212, 0.06);
            border-color: rgba(6, 182, 212, 0.25);
        }

        .voice-card-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            font-size: 11px;
            font-family: var(--agent-font-mono);
            font-weight: 700;
            color: var(--agent-text-muted);
            letter-spacing: 0.5px;
        }

        .voice-transcript-mode {
            font-size: 9.5px;
            padding: 2px 6px;
            border-radius: var(--agent-radius-xs);
            background: rgba(255, 255, 255, 0.05);
            color: #06b6d4;
            text-transform: uppercase;
        }

        .voice-transcript-text {
            font-size: 13px;
            color: #ffffff;
            line-height: 1.45;
            min-height: 24px;
            max-height: 160px;
            overflow-y: auto;
        }

        .voice-response-text {
            font-size: 13px;
            color: #ffffff;
            line-height: 1.5;
            max-height: 200px;
            overflow-y: auto;
        }

        .btn-sm-stop-speak {
            background: rgba(239, 68, 68, 0.15);
            border: 1px solid rgba(239, 68, 68, 0.3) !important;
            color: #f87171 !important;
            padding: 3px 8px;
            border-radius: var(--agent-radius-xs);
            font-size: 10.5px;
            font-family: var(--agent-font-mono);
            cursor: pointer;
            transition: all 0.15s ease;
        }

        .btn-sm-stop-speak:hover {
            background: rgba(239, 68, 68, 0.25);
        }

        /* ==========================================================================
           PART 5: AGENT PERMISSION REQUIRED CARD
           ========================================================================== */
        .simba-action-card, .agent-confirm-card {
            background: rgba(18, 14, 8, 0.95);
            border: 1px solid rgba(245, 158, 11, 0.4);
            border-radius: var(--agent-radius-md);
            padding: 14px 16px;
            margin: 10px 0;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.55);
        }

        .agent-btn-confirm {
            background: var(--agent-accent) !important;
            color: #000000 !important;
            font-weight: 700 !important;
            font-family: var(--agent-font-mono) !important;
            border-radius: var(--agent-radius-xs) !important;
            padding: 6px 14px !important;
            font-size: 12px !important;
            cursor: pointer;
            transition: all 0.15s ease;
        }

        .agent-btn-confirm:hover {
            filter: brightness(1.1);
        }

        .agent-btn-cancel {
            background: rgba(255, 255, 255, 0.08) !important;
            border: 1px solid var(--agent-border) !important;
            color: #ffffff !important;
            font-family: var(--agent-font-mono) !important;
            border-radius: var(--agent-radius-xs) !important;
            padding: 6px 14px !important;
            font-size: 12px !important;
            cursor: pointer;
            transition: all 0.15s ease;
        }

        .agent-btn-cancel:hover {
            background: rgba(255, 255, 255, 0.14);
        }

        /* ==========================================================================
           ACTION DISCOVERY MODAL
           ========================================================================== */
        .simba-custom-modal-overlay {
            position: fixed;
            inset: 0;
            background: rgba(0, 0, 0, 0.72);
            backdrop-filter: blur(8px);
            z-index: 1060;
            display: grid;
            place-items: center;
            padding: 20px;
            animation: fadeInModal 0.2s ease-out;
        }

        .simba-custom-modal {
            background: rgba(12, 16, 26, 0.98);
            border: 1px solid var(--agent-border-strong);
            border-radius: var(--agent-radius-lg);
            width: 100%;
            max-width: 580px;
            box-shadow: var(--agent-shadow-lg);
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }

        .discovery-modal {
            max-width: 860px;
            max-height: 85vh;
        }

        .simba-modal-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 16px 20px;
            border-bottom: 1px solid var(--agent-border);
        }

        .simba-modal-title {
            font-family: var(--agent-font-sans);
            font-size: 14px;
            font-weight: 700;
            color: #ffffff;
            display: flex;
            align-items: center;
            gap: 8px;
            letter-spacing: 0.3px;
        }

        .discovery-target-chip {
            font-size: 10px;
            font-family: var(--agent-font-mono);
            font-weight: 700;
            padding: 2px 7px;
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--agent-border);
            border-radius: var(--agent-radius-full);
            color: rgba(255, 255, 255, 0.8);
            display: inline-flex;
            align-items: center;
            gap: 5px;
        }

        .discovery-modal-toolbar {
            padding: 12px 20px;
            border-bottom: 1px solid var(--agent-border);
            display: flex;
            flex-direction: column;
            gap: 10px;
            background: rgba(0, 0, 0, 0.15);
        }

        .discovery-modal-body {
            padding: 16px 20px;
            overflow-y: auto;
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
            gap: 12px;
            flex: 1;
        }

        .discovery-card {
            background: var(--agent-surface-card);
            border: 1px solid var(--agent-border);
            border-radius: var(--agent-radius-sm);
            padding: 12px 14px;
            display: flex;
            flex-direction: column;
            gap: 7px;
            transition: all 0.15s ease;
        }

        .discovery-card:hover {
            border-color: var(--agent-border-hover);
            transform: translateY(-1px);
        }

        .discovery-card-top {
            display: flex;
            align-items: flex-start;
            justify-content: space-between;
            gap: 8px;
        }

        .discovery-card-title {
            display: flex;
            align-items: center;
            gap: 7px;
            font-weight: 600;
            font-size: 12.5px;
            color: #ffffff;
            font-family: var(--agent-font-sans);
        }

        .discovery-badges-wrap {
            display: flex;
            align-items: center;
            gap: 4px;
            flex-wrap: wrap;
        }

        .discovery-badge {
            font-size: 9px;
            font-family: var(--agent-font-mono);
            font-weight: 700;
            padding: 1px 5px;
            border-radius: var(--agent-radius-xs);
            text-transform: uppercase;
        }

        .discovery-badge.cloud {
            background: var(--agent-success-soft);
            color: var(--agent-success);
            border: 1px solid var(--agent-success-border);
        }

        .discovery-badge.desktop {
            background: rgba(6, 182, 212, 0.12);
            color: #06b6d4;
            border: 1px solid rgba(6, 182, 212, 0.25);
        }

        .discovery-badge.offline {
            background: var(--agent-danger-soft);
            color: #f87171;
            border: 1px solid var(--agent-danger-border);
        }

        .discovery-badge.dangerous {
            background: var(--agent-warning-soft);
            color: #f59e0b;
            border: 1px solid var(--agent-warning-border);
        }

        .discovery-card-desc {
            font-size: 11px;
            color: var(--agent-text-muted);
            line-height: 1.4;
            flex-grow: 1;
        }

        .btn-use-discovered-tool {
            margin-top: auto;
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid var(--agent-border) !important;
            color: #ffffff !important;
            padding: 5px 10px;
            border-radius: var(--agent-radius-xs);
            font-size: 11px;
            font-family: var(--agent-font-mono);
            font-weight: 600;
            cursor: pointer;
            text-align: center;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
            transition: all 0.15s ease;
        }

        .btn-use-discovered-tool:hover {
            background: var(--agent-accent);
            color: #000000 !important;
            border-color: var(--agent-accent) !important;
        }

        .discovery-loading {
            grid-column: 1 / -1;
            text-align: center;
            padding: 36px 20px;
            color: var(--agent-text-muted);
        }

        .simba-modal-body {
            padding: 16px 20px;
            font-size: 12.5px;
            color: var(--agent-text);
            line-height: 1.5;
        }

        .simba-modal-footer {
            padding: 12px 20px;
            border-top: 1px solid var(--agent-border);
            display: flex;
            justify-content: flex-end;
            gap: 8px;
            background: rgba(0, 0, 0, 0.15);
        }

        .btn-modal-secondary {
            background: rgba(255, 255, 255, 0.06);
            border: 1px solid var(--agent-border) !important;
            color: #ffffff !important;
            padding: 6px 14px;
            border-radius: var(--agent-radius-xs);
            font-size: 12px;
            font-family: var(--agent-font-mono);
            cursor: pointer;
            transition: all 0.15s ease;
        }

        .btn-modal-secondary:hover {
            background: rgba(255, 255, 255, 0.12);
        }

        /* ==========================================================================
           PART 24-26: RESPONSIVE BREAKPOINTS (1920 to 375px)
           ========================================================================== */
        @media (max-width: 1024px) {
            .agent-status-grid {
                grid-template-columns: repeat(2, 1fr);
            }

            .agent-quick-grid {
                grid-template-columns: repeat(2, 1fr);
            }
        }

        @media (max-width: 768px) {
            .agent-workspace-wrapper, .voice-workspace-wrapper {
                padding: 14px 12px 28px;
                gap: 16px;
            }

            .agent-header-row, .voice-header-card {
                flex-direction: column;
                align-items: flex-start;
                gap: 12px;
            }

            .agent-header-right {
                width: 100%;
                justify-content: space-between;
            }

            .agent-system-strip {
                width: 100%;
                justify-content: space-between;
            }

            .agent-status-grid {
                grid-template-columns: 1fr;
            }

            .agent-quick-grid {
                grid-template-columns: 1fr;
            }

            .agent-history-drawer {
                width: 100vw;
                max-width: 100vw;
            }

            .simba-custom-modal {
                max-width: 95vw;
            }

            .voice-pipeline-card {
                overflow-x: auto;
                justify-content: flex-start;
            }

            .voice-visualizer-container {
                width: 110px;
                height: 110px;
            }

            .voice-main-mic-btn {
                width: 72px;
                height: 72px;
                font-size: 24px;
            }

            .composer-area {
                padding-bottom: max(12px, env(safe-area-inset-bottom));
            }
        }

        @media (max-width: 480px) {
            .agent-header-right {
                flex-direction: column;
                align-items: stretch;
            }

            .btn-agent-header-action {
                justify-content: center;
            }

            .agent-context-dropdown-wrap {
                justify-content: space-between;
            }

            .simba-select {
                max-width: 100%;
                flex-grow: 1;
            }
        }

        /* --- Part 35: Accessibility & Prefers-Reduced-Motion --- */
        @media (prefers-reduced-motion: reduce) {
            .agent-pulse-dot,
            .voice-pulse-dot,
            .voice-wave-ring,
            .voice-speaking-bars span {
                animation: none !important;
            }

            .agent-quick-card,
            .agent-status-card,
            .btn-voice-action,
            .voice-main-mic-btn,
            .btn-start-task {
                transition: none !important;
                transform: none !important;
            }

            .agent-history-drawer {
                animation: none !important;
            }
        }
    </style>'''

print("Length of new CSS block:", len(css_block))
