import sys

sys.stdout.reconfigure(encoding='utf-8')

with open('templates/chat.html', 'r', encoding='utf-8', errors='ignore') as f:
    text = f.read()

import re

print("--- FETCH / ASK_AI CALLS IN SCRIPT ---")
for m in re.finditer(r'(fetch\([^\)]*ask[^\)]*\))', text):
    start = max(0, m.start() - 100)
    end = min(len(text), m.end() + 200)
    print("MATCH:\n", text[start:end])
    print("="*40)
