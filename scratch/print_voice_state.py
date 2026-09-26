import sys

sys.stdout.reconfigure(encoding='utf-8')

with open('templates/chat.html', 'r', encoding='utf-8', errors='ignore') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'function setVoiceState' in line or 'setVoiceState =' in line:
        print(f"setVoiceState at line {i+1}")
        for j in range(max(0, i-5), min(len(lines), i+60)):
            print(f"{j+1}: {lines[j]}", end="")
