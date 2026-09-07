with open('templates/chat.html', 'r', encoding='utf-8') as f:
    text = f.read()

import re

items = [
    'agent-workspace-wrapper',
    'agent-system-strip',
    'system-chip',
    'agent-context-dropdown-wrap',
    'simba-select',
    'btn-agent-header-action',
    'agent-status-card',
    'agent-card-action-btn',
    'agent-empty-task-card',
    'btn-start-task',
    'btn-task-control',
    'agent-step-checklist',
    'agent-checklist-item',
    'btn-more-tasks-link',
    'agent-quick-card',
    'agent-target-badge',
    'voice-workspace-wrapper',
    'voice-header-card',
    'voice-hero-stage',
    'voice-visualizer-container',
    'voice-main-mic-btn',
    'voice-stage-controls',
    'btn-voice-action',
    'voice-handsfree-pill',
    'voice-quick-chip',
    'voice-cards-grid',
    'voice-transcript-card',
    'voice-response-card',
]

for item in items:
    print(f"\n==================== {item} ====================")
    pattern = r'(\.' + item + r'[\s,\{][^\{]*\{[^\}]*\})'
    matches = re.findall(pattern, text)
    if matches:
        for m in matches[:2]:
            print(m.strip()[:200])
    else:
        print("NO EXACT CSS RULE FOUND!")
