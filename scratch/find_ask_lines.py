import sys

sys.stdout.reconfigure(encoding='utf-8')

with open('templates/chat.html', 'r', encoding='utf-8', errors='ignore') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if 'fetch("/ask_ai/"' in line or "fetch('/ask_ai/'" in line:
        print(f"fetch /ask_ai/ at line {i+1}")
