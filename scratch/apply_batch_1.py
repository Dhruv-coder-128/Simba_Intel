import sys
import re

sys.stdout.reconfigure(encoding='utf-8')

with open('templates/chat.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 1. REMOVE LIGHTNING ICON FROM MODEL SELECTOR TRIGGER
target_cyber_select = '''                            <button type="button" class="cyber-select" id="cyberSelect" onclick="toggleModelDropdown(event)" aria-haspopup="listbox" aria-expanded="false" title="Select AI Model or Smart Routing Mode">
                                <span class="model-trigger-content">
                                    <span id="selectedIcon" class="model-trigger-icon">
                                        {% if selected_model == 'fast' or selected_model == 'nova-mind' %}
                                        {% elif selected_model == 'balanced' %}⚖
                                        {% elif selected_model == 'powerful' or selected_model == 'ox-alpha' %}
                                        {% elif selected_model == 'economical' %}
                                        {% elif selected_model == 'quantum-core' %}
                                        {% elif selected_model == 'sky-net' or selected_model == 'sky-net-mini' %}
                                        {% elif selected_model == 'image-studio' %}
                                        {% else %}{% endif %}
                                    </span>
                                    <span id="selectedText" class="model-trigger-name">'''

replacement_cyber_select = '''                            <button type="button" class="cyber-select" id="cyberSelect" onclick="toggleModelDropdown(event)" aria-haspopup="listbox" aria-expanded="false" title="Select AI Model or Smart Routing Mode">
                                <span class="model-trigger-content">
                                    <span id="selectedText" class="model-trigger-name">'''

if target_cyber_select in html:
    html = html.replace(target_cyber_select, replacement_cyber_select)
    print("[OK] Removed selectedIcon from cyberSelect trigger")
else:
    print("[FAIL] Could not find target_cyber_select")

# 2. REMOVE CSS RULES FOR SELECTED ICON
target_css_1 = '''            /* On desktop, show both text and icon */
            .cyber-select #selectedText {
                display: inline;
            }

            .cyber-select #selectedIcon {
                display: inline-flex;
            }'''

replacement_css_1 = '''            /* On desktop, show selected model name */
            .cyber-select #selectedText {
                display: inline;
            }'''

if target_css_1 in html:
    html = html.replace(target_css_1, replacement_css_1)
    print("[OK] Cleaned CSS rule 1 for selectedIcon")
else:
    print("[FAIL] Could not find target_css_1")

target_css_2 = '''.cyber-select #selectedText,
            .cyber-select #selectedIcon {
                display: none !important;
            }'''

replacement_css_2 = '''.cyber-select #selectedText {
                display: none !important;
            }'''

if target_css_2 in html:
    html = html.replace(target_css_2, replacement_css_2)
    print("[OK] Cleaned CSS rule 2 for selectedIcon")
else:
    print("[FAIL] Could not find target_css_2")

# 3. REMOVE SELECTED ICON JS LOGIC & ⚡ FALLBACK
target_js_select = '''                    const value = this.getAttribute("data-value");
                    const name = this.getAttribute("data-name") || this.querySelector('strong')?.innerText || value;
                    const icon = this.getAttribute("data-icon") || "⚡";

                    const hiddenInput = document.getElementById("model-selector");
                    const selectedText = document.getElementById("selectedText");
                    const selectedIcon = document.getElementById("selectedIcon");

                    if (hiddenInput) hiddenInput.value = value;
                    if (selectedText) selectedText.innerText = name;
                    if (selectedIcon) selectedIcon.innerText = icon;'''

replacement_js_select = '''                    const value = this.getAttribute("data-value");
                    const name = this.getAttribute("data-name") || this.querySelector('strong')?.innerText || value;

                    const hiddenInput = document.getElementById("model-selector");
                    const selectedText = document.getElementById("selectedText");

                    if (hiddenInput) hiddenInput.value = value;
                    if (selectedText) selectedText.innerText = name;'''

if target_js_select in html:
    html = html.replace(target_js_select, replacement_js_select)
    print("[OK] Cleaned cyberOption click listener in JS")
else:
    print("[FAIL] Could not find target_js_select")

target_sync_storage = '''                const selectedIcon = document.getElementById("selectedIcon");
                if (selectedText) selectedText.innerText = option.getAttribute("data-name") || option.querySelector('strong')?.innerText || option.innerText || targetModel;
                if (selectedIcon) selectedIcon.innerText = option.getAttribute("data-icon") || "⚡";'''

replacement_sync_storage = '''                if (selectedText) selectedText.innerText = option.getAttribute("data-name") || option.querySelector('strong')?.innerText || option.innerText || targetModel;'''

if target_sync_storage in html:
    html = html.replace(target_sync_storage, replacement_sync_storage)
    print("[OK] Cleaned syncModelSelectorFromStorage in JS")
else:
    print("[FAIL] Could not find target_sync_storage")

# 4. REMOVE REDUNDANT HEADER ROW ABOVE CHAT-FLOW AND RESTRUCTURE CHAT-FLOW
target_header_cf = '''                    {% if session_type == 'agent' and messages %}
                    <div class="agent-header-row" style="padding:12px 20px; border-bottom:1px solid rgba(255,255,255,0.08); background:rgba(12,16,26,0.6);">
                        <div class="agent-header-left">
                            <div class="agent-title-tag">
                                <span class="agent-pulse-dot"></span>
                                <span class="agent-mode-badge"><i class="fa-solid fa-robot"></i> AGENT MODE</span>
                                <span class="agent-lifecycle-badge status-idle" id="agentLifecycleBadgeHeader">
                                    <i class="fa-solid fa-circle-notch"></i>
                                    <span id="agentLifecycleTextHeader">IDLE</span>
                                </span>
                            </div>
                        </div>
                        <div class="agent-header-right">
                            <div class="agent-system-strip" role="status" aria-label="System status">
                                <span class="system-chip" title="Agent core ready">
                                    <span class="status-dot dot-online"></span>
                                    <span>Agent: <strong>Online</strong></span>
                                </span>
                                <span class="system-chip desktop-chip" onclick="togglePcAgentModal()" title="Desktop Agent bridge status (click to configure)">
                                    <span class="status-dot {% if is_pc_connected %}dot-online{% else %}dot-offline{% endif %}"></span>
                                    <span>Desktop: <strong>{% if is_pc_connected %}Connected{% else %}Offline{% endif %}</strong></span>
                                </span>
                                <span class="system-chip screen-chip" onclick="toggleScreenAwareness()" title="Desktop visual inspection status">
                                    <span class="status-dot {% if screen_awareness_enabled %}dot-online{% else %}dot-disabled{% endif %}"></span>
                                    <span>Screen: <strong>{% if screen_awareness_enabled %}Available{% else %}Disabled{% endif %}</strong></span>
                                </span>
                            </div>
                            <button type="button" class="btn-agent-header-action" onclick="openActionDiscoveryModal()" title="Browse all registered agent tools">
                                <i class="fa-solid fa-toolbox"></i>
                                <span>Tools</span>
                            </button>
                            <button type="button" class="btn-agent-header-action" onclick="toggleAgentTaskHistory()" title="View dedicated agent task execution history">
                                <i class="fa-solid fa-clock-rotate-left"></i>
                                <span>Task History</span>
                            </button>
                        </div>
                    </div>
                    {% endif %}

            <div id="chat-flow">
                {% if not messages %}
                {% if session_type == 'agent' %}'''

replacement_header_cf = '''            <div id="chat-flow">
                {% if session_type == 'agent' %}'''

if target_header_cf in html:
    html = html.replace(target_header_cf, replacement_header_cf)
    print("[OK] Removed redundant header row and opened chat-flow with agent check")
else:
    print("[FAIL] Could not find target_header_cf")

# 5. ASSISTANT MODE WRAPPER IN CHAT-FLOW
target_qc_start = '''                {% else %}
                <div class="welcome-container" id="qcHome">'''

replacement_qc_start = '''                {% else %}
                <!-- Assistant Mode: Conversation-First -->
                {% if not messages %}
                <div class="welcome-container" id="qcHome">'''

if target_qc_start in html:
    html = html.replace(target_qc_start, replacement_qc_start)
    print("[OK] Wrapped qcHome in Assistant Mode branch")
else:
    print("[FAIL] Could not find target_qc_start")

target_qc_end = '''                        if (timeEl) timeEl.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                        if (dateEl) dateEl.textContent = new Date().toLocaleDateString([], { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric' });
                    })();
                </script>
                {% endif %}
                {% endif %}

                {% for m in messages %}'''

replacement_qc_end = '''                        if (timeEl) timeEl.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                        if (dateEl) dateEl.textContent = new Date().toLocaleDateString([], { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric' });
                    })();
                </script>
                {% endif %}

                {% for m in messages %}'''

if target_qc_end in html:
    html = html.replace(target_qc_end, replacement_qc_end)
    print("[OK] Adjusted qcHome end tag in chat-flow")
else:
    print("[FAIL] Could not find target_qc_end")

target_cf_end = '''                    <div class="followup-suggestions"></div>
                </div>
                {% endif %}
                {% endfor %}
            </div>'''

replacement_cf_end = '''                    <div class="followup-suggestions"></div>
                </div>
                {% endif %}
                {% endfor %}
                {% endif %}
            </div>'''

if target_cf_end in html:
    html = html.replace(target_cf_end, replacement_cf_end)
    print("[OK] Closed Assistant Mode branch inside chat-flow")
else:
    print("[FAIL] Could not find target_cf_end")

# Write back
with open('templates/chat.html', 'w', encoding='utf-8') as f:
    f.write(html)

print("Batch 1 completed successfully!")
