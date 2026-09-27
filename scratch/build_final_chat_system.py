with open('templates/chat.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 1. Assistant workspace (lines 12872 to 13443, 0-indexed: 12871 to 13443)
assistant_ws_content = "".join(lines[12871:13443])
with open('templates/chat/assistant_workspace.html', 'w', encoding='utf-8') as f:
    f.write(assistant_ws_content)
print("Wrote templates/chat/assistant_workspace.html")

# 2. Composer (lines 13453 to 13720, 0-indexed: 13452 to 13720)
composer_content = "".join(lines[13452:13720])
with open('templates/chat/composer.html', 'w', encoding='utf-8') as f:
    f.write(composer_content)
print("Wrote templates/chat/composer.html")

# 3. Create the clean, modular templates/chat.html
modular_chat_html = """{% load static %}
<!DOCTYPE html>
<html lang="en" data-theme="{{ profile.theme|default:'cyberpunk' }}"
    data-notifications="{{ profile.notifications_enabled|yesno:'on,off' }}" data-accent="{{ profile.accent_override }}"
    data-density="{{ profile.density|default:'comfortable' }}" data-radius="{{ profile.card_radius|default:'rounded' }}"
    data-animation="{{ profile.animation_level|default:'full' }}"
    data-glass="{{ profile.glass_intensity|default:'medium' }}">

<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Simba Intel</title>
    <link rel="icon" type="image/png" href="{% static 'favicon2.png' %}">

    {% include "chat/styles.html" %}

    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500&family=Outfit:wght@300;400;600&display=swap" rel="stylesheet">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
    <!-- Deferred third-party libraries for maximum initial render speed -->
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js" defer></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/dompurify/3.1.6/purify.min.js" defer></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/themes/prism-tomorrow.min.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/prism.min.js" defer></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.11/katex.min.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/KaTeX/0.16.11/katex.min.js" defer></script>
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js" defer></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/plugins/autoloader/prism-autoloader.min.js" defer></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/plugins/line-numbers/prism-line-numbers.min.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/prism/1.29.0/plugins/line-numbers/prism-line-numbers.min.js" defer></script>
</head>

<body data-session-type="{{ session_type|default:'assistant' }}">

    <div id="simbaToastContainer"></div>
    <div id="toast-container"></div>

    <!-- Modals & Overlays (Lockdown, Image Viewer, Discovery, Shortcuts, Desktop Agent) -->
    {% include "chat/modals.html" %}

    <input type="hidden" id="csrf-token" value="{{ csrf_token }}">
    <!-- Mobile overlay -->
    <div id="mobile-overlay" class="mobile-overlay"></div>

    <!-- Workspace Sidebar Navigation -->
    {% include "chat/sidebar.html" %}

    <div id="workspace">
        <!-- Top Navigation Bar -->
        <header class="workspace-topbar">
            <div class="topbar-left">
                <button id="mobile-menu-btn" class="mobile-menu-btn" aria-label="Toggle navigation drawer"
                    type="button">
                    <i class="fa-solid fa-bars"></i>
                </button>
                <nav class="workspace-mode-nav" aria-label="Workspace Modes">
                    <a href="/?type=assistant"
                        class="mode-tab {% if session_type == 'assistant' or not session_type %}active{% endif %}"
                        title="Conversational AI & Vision"><i class="fa-solid fa-message"></i>
                        <span>Assistant</span></a>
                    <a href="/?type=agent" class="mode-tab {% if session_type == 'agent' %}active{% endif %}"
                        title="Autonomous System & Desktop Agent"><i class="fa-solid fa-robot"></i> <span>Agent
                            Mode</span></a>
                    <a href="/?type=voice" class="mode-tab {% if session_type == 'voice' %}active{% endif %}"
                        title="Voice Synthesis & Studio"><i class="fa-solid fa-microphone"></i> <span>Voice
                            Agent</span></a>
                    <a href="{% url 'analytics_dashboard' %}" class="mode-tab" title="Intelligence & Resource Analytics"
                        onclick="saveChatStateBeforeLeaving()"><i class="fa-solid fa-chart-line"></i>
                        <span>Analytics</span></a>
                    <a href="{% url 'profile_settings' %}" class="mode-tab" title="System Settings"
                        onclick="saveChatStateBeforeLeaving()"><i class="fa-solid fa-gear"></i>
                        <span>Settings</span></a>
                </nav>
                {% if current_session %}
                <div class="topbar-session-badge" title="{{ current_session.title }}">
                    <i class="fa-solid fa-terminal"></i>
                    <span>{{ current_session.title|truncatechars:28 }}</span>
                </div>
                {% endif %}
            </div>
            <div class="topbar-right">
                <button type="button" class="topbar-cmd-btn" onclick="openCommandPalette()"
                    title="Command Palette (Ctrl+K)">
                    <i class="fa-solid fa-terminal"></i>
                    <span>Commands</span>
                    <kbd>Ctrl+K</kbd>
                </button>
            </div>
        </header>

        <!-- Dynamic Main Chat & Mode Flow Container -->
        <div id="chat-flow">
            {% if session_type == 'agent' %}
                {% include "chat/agent_workspace.html" %}
            {% elif session_type == 'voice' %}
                {% include "chat/voice_workspace.html" %}
            {% else %}
                {% include "chat/assistant_workspace.html" %}
            {% endif %}
        </div>

        <!-- Floating Jump to Latest Pill Button -->
        <button type="button" id="btnJumpToLatest" class="jump-to-latest-btn" onclick="scrollToLatestMessage(true)" aria-label="Jump to latest message">
            <i class="fa-solid fa-arrow-down"></i>
            <span id="jumpToLatestText">Jump to latest</span>
        </button>

        <!-- Command Composer Input Bar (Suppressed in Voice Mode) -->
        {% if session_type != 'voice' %}
            {% include "chat/composer.html" %}
        {% endif %}
    </div>

    <!-- Client-Side Runtime Engine Scripts -->
    {% include "chat/scripts.html" %}
</body>

</html>
"""

# Backup original chat.html first
with open('templates/chat.html.bak', 'w', encoding='utf-8') as f:
    f.writelines(lines)
print("Created backup at templates/chat.html.bak")

# Write the new modular chat.html
with open('templates/chat.html', 'w', encoding='utf-8') as f:
    f.write(modular_chat_html)
print("Successfully generated clean modular templates/chat.html!")
