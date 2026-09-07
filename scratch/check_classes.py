with open('templates/chat.html', 'r', encoding='utf-8') as f:
    text = f.read()

pos_style_end = text.find('</style>')
css_text = text[:pos_style_end]

classes_to_check = [
    'simba-select',
    'agent-context-dropdown-wrap',
    'agent-card-action-btn',
    'btn-start-task',
    'btn-task-control',
    'agent-plan-preview-box',
    'btn-execute-plan',
    'agent-step-checklist',
    'agent-step',
    'agent-checklist-item',
    'btn-more-tasks-link',
    'btn-voice-action',
    'voice-handsfree-pill',
    'voice-quick-chip',
    'btn-sm-stop-speak',
    'btn-agent-header-action',
    'system-chip',
    'agent-target-badge',
    'agent-status-card',
    'agent-empty-task-card',
    'agent-active-task-card',
    'agent-technical-details',
    'agent-quick-card',
    'voice-hero-stage',
    'voice-cards-grid',
    'voice-transcript-card',
    'voice-response-card',
    'voice-stage-controls',
]

print("=== CHECKING CSS DEFINITIONS IN <style> ===")
for cls in classes_to_check:
    found = (f'.{cls}' in css_text) or (f'#{cls}' in css_text)
    print(f"{cls:30s}: {'FOUND' if found else 'MISSING IN CSS!'}")
