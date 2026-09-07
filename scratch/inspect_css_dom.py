import re

with open('templates/chat.html', 'r', encoding='utf-8') as f:
    text = f.read()

terms = [
    'agentWorkspace', 'voiceWorkspace', 'agentContextSelect', 
    'agentEmptyTaskCard', 'agentActiveTaskCard', 'voiceAutoListenToggle',
    'agentTaskHistoryDrawer', 'actionDiscoveryModal'
]
for term in terms:
    m = re.search(r'id=[\"\']' + term + r'[\"\']', text)
    if m:
        l = text[:m.start()].count('\n') + 1
        print(f'{term}: line {l}')
    else:
        print(f'{term}: NOT FOUND')

print("\n--- Checking CSS Rules for Agent & Voice ---")
# Check where agent styles start in <style>
pos = text.find('SIMBA_INTEL AGENT MODE HUD & EXECUTION WORKSPACE')
if pos != -1:
    line_start = text[:pos].count('\n') + 1
    print(f"Found Agent Mode HUD styles around line {line_start}")
else:
    pos2 = text.find('.agent-workspace-wrapper')
    if pos2 != -1:
        line_start = text[:pos2].count('\n') + 1
        print(f"Found .agent-workspace-wrapper around line {line_start}")
    else:
        print("Agent workspace wrapper styles not found by exact string!")

# Check voice styles in <style>
pos_voice = text.find('VOICE AGENT WORKSPACE')
if pos_voice != -1:
    line_voice = text[:pos_voice].count('\n') + 1
    print(f"Found Voice styles around line {line_voice}")
