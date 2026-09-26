import sys

sys.stdout.reconfigure(encoding='utf-8')

with open('templates/chat.html', 'r', encoding='utf-8', errors='ignore') as f:
    text = f.read()

import re

for fn in ['setAgentLifecycleStatus', 'executeQuickTask', 'toggleVoiceAgentListening', 'handleVoiceCommand', 'executePlanApproved', 'stopCurrentAgentTask']:
    matches = [m.start() for m in re.finditer(rf'\b{fn}\b', text)]
    print(f"Function {fn}: {len(matches)} occurrences")
    for pos in matches[:3]:
        line_num = text[:pos].count('\n') + 1
        print(f"  Line {line_num}: {text[pos-50:pos+100].strip()}")
