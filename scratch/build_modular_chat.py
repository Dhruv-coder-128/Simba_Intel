import os

# Create templates/chat directory if it doesn't exist
os.makedirs('templates/chat', exist_ok=True)

with open('templates/chat.html', 'r', encoding='utf-8') as f:
    lines = f.readlines()

print(f"Total lines in original chat.html: {len(lines)}")

# 1. Styles: lines 17 to 11672 (0-indexed: 16 to 11672)
styles_content = "".join(lines[16:11672])

# Add extra styling for voice mode and barge-in
extra_styles = """
/* Voice Mode Clean Cockpit - Hide bottom text composer and chat blocks */
body[data-session-type="voice"] #input-wrapper,
body[data-session-type="voice"] #btnJumpToLatest,
.voice-workspace-active #input-wrapper {
    display: none !important;
}

/* Ensure voice cards have smooth transitions */
.voice-feed-card {
    background: rgba(15, 23, 42, 0.65);
    border: 1px solid rgba(6, 182, 212, 0.2);
    border-radius: 10px;
    padding: 12px 14px;
    margin-bottom: 10px;
    transition: border-color 0.2s, background 0.2s;
}
.voice-feed-card:hover {
    border-color: rgba(6, 182, 212, 0.45);
    background: rgba(15, 23, 42, 0.85);
}
"""

styles_with_extra = styles_content.replace('    </style>', extra_styles + '\n    </style>')
with open('templates/chat/styles.html', 'w', encoding='utf-8') as f:
    f.write(styles_with_extra)
print("Wrote templates/chat/styles.html")

# 2. Modals: top overlays (lines 11708 to 11831, 0-indexed: 11707 to 11831)
# PLUS bottom drawers and modals (lines 24394 to 24535, 0-indexed: 24394 to 24535)
top_modals = "".join(lines[11707:11831])
bottom_modals = "".join(lines[24394:24535])

modals_content = top_modals + "\n" + bottom_modals
with open('templates/chat/modals.html', 'w', encoding='utf-8') as f:
    f.write(modals_content)
print("Wrote templates/chat/modals.html")

# 3. Sidebar: lines 11842 to 12104 (0-indexed: 11841 to 12104)
sidebar_content = "".join(lines[11841:12104])
with open('templates/chat/sidebar.html', 'w', encoding='utf-8') as f:
    f.write(sidebar_content)
print("Wrote templates/chat/sidebar.html")

# 4. Agent Workspace: lines 12153 to 12653 (0-indexed: 12152 to 12653)
agent_ws_content = "".join(lines[12152:12653])

# Fix: hide bridgeCommandPill when is_pc_connected is True in template
agent_ws_fixed = agent_ws_content.replace(
    '<div class="bridge-command-ribbon" id="bridgeCommandPill">',
    '<div class="bridge-command-ribbon" id="bridgeCommandPill" {% if is_pc_connected %}style="display:none;"{% endif %}>'
)
agent_ws_fixed = agent_ws_fixed.replace(
    '<span class="bridge-beacon {% if is_pc_connected %}online{% endif %}"></span>',
    '<span class="bridge-beacon {% if is_pc_connected %}online{% endif %}" id="bridgeBeaconDot"></span>'
)
agent_ws_fixed = agent_ws_fixed.replace(
    '{% if is_pc_connected %}\n                                    <i class="fa-brands fa-windows"></i>\n                                    {% else %}\n                                    <i class="fa-solid fa-tower-broadcast"></i>\n                                    {% endif %}',
    '<i class="{% if is_pc_connected %}fa-brands fa-windows{% else %}fa-solid fa-tower-broadcast{% endif %}" id="bridgeBeaconIcon"></i>'
)

with open('templates/chat/agent_workspace.html', 'w', encoding='utf-8') as f:
    f.write(agent_ws_fixed)
print("Wrote templates/chat/agent_workspace.html")

# 5. Voice Workspace: lines 12655 to 12869 (0-indexed: 12654 to 12869)
voice_ws_content = "".join(lines[12654:12869])

# Fix: Populate voice feed with past messages from session so history persists!
voice_feed_replacement = """                    <div class="voice-feed-list" id="voiceFeedList">
                        {% if messages %}
                        {% for m in messages %}
                        <div class="voice-feed-card">
                            <div class="feed-card-header">
                                <div style="display:flex; align-items:center; gap:8px;">
                                    <span class="feed-tag info"><i class="fa-regular fa-comment-dots"></i> QUERY</span>
                                    <span class="feed-time">{{ m.timestamp|default:"" }}</span>
                                </div>
                                <div class="feed-card-actions">
                                    <button type="button" class="btn-feed-action" onclick="simbaSpeak('{{ m.ai_response|escapejs }}')" title="Replay voice audio">
                                        <i class="fa-solid fa-volume-high"></i>
                                    </button>
                                    <button type="button" class="btn-feed-action" onclick="copyVoiceResponseText(this)" title="Copy text">
                                        <i class="fa-regular fa-copy"></i>
                                    </button>
                                </div>
                            </div>
                            <div class="feed-user-query">
                                <i class="fa-solid fa-microphone"></i>
                                <span>{{ m.user_query }}</span>
                            </div>
                            <div class="feed-simba-resp">
                                <i class="fa-solid fa-robot"></i>
                                <span class="feed-resp-content">{{ m.ai_response }}</span>
                            </div>
                        </div>
                        {% endfor %}
                        {% else %}
                        <div class="voice-feed-empty" id="voiceFeedEmpty">
                            <i class="fa-solid fa-headset" style="font-size:24px; opacity:0.3; margin-bottom:8px;"></i>
                            <div>Spoken conversation turns will be recorded here with instant audio replay.</div>
                        </div>
                        {% endif %}
                    </div>"""

old_voice_feed = """                    <div class="voice-feed-list" id="voiceFeedList">
                        <div class="voice-feed-empty" id="voiceFeedEmpty">
                            <i class="fa-solid fa-headset" style="font-size:24px; opacity:0.3; margin-bottom:8px;"></i>
                            <div>Spoken conversation turns will be recorded here with instant audio replay.</div>
                        </div>
                    </div>"""

voice_ws_fixed = voice_ws_content.replace(old_voice_feed, voice_feed_replacement)

with open('templates/chat/voice_workspace.html', 'w', encoding='utf-8') as f:
    f.write(voice_ws_fixed)
print("Wrote templates/chat/voice_workspace.html")

# 6. Scripts: lines 13723 to 24393 (0-indexed: 13722 to 24393)
scripts_content = "".join(lines[13722:24393])

with open('templates/chat/scripts.html', 'w', encoding='utf-8') as f:
    f.write(scripts_content)
print("Wrote templates/chat/scripts.html")
