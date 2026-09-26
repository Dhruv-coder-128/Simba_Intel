import sys

sys.stdout.reconfigure(encoding='utf-8')

with open('templates/chat.html', 'r', encoding='utf-8', errors='ignore') as f:
    text = f.read()

import re

agent_css = len(re.findall(r'\.agent-[a-zA-Z0-9_-]+', text))
voice_css = len(re.findall(r'\.voice-[a-zA-Z0-9_-]+', text))

print(f"Agent CSS rules count: {agent_css}")
print(f"Voice CSS rules count: {voice_css}")
