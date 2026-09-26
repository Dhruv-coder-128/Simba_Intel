import sys

sys.stdout.reconfigure(encoding='utf-8')

with open('templates/chat.html', 'r', encoding='utf-8', errors='ignore') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'id="agentWorkspace"' in line or "id='agentWorkspace'" in line:
        print(f"agentWorkspace begins around line {i+1}")
    if 'id="voiceWorkspace"' in line or "id='voiceWorkspace'" in line:
        print(f"voiceWorkspace begins around line {i+1}")
    if 'id="workspace"' in line or "id='workspace'" in line:
        print(f"workspace begins around line {i+1}")
