import sys

sys.stdout.reconfigure(encoding='utf-8')

with open('templates/chat.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Verify key target anchors exist
targets = [
    '<button type="button" class="topbar-cmd-btn"',
    '{% if session_type == \'agent\' and messages %}',
    '<div id="chat-flow">',
    '{% if not messages %}',
    '<div class="agent-workspace agent-workspace-wrapper" id="agentWorkspace">',
    '{% elif session_type == \'voice\' %}',
    '<div class="voice-workspace voice-workspace-wrapper" id="voiceWorkspace">',
    '{% else %}\n                <div class="welcome-container" id="qcHome">',
    'if (timeEl) timeEl.textContent = new Date().toLocaleTimeString',
    '<span id="selectedIcon" class="model-trigger-icon">',
    'const icon = this.getAttribute("data-icon") || "⚡";',
    'async function sendQuery(event) {',
    'window.executeQuickTask = function(promptText) {',
    'window.initVoiceAgent = function() {',
]

for t in targets:
    pos = content.find(t)
    print(f"Target '{t[:40]}...': found={pos != -1} (pos={pos})")
